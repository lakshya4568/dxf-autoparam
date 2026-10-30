"""What one tool hands the next, and what a refusal says.

review_parameters lists a unit's values by bare name; rename_values wanted 'unit.name' and answered "no parameter GapY12" (49 items in one live run). The
new name arrived with the unit prefix copied from the old one and was refused as "not a PascalCase engineering name" (14). A name another unit used for its
own value was "already used on this sheet" (9). And every refusal still moved the revision: a refused rename pushed its history entry before it had
finished checking. set_structure took the eleven views of the sheet for the one view of the unit."""

from __future__ import annotations

import pytest
from test_agent_context import session
from test_crossview import mini_gad

from dxf_autoparam.ai.agent import Workbench
from dxf_autoparam.ai.context import SheetScope
from dxf_autoparam.ai.run import Run, SheetBench
from dxf_autoparam.ai.understanding_tools import parameter_review, resolve_rename
from dxf_autoparam.crossview import SheetError, SheetModel
from dxf_autoparam.generic import is_generated
from dxf_autoparam.workspace import SheetSession

# these tests measure the engine within ONE unit made of a section and its plan (conftest.joined_units): local systems, each view its own,
# are test_local_systems.py
pytestmark = pytest.mark.usefixtures("joined_units")


def bench_on(tmp_path):
    sheet, uid, _g, _gem = session(tmp_path, [])
    bench = SheetBench(Run(sheet, "R9", "look", {"kind": "drawing"}))
    bench.open(uid)
    return sheet.sm, uid, bench


def generic_names(sm, uid, n=3):
    return [name for name, p in sm.unit(uid).prog.params.items() if is_generated(name) and p.kind == "length"][:n]


def test_the_name_review_parameters_lists_is_the_name_rename_values_takes(tmp_path):
    sm, uid, bench = bench_on(tmp_path)
    listed = [r["name"] for r in parameter_review(sm, uid)["values"] if r["name"] in generic_names(sm, uid)]
    assert listed and "." not in listed[0]
    item, _note = bench.write("rename_values", {"items": [{"from": listed[0], "to": "ClearSpanTest"}]})  # bare, as listed
    v = bench.verdict(item)
    assert v["ok"] and v["renamed"] == [f"{listed[0]} → ClearSpanTest"] and "ClearSpanTest" in sm.unit(uid).prog.params and listed[0] not in sm.unit(uid).prog.params


def test_a_unit_prefix_copied_onto_the_new_name_is_dropped_not_refused(tmp_path):
    sm, uid, bench = bench_on(tmp_path)
    a, b = generic_names(sm, uid)[:2]
    item, _note = bench.write("rename_values", {"items": [{"from": f"{uid}.{a}", "to": f"{uid}.ExistingTrackOffset"}, {"from": b, "to": f"{uid}.OtherSize"}]})
    v = bench.verdict(item)
    assert v["ok"] and set(sm.unit(uid).prog.params) >= {"ExistingTrackOffset", "OtherSize"}


def test_the_error_says_which_of_the_two_names_is_wrong_and_why(tmp_path):
    sm, uid, _bench = bench_on(tmp_path)
    a = generic_names(sm, uid)[0]
    others = [u for u in sm.units if u != uid]
    with pytest.raises(SheetError, match=r"the OLD name 'NoSuchValue'.*review_parameters"):
        resolve_rename(sm, "NoSuchValue", "Fine", uid)
    with pytest.raises(SheetError, match=r"the OLD name 'U99.X'.*no unit U99"):
        resolve_rename(sm, "U99.X", "Fine", uid)
    with pytest.raises(SheetError, match=rf"the OLD name '{uid}.Missing': {uid} has no value Missing"):
        resolve_rename(sm, f"{uid}.Missing", "Fine", uid)
    with pytest.raises(SheetError, match=r"the NEW name 'U05.Thing' must be bare"):
        resolve_rename(sm, a, "U05.Thing", uid)
    if others:
        with pytest.raises(SheetError, match=rf"the NEW name '{others[0]}.Thing' must be bare.*not the unit of"):
            resolve_rename(sm, a, f"{others[0]}.Thing", uid)
    with pytest.raises(SheetError, match=r"the NEW name 'not pascal' is not a PascalCase engineering name — it must look like ClearHeadroom"):
        sm.rename(f"{uid}.{a}", "not pascal")
    with pytest.raises(SheetError, match=r"the NEW name 'GapX6' is not a PascalCase"):
        sm.rename(f"{uid}.{a}", "GapX6")
    assert resolve_rename(sm, a, f"{uid}.Fine", uid) == (f"{uid}.{a}", "Fine")


