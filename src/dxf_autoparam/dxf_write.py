"""Regenerated points → the ORIGINAL DXF, edited in place by entity handle.

Nothing is redrawn: every entity keeps its handle, layer, linetype, colour, style,
widths and bulges; only the coordinates the model computes (and the numbers in notes
that state a value) change. Entities the prototype does not position are left exactly
as they were. Dimensions are re-rendered so their text shows the new measurement.
"""

from __future__ import annotations

import ezdxf
from ezdxf.math import Vec3

from .ir import Model, Role
from .regen import Regenerated


def _v(p, z: float = 0.0) -> Vec3:
    return Vec3(p[0], p[1], z)


def write_dxf(model: Model, reg: Regenerated, out_path: str) -> dict:
    src = model.analysis.drawing.path
    doc = ezdxf.readfile(src)
    db = doc.entitydb
    report = {"updated": 0, "dimensions_rendered": 0, "dimension_render_failed": 0, "texts_changed": 0, "kept": 0}
    for it in model.analysis.drawing.items:
        if it.role == Role.FIXED or it.index not in reg.pts:
            report["kept"] += 1
            continue
        e = db.get(it.handle)
        if e is None:
            continue
        pts = reg.pts[it.index]
        t = it.dxftype
        if t == "LINE":
            e.dxf.start = _v(pts[0], e.dxf.start.z)
            e.dxf.end = _v(pts[1], e.dxf.end.z)
        elif t == "LWPOLYLINE":
            old = list(e.get_points("xyseb"))
            e.set_points([(p[0], p[1], o[2], o[3], o[4]) for p, o in zip(pts, old)], format="xyseb")
        elif t == "POLYLINE":
            for v, p in zip(e.vertices, pts):
                v.dxf.location = _v(p, v.dxf.location.z)
        elif t == "ARC":
            e.dxf.center = _v(pts[0], e.dxf.center.z)
            if it.index in reg.radius:
                e.dxf.radius = reg.radius[it.index]
        elif t == "CIRCLE":
            e.dxf.center = _v(pts[0], e.dxf.center.z)
            if it.index in reg.radius:
                e.dxf.radius = reg.radius[it.index]
        elif t == "ELLIPSE":
            e.dxf.center = _v(pts[0], e.dxf.center.z)
        elif t == "TEXT":
            e.dxf.insert = _v(pts[0])
            if len(pts) > 1 and e.dxf.hasattr("align_point"):
                e.dxf.align_point = _v(pts[1])
            if it.index in reg.texts and reg.texts[it.index] != it.text:
                e.dxf.text = reg.texts[it.index]
                report["texts_changed"] += 1
        elif t == "MTEXT":
            e.dxf.insert = _v(pts[0])
            if it.index in reg.texts and reg.texts[it.index] != it.text:
                e.text = reg.texts[it.index]
                report["texts_changed"] += 1
        elif t == "DIMENSION":
            for key, p in zip(("defpoint", "defpoint2", "defpoint3", "text_midpoint"), pts):
                if e.dxf.hasattr(key):
                    setattr(e.dxf, key, _v(p))
            try:
                e.override().render()
                report["dimensions_rendered"] += 1
            except Exception:  # an exotic dimension style ezdxf cannot render: defpoints are still right
                report["dimension_render_failed"] += 1
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
                            edge.control_points = [_v(p) for p in pts[k : k + n]]
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
            if len(e.control_points):
                e.control_points = [_v(p) for p in pts]
            else:
                e.fit_points = [_v(p) for p in pts]
        report["updated"] += 1
    doc.saveas(out_path)
    return report


def audit(path: str) -> dict:
    """Re-open a written file the strict way and report what an auditor finds."""
    doc = ezdxf.readfile(path)
    a = doc.audit()
    return {"errors": len(a.errors), "fixes": len(a.fixes), "entities": len(doc.modelspace())}
