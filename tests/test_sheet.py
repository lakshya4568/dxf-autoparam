"""A whole sheet as logical views: frame, panel rules, views with their titles / types / scales, tables, notes, the
title block, a watermark — found without touching the drawing, on a built sheet and on real GAD sheets."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from dxf_autoparam.analyse import analyse
from dxf_autoparam.build import Decisions, build
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.program import from_model
from dxf_autoparam.regen import regenerate_program
from dxf_autoparam.sheet import segment, view_drawing

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT.parent / "aagento-bridge" / "public" / "test-fixtures" / "dxf"


def rect(msp, x0, y0, x1, y1, layer="0"):
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": layer})


def text(msp, s, x, y, h=250.0, layer="TEXT"):
    msp.add_text(s, height=h, dxfattribs={"layer": layer, "insert": (x, y)})


def built_sheet(path: Path) -> Path:
    """A1 sheet at 1:100, drawn in mm: an elevation with its plan aligned under it, a detail drawn 4× larger (1:25),
    a table, notes and a title block in a ruled column on the right, a stamp repeated across the sheet."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    rect(msp, 0, 0, 84100, 59400, "BORDER")
    rect(msp, 1000, 1000, 83100, 58400, "BORDER")
    msp.add_line((68000, 1000), (68000, 58400), dxfattribs={"layer": "BORDER"})  # the right column
    msp.add_line((68000, 20000), (83100, 20000), dxfattribs={"layer": "BORDER"})  # title block top
    for k, words in enumerate(["DRG. NO. 001", "DRAWN", "CHECKED", "APPROVED", "GENERAL ARRANGEMENT DRAWING", "CONSULTANT"]):
        text(msp, words, 69000, 18000 - 2500 * k)
    text(msp, "NOTES:", 69000, 56000, 350)
    for k in range(5):
        text(msp, f"{k + 1}. ALL DIMENSIONS ARE IN MILLIMETRES UNLESS STATED.", 69000, 55000 - 700 * k)
    # ELEVATION: a box with an opening
    rect(msp, 10000, 35000, 30000, 45000)
    rect(msp, 14000, 37000, 26000, 43000)
    msp.add_linear_dim(base=(0, 46500), p1=(14000, 45000), p2=(26000, 45000), dxfattribs={"layer": "DIM"}).render()
    msp.add_linear_dim(base=(0, 47500), p1=(10000, 45000), p2=(30000, 45000), dxfattribs={"layer": "DIM"}).render()
    msp.add_linear_dim(base=(31500, 0), p1=(30000, 35000), p2=(30000, 45000), angle=90, dxfattribs={"layer": "DIM"}).render()
    text(msp, "ELEVATION (SCALE 1:100)", 16500, 33200, 400)
    msp.add_line((16500, 33000), (22500, 33000), dxfattribs={"layer": "TEXT"})  # its underline
    # PLAN: aligned under the elevation (the same x set-out)
    rect(msp, 10000, 15000, 30000, 25000)
    msp.add_line((14000, 15000), (14000, 25000))
    msp.add_line((26000, 15000), (26000, 25000))
    text(msp, "PLAN", 18500, 13000, 400)
    # DETAIL at 1:25: drawn 4× the size, its dimensions state the true sizes
    rect(msp, 40000, 30000, 41600, 38000)
    rect(msp, 39200, 28400, 42400, 30000)
    for p1, p2, base, angle, s in [((40000, 38000), (41600, 38000), (0, 39500), 0, "400"),
                                   ((41600, 30000), (41600, 38000), (43500, 0), 90, "2000"),
                                   ((39200, 28400), (42400, 28400), (0, 27200), 0, "800")]:
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, text=s, dxfattribs={"layer": "DIM"}).render()
    text(msp, "DETAIL OF WALL (SCALE 1:25)", 37500, 25500, 400)
    # TABLE: 4 rows × 3 columns with words in the cells, its heading above it
    for k in range(5):
        msp.add_line((40000, 5000 + 1750 * k), (60000, 5000 + 1750 * k))
    for x in (40000, 46000, 54000, 60000):
        msp.add_line((x, 5000), (x, 12000))
    for r in range(4):
        for c, x in enumerate((40500, 46500, 54500)):
            text(msp, f"ROW{r} COL{c}", x, 5500 + 1750 * r, 300)
    text(msp, "HYDRAULIC TABLE", 46000, 12600, 450)
    for k in range(6):  # a stamp across the whole sheet
        text(msp, "SAMPLE STAMP TEXT", 3000 + 11000 * k, 3000 + 8000 * k, 600, "STAMP")
    doc.saveas(path)
    return path


@pytest.fixture(scope="module")
def sheet(tmp_path_factory):
    path = built_sheet(tmp_path_factory.mktemp("sheet") / "sheet.dxf")
    dr, _ = read_dxf(str(path))
    return dr, segment(dr)


