"""A model reached through an OpenAI-compatible gateway (Experiential Labs, Token Harbor), speaking the same `step` the agent loop speaks to Vertex.

The loop works in Gemini's shapes (`types.Content` with function calls / responses); this client translates those to chat-completions
messages and tools and the answer back, so the loop, the engine and the ledger do not know which provider they talk to.

    EXPLABS_API_KEY / EXPLABS_BASE_URL          the Experiential Labs gateway (default https://api.experientiallabs.ai/v1)
    TOKENHARBOR_API_KEY / TOKENHARBOR_BASE_URL  Token Harbor (default https://tokenharbor.ai/v1; its catalogue and its free models: `ai/tokenharbor.py`)
    (a key is a secret: environment / .env only, never logged)

The request is what the Vertex path sends, in the gateway's words: the reasoning level the person picked (`reasoning_effort`, "high" for the
picker's "· high"), temperature 0, the output limit (the model's own 32,768 at most), and for the agent tools + tool_choice. What a model
refuses (HTTP 400/422) is given up one thing at a time, and the call says so in its usage (`dropped`) and in a note of the run: a picture (a
text-only model goes on without pictures, working from the numbers the tools return), "a tool call is required" (it is then asked to choose; the
loop asks again when it answers in words), else the optional fields. A run is never lost to one of them, and what a model refused is remembered
for the rest of the run, so the next turn does not ask twice. A rate limit (HTTP 429: a free tier is slowed down for minutes at a time) is waited out —
as long as `Retry-After` asks, else 10 s growing to 60 s, six tries, a note of the run each time, Stop heard within a second — before the turn fails;
a network error or a 5xx gets three tries. The gateway reports the cost of a call, or else the model's listed price gives it
(zero for a free model); it is kept in the ledger (`cost_usd`) and the Cost tab uses it as the authority for these models. Answers are cached on
disk like Vertex's, by everything sent.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass

import httpx

from .vertex import CACHE, GeminiStopped, GeminiUnavailable, _log, load_env_file

BASE_URL = "https://api.experientiallabs.ai/v1"
MAX_OUTPUT = 32768  # the model's limit as the gateway lists it
OPTIONAL = ("reasoning_effort", "temperature", "max_tokens")
PICTURE_ERROR = re.compile(r"\b(image|vision|multi-?modal|modalit)", re.IGNORECASE)  # how a gateway says a model does not take a picture
TOOL_ERROR = re.compile(r"tool[_ ]choice|tool calls? (is |are )?required", re.IGNORECASE)  # ... or does not take "a tool call is required"
NO_PICTURE = "[{n} picture(s) were given here; this model does not read pictures]"
RATE_TRIES = 6  # a rate limit ("slowed down for a few minutes") is waited out: this many tries ...
RATE_WAIT_S = (10.0, 20.0, 40.0, 60.0, 60.0)  # ... waiting as the answer asks (Retry-After) or this long between them
GAVE_UP = {"picture": "this model does not read pictures: they are left out from now on, and it works from the numbers the tools return",
           "tool_choice": 'this model would not take "a tool call is required": it is asked to choose, and the loop asks again when it answers in words'}


@dataclass(frozen=True)
class Provider:
    name: str  # what the ledger calls it: a call's model id is "<name>:<gateway id>"
    label: str  # how an error names it
    key_env: str
    base_env: str
    base_url: str


PROVIDERS = {"gateway": Provider("gateway", "the gateway", "EXPLABS_API_KEY", "EXPLABS_BASE_URL", BASE_URL),
             "tokenharbor": Provider("tokenharbor", "Token Harbor", "TOKENHARBOR_API_KEY", "TOKENHARBOR_BASE_URL", "https://tokenharbor.ai/v1")}


@dataclass
class GatewayConfig:
    model: str  # the gateway's own id for the model
    thinking: str = "high"
    fallback_model: str = ""
    fallback_thinking: str = "high"
    explicit_cache: bool = False
    provider: str = "gateway"  # a key of PROVIDERS
    price: dict | None = None  # USD per million tokens (input, output, cached): the cost of a call the gateway does not report itself


def _data_uri(blob) -> str:
    return f"data:{getattr(blob, 'mime_type', None) or 'image/png'};base64,{base64.b64encode(blob.data).decode()}"


def _user_content(parts) -> list[dict]:
    out: list[dict] = []
    for p in parts or []:
        if getattr(p, "text", None) and not getattr(p, "thought", False):
            out.append({"type": "text", "text": p.text})
        elif getattr(p, "inline_data", None) is not None:
            out.append({"type": "image_url", "image_url": {"url": _data_uri(p.inline_data)}})
    return out


def to_messages(system: str, prefix_parts: list, history: list) -> list[dict]:
    """Gemini-shaped conversation → chat-completions messages. A function call gets an id from its place in the conversation, and the
    function response that answers it (the next user content, in order) carries the same id. Pictures a tool returned go in a user message
    after the tool results: a tool message can only carry text."""
    msgs: list[dict] = [{"role": "system", "content": system}]
    if prefix_parts:
        msgs.append({"role": "user", "content": _user_content(prefix_parts)})
    pending: list[tuple[str, str]] = []  # (id, name) of calls not yet answered
    n = 0
    for c in history:
        parts = list(c.parts or [])
        if c.role == "model":
            text = "\n".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))
            calls = []
            for p in parts:
                fc = getattr(p, "function_call", None)
                if fc:
                    n += 1
                    cid = getattr(fc, "id", None) or f"call_{n}"
                    calls.append({"id": cid, "type": "function", "function": {"name": fc.name, "arguments": json.dumps(dict(fc.args or {}), default=str)}})
                    pending.append((cid, fc.name))
            m: dict = {"role": "assistant", "content": text or None}
            if calls:
                m["tool_calls"] = calls
            msgs.append(m)
            continue
        images, plain = [], []
        for p in parts:
            fr = getattr(p, "function_response", None)
            if fr:
                k = next((i for i, (_cid, nm) in enumerate(pending) if nm == fr.name), None)
                cid = pending.pop(k)[0] if k is not None else f"call_orphan_{len(msgs)}"
                msgs.append({"role": "tool", "tool_call_id": cid, "content": json.dumps(fr.response, default=str)})
                for sub in getattr(fr, "parts", None) or []:
                    blob = getattr(sub, "inline_data", None)
                    if blob is not None:
                        images.append({"type": "image_url", "image_url": {"url": _data_uri(blob)}})
            else:
                plain.extend(_user_content([p]))
        if images or plain:
            msgs.append({"role": "user", "content": plain + images})
    return msgs


def _is_picture(part) -> bool:
    return isinstance(part, dict) and part.get("type") == "image_url"


def strip_pictures(msgs: list[dict]) -> tuple[list[dict], int]:
    """The same messages without their pictures (a line in each message says how many were there), and how many were left out."""
    left, out = 0, []
    for m in msgs:
        c = m.get("content")
        if isinstance(c, list) and any(_is_picture(x) for x in c):
            kept = [x for x in c if not _is_picture(x)]
            n = len(c) - len(kept)
            left += n
            m = {**m, "content": kept + [{"type": "text", "text": NO_PICTURE.format(n=n)}]}
        out.append(m)
    return out, left


def to_tools(tools: list) -> list[dict]:
    out = []
    for t in tools or []:
        for d in getattr(t, "function_declarations", None) or []:
            schema = getattr(d, "parameters_json_schema", None) or getattr(d, "parameters", None) or {"type": "object", "properties": {}}
            out.append({"type": "function", "function": {"name": d.name, "description": d.description or "",
                                                         "parameters": schema if isinstance(schema, dict) else json.loads(json.dumps(schema, default=str))}})
    return out


def retry_after(r: httpx.Response) -> float | None:
    """What a 429 / 503 asks for in `Retry-After` (seconds, at most a minute: the run's own limits decide beyond that), else None."""
    try:
        s = float(r.headers.get("retry-after", ""))
    except ValueError:
        return None
    return min(max(s, 1.0), 60.0)


class Gateway:
    def __init__(self, cfg: GatewayConfig, client: httpx.Client | None = None):
        load_env_file()
        self.cfg = cfg
        self.provider = PROVIDERS[cfg.provider]
        self.step_timeout_s: float | None = None
        self._key = os.environ.get(self.provider.key_env, "")
        self.base = (os.environ.get(self.provider.base_env) or self.provider.base_url).rstrip("/")
        self.client = client or httpx.Client(timeout=httpx.Timeout(600.0, connect=20.0))
        self.unsupported: set[str] = set()  # optional fields this model refused: not sent again in this run
        self.text_only = False  # it refused a picture: pictures are left out from then on
        self.free_choice = False  # it refused "a tool call is required": it is asked to choose
        self._said: set[str] = set()

    def close(self) -> list[str]:
        self.client.close()
        return []

    def _degrade(self, body: dict, text: str) -> tuple[dict, list[str]] | None:
        """The request again without what the gateway just refused, and what was given up: a picture, "a tool call is required", else the optional
        fields; None when nothing is left to give up (the refusal is then the model's, and is said)."""
        if PICTURE_ERROR.search(text) and any(_is_picture(x) for m in body.get("messages", []) if isinstance(m.get("content"), list) for x in m["content"]):
            msgs, n = strip_pictures(body["messages"])
            self.text_only = True
            return {**body, "messages": msgs}, [f"{n} picture(s)"]
        if body.get("tool_choice") == "required" and TOOL_ERROR.search(text):
            self.free_choice = True
            return {**body, "tool_choice": "auto"}, ["tool_choice"]
        gone = [k for k in OPTIONAL if k in body]
        if gone:
            self.unsupported.update(gone)
            return {k: v for k, v in body.items() if k not in OPTIONAL}, gone
        return None

    def _wait(self, seconds: float, stop) -> None:
        """Sleep in slices, so that Stop is heard within a second."""
        n = max(1, round(seconds))
        for _ in range(n):
            if stop and stop():
                raise GeminiStopped("stopped")
            time.sleep(seconds / n)

    def _post(self, body: dict, stop, on_event=None) -> tuple[dict, list[str]]:
        if not self._key:
            raise GeminiUnavailable(f"{self.provider.key_env} is not set: put it in .env")
        deadline = self.step_timeout_s or float(os.environ.get("VERTEX_STEP_TIMEOUT_MS", "240000")) / 1000
        last, dropped, tries, limited = "", [], 0, 0
        while True:
            if stop and stop():
                raise GeminiStopped("stopped")
            wait = 2 + 4 * tries
            try:
                r = self.client.post(f"{self.base}/chat/completions", json=body, timeout=deadline,
                                     headers={"Authorization": f"Bearer {self._key}"})
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if r.status_code == 200:
                    try:
                        return r.json(), dropped
                    except ValueError:  # a busy gateway may answer 200 with a body cut short or not JSON at all: tried again like a server error
                        last = f"HTTP 200 with a body that is not JSON: {r.text[:120]!r}"
                        tries += 1
                        if tries >= 3:
                            break
                        self._wait(wait, stop)
                        continue
                last = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code in (400, 422):
                    fix = self._degrade(body, r.text)
                    if fix is not None:  # the same turn without what was refused; each thing is given up once, so this ends
                        body, gave = fix
                        dropped += gave
                        continue
                if r.status_code == 429:  # a rate limit is waited out, for longer than a failure: an account is slowed down for a few minutes
                    limited += 1
                    if limited >= RATE_TRIES:
                        break
                    pause = retry_after(r) or RATE_WAIT_S[min(limited - 1, len(RATE_WAIT_S) - 1)]
                    if on_event:
                        on_event({"kind": "note", "text": f"{self.provider.label} is slowing requests down (HTTP 429): waiting {pause:g} s, then trying again ({limited} of {RATE_TRIES - 1})"})
                    self._wait(pause, stop)
                    continue
                if r.status_code not in (500, 502, 503, 504):
                    break
                if r.status_code == 503:
                    wait = retry_after(r) or wait
            tries += 1
            if tries >= 3:
                break
            self._wait(wait, stop)
        raise GeminiUnavailable(f"{self.provider.label} did not answer ({self.cfg.model}): {last}")

    def step(self, system: str, tools: list, prefix_parts: list, prefix_key: str, history: list, label: str, thinking: str,
             max_out: int = 16384, stop=None, on_event=None):
        """One agent turn through the gateway. Returns (content, usage) as Vertex's `step` does."""
        from google.genai import types

        msgs = to_messages(system, prefix_parts, history)
        if self.text_only:
            msgs = strip_pictures(msgs)[0]
        body = {"model": self.cfg.model, "messages": msgs, "temperature": 0,
                "max_tokens": min(int(max_out), MAX_OUTPUT)}
        if thinking in ("none", "low", "medium", "high"):
            body["reasoning_effort"] = thinking
        for k in self.unsupported:  # what this model refused before is not asked again
            body.pop(k, None)
        specs = to_tools(tools)
        if specs:
            body.update({"tools": specs, "tool_choice": "auto" if self.free_choice else "required"})
        key = "gw-" + hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:24]
        CACHE.mkdir(parents=True, exist_ok=True)
        hit = CACHE / f"{key}.json"
        if hit.exists():
            data = json.loads(hit.read_text())
            return types.Content.model_validate(data["content"]), {**data["usage"], "cached": True}
        t0 = time.perf_counter()
        resp, dropped = self._post(body, stop, on_event)
        if stop and stop():
            raise GeminiStopped("stopped")
        for what, text in GAVE_UP.items():  # said once per run, when it happens
            if any(what in d for d in dropped) and what not in self._said:
                self._said.add(what)
                if on_event:
                    on_event({"kind": "note", "text": f"{self.cfg.model}: {text}"})
        choice = (resp.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        parts = []
        thought = msg.get("reasoning_content") or msg.get("reasoning")
        if thought:
            parts.append(types.Part(text=str(thought), thought=True))
            if on_event:
                on_event({"kind": "thought", "text": str(thought)})
        if msg.get("content"):
            parts.append(types.Part.from_text(text=msg["content"]))
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            parts.append(types.Part(function_call=types.FunctionCall(id=tc.get("id"), name=fn.get("name", ""), args=args if isinstance(args, dict) else {})))
        content = types.Content(role="model", parts=parts or [types.Part.from_text(text="")])
        u = resp.get("usage") or {}
        reasoning = int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        cached = int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        cost, price = u.get("cost"), self.cfg.price or {}
        if cost is None and price.get("input") is not None and price.get("output") is not None:  # no cost in the answer: the model's listed price gives it
            cheap = price["cached"] if price.get("cached") is not None else price["input"]
            cost = (max(int(u.get("prompt_tokens") or 0) - cached, 0) * price["input"] + cached * cheap + int(u.get("completion_tokens") or 0) * price["output"]) / 1e6
        usage = {"model": f"{self.provider.name}:{self.cfg.model}", "provider": self.provider.name, "thinking": thinking, "label": label,
                 "seconds": round(time.perf_counter() - t0, 1), "input_tokens": int(u.get("prompt_tokens") or 0),
                 "output_tokens": max(int(u.get("completion_tokens") or 0) - reasoning, 0), "thinking_tokens": reasoning,
                 "vertex_cached_tokens": cached,
                 "cost_usd": cost, "finish": choice.get("finish_reason") or "", "prompt_cache": "implicit", "cached": False, **({"dropped": dropped} if dropped else {})}
        hit.write_text(json.dumps({"content": content.model_dump(mode="json", exclude_none=True), "usage": usage}))
        _log({**usage, "key": key})
        return content, usage

    def ask(self, *a, **k):
        raise GeminiUnavailable("the gateway model serves the agent session only (it has no structured-answer call)")
