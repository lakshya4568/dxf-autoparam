"""The app's Gemini jobs, with Gemini replaced by a stand-in — no network, no cost."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from dxf_autoparam.ai import agent, parametrize, vertex
from dxf_autoparam.ai.vertex import GeminiStopped
from dxf_autoparam.server import Session

ROOT = Path(__file__).resolve().parents[1]
XX = str(ROOT / "examples" / "sectional_elevation_xx.dxf")
ANSWER = json.loads((ROOT / "tests" / "fixtures" / "sectional_elevation_xx.answer.json").read_text())


class NoGemini:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1
        return []


@pytest.fixture
def session(monkeypatch):
    calls = []

    def fake_run(path, region=None, rounds=2, log=print, hold_existing=False, instructions="", gem=None, on_event=None, stop=None, **_):
        calls.append(("run", instructions, gem))
        if instructions == "wait for stop":  # a long run the person stops
            on_event({"kind": "thought", "text": "thinking…"})
            t0 = time.time()
            while not stop() and time.time() - t0 < 30:
                time.sleep(0.02)
            raise GeminiStopped("stopped by the person")
        on_event({"kind": "call", "label": "parametrize", "model": "stand-in", "thinking": "high", "prompt_cache": "created", "attempt": 1})
        on_event({"kind": "thought", "text": "**Segmenting** R26 is the barrel."})
        prog, rep = parametrize.reapply(path, ANSWER, region, hold_existing=hold_existing)
        on_event({"kind": "round", "round": 1, "accepted": rep.accepted, "rejected": rep.rejected, "errors": []})
        return prog, rep, {"answer": ANSWER, "usage": [{"label": "parametrize", "thoughts": ["**Segmenting** R26 is the barrel."]}],
                           "seconds": 0.1, "tokens_in": 10, "tokens_out": 5, "tokens_cached": 8}

    def fake_refine(path, previous, request, region=None, rounds=2, log=print, hold_existing=False, instructions="", gem=None, on_event=None,
                    stop=None, **_):
        calls.append(("revise", request, previous is not None, instructions))
        return fake_run(path, region=region, hold_existing=hold_existing, instructions=instructions, gem=gem, on_event=on_event)

    def fake_agent(path, region=None, instructions="", start=None, request="", hold_existing=False, gem=None, on_event=None, stop=None, **_):
        if start is not None:
            return fake_refine(path, start, request, region=region, hold_existing=hold_existing, instructions=instructions, gem=gem,
                               on_event=on_event, stop=stop)
        return fake_run(path, region=region, hold_existing=hold_existing, instructions=instructions, gem=gem, on_event=on_event, stop=stop)

    monkeypatch.setattr(parametrize, "ai_parametrize", fake_run)
    monkeypatch.setattr(parametrize, "ai_refine", fake_refine)
    monkeypatch.setattr(agent, "agent_parametrize", fake_agent)
    monkeypatch.setattr(vertex, "Gemini", NoGemini)
    s = Session(XX)
    s.calls = calls
    return s


def wait(s: Session) -> None:
    t0 = time.time()
    while s.busy() and time.time() - t0 < 60:
        time.sleep(0.05)


def test_a_run_streams_progress_and_follows_the_instructions(session):
    session.start_ai("run", instructions="Keep the tracks as drawn.")
    wait(session)
    kinds = [e["kind"] for e in session.job["events"]]
    assert kinds[:2] == ["call", "thought"] and kinds[-1] == "done"
    assert session.mode == "ai" and session.instructions == "Keep the tracks as drawn."
    assert session.calls[0][:2] == ("run", "Keep the tracks as drawn.")
    st = session.state()
    assert st["thoughts"][0]["thoughts"] and st["history"][0]["text"] == "Keep the tracks as drawn."
    assert not st["ai_job"]["running"]


def test_a_revision_gets_the_previous_answer_and_the_request_and_keeps_the_client(session):
    with pytest.raises(RuntimeError, match="run Gemini first"):
        session.start_ai("revise", request="make the wing length a parameter")
    session.start_ai("run", instructions="Parametrize the proposed box.")
    wait(session)
    gem = session.gem
    session.start_ai("revise", request="R12 and R13 are one footing")
    wait(session)
    assert session.calls[1] == ("revise", "R12 and R13 are one footing", True, "Parametrize the proposed box.")
    assert session.calls[2][2] is gem  # the same client: its prompt cache serves the follow-up
    assert [h["kind"] for h in session.history] == ["run", "revise"]


def test_one_job_at_a_time_and_a_new_drawing_drops_the_client(session):
    session.job = {"running": True, "events": [], "error": None, "kind": "run", "started": 0}
    with pytest.raises(RuntimeError, match="already working"):
        session.start_ai("run")
    session.job["running"] = False
    session.start_ai("run")
    wait(session)
    gem = session.gem
    session.open(XX)
    assert session.gem is None and gem.closed == 1 and session.history == []


def test_stopping_a_run_keeps_what_the_person_had(session):
    before = session.mode
    session.start_ai("run", instructions="wait for stop")
    time.sleep(0.2)
    assert session.stop_ai() is True
    wait(session)
    kinds = [e["kind"] for e in session.job["events"]]
    assert "stopped" in kinds and session.job["error"] is None
    assert session.mode == before and session.history == []  # nothing replaced
    assert session.stop_ai() is False  # nothing left to stop


def test_a_repair_round_stopped_keeps_the_validated_round(monkeypatch):
    first = json.loads(json.dumps(ANSWER))
    first["relations"].append({"name": "Bad", "label": "", "expr": "NoSuchValue"})  # one rejection → a repair round

    class StopsOnRepair:
        def __init__(self):
            self.cfg = type("C", (), {"model": "fake", "thinking": "high"})()
            self.n = 0

        def ask(self, *a, **k):
            self.n += 1
            if self.n == 2:
                raise GeminiStopped("stopped by the person")
            return first, {"model": "fake", "input_tokens": 0, "output_tokens": 0, "cached": False}

        def close(self):
            return []

    monkeypatch.setattr(parametrize, "Gemini", StopsOnRepair)
    events = []
    _prog, rep, info = parametrize.ai_parametrize(XX, rounds=2, log=lambda *a: None, on_event=events.append)
    assert info["answer"] == first and len(rep.errors()) == 1
    assert any(e["kind"] == "stopped" for e in events)
