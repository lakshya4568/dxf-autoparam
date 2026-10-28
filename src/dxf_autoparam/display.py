"""What the canvas draws: every entity, as polylines / filled polygons / texts, in world coordinates.

Drawn from the REGENERATED points, so the picture is always the model's: straight
geometry from its points, arcs and circles from centre and radius, hatches from their
regenerated boundaries, dimensions re-measured, and curves the prototype does not
reshape (ellipses, splines, dimension blocks) carried along with their anchor.

Each primitive also carries the entity's resolved CAD style (`s`: colour, ACI-7 foreground flag, dash pattern in
drawing units, lineweight in mm, alpha, font — fidelity.Styler) and compound annotations are drawn from the PARTS CAD
draws them with: a dimension's extension and dimension lines, arrowheads and the text of its block; a leader's arrowhead;
a multileader's lines, arrows and content; a hatch's pattern lines. When a dimension or leader is reshaped, every part
follows the control point it belongs to (an arrowhead its tip, an extension line its two ends, the text the middle), so
nothing is redrawn in a different style. Kinds: "p" polyline, "g" filled polygon (`mask`: a wipeout, `fill`: a hatch's
boundary), "m" many straight segments (flat x0 y0 x1 y1 …: hatch pattern lines), "t" text.
"""

from __future__ import annotations

import math
import re

from .fidelity import pattern_segments, rigid, transform_part, wide_polygons
from .ir import Item


class CurveMap:
    """x' = sx·x + kx·y + tx, y' = ky·x + sy·y + ty — how a curve follows its two ends (curve_map)."""

    def __init__(self, sx: float = 1.0, kx: float = 0.0, tx: float = 0.0, ky: float = 0.0, sy: float = 1.0, ty: float = 0.0):
        self.sx, self.kx, self.tx, self.ky, self.sy, self.ty = sx, kx, tx, ky, sy, ty

    def apply(self, p) -> tuple[float, float]:
        return (self.sx * p[0] + self.kx * p[1] + self.tx, self.ky * p[0] + self.sy * p[1] + self.ty)

    def matrix(self):
        from ezdxf.math import Matrix44

        return Matrix44([self.sx, self.ky, 0, 0, self.kx, self.sy, 0, 0, 0, 0, 1, 0, self.tx, self.ty, 0, 1])  # row vectors (ezdxf)

    def is_identity(self) -> bool:
        return (self.sx, self.kx, self.tx, self.ky, self.sy, self.ty) == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)

    def mirrors(self) -> bool:
        return self.sx * self.sy - self.kx * self.ky < 0


def curve_map(old: list, new: list, turn: float = 0.0) -> CurveMap:
    """How a curve (ellipse arc, spline) set out from its two ends follows them. Each axis is scaled between where its ends
    were and where they are — an affine map, so an ellipse stays an ellipse and a spline its own curve, and a wall drawn
    from a box's face to its end line stays on both; on an axis where the ends coincide (a closed curve) it moves with
    its first end. A part turned by a component transform (`turn`, degrees) turns the curve with it about its first end."""
    if not old or not new:
        return CurveMap()
    (a0x, a0y), (b0x, b0y) = old[0], new[0]
    if turn:
        c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
        return CurveMap(c, -s, b0x - c * a0x + s * a0y, s, c, b0y - s * a0x - c * a0y)
    (a1x, a1y), (b1x, b1y) = old[-1], new[-1]

    def axis(a0: float, a1: float, b0: float, b1: float) -> tuple[float, float]:
        if abs(a1 - a0) <= 1e-9 * max(1.0, abs(a0), abs(a1)):
            return 1.0, b0 - a0
        k = (b1 - b0) / (a1 - a0)
        return k, b0 - a0 * k

    sx, tx = axis(a0x, a1x, b0x, b1x)
    sy, ty = axis(a0y, a1y, b0y, b1y)
    return CurveMap(sx, 0.0, tx, 0.0, sy, ty)


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


def _moved_rigidly(it: Item, pts) -> tuple[bool, float, float]:
    """Whether every point moved by one offset (and by how much)."""
    if not it.pts or len(pts) != len(it.pts):
        return False, 0.0, 0.0
    dx, dy = pts[0][0] - it.pts[0][0], pts[0][1] - it.pts[0][1]
    ok = all(abs((p[0] - q[0]) - dx) < 1e-6 and abs((p[1] - q[1]) - dy) < 1e-6 for p, q in zip(pts, it.pts, strict=False))
    return ok, dx, dy


def _nearest(old: list, p) -> int:
    return min(range(len(old)), key=lambda j: (old[j][0] - p[0]) ** 2 + (old[j][1] - p[1]) ** 2)


