"""What a run says of itself must be what the sheet shows — the gaps a live run on a real sheet exposed, each with the model scripted.

A live run on a real eight-view sheet ended "Complete: every criterion holds" while: a size the engine had refused was never made again (it only
looked repaired, because the engine takes a refused size back); a share the sheet refused in part was reported as applied; a relation was written
as a bare number; the model had said two clauses of the instruction would be handled by a plan and never stated one; and a plan view the engine
took for a table was never looked at. Each is held here, on small sheets, with no network."""

from __future__ import annotations

import copy

import pytest
from test_crossview import two_views, view
from test_run import Scripted, wait
from test_sheet import built_sheet

from dxf_autoparam.ai.loop import Budget
from dxf_autoparam.ai.scripted import call
from dxf_autoparam.crossview import EMPTY_ANSWER, SheetModel
from dxf_autoparam.workspace import SheetSession

INSTR = ("Parametrize every view. State in your plan which components and dimensions appear in more than one view and how they relate. "
         "Where something is ambiguous, record your assumption in the plan.")
Q1, Q2, Q3 = ("Parametrize every view", "State in your plan which components and dimensions appear in more than one view and how they relate",
              "Where something is ambiguous, record your assumption in the plan")


def reading(handled_by: tuple[str, str, str] = ("parts", "plan", "plan")):
    kinds = ("scope", "link_views", "process")
    return call("account_instruction", items=[{"quote": q, "kind": k, "meaning": "as read", "handled_by": h, **({"why": "test"} if h == "none" else {})}
                                               for q, k, h in zip((Q1, Q2, Q3), kinds, handled_by, strict=True)])


PLAIN = ("none", "none", "none")  # nothing is promised: the clauses are read and nothing more is claimed


def part(name: str) -> dict:
    return {"name": name, "type": "box", "level": "assembly", "parent": None, "regions": [], "entities": [], "existing": False, "parametrize": True,
            "evidence": [], "description": "", "confidence": 0.9}


def two_unit_session(tmp_path, script):
    """Two views, not drawn in line, each already parametrized (a part and the 3000 opening both state) — the model's earlier work."""
    sm = SheetModel.open(str(two_views(tmp_path / "two.dxf")))
    ua, ub = sm.unit_of_view[view(sm, "SECTION A-A")], sm.unit_of_view[view(sm, "SIDE ELEVATION")]
    for uid, name in ((ua, "Body"), (ub, "Shell")):
        sm.set_answer(uid, {**copy.deepcopy(EMPTY_ANSWER), "components": [part(name)], "parameters": [
            {"name": "OpeningWidth", "label": "Opening", "component": "", "kind": "length", "candidate": "c3", "value": 3000.0}]})
    sheet = SheetSession()
    sheet.sm = sm
    gem = Scripted(script)
    sheet.gem_factory = lambda: gem
    return sheet, sm, ua, ub, gem


def run(sheet, **opts):
    r = sheet.start_run({"instruction": INSTR, "scope": {"kind": "drawing"}, **({"options": opts} if opts else {})})
    return r["run"], wait(sheet, r["run"])


def tools(p, name):
    return [e for e in p["events"] if e["kind"] == "tool" and e["name"] == name]


def criterion(p, cid):
    return next(c for c in p["verdict"]["criteria"] if c["id"] == cid)


SHARE = {"items": [{"name": "OpeningWidth", "targets": [["U01", "c3"], ["U02", "c3"]], "evidence": ["both views state 3000"]}]}


def plan_call(**over):
    link = {"what": "opening", "kind": "dimension", "relation": "same_dimension", "appears_in": [{"unit": "U01", "value": "OpeningWidth"}, {"unit": "U02", "value": "OpeningWidth"}],
            "bound_by": "shared_value", "shared_value": "OpeningWidth", "evidence": ["both views state 3000"]}
    return call("state_plan", summary="one opening, drawn twice", links=[{**link, **over}], assumptions=[{"text": "the two 3000s are one opening", "why": "same words"}])


# ── a plan the model said would handle the instruction ───────────────────────────────────────────


def test_a_plan_the_model_promised_and_never_stated_stops_finish_once_and_fails_the_verdict(tmp_path):
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, [[reading()], [call("finish", summary="done")], [call("finish", summary="done")]])
    _rid, p = run(sheet)
    first, second = tools(p, "finish")
    assert not first["ok"] and "OPEN" in first["why"] and "handled by plan" in first["why"] and second["ok"]  # told once, then let go
    v = p["verdict"]
    assert v["state"] == "partial" and not criterion(p, "commitments_kept")["ok"]
    assert "State in your plan" in criterion(p, "commitments_kept")["detail"] and "state_plan" in criterion(p, "commitments_kept")["detail"]
    assert v["finish_summary"] == "done"  # what the model said it did is kept, whole


