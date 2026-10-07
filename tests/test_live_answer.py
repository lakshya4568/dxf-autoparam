"""A real Gemini answer (3.8 Flash @high, X-X sectional elevation, after two repair rounds) replayed through the
validator — no AI call. What the engine must make of it, whatever changes in the engine later."""

from __future__ import annotations

import json
from pathlib import Path

from dxf_autoparam.ai import parametrize
from dxf_autoparam.ai.parametrize import reapply
from dxf_autoparam.regen import regenerate_program

ROOT = Path(__file__).resolve().parents[1]
XX = str(ROOT / "examples" / "sectional_elevation_xx.dxf")
ANSWER = json.loads((ROOT / "tests" / "fixtures" / "sectional_elevation_xx.answer.json").read_text())


def test_the_live_answer_applies_cleanly_and_its_intent_holds():
    prog, rep = reapply(XX, ANSWER)
    assert rep.errors() == []
    I = prog.intent
    assert I["uncovered_regions"] == []  # every region belongs to a part
    assert {c.name for c in prog.components if c.existing} >= {"ExistingBarrel", "ExistingTopSlab"}
    assert all(b["status"] == "confirmed" for b in I["behaviours"] if b["status"] != "held")
    assert all(c["status"] == "always" for c in I["constraints"])
    # lengthening the barrel: the barrel grows, what is downstream follows, the tracks stay where the site put them
    imp = I["impact"]["ProposedBarrelLength"]
    assert imp["ProposedBarrel"] == "grows x" and "ProposedDropWall" in imp
    assert "RailwayTracks" not in imp and "ProposedTracks" not in imp
    assert any(f.code == "V8" and f.severity == "info" for f in rep.findings)  # the engine re-anchored the slope foot
    r = regenerate_program(prog, {"ProposedBarrelLength": prog.params["ProposedBarrelLength"].value + 1000})
    assert not r.issues


def test_holding_existing_work_keeps_the_old_box_as_built():
    prog, _rep = reapply(XX, ANSWER, hold_existing=True)
    for name, row in prog.intent["impact"].items():
        if prog.params[name].kind != "level":
            # existing parts never grow, shrink or move; where an existing line meets new work (the new embankment
            # slope reaching the existing formation line) that meeting corner may slide — "reshapes inside", at most one
            bad = {k: v for k, v in row.items() if k.startswith("Existing") and not v.startswith("reshapes inside (1 ")}
            assert not bad, (name, bad)


def test_a_repair_round_that_does_worse_is_not_kept(monkeypatch):
    worse = json.loads(json.dumps(ANSWER))
    worse["datum_formulas"].append({"datum": "y18", "expr": "y10 + ClearHeight + 50"})  # moves a line: rejected
    worse["relations"].append({"name": "Nonsense", "label": "", "expr": "NoSuchValue * 2"})
    first = json.loads(json.dumps(ANSWER))
    first["relations"].append({"name": "Bad", "label": "", "expr": "NoSuchValue"})  # one rejection → a repair round

    answers = [first, worse]

    class FakeGemini:
        def __init__(self):
            self.cfg = type("C", (), {"model": "fake", "thinking": "high"})()

        def ask(self, *a, **k):
            return answers.pop(0), {"model": "fake", "input_tokens": 0, "output_tokens": 0, "cached": False}

        def close(self):
            return []

    monkeypatch.setattr(parametrize, "Gemini", FakeGemini)
    _prog, rep, info = parametrize.ai_parametrize(XX, rounds=2, log=lambda *a: None)
    assert info["answer"] is first or info["answer"] == first
    assert len(rep.errors()) == 1
