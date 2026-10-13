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


class RecordedModel(ScriptedModel):
    """The model's OWN turns of an earlier live run, replayed — for judging what an engine would have made of them, with no network and no cost.

    Each turn is the model's answer exactly as recorded (the client's on-disk cache keeps it with the key the usage ledger names), so what is replayed is
    the model's real behaviour, not a reconstruction: the same calls with the same arguments, in the same order, whatever the engine now answers.
    A turn the engine answers differently than it did then (a call that is now refused) simply goes on to the model's next recorded turn."""

    def __init__(self, turns: list, delay: float = 0.0, then: list[list] | None = None):
        """`then`: scripted turns (lists of calls) that follow the recorded ones — what the model would have gone on to do, to see what the
        engine says of it. They are marked as scripted; nothing in them is the model's own."""
        then = [list(t) for t in (then or [])]
        super().__init__([[p for p in t.parts if getattr(p, "function_call", None)] for t in turns] + then, delay=delay,
                         thoughts=["[replayed from the recorded run] " + (next((p.text for p in t.parts if getattr(p, "thought", False) and p.text), "") or "")[:300] for t in turns]
                         + ["[scripted continuation, not the model]"] * len(then))
        self.recorded = turns

    @classmethod
    def from_ledger(cls, ledger_path: str, cache_dir: str, **kw) -> RecordedModel:
        """The turns of a run, from its usage ledger (one line per model call: label and cache key) and the client's answer cache."""
        import json
        from pathlib import Path

        from google.genai import types

        turns = []
        for line in Path(ledger_path).read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            f = Path(cache_dir) / f"{row['key']}.json"
            if row.get("error") or row.get("stopped") or not f.exists():
                continue
            turns.append((row.get("at", ""), types.Content.model_validate(json.loads(f.read_text())["content"])))
        return cls([t for _at, t in turns], **kw)
