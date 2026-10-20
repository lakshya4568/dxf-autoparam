"""Gemini on Vertex AI, configured the way the Aagento sidecar is — from the environment or gcloud.

    GOOGLE_CLOUD_PROJECT (or GCLOUD_PROJECT / GCP_PROJECT, else `gcloud config get-value project`)
    VERTEX_LOCATION (or GOOGLE_CLOUD_LOCATION; default "global")
    VERTEX_MODEL (or GEMINI_MODEL; default "gemini-3.8-flash"), thinking VERTEX_THINKING_LEVEL (default "high")
    VERTEX_FALLBACK_MODEL (default "gemini-3.7-flash", thinking VERTEX_FALLBACK_THINKING_LEVEL "high") — used when
        the primary is out of capacity or past its deadline (429 / 503 / 504)
    VERTEX_EXPLICIT_CACHE (default on; "0" turns it off), VERTEX_CACHE_TTL_S (default 1200)
    VERTEX_TIMEOUT_MS (default 600000) — also the server's deadline: shorter makes long thinking end in a 504
    VERTEX_STEP_TIMEOUT_MS (default 240000) — one agent step's deadline (steps answer in seconds to a minute; a
        call that hangs past it — a stalled shared pool — is retried, then the fallback model takes over)
    VERTEX_IDLE_S (default 180) — a streamed answer that sends nothing for this long is cut and retried
    credentials: Application Default Credentials (`gcloud auth application-default login`)

Nothing is hardcoded. Two caches, for two different things:
  • answers on disk (.cache/ai/), keyed by a hash of everything sent (model and thinking level included): asking
    the same question about the same drawing twice costs nothing;
  • a Vertex EXPLICIT prompt cache for the part of the request that repeats within one run — the system prompt,
    the pictures, the knowledge and the CAD JSON. The first call creates it, each repair round sends only its own
    rejection list against it (cached tokens are billed at a discount), and it is deleted when the run ends.
Every call's tokens (and how many were served from the prompt cache) are logged in .cache/ai/usage.jsonl.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

CACHE = Path(".cache") / "ai"
# Below this many prefix tokens Vertex refuses an explicit cache (the same floor aagento-bridge's sidecar uses
# for 3.8 Flash); a shorter request is simply sent whole.
MIN_CACHE_TOKENS = 6144
IMAGE_TOKENS = 1300  # rough cost of one drawing picture, for that estimate only


@dataclass
class VertexConfig:
    project: str
    location: str
    model: str
    thinking: str  # low | medium | high
    thinking_budget: int | None = None  # thinking tokens budget, or None for dynamic/model default
    fallback_model: str = ""
    fallback_thinking: str = "high"
    fallback_thinking_budget: int | None = None
    explicit_cache: bool = True
    cache_ttl_s: int = 1200
    max_output_tokens: int = 65536  # thinking counts against it: high thinking on a big drawing needs room


def load_env_file(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# The models a person can pick between for a run (the page's model picker). Each is run at the thinking level named here;
# `fallback` is what takes over when it is out of capacity ("" = none: a model that was chosen on purpose is never swapped
# for a cheaper one behind the person's back, the run fails visibly instead). The default is the env's model.
MODEL_CHOICES: list[dict] = [
    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash · high", "thinking": "high", "fallback": None},  # None = the env's fallback
    {"id": "gemini-4-argon", "label": "Gemini 4 Argon · high (premium)", "thinking": "high", "fallback": "",
     "explicit_cache": False,
     # USD per million tokens, as the owner gave them (introductory, through 2026-11-30; cached ≈ 95% off; implicit caching only)
     "price": {"input": 2.0, "cached": 0.10, "output": 10.0, "until": "2026-11-30"}},  # Vertex answers 400 "does not support explicit context caching" (probed 2026-10-13)
]


# A model reached through the gateway (ai/gateway.py): same agent session, another provider. Its id is "gateway:<gateway id>" so the ledger
# and the Cost tab keep it apart from the same model called on Vertex directly; the gateway reports each call's cost itself.
MODEL_CHOICES.append({"id": "gateway:gemini-4-argon", "label": "Gemini 4 Argon · high (via gateway)", "thinking": "high", "fallback": "",
                      "provider": "gateway", "gateway_model": "gemini-4-argon", "explicit_cache": False})


def model_choices() -> dict:
    """What the picker offers, and which is the default (the environment's model; it is listed even when it is not in the table)."""
    load_env_file()
    default = os.environ.get("VERTEX_MODEL") or os.environ.get("GEMINI_MODEL") or MODEL_CHOICES[0]["id"]
    gateway_ok = bool(os.environ.get("EXPLABS_API_KEY"))  # a gateway model is offered only when its key is set
    models = [{k: m[k] for k in ("id", "label", "thinking")} for m in MODEL_CHOICES if m.get("provider") != "gateway" or gateway_ok]
    if default not in {m["id"] for m in models}:
        models.insert(0, {"id": default, "label": f"{default} · {os.environ.get('VERTEX_THINKING_LEVEL', 'high')}", "thinking": os.environ.get("VERTEX_THINKING_LEVEL", "high")})
    return {"default": default, "models": models}


class GeminiUnavailable(RuntimeError):
    """Every model in the plan was out of capacity, past its deadline, or gave no usable answer."""


class GeminiStopped(RuntimeError):
    """The person stopped the run."""


@dataclass
class Reply:
    """One streamed answer: the JSON text, the model's thought summaries, the last usage and finish reason."""

    text: str
    thoughts: list[str]
    usage_metadata: object
    finish: str


class Stalled(TimeoutError):
    """Vertex sent nothing for too long (a stalled shared pool): the attempt is abandoned and retried."""


def _pumped(produce, on_item, idle_s: float, stop, what: str) -> None:
    """Run a blocking producer on a worker thread and hand its items over here, so a stall or the person's Stop is
    noticed within a fraction of a second instead of after the HTTP read timeout (10 minutes). `produce(put)` calls
    put(item) per item. Raises Stalled after `idle_s` with no item, GeminiStopped on stop, or the producer's error."""
    q: queue.Queue = queue.Queue()
    abandoned = threading.Event()

    def run():
        try:
            produce(lambda item: abandoned.is_set() or q.put(("item", item)))
            q.put(("end", None))
        except Exception as exc:  # noqa: BLE001 — not swallowed: re-raised in the caller's thread
            q.put(("err", exc))

    threading.Thread(target=run, daemon=True, name=f"vertex-{what}").start()
    last = time.monotonic()
    try:
        while True:
            if stop and stop():
                raise GeminiStopped("stopped by the person")
            try:
                kind, val = q.get(timeout=0.2)
            except queue.Empty:
                if time.monotonic() - last > idle_s:
                    raise Stalled(f"{what}: no reply from Vertex for {idle_s:.0f} s") from None
                continue
            last = time.monotonic()
            if kind == "end":
                return
            if kind == "err":
                raise val
            on_item(val)
    finally:
        abandoned.set()  # a stalled thread ends on its own HTTP timeout; nothing it sends later is used


def _stream(client, model: str, contents, config, on_event, stop=None) -> Reply:
    """Stream one answer. Thought summaries are passed on as they arrive (the person watches the model work).
    The person's Stop and a stall (nothing streamed for VERTEX_IDLE_S) end it at once."""
    text, thoughts, state = [], [], {"um": None, "finish": "UNKNOWN"}

    def produce(put):
        stream = client.models.generate_content_stream(model=model, contents=contents, config=config)
        try:
            for chunk in stream:
                put(chunk)
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()

    def take(chunk):
        state["um"], state["finish"] = _take(chunk, text, thoughts, on_event, state["um"], state["finish"])

    _pumped(produce, take, float(os.environ.get("VERTEX_IDLE_S", "180")), stop, model)
    return Reply("".join(text), thoughts, state["um"], state["finish"])


def _take(chunk, text: list[str], thoughts: list[str], on_event, um, finish):
    """One streamed message: answer text, thought summaries, usage, finish reason."""
    um = getattr(chunk, "usage_metadata", None) or um
    for cand in getattr(chunk, "candidates", None) or []:
        fr = getattr(cand, "finish_reason", None)
        if fr is not None:
            finish = getattr(fr, "name", None) or str(fr)
        for part in getattr(getattr(cand, "content", None), "parts", None) or []:
            if not getattr(part, "text", None):
                continue
            if getattr(part, "thought", False):
                thoughts.append(part.text)
                if on_event:
                    on_event({"kind": "thought", "text": part.text})
            else:
                text.append(part.text)
    return um, finish


def _read(reply: Reply, schema) -> dict | None:
    """The structured answer, or None when the reply is not complete, valid JSON (cut off, blocked, empty)."""
    from pydantic import ValidationError

    try:
        return schema.model_validate(json.loads(reply.text or "")).model_dump()
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
        return None


def _tokens(reply: Reply) -> dict:
    um = reply.usage_metadata
    return {"input_tokens": getattr(um, "prompt_token_count", 0) or 0, "output_tokens": getattr(um, "candidates_token_count", 0) or 0,
            "thinking_tokens": getattr(um, "thoughts_token_count", 0) or 0,
            # input tokens served from a prompt cache (explicit, or Vertex's implicit one), billed at a discount
            "vertex_cached_tokens": getattr(um, "cached_content_token_count", 0) or 0}


def _wait(seconds: float, stop) -> None:
    """A back-off the person can cut short."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if stop and stop():
            raise GeminiStopped("stopped by the person")
        time.sleep(min(0.2, end - time.monotonic()) if end > time.monotonic() else 0)


def _log(entry: dict) -> None:
    with open(CACHE / "usage.jsonl", "a") as f:
        f.write(json.dumps({**entry, "at": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")


def config(model: str | None = None) -> VertexConfig:
    """The environment's configuration; `model` (one of MODEL_CHOICES) is the person's pick for this run and brings its own thinking level and fallback."""
    load_env_file()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if not project:
        try:
            project = subprocess.run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True, timeout=20, check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            project = ""
    if not project:
        raise RuntimeError("No Google Cloud project: set GOOGLE_CLOUD_PROJECT in .env or run `gcloud config set project <id>`.")
    raw_budget = os.environ.get("VERTEX_THINKING_BUDGET") or os.environ.get("VERTEX_THINKING_TOKENS")
    thinking_level = os.environ.get("VERTEX_THINKING_LEVEL", "high")
    thinking_budget = int(raw_budget) if raw_budget and raw_budget.strip().lstrip("-").isdigit() else None
    if thinking_level.isdigit():
        thinking_budget = int(thinking_level)
        thinking_level = "high"
    fallback_level = os.environ.get("VERTEX_FALLBACK_THINKING_LEVEL", "high")
    fallback_budget = thinking_budget
    if fallback_level.isdigit():
        fallback_budget = int(fallback_level)
        fallback_level = "high"
    cfg = VertexConfig(
        project=project,
        location=os.environ.get("VERTEX_LOCATION") or os.environ.get("GOOGLE_CLOUD_LOCATION") or "global",
        model=os.environ.get("VERTEX_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash",
        thinking=thinking_level,
        thinking_budget=thinking_budget,
        fallback_model=os.environ.get("VERTEX_FALLBACK_MODEL", "gemini-3.7-flash"),
        fallback_thinking=fallback_level,
        fallback_thinking_budget=fallback_budget,
        explicit_cache=os.environ.get("VERTEX_EXPLICIT_CACHE", "1") != "0",
        cache_ttl_s=int(os.environ.get("VERTEX_CACHE_TTL_S", "1200")),
        max_output_tokens=int(os.environ.get("VERTEX_MAX_OUTPUT_TOKENS", "65536")),
    )
    if model:
        choice = next((m for m in MODEL_CHOICES if m["id"] == model), None)
        if choice is None:
            raise ValueError(f"unknown model {model!r}: choose one of {[m['id'] for m in MODEL_CHOICES]}")
        cfg.model, cfg.thinking = choice["id"], choice["thinking"]
        if "thinking_budget" in choice:
            cfg.thinking_budget = choice["thinking_budget"]
        if choice.get("explicit_cache") is False:
            cfg.explicit_cache = False
        if choice["fallback"] is not None:
            cfg.fallback_model = choice["fallback"]
        if cfg.fallback_model == cfg.model:
            cfg.fallback_model = ""
    return cfg


def _thinking_config(thinking: str | int | None, budget: int | None = None):
    """Build types.ThinkingConfig with thinking_level and thinking_budget (thinking tokens)."""
    from google.genai import types

    budget_val = budget
    level_val = thinking
    if isinstance(thinking, int) or (isinstance(thinking, str) and thinking.isdigit()):
        budget_val = int(thinking)
        level_val = "high"
    kw = {"include_thoughts": True}
    if level_val:
        kw["thinking_level"] = level_val
    if budget_val is not None:
        kw["thinking_budget"] = budget_val
    return types.ThinkingConfig(**kw)


def _transient(exc: Exception) -> bool:
    """Out of capacity, overloaded, or past its deadline: worth a retry and then the fallback model."""
    code = getattr(exc, "code", None)
    if code in (429, 500, 503, 504):
        return True
    if isinstance(exc, (Stalled, httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    text = str(exc)
    return isinstance(exc, TimeoutError) or any(k in text for k in ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "DEADLINE", "timed out", "Timeout"))


class Gemini:
    def __init__(self, cfg: VertexConfig | None = None, client=None):
        self.cfg = cfg or config()
        if client is None:
            from google import genai
            from google.genai import types

            # The SDK sends this as the SERVER deadline too (X-Server-Timeout): a call that thinks longer is cut off
            # by Vertex with a 504. High thinking on a 50-region drawing takes 1-4 minutes, so 10 minutes.
            timeout_ms = int(os.environ.get("VERTEX_TIMEOUT_MS", "600000"))
            client = genai.Client(vertexai=True, project=self.cfg.project, location=self.cfg.location,
                                  http_options=types.HttpOptions(timeout=timeout_ms))
        self.client = client
        self.step_timeout_s: float | None = None  # one agent turn's deadline, set from a run's budget (else VERTEX_STEP_TIMEOUT_MS)
        # What the loop says about the explicit prefix cache for its next request: False sends the request whole and leaves the sharing to the provider's own
        # (implicit) cache — which serves a conversation that only grows, to its end, where an explicit cache of the first part serves that part only; True
        # (and None, the default) keep the explicit cache the configuration allows.
        self.explicit_override: bool | None = None
        # (model, prefix hash) → cached-content name; None when Vertex refused a cache for that prefix
        self._prompt_caches: dict[tuple[str, str], str | None] = {}

    # ── the explicit prompt cache ────────────────────────────────────────────────

    def _prefix_cache(self, model: str, prefix_key: str, system: str, parts: list, est_tokens: int, tools=None,
                      tool_config=None) -> tuple[str | None, str]:
        """The cached-content name for this run's shared prefix on this model (created on first use)."""
        from google.genai import errors as genai_errors
        from google.genai import types

        if not self.cfg.explicit_cache:
            return None, "off"
        if est_tokens < MIN_CACHE_TOKENS:
            return None, f"prefix too short (~{est_tokens} tokens)"
        k = (model, prefix_key)
        if k in self._prompt_caches:
            name = self._prompt_caches[k]
            return name, "reused" if name else "unavailable"
        try:
            extra = {"tools": tools, "tool_config": tool_config} if tools else {}
            cc = self.client.caches.create(model=model, config=types.CreateCachedContentConfig(
                display_name=f"dxf-autoparam-{prefix_key[:12]}", system_instruction=system,
                contents=[types.Content(role="user", parts=parts)], ttl=f"{self.cfg.cache_ttl_s}s", **extra))
        except genai_errors.APIError as exc:  # a model / region without explicit caching: send the request whole
            self._prompt_caches[k] = None
            return None, f"unavailable ({getattr(exc, 'code', '')} {str(exc)[:100]})"
        self._prompt_caches[k] = cc.name
        return cc.name, "created"

    def _forget_cache(self, model: str, prefix_key: str) -> None:
        self._prompt_caches.pop((model, prefix_key), None)

    def close(self) -> list[str]:
        """Delete this run's prompt caches (they would otherwise expire on their own after the TTL)."""
        from google.genai import errors as genai_errors

        problems = []
        for (model, _k), name in list(self._prompt_caches.items()):
            if not name:
                continue
            try:
                self.client.caches.delete(name=name)
            except genai_errors.APIError as exc:  # already expired or gone: nothing to clean up
                problems.append(f"{model}: {getattr(exc, 'code', '')} {str(exc)[:80]}")
        self._prompt_caches.clear()
        return problems

    # ── one turn of a tool-using agent ────────────────────────────────────────────

    def step(self, system: str, tools: list, prefix_parts: list, prefix_key: str, history: list, label: str, thinking: str,
             max_out: int | None = None, stop=None, on_event=None, thinking_budget: int | None = None):
        """One agent turn: the cached prefix (system, tools, pictures, overview) + the conversation so far → the
        model's next content (thought summaries and function calls). Turns are cached on disk by everything sent, so
        replaying an identical run is free. Returns (content, usage)."""
        from google.genai import errors as genai_errors
        from google.genai import types

        tool_config = types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY"))
        budget = self.cfg.thinking_budget if thinking_budget is None else thinking_budget
        budget_key = f"@{budget}" if budget is not None else ""
        h = hashlib.sha256()
        for part in (self.cfg.model, f"{thinking}{budget_key}", system, prefix_key, json.dumps([t.model_dump(mode="json", exclude_none=True) for t in tools], sort_keys=True)):
            h.update(part.encode())
        for c in history:
            h.update(json.dumps(c.model_dump(mode="json", exclude_none=True), sort_keys=True).encode())
        key = "agent-" + h.hexdigest()[:24]
        CACHE.mkdir(parents=True, exist_ok=True)
        hit = CACHE / f"{key}.json"
        if hit.exists():
            data = json.loads(hit.read_text())
            content = types.Content.model_validate(data["content"])
            for part in content.parts or []:
                if getattr(part, "thought", False) and part.text and on_event:
                    on_event({"kind": "thought", "text": part.text, "cached": True})
            return content, {**data["usage"], "cached": True}
        est = len(system) // 4 + sum(len(getattr(p, "text", "") or "") // 4 if getattr(p, "text", None) else IMAGE_TOKENS for p in prefix_parts)
        effective_max_out = self.cfg.max_output_tokens if max_out is None else max_out
        base = {"temperature": 0.0, "max_output_tokens": effective_max_out, "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)}
        plan = [(self.cfg.model, thinking, budget)]
        if self.cfg.fallback_model and self.cfg.fallback_model != self.cfg.model:
            plan.append((self.cfg.fallback_model, self.cfg.fallback_thinking, self.cfg.fallback_thinking_budget))
        t0, last = time.perf_counter(), None
        # Vertex ends the call itself at this deadline (sent as its server timeout); the worker thread backs it up
        step_ms = int((self.step_timeout_s or 0) * 1000) or int(os.environ.get("VERTEX_STEP_TIMEOUT_MS", "240000"))
        for model, think, tb in plan:
            for attempt in range(2):
                if stop and stop():
                    raise GeminiStopped("stopped by the person")
                cached, cache_state = (None, "implicit") if self.explicit_override is False else self._prefix_cache(model, prefix_key, system, prefix_parts, est, tools, tool_config)
                kw = {**base, "cached_content": cached} if cached else {**base, "system_instruction": system, "tools": tools, "tool_config": tool_config}
                contents = history if cached else [types.Content(role="user", parts=prefix_parts), *history]
                if on_event:
                    on_event({"kind": "call", "label": label, "model": model, "thinking": think, "prompt_cache": cache_state, "attempt": attempt + 1})
                try:
                    cfg = types.GenerateContentConfig(**kw, thinking_config=_thinking_config(think, tb),
                                                      http_options=types.HttpOptions(timeout=step_ms))
                    got: list = []
                    _pumped(lambda put, c=contents, g=cfg, m=model: put(self.client.models.generate_content(model=m, contents=c, config=g)),
                            got.append, step_ms / 1000 + 15, stop, f"{model} {label}")
                    resp = got[0]
                except (genai_errors.APIError, TimeoutError, OSError, httpx.TransportError) as exc:
                    last = exc
                    if cached and getattr(exc, "code", None) in (400, 403, 404) and "cach" in str(exc).lower():
                        self._forget_cache(model, prefix_key)
                        continue
                    if not _transient(exc):
                        raise
                    if on_event:
                        on_event({"kind": "retry", "label": label, "model": model, "why": f"{getattr(exc, 'code', '')} {str(exc)[:120]}"})
                    _wait(4 * (attempt + 1), stop)
                    continue
                cands = getattr(resp, "candidates", None) or []
                content = cands[0].content if cands and getattr(cands[0], "content", None) else types.Content(role="model", parts=[])
                fr = getattr(cands[0], "finish_reason", None) if cands else None
                for part in content.parts or []:
                    if getattr(part, "thought", False) and part.text and on_event:
                        on_event({"kind": "thought", "text": part.text})
                usage = {"model": model, "thinking": think, "label": label, "seconds": round(time.perf_counter() - t0, 1),
                         **_tokens(Reply("", [], getattr(resp, "usage_metadata", None), "")), "finish": getattr(fr, "name", str(fr)),
                         "prompt_cache": cache_state, "cached": False}
                hit.write_text(json.dumps({"content": content.model_dump(mode="json", exclude_none=True), "usage": usage}))
                _log({**usage, "key": key})
                return content, usage
        raise GeminiUnavailable(f"Vertex AI did not answer ({', '.join(m for m, *_ in plan)}): {last}")

    # ── a structured question ─────────────────────────────────────────────────────

    def ask(self, system: str, texts: list[str], images: list[bytes], schema, label: str = "ask",
            image_keys: list[str] | None = None, shared: int = 0, on_event=None, stop=None) -> tuple[dict, dict]:
        """Structured answer (validated against `schema`, a pydantic model) and usage. Cached.

        `image_keys` stand in for images whose bytes are not reproducible (a renderer that
        stamps its output); give the cache a stable key for them, e.g. a hash of the source file.
        `shared`: how many leading `texts` are the same across this run's calls; with the system prompt and the
        images they go into the explicit prompt cache, and each call sends only the texts after them.
        `on_event`: called with {"kind": "call" | "thought" | "retry", …} while the model works.
        `stop`: a callable; when it returns True the call ends with GeminiStopped at the next streamed message.
        Usage carries the model's thought summaries (`thoughts`), kept with the answer on disk too.
        """
        from google.genai import errors as genai_errors
        from google.genai import types

        image_ids = [image_keys[k] if image_keys and k < len(image_keys) and image_keys[k] else hashlib.sha256(img).hexdigest()
                     for k, img in enumerate(images)]
        budget = self.cfg.thinking_budget
        budget_key = f"@{budget}" if budget is not None else ""
        h = hashlib.sha256()
        for part in (self.cfg.model, f"{self.cfg.thinking}{budget_key}", system, json.dumps(schema.model_json_schema(), sort_keys=True), *texts):
            h.update(part.encode())
        for key_part in image_ids:
            h.update(key_part.encode())
        key = h.hexdigest()[:24]
        CACHE.mkdir(parents=True, exist_ok=True)
        hit = CACHE / f"{key}.json"
        if hit.exists():
            data = json.loads(hit.read_text())
            if on_event:
                on_event({"kind": "call", "label": label, "cached": True})
                for t in data["usage"].get("thoughts", []):
                    on_event({"kind": "thought", "text": t, "cached": True})
            return data["answer"], {**data["usage"], "cached": True}

        image_parts = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images]
        text_parts = [types.Part.from_text(text=t) for t in texts]
        shared = max(0, min(shared, len(texts) - 1))
        ph = hashlib.sha256(system.encode())
        for part in (*image_ids, *texts[:shared]):
            ph.update(part.encode())
        prefix_key = ph.hexdigest()[:24]
        est = (len(system) + sum(len(t) for t in texts[:shared])) // 4 + IMAGE_TOKENS * len(images)
        base = {"response_mime_type": "application/json", "response_schema": schema, "temperature": 0.0,
                "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)}

        def gen_config(thinking: str, cached: str | None, max_out: int, tb: int | None = None):
            # with a cached prefix the system prompt lives in the cache and may not be sent again
            kw = {**base, "max_output_tokens": max_out}
            kw.update({"cached_content": cached} if cached else {"system_instruction": system})
            try:
                return types.GenerateContentConfig(**kw, thinking_config=_thinking_config(thinking, tb))
            except (TypeError, ValueError):  # an SDK without thinking levels (pydantic rejects the field)
                return types.GenerateContentConfig(**kw)

        # The primary model, then the fallback (e.g. 3.8 Flash → 3.7 Flash @high) when the primary is out of
        # capacity or past its deadline. Each gets one retry after a short back-off. A prompt cache belongs to one
        # model, so the fallback gets its own.
        plan = [(self.cfg.model, self.cfg.thinking, self.cfg.thinking_budget)]
        if self.cfg.fallback_model and self.cfg.fallback_model != self.cfg.model:
            plan.append((self.cfg.fallback_model, self.cfg.fallback_thinking, self.cfg.fallback_thinking_budget))
        t0 = time.perf_counter()
        last: Exception | None = None
        answer, used, used_thinking, cache_state, resp = None, None, None, "off", None
        thoughts_all: list[str] = []
        max_out = self.cfg.max_output_tokens
        wasted = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
        for model, thinking, tb in plan:
            think, think_budget = thinking, tb
            for attempt in range(2):
                cached, cache_state = (self._prefix_cache(model, prefix_key, system, image_parts + text_parts[:shared], est)
                                       if shared else (None, "off"))
                contents = text_parts[shared:] if cached else image_parts + text_parts
                if stop and stop():
                    raise GeminiStopped("stopped by the person")
                if on_event:
                    on_event({"kind": "call", "label": label, "model": model, "thinking": think, "prompt_cache": cache_state, "attempt": attempt + 1})
                try:
                    resp = _stream(self.client, model, contents, gen_config(think, cached, max_out, think_budget), on_event, stop)
                except GeminiStopped:
                    # Vertex reports no usage for a cut stream; what it generated until then is billed all the same
                    _log({"model": model, "thinking": think, "label": label, "stopped": True, "prompt_cache": cache_state, "key": key})
                    raise
                except (genai_errors.APIError, TimeoutError, OSError, httpx.TransportError) as exc:
                    last = exc
                    msg = str(exc).lower()
                    if cached and getattr(exc, "code", None) in (400, 403, 404) and "cach" in msg:
                        self._forget_cache(model, prefix_key)  # expired or refused: recreate (or go uncached) next attempt
                        continue
                    if getattr(exc, "code", None) == 400 and ("max_output_tokens" in msg or "maxoutputtokens" in msg) and max_out > 8192:
                        max_out //= 2  # a model with a smaller output limit
                        continue
                    if not _transient(exc):
                        raise
                    if on_event:
                        on_event({"kind": "retry", "label": label, "model": model, "why": f"{getattr(exc, 'code', '')} {str(exc)[:120]}"})
                    _wait(4 * (attempt + 1), stop)
                    continue
                thoughts_all += resp.thoughts
                answer = _read(resp, schema)
                if answer is not None:
                    used, used_thinking = model, think
                    break
                # billed but unusable (cut off, blocked, empty): logged, then tried again
                finish, tok = resp.finish, _tokens(resp)
                for k in wasted:
                    wasted[k] += tok[k]
                _log({"model": model, "thinking": think, "label": label, "error": f"no complete JSON (finish {finish})",
                       "chars": len(getattr(resp, "text", "") or ""), "prompt_cache": cache_state, **tok, "key": key})
                last = GeminiUnavailable(f"{model} @{think}: no complete JSON (finish {finish})")
                if on_event:
                    on_event({"kind": "retry", "label": label, "model": model, "why": f"reply not complete JSON (finish {finish})"})
                if finish == "MAX_TOKENS" and think == "high":
                    think = "medium"  # the thinking ate the output budget: think less, keep the answer
                    think_budget = None
            if answer is not None:
                break
        if answer is None:
            raise GeminiUnavailable(f"Vertex AI gave no usable answer ({', '.join(m for m, *_ in plan)}): {last}")
        usage = {"model": used, "thinking": used_thinking, "fallback": used != self.cfg.model, "label": label,
                 "seconds": round(time.perf_counter() - t0, 1), **_tokens(resp), "finish": resp.finish,
                 "prompt_cache": cache_state, "cached": False, "thoughts": thoughts_all}
        if any(wasted.values()):
            usage["wasted"] = wasted  # tokens of attempts that gave no usable answer (billed all the same)
        hit.write_text(json.dumps({"answer": answer, "usage": usage}))
        _log({**{k: v for k, v in usage.items() if k != "thoughts"}, "key": key})
        return answer, usage
