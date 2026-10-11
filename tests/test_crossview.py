"""One parametric model for a whole sheet: views drawn in projection change together, a size two views both state
is one shared parameter, every change is checked on the regenerated sheet and committed only when it holds."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from test_sheet import FIXTURES, built_sheet, rect, text

from dxf_autoparam.crossview import SheetError, SheetModel


@pytest.fixture
def sheet(tmp_path):
    return SheetModel.open(str(built_sheet(tmp_path / "sheet.dxf")))


def view(sm: SheetModel, name: str) -> str:
    return next(g.id for g in sm.layout.views() if g.name == name)


def opening(sm: SheetModel, uid: str, value: float, kind: str | None = None) -> str:
    u = sm.unit(uid)
    return next(c.id for c in u.an.clusters.values() if abs(c.value * u.sub.units_mm - value) < 1 and "x" in c.axes
                and (kind is None or c.kind.value == kind))


def xs(sm: SheetModel, sr, vid: str) -> list[float]:
    """The x of every structural vertex a view shows after a regeneration."""
    out = set()
    for i in sm.layout.group(vid).items:
        it = sm.dr.items[i]
        if it.role.value == "structural":
            for k in it.vertex_pts:
                out.add(round(sr.reg.pts.get(i, it.pts)[k][0], 3))
    return sorted(out)


def test_views_drawn_in_projection_are_one_unit_and_change_together(sheet):
    el, pl, de = view(sheet, "ELEVATION"), view(sheet, "PLAN"), view(sheet, "DETAIL OF WALL")
    assert sheet.unit_of_view[el] == sheet.unit_of_view[pl] != sheet.unit_of_view[de]
    link = next(lk for lk in sheet.links if {lk["a"], lk["b"]} == {el, pl})
    assert link["strong"] and link["axis"] == "x" and link["planes"] == 4
    uid = sheet.unit_of_view[el]
    p = sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    assert p.bindings[0].status == "drives"
    r = sheet.apply({"ClearSpan": 14000})
    assert r.ok, r.errors
    assert set(r.by_view) == {el, pl}  # the elevation and its plan: nothing else moved
    # the plan's lines are where the elevation's faces are: the projection still holds
    assert set(xs(sheet, r, pl)) <= set(xs(sheet, r, el))
    assert r.measured["ClearSpan"][uid] == pytest.approx(14000)


def test_a_change_that_breaks_the_sheet_is_refused_and_nothing_changes(sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    before, history = sheet.current(), len(sheet.history)
    r = sheet.apply({"ClearSpan": 0})  # an opening of nothing: its faces collapse onto each other
    assert not r.ok and r.errors
    assert sheet.current() == before and len(sheet.history) == history
    rng = sheet.valid_range("ClearSpan")
    assert 0 < rng["min"] < 12000 and rng["min_reason"] and rng["max"] > 12000


def test_rename_keeps_value_and_effect_and_undo_brings_the_old_name_back(sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    sheet.apply({"ClearSpan": 13000})
    sheet.rename("ClearSpan", "MainOpening")
    cur = sheet.current()
    assert "ClearSpan" not in cur and cur["MainOpening"] == pytest.approx(13000)
    assert sheet.preview({"MainOpening": 15000}).ok
    with pytest.raises(SheetError):
        sheet.preview({"ClearSpan": 15000})
    with pytest.raises(SheetError):
        sheet.rename("MainOpening", "not a name")
    assert sheet.undo()
    assert "ClearSpan" in sheet.current() and "MainOpening" not in sheet.current()
    assert sheet.redo() and "MainOpening" in sheet.current()


def test_undo_and_redo_values(sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    sheet.apply({"ClearSpan": 13000})
    sheet.apply({"ClearSpan": 13500})
    assert sheet.current()["ClearSpan"] == pytest.approx(13500)
    sheet.undo()
    assert sheet.current()["ClearSpan"] == pytest.approx(13000)
    sheet.redo()
    assert sheet.current()["ClearSpan"] == pytest.approx(13500)


def two_views(path: Path) -> Path:
    """Two views NOT drawn in line (one beside and below the other), each stating 3000 for its opening."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    rect(msp, 0, 0, 60000, 40000, "BORDER")
    rect(msp, 2000, 25000, 10000, 32000)
    rect(msp, 4000, 26000, 7000, 31000)
    msp.add_linear_dim(base=(0, 33500), p1=(4000, 32000), p2=(7000, 32000), dxfattribs={"layer": "DIM"}).render()
    text(msp, "SECTION A-A", 3000, 23500, 400)
    rect(msp, 30000, 5000, 44000, 12000)
    rect(msp, 33000, 6000, 36000, 11000)
    msp.add_linear_dim(base=(0, 13500), p1=(33000, 12000), p2=(36000, 12000), dxfattribs={"layer": "DIM"}).render()
    text(msp, "SIDE ELEVATION", 32000, 3500, 400)
    doc.saveas(path)
    return path


