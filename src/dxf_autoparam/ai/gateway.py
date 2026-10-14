"""A model reached through an OpenAI-compatible gateway (Experiential Labs), speaking the same `step` the agent loop speaks to Vertex.

The loop works in Gemini's shapes (`types.Content` with function calls / responses); this client translates those to chat-completions
messages and tools and the answer back, so the loop, the engine and the ledger do not know which provider they talk to.

    EXPLABS_API_KEY   the gateway key (a secret: environment / .env only, never logged)
    EXPLABS_BASE_URL  default https://api.experientiallabs.ai/v1

The request is what the Vertex path sends, in the gateway's words: the reasoning level the person picked (`reasoning_effort`, "high" for the
picker's "· high"), temperature 0, the output limit (the model's own 32,768 at most), and for the agent tools + tool_choice. A model that
rejects one of these (HTTP 400/422) is asked again without them, once, and the call says so in its usage (`dropped`): a run is never lost
to an optional field. The gateway reports the cost of a call; it is kept in the ledger (`cost_usd`) and the Cost tab uses it as the
authority for these models. Answers are cached on disk like Vertex's, by everything sent.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass

import httpx

from .vertex import CACHE, GeminiStopped, GeminiUnavailable, _log, load_env_file

BASE_URL = "https://api.experientiallabs.ai/v1"
MAX_OUTPUT = 32768  # the model's limit as the gateway lists it
OPTIONAL = ("reasoning_effort", "temperature", "max_tokens")


@dataclass
class GatewayConfig:
    model: str  # the gateway's own id for the model
    thinking: str = "high"
    fallback_model: str = ""
    fallback_thinking: str = "high"
    explicit_cache: bool = False


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


def to_tools(tools: list) -> list[dict]:
    out = []
    for t in tools or []:
        for d in getattr(t, "function_declarations", None) or []:
            schema = getattr(d, "parameters_json_schema", None) or getattr(d, "parameters", None) or {"type": "object", "properties": {}}
            out.append({"type": "function", "function": {"name": d.name, "description": d.description or "",
                                                         "parameters": schema if isinstance(schema, dict) else json.loads(json.dumps(schema, default=str))}})
    return out


class Gateway:
    def __init__(self, cfg: GatewayConfig, client: httpx.Client | None = None):
        load_env_file()
        self.cfg = cfg
        self.step_timeout_s: float | None = None
        self._key = os.environ.get("EXPLABS_API_KEY", "")
        self.base = (os.environ.get("EXPLABS_BASE_URL") or BASE_URL).rstrip("/")
        self.client = client or httpx.Client(timeout=httpx.Timeout(600.0, connect=20.0))

    def close(self) -> list[str]:
        self.client.close()
        return []

    def _post(self, body: dict, stop) -> tuple[dict, list[str]]:
        if not self._key:
            raise GeminiUnavailable("EXPLABS_API_KEY is not set: put it in .env")
        deadline = self.step_timeout_s or float(os.environ.get("VERTEX_STEP_TIMEOUT_MS", "240000")) / 1000
        last, dropped = "", []
        for attempt in range(3):
            if stop and stop():
                raise GeminiStopped("stopped")
            try:
                r = self.client.post(f"{self.base}/chat/completions", json=body, timeout=deadline,
                                     headers={"Authorization": f"Bearer {self._key}"})
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if r.status_code == 200:
                    return r.json(), dropped
                last = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code in (400, 422) and any(k in body for k in OPTIONAL):
                    dropped = [k for k in OPTIONAL if k in body]  # an unsupported field: the same turn without the optional ones
                    body = {k: v for k, v in body.items() if k not in OPTIONAL}
                    continue
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
            time.sleep(2 + 4 * attempt)
        raise GeminiUnavailable(f"the gateway did not answer ({self.cfg.model}): {last}")

    def step(self, system: str, tools: list, prefix_parts: list, prefix_key: str, history: list, label: str, thinking: str,
             max_out: int = 16384, stop=None, on_event=None):
        """One agent turn through the gateway. Returns (content, usage) as Vertex's `step` does."""
        from google.genai import types

        msgs = to_messages(system, prefix_parts, history)
        body = {"model": self.cfg.model, "messages": msgs, "temperature": 0,
                "max_tokens": min(int(max_out), MAX_OUTPUT)}
        if thinking in ("none", "low", "medium", "high"):
            body["reasoning_effort"] = thinking
        specs = to_tools(tools)
        if specs:
            body.update({"tools": specs, "tool_choice": "required"})
        key = "gw-" + hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:24]
        CACHE.mkdir(parents=True, exist_ok=True)
        hit = CACHE / f"{key}.json"
        if hit.exists():
            data = json.loads(hit.read_text())
            return types.Content.model_validate(data["content"]), {**data["usage"], "cached": True}
        t0 = time.perf_counter()
        resp, dropped = self._post(body, stop)
        if stop and stop():
            raise GeminiStopped("stopped")
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
        usage = {"model": f"gateway:{self.cfg.model}", "provider": "gateway", "thinking": thinking, "label": label,
                 "seconds": round(time.perf_counter() - t0, 1), "input_tokens": int(u.get("prompt_tokens") or 0),
                 "output_tokens": max(int(u.get("completion_tokens") or 0) - reasoning, 0), "thinking_tokens": reasoning,
                 "vertex_cached_tokens": int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
                 "cost_usd": u.get("cost"), "finish": choice.get("finish_reason") or "", "prompt_cache": "implicit", "cached": False, **({"dropped": dropped} if dropped else {})}
        hit.write_text(json.dumps({"content": content.model_dump(mode="json", exclude_none=True), "usage": usage}))
        _log({**usage, "key": key})
        return content, usage

    def ask(self, *a, **k):
        raise GeminiUnavailable("the gateway model serves the agent session only (it has no structured-answer call)")
