"""Curved structure: a wing wall drawn as quarter ellipses (as the plans of 7A, 173A and 20A draw theirs) is structure, set out from
its two ends, and redrawn exactly — an ellipse stays an ellipse — when a value moves them; a curve the size of the writing is a mark.

Also the sheet segmentation guard the curves exposed: a piece with a view title of its own is never swallowed as a satellite of a
heavier untitled piece beside it."""

from __future__ import annotations

import math

import ezdxf
import pytest

from dxf_autoparam import autoparametrize, regenerate, validate
from dxf_autoparam.build import Decisions
from dxf_autoparam.display import curve_map
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.dxf_write import write_dxf
from dxf_autoparam.ir import GapKind, Role
from dxf_autoparam.sheet import segment
from dxf_autoparam.topology import of

A, B, T = 10200.0, 7280.0, 350.0  # the wall's splay along the box face line, its reach, its thickness


def wing_plan(path) -> str:
    """A box in plan with a wing wall on its left: two quarter ellipses about one centre, from the wall's end line to the box face."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_ellipse((0, 0), major_axis=(A, 0), ratio=B / A, start_param=math.pi, end_param=1.5 * math.pi)
    msp.add_ellipse((0, 0), major_axis=(A + T, 0), ratio=(B + T) / (A + T), start_param=math.pi, end_param=1.5 * math.pi)
    msp.add_line((-A - T, 0), (-A, 0))  # the wall's end
    msp.add_lwpolyline([(0, -B - T - 3000), (4000, -B - T - 3000), (4000, -B + 2000), (0, -B + 2000)], close=True)  # the box
    msp.add_text("WING WALL", dxfattribs={"insert": (-A / 2, -B / 2), "height": 250})
    msp.add_spline([(500, -B), (550, -B + 60), (600, -B)])  # a mark, the size of the writing
    doc.saveas(path)
    return str(path)


@pytest.fixture
def plan(tmp_path):
    return wing_plan(tmp_path / "wing.dxf")


def _items(dr, t):
    return [it for it in dr.items if it.dxftype == t]


def test_a_curved_wall_is_structure_and_a_curve_the_size_of_the_writing_is_a_mark(plan):
    dr, _ = read_dxf(plan)
    walls = _items(dr, "ELLIPSE")
    assert [it.role for it in walls] == [Role.STRUCTURAL, Role.STRUCTURAL]
    assert walls[0].pts == [pytest.approx((-A, 0.0), abs=1e-6), pytest.approx((0.0, -B), abs=1e-6)], "set out from its two ends"
    assert _items(dr, "SPLINE")[0].role == Role.ANNOTATION
    assert any("marks, not structure" in n for n in dr.notes)


def test_the_analysis_finds_the_walls_sizes_and_the_region_between_the_curves(plan):
    an = autoparametrize(plan).analysis
    u = an.drawing.units_mm
    found = {(g.kind, round(g.value * u)) for g in an.gaps.values()}
    assert {(GapKind.RUN, A), (GapKind.RISE, B), (GapKind.RUN, A + T), (GapKind.RISE, B + T)} <= found
    assert any(k == GapKind.CHAIN and v == T for k, v in found), "the thickness at the wall's end"
    walls = {it.index for it in _items(an.drawing, "ELLIPSE")}
    assert any(walls <= set(r.items) for r in of(an).regions), "the wall is a region bounded by both curves"


def _named(plan):
    an = autoparametrize(plan).analysis
    u = an.drawing.units_mm
    splay = next(g.cluster for g in an.gaps.values() if g.kind == GapKind.RUN and round(g.value * u) == A)
    thick = next(g.cluster for g in an.gaps.values() if g.kind == GapKind.CHAIN and round(g.value * u) == T and g.axis == "x")
    return autoparametrize(plan, decisions=Decisions(accept={splay, thick}, rename={splay: "WingSplay", thick: "WingThickness"}))


def test_a_named_splay_redraws_the_wall_exactly_between_its_moved_ends(plan, tmp_path):
    model = _named(plan)
    assert validate(model)["regenerate_ok"] == len(model.parameters)
    dr = model.analysis.drawing
    end_line = _items(dr, "LINE")[0]
    r = regenerate(model, {"WingSplay": 12000.0, "WingThickness": 500.0})
    assert not r.issues
    inner, outer = _items(dr, "ELLIPSE")
    assert r.pts[inner.index][0] == pytest.approx(r.pts[end_line.index][1]) and r.pts[outer.index][0] == pytest.approx(r.pts[end_line.index][0])
    out = tmp_path / "out.dxf"
    write_dxf(model, r, str(out))
    written = {round(e.dxf.major_axis.magnitude): e for e in ezdxf.readfile(out).modelspace().query("ELLIPSE")}
    e = written[12000]
    assert e.dxf.major_axis.magnitude * e.dxf.ratio == pytest.approx(B), "the reach stays: only the splay was changed"
    assert tuple(e.start_point)[:2] == pytest.approx(r.pts[inner.index][0], abs=1e-6)
    assert tuple(e.end_point)[:2] == pytest.approx(r.pts[inner.index][1], abs=1e-6)


def test_a_line_that_runs_into_a_curve_part_way_touches_the_curve_not_its_chord(tmp_path):
    """A wall line ending on a curved wall between the curve's ends (a return wall's face meeting a wing in plan) touches the curve as drawn
    and after both moved together; tested along the chord between the curve's ends it never touched, and every plan moving it reported a tear."""
    from dxf_autoparam.plan import _touch

    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    e = msp.add_ellipse((0, 0), major_axis=(A, 0), ratio=B / A, start_param=math.pi, end_param=1.5 * math.pi)
    x = -A / 2
    on = (x, -B * math.sqrt(1 - (x / A) ** 2))  # a point of the curve, half way along its splay
    msp.add_line(on, (x, -B - 2000))
    msp.add_text("PLAN", dxfattribs={"insert": (0, 1000), "height": 250})
    doc.saveas(tmp_path / "touch.dxf")
    assert e.dxf.ratio
    dr, _ = read_dxf(str(tmp_path / "touch.dxf"))
    (curve,), (line,) = _items(dr, "ELLIPSE"), _items(dr, "LINE")
    assert _touch(curve, curve.pts, line, line.pts, dr.tol * 2)
    moved = [[(p[0] + 700, p[1] - 300) for p in it.pts] for it in (curve, line)]
    assert _touch(curve, moved[0], line, moved[1], dr.tol * 2)
    stretched = [curve.pts[0], (curve.pts[1][0] + 2000, curve.pts[1][1])]  # the curve stretched, the line left where it was: they part
    assert not _touch(curve, stretched, line, line.pts, dr.tol * 2)


