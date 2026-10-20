"""A size stated in more than one unit is ONE size: the sheet says when the same name is carried by several units and nothing joins them.

A paid run said it would link the views with share_sizes, never called it, and the gate passed the clause because one unit (two views drawn in
projection) existed on the sheet. Seven names recurred across units — five with the same number — and the sheet held no shared value."""

from __future__ import annotations

from test_crossview import mini_gad

from dxf_autoparam.ai.run import Run, SheetBench
from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.generic import is_generated
from dxf_autoparam.workspace import SheetSession


def name_value(sm, uid: str, value: float, new: str) -> None:
    """Give the unit's analysis-named size of this number an engineering name."""
    old = next(n for n, p in sm.unit(uid).prog.params.items() if is_generated(n) and abs(p.value - value) < 1e-6)
    sm.rename(f"{uid}.{old}", new)


def sheet_with(tmp_path, first: float, second: float, name: str):
    sheet = SheetSession()
    sheet.sm = sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    one, two = list(sm.units)[:2]
    name_value(sm, one, first, name)
    name_value(sm, two, second, name)
    return sheet, sm, one, two


def links_clause(sheet, rid: str = "R1") -> dict:
    bench = SheetBench(Run(sheet, rid, "Make this whole drawing parametric. Link the views.", {"kind": "drawing"}))
    bench.ledger.append({"quote": "Link the views.", "kind": "link_views", "meaning": "x", "handled_by": "links", "quote_norm": "link the views"})
    return next(c for c in bench.commitments() if c["handled_by"] == "links")


def test_one_name_in_two_units_with_one_number_is_a_repeat_until_a_shared_value_joins_them(tmp_path):
    _sheet, sm, one, two = sheet_with(tmp_path, 300, 300, "WallThickness")
    rows = sm.unlinked_repeats()
    assert [r["name"] for r in rows] == ["WallThickness"] and rows[0]["same"] and rows[0]["units"] == sorted([one, two])
    assert rows[0]["values"] == {one: 300.0, two: 300.0} or rows[0]["values"] == {two: 300.0, one: 300.0}
    sm.share("WallThickness", [(one, "WallThickness"), (two, "WallThickness")])
    assert sm.unlinked_repeats() == [], "shared: one value, nothing left loose"


def test_a_name_only_one_unit_has_is_not_a_repeat(tmp_path):
    sheet = SheetSession()
    sheet.sm = sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    one, _two = list(sm.units)[:2]
    name_value(sm, one, 300, "WallThickness")
    assert sm.unlinked_repeats() == []


def test_the_links_commitment_reads_what_the_sheet_holds_not_that_one_unit_is_drawn_in_projection(tmp_path):
    sheet, sm, one, two = sheet_with(tmp_path, 300, 300, "WallThickness")
    assert any(len(u.views) > 1 for u in sm.units.values()), "the old test passed on this alone"
    clause = links_clause(sheet)
    assert not clause["ok"] and "WallThickness" in clause["why"] and "share_sizes" in clause["why"] and one in clause["why"] and two in clause["why"]
    sm.share("WallThickness", [(one, "WallThickness"), (two, "WallThickness")])
    assert links_clause(sheet)["ok"]


def test_a_plan_that_states_the_link_on_the_record_satisfies_the_clause(tmp_path):
    sheet, sm, one, two = sheet_with(tmp_path, 300, 300, "WallThickness")
    sm.stated_plan = {"run": "R1", "summary": "", "links": [{"what": "wall", "bound_by": "noted_only", "appears_in": [
        {"unit": one, "view": sm.units[one].views[0]}, {"unit": two, "view": sm.units[two].views[0]}]}], "assumptions": []}
    assert links_clause(sheet)["ok"], "said, with the places, to be only noted: on the record, not enforced"


def test_one_name_for_two_numbers_is_a_note_not_a_failed_commitment(tmp_path):
    sheet, sm, _one, _two = sheet_with(tmp_path, 300, 2200, "SlabDepth")
    rows = sm.unlinked_repeats()
    assert len(rows) == 1 and rows[0]["name"] == "SlabDepth" and not rows[0]["same"]
    assert links_clause(sheet)["ok"], "the engine cannot tell two sizes from one size seen again: it does not fail the model for it"
    bench = SheetBench(Run(sheet, "R2", "Make this whole drawing parametric.", {"kind": "drawing"}))
    notes = bench.repeat_notes()
    assert len(notes) == 1 and "SlabDepth" in notes[0] and "two sizes" in notes[0] and "300" in notes[0] and "2200" in notes[0]


def test_the_model_is_told_where_it_names_a_value_that_another_unit_already_has(tmp_path):
    sheet, sm, one, two = sheet_with(tmp_path, 300, 300, "WallThickness")
    bench = SheetBench(Run(sheet, "R1", "Make this whole drawing parametric.", {"kind": "drawing"}))
    wb = bench.open(one)
    said = wb._also_named("WallThickness")
    assert len(said) == 1 and said[0].startswith(f"{two}: 300 mm") and "share_sizes" in said[0]
    (tmp_path / "other").mkdir()
    sheet2, _sm2, one2, _two2 = sheet_with(tmp_path / "other", 300, 2200, "SlabDepth")
    said2 = SheetBench(Run(sheet2, "R3", "Make this whole drawing parametric.", {"kind": "drawing"})).open(one2)._also_named("SlabDepth")
    assert len(said2) == 1 and "2200 mm" in said2[0] and "rename" in said2[0]
    sm.share("WallThickness", [(one, "WallThickness"), (two, "WallThickness")])
    assert SheetBench(Run(sheet, "R4", "x", {"kind": "drawing"})).open(one)._also_named("WallThickness") == [], "a shared name is joined already"


def test_a_run_answered_by_two_models_says_so(tmp_path):
    from types import SimpleNamespace

    sheet, _sm, _one, _two = sheet_with(tmp_path, 300, 300, "WallThickness")
    run = Run(sheet, "R1", "Make this whole drawing parametric.", {"kind": "drawing"})
    bench = SheetBench(run)
    assert bench.model_notes() == [], "no loop yet"
    run.loop = SimpleNamespace(state=SimpleNamespace(usages=[{"model": "m-a"}] * 5 + [{"model": "m-b"}] * 2 + [{"model": "m-a", "cached": True}]))
    run.events += [{"kind": "retry", "model": "m-a", "why": "429"}] * 3 + [{"kind": "retry", "why": "no answer"}]
    assert bench.model_notes() == ["answered by more than one model: m-a 5 call(s), m-b 2 call(s) (3 attempt(s) were refused, too slow or unusable)"]
    run.loop = SimpleNamespace(state=SimpleNamespace(usages=[{"model": "m-a"}] * 3))
    assert bench.model_notes() == []
