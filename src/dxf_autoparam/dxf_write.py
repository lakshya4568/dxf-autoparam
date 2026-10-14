"""Regenerated points → the ORIGINAL DXF, edited in place.

  top-level entity            its coordinates are set (handle, layer, style, widths, bulges kept)
  symbol block (rigid)        its insertion point moves with what it marks
  view stored as a block      unchanged → untouched; moved as a whole → insertion point moves;
                              reshaped → the block reference is exploded into real entities
                              (same order the reader walked) and those are reshaped
  dimensions                  measured points moved, then re-rendered so the text shows the new value
  notes stating a value       the number is rewritten
  everything else             left exactly as it was
"""

from __future__ import annotations

import re
from collections import defaultdict

import ezdxf
import ezdxf.recover
import ezdxf.upright
from ezdxf.math import Vec3

from .ir import Item, Role
from .regen import Regenerated


def _v(p, z: float = 0.0) -> Vec3:
    return Vec3(p[0], p[1], z)


def _moved(a: list, b: list) -> bool:
    return any(abs(p[0] - q[0]) > 1e-9 or abs(p[1] - q[1]) > 1e-9 for p, q in zip(a, b))


def _render(e, it: Item, report: dict) -> bool:
    """Rebuild a dimension's block. A dimension style ezdxf cannot render is counted and named, not hidden."""
    try:
        e.override().render()
    except (ezdxf.DXFError, ValueError, KeyError, ArithmeticError) as exc:
        report["dimension_render_failed"] += 1
        report.setdefault("dimension_render_errors", []).append(f"{it.src}: {type(exc).__name__}: {exc}"[:160])
        return False
    return True


def _apply(e, it: Item, pts: list, reg: Regenerated, report: dict) -> None:
    ezdxf.upright.upright(e)  # as the reader saw it; ignores what it does not handle, raises only on broken data
    t = e.dxftype()
    if t == "LINE":
        e.dxf.start = _v(pts[0], e.dxf.start.z)
        e.dxf.end = _v(pts[1], e.dxf.end.z)
    elif t == "LWPOLYLINE":
        old = list(e.get_points("xyseb"))
        e.set_points([(p[0], p[1], o[2], o[3], o[4]) for p, o in zip(pts, old)], format="xyseb")
    elif t == "POLYLINE":
        for v, p in zip(e.vertices, pts):
            v.dxf.location = _v(p, v.dxf.location.z)
    elif t in ("ARC", "CIRCLE"):
        e.dxf.center = _v(pts[0], e.dxf.center.z)
        if it.index in reg.radius:
            e.dxf.radius = reg.radius[it.index]
    elif t in ("ELLIPSE",):
        e.dxf.center = _v(pts[0], e.dxf.center.z)
    elif t in ("TEXT", "ATTRIB"):
        e.dxf.insert = _v(pts[0])
        if len(pts) > 1 and e.dxf.hasattr("align_point"):
            e.dxf.align_point = _v(pts[1])
        new = reg.texts.get(it.index)
        if new is not None and new != it.text:
            e.dxf.text = new
            report["texts_changed"] += 1
    elif t == "MTEXT":
        e.dxf.insert = _v(pts[0])
        new = reg.texts.get(it.index)
        if new is not None and new != it.text:
            e.text = new
            report["texts_changed"] += 1
    elif t == "DIMENSION":
        for key, p in zip(("defpoint", "defpoint2", "defpoint3", "text_midpoint"), pts):
            if e.dxf.hasattr(key):
                setattr(e.dxf, key, _v(p))
        if _render(e, it, report):
            # A text override that writes the measured number ("CLEAR SPAN 3000") follows the new measurement.
            text = e.dxf.get("text", "")
            u_mm = (report.get("_item_units_mm") or {}).get(it.index, report.get("_units_mm", 1.0))
            old_mm = (it.extra.get("measurement") or 0.0) * u_mm
            if text and text != "<>" and old_mm > 0:
                new_mm = float(e.get_measurement()) * u_mm
                tokens = re.findall(r"\d+(?:\.\d+)?", text)
                for tok in tokens:
                    v = float(tok)
                    for scale, dec in ((1.0, 0), (0.001, 3), (0.001, 2)):
                        if abs(v - old_mm * scale) <= (0.5 if scale == 1.0 else 0.0005):
                            new = f"{new_mm * scale:.{dec}f}" if dec else f"{round(new_mm)}"
                            text = re.sub(rf"(?<![\d.]){re.escape(tok)}(?![\d.])", new, text, count=1)
                            break
                if text != e.dxf.get("text", ""):
                    e.dxf.text = text
                    _render(e, it, report)
                    report["texts_changed"] += 1
            report["dimensions_rendered"] += 1
    elif t == "LEADER":
        e.vertices = [_v(p) for p in pts]
    elif t == "HATCH":
        k = 0
        for path in e.paths:
            if hasattr(path, "vertices"):
                new = []
                for v in path.vertices:
                    x, y = pts[k]
                    new.append((x, y, *v[2:]) if len(v) > 2 else (x, y))
                    k += 1
                path.vertices = new
            else:
                for edge in path.edges:
                    name = type(edge).__name__
                    if name == "LineEdge":
                        edge.start, edge.end = pts[k], pts[k + 1]
                        k += 2
                    elif name in ("ArcEdge", "EllipseEdge"):
                        edge.center = pts[k]
                        k += 1
                    elif name == "SplineEdge":
                        n = len(edge.control_points)
                        edge.control_points = [_v(p) for p in pts[k: k + n]]
                        k += n
        if e.seeds:
            e.set_seed_points([pts[k + i] for i in range(len(e.seeds))])
    elif t in ("SOLID", "TRACE", "3DFACE"):
        for i, p in enumerate(pts[:4]):
            setattr(e.dxf, f"vtx{i}", _v(p))
    elif t == "POINT":
        e.dxf.location = _v(pts[0])
    elif t == "INSERT":
        e.dxf.insert = _v(pts[0], e.dxf.insert.z)
    elif t == "SPLINE":
        dx, dy = pts[0][0] - it.pts[0][0], pts[0][1] - it.pts[0][1]
        if len(e.control_points):
            e.control_points = [Vec3(p[0] + dx, p[1] + dy, p[2]) for p in e.control_points]
        if len(e.fit_points):
            e.fit_points = [Vec3(p[0] + dx, p[1] + dy, p[2]) for p in e.fit_points]
    report["updated"] += 1