def test_a_stated_plan_is_held_to_the_sheet_and_keeps_the_promise(tmp_path):
    sheet, sm, _ua, _ub, _gem = two_unit_session(tmp_path, [[reading()], [call("share_sizes", **SHARE)], [plan_call()], [call("finish", summary="shared and stated")]])
    rid, p = run(sheet)
    assert p["status"] == "completed", p["verdict"]
    assert criterion(p, "commitments_kept")["ok"] and criterion(p, "plan_holds")["ok"]
    link = p["verdict"]["plan"]["links"][0]
    assert link["holds"] and link["bound_by"] == "shared_value" and [x["unit"] for x in link["appears_in"]] == ["U01", "U02"]
    assert sm.stated_plan["run"] == rid and sm.stated_plan["assumptions"][0]["text"].startswith("the two 3000s")
    assert tools(p, "state_plan")[0]["ok"] and "kept in the plan" in tools(p, "state_plan")[0]["summary"]


def test_a_link_that_claims_a_binding_the_sheet_does_not_hold_is_refused_and_stays_open(tmp_path):
    script = [[reading()], [plan_call()], [call("finish", summary="x")], [call("finish", summary="x")]]  # claims a shared value nobody made
    sheet, sm, _ua, _ub, _gem = two_unit_session(tmp_path, script)
    _rid, p = run(sheet)
    refused = tools(p, "state_plan")[0]
    assert not refused["ok"] and "no shared value 'OpeningWidth'" in refused["why"]
    assert sm.stated_plan["links"] == [] and sm.stated_plan["summary"] and p["verdict"]["state"] == "partial"  # the summary stands; the link that did not hold was not kept
    assert not criterion(p, "refusals_repaired")["ok"] and p["verdict"]["refused"][0]["item"] == "plan:opening"


def test_a_link_the_model_says_is_only_noted_closes_a_refused_share_and_says_so(tmp_path):
    bad_share = {"items": [{"name": "Missing", "targets": [["U01", "c1"], ["U02", "c4"]]}]}  # 3000 against 1000: not one size
    noted = {"what": "pier", "relation": "same_dimension", "bound_by": "noted_only", "shared_value": "Missing",
             "appears_in": [{"unit": "U01", "part": "Body"}, {"unit": "U02", "part": "Shell"}], "note": "the views do not state one size"}
    script = [[reading(PLAIN)], [call("share_sizes", **bad_share)], [call("state_plan", links=[noted])], [call("finish", summary="x")]]
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, script)
    _rid, p = run(sheet)
    assert not tools(p, "share_sizes")[0]["ok"]
    v = p["verdict"]
    assert v["state"] == "completed" and v["refused"] == []
    assert v["given_up"][0]["item"] == "share:Missing" and "only noted" in v["given_up"][0]["how"]
    assert any("left out on purpose: share:Missing" in n for n in v["notes"]) and "note" in v["headline"]


# ── a share the sheet refuses in part ─────────────────────────────────────────────────────────────