def _by_nearest(old: list, new: list):
    def fn(p):
        j = _nearest(old, p)
        return (p[0] + new[j][0] - old[j][0], p[1] + new[j][1] - old[j][1])

    return fn


def _follow(parts: list[dict], old: list, new: list, turn: float = 0.0, rotate_tags: tuple[str, ...] = ("arrow", "text")) -> list[dict]:
    """Parts of a reshaped compound, each point moved with the control point it was drawn nearest to (an arrowhead with
    its tip — turned with the line it ends —, an extension line's foot with what it measures, the text with the middle)."""
    out = []
    stretch = _by_nearest(old, new)
    for q in parts:
        if q.get("tag") in rotate_tags:  # moves as one piece with its control point
            ref = q["at"] if q["k"] == "t" else (sum(p[0] for p in q["pts"]) / len(q["pts"]), sum(p[1] for p in q["pts"]) / len(q["pts"]))
            j = _nearest(old, ref)
            r = transform_part(q, rigid(new[j][0] - old[j][0], new[j][1] - old[j][1], turn, old[j]))
            if q["k"] == "t" and turn:
                r["rot"] = q.get("rot", 0.0) + math.degrees(turn)
        else:
            r = transform_part(q, stretch)
        out.append(r)
    return out


def _label(it: Item, a, b, units_mm: float) -> str:
    """A reshaped dimension's text: the new measurement, or its written override with the old measured number replaced."""
    value = math.dist(a, b) * units_mm
    label = it.text if it.text and "<>" not in it.text and any(ch.isdigit() for ch in it.text) else f"{value:.0f}"
    old_mm = (it.extra.get("measurement") or 0.0) * units_mm
    if label == it.text and old_mm > 0:  # a written number that was the measured one follows the measurement
        for tok in re.findall(r"\d+(?:\.\d+)?", label):
            if abs(float(tok) - old_mm) <= max(0.5, 5e-4 * old_mm):
                label = re.sub(rf"(?<![\d.]){re.escape(tok)}(?![\d.])", f"{value:.0f}", label, count=1)
                break
    return label


def _dimension(it: Item, pts, units_mm: float, style: dict | None) -> list[dict]:
    out: list[dict] = []
    parts = it.extra.get("parts") or []
    rigid_, dx, dy = _moved_rigidly(it, pts)
    if parts and rigid_:  # unchanged in shape: the parts of its own block, as drawn
        fn = rigid(dx, dy)
        return [{**transform_part(q, fn), "dim": True} for q in parts]
    p1, p2 = pts[1], pts[2]
    a, b = _dim_ends(it, pts)
    oa, ob = _dim_ends(it, it.pts)
    label = _label(it, a, b, units_mm)
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    omid = ((oa[0] + ob[0]) / 2, (oa[1] + ob[1]) / 2)
    turn = math.atan2(b[1] - a[1], b[0] - a[0]) - math.atan2(ob[1] - oa[1], ob[0] - oa[0]) if math.dist(a, b) > 1e-12 and math.dist(oa, ob) > 1e-12 else 0.0
    if parts:
        texts = [q for q in parts if q["k"] == "t"]
        tpos = texts[0]["at"] if texts else omid
        off = (tpos[0] - omid[0], tpos[1] - omid[1])
        c, s_ = math.cos(turn), math.sin(turn)
        ntext = (mid[0] + c * off[0] - s_ * off[1], mid[1] + s_ * off[0] + c * off[1])
        if it.extra.get("dimtype") in (0, 1):
            old, new = [it.pts[1], it.pts[2], oa, ob, tpos], [p1, p2, a, b, ntext]
        else:
            old, new = [*it.pts[:4], tpos], [*pts[:4], ntext]
        for q in _follow(parts, old, new, turn):
            q["dim"] = True
            if q["k"] == "t":
                q["text"] = label
            out.append(q)
        return out
    # no block to draw from (written by a tool that renders none): drawn from its points, in its style
    h = it.extra.get("dimtxt") or max(math.dist(a, b) * 0.08, 1e-9)   # its style's height, else a size its line can carry
    rot = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    if rot > 90.5 or rot <= -89.5:   # a dimension's number reads from below or from the right
        rot = rot - 180 if rot > 0 else rot + 180
    drawn_mid = it.pts[3] if len(it.pts) > 3 and any(it.pts[3]) else None
    if drawn_mid is not None:   # the number keeps the place the draftsman gave it beside its line
        off = (drawn_mid[0] - omid[0], drawn_mid[1] - omid[1])
    else:   # above the line by the style's gap, as CAD places it
        r = math.radians(rot)
        k = it.extra.get("dimgap", h * 0.25) + h / 2
        off = (-math.sin(r) * k, math.cos(r) * k)
    at = (mid[0] + off[0], mid[1] + off[1])
    for seg in ((p1, a), (p2, b), (a, b)):
        out.append({"k": "p", "pts": list(seg), "dim": True})
    out.append({"k": "t", "at": at, "text": label, "h": h, "rot": rot, "dim": True, "ha": "c", "va": "m"})
    return out


