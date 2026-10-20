"""Design intent: which side of a size stays when it changes, decided from the drawing, tried for real, stored as an ordinary plan.

Held on generated boxes (one to three cells) and on every example drawing, with sizes named the way an agent names them: nothing here is
about one drawing, and what is held is the guarantees — a symmetric structure stays symmetric, a structure stands on its base, a person's
choice outranks the default, no size stops being an input, the drawing is reproduced exactly at its drawn values."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from dxf_autoparam import design_intent as di
from dxf_autoparam.ai.run import SheetBench
from dxf_autoparam.crossview import EMPTY_ANSWER, SheetModel
from dxf_autoparam.plan import drives_pairs
from dxf_autoparam.plan_bench import Box, box_answer, box_gad
from dxf_autoparam.regen import regenerate_program
from dxf_autoparam.validator import baseline

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples").glob("*.dxf"))


def box_sheet(tmp_path: Path, cells: int, intent: bool = True) -> tuple[SheetModel, str, dict]:
    """A generated box of `cells` cells, parametrized the way the generator's answer says, with or without the engine's own design intent."""
    b = Box(cells=cells, span=2500.0)
    g = box_gad(tmp_path / f"box{cells}.dxf", b)
    sm = SheetModel.open(g["path"])
    two = next(k for k, u in sm.units.items() if len(u.views) == 2)
    sec = max(sm.units[two].views, key=lambda v: sm.layout.group(v).bbox[3])
    uid = sm.unit_of_view[sec]
    sm.commit_answer(uid, box_answer(sm, uid, g["box"], g["handles"]), intent=intent)
    return sm, uid, g


def independent_sizes(sm: SheetModel, uid: str, limit: int = 10) -> dict:
    """Sizes the generic set-out itself holds independent (the spanning tree it is built on), named between their two lines as an agent names them."""
    an = sm.pristine_analysis(uid)
    u = an.drawing.units_mm
    rows = []
    for p in baseline(an).params.values():
        if p.kind != "length" or not p.measures or p.value <= 0:
            continue
        a, b = p.measures
        rows.append({"name": f"Size{len(rows) + 1:02d}", "label": "", "component": "", "kind": "length", "from_datum": a, "to_datum": b,
                     "value": round(abs(an.datums[b].value - an.datums[a].value) * u, 6)})
        if len(rows) >= limit:
            break
    return {**copy.deepcopy(EMPTY_ANSWER), "parameters": rows}


def worst_error_mm(prog) -> float:
    r = regenerate_program(prog, {}, check=False)
    an = prog.analysis
    return max((max(math.dist(r.pts[it.index][k], p) for k, p in enumerate(it.pts)) for it in an.drawing.items if it.index in r.pts and it.pts), default=0.0) * an.drawing.units_mm


# ── what the evidence says ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cells", [1, 2, 3])
def test_a_symmetric_box_grows_equally_on_both_sides_and_says_why(tmp_path, cells):
    sm, uid, _g = box_sheet(tmp_path, cells)
    prog = sm.unit(uid).prog
    why = sm.growth(f"{uid}.ClearSpan")[0]["intent"]
    assert why["source"] == di.SOURCE and why["status"] == "decided" and why["policy"] == "centered"
    assert "mirror" in why["evidence"][0] and why["centre"] in why["evidence"][0]
    v0, v1 = prog.datum_values(), prog.datum_values({"ClearSpan": prog.params["ClearSpan"].value + 1.0})
    walls = next(d for d in di.drivers(prog, sm.unit(uid).answer) if d.name == "OuterWall").pairs  # the outer walls: their outer faces are the box's two sides
    lo, hi = min((a for a, _b in walls), key=lambda d: v0[d]), max((b for _a, b in walls), key=lambda d: v0[d])
    assert abs(v1[hi] - v0[hi]) > 0 and v1[lo] - v0[lo] == pytest.approx(-(v1[hi] - v0[hi])), "the box's two sides move the same distance apart"


@pytest.mark.parametrize("cells", [1, 3])
def test_a_box_stands_on_its_base_so_a_slab_grows_upward(tmp_path, cells):
    sm, uid, _g = box_sheet(tmp_path, cells)
    (row,) = sm.growth(f"{uid}.TopSlab")
    assert row["mode"] == "start", "the bottom line stays, the top line moves"
    assert row["intent"]["policy"] == "start_fixed"
    assert row["intent"]["status"] == "provisional" and "assumed" in row["intent"]["evidence"][0], "a convention, said as one (the plan carries the decision's status)"


def test_the_default_is_the_engines_own_plan_and_is_not_what_the_agent_starts_from(tmp_path):
    sm, uid, _g = box_sheet(tmp_path, 2)
    plans = sm.unit(uid).answer["plans"]
    assert plans and all(di.derived(p) and p["status"] == "accepted" for p in plans)
    assert not di.strip(sm.unit(uid).answer).get("plans")
    assert [p["id"] for p in plans] == sorted(p["id"] for p in plans if p["id"].startswith("I_"))


def test_saved_work_from_before_the_design_intent_gets_it_when_opened_and_only_once(tmp_path, monkeypatch):
    from dxf_autoparam.workspace import SheetSession

    sm, uid, g = box_sheet(tmp_path, 2, intent=False)  # work as it was saved before the design intent existed
    assert "intent_axes" not in sm.unit(uid).answer
    project = tmp_path / "saved.autoparam.json"
    sm.save(str(project))
    sheet = SheetSession()
    sheet.open(g["path"], project=str(project))
    u = sheet.sm.unit(uid)
    assert u.answer["intent_axes"] and any(di.derived(p) for p in u.answer["plans"])
    assert not sheet.sm.history, "worked out on opening: not a step of the person's, nothing to undo"
    assert sheet.sm.growth(f"{uid}.ClearSpan")[0]["intent"]["source"] == di.SOURCE
    assert "intent_axes" not in di.strip(u.answer), "and the agent does not see it"
    # saved again and opened again: it is derived already, and is not worked out a second time
    again = tmp_path / "again.autoparam.json"
    sheet.sm.save(str(again))
    calls: list = []
    real = SheetModel.resolve_intent
    monkeypatch.setattr(SheetModel, "resolve_intent", lambda self, unit=None: calls.append(unit) or real(self, unit))
    SheetSession().open(g["path"], project=str(again))
    assert calls == []


def test_the_intent_worked_out_on_opening_is_kept_on_disk_so_the_next_opening_does_not_repeat_it(tmp_path, monkeypatch):
    from dxf_autoparam import autosave as keep
    from dxf_autoparam.workspace import SheetSession

    sm, uid, g = box_sheet(tmp_path, 2, intent=False)
    project = keep.project_path(g["path"], tmp_path / "state")
    project.parent.mkdir(parents=True)
    sm.save(str(project))  # the saved work of an earlier version: no design intent in it
    assert "intent_axes" not in json.loads(project.read_text())["answers"][uid]
    first = SheetSession()
    first.autosave = keep.Autosave(first, root=tmp_path / "state", every=60)
    first.open(g["path"])
    assert "intent_axes" in first.sm.unit(uid).answer
    assert first.autosave.flush() is True, "worked out on opening: written, although nobody changed anything"
    assert "intent_axes" in json.loads(project.read_text())["answers"][uid]
    calls: list = []
    real = SheetModel.resolve_intent
    monkeypatch.setattr(SheetModel, "resolve_intent", lambda self, unit=None: calls.append(unit) or real(self, unit))
    second = SheetSession()
    second.autosave = keep.Autosave(second, root=tmp_path / "state", every=60)
    second.open(g["path"])
    assert calls == [] and second.autosave.flush() is False, "the next opening has it, and has nothing to write"


def test_the_default_can_be_switched_off_for_a_comparison(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPARAM_DESIGN_INTENT", "0")
    sm, uid, _g = box_sheet(tmp_path, 1)
    assert not [p for p in sm.unit(uid).answer.get("plans", []) if di.derived(p)] and "intent_axes" not in sm.unit(uid).answer
    assert sm.growth(f"{uid}.ClearSpan")[0]["intent"] is None


def test_deriving_the_default_changes_no_value_and_no_line_at_the_drawn_sizes(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_i, uid, _ = box_sheet(tmp_path / "a", 2)
    without, uid2, _ = box_sheet(tmp_path / "b", 2, intent=False)
    a, b = with_i.unit(uid).prog, without.unit(uid2).prog
    assert worst_error_mm(a) < 1e-6 and worst_error_mm(b) < 1e-6
    assert {n: p.value for n, p in a.params.items() if p.source == "ai"} == {n: p.value for n, p in b.params.items() if p.source == "ai"}


def test_what_the_default_cannot_decide_it_leaves_to_the_set_out_and_says_so(tmp_path):
    sm = SheetModel.open(str(EXAMPLES[0]))
    uid = next(iter(sm.units))
    res = sm.commit_answer(uid, independent_sizes(sm, uid))
    for ax in res["intent"]["axes"]:
        assert ax["evidence"], ax
        if ax["status"] == "undecided":
            assert ax["policy"] == "as_set_out" and "no side could stay" in ax["evidence"][0]
        if ax["status"] == "provisional":
            assert "assumed" in ax["evidence"][0] and ax["policy"] in ("start_fixed", "end_fixed")


# ── a person's choice ──────────────────────────────────────────────────────────────────────────────


def test_a_persons_choice_outranks_the_default_and_the_default_is_derived_again_around_it(tmp_path):
    sm, uid, _g = box_sheet(tmp_path, 2)
    key = f"{uid}.ClearSpan"
    default = sm.growth(key)[0]
    assert default["intent"]["source"] == di.SOURCE
    sm.anchor(key, uid, "start")
    row = sm.growth(key)[0]
    assert row["mode"] == "start" and row["intent"]["source"] != di.SOURCE
    sm.resolve_intent(uid)  # re-deriving is not allowed to undo what a person chose
    assert sm.growth(key)[0]["mode"] == "start" and sm.growth(key)[0]["intent"]["source"] != di.SOURCE
    assert any(di.derived(p) for p in sm.unit(uid).answer["plans"]), "and the other sizes keep the engine's default"
    assert sm.undo() and sm.undo(), "the choice and the re-deriving after it are two steps, like any other"
    back = sm.growth(key)[0]
    assert back["intent"]["source"] == di.SOURCE and back["mode"] == default["mode"], "undone, the default is back"


def test_the_page_reads_the_growth_of_a_value_and_can_choose_a_side_or_derive_the_intent_again(tmp_path):
    from dxf_autoparam.workspace import SheetSession

    sm, uid, _g = box_sheet(tmp_path, 3, intent=False)  # named by the agent, the default not derived yet (work from before it existed)
    sheet = SheetSession()
    sheet.sm = sm
    key = f"{uid}.ClearSpan"
    assert sheet.param(key)["growth"][0]["intent"] is None
    out = sheet.edit("intent", {"unit": uid})["result"]
    assert out[uid]["changed"] is True and any(a["status"] == "decided" for a in out[uid]["axes"])
    assert sheet.param(key)["growth"][0]["intent"]["source"] == di.SOURCE
    sheet.edit("anchor", {"name": key, "unit": uid, "mode": "end"})
    assert sheet.param(key)["growth"][0]["intent"]["source"] != di.SOURCE, "a person's choice, not the engine's"
    with pytest.raises(Exception, match="no unit"):
        sheet.edit("intent", {"unit": "U99"})


@pytest.mark.parametrize("cells, to", [(1, 3100.0), (2, 2900.0), (3, 2200.0)])
def test_changing_a_value_moves_every_member_where_the_generator_draws_it_centred(tmp_path, cells, to):
    """Wider or narrower, the whole box — walls, footing, wings, the pitching on them — is where the generator draws it at that span, about the centre
    line: the engine's own default, with no instruction and no person's plan."""
    from test_intent_plan import off_intent

    sm, uid, g = box_sheet(tmp_path, cells)
    assert not [p for p in sm.unit(uid).answer["plans"] if not di.derived(p)], "no plan of a person: this is the default"
    r = sm.apply({f"{uid}.ClearSpan": to})
    assert r.ok, r.errors
    assert off_intent(sm, g, to, "centered") == []


# ── every example drawing ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_example_gets_a_design_intent_that_holds_or_none_and_loses_no_input(path):
    sm = SheetModel.open(str(path))
    for uid in list(sm.units):
        answer = independent_sizes(sm, uid)
        if not answer["parameters"]:
            continue
        before_prog, _ = sm._trial_builder(uid)(answer)
        before = di.drivers(before_prog, answer)
        res = sm.commit_answer(uid, answer)
        assert "intent" in res or res.get("intent_skipped"), res
        prog = sm.unit(uid).prog
        assert worst_error_mm(prog) < 1e-6, "the drawing is reproduced exactly at its drawn values"
        for p in sm.unit(uid).answer.get("plans", []):
            row = next(r for r in prog.intent["plans"] if r["id"] == p["id"])
            assert p["status"] == "accepted" and row["ok"], row
        for d in before:  # nothing the agent named stops being an input, or stops driving what it drove
            assert d.name in prog.params, f"{d.name} would stop being an input"
            assert not drives_pairs(prog, d.name, d.pairs), f"{d.name} no longer drives {d.pairs}"


# ── said to the person ────────────────────────────────────────────────────────────────────────────


def test_the_verdict_notes_what_rests_on_convention_or_could_not_be_decided():
    axes = [{"axis": "x", "assembly": "x1", "policy": "start_fixed", "centre": None, "status": "provisional", "drivers": ["Span"], "evidence": ["assumed"], "dropped": [], "tried": []},
            {"axis": "y", "assembly": "y1", "policy": "as_set_out", "centre": None, "status": "undecided", "drivers": ["Height"], "evidence": ["no side"],
             "dropped": [{"name": "Cover", "why": "it would hang on Height"}], "tried": []},
            {"axis": "x", "assembly": "x9", "policy": "centered", "centre": "x4", "status": "decided", "drivers": ["Width"], "evidence": ["mirror"], "dropped": [], "tried": []}]
    bench = SimpleNamespace(commit_results={"U01": {"ok": True, "intent": {"axes": axes}}, "U02": {"ok": True, "intent_skipped": "it did not hold"}})
    notes = SheetBench.intent_notes(bench)
    assert any("U01: Span keep the left side and grow toward the right" in n and "a convention" in n for n in notes)
    assert any("U01: Height keep the direction the set-out gave them" in n and "no side could be chosen" in n for n in notes)
    assert any("Cover is left out" in n for n in notes) and any("U02" in n and "did not hold" in n for n in notes)
    assert not any("Width" in n for n in notes), "what evidence decided is not a note"


# ── how much of a unit is parametric, measured ────────────────────────────────────────────────────


def test_the_dimensions_a_named_value_drives_are_counted_and_the_rest_are_said_to_be_constants(tmp_path):
    from dxf_autoparam.status import dimension_drive

    sm, uid, _g = box_sheet(tmp_path, 2)
    d = dimension_drive(sm.unit(uid).prog)
    assert d["total"] == d["driven"] + d["constant"] + d["unread"] and d["driven"] > 0
    assert len(d["constants"]) == min(d["constant"], 8) and all(c["mm"] > 0 for c in d["constants"])
    assert d["unsteppable"] == []
    # nothing named: the dimensions all state sizes nothing named changes
    (tmp_path / "blank").mkdir()
    blank, uid2, _ = box_sheet(tmp_path / "blank", 2)
    blank.commit_answer(uid2, {**copy.deepcopy(EMPTY_ANSWER)}, intent=False)
    none = dimension_drive(blank.unit(uid2).prog)
    assert none["driven"] == 0 and none["constant"] + none["unread"] == none["total"] == d["total"]


def test_how_many_dimensions_are_driven_is_measured_once_per_program_not_at_every_step(tmp_path, monkeypatch):
    from dxf_autoparam import status
    from dxf_autoparam.workspace import SheetSession

    sm, uid, _g = box_sheet(tmp_path, 2)
    sheet = SheetSession()
    sheet.sm = sm
    calls: list = []
    real = status.dimension_drive
    monkeypatch.setattr(status, "dimension_drive", lambda prog, *a, **k: calls.append(prog) or real(prog, *a, **k))
    first = sheet.unit(uid)["dimensions"]
    sm.apply({f"{uid}.ClearSpan": sm.current()[f"{uid}.ClearSpan"] + 100.0})  # a step: the panel reads the unit again
    again = sheet.unit(uid)["dimensions"]
    assert len(calls) == 1 and again == first, "the same program: not measured again"
    sm.commit_answer(uid, di.strip(sm.unit(uid).answer))  # another program (the answer was committed again)
    sheet.unit(uid)
    assert len(calls) == 2


def test_the_page_is_told_how_many_dimensions_are_driven_and_the_verdict_notes_those_that_are_not(tmp_path):
    from dxf_autoparam.workspace import SheetSession

    sm, uid, _g = box_sheet(tmp_path, 2)
    sheet = SheetSession()
    sheet.sm = sm
    info = sheet.unit(uid)["dimensions"]
    assert info and info["driven"] > 0 and info["total"] == info["driven"] + info["constant"] + info["unread"]
    note = SheetBench.dimension_notes(SimpleNamespace(sm=sm, _lock=lambda: sheet.lock))
    assert (info["constant"] > 0) == bool(note)
    assert all(uid in n and "named value" in n for n in note)


# ── an axis that cannot be decided: the ways to settle it, each tried for real ────────────────────────


def pinned_box_sheet(tmp_path: Path, cells: int = 2) -> tuple[SheetModel, str, dict]:
    """A generated box whose vertical chain is pinned at BOTH ends by site levels (the structure's base and its top), with the slabs as sizes."""
    b = Box(cells=cells, span=2500.0)
    g = box_gad(tmp_path / f"pinned{cells}.dxf", b)
    sm = SheetModel.open(g["path"])
    two = next(k for k, u in sm.units.items() if len(u.views) == 2)
    sec = max(sm.units[two].views, key=lambda v: sm.layout.group(v).bbox[3])
    uid = sm.unit_of_view[sec]
    ans = box_answer(sm, uid, g["box"], g["handles"])
    an, um = sm.unit(uid).an, sm.unit(uid).sub.units_mm

    def line(at: float) -> str:
        return min((d for d in an.datums.values() if d.axis == "y"), key=lambda d: abs(d.value * um - at)).id

    ans["levels"] = [{"datum": line(0.0), "name": "BedLevel", "role": "site_input"},
                     {"datum": line(b.bottom + b.height + b.top), "name": "FormationLevel", "role": "site_input"}]
    sm.commit_answer(uid, ans)
    return sm, uid, g


def test_an_axis_pinned_at_both_ends_is_undecided_and_says_which_levels_stand_in_the_way(tmp_path):
    sm, uid, _g = pinned_box_sheet(tmp_path)
    row = sm.growth(f"{uid}.TopSlab")[0]
    assert row["intent"] is None and row["undecided"]["axis"] == "y"
    assert {b["level"] for b in row["undecided"]["blocked"]} == {"BedLevel", "FormationLevel"}
    assert "FormationLevel" in row["undecided"]["evidence"][0] and "would have to move" in row["undecided"]["evidence"][0]


def test_the_ways_to_settle_it_are_tried_for_real_and_only_what_settles_it_is_offered(tmp_path):
    sm, uid, _g = pinned_box_sheet(tmp_path)
    before = (sm.revision, len(sm.history), json.dumps(sm.unit(uid).answer, sort_keys=True))
    opts = sm.settle_options(f"{uid}.TopSlab", uid)
    assert (sm.revision, len(sm.history), json.dumps(sm.unit(uid).answer, sort_keys=True)) == before, "asking changes nothing"
    by = {c["id"]: c for c in opts["choices"]}
    assert set(by) == {"level:BedLevel", "level:FormationLevel"}
    top, bottom = by["level:BedLevel"], by["level:FormationLevel"]
    assert top["policy"] == "end_fixed" and top["stays"] == "the top side stays" and top["stops_being_input"] == ["BedLevel"]
    assert bottom["policy"] == "start_fixed" and bottom["stays"] == "the bottom side stays" and bottom["stops_being_input"] == ["FormationLevel"]
    assert any("TopSlab grows toward the top" in m for m in bottom["moves"]) and any("TopSlab grows toward the bottom" in m for m in top["moves"])
    # reading one slab instead of setting it does not settle a chain pinned at both ends: said, not offered
    assert {r["id"] for r in opts["rejected"]} == {"reading:BottomSlab", "reading:TopSlab"} and all("does not settle" in r["why"] for r in opts["rejected"])


def test_a_choice_is_the_persons_own_decision_one_step_and_the_default_is_derived_around_it(tmp_path):
    sm, uid, g = pinned_box_sheet(tmp_path)
    key = f"{uid}.TopSlab"
    depth = len(sm.history)
    out = sm.settle(key, uid, "level:FormationLevel")
    assert len(sm.history) == depth + 1, "one step: one undo takes it back"
    assert out["mode"] == "start" and out["intent"]["status"] == "decided" and "undecided" not in out
    assert out["intent"]["evidence"][0] == "your choice: Let FormationLevel follow the structure"
    ans = sm.unit(uid).answer
    assert {lv["name"]: lv["role"] for lv in ans["levels"]} == {"BedLevel": "site_input", "FormationLevel": "derived"}
    assert ans["settled"][0]["was"] == {"role": "site_input"} and "FormationLevel" not in sm.unit(uid).prog.params
    # the bottom stays, the top slab grows upward: where the generator draws it at the new thickness
    from test_intent_plan import points

    b = g["box"]
    assert sm.apply({key: b.top + 300.0}).ok
    um = sm.unit(uid).sub.units_mm

    def span(name: str) -> tuple[float, float]:
        ys = [p[1] * um for p in points(sm, g, name)]
        return min(ys), max(ys)

    assert span("BottomSlab") == pytest.approx((0.0, b.bottom), abs=1e-3)
    assert span("TopSlab") == pytest.approx((b.bottom + b.height, b.bottom + b.height + b.top + 300.0), abs=1e-3)
    assert sm.undo()
    # the other level freed instead: the top stays, everything below goes down with the thickening
    sm.undo()
    sm.settle(key, uid, "level:BedLevel")
    assert sm.apply({key: b.top + 300.0}).ok
    assert span("TopSlab") == pytest.approx((b.bottom + b.height - 300.0, b.bottom + b.height + b.top), abs=1e-3)
    assert span("BottomSlab") == pytest.approx((-300.0, b.bottom - 300.0), abs=1e-3)
    assert sm.undo()
    assert sm.undo()
    assert sm.growth(key)[0]["undecided"] and {lv["role"] for lv in sm.unit(uid).answer["levels"]} == {"site_input"}


def test_taking_a_choice_back_writes_back_what_it_changed(tmp_path):
    sm, uid, _g = pinned_box_sheet(tmp_path)
    key = f"{uid}.TopSlab"
    sm.settle(key, uid, "level:BedLevel")
    assert sm.growth(key)[0]["settled"][0]["choice"] == "level:BedLevel"
    sm.unsettle(uid, "level:BedLevel")
    ans = sm.unit(uid).answer
    assert "settled" not in ans and {lv["role"] for lv in ans["levels"]} == {"site_input"}
    assert sm.growth(key)[0]["undecided"], "undecided again, as it was"
    with pytest.raises(Exception, match="no choice"):
        sm.unsettle(uid, "level:BedLevel")


def test_a_choice_that_is_not_one_of_the_ways_is_refused_and_nothing_changes(tmp_path):
    sm, uid, _g = pinned_box_sheet(tmp_path)
    before = (sm.revision, len(sm.history))
    with pytest.raises(Exception, match="does not settle"):
        sm.settle(f"{uid}.TopSlab", uid, "reading:TopSlab")
    assert (sm.revision, len(sm.history)) == before


def test_a_value_the_person_set_for_a_freed_level_is_not_dropped_without_their_say(tmp_path):
    sm, uid, _g = pinned_box_sheet(tmp_path)
    key = f"{uid}.TopSlab"
    sm.apply({f"{uid}.FormationLevel": sm.current()[f"{uid}.FormationLevel"] + 0.1})
    opts = sm.settle_options(key, uid)
    free = next(c for c in opts["choices"] if c["id"] == "level:FormationLevel")
    assert free["discards"] == ["FormationLevel"]
    with pytest.raises(Exception, match="discard the value you set"):
        sm.settle(key, uid, "level:FormationLevel")
    sm.settle(key, uid, "level:FormationLevel", discard_values=True)
    assert "FormationLevel" not in sm.values.get(uid, {})


def test_derived_plans_keep_a_part_still_for_their_own_assembly_only(tmp_path):
    """The foundation a width plan keeps still is not kept still against the height plans that must move it (it is the engine's own default)."""
    sm, uid, _g = pinned_box_sheet(tmp_path)
    free = sm.settle_options(f"{uid}.TopSlab", uid)
    assert any(c["id"] == "level:BedLevel" and c["status"] == "decided" for c in free["choices"])


def test_the_page_asks_for_the_ways_and_chooses_one(tmp_path):
    from dxf_autoparam.workspace import SheetSession

    sm, uid, _g = pinned_box_sheet(tmp_path)
    sheet = SheetSession()
    sheet.sm = sm
    key = f"{uid}.TopSlab"
    assert sheet.param(key)["growth"][0]["undecided"]
    ways = sheet.settle_options(key, uid)
    assert [c["id"] for c in ways["choices"]] == sorted(c["id"] for c in ways["choices"]) or ways["choices"]
    sheet.edit("settle", {"name": key, "unit": uid, "choice": ways["choices"][0]["id"]})
    assert sheet.unit(uid)["settled"][0]["choice"] == ways["choices"][0]["id"]
    sheet.edit("unsettle", {"unit": uid, "choice": ways["choices"][0]["id"]})
    assert sheet.unit(uid)["settled"] == []


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_on_every_example_what_is_offered_for_an_undecided_axis_settles_it_exactly_and_what_is_not_is_said(path):
    """Sizes named the way an agent names them; whatever the engine offers for an axis it could not decide was tried for real, so choosing it settles
    that axis in one step, reproduces the drawing exactly at its drawn values, stops only the inputs it said, and one undo puts everything back."""
    sm = SheetModel.open(str(path))
    for uid in list(sm.units):
        answer = independent_sizes(sm, uid)
        if not answer["parameters"]:
            continue
        sm.commit_answer(uid, answer)
        for row in [r for r in sm.unit(uid).answer.get("intent_axes", []) if r["status"] == "undecided"][:1]:  # one axis per drawing keeps this affordable
            key = f"{uid}.{row['drivers'][0]}"
            opts = sm.settle_options(key, uid)
            assert opts["status"] == "undecided" and (opts["choices"] or opts["rejected"] or opts["notes"]), "it says what it tried, or why it tried nothing"
            for c in opts["choices"][:2]:
                before = (json.dumps(sm.unit(uid).answer, sort_keys=True), len(sm.history))
                before_inputs = di.inputs_of(sm.unit(uid).prog)
                sm.settle(key, uid, c["id"], discard_values=True)
                assert len(sm.history) == before[1] + 1
                prog = sm.unit(uid).prog
                assert worst_error_mm(prog) < 1e-6
                lost = sorted(before_inputs - set(prog.params))
                assert lost == c["stops_being_input"], (c["id"], lost, c["stops_being_input"])
                now = [a for a in sm.unit(uid).answer["intent_axes"] if a["axis"] == row["axis"] and set(row["drivers"]) & (set(a["drivers"]) | {x["name"] for x in a["dropped"]})]
                assert now and all(a["status"] != "undecided" for a in now), c["id"]
                assert sm.undo()
                assert (json.dumps(sm.unit(uid).answer, sort_keys=True), len(sm.history)) == before


def test_a_provisional_direction_is_shown_as_provisional_with_its_evidence():
    """The plans carry the decision's status and evidence, not what they were written with before it was known which side would be kept."""
    path = next(p for p in EXAMPLES if p.stem == "two_cell_box_section")
    sm = SheetModel.open(str(path))
    uid = next(iter(sm.units))
    answer = independent_sizes(sm, uid)
    sm.commit_answer(uid, answer)
    row = next(r for r in sm.unit(uid).answer["intent_axes"] if r["status"] == "provisional")
    shown = sm.growth(f"{uid}.{row['drivers'][0]}")[0]["intent"]
    assert shown["status"] == "provisional" and shown["evidence"] == row["evidence"] and "assumed" in shown["evidence"][0]