def test_a_share_refused_in_part_is_not_ok_and_stays_open_until_the_sheet_holds_it(tmp_path):
    both = {"items": [*SHARE["items"], {"name": "Missing", "targets": [["U01", "c1"], ["U02", "c4"]]}]}
    script = [[reading(PLAIN)], [call("share_sizes", **both)], [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, sm, _ua, _ub, _gem = two_unit_session(tmp_path, script)
    _rid, p = run(sheet)
    share = tools(p, "share_sizes")[0]
    assert not share["ok"] and "refused" in share["summary"]
    assert share["result"]["partial"] is True and len(share["result"]["applied"]) == 1  # what held stays applied, and is said
    assert "OpeningWidth" in sm.current()
    v = p["verdict"]
    assert v["state"] == "partial" and not criterion(p, "refusals_repaired")["ok"]
    assert v["refused"][0]["item"] == "share:Missing" and "do not state one size" in v["refused"][0]["why"]


def test_the_repair_of_a_refused_share_is_the_sheet_holding_it(tmp_path):
    bad = {"items": [{"name": "Missing", "targets": [["U01", "c1"], ["U02", "c4"]]}]}
    good = {"items": [{"name": "Missing", "targets": [["U01", "c1"], ["U02", "c0"]]}]}  # 3000 and 3000
    sheet, sm, _ua, _ub, _gem = two_unit_session(tmp_path, [[reading(PLAIN)], [call("share_sizes", **bad)], [call("share_sizes", **good)], [call("finish", summary="x")]])
    _rid, p = run(sheet)
    assert [t["ok"] for t in tools(p, "share_sizes")] == [False, True]
    assert p["verdict"]["state"] == "completed" and p["verdict"]["refused"] == [] and "Missing" in sm.current()


# ── a size the engine refused ─────────────────────────────────────────────────────────────────────

GHOST = {"items": [{"name": "Ghost", "part": "Body", "candidate": "c999"}]}  # a candidate nobody found: refused


def test_a_refused_size_is_not_repaired_by_having_been_taken_back(tmp_path):
    script = [[reading(PLAIN)], [call("open_unit", unit="U01")], [call("define_parameters", **GHOST)], [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, script)
    _rid, p = run(sheet)
    assert not tools(p, "define_parameters")[0]["ok"]
    first, _second = tools(p, "finish")
    assert not first["ok"] and "refused and never repaired: Ghost" in first["why"] and "remove it" in first["why"]
    v = p["verdict"]
    assert v["state"] == "partial" and v["refused"][0]["item"] == "Ghost" and not criterion(p, "refusals_repaired")["ok"]


def test_a_refused_size_the_model_removes_is_left_out_on_purpose_and_said(tmp_path):
    script = [[reading(PLAIN)], [call("open_unit", unit="U01")], [call("define_parameters", **GHOST)], [call("remove", parameters=["Ghost"])], [call("finish", summary="x")]]
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, script)
    _rid, p = run(sheet)
    v = p["verdict"]
    assert v["state"] == "completed" and v["refused"] == []
    assert [g["item"] for g in v["given_up"]] == ["Ghost"] and v["given_up"][0]["how"] == "removed by the model"
    assert any(n.startswith("left out on purpose: Ghost") for n in v["notes"])


def test_a_size_refused_then_made_properly_is_repaired_by_the_engine_keeping_it(tmp_path):
    fixed = {"items": [{"name": "Ghost", "part": "Body", "candidate": "c1"}]}
    script = [[reading(PLAIN)], [call("open_unit", unit="U01")], [call("define_parameters", **GHOST)], [call("define_parameters", **fixed)], [call("finish", summary="x")]]
    sheet, sm, _ua, _ub, _gem = two_unit_session(tmp_path, script)
    _rid, p = run(sheet)
    assert p["verdict"]["state"] == "completed" and p["verdict"]["given_up"] == [] and "Ghost" in sm.unit("U01").prog.params


# ── a relation is a statement of what a quantity follows ──────────────────────────────────────────


def test_a_relation_that_names_nothing_is_refused_and_one_that_follows_a_value_is_kept(tmp_path):
    script = [[reading(PLAIN)], [call("open_unit", unit="U01")], [call("set_relation", name="Frozen", expr="7500")],
              [call("set_relation", name="Doubled", expr="OpeningWidth * 2")], [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, sm, _ua, _ub, _gem = two_unit_session(tmp_path, script)
    _rid, p = run(sheet)
    frozen, doubled = tools(p, "set_relation")
    assert not frozen["ok"] and "CONSTANT" in frozen["why"] and "no name in it" in frozen["why"]
    assert doubled["ok"]
    assert [r["name"] for r in sm.units["U01"].answer["relations"]] == ["Doubled"]
    assert p["verdict"]["refused"][0]["item"] == "Frozen"  # and nothing hides that it was refused


def test_a_refused_relation_taken_out_is_left_out_on_purpose(tmp_path):
    script = [[reading(PLAIN)], [call("open_unit", unit="U01")], [call("set_relation", name="Frozen", expr="7500")], [call("set_relation", name="Frozen", expr="")],
              [call("finish", summary="x")]]
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, script)
    _rid, p = run(sheet)
    assert p["verdict"]["state"] == "completed" and [g["item"] for g in p["verdict"]["given_up"]] == ["Frozen"]


def test_a_unit_that_was_opened_and_never_parametrized_is_said(tmp_path):
    sheet = SheetSession(str(two_views(tmp_path / "two.dxf")))  # nothing parametrized
    gem = Scripted([[reading(PLAIN)], [call("open_unit", unit="U01")], [call("finish", summary="x")], [call("finish", summary="x")]])
    sheet.gem_factory = lambda: gem
    _rid, p = run(sheet)
    assert any(n.startswith("views never parametrized in this run: U01, U02") for n in p["verdict"]["notes"])


# ── a group the engine doubts must be looked at ───────────────────────────────────────────────────


def sheet_with_a_doubted_table(tmp_path, script):
    sheet = SheetSession(str(built_sheet(tmp_path / "sheet.dxf")))
    table = next(g for g in sheet.sm.layout.groups if g.kind == "table")
    table.counts = {**table.counts, "geometry": 139, "texts": 14, "dimensions": 29, "curves": 8}  # the content of a drawn view
    gem = Scripted(script)
    sheet.gem_factory = lambda: gem
    return sheet, table.id, gem


def test_inspect_sheet_counts_views_as_views_and_says_what_the_other_groups_hold(tmp_path):
    sheet, tid, _gem = sheet_with_a_doubted_table(tmp_path, [[reading(PLAIN)], [call("inspect_sheet")], [call("finish", summary="x")], [call("finish", summary="x")]])
    _rid, p = run(sheet)
    res = tools(p, "inspect_sheet")[0]["result"]
    assert all(v["kind"] == "view" for v in res["views"]) and len(res["views"]) == len(sheet.sm.layout.views())
    other = {g["id"]: g for g in res["other_groups"]}
    assert other[tid]["drawn"] == 139 and "taken for a table" in other[tid]["doubt"]
    assert all("doubt" not in g for gid, g in other.items() if gid != tid)
    assert res["plan"]["stated"] is False
    assert "other groups (1 doubted)" in tools(p, "inspect_sheet")[0]["summary"]


def test_a_doubted_group_nobody_looked_at_is_said_and_one_that_was_looked_at_is_not(tmp_path):
    sheet, tid, _gem = sheet_with_a_doubted_table(tmp_path, [[reading(PLAIN)], [call("finish", summary="x")], [call("finish", summary="x")]])
    rid, p = run(sheet)
    first = tools(p, "finish")[0]
    assert not first["ok"] and "taken for a table" in first["why"]
    assert any(n.startswith("not examined: ") and tid in n for n in p["verdict"]["notes"])

    sheet, tid, _gem = sheet_with_a_doubted_table(tmp_path, [[reading(PLAIN)], [call("zoom_view", view=tid)], [call("finish", summary="x")]])
    rid, p = run(sheet)
    zoom = tools(p, "zoom_view")[0]
    assert zoom["ok"] and zoom["result"]["group"]["id"] == tid and "of " + tid in zoom["summary"]
    assert tools(p, "finish")[0]["ok"] and not any("not examined" in n for n in p["verdict"]["notes"])
    assert sheet.runs[rid].bench.looked == {tid}


def test_the_model_can_say_what_a_doubted_group_is_and_it_becomes_a_unit_that_takes_no_other_units_name(tmp_path):
    script = [[reading(PLAIN)], [call("zoom_view", view="T01")],
              [call("describe_views", views=[{"id": "T01", "kind": "view", "view_type": "plan", "name": "PLAN"}])], [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, _tid, _gem = sheet_with_a_doubted_table(tmp_path, script)
    before = set(sheet.sm.units)
    _rid, p = run(sheet)
    assert tools(p, "describe_views")[0]["ok"] and set(sheet.sm.units) == before | {"UT01"}
    assert any("never parametrized" in n and "UT01" in n for n in p["verdict"]["notes"])  # a view nobody parametrized is said


# ── the budget never pauses a run that was not asked to be paused, and a reached limit is lifted ──


def chatty(n: int) -> list:
    return [[call("find_values", value_mm=3000)] for _ in range(n)]


def test_by_default_a_long_run_is_not_paused(tmp_path):
    assert Budget().soft_turns == 0 and Budget.from_env().soft_turns == 0 and Budget().max_turns >= 1000
    assert Budget().with_(soft_turns=5, max_turns=3).soft_turns == 3 and Budget().with_(soft_turns=0).soft_turns == 0
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, [[reading(PLAIN)], [call("open_unit", unit="U01")], *chatty(60), [call("finish", summary="x")]])
    _rid, p = run(sheet)
    assert p["status"] == "completed" and p["usage"]["turns"] > 60 and p["usage"]["limits"]["soft_turns"] == 0
    assert not any(e["kind"] == "state" and e["to"] == "paused" for e in p["events"])


@pytest.mark.parametrize("limit", [{"max_turns": 4}, {"max_tokens": 40}, {"max_tool_calls": 4}])  # a scripted turn is one call and 10 tokens
def test_continuing_a_run_that_reached_a_limit_lifts_that_limit(tmp_path, limit):
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, [[reading(PLAIN)], [call("open_unit", unit="U01")], *chatty(3), [call("finish", summary="x")]])
    rid, p = run(sheet, budget=limit)
    assert p["status"] == "exhausted" and p["verdict"] is None
    key = next(iter(limit))
    sheet.continue_run({"run": rid})  # no number to type: the limit that stopped the work is lifted
    p = wait(sheet, rid)
    assert p["status"] == "completed", p["verdict"]
    assert p["usage"]["limits"][key] > limit[key]
    assert any(e["kind"] == "note" and "limits lifted" in e["text"] and key in e["text"] for e in p["events"])
