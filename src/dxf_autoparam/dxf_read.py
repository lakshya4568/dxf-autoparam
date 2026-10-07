"""DXF → Drawing: every visible entity, in world coordinates, with where it came from.

What a real GAD file throws at a reader, and what happens to it here:

  damaged / non-standard files     ezdxf.recover — repaired on read, repairs counted
  views stored as BLOCKS (INSERT)  expanded recursively (nested, rotated, scaled, mirrored,
                                   MINSERT arrays); a big block is real geometry, a small one
                                   (level marker, arrow, logo) is a RIGID symbol on its insert
  attributes on blocks (ATTRIB)    read as texts of that block
  mirrored entities (extrusion -Z) turned upright first, so every coordinate is world X/Y
  layers off / frozen, invisible   skipped — the reader sees what CAD shows
  content only in paper space      the busiest paper-space layout is used instead
  DIMENSIONs (also inside blocks)  kept as dimensions: measured points + value + text
  XREF, ACAD_TABLE, IMAGE, OLE ... counted as unsupported and left exactly as they are
  units                            $INSUNITS, else guessed from what the dimensions say

Roles come from drafting conventions only (layer names, linetypes, entity types):
  structural   lines / polylines / arcs / circles on ordinary layers
  reference    centre / axis lines (CENTER, DASHDOT, PHANTOM linetypes, CL / AXIS layers)
  annotation   dimensions, texts, leaders, hatches, symbols, and anything on a dim/text/hatch layer
  fixed        sheet border / title block layers — never moves
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
import ezdxf.recover
import ezdxf.upright
from ezdxf import path as ezpath
from ezdxf.document import Drawing as EzDoc

from .ir import Drawing, Item, Role

INSUNITS_MM = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 14: 100.0}


@dataclass
class ReadOptions:
    tol_mm: float = 0.5
    annotation_layers: str = r"DIM|TEXT|ANNO|NOTE|LEADER|HATCH|SYMB|DEFPOINTS|TABLE|LABEL|VIEWPORT|VPORT"
    fixed_layers: str = r"BORDER|FRAME|TITLE|SHEET|LOGO|REVISION"
    reference_layers: str = r"(^|[^A-Z])(CL|C/L|CENT(RE|ER)|AXIS|AXES|GRID)([^A-Z]|$)"
    reference_linetypes: str = r"CENT|DASHDOT|PHANTOM|DIVIDE"
    include_layers: set[str] | None = None  # analyse only these (others become annotation)
    extra_fixed: set[str] = field(default_factory=set)
    symbol_max_entities: int = 40  # a block with fewer entities than this, and small, is a rigid symbol
    symbol_max_size_frac: float = 0.05  # ... and smaller than this share of the drawing
    units_mm: float | None = None  # override $INSUNITS


STRUCTURAL_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE"}
UNSUPPORTED = {"ACAD_TABLE", "IMAGE", "OLE2FRAME", "OLEFRAME", "WIPEOUT", "UNDERLAY", "PDFUNDERLAY", "DWFUNDERLAY",
               "DGNUNDERLAY", "VIEWPORT", "XLINE", "RAY", "MESH", "3DSOLID", "REGION", "BODY", "SURFACE", "MLEADER", "MULTILEADER"}


def _linetype(doc: EzDoc, e, layer_name: str) -> str:
    lt = (e.dxf.get("linetype") or "BYLAYER").upper()
    if lt in ("BYLAYER", "BYBLOCK"):
        layer = doc.layers.get(layer_name) if layer_name in doc.layers else None
        lt = (layer.dxf.get("linetype") if layer else "CONTINUOUS") or "CONTINUOUS"
    return lt.upper()


def _props(doc: EzDoc, e, layer_name: str) -> dict:
    """Colour (ACI, BYLAYER resolved), linetype and lineweight (mm) as drawn — evidence of what a line is."""
    layer = doc.layers.get(layer_name) if layer_name in doc.layers else None
    layer_color = abs(int(layer.dxf.get("color", 7))) if layer else 7
    color = int(e.dxf.get("color", 256))
    lw = int(e.dxf.get("lineweight", -1))
    if lw < 0 and layer is not None:
        lw = int(layer.dxf.get("lineweight", -3))
    return {"color": layer_color if color in (0, 256) else color, "linetype": _linetype(doc, e, layer_name),
            "lineweight": lw / 100.0 if lw >= 0 else None, "layer_color": layer_color,
            "layer_linetype": ((layer.dxf.get("linetype") if layer else None) or "CONTINUOUS").upper()}


def _role(doc: EzDoc, e, layer_name: str, opts: ReadOptions) -> Role:
    layer = layer_name.upper()
    if re.search(opts.fixed_layers, layer, re.IGNORECASE) or layer_name in opts.extra_fixed:
        return Role.FIXED
    t = e.dxftype()
    if t not in STRUCTURAL_TYPES:
        return Role.ANNOTATION
    if opts.include_layers is not None and layer_name not in opts.include_layers:
        return Role.ANNOTATION
    if t in ("LINE", "LWPOLYLINE", "POLYLINE") and (
        re.search(opts.reference_linetypes, _linetype(doc, e, layer_name), re.IGNORECASE) or re.search(opts.reference_layers, layer, re.IGNORECASE)
    ):
        return Role.REFERENCE
    if re.search(opts.annotation_layers, layer, re.IGNORECASE):
        return Role.ANNOTATION
    return Role.STRUCTURAL


def _xy(p) -> tuple[float, float]:
    return (float(p[0]), float(p[1]))


# Errors malformed DXF DATA raises (bad values, broken references). Programming errors (TypeError,
# AttributeError on our side) are not in it: they must surface, not be absorbed as "bad data".
DATA_ERRORS = (ezdxf.DXFError, ValueError, ArithmeticError, IndexError, KeyError)


def plain_text(e) -> str:
    t = e.dxftype()
    try:
        if t == "MTEXT":
            return e.plain_text(split=False)
        if t in ("TEXT", "ATTRIB", "ATTDEF"):
            return e.plain_text()
    except DATA_ERRORS:  # unparsable formatting codes: the raw string is still the note
        return str(e.dxf.get("text", ""))
    return str(e.dxf.get("text", ""))


def _flatten(e, tol: float) -> list[list[tuple[float, float]]]:
    try:
        p = ezpath.make_path(e)
    except TypeError:  # make_path's documented answer for a type with no path (TEXT, MTEXT, INSERT in a block)
        return []
    try:
        out = []
        for sub in p.sub_paths():
            pts = [(v.x, v.y) for v in sub.flattening(tol)]
            if len(pts) >= 2:
                out.append(pts)
        return out
    except DATA_ERRORS:  # a curve ezdxf cannot flatten is drawn without its shape (display only)
        return []


def entity_points(e, tol: float = 1.0) -> dict | None:
    """The positioning points of one (upright, world-coordinate) entity, in a fixed order the writer replays."""
    t = e.dxftype()
    if t == "LINE":
        return {"pts": [_xy(e.dxf.start), _xy(e.dxf.end)], "vertex_pts": [0, 1], "segments": [(0, 1)]}
    if t == "LWPOLYLINE":
        raw = list(e.get_points("xyb"))
        if not raw:
            return None
        return _poly([(float(x), float(y)) for x, y, _ in raw], [float(b) for _, _, b in raw], bool(e.closed))
    if t == "POLYLINE":
        if e.is_poly_face_mesh or e.is_polygon_mesh:
            return None
        verts = list(e.vertices)
        if not verts:
            return None
        return _poly([_xy(v.dxf.location) for v in verts], [float(v.dxf.get("bulge", 0.0)) for v in verts], bool(e.is_closed))
    if t == "ARC":
        return {
            "pts": [_xy(e.dxf.center), _xy(e.start_point), _xy(e.end_point)],
            "vertex_pts": [1, 2],
            "segments": [],
            "radius": float(e.dxf.radius),
            "extra": {"start_angle": e.dxf.start_angle, "end_angle": e.dxf.end_angle},
        }
    if t == "CIRCLE":
        return {"pts": [_xy(e.dxf.center)], "vertex_pts": [0], "segments": [], "radius": float(e.dxf.radius)}
    if t in ("ELLIPSE", "SPLINE"):
        disp = _flatten(e, tol)
        anchor = _xy(e.dxf.center) if t == "ELLIPSE" else (disp[0][0] if disp else (0.0, 0.0))
        return {"pts": [anchor], "vertex_pts": [], "segments": [], "display": disp}
    if t in ("TEXT", "ATTRIB", "ATTDEF"):
        pts = [_xy(e.dxf.insert)]
        if e.dxf.hasattr("align_point") and (e.dxf.get("halign", 0) or e.dxf.get("valign", 0)):
            pts.append(_xy(e.dxf.align_point))
        return {"pts": pts, "vertex_pts": [], "segments": [], "text": plain_text(e), "text_height": float(e.dxf.get("height", 1.0)),
                "extra": {"rotation": float(e.dxf.get("rotation", 0.0)), "raw": e.dxf.get("text", "")}}
    if t == "MTEXT":
        return {"pts": [_xy(e.dxf.insert)], "vertex_pts": [], "segments": [], "text": plain_text(e), "text_height": float(e.dxf.get("char_height", 1.0)),
                "extra": {"rotation": float(e.get_rotation() if hasattr(e, "get_rotation") else e.dxf.get("rotation", 0.0)), "raw": e.text}}
    if t == "DIMENSION":
        pts = [_xy(e.dxf.get("defpoint", (0, 0))), _xy(e.dxf.get("defpoint2", (0, 0))), _xy(e.dxf.get("defpoint3", (0, 0))), _xy(e.dxf.get("text_midpoint", (0, 0)))]
        try:
            measurement = float(e.get_measurement()) if (int(e.dxf.dimtype) & 7) in (0, 1) else float(e.dxf.get("actual_measurement", 0.0) or 0.0)
        except DATA_ERRORS:
            measurement = float(e.dxf.get("actual_measurement", 0.0) or 0.0)
        disp = []
        try:
            for v in e.virtual_entities():
                disp.extend(_flatten(v, tol))
        except DATA_ERRORS:  # no block to draw it from: it is redrawn from its points instead
            disp = []
        return {"pts": pts, "vertex_pts": [], "segments": [], "text": e.dxf.get("text", ""), "display": disp,
                "extra": {"dimtype": int(e.dxf.dimtype) & 7, "angle": float(e.dxf.get("angle", 0.0)), "measurement": measurement}}
    if t == "LEADER":
        return {"pts": [_xy(v) for v in e.vertices], "vertex_pts": [], "segments": []}
    if t == "HATCH":
        # Points in path order (the writer replays it); each boundary as indices into
        # them, so a hatch is redrawn from its regenerated boundary.
        pts: list[tuple[float, float]] = []
        rings: list[list[int]] = []
        for p in e.paths:
            ring: list[int] = []
            if hasattr(p, "vertices"):
                for v in p.vertices:
                    ring.append(len(pts))
                    pts.append((float(v[0]), float(v[1])))
            else:
                for edge in p.edges:
                    name = type(edge).__name__
                    if name == "LineEdge":
                        ring.append(len(pts))
                        pts.extend([_xy(edge.start), _xy(edge.end)])
                    elif name in ("ArcEdge", "EllipseEdge"):
                        ring.append(len(pts))
                        pts.append(_xy(edge.center))
                    elif name == "SplineEdge":
                        for c in edge.control_points:
                            ring.append(len(pts))
                            pts.append(_xy(c))
            if len(ring) >= 3:
                rings.append(ring)
        if e.seeds:
            pts.extend(_xy(p) for p in e.seeds)
        polys = [[pts[k] for k in r] for r in rings]
        return {"pts": pts, "vertex_pts": [], "segments": [], "extra": {"polys": polys, "rings": rings, "pattern": e.dxf.get("pattern_name", "")}}
    if t in ("SOLID", "TRACE", "3DFACE"):
        return {"pts": [_xy(e.dxf.get(f"vtx{i}", (0, 0))) for i in range(4)], "vertex_pts": [], "segments": []}
    if t == "POINT":
        return {"pts": [_xy(e.dxf.location)], "vertex_pts": [], "segments": []}
    if t == "INSERT":
        return {"pts": [_xy(e.dxf.insert)], "vertex_pts": [], "segments": [], "extra": {"block": e.dxf.name}}
    return None


def _poly(pts, bulges, closed) -> dict:
    n = len(pts)
    segs = []
    last = n if closed else n - 1
    for i in range(last):
        j = (i + 1) % n
        if abs(bulges[i]) < 1e-9 and pts[i] != pts[j]:
            segs.append((i, j))
    return {"pts": pts, "vertex_pts": list(range(n)), "segments": segs, "bulges": bulges, "closed": closed}


def _visible_layers(doc: EzDoc) -> set[str]:
    out = set()
    for layer in doc.layers:
        try:
            if layer.is_on() and not layer.is_frozen():
                out.add(layer.dxf.name)
        except DATA_ERRORS:  # unreadable layer flags: shown, rather than silently dropping its entities
            out.add(layer.dxf.name)
    return out


def _upright(e) -> None:
    """Flip a mirrored (0, 0, -1) extrusion into world coordinates. ezdxf ignores entities it does not handle;
    it raises only on broken data (a zero extrusion vector), which the per-entity guard counts."""
    ezdxf.upright.upright(e)


def _block_size(doc: EzDoc, name: str) -> tuple[int, float]:
    """(entity count, diagonal of the block's own extents)."""
    blk = doc.blocks.get(name)
    if blk is None:
        return 0, 0.0
    n = len(blk)
    try:
        from ezdxf import bbox

        b = bbox.extents(blk, fast=True)
        return n, (b.size.magnitude if b.has_data else 0.0)
    except DATA_ERRORS:  # extents unknown: not treated as a small symbol
        return n, 0.0


def read_dxf(path: str, opts: ReadOptions | None = None) -> tuple[Drawing, EzDoc]:
    opts = opts or ReadOptions()
    notes: list[str] = []
    try:
        doc, auditor = ezdxf.recover.readfile(path)
        if auditor.fixes:
            notes.append(f"{len(auditor.fixes)} structural problem(s) in the file were repaired on read.")
    except ezdxf.DXFStructureError as exc:
        # Not loadable even in recovery mode (e.g. R12-style entities under a modern header):
        # rebuild it from raw tags into a clean file, and work on that file from here on.
        from .dxf_repair import rebuild

        rebuilt = str(Path(".cache") / "rebuilt" / (Path(path).stem + ".rebuilt.dxf"))
        doc, counts = rebuild(path, rebuilt)
        lost = {k: v for k, v in counts.items() if k != "rebuilt"}
        notes.append(f"The file is malformed ({exc}); rebuilt {counts['rebuilt']} entities into a clean R2018 file"
                     + (f", could not carry {lost}" if lost else "") + ".")
        path = rebuilt
    layout = doc.modelspace()
    if len(layout) < 2:
        busiest = max((lo for lo in doc.layouts if not lo.is_modelspace), key=len, default=None)
        if busiest is not None and len(busiest) > len(layout):
            layout = busiest
            notes.append(f"Model space is empty; read paper space layout '{busiest.name}'.")
    visible = _visible_layers(doc)
    items: list[Item] = []
    unsupported: Counter[str] = Counter()
    hidden = 0

    # The drawing's size decides what a "small" (symbol) block is.
    try:
        from ezdxf import bbox

        ext = bbox.extents(layout, fast=True)
        sheet = ext.size.magnitude if ext.has_data else 1.0
    except DATA_ERRORS:
        sheet = 1.0
        notes.append("The sheet's extents could not be computed; curves are flattened at a default tolerance.")
    sizes: dict[str, tuple[int, float]] = {}
    tol_flat = max(sheet * 2e-4, 1e-6)

    def add(e, src: str, layer_name: str, anchor: int | None, force_role: Role | None) -> int | None:
        t = e.dxftype()
        if t in UNSUPPORTED:
            unsupported[t] += 1
            return None
        try:
            _upright(e)
            info = entity_points(e, tol_flat)
        except (*DATA_ERRORS, AttributeError, TypeError) as exc:  # one malformed entity: counted, the rest is read
            unsupported[f"{t} (unreadable: {type(exc).__name__})"] += 1
            return None
        if info is None:
            unsupported[t] += 1
            return None
        role = force_role or _role(doc, e, layer_name, opts)
        info.setdefault("extra", {})["props"] = _props(doc, e, layer_name)
        it = Item(
            index=len(items), handle=src.split("/")[0], dxftype=t, layer=layer_name, role=role, pts=info["pts"],
            closed=info.get("closed", False), bulges=info.get("bulges", []), radius=info.get("radius"),
            text=info.get("text"), text_height=info.get("text_height"), vertex_pts=info["vertex_pts"],
            segments=info["segments"], extra=info.get("extra", {}), src=src, anchor=anchor, display=info.get("display", []),
        )
        items.append(it)
        return it.index

    def expand(ins, src: str, parent_layer: str, anchor: int | None, symbol: bool) -> None:
        """Block content in world coordinates; nested blocks recurse depth-first (the order explode() uses)."""
        try:
            children = list(ins.virtual_entities())
        except (*DATA_ERRORS, AttributeError, TypeError) as exc:
            unsupported[f"INSERT (cannot expand: {type(exc).__name__})"] += 1
            return
        for k, v in enumerate(children):
            layer_name = parent_layer if v.dxf.get("layer", "0") == "0" else v.dxf.layer
            if v.dxf.get("invisible", 0):
                continue
            sub = f"{src}/{k}"
            if v.dxftype() == "INSERT":
                expand_insert(v, sub, layer_name, anchor, symbol)
            else:
                add(v, sub, layer_name, anchor, Role.ANNOTATION if symbol else None)
        for a, att in enumerate(getattr(ins, "attribs", [])):
            add(att, f"{src}/@{a}", att.dxf.get("layer", parent_layer), anchor, Role.ANNOTATION)

    def expand_insert(ins, src: str, layer_name: str, anchor: int | None, symbol: bool) -> None:
        try:
            _upright(ins)
        except (*DATA_ERRORS, AttributeError, TypeError) as exc:
            unsupported[f"INSERT (unreadable: {type(exc).__name__})"] += 1
            return
        name = ins.dxf.name
        blk = doc.blocks.get(name)
        if blk is None or blk.block.is_xref:
            unsupported["XREF" if blk is not None else "INSERT (missing block)"] += 1
            return
        if name not in sizes:
            sizes[name] = _block_size(doc, name)
        n, diag = sizes[name]
        scale = max(abs(ins.dxf.get("xscale", 1.0)), abs(ins.dxf.get("yscale", 1.0)))
        small = n <= opts.symbol_max_entities and diag * scale <= opts.symbol_max_size_frac * sheet
        if anchor is None and small:
            # a rigid symbol: everything in it follows its insertion point
            anchor = add(ins, src, layer_name, None, Role.ANNOTATION)
            symbol = True
        if ins.mcount > 1:
            for m, single in enumerate(ins.multi_insert()):
                expand(single, f"{src}#{m}", layer_name, anchor, symbol)
        else:
            expand(ins, src, layer_name, anchor, symbol)

    for e in layout:
        if e.dxf.get("invisible", 0):
            hidden += 1
            continue
        layer_name = e.dxf.get("layer", "0")
        if layer_name not in visible:
            hidden += 1
            continue
        if e.dxftype() == "INSERT":
            expand_insert(e, e.dxf.handle, layer_name, None, False)
        else:
            add(e, e.dxf.handle, layer_name, None, None)
    if hidden:
        notes.append(f"{hidden} entities on layers that are off/frozen (or invisible) were not read, as CAD does not show them.")

    declared = INSUNITS_MM.get(int(doc.header.get("$INSUNITS", 0) or 0))
    measured = _guess_units(items, [])
    if opts.units_mm:
        units_mm = opts.units_mm
    elif declared and measured and abs(declared / measured - 1) > 0.05 and _has_dims(items):
        units_mm = measured
        notes.append(f"The header says 1 unit = {declared:g} mm but the dimensions measure 1 unit = {measured:g} mm; the dimensions win.")
    else:
        units_mm = declared or _guess_units(items, notes)
    _fix_frames(items, notes)
    struct = [it.pts[k] for it in items if it.role == Role.STRUCTURAL for k in it.vertex_pts]
    xs = [p[0] for p in struct]
    ys = [p[1] for p in struct]
    extent = (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)
    dr = Drawing(path=path, units_mm=units_mm, tol=opts.tol_mm / units_mm, items=items, extent=extent,
                 unsupported=dict(unsupported), notes=notes, layout=layout.name)
    return dr, doc


def _fix_frames(items: list[Item], notes: list[str]) -> None:
    """The sheet border — an outline or line spanning (nearly) the whole drawing in both directions
    or along one full side — is FIXED: it never moves, and it does not join the views it surrounds."""
    pts = [p for it in items if it.role in (Role.STRUCTURAL, Role.REFERENCE) for p in it.pts]
    if not pts:
        return
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    W, H = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    fixed = 0
    for it in items:
        if it.role != Role.STRUCTURAL or len(it.pts) < 2:
            continue
        xs, ys = [p[0] for p in it.pts], [p[1] for p in it.pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if (w > 0.9 * W and h > 0.9 * H) or (w > 0.97 * W and h < 0.01 * H and min(ys) - y0 < 0.02 * H or w > 0.97 * W and y1 - max(ys) < 0.02 * H and h < 0.01 * H)\
                or (h > 0.97 * H and w < 0.01 * W and (min(xs) - x0 < 0.02 * W or x1 - max(xs) < 0.02 * W)):
            it.role = Role.FIXED
            fixed += 1
    if fixed:
        notes.append(f"{fixed} sheet-border line(s) are held fixed.")


def _has_dims(items: list[Item]) -> bool:
    return sum(1 for it in items if it.dxftype == "DIMENSION" and it.extra.get("dimtype") in (0, 1)) >= 3


def _guess_units(items: list[Item], notes: list[str]) -> float:
    """No $INSUNITS: a dimension's stated number over its drawn length tells the drawing unit.

    stated/drawn ≈ 1     drawn in mm, written in mm        → 1 mm per unit
    stated/drawn ≈ 1000  drawn in m, written in mm         → 1000 mm per unit
    stated/drawn ≈ 0.001 drawn in mm, written in m         → 1 mm per unit
    stated/drawn ≈ 10    drawn in cm, written in mm        → 10 mm per unit
    """
    ratios = []
    for it in items:
        if it.dxftype == "DIMENSION" and it.extra.get("dimtype") in (0, 1):
            length = math.dist(it.pts[1], it.pts[2])
            nums = re.findall(r"\d+(?:\.\d+)?", it.text or "")
            value = float(nums[0]) if nums else it.extra.get("measurement", 0.0)
            if length > 0 and value:
                ratios.append(value / length)
    if ratios:
        ratios.sort()
        r = ratios[len(ratios) // 2]
        for ratio, mm_per_unit, label in ((1.0, 1.0, "mm"), (1000.0, 1000.0, "m"), (0.001, 1.0, "mm (values written in m)"), (10.0, 10.0, "cm")):
            if abs(r / ratio - 1) < 0.05:
                notes.append(f"No units in the file; dimensions say the drawing unit is {label}.")
                return mm_per_unit
    notes.append("No units in the file; millimetres assumed.")
    return 1.0
