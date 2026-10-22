"""Valid changes, invalid changes, ambiguous instructions, solver failures and rollback — and every refusal says which check failed, on which
entities, and what KIND of refusal it is (refusal.py): an edit that cannot be drawn, a model that does not carry the change, a promise a person
made, a rule bound to the sheet, a program that cannot be evaluated — and whether the sheet as it stands fails the same check already (the edit
did not cause it: the check, or the state the sheet is in, needs looking at).

Two generated drawings: the box culvert of the plan tests (walls, slabs, haunches, foundation, wing walls, an unrelated detail), and a slab with a
wall on it and a 100 mm nib off the wall's face whose far end is set out from the slab's edge, not from the wall — the model's own gap."""

from __future__ import annotations

import copy
import json

import ezdxf
import pytest
from test_crossview import mini_gad
from test_intent_plan import FOLLOW_ALL, box_sheet

from dxf_autoparam.ai.agent import agent_parametrize
from dxf_autoparam.crossview import EMPTY_ANSWER, SheetError, SheetModel
from dxf_autoparam.production.bench import _sheet, truth_binding
from dxf_autoparam.production.bridge import default_bridge
from dxf_autoparam.refusal import KINDS, summary

BRIDGE = default_bridge().status()


@pytest.fixture(autouse=True)
def bridge_pack(monkeypatch):
    monkeypatch.setenv("AUTOPARAM_DOMAIN", "bridge")  # the box's instructions use the pack's words, as a person would switch it on


def nib_gad(path) -> str:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (4000, 0), (4000, 400), (0, 400)], close=True)  # the slab
    msp.add_lwpolyline([(1000, 400), (1400, 400), (1400, 3000), (1000, 3000)], close=True)  # a 400 mm wall on it
    msp.add_line((1400, 2600), (1500, 2600))  # a 100 mm nib off the wall's face
    msp.add_linear_dim(base=(1000, 3500), p1=(1000, 3000), p2=(1400, 3000), dimstyle="Standard").render()
    msp.add_linear_dim(base=(-600, 0), p1=(0, 0), p2=(0, 400), angle=90, dimstyle="Standard").render()
    doc.saveas(str(path))
    return str(path)


def nib_sheet(tmp_path, nib: str = "{x0} + 1500", plans: list | None = None):
    """The nib drawing with its two sizes named; the nib's far end set out by `nib` (a formula over the lines, {x0} {x2} …)."""
    sm = SheetModel.open(nib_gad(tmp_path / "nib.dxf"))
    uid = next(iter(sm.units))
    u = sm.unit(uid)
    an, um = u.an, u.sub.units_mm

    def line(axis, at):
        return min((d for d in an.datums.values() if d.axis == axis), key=lambda d: abs(d.value * um - at)).id

    L = {"x0": line("x", 0), "x1": line("x", 1000), "x2": line("x", 1400), "x3": line("x", 1500), "y0": line("y", 0), "y1": line("y", 400)}
    ans = copy.deepcopy(EMPTY_ANSWER)
    ans["parameters"] = [{"name": "WallThickness", "label": "WallThickness", "component": "", "kind": "length", "from_datum": L["x1"], "to_datum": L["x2"],
                          "value": 400.0},
                         {"name": "SlabThickness", "label": "SlabThickness", "component": "", "kind": "length", "from_datum": L["y0"], "to_datum": L["y1"],
                          "value": 400.0}]
    ans["datum_formulas"] = [{"datum": L["x3"], "expr": nib.format(**L)}]
    if plans:
        ans["plans"] = [json.loads(json.dumps(p).replace("{x2}", L["x2"]).replace("{y0}", L["y0"]).replace("{y1}", L["y1"])) for p in plans]
    sm.commit_answer(uid, ans, intent=False)
    return sm, uid, L


def state(sm) -> str:
    """Everything a refused change must leave as it was."""
    return json.dumps({"revision": sm.revision, "values": sm.values, "answers": {k: u.answer for k, u in sm.units.items()},
                       "history": len(sm.history)}, sort_keys=True, default=str)


def shown(path, x_from: float, x_to: float) -> list[float]:
    """What the drawing's horizontal dimensions in [x_from, x_to] show, in mm."""
    out = []
    for d in ezdxf.readfile(path).modelspace().query("DIMENSION"):
        if x_from <= d.dxf.defpoint2.x <= x_to and abs(d.dxf.defpoint2.y - d.dxf.defpoint3.y) < 1e-6:
            out.append(round(float(d.get_measurement()) * float(d.override().get("dimlfac", 1.0) or 1.0), 3))
    return sorted(out)


# ── valid ─────────────────────────────────────────────────────────────────────────


def test_a_valid_change_is_applied_its_dimension_says_it_and_one_undo_takes_it_back(tmp_path):
    sm, uid, _L = nib_sheet(tmp_path)
    before = sm.current()
    r = sm.apply({f"{uid}.WallThickness": 450.0})
    assert r.ok and not r.failures and r.changed
    out = str(tmp_path / "edited.dxf")
    sm.export(out)
    assert 450.0 in shown(out, 900, 1600) and 400.0 not in shown(out, 900, 1600), "the wall's own dimension shows the new size"
    assert sm.undo() and sm.current() == before