def test_saved_work_is_read_as_it_was_made(plan, tmp_path):
    """A project records how its drawing was read: work saved before free curves were structure (no "reader" record) keeps reading them as
    marks — its datum, gap and candidate ids count the structure as it was then; work saved since reads them as structure again."""
    import json

    from dxf_autoparam.crossview import SheetModel

    sm = SheetModel.open(plan)
    d = sm.to_dict()
    assert d["reader"] == {"curves": True}
    now, before = tmp_path / "now.json", tmp_path / "before.json"
    now.write_text(json.dumps(d))
    before.write_text(json.dumps({k: v for k, v in d.items() if k != "reader"}))
    walls = [it.index for it in sm.dr.items if it.dxftype == "ELLIPSE"]
    again = SheetModel.load(str(now), dxf=plan)
    assert again.dr.curves and all(again.dr.items[i].role == Role.STRUCTURAL for i in walls)
    old = SheetModel.load(str(before), dxf=plan)
    assert not old.dr.curves and all(old.dr.items[i].role == Role.ANNOTATION for i in walls)
    assert old.to_dict()["reader"] == {"curves": False}, "and it stays so when saved again"


@pytest.mark.parametrize("turn", [0.0, 30.0])
def test_the_page_and_the_file_redraw_a_curve_by_the_same_map(turn):
    doc = ezdxf.new("R2018")
    e = doc.modelspace().add_ellipse((0, 0), major_axis=(A, 0), ratio=B / A, start_param=math.pi, end_param=1.5 * math.pi)
    old = [tuple(e.start_point)[:2], tuple(e.end_point)[:2]]
    new = [(-A - 1800, 250.0), (0.0, -B + 250.0)] if not turn else [(-A + 900.0, 40.0), (0.0, 0.0)]
    m = curve_map(old, new, turn)
    mid = tuple(next(iter(e.construction_tool().vertices([1.25 * math.pi]))))[:2]
    e.transform(m.matrix())
    assert tuple(e.start_point)[:2] == pytest.approx(m.apply(old[0]), abs=1e-6)
    assert tuple(e.end_point)[:2] == pytest.approx(m.apply(old[1]), abs=1e-6)
    on = [tuple(p)[:2] for p in e.flattening(0.01)]
    assert min(math.dist(p, m.apply(mid)) for p in on) < 0.1, "a point of the curve maps onto the redrawn curve: still an ellipse"


@pytest.mark.parametrize("gap", [560.0, 640.0])
def test_a_titled_view_beside_a_heavier_untitled_one_stays_a_view(tmp_path, gap):
    """A plan with no title of its own, thirty times heavier than a small titled section drawn `gap` below it — between two and
    three tight gaps of the sheet, the satellite reach: the section stays a view of its own (it was swallowed, and the plan took
    its title, as 7A's half section was by its plan once the plan's curved walls were read)."""
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_lwpolyline([(-3000, -9000), (43000, -9000), (43000, 33000), (-3000, 33000)], close=True)  # the sheet border
    for i in range(20):  # the plan: a grid of cells
        for j in range(15):
            x, y = i * 2000, j * 2000
            msp.add_lwpolyline([(x, y), (x + 1800, y), (x + 1800, y + 1800), (x, y + 1800)], close=True)
    for k in range(12):  # the section
        x = 18000 + 300 * k
        msp.add_lwpolyline([(x, -gap - 200 - 100 * k), (x + 250, -gap - 200 - 100 * k), (x + 250, -gap - 2800), (x, -gap - 2800)], close=True)
    msp.add_text("SECTION A-A", dxfattribs={"insert": (18500, -gap - 3600), "height": 250})
    doc.saveas(tmp_path / "sheet.dxf")
    dr, _ = read_dxf(str(tmp_path / "sheet.dxf"))
    views = [g for g in segment(dr).groups if g.kind == "view"]
    assert len(views) == 2
    section = next(g for g in views if (g.name or "").startswith("SECTION A-A"))
    assert len(section.items) < 20, "the section alone, not the plan"
