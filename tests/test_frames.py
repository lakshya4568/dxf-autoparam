"""Each view in its own coordinate frame: real millimetres from the view's own origin, the reduced level where it states one — and back to the
sheet exactly, so a view opened on its own still edits the sheet's entities. Generated sheets: a box section with its plan and a stated bed level,
and a sheet whose detail is drawn at twice the main scale."""

from __future__ import annotations

import random

import ezdxf
import pytest

from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.frames import frames, view_frame
from dxf_autoparam.plan_bench import Box
from dxf_autoparam.production.bench import _sheet
from dxf_autoparam.workspace import SheetSession


def test_every_view_maps_to_the_sheet_and_back_exactly(tmp_path):
    sm, _us, _up, _g = _sheet(Box(cells=2), tmp_path, "s")
    rnd = random.Random(7)
    for gid in frames(sm, read=True):
        fr = view_frame(sm, gid)
        x0, y0, x1, y1 = sm.layout.group(gid).bbox
        for _ in range(20):
            x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
            lx, ly = fr.to_local(x, y)
            bx, by = fr.to_sheet(lx, ly)
            assert bx == pytest.approx(x, abs=1e-9) and by == pytest.approx(y, abs=1e-9)


def test_the_section_is_set_out_from_its_axis_and_its_stated_level(tmp_path):
    b = Box(cells=2)
    sm, us, up, _g = _sheet(b, tmp_path, "s")
    sec = next(v for v in sm.units[us].views)
    fr = view_frame(sm, sec)
    assert "axis" in fr.x_from or "centre line" in fr.x_from, fr.x_from  # a symmetric box: x = 0 on its axis
    assert fr.level and fr.level["name"] == "BedLevel" and "BedLevel" in fr.y_from
    assert fr.to_local(0.0, fr.level["at_y"])[1] == pytest.approx(0.0), "y = 0 on the stated level"
    assert fr.rl(fr.level["at_y"]) == pytest.approx(fr.level["rl_m"])
    assert fr.rl(fr.level["at_y"] + 1000.0 / fr.mm_per_unit) == pytest.approx(fr.level["rl_m"] + 1.0), "a metre up is a metre of level"
    assert fr.mm_per_unit == pytest.approx(sm.unit(us).sub.units_mm)
    plan = view_frame(sm, sm.units[up].views[0])
    assert plan.level is None or plan.level["name"] == "BedLevel", "a plan states no level of its own"


def test_the_page_summary_carries_each_views_frame_without_reading_every_unit(tmp_path):
    sm, _us, _up, _g = _sheet(Box(cells=1), tmp_path, "s")
    sheet = SheetSession()
    sheet.sm = sm
    views = [g for g in sheet.summary()["groups"] if g["kind"] == "view"]
    assert views and all("local" in g and g["local"]["mm_per_unit"] > 0 for g in views)


def two_scale_sheet(path) -> str:
    """A section at the sheet's scale and, well apart, a detail drawn twice as large whose dimensions state real millimetres."""
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (6000, 0), (6000, 500), (0, 500)], close=True)
    msp.add_lwpolyline([(2000, 500), (2400, 500), (2400, 3000), (2000, 3000)], close=True)
    for base, p1, p2, ang in [((0, -600), (0, 0), (6000, 0), 0), ((6600, 0), (6000, 0), (6000, 500), 90), ((2000, 3400), (2000, 3000), (2400, 3000), 0),
                              ((-700, 500), (2000, 500), (2000, 3000), 90)]:
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=ang).render()
    msp.add_text("SECTION (SCALE 1:100)", height=250, dxfattribs={"insert": (1500, -1400)})
    ox = 30000  # the detail: a 300 × 800 mm member on a 1000 × 200 mm base, drawn at 2 units per millimetre
    msp.add_lwpolyline([(ox, 0), (ox + 2000, 0), (ox + 2000, 400), (ox, 400)], close=True)
    msp.add_lwpolyline([(ox + 700, 400), (ox + 1300, 400), (ox + 1300, 2000), (ox + 700, 2000)], close=True)
    for base, p1, p2, ang, txt in [((ox, -600), (ox, 0), (ox + 2000, 0), 0, "1000"), ((ox + 2600, 0), (ox + 2000, 0), (ox + 2000, 400), 90, "200"),
                                   ((ox + 700, 2400), (ox + 700, 2000), (ox + 1300, 2000), 0, "300"),
                                   ((ox - 700, 400), (ox + 700, 400), (ox + 700, 2000), 90, "800")]:
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=ang, text=txt).render()
    msp.add_text("DETAIL (SCALE 1:50)", height=250, dxfattribs={"insert": (ox + 200, -1400)})
    doc.saveas(str(path))
    return str(path)


def test_a_detail_drawn_at_another_scale_is_said_in_real_millimetres(tmp_path):
    sm = SheetModel.open(two_scale_sheet(tmp_path / "two.dxf"))
    views = sorted(sm.layout.views(), key=lambda g: g.bbox[0])
    assert len(views) == 2, [g.name for g in views]
    main, detail = (view_frame(sm, g.id) for g in views)
    assert main.mm_per_unit == pytest.approx(1.0) and detail.mm_per_unit == pytest.approx(0.5), (main, detail)
    ox = 30000
    a, b = detail.to_local(ox + 700, 400), detail.to_local(ox + 1300, 400)
    assert b[0] - a[0] == pytest.approx(300.0), "the member drawn 600 units wide is 300 mm in its own frame"
    assert detail.to_local(ox + 700, 2000)[1] - a[1] == pytest.approx(800.0)


def test_the_agent_reads_each_view_in_the_frame_the_person_s_view_tab_shows(tmp_path):
    from dxf_autoparam.ai.understanding_tools import view_context

    b = Box(cells=2)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    sec = next(v for v in sm.units[us].views)
    fr, got = view_frame(sm, sec), view_context(sm, sec)["view"]["frame"]
    assert (got["x_from"], got["y_from"]) == (fr.x_from, fr.y_from) and got["origin_dxf"] == [pytest.approx(v, abs=1e-3) for v in fr.origin]
    x0, y0, x1, y1 = sm.layout.group(sec).bbox
    assert got["local_bbox_mm"] == [pytest.approx(v, abs=0.1) for v in (*fr.to_local(x0, y0), *fr.to_local(x1, y1))]
    assert got["level_from"] == "BedLevel" and got["level_at_y0_m"] == pytest.approx(fr.rl(fr.origin[1]), abs=1e-3)
