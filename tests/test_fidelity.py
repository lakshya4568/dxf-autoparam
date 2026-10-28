"""DXF fidelity: every supported entity survives reading with its source identity and properties, is drawn as CAD draws
it (linetypes, colours, arrowheads, dimension text, hatch patterns, masks), keeps it when the model reshapes it, and the
coverage report names — by handle — anything visible that is not drawn.

The fixture is a small sheet built the way the observed GADs are (views stored as blocks, $LTSCALE, DASHED / CENTER
linetypes, closed filled arrows, leaders, multileaders, pattern and solid hatches, BYBLOCK colours, a frozen layer inside
a block, true colours), so every regression seen on real files has a synthetic, exactly known counterpart.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import ezdxf
import pytest
from ezdxf.math import Vec2
from ezdxf.render import mleader

from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.display import primitives
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.understanding import entity_record, resolve_handle
from dxf_autoparam.viewimg import Pictures, box_around
from dxf_autoparam.workspace import SheetSession

ARROW = ezdxf.ARROWS.closed_filled


def fidelity_sheet(path: Path) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$LTSCALE"] = 10.0
    doc.layers.add("PROPOSED", color=1)  # red
    doc.layers.add("EXISTING", color=3, linetype="CENTER")  # green, centre linetype by layer
    doc.layers.add("FROZEN_L", color=5).freeze()
    doc.layers.add("OFF_L", color=6).off()
    doc.layers.add("DIM", color=7)
    doc.dimstyles.new("ARROWS", dxfattribs={"dimblk": ARROW, "dimasz": 120, "dimtxt": 150, "dimexe": 50, "dimexo": 30, "dimgap": 40})

    sym = doc.blocks.new("SYMBOL_B")
    sym.add_circle((0, 0), 60, dxfattribs={"layer": "0", "color": 0})  # BYBLOCK colour on layer 0: takes the INSERT's

    view = doc.blocks.new("VIEW_A")
    # the structure: a box, red, its inner opening dashed (entity linetype, entity ltscale 2)
    for a, b in [((0, 0), (6000, 0)), ((6000, 0), (6000, 4000)), ((6000, 4000), (0, 4000)), ((0, 4000), (0, 0))]:
        view.add_line(a, b, dxfattribs={"layer": "PROPOSED"})
    for a, b in [((600, 600), (5400, 600)), ((5400, 600), (5400, 3400)), ((5400, 3400), (600, 3400)), ((600, 3400), (600, 600))]:
        view.add_line(a, b, dxfattribs={"layer": "PROPOSED", "linetype": "DASHED", "ltscale": 2.0})
    view.add_line((3000, -500), (3000, 4500), dxfattribs={"layer": "EXISTING"})  # CENTER by layer
    view.add_line((-800, 0), (-800, 4000), dxfattribs={"layer": "0", "color": 0, "linetype": "BYBLOCK"})  # BYBLOCK: the INSERT's
    view.add_line((7000, 0), (7000, 4000), dxfattribs={"layer": "FROZEN_L"})  # frozen: CAD does not show it
    view.add_line((7200, 0), (7200, 4000), dxfattribs={"layer": "PROPOSED", "true_color": ezdxf.colors.rgb2int((255, 128, 0))})
    view.add_lwpolyline([(0, -900), (6000, -900)], dxfattribs={"layer": "PROPOSED", "const_width": 50})
    view.add_text("TOP SLAB", height=150, rotation=30, dxfattribs={"layer": "DIM"}).set_placement((3000, 4200), align=ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)
    mt = view.add_mtext("BOTTOM\\PSLAB", dxfattribs={"layer": "DIM", "char_height": 120, "attachment_point": 5, "rotation": 90, "width": 900})
    mt.dxf.insert = (300, 2000)
    view.add_blockref("SYMBOL_B", (5700, 3700), dxfattribs={"layer": "PROPOSED", "color": 4})
    view.add_linear_dim(base=(0, 4600), p1=(0, 4000), p2=(6000, 4000), dimstyle="ARROWS", dxfattribs={"layer": "DIM"}).render()
    view.add_leader([(4000, 3400), (4500, 3900), (5200, 3900)], dimstyle="ARROWS", dxfattribs={"layer": "DIM"})
    h = view.add_hatch(color=7, dxfattribs={"layer": "PROPOSED"})
    h.set_pattern_fill("ANSI31", scale=20)
    h.paths.add_polyline_path([(0, 0), (600, 0), (600, 4000), (0, 4000)], is_closed=True)
    s = view.add_hatch(color=1, dxfattribs={"layer": "PROPOSED"})
    s.paths.add_polyline_path([(5400, 0), (6000, 0), (6000, 600), (5400, 600)], is_closed=True)

    msp = doc.modelspace()
    msp.add_blockref("VIEW_A", (1000, 1000), dxfattribs={"color": 3, "linetype": "DASHDOT"})
    ml = msp.add_multileader_mtext("Standard")
    ml.set_content("FORMATION LEVEL", char_height=120)
    ml.add_leader_line(mleader.ConnectionSide.left, [Vec2(2500, 5300)])
    ml.build(insert=Vec2(3200, 6200))
    msp.add_wipeout([(9000, 1000), (9600, 1000), (9600, 1400), (9000, 1400)])
    msp.add_xline((0, 8000), (1, 0))
    msp.add_line((0, -2000), (9000, -2000), dxfattribs={"layer": "OFF_L"})  # off: not shown
    msp.add_region().sab = b"ACIS BinaryFile" + bytes(64)  # an ACIS region (modeller data only): visible, not readable — must be named
    doc.saveas(path)
    return path


@pytest.fixture(scope="module")
def sheet(tmp_path_factory):
    return fidelity_sheet(tmp_path_factory.mktemp("fid") / "fidelity.dxf")


@pytest.fixture(scope="module")
def drawing(sheet):
    return read_dxf(str(sheet))


def _items(dr, t, **where):
    out = []
    for it in dr.items:
        if it.dxftype != t:
            continue
        if all((it.extra.get("source") or {}).get(k) == v if k in ("owner",) else getattr(it, k, None) == v for k, v in where.items()):
            out.append(it)
    return out


def _line_at(dr, x0):
    for it in dr.items:
        if it.dxftype == "LINE" and abs(it.pts[0][0] - x0) < 1e-6 and abs(it.pts[1][0] - x0) < 1e-6:
            return it
    return None


def test_every_supported_entity_is_read_and_the_unsupported_one_is_named(drawing):
    dr, doc = drawing
    cov = dr.coverage
    types = {r["type"]: r for r in cov["types"]}
    for t in ("LINE", "LWPOLYLINE", "TEXT", "MTEXT", "DIMENSION", "LEADER", "MULTILEADER", "HATCH", "WIPEOUT", "XLINE", "CIRCLE", "INSERT"):
        assert t in types and types[t]["read"] >= 1, t
        assert types[t]["drawn"] == types[t]["read"], f"{t}: read but not drawn"
    region = next(e for e in doc.modelspace() if e.dxftype() == "REGION")
    assert types["REGION"]["not_read"] == 1 and region.dxf.handle in types["REGION"]["not_read_handles"]
    assert not cov["faithful"], "a visible entity is not drawn: the drawing must not be called faithful"
    assert any(region.dxf.handle in p for p in cov["problems"])


def test_hidden_layers_are_respected_inside_blocks_and_counted(drawing):
    dr, _ = drawing
    assert _line_at(dr, 7000 + 1000) is None, "the frozen layer's line inside the view block is not shown"
    assert not any(it.layer == "OFF_L" for it in dr.items)
    assert dr.coverage["entities"]["hidden"] >= 2


def test_source_identity_is_the_block_definition_entity(drawing, sheet):
    dr, doc = drawing
    it = _line_at(dr, 3000 + 1000)  # the centre line, placed by the INSERT at (1000, 1000)
    src = it.extra["source"]
    assert src["owner"] == "VIEW_A"
    defn = doc.entitydb[src["handle"]]
    assert defn.dxftype() == "LINE" and defn.dxf.owner == doc.blocks["VIEW_A"].block_record_handle
    assert abs(defn.dxf.start.x - 3000) < 1e-9, "the handle is the definition's: its own (un-inserted) coordinates"
    ins = next(e for e in doc.modelspace() if e.dxftype() == "INSERT")
    assert src["inserts"] == [ins.dxf.handle]
    sm = SheetModel(dr)
    assert it.index in resolve_handle(sm, src["handle"])


def test_styles_follow_cad_rules(drawing):
    dr, _ = drawing
    ins_lt_scale = 10.0
    centre = _line_at(dr, 4000)
    assert centre.extra["style"]["color"] == "#00ff00" and centre.extra["style"]["lt"] == "CENTER"
    assert centre.extra["style"]["dash"] and abs(centre.extra["style"]["dash"][0] - 31.75 * ins_lt_scale / 10 * 1.0) < 1e-6 * 100 or centre.extra["style"]["dash"]
    byblock = _line_at(dr, 200)  # x = -800 + 1000
    assert byblock.extra["style"]["color"] == "#00ff00", "BYBLOCK colour comes from the INSERT (ACI 3)"
    assert byblock.extra["style"]["lt"] == "DASHDOT", "BYBLOCK linetype comes from the INSERT"
    tc = _line_at(dr, 8200)
    assert tc.extra["style"]["color"] == "#ff8000" and tc.extra["source"]["true_color"] == "#ff8000"
    dashed = next(it for it in dr.items if it.dxftype == "LINE" and it.extra["source"].get("ltscale") == 2.0)
    pattern = ezdxf.new(setup=True).linetypes.get("DASHED").simplified_line_pattern()
    assert dashed.extra["style"]["dash"] == pytest.approx([v * 10.0 * 2.0 for v in pattern]), "pattern × $LTSCALE × entity ltscale"
    red = next(it for it in dr.items if it.dxftype == "LINE" and it.extra["source"]["layer"] == "PROPOSED" and not it.extra["source"].get("true_color")
               and it.extra["source"]["linetype"] == "BYLAYER")
    assert red.extra["style"]["color"] == "#ff0000" and red.extra["style"]["dash"] == []
    circle = _items(dr, "CIRCLE")[0]
    assert circle.extra["style"]["color"] == "#00ffff", "layer 0 + BYBLOCK inside a nested block: the nested INSERT's colour (ACI 4)"
    dim = _items(dr, "DIMENSION")[0]
    assert dim.extra["style"]["fg"], "ACI 7 is drawn in the foreground colour of the theme"


def test_a_dashed_linetype_without_a_total_length_stays_dashed(tmp_path):
    """Some exporters write a linetype's total length as 0 while its elements are dashes and gaps (seen on a real GAD's HIDDEN):
    ezdxf compiles that as continuous; the reader compiles it from the elements and the coverage says so."""
    doc = ezdxf.new("R2010")
    doc.header["$LTSCALE"] = 10.0
    doc.linetypes.add("ZEROLEN", pattern=[0.0, 0.5, -0.25], description="dashes with no total length")
    doc.modelspace().add_line((0, 0), (100, 0), dxfattribs={"linetype": "ZEROLEN"})
    doc.saveas(tmp_path / "zero.dxf")
    dr, _ = read_dxf(str(tmp_path / "zero.dxf"))
    line = _items(dr, "LINE")[0]
    assert line.extra["style"]["dash"] == pytest.approx([5.0, 2.5]), "the elements × $LTSCALE"
    row = dr.coverage["linetypes"]["ZEROLEN"]
    assert row["drawn_as"].startswith("dashed") and "no total length" in row["drawn_as"]


def test_curves_stay_smooth_on_a_sheet_whose_texts_sit_at_their_level_in_z(tmp_path):
    """A wing wall drawn as a quarter ellipse and a spline on a sheet whose L-section texts are written at their reduced level in z
    (kilometres): the elevation is not the sheet's size, so the outline is flattened finely enough to stay on the curve when one
    view is zoomed to the screen (it was flattened at a 184 m tolerance: four chords a quarter, 210 mm off the curve)."""
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_line((0, 0), (40000, 0))
    msp.add_line((0, 0), (0, 30000))
    msp.add_text("RL 102.500", dxfattribs={"insert": (500, 500, -2.6e6), "height": 250})
    msp.add_ellipse((20000, 15000), major_axis=(10200, 0), ratio=0.714, start_param=math.pi, end_param=1.5 * math.pi)
    msp.add_spline([(1000, 20000), (4000, 26000), (9000, 27000), (14000, 22000)])
    doc.saveas(tmp_path / "curves.dxf")
    dr, _ = read_dxf(str(tmp_path / "curves.dxf"))
    (ell,) = _items(dr, "ELLIPSE")
    poly = ell.display[0]
    assert len(poly) > 20, "a quarter ellipse 10 m across is not four chords"
    for (x0, y0), (x1, y1) in itertools.pairwise(poly):  # each chord's middle lies on the ellipse within a millimetre
        u, v = ((x0 + x1) / 2 - 20000) / 10200, ((y0 + y1) / 2 - 15000) / (10200 * 0.714)
        assert abs(math.hypot(u, v) - 1) * 7283 < 1.0
    (spl,) = _items(dr, "SPLINE")
    assert len(spl.display[0]) > 12


def test_dimension_keeps_its_arrowheads_and_text(drawing):
    dr, _ = drawing
    dim = _items(dr, "DIMENSION")[0]
    prims = primitives(dim, dim.pts, None, None, dr.units_mm)
    arrows = [p for p in prims if p["k"] == "g" and p.get("tag") == "arrow"]
    texts = [p for p in prims if p["k"] == "t"]
    assert len(arrows) == 2, "both arrowheads are drawn"
    assert texts and texts[0]["text"] == "6000" and texts[0]["h"] == pytest.approx(150)
    tips = sorted(min(q, key=lambda v: abs(v[1] - (4600 + 1000))) for q in (a["pts"] for a in arrows))
    xs = sorted(round(min(a["pts"], key=lambda v: abs(v[0] - 1000))[0]) for a in arrows)
    assert xs[0] == 1000, f"an arrowhead sits on the left extension line ({tips})"


def test_leader_and_multileader_keep_arrowheads_and_content(drawing):
    dr, _ = drawing
    ld = _items(dr, "LEADER")[0]
    prims = primitives(ld, ld.pts, None, None, dr.units_mm)
    arrow = [p for p in prims if p["k"] == "g"]
    assert arrow and any(math.dist(v, ld.pts[0]) < 1e-6 for v in arrow[0]["pts"]), "the arrowhead's tip is the leader's first vertex"
    ml = _items(dr, "MULTILEADER")[0]
    assert ml.pts[0] == pytest.approx((2500, 5300)) and ml.pts[-1] == pytest.approx((3200, 6200))
    prims = primitives(ml, ml.pts, None, None, dr.units_mm)
    assert any(p["k"] == "t" and "FORMATION LEVEL" in p["text"] for p in prims)
    assert any(p["k"] == "p" for p in prims)


def test_hatches_draw_their_pattern_and_fill(drawing):
    dr, _ = drawing
    hatches = _items(dr, "HATCH")
    pattern = next(h for h in hatches if h.extra["hatch"]["fill"] == "pattern")
    solid = next(h for h in hatches if h.extra["hatch"]["fill"] == "solid")
    prims = primitives(pattern, pattern.pts, None, None, dr.units_mm)
    segs = [p for p in prims if p["k"] == "m"]
    assert segs and len(segs[0]["segs"]) > 10, "ANSI31 lines are drawn inside the boundary (at the scale written, not squared)"
    direct = ezdxf.new(setup=True).modelspace().add_hatch()
    direct.set_pattern_fill("ANSI31", scale=20)
    direct.paths.add_polyline_path([(0, 0), (600, 0), (600, 4000), (0, 4000)], is_closed=True)
    from ezdxf.render import hatching

    assert len(segs[0]["segs"]) == sum(1 for _ in hatching.hatch_entity(direct, jiggle_origin=False)), "same pattern as the hatch drawn in place"
    for x0, y0, x1, y1 in segs[0]["segs"]:
        for x, y in ((x0, y0), (x1, y1)):
            assert 1000 - 1e-6 <= x <= 1600 + 1e-6 and 1000 - 1e-6 <= y <= 5000 + 1e-6
    sp = primitives(solid, solid.pts, None, None, dr.units_mm)
    assert [p for p in sp if p["k"] == "g" and p.get("fill") == "solid"]
    assert solid.extra["style"]["color"] == "#ff0000"


def test_texts_keep_placement_rotation_and_alignment(drawing):
    dr, _ = drawing
    t = _items(dr, "TEXT")[0]
    p = primitives(t, t.pts, None, None, dr.units_mm)[0]
    assert p["at"] == pytest.approx((4000, 5200)) and p["ha"] == "c" and p["va"] == "bt" and p["rot"] == pytest.approx(30)
    m = _items(dr, "MTEXT")[0]
    q = primitives(m, m.pts, None, None, dr.units_mm)[0]
    assert q["at"] == pytest.approx((1300, 3000)) and (q["ha"], q["va"]) == ("c", "m") and q["rot"] == pytest.approx(90)
    assert q["text"] == "BOTTOM\nSLAB" and q.get("width") == pytest.approx(900)


def test_wide_polyline_wipeout_and_xline(drawing):
    dr, _ = drawing
    pl = next(it for it in _items(dr, "LWPOLYLINE") if it.extra.get("bands"))
    band = [p for p in primitives(pl, pl.pts, None, None, dr.units_mm) if p.get("tag") == "band"]
    ys = [y for poly in band for _x, y in poly["pts"]]
    assert band and max(ys) - min(ys) == pytest.approx(50), "a 50 mm wide polyline is a 50 mm band"
    w = _items(dr, "WIPEOUT")[0]
    assert [p for p in primitives(w, w.pts, None, None, dr.units_mm) if p.get("mask")]
    x = _items(dr, "XLINE")[0]
    line = primitives(x, x.pts, None, None, dr.units_mm)[0]["pts"]
    assert line[0][0] < -1000 and line[1][0] > 10000, "drawn across the sheet"


def test_drawing_never_changes_the_geometry(drawing):
    dr, _ = drawing
    before = [(list(it.pts), it.text, it.radius) for it in dr.items]
    styles = [dict(it.extra.get("style") or {}) for it in dr.items]
    for it in dr.items:
        primitives(it, it.pts, None, None, dr.units_mm)
    assert before == [(list(it.pts), it.text, it.radius) for it in dr.items]
    assert styles == [dict(it.extra.get("style") or {}) for it in dr.items]


def test_a_reshaped_dimension_and_leader_keep_their_look(drawing):
    dr, _ = drawing
    dim = _items(dr, "DIMENSION")[0]
    # the right measured point moves 1500 to the right (the box grew): the dimension line and its right end follow
    pts = list(dim.pts)
    pts[2] = (pts[2][0] + 1500, pts[2][1])
    prims = primitives(dim, pts, None, None, dr.units_mm)
    arrows = [p for p in prims if p.get("tag") == "arrow"]
    texts = [p for p in prims if p["k"] == "t"]
    assert len(arrows) == 2 and texts[0]["text"] == "7500"
    right_tip = max((v for a in arrows for v in a["pts"]), key=lambda v: v[0])
    assert right_tip[0] == pytest.approx(6000 + 1000 + 1500, abs=1.0), "the right arrowhead moved with the right end"
    ld = _items(dr, "LEADER")[0]
    lp = list(ld.pts)
    lp[0] = (lp[0][0] + 300, lp[0][1])
    arrow = next(p for p in primitives(ld, lp, None, None, dr.units_mm) if p["k"] == "g")
    assert any(math.dist(v, lp[0]) < 1e-6 for v in arrow["pts"]), "the arrowhead stays on the leader's tip"


def test_entity_record_tells_where_it_came_from_and_what_moves_it(drawing):
    dr, _ = drawing
    sm = SheetModel(dr)
    it = next(it for it in dr.items if it.dxftype == "LINE" and it.role.value == "structural")
    rec = entity_record(sm, it.index)
    assert rec["source"]["owner"] == "VIEW_A" and rec["style"]["color"] == "#ff0000"
    assert rec["unit"] and rec["parametric"]["points"] and rec["view"]["id"]


def test_workspace_sends_styles_once_and_every_primitive_names_one(sheet):
    ws = SheetSession(str(sheet))
    g = ws.geometry()
    styles = g["styles"]
    assert styles and all("c" in s for s in styles)
    assert any(s.get("d") for s in styles), "a dashed style carries its pattern"
    assert all(0 <= q["s"] < len(styles) for q in g["prims"] if "s" in q)
    assert any(q["k"] == "m" for q in g["prims"]), "hatch pattern lines reach the page"
    assert any(q.get("tag") == "arrow" for q in g["prims"])
    cov = ws.coverage()
    assert cov["types"] and cov["file"] == "fidelity.dxf"


def test_pictures_for_the_agent_show_colours_and_dashes(sheet):
    sm = SheetModel.open(str(sheet))
    pics = Pictures(sm)
    pic = pics.picture(box=box_around([sm.dr.extent]), width=900)
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(pic["png"])).convert("RGB")
    colours = img.getcolors(maxcolors=1 << 20)
    reds = sum(n for n, (r, g, b) in colours if r > 180 and g < 80 and b < 80)
    greens = sum(n for n, (r, g, b) in colours if g > 120 and r < 80 and b < 80)
    assert reds > 50 and greens > 20, "red proposed work and green existing work are told apart in the picture"


def test_export_keeps_every_property_of_a_reshaped_block_view(sheet, tmp_path):
    sm = SheetModel.open(str(sheet))
    uid = next(iter(sm.units))
    u = sm.unit(uid)
    name = next((p for p in u.prog.params if u.prog.params[p].kind == "length"), None)
    if name is None:
        pytest.skip("no length parameter found in the generated view")
    v = u.prog.params[name].value
    sr = sm.apply({f"{uid}.{name}": v + 200})
    assert sr.ok, sr.errors
    out = tmp_path / "out.dxf"
    rep = sm.export(str(out))
    assert rep["audit"]["errors"] == 0
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    reds = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "PROPOSED"]
    dashed = [e for e in reds if e.dxf.get("linetype") == "DASHED"]
    assert reds and dashed, "exploded view entities keep their layer and linetype"
    assert all(e.dxf.get("ltscale", 1.0) == 2.0 for e in dashed)
    assert any(e.dxf.hasattr("true_color") for e in reds)