def test_the_built_sheet_is_found_as_its_views_tables_notes_and_title_block(sheet):
    dr, lay = sheet
    views = {g.name: g for g in lay.views()}
    assert set(views) == {"ELEVATION", "PLAN", "DETAIL OF WALL"}, [(g.id, g.kind, g.name) for g in lay.groups]
    assert views["ELEVATION"].view_type == "elevation" and views["ELEVATION"].scale == 100
    assert views["PLAN"].view_type == "plan"
    assert views["DETAIL OF WALL"].view_type == "detail" and views["DETAIL OF WALL"].scale == 25
    kinds = {g.kind for g in lay.groups}
    assert {"table", "notes", "title_block"} <= kinds
    table = next(g for g in lay.groups if g.kind == "table")
    assert table.name == "HYDRAULIC TABLE" and sum(1 for i in table.items if dr.items[i].text) >= 12
    assert len(lay.watermark) == 6 and lay.frame is not None and lay.rules
    # every entity belongs to exactly one part of the sheet (or the frame / rules / watermark), none is lost
    owned = [i for g in lay.groups for i in g.items] + lay.furniture()
    assert sorted(owned) == sorted(set(owned)) and set(owned) == {it.index for it in dr.items if it.pts}


def test_a_detail_drawn_at_another_scale_reads_its_own_units(sheet):
    _dr, lay = sheet
    detail = next(g for g in lay.views() if g.name == "DETAIL OF WALL")
    assert detail.units_mm == pytest.approx(0.25)
    assert any("another scale" in q for q in detail.questions)
    assert next(g for g in lay.views() if g.name == "ELEVATION").units_mm is None  # the sheet's own


def test_titles_and_their_underlines_go_with_the_view_they_name(sheet):
    dr, lay = sheet
    el = next(g for g in lay.views() if g.name == "ELEVATION")
    title = next(i for i in el.items if dr.items[i].text and "ELEVATION" in dr.items[i].text)
    underline = next(it.index for it in dr.items if it.dxftype == "LINE" and it.pts[0][1] == 33000)
    assert title in el.titles and underline in el.items
    dims = [i for i in el.items if dr.items[i].dxftype == "DIMENSION"]
    assert len(dims) == 3  # its dimensions join it


def test_a_view_is_a_standalone_drawing_that_maps_back_to_the_sheet(sheet):
    dr, lay = sheet
    el = next(g for g in lay.views() if g.name == "ELEVATION")
    sub, back = view_drawing(dr, el)
    assert len(sub.items) == len(el.items) and back == sorted(el.items)
    assert all(sub.items[k].handle == dr.items[s].handle for k, s in enumerate(back))
    an = analyse(sub)
    r = regenerate_program(from_model(build(an, Decisions())))
    assert not r.issues
    for k, s in enumerate(back):  # unchanged values reproduce the sheet's own points
        if k in r.pts:
            assert all(abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6 for a, b in zip(r.pts[k], dr.items[s].pts, strict=False))
    assert dr.items[back[0]].index == back[0]  # the sheet is untouched


def test_the_same_drawing_gives_the_same_ids_and_keys(sheet, tmp_path):
    dr, lay = sheet
    dr2, _ = read_dxf(dr.path)
    lay2 = segment(dr2)
    assert [(g.id, g.key, g.name) for g in lay.groups] == [(g.id, g.key, g.name) for g in lay2.groups]


@pytest.mark.skipif(not (FIXTURES / "gad_ezdxf_b.dxf").exists(), reason="aagento-bridge fixtures not present")
def test_a_real_sheet_b():
    dr, _ = read_dxf(str(FIXTURES / "gad_ezdxf_b.dxf"))
    lay = segment(dr)
    names = {g.name: g for g in lay.views()}
    assert {"HALF SECTION & HALF ELEVATION", "C/S OF RETURN WALL"} <= set(names)
    assert names["HALF SECTION & HALF ELEVATION"].view_type == "composite"
    assert names["C/S OF RETURN WALL"].scale == 100 and len(names["C/S OF RETURN WALL"].items) >= 50
    assert {g.name for g in lay.groups if g.kind == "table"} == {"HYDRAULIC TABLE", "TRACK STRUCTURE"}
    assert any(g.kind == "title_block" for g in lay.groups)


@pytest.mark.skipif(not (FIXTURES / "gad_ezdxf_a.dxf").exists(), reason="aagento-bridge fixtures not present")
def test_a_real_sheet_a_keeps_its_section_and_plan_whole():
    dr, _ = read_dxf(str(FIXTURES / "gad_ezdxf_a.dxf"))
    lay = segment(dr)
    names = {g.name: g for g in lay.views()}
    for n in ("LONGITUDINAL SECTION(X-X", "PLAN TOP", "CROSS SECTION OF R.C.C BOX", "SECTION OF CURTAIN WALL", "SECTION OF DROP WALL"):
        assert n in names, sorted(names)
    assert len(names["LONGITUDINAL SECTION(X-X"].items) >= 300 and len(names["PLAN TOP"].items) >= 250
    assert names["PLAN TOP"].view_type == "plan" and names["SECTION OF CURTAIN WALL"].scale == 25
    assert {"HYDRAULIC TABLE", "TRACK STRUCTURE"} <= {g.name for g in lay.groups if g.kind == "table"}