def test_a_size_two_separate_views_state_is_proposed_shared_and_drives_both(tmp_path):
    sm = SheetModel.open(str(two_views(tmp_path / "two.dxf")))
    a, b = view(sm, "SECTION A-A"), view(sm, "SIDE ELEVATION")
    ua, ub = sm.unit_of_view[a], sm.unit_of_view[b]
    assert ua != ub and not any(lk["strong"] for lk in sm.links)
    prop = next(p for p in sm.shared_proposals() if p["value"] == 3000)
    assert {prop["a"][0], prop["b"][0]} == {ua, ub} and len(prop["evidence"]) == 2
    p = sm.share("Opening", [tuple(prop["a"]), tuple(prop["b"])], evidence=prop["evidence"])
    assert [b.status for b in p.bindings] == ["drives", "drives"]
    r = sm.apply({"Opening": 3600})
    assert r.ok, r.errors
    assert set(r.by_view) == {a, b}
    assert r.measured["Opening"] == {ua: pytest.approx(3600), ub: pytest.approx(3600)}
    imp = sm.impact("Opening")
    assert set(imp["views"]) == {a, b}
    # a size the views do not both state is refused as a whole
    with pytest.raises(SheetError):
        sm.share("Wrong", [(ua, opening(sm, ua, 3000)), (ub, opening(sm, ub, 14000))])
    assert "Wrong" not in sm.current()


def test_save_and_load_the_project(tmp_path, sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    sheet.apply({"ClearSpan": 13000})
    proj = tmp_path / "sheet.autoparam.json"
    sheet.save(str(proj))
    sm2 = SheetModel.load(str(proj))
    assert sm2.current()["ClearSpan"] == pytest.approx(13000)
    r1, r2 = sheet.regenerate(), sm2.regenerate()
    assert r1.reg.pts == r2.reg.pts


def test_export_writes_every_regenerated_view_into_the_original(tmp_path, sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    sheet.apply({"ClearSpan": 14000})
    out = tmp_path / "out.dxf"
    rep = sheet.export(str(out))
    assert rep["audit"]["errors"] == 0 and rep["updated"] > 0 and not rep["errors"]
    doc = ezdxf.readfile(str(out))
    widths = sorted(round(d.get_measurement()) for d in doc.modelspace().query("DIMENSION") if abs(d.get_measurement() - 14000) < 1)
    assert widths == [14000]  # the opening's dimension now reads the new size


@pytest.mark.skipif(not (FIXTURES / "gad_ezdxf_a.dxf").exists(), reason="aagento-bridge fixtures not present")
def test_a_real_sheet_section_and_plan_follow_one_barrel_length(tmp_path):
    sm = SheetModel.open(str(FIXTURES / "gad_ezdxf_a.dxf"))
    sec, plan = view(sm, "LONGITUDINAL SECTION(X-X"), view(sm, "PLAN TOP")
    uid = sm.unit_of_view[sec]
    assert sm.unit_of_view[plan] == uid  # drawn in projection: one unit
    cid = opening(sm, uid, 11740)
    p = sm.share("BarrelLength", [(uid, cid)], evidence=["written in both views"])
    assert p.bindings[0].status == "drives"
    for v in (10000, 13000):
        r = sm.preview({"BarrelLength": v})
        assert r.ok, r.errors[:3]
        assert r.by_view.get(sec, 0) > 50 and r.by_view.get(plan, 0) > 50
        assert set(r.by_view) == {sec, plan}  # the other views stay as drawn
    sm.apply({"BarrelLength": 13000})
    rep = sm.export(str(tmp_path / "a.dxf"))
    assert rep["audit"]["errors"] == 0
    # the notes that state the barrel length in the section and in the plan now state the new one; the other
    # view's own note (another barrel) is left as it was
    doc = ezdxf.readfile(str(tmp_path / "a.dxf"))
    notes = sorted(e.text for e in doc.modelspace().query("MTEXT") if "BARREL LENGTH" in e.text)
    assert notes == ["BARREL LENGTH = 13000", "BARREL LENGTH = 13000 mm"], notes  # the two reshaped views, written out
    kept = [e.text for b in doc.blocks for e in b.query("MTEXT") if "BARREL LENGTH" in e.text]
    assert "BARREL LENGTH = 15950" in kept  # the untouched view keeps its block, and its own note
