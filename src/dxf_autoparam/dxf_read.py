"""DXF → Drawing: every entity reduced to the points that position it.

Roles come from DRAFTING conventions only (layer names, linetypes, entity types) —
nothing here knows what a culvert, slab or girder is:

  structural   LINE / LWPOLYLINE / POLYLINE / ARC / CIRCLE on ordinary layers
  reference    centre / axis lines (CENTER, DASHDOT, PHANTOM linetypes, CL / AXIS layers)
  annotation   DIMENSION, TEXT, MTEXT, LEADER, HATCH, INSERT, ... and anything on a
               dimension / text / hatch layer — it follows the structure
  fixed        sheet border / title block layers — never moves

The patterns are options, so a project with its own layer standard can pass its own.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import ezdxf
from ezdxf.document import Drawing as EzDoc

from .ir import Drawing, Item, Role

INSUNITS_MM = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 14: 100.0}


@dataclass
class ReadOptions:
    tol_mm: float = 0.5
    annotation_layers: str = r"DIM|TEXT|ANNO|NOTE|LEADER|HATCH|SYMB|DEFPOINTS|TABLE|LABEL|VIEWPORT|VPORT"
    fixed_layers: str = r"BORDER|FRAME|TITLE|SHEET|LOGO|REVISION"
    reference_layers: str = r"(^|[^A-Z])(CL|C/L|CENT(RE|ER)|AXIS|AXES|GRID)([^A-Z]|$)"
    reference_linetypes: str = r"CENT|DASHDOT|PHANTOM|DIVIDE"
    include_layers: set[str] | None = None  # analyse only these (others become annotation)
    explode_inserts: bool = False
    extra_fixed: set[str] = field(default_factory=set)


STRUCTURAL_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE"}


def _linetype(doc: EzDoc, e) -> str:
    lt = (e.dxf.get("linetype") or "BYLAYER").upper()
    if lt in ("BYLAYER", "BYBLOCK"):
        layer = doc.layers.get(e.dxf.layer) if e.dxf.layer in doc.layers else None
        lt = (layer.dxf.get("linetype") if layer else "CONTINUOUS") or "CONTINUOUS"
    return lt.upper()


def _role(doc: EzDoc, e, opts: ReadOptions) -> Role:
    layer = e.dxf.layer.upper()
    if re.search(opts.fixed_layers, layer, re.I) or e.dxf.layer in opts.extra_fixed:
        return Role.FIXED
    t = e.dxftype()
    if t not in STRUCTURAL_TYPES:
        return Role.ANNOTATION
    if opts.include_layers is not None and e.dxf.layer not in opts.include_layers:
        return Role.ANNOTATION
    if t in ("LINE", "LWPOLYLINE", "POLYLINE") and (
        re.search(opts.reference_linetypes, _linetype(doc, e), re.I) or re.search(opts.reference_layers, layer, re.I)
    ):
        return Role.REFERENCE
    if re.search(opts.annotation_layers, layer, re.I):
        return Role.ANNOTATION
    return Role.STRUCTURAL


def _xy(p) -> tuple[float, float]:
    return (float(p[0]), float(p[1]))


def entity_points(e) -> dict | None:
    """The positioning points of one entity, in a fixed order the writer replays."""
    t = e.dxftype()
    if t == "LINE":
        return {"pts": [_xy(e.dxf.start), _xy(e.dxf.end)], "vertex_pts": [0, 1], "segments": [(0, 1)]}
    if t == "LWPOLYLINE":
        raw = list(e.get_points("xyb"))
        pts = [(float(x), float(y)) for x, y, _ in raw]
        bulges = [float(b) for _, _, b in raw]
        return _poly(pts, bulges, bool(e.closed))
    if t == "POLYLINE":
        if e.is_3d_polyline or e.is_poly_face_mesh or e.is_polygon_mesh:
            return None
        pts = [_xy(v.dxf.location) for v in e.vertices]
        bulges = [float(v.dxf.get("bulge", 0.0)) for v in e.vertices]
        return _poly(pts, bulges, bool(e.is_closed))
    if t == "ARC":
        c = _xy(e.dxf.center)
        return {
            "pts": [c, _xy(e.start_point), _xy(e.end_point)],
            "vertex_pts": [1, 2],
            "segments": [],
            "radius": float(e.dxf.radius),
            "extra": {"start_angle": e.dxf.start_angle, "end_angle": e.dxf.end_angle},
        }
    if t == "CIRCLE":
        return {"pts": [_xy(e.dxf.center)], "vertex_pts": [0], "segments": [], "radius": float(e.dxf.radius)}
    if t == "ELLIPSE":
        return {"pts": [_xy(e.dxf.center)], "vertex_pts": [], "segments": []}
    if t == "TEXT":
        pts = [_xy(e.dxf.insert)]
        if e.dxf.hasattr("align_point"):
            pts.append(_xy(e.dxf.align_point))
        return {"pts": pts, "vertex_pts": [], "segments": [], "text": e.dxf.text, "text_height": float(e.dxf.height)}
    if t == "MTEXT":
        return {"pts": [_xy(e.dxf.insert)], "vertex_pts": [], "segments": [], "text": e.text, "text_height": float(e.dxf.char_height)}
    if t == "DIMENSION":
        pts = [_xy(e.dxf.get("defpoint", (0, 0))), _xy(e.dxf.get("defpoint2", (0, 0))), _xy(e.dxf.get("defpoint3", (0, 0))), _xy(e.dxf.get("text_midpoint", (0, 0)))]
        return {
            "pts": pts,
            "vertex_pts": [],
            "segments": [],
            "text": e.dxf.get("text", ""),
            "extra": {"dimtype": int(e.dxf.dimtype) & 7, "angle": float(e.dxf.get("angle", 0.0)), "measurement": float(e.dxf.get("actual_measurement", 0.0) or 0.0)},
        }
    if t == "LEADER":
        return {"pts": [_xy(v) for v in e.vertices], "vertex_pts": [], "segments": []}
    if t == "HATCH":
        # Points in path order (the writer replays this order); each path's outline is
        # also kept as a polygon — a hatch is the drawing saying "this region is material".
        pts: list[tuple[float, float]] = []
        polys: list[list[tuple[float, float]]] = []
        for path in e.paths:
            ring: list[tuple[float, float]] = []
            if hasattr(path, "vertices"):  # polyline path
                ring = [(float(v[0]), float(v[1])) for v in path.vertices]
                pts.extend(ring)
            else:
                for edge in path.edges:
                    name = type(edge).__name__
                    if name == "LineEdge":
                        pts.extend([_xy(edge.start), _xy(edge.end)])
                        ring.append(_xy(edge.start))
                    elif name in ("ArcEdge", "EllipseEdge"):
                        pts.append(_xy(edge.center))
                    elif name == "SplineEdge":
                        pts.extend(_xy(p) for p in edge.control_points)
            if len(ring) >= 3:
                polys.append(ring)
        if e.seeds:
            pts.extend(_xy(p) for p in e.seeds)
        return {"pts": pts, "vertex_pts": [], "segments": [], "extra": {"polys": polys}}
    if t in ("SOLID", "TRACE", "3DFACE"):
        return {"pts": [_xy(e.dxf.get(f"vtx{i}", (0, 0))) for i in range(4)], "vertex_pts": [], "segments": []}
    if t == "POINT":
        return {"pts": [_xy(e.dxf.location)], "vertex_pts": [], "segments": []}
    if t == "INSERT":
        return {"pts": [_xy(e.dxf.insert)], "vertex_pts": [], "segments": []}
    if t == "SPLINE":
        cps = e.control_points if len(e.control_points) else e.fit_points
        return {"pts": [_xy(p) for p in cps], "vertex_pts": [], "segments": []}
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


def read_dxf(path: str, opts: ReadOptions | None = None) -> tuple[Drawing, EzDoc]:
    opts = opts or ReadOptions()
    doc = ezdxf.readfile(path)
    units_mm = INSUNITS_MM.get(int(doc.header.get("$INSUNITS", 0) or 0), 1.0)
    msp = doc.modelspace()
    entities = list(msp)
    if opts.explode_inserts:
        # Exploding replaces each block reference by its entities in modelspace, so the
        # written result is exploded too (stated in the report).
        for e in entities:
            if e.dxftype() == "INSERT":
                try:
                    e.explode()
                except Exception as exc:  # a block ezdxf cannot explode stays a rigid symbol
                    print(f"warning: INSERT {e.dxf.handle} kept whole: {exc}")
        entities = list(msp)
    items: list[Item] = []
    unsupported: Counter[str] = Counter()
    for e in entities:
        info = entity_points(e)
        if info is None:
            unsupported[e.dxftype()] += 1
            continue
        items.append(
            Item(
                index=len(items),
                handle=e.dxf.handle,
                dxftype=e.dxftype(),
                layer=e.dxf.layer,
                role=_role(doc, e, opts),
                pts=info["pts"],
                closed=info.get("closed", False),
                bulges=info.get("bulges", []),
                radius=info.get("radius"),
                text=info.get("text"),
                text_height=info.get("text_height"),
                vertex_pts=info["vertex_pts"],
                segments=info["segments"],
                extra=info.get("extra", {}),
            )
        )
    xs = [p[0] for it in items if it.role == Role.STRUCTURAL for k in it.vertex_pts for p in [it.pts[k]]]
    ys = [p[1] for it in items if it.role == Role.STRUCTURAL for k in it.vertex_pts for p in [it.pts[k]]]
    extent = (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)
    return (
        Drawing(path=path, units_mm=units_mm, tol=opts.tol_mm / units_mm, items=items, extent=extent, unsupported=dict(unsupported)),
        doc,
    )
