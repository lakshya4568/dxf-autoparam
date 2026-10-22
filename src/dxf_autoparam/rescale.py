"""Change the scale a view is DRAWN at — never the size of what it shows.

A view at 1:25 redrawn at 1:50 is half as large on the sheet; the structure in it is the same structure. So, for every entity of that view only:

  geometry     every point moves toward the view's own origin (frames.py) by k = old ratio / new ratio; radii and axes scale by k; bulges and
               angles stay (a uniform scale keeps them)
  dimensions   their measured points move like geometry, and their linear factor (DIMLFAC) is divided by k — every number a dimension shows
               stays the real size; a number written into its text override stays as written (it was the real size already)
  annotation   text heights, arrow and tick sizes, hatch pattern scales and symbol blocks (a level mark, an arrow) are PAPER sizes: they stay as
               they are and only move with the point they are placed at — a label stays readable, a pattern keeps its density on paper
  the title    a text of the view that states the old ratio ("SCALE 1:25") is rewritten with the new one

Nothing outside the view changes. A unit read again from the rescaled sheet reads its own scale from its own dimensions (sheet._units) and the same
millimetres: the parametric values are real sizes and do not change. Entities of a kind this does not rescale are counted and named, never moved."""

from __future__ import annotations

import math
import re

import ezdxf
from ezdxf.math import Matrix44, Vec3

GEOMETRY = ("LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "SPLINE", "POINT", "SOLID", "TRACE", "3DFACE")
RATIO = re.compile(r"1\s*:\s*(\d+(?:\.\d+)?)")


def _about(origin: tuple[float, float], k: float) -> Matrix44:
    ox, oy = origin
    return Matrix44.translate(-ox, -oy, 0) @ Matrix44.scale(k, k, 1) @ Matrix44.translate(ox, oy, 0)


def _pt(p, origin, k) -> Vec3:
    v = Vec3(p)
    return Vec3(origin[0] + (v.x - origin[0]) * k, origin[1] + (v.y - origin[1]) * k, v.z)


def _block_size(doc, name: str) -> float:
    xs, ys = [], []
    blk = doc.blocks.get(name)
    for e in blk or []:
        for attr in ("start", "end", "center", "insert", "location"):
            if e.dxf.hasattr(attr):
                v = Vec3(e.dxf.get(attr))
                xs.append(v.x)
                ys.append(v.y)
        if e.dxftype() == "LWPOLYLINE":
            for x, y, *_rest in e.get_points("xy"):
                xs.append(x)
                ys.append(y)
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys)) if xs else 0.0