def test_a_refused_rename_leaves_no_trace(tmp_path):
    sm, uid, _bench = bench_on(tmp_path)
    a = generic_names(sm, uid)[0]
    rev, steps, answers = sm.revision, len(sm.history), {k: u.answer for k, u in sm.units.items()}
    for old, new in ((f"{uid}.NoSuchValue", "Fine"), (f"{uid}.{a}", "not pascal"), ("NoSuchShared", "Fine")):
        with pytest.raises(SheetError):
            sm.rename(old, new)
        assert sm.revision == rev and len(sm.history) == steps and {k: u.answer for k, u in sm.units.items()} == answers
    sm.rename(f"{uid}.{a}", "Fine")
    assert sm.revision == rev + 1 and len(sm.history) == steps + 1


def test_a_name_another_unit_uses_for_its_own_value_is_a_note_not_an_obstacle(tmp_path):
    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    one, two = (k for k in list(sm.units)[:2])
    a, b = generic_names(sm, one)[0], generic_names(sm, two)[0]
    sm.rename(f"{one}.{a}", "Alpha")
    sm.rename(f"{two}.{b}", "Alpha")  # was: "Alpha is already used on this sheet"
    assert "Alpha" in sm.unit(one).prog.params and "Alpha" in sm.unit(two).prog.params
    assert [u for u, _v in sm.namesakes("Alpha", {two})] == [one]
    assert set(sm.current()) >= {f"{one}.Alpha", f"{two}.Alpha"}, "two values, each its unit's own"
    # but one unit cannot have two values of one name, and a shared size's name is taken everywhere
    c = generic_names(sm, one)[1]
    with pytest.raises(SheetError, match=rf"already a value of {one}"):
        sm.rename(f"{one}.{c}", "Alpha")


def test_the_tool_says_when_the_new_name_is_a_namesake_in_another_unit(tmp_path):
    sheet = SheetSession()
    sheet.sm = sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    uid, other = list(sm.units)[:2]
    sm.unit(other)
    sm.rename(f"{other}.{generic_names(sm, other)[0]}", "Alpha")
    bench = SheetBench(Run(sheet, "R9", "look", {"kind": "drawing"}))
    bench.open(uid)
    item, _note = bench.write("rename_values", {"items": [{"from": generic_names(sm, uid)[0], "to": "Alpha"}]})
    v = bench.verdict(item)
    assert v["ok"] and any("also a value of" in n and other in n and "share_sizes" in n for n in v["note"])


def test_set_structure_is_limited_to_the_views_of_the_unit(tmp_path):
    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    bench = Workbench(sm.path, analysis=sm.pristine_analysis(uid), scope=SheetScope(sm, uid))
    every = [g.id for g in sm.layout.views()]
    assert len(every) > len(sm.units[uid].views)
    _item, note = bench.write("set_structure", {"structure_type": "box", "views": every})
    assert bench.answer["views"] == sm.units[uid].views, "the unit's own views, not the sheet's"
    assert "belong to other units" in note and all(v in note for v in every if v not in sm.units[uid].views)
    _item, note = bench.write("set_structure", {"structure_type": "box", "views": list(sm.units[uid].views)})
    assert note == "" and bench.answer["views"] == sm.units[uid].views
    _item, _note = bench.write("set_structure", {"structure_type": "box", "views": ["V98", "V99"]})
    assert bench.answer["views"] == sm.units[uid].views, "none of the listed views is this unit's: it keeps its own"