def _leader(it: Item, pts) -> list[dict]:
    """The leader line through its (regenerated) vertices, and its arrowhead carried on its tip — turned with the first segment."""
    out: list[dict] = [{"k": "p", "pts": list(pts)}]
    parts = [q for q in it.extra.get("parts") or [] if q["k"] == "g" or q.get("tag") == "arrow"]
    if not parts or not pts:
        return out
    turn = 0.0
    if len(pts) > 1 and len(it.pts) > 1 and math.dist(pts[0], pts[1]) > 1e-12 and math.dist(it.pts[0], it.pts[1]) > 1e-12:
        turn = math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0]) - math.atan2(it.pts[1][1] - it.pts[0][1], it.pts[1][0] - it.pts[0][0])
    fn = rigid(pts[0][0] - it.pts[0][0], pts[0][1] - it.pts[0][1], turn, it.pts[0])
    out.extend(transform_part(q, fn) for q in parts)
    return out


def _hatch(it: Item, pts) -> list[dict]:
    h = it.extra.get("hatch") or {}
    name = it.extra.get("pattern", "") or h.get("name", "")
    fill = h.get("fill") or ("solid" if name.upper() == "SOLID" else "pattern")
    rings = [[pts[k] for k in ring] for ring in it.extra.get("rings", []) if all(k < len(pts) for k in ring)]
    out: list[dict] = [{"k": "g", "pts": r, "pattern": name, "fill": fill} for r in rings]
    if fill != "pattern" or not h or h.get("too_dense"):
        return out
    rigid_, dx, dy = _moved_rigidly(it, pts)
    if rigid_:
        segs = [[x0 + dx, y0 + dy, x1 + dx, y1 + dy] for x0, y0, x1, y1 in h.get("segments", [])]
    else:  # a new boundary: hatched again from the pattern's own base lines
        segs, dense = pattern_segments(h.get("baselines", []), rings)
        if dense:
            return out
    if segs:
        out.append({"k": "m", "segs": segs, "tag": "hatch"})
    return out


def _bands(it: Item, pts) -> list[dict]:
    """A polyline with width: the band CAD fills (recomputed from the regenerated vertices)."""
    rigid_, dx, dy = _moved_rigidly(it, pts)
    if rigid_:
        return [{"k": "g", "pts": [(x + dx, y + dy) for x, y in band], "tag": "band"} for band in it.extra.get("bands", [])]
    widths = it.extra.get("widths")
    if it.dxftype != "LWPOLYLINE" or not widths or len(widths) != len(pts):
        return [{"k": "g", "pts": [(x + dx, y + dy) for x, y in band], "tag": "band"} for band in it.extra.get("bands", [])]
    from ezdxf.entities import LWPolyline

    e = LWPolyline.new(dxfattribs={"const_width": it.extra.get("const_width", 0.0)})
    bulges = it.bulges or [0.0] * len(pts)
    e.set_points([(p[0], p[1], w[0], w[1], b) for p, w, b in zip(pts, widths, bulges, strict=False)], format="xyseb")
    e.closed = it.closed
    return [{"k": "g", "pts": band, "tag": "band"} for band in wide_polygons(e) if len(band) >= 3]


def _text_prim(it: Item, pts, text: str | None) -> dict:
    at, ha, va = _text_anchor(it, pts)
    o = {"k": "t", "at": at, "text": text if text is not None else (it.text or ""), "h": it.text_height or 1.0,
         "rot": it.extra.get("rotation", 0.0), "mtext": it.dxftype == "MTEXT", "ha": ha, "va": va}
    if abs(it.extra.get("wf", 1.0) - 1.0) > 1e-6:
        o["wf"] = it.extra["wf"]
    if it.dxftype == "MTEXT" and abs(it.extra.get("spacing", 1.0) - 1.0) > 1e-6:
        o["ls"] = it.extra["spacing"]
    if it.extra.get("width"):
        o["width"] = it.extra["width"]
    if it.extra.get("oblique"):
        o["oblique"] = it.extra["oblique"]
    return o


