"""What the canvas draws: every entity, as polylines / filled polygons / texts, in world coordinates.

Drawn from the REGENERATED points, so the picture is always the model's: straight
geometry from its points, arcs and circles from centre and radius, hatches from their
regenerated boundaries, dimensions re-measured, and curves the prototype does not
reshape (ellipses, splines, dimension blocks) carried along with their anchor.
"""

from __future__ import annotations

import math

from .ir import Item


def _bulge_arc(a, b, bulge, n=12):
    from ezdxf.math import Vec2, bulge_to_arc

    if math.dist(a, b) < 1e-12:
        return []
    c, a0, a1, r = bulge_to_arc(Vec2(a), Vec2(b), bulge)
    if a1 < a0:
        a1 += 2 * math.pi
    pts = [(c.x + r * math.cos(a0 + (a1 - a0) * k / n), c.y + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(1, n)]
    return pts if bulge > 0 else pts[::-1]


def _arc(c, r, a0, a1, n=48):
    a0, a1 = math.radians(a0), math.radians(a1)
    if a1 <= a0:
        a1 += 2 * math.pi
    steps = max(4, int(n * (a1 - a0) / (2 * math.pi)))
    return [(c[0] + r * math.cos(a0 + (a1 - a0) * k / steps), c[1] + r * math.sin(a0 + (a1 - a0) * k / steps)) for k in range(steps + 1)]


def primitives(it: Item, pts: list[tuple[float, float]], radius: float | None, text: str | None, units_mm: float) -> list[dict]:
    t = it.dxftype
    out: list[dict] = []
    if t in ("LINE", "LEADER"):
        out.append({"k": "p", "pts": pts})
    elif t in ("LWPOLYLINE", "POLYLINE"):
        if it.bulges and any(abs(b) > 1e-9 for b in it.bulges):
            seq = []
            n = len(pts)
            last = n if it.closed else n - 1
            for i in range(last):
                seq.append(pts[i])
                b = it.bulges[i] if i < len(it.bulges) else 0.0
                if abs(b) > 1e-9:
                    seq.extend(_bulge_arc(pts[i], pts[(i + 1) % n], b))
            if not it.closed:
                seq.append(pts[-1])
            out.append({"k": "p", "pts": seq, "closed": it.closed})
        else:
            out.append({"k": "p", "pts": pts, "closed": it.closed})
    elif t == "CIRCLE":
        out.append({"k": "p", "pts": _arc(pts[0], radius or it.radius or 0.0, 0, 360, 64), "closed": True})
    elif t == "ARC":
        out.append({"k": "p", "pts": _arc(pts[0], radius or it.radius or 0.0, it.extra.get("start_angle", 0), it.extra.get("end_angle", 0))})
    elif t in ("SOLID", "TRACE", "3DFACE"):
        out.append({"k": "g", "pts": [pts[0], pts[1], pts[3], pts[2]]})
    elif t == "HATCH":
        for ring in it.extra.get("rings", []):
            out.append({"k": "g", "pts": [pts[k] for k in ring], "pattern": it.extra.get("pattern", "")})
    elif t in ("TEXT", "MTEXT", "ATTRIB"):
        out.append({"k": "t", "at": pts[0], "text": text if text is not None else (it.text or ""), "h": it.text_height or 1.0,
                    "rot": it.extra.get("rotation", 0.0), "mtext": t == "MTEXT"})
    elif t == "POINT":
        x, y = pts[0]
        s = (it.text_height or 0) or 1.0
        out.append({"k": "p", "pts": [(x - s, y), (x + s, y)]})
    elif t == "DIMENSION":
        p1, p2, dl = pts[1], pts[2], pts[0]
        moved_rigidly = all(abs((pts[i][0] - it.pts[i][0]) - (pts[0][0] - it.pts[0][0])) < 1e-6 and
                            abs((pts[i][1] - it.pts[i][1]) - (pts[0][1] - it.pts[0][1])) < 1e-6 for i in range(3))
        if moved_rigidly and it.display:
            dx, dy = pts[0][0] - it.pts[0][0], pts[0][1] - it.pts[0][1]
            for poly in it.display:
                out.append({"k": "p", "pts": [(x + dx, y + dy) for x, y in poly], "dim": True})
        else:
            kind = it.extra.get("dimtype")
            ang = math.radians(it.extra.get("angle", 0.0))
            if kind == 0:
                u = (math.cos(ang), math.sin(ang))
                proj = lambda p: (p[0] - dl[0]) * u[0] + (p[1] - dl[1]) * u[1]
                a = (dl[0] + proj(p1) * u[0], dl[1] + proj(p1) * u[1])
                b = (dl[0] + proj(p2) * u[0], dl[1] + proj(p2) * u[1])
            else:
                a, b = p1, p2
            for seg in ((p1, a), (p2, b), (a, b)):
                out.append({"k": "p", "pts": list(seg), "dim": True})
            value = math.dist(a, b) * units_mm
            label = it.text if it.text and "<>" not in it.text and any(ch.isdigit() for ch in it.text) else f"{value:.0f}"
            out.append({"k": "t", "at": ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), "text": label, "h": None, "rot": math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])), "dim": True})
    elif it.display:  # ellipse, spline: carried with their anchor
        dx, dy = pts[0][0] - it.pts[0][0], pts[0][1] - it.pts[0][1]
        for poly in it.display:
            out.append({"k": "p", "pts": [(x + dx, y + dy) for x, y in poly]})
    for o in out:
        o["i"] = it.index
        o["role"] = it.role.value
        o["layer"] = it.layer
    return out


def scene(an, pts: dict[int, list], radius: dict[int, float], texts: dict[int, str]) -> list[dict]:
    dr = an.drawing
    out: list[dict] = []
    for it in dr.items:
        if it.dxftype == "INSERT":  # a symbol's insertion point draws nothing itself
            continue
        out.extend(primitives(it, pts.get(it.index, it.pts), radius.get(it.index), texts.get(it.index), dr.units_mm))
    return out
