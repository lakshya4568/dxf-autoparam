"""Scale is presentation, size is the design: a view drawn at 1:25 beside one at 1:100, each read at its own scale; a geometry edit moves each by its
real size and every dimension says the real size; redrawing a view at another scale changes how large it is on the sheet and nothing it measures.

The sheet: a section at the sheet's scale (1 unit = 1 mm) and a detail drawn four times as large (1:25 on a 1:100 sheet) whose automatic dimensions
carry DIMLFAC 0.25 — the way CAD draws a detail: they measure drawing units and show millimetres."""

from __future__ import annotations

import ezdxf
import pytest

from dxf_autoparam.coverage import dimension_rows
from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.frames import view_frame
from dxf_autoparam.rescale import rescale_view

OX = 40000.0  # where the detail is drawn on the sheet
K = 4.0  # drawing units per millimetre in the detail (1:25 on a 1:100 sheet)


def sheet(path) -> str:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    # the section, 1 unit = 1 mm: a 6000 × 500 base, a 400 × 2500 wall on it
    msp.add_lwpolyline([(0, 0), (6000, 0), (6000, 500), (0, 500)], close=True)
    msp.add_lwpolyline([(2800, 500), (3200, 500), (3200, 3000), (2800, 3000)], close=True)
    for base, p1, p2, ang in [((0, -700), (0, 0), (6000, 0), 0), ((6800, 0), (6000, 0), (6000, 500), 90),
                              ((2800, 3500), (2800, 3000), (3200, 3000), 0), ((-800, 500), (2800, 500), (2800, 3000), 90)]:
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=ang, dimstyle="Standard").render()
    msp.add_text("SECTION (SCALE 1:100)", height=250, dxfattribs={"insert": (2000, -1600)})
    # the detail, 4 units = 1 mm: a 1000 × 200 footing, a 300 × 800 stem on it
    msp.add_lwpolyline([(OX, 0), (OX + 1000 * K, 0), (OX + 1000 * K, 200 * K), (OX, 200 * K)], close=True)
    msp.add_lwpolyline([(OX + 350 * K, 200 * K), (OX + 650 * K, 200 * K), (OX + 650 * K, 1000 * K), (OX + 350 * K, 1000 * K)], close=True)
    for base, p1, p2, ang in [((OX, -700), (OX, 0), (OX + 1000 * K, 0), 0),
                              ((OX + 1000 * K + 800, 0), (OX + 1000 * K, 0), (OX + 1000 * K, 200 * K), 90),
                              ((OX + 350 * K, 1000 * K + 600), (OX + 350 * K, 1000 * K), (OX + 650 * K, 1000 * K), 0),
                              ((OX - 800, 200 * K), (OX + 350 * K, 200 * K), (OX + 350 * K, 1000 * K), 90)]:
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=ang, dimstyle="Standard", override={"dimlfac": 1 / K}).render()
    msp.add_text("DETAIL A (SCALE 1:25)", height=250, dxfattribs={"insert": (OX + 600, -1600)})
    # a label on the stem's top right corner, its leader starting ON the corner
    msp.add_leader([(OX + 650 * K, 1000 * K), (OX + 650 * K + 900, 1000 * K + 700), (OX + 650 * K + 1900, 1000 * K + 700)])
    msp.add_text("STEM", height=250, dxfattribs={"insert": (OX + 650 * K + 1950, 1000 * K + 650)})
    doc.saveas(str(path))
    return str(path)


def views(sm):
    a, b = sorted(sm.layout.views(), key=lambda g: g.bbox[0])
    return a.id, b.id


def shown(dim) -> float:
    """What a dimension SHOWS: its measured length × its linear factor (the number in its rendered block)."""
    return float(dim.get_measurement()) * float(dim.override().get("dimlfac", 1.0) or 1.0)


def dims_in(path, x_from: float, x_to: float) -> list:
    doc = ezdxf.readfile(path)
    return sorted((d for d in doc.modelspace().query("DIMENSION") if x_from <= d.dxf.defpoint2.x <= x_to), key=lambda d: (round(d.dxf.defpoint2.x), round(d.dxf.defpoint2.y)))


def value_on(sm, uid: str, mm: float) -> str:
    """The engine's own value for a size a dimension of the unit states (the one stepping moves that dimension)."""
    for r in dimension_rows(sm.unit(uid).prog):
        if r.get("mm") is not None and abs(r["mm"] - mm) < 1e-6 and r.get("by"):
            return r["by"][0]
    raise AssertionError(f"no value states {mm} mm in {uid}")


def test_each_view_is_read_at_its_own_scale_and_said_in_real_millimetres(tmp_path):
    sm = SheetModel.open(sheet(tmp_path / "s.dxf"))
    sec, det = views(sm)
    assert sm.unit(sm.unit_of_view[sec]).sub.units_mm == pytest.approx(1.0)
    assert sm.unit(sm.unit_of_view[det]).sub.units_mm == pytest.approx(1 / K), "the detail's own dimensions say 1 unit = 0.25 mm"
    fr = view_frame(sm, det)
    a, b = fr.to_local(OX + 350 * K, 200 * K), fr.to_local(OX + 650 * K, 200 * K)
    assert b[0] - a[0] == pytest.approx(300.0), "the stem is 300 mm in its own frame, whatever it is drawn at"


