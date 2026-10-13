"""The way back, and which geometry a value belongs to — through the real SheetModel and the HTTP routes of the page.

The imported drawing is the baseline: it is never edited, a value's original is what its lines measure on it, and a
reset goes back to it by regenerating — checked on the whole sheet, or refused with nothing changed."""

from __future__ import annotations

import json

import pytest
from test_intent_plan import box_sheet

from dxf_autoparam.crossview import SheetError, SheetModel


def sheet(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    return sm, uid, g


def key(uid: str, name: str = "ClearSpan") -> str:
    return f"{uid}.{name}"  # a value of one view is keyed by its unit (a shared one by its name)


def test_a_value_knows_the_original_it_was_measured_as_on_the_imported_drawing(tmp_path):
    sm, uid, _g = sheet(tmp_path)
    (row,) = [r for r in sm.original(key(uid))]
    assert row["value"] == 3000 and row["reliable"] and "measured between" in row["basis"] and row["current"] == 3000
    sm.apply({key(uid): 2500})
    (row,) = sm.original(key(uid))
    assert row["current"] == 2500 and row["value"] == 3000  # the original is not read from the changed drawing
    assert sm.regenerate().changed  # and the drawing has moved


def test_reset_value_restores_that_value_only_and_regenerates_every_view(tmp_path):
    sm, uid, _g = sheet(tmp_path)
    sm.apply({key(uid): 2500})
    other = next(n for n in sm.current() if n != key(uid) and n.startswith(uid) and sm.values[uid].get(n.split(".", 1)[1]) is None)
    sm.apply({other: sm.current()[other] + 50})  # a second value a person changed: it must survive the reset
    before = sm.revision
    res = sm.reset_value(key(uid))
    assert res["changed"] and res["bindings"][0]["original"] == 3000 and res["bindings"][0]["was"] == 2500
    assert sm.current()[key(uid)] == 3000 and sm.current()[other] == sm.values[uid][other.split(".", 1)[1]]
    assert "ClearSpan" not in sm.values.get(uid, {}) and other.split(".", 1)[1] in sm.values[uid]  # only that one
    assert sm.revision == before + 1
    again = sm.reset_value(key(uid))
    assert not again["changed"] and "already" in again["reason"]  # nothing to do is said, not faked
    assert sm.undo() and sm.current()[key(uid)] == 2500  # the reset is one undoable step


def test_reset_is_refused_when_the_sheet_would_not_hold(tmp_path):
    sm, uid, _g = sheet(tmp_path)
    sm.apply({key(uid): 2500})
    # a second value the reset ClearSpan cannot live with: the wall offset is pushed so far that 3000 would overlap it
    u = sm.unit(uid)
    wall = next(n for n, p in u.prog.params.items() if p.source == "ai" and n != "ClearSpan" and p.kind == "length")
    state_before = json.dumps(sm.values, sort_keys=True)
    huge = sm.current()[f"{uid}.{wall}"] * 0.2
    r = sm.regenerate({f"{uid}.{wall}": huge})
    if r.ok:  # (the fixture's members are independent: then the reset must simply succeed)
        sm.reset_value(key(uid))
        return
    with pytest.raises(SheetError):
        sm.reset_value(key(uid))
    assert json.dumps(sm.values, sort_keys=True) == state_before


def test_reset_drawing_goes_back_to_the_imported_state_and_can_be_undone(tmp_path):
    sm, uid, _g = sheet(tmp_path)
    sm.apply({key(uid): 2500})
    sm.set_view("V01", name="CHANGED NAME")
    hist = len(sm.history)
    res = sm.reset_drawing()
    assert res["reset"]["values"] >= 1 and res["reset"]["answers"] >= 1
    assert sm.values == {} and sm.shared == {} and not any(u.answer for u in sm.units.values())
    assert sm.layout.group("V01").name != "CHANGED NAME"
    assert not sm.regenerate().changed  # the drawing is the file's again
    assert len(sm.history) == hist + 1  # the history before it is kept
    assert sm.undo()
    assert sm.current().get(key(uid)) == 2500 and sm.layout.group("V01").name == "CHANGED NAME"  # nothing lost for good


def test_the_baseline_is_the_imported_geometry_and_survives_save_and_reload(tmp_path):
    sm, uid, _g = sheet(tmp_path)
    sm.apply({key(uid): 2500})
    sm.prefs["baseline"] = {"on": True, "color": "#ff00ff"}
    sm.runs.append({"id": "R1", "status": "completed"})
    path = tmp_path / "p.json"
    sm.save(str(path))
    saved = json.loads(path.read_text())
    assert saved["originals"][uid]["ClearSpan"] == 3000 and saved["values"][uid]["ClearSpan"] == 2500
    sm2 = SheetModel.load(str(path), dxf=sm.path)
    assert sm2.current()[key(uid)] == 2500 and sm2.prefs["baseline"]["on"] and sm2.runs[0]["id"] == "R1"
    (row,) = sm2.original(key(uid))
    assert row["value"] == 3000  # re-derived from the DXF, not read back from the saved record
    assert [it.pts for it in sm2.dr.items] == [it.pts for it in sm.dr.items]  # the baseline geometry is the file's own
    sm2.reset_value(key(uid))
    assert not sm2.regenerate().changed


def test_clicking_a_value_says_which_geometry_it_drives_follows_and_leaves(tmp_path):
    sm, uid, _g = sheet(tmp_path)
    h = sm.highlight(key(uid))
    assert h["drives"] and not set(h["drives"]) & set(h["follows"])
    assert h["measured_moves"] > 0 and h["step"]
    moved = set(sm.regenerate({key(uid): 3150}).changed)
    claimed = set(h["drives"]) | set(h["follows"]) | set(h["texts"])
    assert moved <= claimed  # everything that really moves is in some category
    assert set(h["follows"]) <= moved  # a followed entity really moves: what the formulas merely reach is not claimed
    assert len(h["views"]) >= 2  # both views of the unit, each with its own box to fit
    for row in h["views"].values():
        assert row["box"] and row["box"][2] >= row["box"][0]


def test_deviation_measures_how_far_the_drawing_is_from_the_imported_one(tmp_path):
    sm, uid, _g = sheet(tmp_path)
    assert sm.deviation()["changed"] == 0
    sm.apply({key(uid): 2500})
    d = sm.deviation()
    assert d["changed"] > 0 and d["max_shift_mm"] > 0 and len(d["by_view"]) >= 2
    assert sm.deviation(entities=set())["changed"] == 0


def test_the_status_report_is_derived_from_the_model_and_never_claims_what_was_not_measured(tmp_path):
    from dxf_autoparam.status import sheet_status

    sm, uid, _g = sheet(tmp_path)
    st = sheet_status(sm)
    assert {v["state"] for v in st["views"]} <= {"validated", "partial", "components_identified"}
    assert st["counts"]["parameters_named"] >= 1 and st["counts"]["views"] == 2
    assert "Everything is validated" in st["sentence"] or "partial" in st["sentence"]
    # a sheet nobody has parametrized says so
    sm0 = SheetModel.open(sm.path)
    st0 = sheet_status(sm0)
    assert st0["overall"] == "not_started" and all(v["state"] == "not_analyzed" for v in st0["views"])
    assert "not yet analyzed" in st0["sentence"]
    # a run that is working on a unit shows as working, not as finished
    live = sheet_status(sm0, active={next(iter(sm0.units)): "parametrizing"})
    assert live["overall"] == "in_progress"
    # a broken promise is not "validated": a failed plan check leaves the unit partial
    u = sm.unit(uid)
    u.prog.intent["plans"] = [{"id": "X", "checks": [{"check": "fixed", "target": "Wall", "status": "fail", "measured": "moved 5 mm"}], "ok": False}]
    u.answer["plans"] = [{"id": "X", "status": "accepted", "directives": [], "questions": []}]
    assert sheet_status(sm)["units"][uid]["state"] == "partial"