def write_dxf(model, reg: Regenerated, out_path: str) -> dict:
    """Write the regenerated drawing. `model` is anything with `.analysis` (baseline Model or Program)."""
    dr = model.analysis.drawing
    try:
        doc, _ = ezdxf.recover.readfile(dr.path)
    except ezdxf.DXFStructureError:
        doc = ezdxf.readfile(dr.path)
    db = doc.entitydb
    report = {"updated": 0, "dimensions_rendered": 0, "dimension_render_failed": 0, "texts_changed": 0, "kept": 0,
              "blocks_exploded": 0, "blocks_moved": 0, "symbols_moved": 0, "_units_mm": dr.units_mm,
              "_item_units_mm": getattr(model, "item_units_mm", None) or {}}
    by_top: dict[str, list[Item]] = defaultdict(list)
    for it in dr.items:
        by_top[it.handle].append(it)
    by_src = {it.src: it for it in dr.items}

    for top, items in by_top.items():
        e = db.get(top)
        if e is None:
            continue
        if all(it.role == Role.FIXED or (it.index not in reg.pts and it.index not in reg.texts and it.index not in reg.radius) for it in items):
            report["kept"] += len(items)
            continue
        if e.dxftype() != "INSERT":
            for it in items:
                if (it.index in reg.pts or it.index in reg.texts or it.index in reg.radius) and it.role != Role.FIXED:
                    _apply(e, it, reg.pts.get(it.index, it.pts), reg, report)
            continue
        # a block reference
        anchor = by_src.get(top)
        if anchor is not None and anchor.dxftype == "INSERT":  # rigid symbol
            if _moved(reg.pts.get(anchor.index, anchor.pts), anchor.pts):
                e.dxf.insert = _v(reg.pts[anchor.index][0], e.dxf.insert.z)
                report["symbols_moved"] += 1
            continue
        content = [it for it in items if (it.index in reg.pts or it.index in reg.texts or it.index in reg.radius) and it.role != Role.FIXED]
        reshaped_in_place = any(
            (it.index in reg.texts and reg.texts[it.index] != it.text)
            or (it.index in reg.radius and abs(reg.radius[it.index] - (it.radius or 0.0)) > 1e-9)
            for it in content
        )
        if not any(_moved(reg.pts.get(it.index, it.pts), it.pts) for it in content) and not reshaped_in_place:
            report["kept"] += len(items)
            continue
        shifts = {(round(reg.pts.get(it.index, it.pts)[k][0] - p[0], 9), round(reg.pts.get(it.index, it.pts)[k][1] - p[1], 9))
                  for it in content for k, p in enumerate(it.pts)}
        if len(shifts) == 1 and not reshaped_in_place:  # the whole view moved as one piece
            dx, dy = next(iter(shifts))
            ins = e.dxf.insert
            e.dxf.insert = Vec3(ins.x + dx, ins.y + dy, ins.z)
            report["blocks_moved"] += 1
            continue
        if e.mcount > 1:  # an array of a block: reshaping one copy would reshape all
            report["arrays_not_reshaped"] = report.get("arrays_not_reshaped", 0) + 1
            continue
        _explode(e, top, by_src, reg, report)
        report["blocks_exploded"] += 1
    doc.saveas(out_path)
    report.pop("_units_mm", None)
    report.pop("_item_units_mm", None)
    return report


def _explode(ins, prefix: str, by_src: dict[str, Item], reg: Regenerated, report: dict) -> None:
    """Explode a reshaped view block (depth-first, the reader's order) and reshape what it held."""
    attribs = len(getattr(ins, "attribs", []))
    exploded = list(ins.explode())
    body = exploded[: len(exploded) - attribs] if attribs else exploded
    for k, e in enumerate(body):
        sub = f"{prefix}/{k}"
        if e.dxftype() == "INSERT":
            anchor = by_src.get(sub)
            if anchor is not None and anchor.dxftype == "INSERT":
                if anchor.index in reg.pts:
                    e.dxf.insert = _v(reg.pts[anchor.index][0], e.dxf.insert.z)
                    report["symbols_moved"] += 1
                continue
            _explode(e, sub, by_src, reg, report)
            continue
        it = by_src.get(sub)
        if it is not None and (it.index in reg.pts or it.index in reg.texts or it.index in reg.radius) and it.role != Role.FIXED:
            _apply(e, it, reg.pts.get(it.index, it.pts), reg, report)


def audit(path: str) -> dict:
    """Re-open a written file the strict way and report what an auditor finds."""
    doc = ezdxf.readfile(path)
    a = doc.audit()
    return {"errors": len(a.errors), "fixes": len(a.fixes), "entities": len(doc.modelspace())}