def test_a_geometry_edit_at_each_scale_moves_by_its_real_size_and_every_dimension_says_it(tmp_path):
    src = sheet(tmp_path / "s.dxf")
    sm = SheetModel.open(src)
    sec, det = views(sm)
    us, ud = sm.unit_of_view[sec], sm.unit_of_view[det]
    wall, stem = value_on(sm, us, 400.0), value_on(sm, ud, 300.0)
    r = sm.apply({f"{us}.{wall}": 450.0, f"{ud}.{stem}": 350.0})
    assert r.ok, r.errors
    out = str(tmp_path / "edited.dxf")
    sm.export(out)
    before_sec, after_sec = dims_in(src, -5000, OX - 5000), dims_in(out, -5000, OX - 5000)
    before_det, after_det = dims_in(src, OX - 5000, OX + 20000), dims_in(out, OX - 5000, OX + 20000)
    assert sorted(round(shown(d)) for d in before_sec) == [400, 500, 2500, 6000]
    assert sorted(round(shown(d)) for d in after_sec) == [450, 500, 2500, 6000], "the section's wall: +50 mm, drawn +50 units"
    assert sorted(round(shown(d)) for d in before_det) == [200, 300, 800, 1000]
    assert sorted(round(shown(d)) for d in after_det) == [200, 350, 800, 1000], "the detail's stem: +50 mm, drawn +200 units, shown 350"
    stem_dim = next(d for d in after_det if round(shown(d)) == 350)
    assert float(stem_dim.get_measurement()) == pytest.approx(350 * K), "the drawn length is the real size at the detail's own scale"
    h0 = {round(float(d.override().get("dimtxt", 0) or 0), 6) for d in before_det}
    assert {round(float(d.override().get("dimtxt", 0) or 0), 6) for d in after_det} == h0, "a dimension's text height is a paper size: unchanged"


def test_redrawing_a_view_at_another_scale_changes_its_size_on_the_sheet_and_nothing_it_measures(tmp_path):
    src = sheet(tmp_path / "s.dxf")
    sm = SheetModel.open(src)
    _sec, det = views(sm)
    origin = view_frame(sm, det).origin
    out = str(tmp_path / "at-1-50.dxf")
    rep = rescale_view(sm, det, 50, out)
    assert rep["old_ratio"] == 25 and rep["factor"] == pytest.approx(0.5) and not rep["not_rescaled"], rep
    assert rep["titles"] == ["DETAIL A (SCALE 1:25) → DETAIL A (SCALE 1:50)"]
    again = SheetModel.open(out)
    _s2, d2 = views(again)
    assert again.unit(again.unit_of_view[d2]).sub.units_mm == pytest.approx(0.5), "read again, the detail is at its new scale"
    fr = view_frame(again, d2)
    assert fr.origin[0] == pytest.approx(origin[0]) and fr.origin[1] == pytest.approx(origin[1]), "it stays at its own origin"
    stem = [it for it in again.dr.items if it.dxftype == "LWPOLYLINE" and it.pts and min(x for x, _y in it.pts) > OX + 100]
    widths = sorted(round((max(x for x, _y in it.pts) - min(x for x, _y in it.pts)) * fr.mm_per_unit, 6) for it in stem)
    assert widths == [300.0, 1000.0], "the stem and the footing are the same millimetres in its own frame"
    assert sorted(round(shown(d)) for d in dims_in(out, OX - 5000, OX + 20000)) == [200, 300, 800, 1000], "every number the detail shows is unchanged"
    texts = {e.dxf.text: e.dxf.height for e in ezdxf.readfile(out).modelspace().query("TEXT")}
    assert texts == {"SECTION (SCALE 1:100)": 250, "DETAIL A (SCALE 1:50)": 250, "STEM": 250}, "the title says the new scale; every text keeps its height"
    assert sorted(round(shown(d)) for d in dims_in(out, -5000, OX - 5000)) == [400, 500, 2500, 6000], "the section is untouched"
    sec_pts = sorted(tuple(map(round, p)) for it in again.dr.items for p in it.pts if it.dxftype == "LWPOLYLINE" and min(x for x, _y in it.pts) < OX - 5000)
    orig_pts = sorted(tuple(map(round, p)) for it in sm.dr.items for p in it.pts if it.dxftype == "LWPOLYLINE" and min(x for x, _y in it.pts) < OX - 5000)
    assert sec_pts == orig_pts


def test_a_scale_that_is_not_a_scale_is_refused(tmp_path):
    sm = SheetModel.open(sheet(tmp_path / "s.dxf"))
    _sec, det = views(sm)
    with pytest.raises(ValueError):
        rescale_view(sm, det, 0, str(tmp_path / "x.dxf"))


def test_a_leader_on_the_geometry_follows_the_edit_and_keeps_its_paper_size(tmp_path):
    src = sheet(tmp_path / "s.dxf")
    sm = SheetModel.open(src)
    _sec, det = views(sm)
    ud = sm.unit_of_view[det]
    stem = value_on(sm, ud, 300.0)
    r = sm.apply({f"{ud}.{stem}": 350.0})
    assert r.ok, r.errors
    out = str(tmp_path / "edited.dxf")
    sm.export(out)
    tip = ezdxf.readfile(out).modelspace().query("LEADER")[0].vertices[0]
    stems = [it for it in SheetModel.open(out).dr.items if it.dxftype == "LWPOLYLINE" and it.pts and min(x for x, _y in it.pts) > OX + 100 * K]
    stem_pts = [p for it in stems for p in it.pts]
    left, right, top = min(x for x, _y in stem_pts), max(x for x, _y in stem_pts), max(y for _x, y in stem_pts)
    assert (right - left) == pytest.approx(350 * K), "the stem is 350 mm wide, drawn at its own scale"
    assert (tip[0], tip[1]) == (pytest.approx(right), pytest.approx(top)), "the leader still starts on the stem's top right corner"
    heights = {e.dxf.text: e.dxf.height for e in ezdxf.readfile(out).modelspace().query("TEXT")}
    assert heights["STEM"] == 250, "a label is a paper size"

