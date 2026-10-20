"""A whole sheet as logical views: frame, panel rules, views with their titles / types / scales, tables, notes, the
title block, a watermark — found without touching the drawing, on a built sheet and on real GAD sheets."""

from __future__ import annotations

import re
from pathlib import Path

import ezdxf
import pytest

from dxf_autoparam.analyse import analyse
from dxf_autoparam.build import Decisions, build
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.ir import Role
from dxf_autoparam.program import from_model
from dxf_autoparam.regen import regenerate_program
from dxf_autoparam.sheet import segment, view_drawing

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT.parent / "aagento-bridge" / "public" / "test-fixtures" / "dxf"


def rect(msp, x0, y0, x1, y1, layer="0"):
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": layer})


def text(msp, s, x, y, h=250.0, layer="TEXT"):
    msp.add_text(s, height=h, dxfattribs={"layer": layer, "insert": (x, y)})


def built_sheet(path: Path, automatic_detail_dims: bool = False) -> Path:
    """A1 sheet at 1:100, drawn in mm: an elevation with its plan aligned under it, a detail drawn 4× larger (1:25),
    a table, notes and a title block in a ruled column on the right, a stamp repeated across the sheet. The detail's dimensions
    carry their number as text, or (automatic_detail_dims) are measured by CAD with a linear factor and show it only in the block they are drawn with."""
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
        if automatic_detail_dims:  # no text of its own: the true size is the measurement times the factor, drawn in the block
            msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, override={"dimlfac": 0.25}, dxfattribs={"layer": "DIM"}).render()
        else:
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


