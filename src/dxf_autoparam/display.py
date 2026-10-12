"""What the canvas draws: every entity, as polylines / filled polygons / texts, in world coordinates.

Drawn from the REGENERATED points, so the picture is always the model's: straight
geometry from its points, arcs and circles from centre and radius, hatches from their
regenerated boundaries, dimensions re-measured, and curves the prototype does not
reshape (ellipses, splines, dimension blocks) carried along with their anchor.
"""

from __future__ import annotations

import math
import re

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


def _dim_ends(it: Item, pts) -> tuple[tuple[float, float], tuple[float, float]]:
    """The two ends of a dimension's measuring line: the feet of its extension lines on the dimension line."""
    p1, p2, dl = pts[1], pts[2], pts[0]
    if it.extra.get("dimtype") != 0:
        return p1, p2
    ang = math.radians(it.extra.get("angle", 0.0))
    u = (math.cos(ang), math.sin(ang))
    def foot(p):
        t = (p[0] - dl[0]) * u[0] + (p[1] - dl[1]) * u[1]
        return (dl[0] + t * u[0], dl[1] + t * u[1])
    return foot(p1), foot(p2)


# MTEXT attachment 1..9 (top/middle/bottom × left/centre/right); TEXT halign 0 left, 1 centre, 2 right, 3 aligned,
# 4 middle, 5 fit, valign 0 baseline, 1 bottom, 2 middle, 3 top. The canvas places a text by the same anchor.
_HA = {0: "l", 1: "c", 2: "r", 3: "c", 4: "c", 5: "c"}
_VA = {0: "b", 1: "bt", 2: "m", 3: "t"}


def _text_anchor(it: Item, pts) -> tuple[tuple[float, float], str, str]:
    """Where a text is anchored and how it hangs from that point."""
    if it.dxftype == "MTEXT":
        k = min(max(it.extra.get("attach", 1), 1), 9) - 1
        return pts[0], "lcr"[k % 3], ("t", "m", "bt")[k // 3]
    ha, va = it.extra.get("halign", 0), it.extra.get("valign", 0)
    if (ha or va) and len(pts) > 1:
        if ha in (3, 5):   # aligned / fit: the text spans insert → align point, on its baseline
            return ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2), "c", "b"
        return pts[1], _HA.get(ha, "l"), "m" if ha == 4 else _VA.get(va, "b")
    return pts[0], "l", "b"


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
        at, ha, va = _text_anchor(it, pts)
        o = {"k": "t", "at": at, "text": text if text is not None else (it.text or ""), "h": it.text_height or 1.0,
             "rot": it.extra.get("rotation", 0.0), "mtext": t == "MTEXT", "ha": ha, "va": va}
        if abs(it.extra.get("wf", 1.0) - 1.0) > 1e-6:
            o["wf"] = it.extra["wf"]
        if t == "MTEXT" and abs(it.extra.get("spacing", 1.0) - 1.0) > 1e-6:
            o["ls"] = it.extra["spacing"]
        out.append(o)
    elif t == "POINT":
        x, y = pts[0]
        s = (it.text_height or 0) or 1.0
        out.append({"k": "p", "pts": [(x - s, y), (x + s, y)]})
    elif t == "DIMENSION":
        p1, p2 = pts[1], pts[2]
        moved_rigidly = all(abs((pts[i][0] - it.pts[i][0]) - (pts[0][0] - it.pts[0][0])) < 1e-6 and
                            abs((pts[i][1] - it.pts[i][1]) - (pts[0][1] - it.pts[0][1])) < 1e-6 for i in range(3))
        a, b = _dim_ends(it, pts)
        value = math.dist(a, b) * units_mm
        label = it.text if it.text and "<>" not in it.text and any(ch.isdigit() for ch in it.text) else f"{value:.0f}"
        old_mm = (it.extra.get("measurement") or 0.0) * units_mm
        if label == it.text and old_mm > 0:  # a written number that was the measured one follows the measurement
            for tok in re.findall(r"\d+(?:\.\d+)?", label):
                if abs(float(tok) - old_mm) <= max(0.5, 5e-4 * old_mm):
                    label = re.sub(rf"(?<![\d.]){re.escape(tok)}(?![\d.])", f"{value:.0f}", label, count=1)
                    break
        h = it.extra.get("dimtxt") or max(math.dist(a, b) * 0.08, 1e-9)   # its style's height, else a size its line can carry
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        rot = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        if rot > 90.5 or rot <= -89.5:   # a dimension's number reads from below or from the right
            rot = rot - 180 if rot > 0 else rot + 180
        drawn_mid = it.pts[3] if len(it.pts) > 3 and any(it.pts[3]) else None
        if drawn_mid is not None:   # the number keeps the place the draftsman gave it beside its line
            oa, ob = _dim_ends(it, it.pts)
            off = (drawn_mid[0] - (oa[0] + ob[0]) / 2, drawn_mid[1] - (oa[1] + ob[1]) / 2)
        else:   # above the line by the style's gap, as CAD places it
            r = math.radians(rot)
            k = it.extra.get("dimgap", h * 0.25) + h / 2
            off = (-math.sin(r) * k, math.cos(r) * k)
        at = (mid[0] + off[0], mid[1] + off[1])
        if moved_rigidly and it.display:  # unchanged in shape: its own drawn block
            dx, dy = pts[0][0] - it.pts[0][0], pts[0][1] - it.pts[0][1]
            for poly in it.display:
                out.append({"k": "p", "pts": [(x + dx, y + dy) for x, y in poly], "dim": True})
        else:
            for seg in ((p1, a), (p2, b), (a, b)):
                out.append({"k": "p", "pts": list(seg), "dim": True})
        out.append({"k": "t", "at": at, "text": label, "h": h, "rot": rot, "dim": True, "ha": "c", "va": "m"})
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
