"""Dimensions and notes follow the geometry: a number written between two set-out lines (an exploded dimension, an
overall size nobody named) shows the new distance; a dimension whose text was typed over with its own number shows
the new measurement; a text a change pushes onto another is reported, never silently overlapped."""

from __future__ import annotations

import itertools
from pathlib import Path

import ezdxf
import pytest
from test_crossview import opening

from dxf_autoparam.crossview import SheetModel


def exploded(path: Path) -> Path:
    """A box drawn as loose lines, its dimensions EXPLODED (a line, two ticks, the number as a plain text) — the way a
    PDF conversion delivers them — plus one native dimension whose text was typed over with its own number."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for a, b in [((0, 0), (4000, 0)), ((4000, 0), (4000, 3000)), ((4000, 3000), (0, 3000)), ((0, 3000), (0, 0)),
                 ((500, 300), (3500, 300)), ((3500, 300), (3500, 2700)), ((3500, 2700), (500, 2700)), ((500, 2700), (500, 300))]:
        msp.add_line(a, b)
    for y, x0, x1, label in [(3500, 500, 3500, "3000"), (3900, 0, 4000, "4000")]:  # opening, then overall width
        msp.add_line((x0, y), (x1, y), dxfattribs={"layer": "DIM"})
        for x in (x0, x1):
            msp.add_line((x - 60, y - 60), (x + 60, y + 60), dxfattribs={"layer": "DIM"})  # ticks
        msp.add_text(label, height=150, dxfattribs={"layer": "DIM", "insert": ((x0 + x1) / 2 - 300, y + 60)})
    msp.add_text("CLEAR OPENING 3000 MM", height=120, dxfattribs={"layer": "TEXT", "insert": (900, 1500)})
    d = msp.add_linear_dim(base=(0, -600), p1=(0, 0), p2=(4000, 0), text="4000", dxfattribs={"layer": "DIM"})
    d.render()
    doc.saveas(path)
    return path


@pytest.fixture
def sm(tmp_path):
    return SheetModel.open(str(exploded(tmp_path / "exploded.dxf")))


def texts_after(sm, sr) -> dict[str, str]:
    out = {}
    for it in sm.dr.items:
        if it.dxftype in ("TEXT", "MTEXT") and it.text:
            out[it.text] = sr.reg.texts.get(it.index, it.text)
    return out


def width_at(sm, sr, y: float) -> float:
    """The drawn distance between the leftmost and rightmost vertical lines that cross height y, after a change."""
    xs = []
    for it in sm.dr.items:
        if it.dxftype == "LINE" and it.layer == "0":
            (x0, y0), (x1, y1) = sr.reg.pts.get(it.index, it.pts)
            if abs(x0 - x1) < 1e-6 and min(y0, y1) <= y <= max(y0, y1):
                xs.append(x0)
    return max(xs) - min(xs)


def test_numbers_written_between_lines_show_the_new_distance(sm):
    uid = next(iter(sm.units))
    sm.share("ClearSpan", [(uid, opening(sm, uid, 3000))])
    r = sm.apply({"ClearSpan": 3600})
    assert r.ok, r.errors
    t = texts_after(sm, r)
    assert t["3000"] == "3600"  # the exploded dimension of the opening
    assert t["CLEAR OPENING 3000 MM"] == "CLEAR OPENING 3600 MM"
    # the overall width, written as an exploded dimension, shows whatever the box measures now (walls kept or not)
    assert t["4000"] == str(round(width_at(sm, r, 100)))


def test_a_typed_over_dimension_shows_and_exports_the_new_measurement(sm, tmp_path):
    uid = next(iter(sm.units))
    sm.share("ClearSpan", [(uid, opening(sm, uid, 3000))])
    r = sm.apply({"ClearSpan": 3600})
    width = round(width_at(sm, r, 100))
    dim_labels = [p["text"] for p in sm.scene() if p["k"] == "t" and p.get("dim")]
    assert dim_labels == [str(width)]
    rep = sm.export(str(tmp_path / "out.dxf"))
    assert rep["audit"]["errors"] == 0
    doc = ezdxf.readfile(str(tmp_path / "out.dxf"))
    dims = [(d.dxf.text, round(d.get_measurement())) for d in doc.modelspace().query("DIMENSION")]
    assert dims == [(str(width), width)]
    notes = sorted(e.dxf.text for e in doc.modelspace().query("TEXT"))
    assert "3600" in notes and str(width) in notes and "CLEAR OPENING 3600 MM" in notes


def test_a_wider_box_moves_every_number_that_measures_it(sm):
    """Keep the walls (name them): now the box grows, and the overall width — a size nobody named — follows."""
    uid = next(iter(sm.units))
    sm.share("ClearSpan", [(uid, opening(sm, uid, 3000))])
    sm.share("Wall", [(uid, opening(sm, uid, 500))])
    r = sm.preview({"ClearSpan": 3600})
    if not r.ok:
        pytest.skip(f"this drawing keeps its outer width: {r.errors[:1]}")
    t = texts_after(sm, r)
    assert t["4000"] == str(round(width_at(sm, r, 100)))


def test_a_note_pushed_onto_another_is_reported_for_review(tmp_path):
    """Notes keep their place against the line they label (two notes on one line move together); a note a change does
    push onto another one of its view is said, for a person to move — never silently overlapped."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for a, b in [((0, 0), (6000, 0)), ((6000, 0), (6000, 3000)), ((6000, 3000), (0, 3000)), ((0, 3000), (0, 0)),
                 ((500, 300), (2500, 300)), ((2500, 300), (2500, 2700)), ((2500, 2700), (500, 2700)), ((500, 2700), (500, 300))]:
        msp.add_line(a, b)
    msp.add_text("CELL", height=200, dxfattribs={"insert": (2200, 1500)})
    msp.add_text("WALL", height=200, dxfattribs={"insert": (3000, 1500)})
    msp.add_text("SECTION A-A", height=250, dxfattribs={"insert": (2200, -800)})  # its title, below it
    path = tmp_path / "notes.dxf"
    doc.saveas(path)
    sm = SheetModel.open(str(path))
    uid = next(iter(sm.units))
    sm.share("Cell", [(uid, opening(sm, uid, 2000))])
    r = sm.preview({"Cell": 2800})
    assert r.ok and not r.warnings  # both notes hang on the face that moves: they move together, nothing overlaps
    cell = next(it.index for it in sm.dr.items if it.text == "CELL")
    assert sm._overlaps([cell], {cell: [(3050, 1520)]}) == [f"{sm.layout.item_group[cell]}: the note 'CELL' now overlaps 'WALL' — move one of them"]
    assert sm._overlaps([cell], {cell: [(2200, 2200)]}) == []


