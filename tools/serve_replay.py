"""Serve the app with Gemini replaced by a replay of a saved answer — to look at the UI without any AI call.

    uv run python tools/serve_replay.py examples/sectional_elevation_xx.dxf tests/fixtures/sectional_elevation_xx.answer.json --port 8793

Every streamed event is marked [replay]: nothing shown here is the model's own thinking.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from dxf_autoparam.ai import agent, parametrize, vertex
from dxf_autoparam.ai.vertex import GeminiStopped
from dxf_autoparam.server import serve


class _NoGemini:
    def close(self):
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("answer")
    ap.add_argument("--port", type=int, default=8793)
    a = ap.parse_args()
    answer = json.loads(Path(a.answer).read_text())

    def replay(path, region=None, rounds=2, log=print, hold_existing=False, instructions="", gem=None, on_event=None, stop=None, **_):
        emit = on_event or (lambda e: None)
        emit({"kind": "call", "label": "parametrize [replay]", "model": "replay", "thinking": "-", "prompt_cache": "-", "attempt": 1})
        for c in answer.get("components", [])[:8]:
            time.sleep(0.4)
            if stop and stop():
                raise GeminiStopped("stopped by the person")
            emit({"kind": "thought", "text": f"**[replay] {c['name']}** — {'; '.join(c.get('evidence', [])[:2])}"})
        if instructions:
            emit({"kind": "thought", "text": f"**[replay] instructions received** {instructions}"})
        prog, rep = parametrize.reapply(path, answer, region, hold_existing=hold_existing)
        emit({"kind": "round", "round": 1, "accepted": rep.accepted, "rejected": rep.rejected, "errors": []})
        return prog, rep, {"answer": answer, "usage": [{"label": "parametrize [replay]", "model": "replay", "thoughts": ["[replay] no model thinking"]}],
                           "seconds": 3.2, "tokens_in": 0, "tokens_out": 0, "tokens_cached": 0}

    def replay_refine(path, previous, request, **kw):
        kw.setdefault("instructions", "")
        kw["instructions"] = (kw["instructions"] + "\n" + request).strip()
        return replay(path, **kw)

    def replay_agent(path, region=None, instructions="", start=None, request="", hold_existing=False, gem=None, on_event=None, stop=None, **_):
        return replay(path, region=region, hold_existing=hold_existing, instructions=(instructions + "\n" + request).strip(),
                      on_event=on_event, stop=stop)

    parametrize.ai_parametrize = replay
    parametrize.ai_refine = replay_refine
    agent.agent_parametrize = replay_agent
    vertex.Gemini = _NoGemini
    serve(a.dxf, port=a.port)


if __name__ == "__main__":
    main()
