"""A size of material at 0 takes its part away — its outline, its hatch, the dimension of it — and a value above 0 draws it again; an opening at 0
is still refused (an opening of nothing is no structure).

The owner asked for what the production generator does by hand ("the hatches gone, or come back, some wall shown or removed" as values change),
generically: whether a value may be 0 is decided by the kind of gap it measures (material between two faces may go; an opening, a spacing of
repeats, a circle's size, an overall size, a level never), and what is not drawn is said, sent to the page as gone, and not written to the DXF.
Generated drawings, no model."""

from __future__ import annotations

import ezdxf
import pytest
from levels_fixture import LevelBox, level_box_answer, level_box_gad

from dxf_autoparam.crossview import SheetModel


@pytest.fixture(autouse=True)
def bridge_pack(monkeypatch):
    monkeypatch.setenv("AUTOPARAM_DOMAIN", "bridge")


def hatched_level_box(tmp_path):
    """The level box with its wearing course hatched (the hatch's boundary on the course's own corners)."""
    b = LevelBox()
    g = level_box_gad(tmp_path / "level_box.dxf", b)
    doc = ezdxf.readfile(g["path"])
    msp = doc.modelspace()
    h = msp.add_hatch(color=3, dxfattribs={"layer": "FILL"})
    h.set_pattern_fill("ANSI31", scale=20.0)
    h.paths.add_polyline_path([(b.wall, b.bottom), (b.width - b.wall, b.bottom), (b.width - b.wall, b.y_road), (b.wall, b.y_road)], is_closed=True)
    g["handles"]["WearingCourseHatch"] = h.dxf.handle
    doc.saveas(g["path"])
    sm = SheetModel.open(g["path"])
    uid = next(iter(sm.units))
    handles = {k: v for k, v in g["handles"].items() if k != "WearingCourseHatch"}
    sm.commit_answer(uid, level_box_answer(sm, uid, b, handles), intent=False)
    return sm, uid, g, b


def entity(sm, handle):
    return next(it.index for it in sm.dr.items if it.handle == handle)


def test_a_course_at_zero_is_not_drawn_with_its_hatch_and_comes_back(tmp_path):
    sm, uid, g, b = hatched_level_box(tmp_path)
    course, hatch = entity(sm, g["handles"]["WearingCourse"]), entity(sm, g["handles"]["WearingCourseHatch"])
    r = sm.apply({f"{uid}.WearingCourseThickness": 0.0})
    assert r.ok, [f["message"] for f in r.failures]
    assert {course, hatch} <= set(r.absent), r.absent
    assert any("WearingCourseThickness = 0" in w and "WearingCourse is not drawn" in w and "1 hatch" in w and "draws them again" in w for w in r.warnings), r.warnings
    back = sm.apply({f"{uid}.WearingCourseThickness": b.wearing})
    assert back.ok and not back.absent, back.absent
    assert sm.regenerate().reg.pts[course] == pytest.approx(sm.dr.items[course].pts), "back at its drawn size, drawn where it was"


def test_a_hole_at_zero_is_refused_and_a_space_closed_is_said(tmp_path):
    from test_crossview import mini_gad

    sm, uid, _g, _b = hatched_level_box(tmp_path)
    closed = sm.apply({f"{uid}.ClearHeight": 0.0})  # the soffit down on the road: drawable, nothing taken away
    assert closed.ok and any("nothing of the structure is taken away" in w and "dimension" in w for w in closed.warnings), closed.warnings
    assert sm.apply({f"{uid}.TopSlabThickness": -5.0}).ok is False, "below 0 nothing is drawable"
    gad = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    from dxf_autoparam.regen import NO_ZERO, zero_allowed

    for u in gad.units.values():
        prog = gad.unit(next(k for k, x in gad.units.items() if x is u)).prog
        by = {}
        for g in prog.analysis.gaps.values():
            by.setdefault(frozenset((g.a, g.b)), set()).add(g.kind.value)
        for n, p in prog.params.items():
            if {p.kind} & NO_ZERO or by.get(frozenset(p.measures or ()), set()) & NO_ZERO:
                assert n not in zero_allowed(prog), f"{n}: a hole, a spacing or an overall size is never 0"


def test_the_page_drops_what_is_gone_and_the_export_writes_without_it(tmp_path):
    from dxf_autoparam.workspace import SheetSession

    sm, uid, g, b = hatched_level_box(tmp_path)
    course = entity(sm, g["handles"]["WearingCourse"])
    sheet = SheetSession()
    sheet.sm = sm
    sheet.geometry()
    pv = sheet.preview({f"{uid}.WearingCourseThickness": 0.0})
    assert pv["ok"] and any(p["i"] == course and p.get("gone") for p in pv["delta"]), "the page is told the course is gone"
    sm.apply({f"{uid}.WearingCourseThickness": 0.0})
    out = tmp_path / "zero.dxf"
    sm.export(str(out))
    written = {e.dxf.handle for e in ezdxf.readfile(out).modelspace()}
    assert g["handles"]["WearingCourse"] not in written and g["handles"]["WearingCourseHatch"] not in written
    assert g["handles"]["BottomSlab"] in written, "the rest is written"
    sm.apply({f"{uid}.WearingCourseThickness": b.wearing})
    sm.export(str(out))
    assert g["handles"]["WearingCourse"] in {e.dxf.handle for e in ezdxf.readfile(out).modelspace()}, "and back when it is above 0"