# ── invalid: the edit itself cannot be drawn ──────────────────────────────────────


def test_a_size_through_zero_is_an_invalid_edit_naming_the_check_the_value_the_entities_and_nothing_changes(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    before = state(sm)
    r = sm.apply({f"{uid}.OuterWall": -10.0})
    assert not r.ok and r.failures and all(f["kind"] in KINDS for f in r.failures)
    positive = next(f for f in r.failures if f["check"] == "POSITIVE")
    assert positive["kind"] == "invalid_edit" and positive["values"] == ["OuterWall"] and "cannot be zero or negative" in positive["basis"]
    walls = [f for f in r.failures if f["check"] == "GEOMETRY"]
    assert walls and all(f["kind"] == "invalid_edit" for f in walls), [f["basis"] for f in walls]
    left = next(f for f in walls if "LeftWall" in f["parts"])
    assert "the size of OuterWall" in left["basis"] and "through zero" in left["basis"], "the gap OuterWall owns goes through zero"
    assert any("RightWall" in f["parts"] and "the size of OuterWall" in f["basis"] for f in walls), "its other occurrence owns the right wall's gap"
    assert left["entities"] and "(" in left["entities"][0] and all(isinstance(i, int) for i in left["items"]), "the id and the DXF handle; sheet indices"
    assert not any(f["existing"] for f in r.failures) and state(sm) == before, "refused: nothing changed"
    assert summary(r.failures).startswith(f"{len(r.failures)} check(s) failed — ")


def test_members_running_into_each_other_are_an_invalid_edit_naming_both_parts(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    sm.apply_plan(uid, {"instruction": "Change the clear span to 3600, the left side stays fixed. " + FOLLOW_ALL})
    before = state(sm)
    r = sm.apply({f"{uid}.ClearSpan": 100.0})
    clashes = [f for f in r.failures if f["check"] == "CLASH"]
    assert not r.ok and clashes and all(f["kind"] == "invalid_edit" for f in clashes)
    assert any(set(f["parts"]) >= {"RightWall"} and any(p.startswith("Haunch") for p in f["parts"]) for f in clashes)
    assert all(len(f["entities"]) == 2 and len(f["items"]) == 2 for f in clashes) and state(sm) == before


# ── incomplete model: the change could be drawn, the model does not carry it ──────


def test_an_entity_the_model_does_not_tie_is_an_incomplete_model_and_binding_it_as_said_makes_the_change_valid(tmp_path):
    sm, uid, L = nib_sheet(tmp_path)
    before = state(sm)
    r = sm.apply({f"{uid}.WallThickness": 550.0})  # the wall's face moves 150 mm, past the nib's far end 100 mm away
    assert not r.ok
    (f,) = [f for f in r.failures if f["check"] == "GEOMETRY"]
    assert f["kind"] == "incomplete_model" and f["says"] == "the model does not carry this change" and not f["existing"]
    assert f"ends on {L['x2']}, which the change moves +150.0 mm, and on {L['x3']}, which stays" in f["basis"]
    assert "no value or dimension owns that gap" in f["basis"] and f"set {L['x3']} out from {L['x2']} (set_formulas)" in f["basis"]
    assert state(sm) == before
    # bound as the refusal says, the same change is taken
    (tmp_path / "bound").mkdir()
    sm2, uid2, _ = nib_sheet(tmp_path / "bound", nib="{x2} + 100")
    assert sm2.apply({f"{uid2}.WallThickness": 550.0}).ok


# ── the check fails already: not this edit's doing ───────────────────────────────


def test_a_check_the_sheet_already_fails_is_said_to_be_existing_not_blamed_on_the_edit(tmp_path):
    sm, uid, L = nib_sheet(tmp_path)
    sm.values.setdefault(uid, {})["WallThickness"] = 600.0  # a state saved before a check could see it: the nib already past the face
    r = sm.apply({f"{uid}.SlabThickness": 450.0})  # an edit that does not touch the nib
    assert not r.ok
    (f,) = r.failures
    assert f["existing"] is True and f["basis"].startswith("it fails on the sheet as it stands too — this change did not cause it")
    assert f["kind"] == "incomplete_model" and f"{L['x2']}, +200.0 mm from where it is drawn" in f["basis"], "measured from the drawing"
    assert "already failed before this change" in summary(r.failures)


# ── a promise, a rule, the solver ────────────────────────────────────────────────


def test_a_change_that_moves_what_an_accepted_plan_keeps_is_a_broken_promise_naming_the_plan_and_the_entities(tmp_path):
    keep_face = {"id": "P7", "status": "accepted", "instruction": "the wall's face stays where it is",
                 "driver": {"parameter": "SlabThickness", "requested_value": 400.0, "pairs": [["{y0}", "{y1}"]]},
                 "anchor": {"policy": "start_fixed", "source": "person"},
                 "directives": [{"target": "{x2}", "kind": "line", "mode": "keep_fixed", "status": "accepted"}]}
    sm, uid, _L = nib_sheet(tmp_path, plans=[keep_face])
    assert [p["id"] for p in sm.unit(uid).answer.get("plans", []) if p.get("status") == "accepted"] == ["P7"]
    before = state(sm)
    r = sm.apply({f"{uid}.WallThickness": 420.0})
    (f,) = [f for f in r.failures if f["check"] == "PLAN"]
    assert f["kind"] == "broken_promise" and f["plan"] == "P7" and "accepted plan P7 says it stays" in f["basis"]
    assert f["entities"] and f["items"], "the entities on the line the plan keeps"
    assert state(sm) == before


@pytest.mark.skipif(not BRIDGE["available"], reason=f"the production rule bridge cannot run here: {BRIDGE.get('reason')}")
def test_a_rule_bound_to_the_sheet_is_said_as_a_rule(tmp_path):
    from dataclasses import replace

    from dxf_autoparam.plan_bench import Box

    b = replace(Box(), detail=False)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    sm.bind_domain(truth_binding(sm, us, b, family="highway_rcc_box"))
    r = sm.apply({f"{us}.OuterWall": 250.0})
    rules = [f for f in r.failures if f["check"] == "RULE"]
    assert not r.ok and rules and all(f["kind"] == "rule" for f in rules)
    assert any("Outer wall thickness < 0.3m" in f["message"] for f in rules)


def test_a_formula_outside_its_domain_is_a_solver_failure_not_a_crash(tmp_path):
    sm, uid, _L = nib_sheet(tmp_path, nib="{x2} + WallThickness * sqrt((WallThickness - 300) / WallThickness) / 2")
    assert sm.apply({f"{uid}.WallThickness": 420.0}).ok, "inside its domain the formula sets the nib out"
    before = state(sm)
    r = sm.apply({f"{uid}.WallThickness": 250.0})
    (f,) = r.failures
    assert f["check"] == "SOLVER" and f["kind"] == "solver_failure" and "cannot regenerate" in f["message"]
    assert state(sm) == before


# ── a commit that would stop a view following ────────────────────────────────────


def test_a_commit_that_would_stop_a_shared_size_driving_a_view_is_refused_with_its_failures_and_nothing_changes(tmp_path):
    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    other = next(k for k in sm.units if k != uid)
    sm.share("OuterWall", [(uid, "c0"), (other, "c0")])
    before = state(sm)
    ans = copy.deepcopy(sm.unit(uid).answer)
    ans["parameters"] = [p for p in ans["parameters"] if p["name"] != "OuterWall"]
    with pytest.raises(SheetError, match="refused, nothing changed") as err:
        sm.commit_answer(uid, ans, intent=False)
    unbound = [f for f in err.value.failures if f["check"] == "UNBOUND"]
    assert unbound and all(f["kind"] == "incomplete_model" and f["values"] == ["OuterWall"] and not f["existing"] for f in unbound)
    assert state(sm) == before and sm.apply({"OuterWall": 350.0}).ok


# ── the agent: a solver failure in its own edit, an ambiguous instruction ────────


def test_the_agent_reads_a_formula_that_cannot_be_evaluated_as_a_refusal_and_a_loop_it_closed_the_other_way_as_a_note(tmp_path):
    from test_agent import ScriptedGemini, call

    sm, uid, L = nib_sheet(tmp_path)
    script = [[call("set_formulas", items=[{"line": L["x3"], "expr": f"{L['x2']} + NibLength"}])],
              [call("set_formulas", items=[{"line": L["x2"], "expr": f"{L['x3']} - 100"}, {"line": L["x3"], "expr": f"{L['x2']} + 100"}])],
              [call("finish", summary="done")], [call("finish", summary="done")]]
    gem = ScriptedGemini(script)
    agent_parametrize(sm.path, gem=gem, log=lambda *a: None, start=sm.unit(uid).answer)
    (bad,) = gem.seen[0][0]["result"]
    assert not bad["ok"] and bad["failure"]["code"] == "V4" and bad["failure"]["repair"] == "agent" and "NibLength" in bad["failure"]["cause"]
    x2, x3 = gem.seen[1][0]["result"]
    assert x2["ok"] and x3["ok"], "a loop of two lines is one relation said twice: the engine keeps it once"
    assert any("would close a loop" in n and f"kept as {L['x3']} = {L['x2']}" in n for n in x2.get("note", [])), \
        "the formula kept is not the one written: the model is told which way round it was kept"


def test_an_ambiguous_instruction_is_asked_and_nothing_is_applied(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    before = state(sm)
    plan = sm.plan(uid, {"instruction": "Make the slab 450 thick."})
    assert plan["status"] == "needs_decision"
    q = next(q for q in plan["questions"] if "which value is meant" in q["text"])
    assert "BottomSlab" in q["text"] and "TopSlab" in q["text"], "both readings are offered, neither is guessed"
    with pytest.raises(SheetError, match="needs_decision"):
        sm.apply_plan(uid, {"instruction": "Make the slab 450 thick."})
    assert state(sm) == before