def _arc_angles(it: Item, pts, radius) -> tuple[float, float]:
    """An arc's start / end angles: as drawn, or — when its end points were carried round (a turned part) — read from them."""
    a0, a1 = it.extra.get("start_angle", 0.0), it.extra.get("end_angle", 0.0)
    if len(pts) >= 3 and len(it.pts) >= 3 and (pts[1] != it.pts[1] or pts[2] != it.pts[2]):
        c, r = pts[0], radius or it.radius or 0.0
        if r > 0 and abs(math.dist(c, pts[1]) - r) <= 1e-6 * max(1.0, r) and abs(math.dist(c, pts[2]) - r) <= 1e-6 * max(1.0, r):
            return math.degrees(math.atan2(pts[1][1] - c[1], pts[1][0] - c[0])), math.degrees(math.atan2(pts[2][1] - c[1], pts[2][0] - c[0]))
    return a0, a1


def primitives(it: Item, pts: list[tuple[float, float]], radius: float | None, text: str | None, units_mm: float, turn: float = 0.0) -> list[dict]:
    """`turn`: degrees the entity was turned by a component transform (its texts read along the turned part)."""
    t = it.dxftype
    style = it.extra.get("style")
    out: list[dict] = []
    if t == "LINE":
        out.append({"k": "p", "pts": pts})
    elif t == "LEADER":
        out.extend(_leader(it, pts))
    elif t in ("LWPOLYLINE", "POLYLINE"):
        if it.extra.get("bands"):
            out.extend(_bands(it, pts))
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
        a0, a1 = _arc_angles(it, pts, radius)
        out.append({"k": "p", "pts": _arc(pts[0], radius or it.radius or 0.0, a0, a1)})
    elif t in ("SOLID", "TRACE"):
        out.append({"k": "g", "pts": [pts[0], pts[1], pts[3], pts[2]]})
    elif t == "3DFACE":   # a face is drawn as its edges (CAD does not fill it)
        out.append({"k": "p", "pts": [pts[0], pts[1], pts[2], pts[3]], "closed": True})
    elif t == "HATCH":
        out.extend(_hatch(it, pts))
    elif t in ("TEXT", "MTEXT", "ATTRIB"):
        out.append(_text_prim(it, pts, text))
    elif t == "POINT":
        x, y = pts[0]
        s = (it.text_height or 0) or 1.0
        out.append({"k": "p", "pts": [(x - s, y), (x + s, y)]})
    elif t == "DIMENSION":
        out.extend(_dimension(it, pts, units_mm, style))
    elif it.extra.get("infinite"):   # XLINE / RAY: drawn across the sheet, kept as drawn
        (x, y), (ux, uy) = pts[0], it.extra.get("dir", (1.0, 0.0))
        reach = it.extra.get("reach", 1e6)
        a = (x - ux * reach, y - uy * reach) if it.extra["infinite"] == "xline" else (x, y)
        out.append({"k": "p", "pts": [a, (x + ux * reach, y + uy * reach)]})
    elif it.extra.get("frame"):   # WIPEOUT masks what lies under it; an image / underlay shows where it sits
        if it.extra["frame"] == "wipeout":
            out.append({"k": "g", "pts": list(pts), "mask": True})
        else:
            out.append({"k": "p", "pts": list(pts), "closed": True})
            out.append({"k": "t", "at": pts[0], "text": it.extra["frame"].upper() + " (not rendered)", "h": max(math.dist(pts[0], pts[1]) * 0.04, 1e-9) if len(pts) > 1 else 1.0,
                        "rot": 0.0, "ha": "l", "va": "b"})
    elif it.extra.get("parts"):   # a multileader, a table …: its parts, each following the point it hangs from
        rigid_, dx, dy = _moved_rigidly(it, pts)
        parts = it.extra["parts"]
        out.extend([transform_part(q, rigid(dx, dy)) for q in parts] if rigid_ else _follow(parts, it.pts, pts))
    elif it.display:  # ellipse, spline: redrawn between their two ends
        m = curve_map(it.pts, pts, turn)
        for poly in it.display:
            out.append({"k": "p", "pts": [m.apply(p) for p in poly]})
    for o in out:
        o["i"] = it.index
        o["role"] = it.role.value
        o["layer"] = it.layer
        if "s" not in o and style is not None:
            o["s"] = style
        if turn and o["k"] == "t":
            o["rot"] = (o.get("rot") or 0.0) + turn
    return out


def scene(an, pts: dict[int, list], radius: dict[int, float], texts: dict[int, str]) -> list[dict]:
    dr = an.drawing
    out: list[dict] = []
    for it in dr.items:
        if it.dxftype == "INSERT":  # a symbol's insertion point draws nothing itself
            continue
        out.extend(primitives(it, pts.get(it.index, it.pts), radius.get(it.index), texts.get(it.index), dr.units_mm))
    return out
