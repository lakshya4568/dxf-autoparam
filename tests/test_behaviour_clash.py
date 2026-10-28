"""The behaviour report says when a change makes two members run into each other.

It used to call a span of 100 mm valid: no single outline turned inside out, and the only check that looked for members crossing (a plan's own,
`plan.clashes`) is not part of this report. A paid run's sweep said "0 failures" over a drawing whose backing outlines crossed at +10 % of one
value; `check_behaviour` (the agent's own check) and the page's check read the same report."""

from __future__ import annotations

import pytest
from test_intent_plan import box_sheet

from dxf_autoparam.behaviour import behaviour_report


@pytest.fixture(autouse=True)
def bridge_pack(monkeypatch):
    monkeypatch.setenv("AUTOPARAM_DOMAIN", "bridge")


def test_a_change_that_leaves_every_member_apart_says_so(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    rep = behaviour_report(sm, {f"{uid}.ClearSpan": 2500.0})
    assert rep["ok"] and rep["categories"]["validity"]["status"] == "pass"
    assert any("no member runs into another" in r["issue"] for r in rep["categories"]["validity"]["items"])


def test_a_cell_closed_up_past_its_haunches_fails_the_validity_check_naming_both_members(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    assert not sm.preview({f"{uid}.ClearSpan": 100.0}).errors, "the sheet's own checks do not see it: no outline turns inside out"
    rep = behaviour_report(sm, {f"{uid}.ClearSpan": 100.0})
    assert not rep["ok"] and rep["failed"] == ["validity"]
    crossings = [r for r in rep["categories"]["validity"]["items"] if r["status"] == "fail" and r["issue"].startswith("members cross")]
    assert crossings, rep["categories"]["validity"]
    first = crossings[0]
    assert "LeftWall" in first["issue"] and "Haunch" in first["issue"], "the parts are named, not only the entities"
    assert len(first["entities"]) == 2 and all(isinstance(k, int) for k in first["entities"]), "sheet indices: the page can zoom to them"
    assert not any("no member runs into another" in r["issue"] for r in rep["categories"]["validity"]["items"]), "a pass row must not sit beside a failure"


def test_a_value_whose_step_runs_members_into_each_other_is_named_with_the_first_pair(tmp_path):
    # a paid run (2026-10-28) finished "Complete: every criterion holds" and the bench counted 79 of 80 values editable, while 44 of its named lengths
    # ran walls into slabs at ±10 %: the sheet accepts such a step (a crossing refuses only against a plan a person accepted). One sweep now says it
    # — the run's finish, its verdict and the bench all read it
    from dxf_autoparam.behaviour import crossing_steps

    sm, uid, _g = box_sheet(tmp_path)
    assert crossing_steps(sm, [uid]) == [], "a box whose every size steps ±10 % cleanly"
    found = {c["value"]: c for c in crossing_steps(sm, [uid], step=0.97)}  # a 3000 mm span far past what the box holds, either way
    assert f"{uid}.ClearSpan" in found, found
    c = found[f"{uid}.ClearSpan"]
    assert c["step"] in ("+97 %", "−97 %") and c["pairs"] >= 1 and c["first"].startswith(f"{uid}: ") and " runs into " in c["first"]
