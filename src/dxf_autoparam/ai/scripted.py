"""A model replaced by a script — for tests and for looking at the page offline, with no network and no cost.

It answers `Gemini.step` with the next scripted calls and keeps what the engine put in front of it (the prefix with its pictures, the
conversation), so a test can assert what the model was shown. Everything it says is marked as scripted: nothing seen through it is a
model's own thinking.

    gem = ScriptedModel([[call("inspect_sheet")], [call("finish", summary="done")]])
    sheet.gem_factory = lambda: gem
"""

from __future__ import annotations

import time

from .vertex import GeminiStopped


def call(tool: str, **args):
    from google.genai import types

    return types.Part(function_call=types.FunctionCall(name=tool, args=args))


class ScriptedModel:
    def __init__(self, script, delay: float = 0.0, thoughts: list[str] | None = None):
        self.script = list(script)
        self.cfg = type("C", (), {"model": "scripted", "thinking": "high"})()
        self.requests: list[dict] = []
        self.seen: list[list] = []
        self.delay = delay
        self.thoughts = list(thoughts or [])

    def step(self, system, tools, prefix_parts, prefix_key, history, label, thinking, max_out=16384, stop=None, on_event=None):
        from google.genai import types

        if self.delay:
            end = time.time() + self.delay
            while time.time() < end:
                if stop and stop():
                    raise GeminiStopped("stopped by the person")
                time.sleep(0.01)
        self.requests.append({"label": label, "prefix": prefix_parts, "history": list(history), "tools": [d.name for t in tools for d in t.function_declarations],
                              "system": system})
        last = history[-1]
        if last.role == "user" and last.parts and getattr(last.parts[0], "function_response", None):
            self.seen.append([p.function_response for p in last.parts])
        parts = self.script.pop(0) if self.script else [call("finish", summary="out of script")]
        note = self.thoughts.pop(0) if self.thoughts else f"[scripted] {label}"
        if on_event:
            on_event({"kind": "call", "label": label, "model": "scripted", "thinking": thinking})
            on_event({"kind": "thought", "text": note})
        return types.Content(role="model", parts=[types.Part(text=note, thought=True)] + parts), {
            "label": label, "input_tokens": 10, "output_tokens": 5, "thinking_tokens": 5, "cached": False}

    def close(self):
        return []