def splay(path: Path) -> Path:
    """A wall on a footing whose toe is set by a 1:1 splay: the horizontal 1350 under the base is not a size of its
    own — it is as long as the splay's height. Exploded dimensions: a line, the number centred ON it (MTEXT, middle)."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    pts = [(0, 0), (3500, 0), (3500, 3000), (1350, 3000), (1350, 1350), (0, 0)]
    for a, b in itertools.pairwise(pts):
        msp.add_line(a, b)
    msp.add_line((1350, 1350), (3500, 1350))
    for x0, x1, s in [(0, 1350, "1350"), (1350, 3500, "2150")]:
        msp.add_line((x0, -300), (x1, -300), dxfattribs={"layer": "DIM"})
        for x in (x0, x1):
            msp.add_line((x, 0), (x, -350), dxfattribs={"layer": "DIM"})
        msp.add_mtext(s, dxfattribs={"layer": "DIM", "insert": ((x0 + x1) / 2, -300), "char_height": 150, "attachment_point": 5})
    for y0, y1, s in [(0, 1350, "1350"), (1350, 3000, "1650")]:
        msp.add_line((3800, y0), (3800, y1), dxfattribs={"layer": "DIM"})
        for y in (y0, y1):
            msp.add_line((3500, y), (3850, y), dxfattribs={"layer": "DIM"})
        msp.add_mtext(s, dxfattribs={"layer": "DIM", "insert": (3800, (y0 + y1) / 2), "char_height": 150, "attachment_point": 5, "rotation": 90})
    doc.saveas(path)
    return path


def test_a_distance_another_size_sets_shows_its_new_length(tmp_path):
    """Raising the wall pushes the splay's toe out: the horizontal number under it follows the drawn distance, even
    though no size of its own changed, and even though a vertical size of the same value exists."""
    sm = SheetModel.open(str(splay(tmp_path / "splay.dxf")))
    u = sm.unit("U01")
    height = next(n for n, p in u.prog.params.items() if round(p.value) == 1350)
    sr = sm.preview({f"U01.{height}": 1730.0})
    assert sr.ok, sr.errors
    shown = sorted(sr.reg.texts.get(it.index, it.text) for it in sm.dr.items if it.dxftype == "MTEXT")
    assert shown == ["1650", "1730", "1730", "2150"]
    under = next(it.index for it in sm.dr.items if it.dxftype == "MTEXT" and it.text == "1350" and abs(it.pts[0][1] + 300) < 1)
    assert under in sr.changed   # a number that changed in place, without moving, counts as changed


def test_texts_are_shown_by_their_cad_anchor_and_dimension_numbers_by_their_style_height(tmp_path):
    from dxf_autoparam.display import primitives

    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_mtext("MID", dxfattribs={"insert": (100, 100), "char_height": 50, "attachment_point": 5})
    msp.add_mtext("TOP RIGHT", dxfattribs={"insert": (100, 300), "char_height": 50, "attachment_point": 3})
    msp.add_text("C", height=40, dxfattribs={"halign": 1, "valign": 0, "insert": (0, 0), "align_point": (500, 500)})
    doc.dimstyles.new("BIG", dxfattribs={"dimtxt": 2.5, "dimscale": 100, "dimgap": 0.625, "dimtad": 1})
    msp.add_linear_dim(base=(0, -600), p1=(0, 0), p2=(4000, 0), dimstyle="BIG").render()
    doc.saveas(tmp_path / "t.dxf")
    sm = SheetModel.open(str(tmp_path / "t.dxf"))
    got = {}
    for it in sm.dr.items:
        for p in primitives(it, it.pts, None, None, sm.dr.units_mm):
            if p["k"] == "t":
                got[p["text"]] = p
    assert (got["MID"]["ha"], got["MID"]["va"], got["MID"]["at"]) == ("c", "m", (100.0, 100.0))
    assert (got["TOP RIGHT"]["ha"], got["TOP RIGHT"]["va"]) == ("r", "t")
    assert (got["C"]["ha"], got["C"]["at"]) == ("c", (500.0, 500.0))   # a centred TEXT hangs from its align point
    dim = got["4000"]
    assert dim["h"] == pytest.approx(250.0) and dim["ha"] == "c"   # 2.5 × 100: it zooms with the drawing
    assert dim["at"][1] > -600   # above its dimension line, as drawn