def rescale(src: str, out: str, handles: set[str], origin: tuple[float, float], k: float, view_diagonal: float,
            old_ratio: float | None = None, new_ratio: float | None = None) -> dict:
    """Rescale the entities whose top-level handle is in `handles` about `origin` by `k`, write `out`. Returns what was done, by kind."""
    if not (k > 0 and math.isfinite(k)):
        raise ValueError(f"a scale factor must be positive: {k}")
    doc = ezdxf.readfile(src)
    m = _about(origin, k)
    rep: dict = {"factor": k, "origin": list(origin), "geometry": 0, "dimensions": 0, "texts": 0, "hatches": 0, "symbols": 0, "blocks_scaled": 0,
                 "leaders": 0, "titles": [], "not_rescaled": []}
    for e in doc.modelspace():
        if e.dxf.handle not in handles:
            continue
        t = e.dxftype()
        if t in GEOMETRY:
            e.transform(m)
            rep["geometry"] += 1
        elif t == "HATCH":
            scale = float(e.dxf.get("pattern_scale", 1.0)) if e.has_pattern_fill else None
            e.transform(m)
            if scale is not None:
                e.set_pattern_scale(scale)  # a pattern's spacing is a paper size: the same density after the view shrinks
            rep["hatches"] += 1
        elif t in ("TEXT", "ATTRIB"):
            for attr in ("insert", "align_point"):
                if e.dxf.hasattr(attr):
                    e.dxf.set(attr, _pt(e.dxf.get(attr), origin, k))
            rep["texts"] += 1
            if old_ratio and new_ratio:
                rep["titles"] += _retitle(e, "text", old_ratio, new_ratio)
        elif t == "MTEXT":
            e.dxf.insert = _pt(e.dxf.insert, origin, k)
            rep["texts"] += 1
            if old_ratio and new_ratio:
                rep["titles"] += _retitle(e, "text", old_ratio, new_ratio)
        elif t == "DIMENSION":
            for attr in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5", "text_midpoint"):
                if e.dxf.hasattr(attr):
                    e.dxf.set(attr, _pt(e.dxf.get(attr), origin, k))
            ov = e.override()
            lfac = float(ov.get("dimlfac", 1.0) or 1.0)
            ov["dimlfac"] = lfac / k  # the measured length shrinks by k: the number it shows (length × dimlfac) does not
            ov.commit()
            try:
                e.override().render()
            except (ezdxf.DXFError, ValueError, KeyError, ArithmeticError) as exc:
                rep["not_rescaled"].append(f"DIMENSION {e.dxf.handle}: render failed ({type(exc).__name__})")
                continue
            rep["dimensions"] += 1
        elif t == "INSERT":
            e.dxf.insert = _pt(e.dxf.insert, origin, k)
            size = _block_size(doc, e.dxf.name) * max(abs(e.dxf.get("xscale", 1.0)), abs(e.dxf.get("yscale", 1.0)))
            if size >= 0.05 * view_diagonal:  # drawn geometry kept in a block: it is the structure, it scales
                e.dxf.xscale = e.dxf.get("xscale", 1.0) * k
                e.dxf.yscale = e.dxf.get("yscale", 1.0) * k
                rep["blocks_scaled"] += 1
            else:  # a symbol — a level mark, an arrow, a north point: a paper size, it only moves
                rep["symbols"] += 1
        elif t == "LEADER":
            e.vertices = [_pt(v, origin, k) for v in e.vertices]
            rep["leaders"] += 1
        else:
            rep["not_rescaled"].append(f"{t} {e.dxf.handle}")
    doc.saveas(out)
    return rep


def _retitle(e, attr: str, old: float, new: float) -> list[str]:
    text = e.dxf.get(attr, "") if e.dxftype() != "MTEXT" else e.text
    hit = [mm for mm in RATIO.finditer(text or "") if abs(float(mm.group(1)) - old) < 1e-9]
    if not hit:
        return []
    new_text = RATIO.sub(lambda mm: f"1:{new:g}" if abs(float(mm.group(1)) - old) < 1e-9 else mm.group(0), text)
    if e.dxftype() == "MTEXT":
        e.text = new_text
    else:
        e.dxf.set(attr, new_text)
    return [f"{text.strip()} → {new_text.strip()}"]


def rescale_view(sm, view: str, new_ratio: float, out: str, old_ratio: float | None = None) -> dict:
    """Redraw one view of a sheet at another drafting ratio (1:new_ratio). The old ratio is the one the view's own title states, unless given."""
    from .frames import view_frame

    g = sm.layout.group(view)
    items = [sm.dr.items[i] for i in g.items]
    if old_ratio is None:
        stated = [float(mm.group(1)) for it in items if it.text for mm in RATIO.finditer(it.text)]
        if len(set(stated)) != 1:
            raise ValueError(f"{view} states {len(set(stated))} drafting ratios ({sorted(set(stated))}): say which one it is drawn at (old_ratio)")
        old_ratio = stated[0]
    if not (float(new_ratio) > 0 and math.isfinite(float(new_ratio))):
        raise ValueError(f"a drafting ratio is 1:n with n > 0, not 1:{new_ratio}")
    k = old_ratio / float(new_ratio)
    handles = {(it.src or it.handle).split("/")[0] for it in items}
    x0, y0, x1, y1 = g.bbox
    rep = rescale(sm.path, out, handles, view_frame(sm, view).origin, k, math.hypot(x1 - x0, y1 - y0), old_ratio, float(new_ratio))
    rep.update(view=view, old_ratio=old_ratio, new_ratio=float(new_ratio))
    return rep