def long_section_sheet(path: Path, labels: bool = True, axis_through_title: bool = False) -> Path:
    """A1 sheet at 1:100: a longitudinal section of an existing box and the box proposed beside it, each with its track axis
    (a CENTER-linetype line that runs up to the sheet's margin), a plan under it and a block of notes beside it. Inside the
    section stand a cut label on each axis ("SECTION B-B") and a callout on a leader ("DRAINAGE ARRANGEMENT"); the notes
    mention the drainage arrangement and the section too."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    rect(msp, 0, 0, 84100, 59400, "BORDER")
    rect(msp, 1000, 1000, 83100, 58400, "BORDER")
    # the section: ground, two boxes side by side on it, two approach slopes with their end walls — one connected drawing
    msp.add_line((8000, 24000), (64000, 24000))
    for x0 in (28000, 40000):
        rect(msp, x0, 24000, x0 + 12000, 34000)
        rect(msp, x0 + 2000, 26000, x0 + 10000, 32000)
    msp.add_line((12000, 24000), (12000, 30000))
    msp.add_line((12000, 30000), (28000, 34000))
    msp.add_line((60000, 24000), (60000, 30000))
    msp.add_line((52000, 34000), (60000, 30000))
    # the track axes: centre lines through each box that end near the sheet's margin, as an inner border does
    for x in (34000, 46000):
        msp.add_line((x, 15000 if axis_through_title and x == 34000 else 22000), (x, 58000), dxfattribs={"linetype": "CENTER", "layer": "CENTRE"})
    if labels:
        for x in (34000, 46000):
            text(msp, "SECTION B-B", x - 852, 22400, 250)  # a cut label centred on each axis
        msp.add_leader([(16000, 30000), (18000, 26500), (24000, 26500)])  # a callout: its words rest on the landing
        text(msp, "DRAINAGE ARRANGEMENT", 18000, 26560, 250)
    text(msp, "LONGITUDINAL SECTION (X-X) (SCALE 1:100)", 36000 - 4960, 18500, 400)
    # a plan under it
    rect(msp, 8000, 4000, 30000, 12000)
    rect(msp, 10000, 6000, 28000, 10000)
    msp.add_line((14000, 4000), (14000, 12000))
    msp.add_line((24000, 4000), (24000, 12000))
    text(msp, "PLAN", 17500, 2000, 400)
    # notes beside the section
    text(msp, "NOTES:", 68000, 49700, 350)
    for k, words in enumerate(["1. ALL DIMENSIONS ARE IN MILLIMETRES.", "2. DRAINAGE ARRANGEMENT AS PER SITE REQUIREMENTS.",
                               "3. LEVELS ARE IN METRES.", "4. SECTION B-B IS GIVEN ON THE NEXT SHEET."]):
        text(msp, words, 68000, 49000 - 700 * k, 250)
    doc.saveas(path)
    return path


def _find(dr, s: str) -> int:
    return next(it.index for it in dr.items if it.text and it.text.strip().startswith(s))


@pytest.fixture(scope="module")
def long_section(tmp_path_factory):
    path = long_section_sheet(tmp_path_factory.mktemp("long") / "long_section.dxf")
    dr, _ = read_dxf(str(path))
    return dr, segment(dr)


def test_a_centre_line_through_a_view_is_not_a_panel_rule(long_section):
    dr, lay = long_section
    axis = next(it.index for it in dr.items if it.dxftype == "LINE" and it.pts[0][0] == 34000 and it.pts[1][0] == 34000)
    assert dr.items[axis].role == Role.REFERENCE
    assert axis not in lay.rules  # it ends near the margin like an inner border, but it runs THROUGH a drawing: it parts nothing
    assert lay.item_group[axis] == next(g for g in lay.views() if g.name.startswith("LONGITUDINAL")).id


def test_one_section_is_one_view_whatever_labels_stand_in_it(long_section):
    dr, lay = long_section
    assert sorted(g.name for g in lay.views()) == ["LONGITUDINAL SECTION (X-X)", "PLAN"], [(g.id, g.name, len(g.items)) for g in lay.views()]
    section = next(g for g in lay.views() if g.name.startswith("LONGITUDINAL"))
    assert section.view_type == "section" and section.scale == 100
    ground = next(it.index for it in dr.items if it.dxftype == "LINE" and it.pts[0] == (8000, 24000))
    right_wall = next(it.index for it in dr.items if it.dxftype == "LINE" and it.pts[0] == (60000, 24000))
    box = next(it.index for it in dr.items if it.dxftype == "LWPOLYLINE" and it.pts[0] == (28000, 24000))
    assert {ground, right_wall, box} <= set(section.items)  # both sides of the axis, and the box on it, are one drawing


def test_a_cut_label_and_a_callout_belong_to_the_drawing_not_to_its_title(long_section):
    dr, lay = long_section
    section = next(g for g in lay.views() if g.name.startswith("LONGITUDINAL"))
    cut, callout = _find(dr, "SECTION B-B"), _find(dr, "DRAINAGE ARRANGEMENT")
    assert cut in section.items and callout in section.items  # they are drawn into it ...
    assert cut not in section.titles and callout not in section.titles  # ... and name nothing
    assert section.titles == [_find(dr, "LONGITUDINAL SECTION")]
    assert any("callouts" in n for n in lay.notes)


def test_notes_beside_a_view_stay_notes(long_section):
    dr, lay = long_section
    notes = [g for g in lay.groups if g.kind == "notes"]
    assert len(notes) == 1
    words = {dr.items[i].text.split()[0] for i in notes[0].items if dr.items[i].text}
    assert {"NOTES:", "1.", "2.", "3.", "4."} <= words
    assert not set(notes[0].items) & {i for g in lay.views() for i in g.items}  # none of it is drawn into a view
    assert all("NOTES" not in g.name and "DRAINAGE" not in g.name for g in lay.views())


def test_a_title_with_its_views_axis_through_it_is_still_the_title(tmp_path):
    path = long_section_sheet(tmp_path / "through.dxf", labels=False, axis_through_title=True)
    dr, _ = read_dxf(str(path))
    lay = segment(dr)
    assert sorted(g.name for g in lay.views()) == ["LONGITUDINAL SECTION (X-X)", "PLAN"], [(g.id, g.name) for g in lay.views()]


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


def test_a_detail_whose_automatic_dimensions_show_the_number_only_in_their_block_reads_its_own_units(tmp_path):
    dr, _ = read_dxf(built_sheet(tmp_path / "auto.dxf", automatic_detail_dims=True))
    lay = segment(dr)
    detail = next(g for g in lay.views() if g.name == "DETAIL OF WALL")
    dims = [dr.items[i] for i in detail.items if dr.items[i].dxftype == "DIMENSION"]
    assert dims and not any(re.search(r"\d", (d.text or "").replace("<>", "")) for d in dims)  # the number is not in the dimension's own text
    assert detail.units_mm == pytest.approx(0.25)
    assert next(g for g in lay.views() if g.name == "ELEVATION").units_mm is None  # the sheet's own, whose automatic dimensions agree


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
    for n in ("LONGITUDINAL SECTION(X-X)", "PLAN TOP", "CROSS SECTION OF R.C.C BOX", "SECTION OF CURTAIN WALL", "SECTION OF DROP WALL"):
        assert n in names, sorted(names)
    assert len(names["LONGITUDINAL SECTION(X-X)"].items) >= 300 and len(names["PLAN TOP"].items) >= 250
    assert names["PLAN TOP"].view_type == "plan" and names["SECTION OF CURTAIN WALL"].scale == 25
    assert {"HYDRAULIC TABLE", "TRACK STRUCTURE"} <= {g.name for g in lay.groups if g.kind == "table"}
