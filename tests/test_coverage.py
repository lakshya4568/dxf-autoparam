"""Which units of the drawing a run really covered — said by the sheet, not by the model.

A live run's closing words said "U05–U09 were accounted for and left as drawn" while the sheet held work for U05, U06 and U07 and never opened U08 or U09;
and the gate said "1 thing remains" without saying that two of ten units were untouched."""

from __future__ import annotations

from test_crossview import mini_gad
from test_run import Scripted, wait

from dxf_autoparam.ai.coverage import sentence, table_md, unit_rows
from dxf_autoparam.ai.run import Run, SheetBench
from dxf_autoparam.ai.scripted import call
from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.generic import is_generated
from dxf_autoparam.workspace import SheetSession


def two_unit_sheet(tmp_path, name_it: bool = True):
    sheet = SheetSession()
    sheet.sm = sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    one, two = list(sm.units)[:2]
    if name_it:  # the first unit is parametrized: one value named
        sm.rename(f"{one}.{next(n for n, p in sm.unit(one).prog.params.items() if is_generated(n))}", "ClearSpan")
    return sheet, sm, one, two


def test_a_unit_is_parametrized_skipped_on_the_record_looked_at_or_untouched(tmp_path):
    _sheet, sm, one, two = two_unit_sheet(tmp_path)
    units = [one, two, "U98", "U99"]  # unknown units are not rows: a scope names the units the sheet has
    assert [r["unit"] for r in unit_rows(sm, units, {}, [], [])] == [one, two]
    rows = {r["unit"]: r for r in unit_rows(sm, [one, two], {}, [], [])}
    assert rows[one]["state"] == "parametrized" and rows[one]["covered"] and rows[one]["inputs"] >= 1
    assert rows[two]["state"] == "untouched" and not rows[two]["covered"]
    # opened, nothing kept: not covered, and not the same thing as skipped
    assert unit_rows(sm, [two], {two: {}}, [], [])[0]["state"] == "looked_at"
    assert not unit_rows(sm, [two], {two: {}}, [], [])[0]["covered"]
    # work in a workbench that is not applied yet counts for the gate that asks before applying
    assert unit_rows(sm, [two], {two: {"components": [{"name": "Box"}]}}, [], [])[0]["state"] == "parametrized"
    # skipped counts only with the reason ON THE CHECKLIST, for that unit, in words
    said = [{"id": "C1", "text": f"{two}: a single-line schematic, nothing to parametrize", "status": "skipped"}]
    row = unit_rows(sm, [two], {}, said, [])[0]
    assert row["state"] == "skipped" and row["covered"] and "schematic" in row["reason"]
    assert unit_rows(sm, [two], {}, [{"id": "C1", "text": f"{two} first", "status": "todo"}], [])[0]["state"] == "untouched", "a plan to do it is not a reason to skip it"
    assert unit_rows(sm, [two], {}, [{"id": "C1", "text": f"{two}0 and {two}x are other units", "status": "skipped"}], [])[0]["state"] == "untouched", "U2 is not U20"


def test_the_sentence_and_the_table_say_what_the_sheet_holds(tmp_path):
    _sheet, sm, one, two = two_unit_sheet(tmp_path)
    rows = unit_rows(sm, [one, two], {}, [], [{"unit": one, "item": "ClearHeight", "why": "x"}])
    assert sentence(rows) == f"1 of 2 units parametrized ({two} untouched)"
    md = table_md(rows)
    assert md.splitlines()[0].startswith("| unit |") and f"| {one} |" in md and f"| {two} |" in md and "ClearHeight" in md and "untouched" in md
    rows = unit_rows(sm, [one, two], {two: {}}, [], [])
    assert sentence(rows) == f"1 of 2 units parametrized ({two} looked at, nothing kept)"


def test_the_gate_asks_for_the_uncovered_units_only_when_the_whole_drawing_was_asked(tmp_path):
    sheet, _sm, _one, two = two_unit_sheet(tmp_path)
    whole = SheetBench(Run(sheet, "R1", "Make this whole drawing parametric.", {"kind": "drawing"}))
    rows, asked = whole.coverage()
    assert asked and [r["unit"] for r in rows if not r["covered"]] == [two]
    matter = next(m for m in whole.open_matters() if "units parametrized" in m)
    assert two in matter and "update_checklist" in matter and "skipped" in matter, "it says how a unit is skipped properly"
    # one view of the drawing: nothing is asked of the other unit
    part = SheetBench(Run(sheet, "R2", "Name the parts of this view.", {"views": ["V01"]}))
    assert part.coverage()[1] is False and not any("units parametrized" in m for m in part.open_matters())
    # a change of one value is not a promise to parametrize every unit
    change = SheetBench(Run(sheet, "R3", "Reduce the clear span to 2500.", {"kind": "drawing"}))
    change.ledger.append({"quote": "Reduce the clear span", "kind": "change_value", "meaning": "x", "handled_by": "plan", "quote_norm": "x"})
    assert change.coverage()[1] is False


def test_a_run_over_the_drawing_cannot_end_finished_ok_while_a_unit_was_never_touched(tmp_path):
    sheet, _sm, one, two = two_unit_sheet(tmp_path)
    script = [[call("inspect_sheet")], [call("finish", summary="Every unit is parametrized; the rest is left as drawn.")],
              [call("finish", summary="Every unit is parametrized; the rest is left as drawn.")]]
    gem = Scripted(script)
    sheet.gem_factory = lambda: gem
    r = sheet.start_run({"instruction": "Make this whole drawing parametric.", "scope": {"kind": "drawing"}})
    p = wait(sheet, r["run"])
    v = p["verdict"]
    crit = {c["id"]: c for c in v["criteria"]}
    assert crit["all_units_covered"]["ok"] is False and v["state"] != "completed"
    assert v["headline"].startswith(("Partly done: ", "Failed: ")) and f"1 of 2 units parametrized ({two} untouched)" in v["headline"], v["headline"]
    rows = {x["unit"]: x for x in v["coverage"]}
    assert rows[one]["state"] == "parametrized" and rows[two]["state"] == "untouched"
    assert v["coverage_sentence"] == f"1 of 2 units parametrized ({two} untouched)"
    assert "left as drawn" in v["finish_summary"], "the model's words are kept, as its words"
    assert f"| {two} |" in v["engine_summary"] and "untouched" in v["engine_summary"], "and the engine's table says what the sheet holds"
