"""Pictures of the sheet as it stands NOW — for the model, and for the person reading what the model looked at.

The agent used to see the DXF file as imported (ezdxf's own render of the file on disk): after a change the picture
and the engine's numbers described different drawings, and the model could not look closer. Here every picture is
drawn from the SAME primitives the canvas draws (display.primitives, from the regenerated points), stamped with the
sheet's revision, and comes with the frame that maps drawing coordinates to pixels — so what the model sees in a
picture and the ids and numbers its tools return are one geometry, and a picture of an older revision says it is stale.

    pics = Pictures(sm)
    sheet = pics.picture(box=sm.layout.frame, sheet=True)                       # the whole sheet, views boxed and named
    view = pics.picture(box=view_box, unit="U03", ids="lines")                  # one unit; set-out lines labelled x… / y…
    crop = pics.picture(box=(x0, y0, x1, y1), unit="U03", ids="entities")       # a closer look, entities tagged with their ids

Each picture is {"id": "IMG4", "png": bytes, "meta": {...}}; meta holds the revision, the crop, the pixel frame
(px = pad + (x − x0)·scale, py = height − pad − (y − y0)·scale), what was labelled and a fingerprint of the geometry
drawn. The picture shows the CURRENT state, or the state AS DRAWN (`state="drawn"`: the geometry the agent's ids and
numbers refer to: the analysis works on the drawing as imported, with the person's values applied only at the sheet).
"""

from __future__ import annotations

import hashlib
import io
import math
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise

from PIL import Image, ImageDraw, ImageFont

from . import viewplan as vp
from .cadjson import entity_id
from .display import primitives
from .regen import regenerate_program

MAX_PX = 2400
PNG_BUDGET = 96 * 1024 * 1024  # bytes of pictures kept for the person's gallery (a 1600 px picture is ~0.1–0.3 MB: several hundred)


@dataclass
class Frame:
    """The crop and how it maps to pixels (y up in the drawing, down in the picture)."""

    x0: float
    y0: float
    x1: float
    y1: float
    scale: float
    pad: int
    width: int
    height: int

    def px(self, x: float, y: float) -> tuple[float, float]:
        return (self.pad + (x - self.x0) * self.scale, self.height - self.pad - (y - self.y0) * self.scale)

    def world(self, px: float, py: float) -> tuple[float, float]:
        return (self.x0 + (px - self.pad) / self.scale, self.y0 + (self.height - self.pad - py) / self.scale)

    def to_dict(self) -> dict:
        return {"origin": [round(self.x0, 4), round(self.y0, 4)], "scale_px_per_unit": round(self.scale, 6), "pad": self.pad,
                "size": [self.width, self.height],
                "px_from_drawing": "px = pad + (x - origin_x) * scale ; py = height - pad - (y - origin_y) * scale"}


def make_frame(box: tuple[float, float, float, float], width: int = 1600, pad: int = 56) -> Frame:
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    width = min(max(int(width), 320), MAX_PX)
    scale = (width - 2 * pad) / w
    height = int(h * scale + 2 * pad)
    if height > MAX_PX:
        scale = (MAX_PX - 2 * pad) / h
        height = MAX_PX
        width = int(w * scale + 2 * pad)
    return Frame(x0, y0, x1, y1, scale, pad, width, height)


def _font(size: int):
    try:
        return ImageFont.load_default(size)
    except TypeError:  # an old Pillow: one size
        return ImageFont.load_default()


def _dashed(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], fill, width: int = 1, dash: tuple[float, float] = (6.0, 4.0)) -> None:
    """A dotted / dashed polyline (PIL has none): the on-off pattern runs along the whole line."""
    on, off = dash
    phase, drawing = 0.0, True
    for a, b in pairwise(pts):
        seg = math.dist(a, b)
        if seg < 1e-9:
            continue
        ux, uy = (b[0] - a[0]) / seg, (b[1] - a[1]) / seg
        pos = 0.0
        while pos < seg:
            step = min((on if drawing else off) - phase, seg - pos)
            if drawing:
                d.line([(a[0] + ux * pos, a[1] + uy * pos), (a[0] + ux * (pos + step), a[1] + uy * (pos + step))], fill=fill, width=width)
            pos += step
            phase += step
            if phase >= (on if drawing else off) - 1e-9:
                drawing, phase = not drawing, 0.0


def _pattern(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], fill, width: int, pattern: list[float]) -> None:
    """A polyline in a CAD linetype: dash, gap, dash … in pixels; a zero-length dash is a dot. The pattern runs on along
    the whole polyline (continuous linetype generation)."""
    n = len(pattern)
    if not n or sum(pattern) <= 1e-9:
        d.line(pts, fill=fill, width=width)
        return
    r = max(width / 2, 0.8)
    k, left = 0, pattern[0]
    for a, b in pairwise(pts):
        seg = math.dist(a, b)
        if seg < 1e-9:
            continue
        ux, uy = (b[0] - a[0]) / seg, (b[1] - a[1]) / seg
        pos = 0.0
        while True:
            if k % 2 == 0 and pattern[k] <= 1e-9:  # a dot, then on to the gap after it
                cx, cy = a[0] + ux * pos, a[1] + uy * pos
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
                k = (k + 1) % n
                left = pattern[k]
                continue
            if pos >= seg - 1e-9:
                break
            step = min(left, seg - pos)
            if k % 2 == 0:
                d.line([(a[0] + ux * pos, a[1] + uy * pos), (a[0] + ux * (pos + step), a[1] + uy * (pos + step))], fill=fill, width=width)
            pos += step
            left -= step
            if left <= 1e-9:
                k = (k + 1) % n
                left = pattern[k]


def paper_rgb(style: dict | None) -> tuple[int, int, int]:
    """An entity's colour on white paper: ACI 7 (white on a dark screen) is black; a colour too light to read on white
    (yellow, light cyan) is darkened, keeping its hue — what a monochrome-safe plot does."""
    if not style:
        return (40, 40, 40)
    if style.get("fg"):
        return (25, 25, 25)
    c = style.get("color", "#282828")
    r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    if lum > 0.62:
        k = 0.62 / lum
        r, g, b = int(r * k), int(g * k), int(b * k)
    return (r, g, b)


def _nice(mm: float) -> float:
    """A round length near `mm` for a scale bar."""
    if mm <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(mm))
    for m in (1, 2, 5, 10):
        if m * e >= mm * 0.7:
            return m * e
    return 10 * e


class Pictures:
    """The pictures of one sheet model, drawn on demand and remembered for the revision they show."""

    def __init__(self, sm):
        self.sm = sm
        self._rev = sm.revision
        self._cache: dict[tuple, tuple[bytes, dict]] = {}
        self._made: dict[str, dict] = {}
        self._png: dict[str, bytes] = {}
        self._n = 0
        self._sr = None
        self._sr_rev = None
        self._salience: dict[tuple, tuple] = {}

    # ── state ───────────────────────────────────────────────────────────────────

    def _sync(self) -> None:
        if self.sm.revision != self._rev:
            self._rev = self.sm.revision
            self._cache.clear()
            self._salience.clear()
            self._sr = None

    def regenerated(self):
        """The sheet as it now regenerates (once per revision)."""
        self._sync()
        if self._sr is None:
            self._sr = self.sm.regenerate()
        return self._sr

    def is_stale(self, img_id: str) -> bool:
        meta = self._made.get(img_id)
        return meta is None or meta["revision"] != self.sm.revision

    def png_of(self, img_id: str) -> bytes | None:
        return self._png.get(img_id)

    def meta(self, img_id: str) -> dict | None:
        m = self._made.get(img_id)
        return None if m is None else {**m, "stale": m["revision"] != self.sm.revision, "current_revision": self.sm.revision}

    # ── primitives of what is in a crop ─────────────────────────────────────────

    def _units_mm(self) -> dict[int, float]:
        out: dict[int, float] = {}
        for u in self.sm.units.values():
            for s in u.items:
                out[s] = u.sub.units_mm
        return out

    def _prims(self, box, state: str) -> tuple[list[dict], list[dict], set[int]]:
        """(current primitives, original primitives of the entities that moved, sheet entities drawn) within `box`."""
        sm = self.sm
        sr = self.regenerated() if state == "current" else None
        units = self._units_mm()
        x0, y0, x1, y1 = box
        m = 0.12 * max(x1 - x0, y1 - y0, 1e-9)
        bx0, by0, bx1, by1 = x0 - m, y0 - m, x1 + m, y1 + m
        cur: list[dict] = []
        ghost: list[dict] = []
        drawn: set[int] = set()
        for it in sm.dr.items:
            if it.dxftype == "INSERT" or not it.pts:
                continue
            pts = sr.reg.pts.get(it.index, it.pts) if sr else it.pts
            r = (sr.reg.radius.get(it.index) if sr else None) or it.radius or 0.0
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            moved = sr is not None and (it.index in sr.reg.pts and any(abs(a[0] - b[0]) > 1e-9 or abs(a[1] - b[1]) > 1e-9
                                                                        for a, b in zip(pts, it.pts, strict=False))
                                        or it.index in sr.reg.texts and sr.reg.texts[it.index] != it.text)
            hit_now = not (max(xs) + r < bx0 or min(xs) - r > bx1 or max(ys) + r < by0 or min(ys) - r > by1)
            hit_then = False
            if moved:
                ox, oy = [p[0] for p in it.pts], [p[1] for p in it.pts]
                hit_then = not (max(ox) + r < bx0 or min(ox) - r > bx1 or max(oy) + r < by0 or min(oy) - r > by1)
            if not (hit_now or hit_then):
                continue
            mm = units.get(it.index, sm.dr.units_mm)
            if hit_now:
                cur.extend(primitives(it, pts, (sr.reg.radius.get(it.index) if sr else None), (sr.reg.texts.get(it.index) if sr else None), mm,
                                      (sr.reg.turns.get(it.index, 0.0) if sr else 0.0)))
                drawn.add(it.index)
            if moved:
                ghost.extend(primitives(it, it.pts, None, None, mm))
        return cur, ghost, drawn

    # ── drawing ─────────────────────────────────────────────────────────────────

    def picture(self, *, box: tuple[float, float, float, float], unit: str | None = None, state: str = "current", ids: str = "none",
                highlight: Iterable[int] = (), baseline: bool = False, caption: str = "", sheet: bool = False, width: int | None = 1600,
                kind: str = "", tiles: Iterable[tuple[float, float, float, float]] = ()) -> dict:
        """Draw (or recall) a picture. `ids`: none | lines (the unit's set-out lines x… y…) | entities (the unit's entity ids)
        | regions (R…, as drawn). `highlight`: sheet entity indices drawn in orange. `baseline`: the original geometry of
        what moved, dotted. `sheet`: the views boxed and named. `width`: pixels, or None for the width at which this box's own text is readable
        (viewplan: never more than the model reads). `kind`: overview | tile | zoom | sheet (what the picture is for). `tiles`: boxes marked on it
        as TILE_1… Returns {"id", "png", "meta"}."""
        self._sync()
        if state not in ("current", "drawn"):
            raise ValueError("state is current or drawn")
        hl = tuple(sorted({int(i) for i in highlight}))
        tiles = tuple(tuple(round(v, 3) for v in b) for b in tiles)
        key = (tuple(round(v, 3) for v in box), unit, state, ids, hl, baseline, sheet, width, caption, kind, tiles)
        if key in self._cache:
            png, meta = self._cache[key]
            return {"id": meta["id"], "png": png, "meta": self.meta(meta["id"])}
        pid = f"IMG{self._n + 1}"  # drawn on the picture itself, so the id the model reads in a message is the one it sees
        png, meta = self._draw(box, unit, state, ids, set(hl), baseline, f"{pid} · {caption}" if caption else pid, sheet, width, kind or ("sheet" if sheet else "zoom"), tiles)
        self._n += 1
        meta["id"] = pid
        meta["caption"] = caption  # what the picture is OF, in words, without the id drawn on it: the person's gallery names it so
        self._made[meta["id"]] = meta
        self._png[meta["id"]] = png
        held = sum(len(b) for b in self._png.values())
        for old_id in list(self._png)[:-1]:  # the person's gallery keeps what the model was shown, oldest let go first; the newest always stays
            if held <= PNG_BUDGET:
                break
            held -= len(self._png.pop(old_id))
        self._cache[key] = (png, meta)
        return {"id": meta["id"], "png": png, "meta": self.meta(meta["id"])}

    def text_heights(self, box, state: str = "drawn") -> list[float]:
        """The heights (drawing units) of the texts in a box: what its own text size is, and so how big a picture of it has to be."""
        cur, _g, _d = self._prims(box, state)
        return [p["h"] for p in cur if p["k"] == "t" and (p.get("text") or "").strip() and p.get("h")]

    def text_points(self, box, state: str = "drawn") -> list[tuple[float, float]]:
        """Where the notes and dimensions are (their anchor points) inside a box."""
        cur, _g, _d = self._prims(box, state)
        x0, y0, x1, y1 = box
        return [(p["at"][0], p["at"][1]) for p in cur if p["k"] == "t" and (p.get("text") or "").strip() and x0 <= p["at"][0] <= x1 and y0 <= p["at"][1] <= y1]

    def plan(self, box, state: str = "drawn") -> vp.Plan:
        """How to show a box so that its text can be read: the overview and, when that cannot be, the tiles (viewplan.plan_pictures) — placed where the
        text is, so that a unit with little text is still read at the scale its text needs."""
        return vp.plan_pictures(box, vp.text_height(self.text_heights(box, state), box), texts=self.text_points(box, state))

    def _draw(self, box, unit, state, ids, highlight, baseline, caption, sheet, width, kind: str = "zoom", tiles=()) -> tuple[bytes, dict]:
        sm = self.sm
        cur, ghost, drawn = self._prims(box, state)
        heights = [p["h"] for p in cur if p["k"] == "t" and (p.get("text") or "").strip() and p.get("h")]
        text_h = vp.text_height(heights, box)
        labelled = ids == "lines"  # the labels live in the margin: it is made big enough for them, and the drawing never gets them on top of it
        pad = vp.GUTTER if labelled else 56
        if width is None:
            width = vp.picture_width(box, vp.TEXT_PX / max(text_h, 1e-12), pad=pad)
        fr = make_frame(box, min(int(width), vp.MODEL_SIDE) if kind in ("overview", "tile") else int(width), pad)
        img = Image.new("RGB", (fr.width, fr.height), "white")
        d = ImageDraw.Draw(img, "RGBA")
        furniture = set(sm.layout.furniture())
        # the pixel clip: nothing is drawn outside the crop's frame (a picture of a crop is a crop)
        clip = (fr.pad, fr.pad, fr.width - fr.pad, fr.height - fr.pad)

        def P(p):
            x, y = fr.px(max(min(p[0], 1e9), -1e9), max(min(p[1], 1e9), -1e9))
            return (x, y)

        def inside(pts):
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            return not (max(xs) < clip[0] - 40 or min(xs) > clip[2] + 40 or max(ys) < clip[1] - 40 or min(ys) > clip[3] + 40)

        under = None
        u0 = sm.unit(unit) if unit in sm.units else None  # built if it was not yet: a picture of a unit needs its analysis
        if u0 is not None and ids == "lines":  # the set-out lines: which ones, and faint hairlines UNDER the drawing (never over a note)
            under = self._plan_lines(u0, fr, box, state, 44.0 if kind == "overview" else vp.MIN_LINE_PX)
            self._hairlines(d, fr, under)
        if baseline and ghost:  # what the drawing was, dotted, under what it is
            for p in ghost:
                if p["k"] == "p" and len(p["pts"]) >= 2:
                    line = [P(q) for q in p["pts"]] + ([P(p["pts"][0])] if p.get("closed") else [])
                    if inside(line):
                        _dashed(d, line, (60, 90, 255, 200), 1, (3.0, 3.0))
        for p in cur:  # fills first: hatch boundaries (a faint tint under a pattern), solid fills, arrowheads, wipeouts
            if p["k"] == "g" and len(p["pts"]) >= 3:
                poly = [P(q) for q in p["pts"]]
                if not inside(poly):
                    continue
                if p.get("mask"):
                    d.polygon(poly, fill=(255, 255, 255, 255))
                elif p.get("fill") == "pattern":
                    d.polygon(poly, fill=(*paper_rgb(p.get("s")), 22))
                else:
                    col = (255, 130, 0) if p["i"] in highlight else paper_rgb(p.get("s"))
                    d.polygon(poly, fill=(*col, int(255 * (p.get("s") or {}).get("alpha", 1.0))))
        for p in cur:  # hatch pattern lines, thin
            if p["k"] == "m":
                col = (*paper_rgb(p.get("s")), 150)
                segs = p["segs"]
                for x0_, y0_, x1_, y1_ in segs:
                    a, b = P((x0_, y0_)), P((x1_, y1_))
                    if inside([a, b]):
                        d.line([a, b], fill=col, width=1)
        for p in cur:
            if p["k"] != "p" or len(p["pts"]) < 2:
                continue
            line = [P(q) for q in p["pts"]] + ([P(p["pts"][0])] if p.get("closed") else [])
            if not inside(line):
                continue
            i = p["i"]
            if i in highlight:
                d.line(line, fill=(255, 130, 0, 255), width=4)
                continue
            role = p["role"]
            st = p.get("s")
            if st is not None:  # as the draftsman drew it: colour, linetype, lineweight (structure a little heavier)
                col = (*paper_rgb(st), int(255 * st.get("alpha", 1.0)))
                if i in furniture or role == "fixed":
                    col = (*col[:3], 120)
                w = max(1, round((st.get("lw") or 0.25) / 0.3)) + (1 if role == "structural" and not p.get("dim") else 0)
                dash = st.get("dash") or []
                px_pattern = [abs(v) * fr.scale for v in dash]
                if dash and sum(px_pattern) >= 4:  # a pattern finer than a few pixels draws as a line (as CAD does when zoomed out)
                    _pattern(d, line, col, w, px_pattern)
                else:
                    d.line(line, fill=col, width=w)
                continue
            if i in furniture or role == "fixed":
                col, w = (200, 200, 200, 255), 1
            elif p.get("dim"):
                col, w = (70, 120, 190, 255), 1
            elif role == "structural":
                col, w = (20, 20, 20, 255), 2
            elif role == "reference":
                col, w = (200, 40, 40, 255), 1
            else:
                col, w = (130, 130, 130, 255), 1
            d.line(line, fill=col, width=w)
        for p in cur:
            if p["k"] == "t" and (p.get("text") or "").strip():
                self._text(img, d, fr, p, highlight)
        if labelled:  # the margin is the labels': whatever the drawing ran on into it (a long line, a note cut by the crop) is painted out first
            w_, h_, pd = fr.width, fr.height, fr.pad
            for box_ in ((0, 0, w_, pd - 1), (0, h_ - pd + 1, w_, h_), (0, 0, pd - 1, h_), (w_ - pd + 1, 0, w_, h_)):
                d.rectangle(box_, fill=(255, 255, 255, 255))
        # what the labels name
        meta_ids: dict = {}
        u = u0
        if u is not None and ids == "lines" and under is not None:
            meta_ids = self._margin_labels(img, d, fr, under)
        elif u is not None and ids != "none":
            meta_ids = self._overlay(d, fr, u, ids, state, box, drawn)
        if tiles:
            meta_ids["tiles"] = self._mark_tiles(d, fr, tiles)
        if sheet:
            self._view_boxes(d, fr, box)
        self._scale_bar(d, fr)
        cap = caption or ""
        cap = (cap + " · " if cap else "") + f"revision {sm.revision} · {'as drawn' if state == 'drawn' else 'current'}"
        d.text((fr.pad, 6), cap, fill=(30, 30, 30), font=_font(14), stroke_width=2, stroke_fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        h = hashlib.sha256()
        sr = self.regenerated() if state == "current" else None
        for i in sorted(drawn):
            pts = sr.reg.pts.get(i, sm.dr.items[i].pts) if sr else sm.dr.items[i].pts
            h.update(f"{i}:{[(round(a, 3), round(b, 3)) for a, b in pts]}".encode())
        text_px = text_h * fr.scale
        meta = {"revision": sm.revision, "state": state, "unit": unit, "view_ids": self._views_in(box), "box": [round(v, 3) for v in box],
                "frame": fr.to_dict(), "mm_per_unit": sm.dr.units_mm, "entities_drawn": len(drawn),
                "differs_from_drawn": bool(sr and sr.changed), "fingerprint": h.hexdigest()[:16], "ids": ids, "baseline": baseline,
                "kind": kind, "mm_per_px": round(sm.dr.units_mm / fr.scale, 3), "text_px": round(text_px, 1),
                "legible": text_px >= vp.LEGIBLE * vp.TEXT_PX, **meta_ids}
        return buf.getvalue(), meta

    def content_box(self, box, state: str = "drawn", margin: float = 0.03) -> tuple[float, float, float, float]:
        """The box of what is drawn in `box`: the geometry without the few long stray lines that stretch a view's box (the points inside the box, the
        extreme half-percent of them on each side set aside), and every note and dimension text kept. Blank space costs pixels: a picture of a
        section that is mostly sky is a picture whose text is small."""
        cur, _g, _d = self._prims(box, state)
        furniture = set(self.sm.layout.furniture())
        x0, y0, x1, y1 = box
        xs: list[float] = []
        ys: list[float] = []
        tx: list[float] = []
        ty: list[float] = []
        for p in cur:
            if p["i"] in furniture:
                continue
            if p["k"] in ("p", "g"):
                for q in p["pts"]:
                    if x0 <= q[0] <= x1 and y0 <= q[1] <= y1:
                        xs.append(q[0])
                        ys.append(q[1])
            elif p["k"] == "t" and (p.get("text") or "").strip() and x0 <= p["at"][0] <= x1 and y0 <= p["at"][1] <= y1:
                tx.append(p["at"][0])
                ty.append(p["at"][1])
        if len(xs) < 20:
            return box
        cx0, cx1 = vp.percentile(xs, 0.5), vp.percentile(xs, 99.5)
        cy0, cy1 = vp.percentile(ys, 0.5), vp.percentile(ys, 99.5)
        if tx:
            cx0, cx1, cy0, cy1 = min(cx0, min(tx)), max(cx1, max(tx)), min(cy0, min(ty)), max(cy1, max(ty))
        m = margin * max(cx1 - cx0, cy1 - cy0, 1e-9)
        out = (max(x0, cx0 - m), max(y0, cy0 - m), min(x1, cx1 + m), min(y1, cy1 + m))
        if (out[2] - out[0]) < 0.1 * (x1 - x0) or (out[3] - out[1]) < 0.1 * (y1 - y0):
            return box
        return out

    def count_texts(self, box, state: str = "drawn") -> int:
        x0, y0, x1, y1 = box
        cur, _g, _d = self._prims(box, state)
        return sum(1 for p in cur if p["k"] == "t" and (p.get("text") or "").strip() and x0 <= p["at"][0] <= x1 and y0 <= p["at"][1] <= y1)

    def dense_text_boxes(self, box, ideal_scale: float, state: str = "drawn", k: int = 3) -> list[tuple[float, float, float, float]]:
        """Where the notes crowd: boxes of a size at which the text reaches its ideal scale, centred on the densest clusters of texts — ready to give
        zoom_view. At most k, the densest first, no two overlapping by more than a third."""
        cur, _g, _d = self._prims(box, state)
        x0, y0, x1, y1 = box
        pts = [p["at"] for p in cur if p["k"] == "t" and (p.get("text") or "").strip() and x0 <= p["at"][0] <= x1 and y0 <= p["at"][1] <= y1]
        if len(pts) < 6:
            return []
        h = min(x1 - x0, y1 - y0, (vp.MODEL_SIDE - 2 * vp.GUTTER) / max(ideal_scale, 1e-12) * 0.85)  # a box the ideal scale fits in a picture
        w = min(h * 1.25, x1 - x0)
        cells: dict[tuple[int, int], int] = {}
        for x, y in pts:
            cell = (int((x - x0) // (w / 2)), int((y - y0) // (h / 2)))
            cells[cell] = cells.get(cell, 0) + 1
        out: list[tuple[float, float, float, float]] = []
        for (i, j), n in sorted(cells.items(), key=lambda kv: -kv[1]):
            if n < 4 or len(out) >= k:
                break
            cx, cy = x0 + (i + 0.5) * w / 2, y0 + (j + 0.5) * h / 2
            b = (max(x0, cx - w / 2), max(y0, cy - h / 2), min(x1, cx + w / 2), min(y1, cy + h / 2))
            if all(min(b[2], o[2]) - max(b[0], o[0]) < w / 3 or min(b[3], o[3]) - max(b[1], o[1]) < h / 3 for o in out):
                out.append(b)
        return out

    def unit_set(self, uid: str, box, state: str = "drawn") -> dict:
        """The pictures a unit needs to be read: its overview (the structure and the set-out lines that matter) and, when its text would be a blur
        there, the tiles — each at the scale that makes its text readable — marked on the overview as TILE_1… The box is cropped to what is drawn;
        a tile with no note or dimension in it is not made (its geometry is in the overview, its numbers in the tables)."""
        box = self.content_box(box, state)
        plan = self.plan(box, state)
        tiles = plan.tiles
        if tiles and not plan.placed:  # a grid tile with next to nothing to read is not made: its geometry is in the overview, its numbers in the tables
            tiles = vp.with_text(tiles, self.text_points(box, state))
        plan.tiles = tiles
        overview = self.picture(box=box, unit=uid, state=state, ids="lines", caption=f"{uid} · " + ("overview" if tiles else "set-out lines"), width=plan.width,
                                kind="overview", tiles=tiles)
        shots = [self.picture(box=tb, unit=uid, state=state, ids="lines", caption=f"{uid} · TILE_{k}", width=vp.picture_width(tb, plan.ideal_scale), kind="tile")
                 for k, tb in enumerate(tiles, 1)]
        zoom = self.dense_text_boxes(box, plan.ideal_scale, state) if (not plan.legible and not plan.tile_legible) else []
        return {"plan": plan, "box": box, "overview": overview, "tiles": shots, "zoom": zoom}

    def _views_in(self, box) -> list[str]:
        x0, y0, x1, y1 = box
        out = []
        for g in self.sm.layout.groups:
            gx0, gy0, gx1, gy1 = g.bbox
            if g.kind == "view" and not (gx1 < x0 or gx0 > x1 or gy1 < y0 or gy0 > y1):
                out.append(g.id)
        return out

    def _text(self, img, d, fr: Frame, p: dict, highlight: set[int]) -> None:
        """A text as CAD places it: its anchor, how it hangs from it (left / centre / right × top / middle / baseline),
        its rotation and its own colour — up to a few lines of a note."""
        h_px = (p.get("h") or 1.0) * fr.scale
        if h_px < 4.5 and p["i"] not in highlight:
            return
        size = int(max(8, min(28, h_px * 1.25)))
        lines = [ln[:80] for ln in (p["text"] or "").split("\n")[:6]]
        x, y = fr.px(*p["at"])
        if not (fr.pad - 200 <= x <= fr.width - fr.pad + 200 and fr.pad - 200 <= y <= fr.height - fr.pad + 200):
            return
        st = p.get("s")
        col = (255, 130, 0) if p["i"] in highlight else paper_rgb(st) if st is not None else (70, 120, 190) if p.get("dim") else (95, 95, 95)
        font = _font(size)
        lh = int(size * 1.35 * (p.get("ls") or 1.0))
        w = max(int(d.textlength(ln, font=font)) for ln in lines) + 4
        block_h = lh * (len(lines) - 1) + size
        ha, va = p.get("ha", "l"), p.get("va", "b")
        ax = {"l": 0, "c": w / 2, "r": w}.get(ha, 0)
        ay = {"t": 0, "m": block_h / 2, "b": block_h - size * 0.2, "bt": block_h}.get(va, block_h - size * 0.2)
        # the tile is twice the block so the anchor is its centre: rotating about the centre keeps the anchor in place
        tw, th = int(2 * max(ax, w - ax) + 8), int(2 * max(ay, block_h - ay) + 8)
        tile = Image.new("RGBA", (tw, th), (255, 255, 255, 0))
        td = ImageDraw.Draw(tile)
        ox, oy = tw / 2 - ax, th / 2 - ay
        for k, ln in enumerate(lines):
            td.text((ox, oy + k * lh), ln, fill=(*col, 255), font=font, anchor="la")
        rot = float(p.get("rot") or 0.0)
        if abs(rot) > 0.5 and abs(abs(rot) - 360) > 0.5:
            tile = tile.rotate(rot, expand=True, resample=Image.BICUBIC)
        img.paste(tile, (int(x - tile.width / 2), int(y - tile.height / 2)), tile)

    def _scale_bar(self, d: ImageDraw.ImageDraw, fr: Frame) -> None:
        mm_per_unit = self.sm.dr.units_mm
        px_per_mm = fr.scale / mm_per_unit if mm_per_unit else 0
        if px_per_mm <= 0:
            return
        target_mm = (fr.width - 2 * fr.pad) * 0.18 / px_per_mm
        mm = _nice(target_mm)
        length = mm * px_per_mm
        x, y = fr.pad, fr.height - 22
        d.line([(x, y), (x + length, y)], fill=(0, 0, 0), width=3)
        d.line([(x, y - 4), (x, y + 4)], fill=(0, 0, 0), width=2)
        d.line([(x + length, y - 4), (x + length, y + 4)], fill=(0, 0, 0), width=2)
        d.text((x + length + 6, y), f"{mm:g} mm", fill=(0, 0, 0), font=_font(13), anchor="lm")

    def _view_boxes(self, d: ImageDraw.ImageDraw, fr: Frame, box) -> None:
        colours = {"view": (37, 99, 235), "table": (22, 163, 74), "notes": (180, 120, 20), "title_block": (124, 58, 237), "label": (220, 38, 38)}
        for g in self.sm.layout.groups:
            col = colours.get(g.kind, (0, 0, 0))
            a, b = fr.px(g.bbox[0], g.bbox[3]), fr.px(g.bbox[2], g.bbox[1])
            d.rectangle([a, (max(b[0], a[0] + 2), max(b[1], a[1] + 2))], outline=(*col, 255), fill=(*col, 16), width=3 if g.kind == "view" else 2)
            unit = self.sm.unit_of_view.get(g.id)
            label = f"{g.id} {g.view_type if g.kind == 'view' else g.kind}" + (f" · {g.name[:40]}" if g.name else "") + (f" [{unit}]" if unit else "")
            d.text((a[0] + 4, a[1] + 3), label, fill=(*col, 255), font=_font(16), stroke_width=3, stroke_fill=(255, 255, 255))

    # ── what the labels name ────────────────────────────────────────────────────

    def _salience_inputs(self, u) -> tuple[dict[str, tuple[bool, bool, int, int]], int]:
        """Per set-out line of a unit: does a dimension or a named size stand on it, is it an axis or a stated level, how many entities are drawn on it,
        how many major regions it bounds (viewplan.salience). Once per unit and revision."""
        key = (u.id, self._rev)
        got = self._salience.get(key)
        if got is not None:
            return got
        from .topology import DatumIndex
        from .topology import of as topology_of

        an = u.an
        named = {m for p in (u.prog.params.values() if u.prog is not None else []) for m in (p.measures or ())}
        dims: set[str] = set()
        for c in an.clusters.values():
            if c.kind.value == "dim":
                for g in c.gaps:
                    gap = an.gaps.get(g)
                    if gap is not None and gap.axis in ("x", "y"):
                        dims |= {gap.a, gap.b}
        axes = {dd for dd, *_ in an.stated_levels} | set(an.axes)
        regions: dict[str, int] = {}
        topo = topology_of(an)
        if topo.regions:
            big = 0.0025 * max((abs(r.area) for r in topo.regions), default=0.0) * 4
            dix = DatumIndex(an)
            for r in topo.regions:
                if abs(r.area) >= big:
                    for axis, v in (("x", r.bbox[0]), ("x", r.bbox[2]), ("y", r.bbox[1]), ("y", r.bbox[3])):
                        d = dix.at(axis, v)
                        if d:
                            regions[d] = regions.get(d, 0) + 1
        out = {d.id: (d.id in dims or d.id in named, d.id in axes, len(d.items), regions.get(d.id, 0)) for d in an.datums.values()}
        top = max((v[2] for v in out.values()), default=0)
        self._salience[key] = (out, top)
        return out, top

    def _plan_lines(self, u, fr: Frame, box, state: str, min_gap: float = vp.MIN_LINE_PX) -> dict:
        """Which of the unit's set-out lines this picture labels, and which crowd into a band: scored (viewplan.salience), at most as many as fit."""
        pos = self._datum_positions(u, state)
        inputs, top = self._salience_inputs(u)
        x0, y0, x1, y1 = box
        xs: list[vp.Line] = []
        ys: list[vp.Line] = []
        for did, (axis, v) in pos.items():
            if axis == "x" and x0 <= v <= x1:
                target, p = xs, fr.pad + (v - fr.x0) * fr.scale
            elif axis == "y" and y0 <= v <= y1:
                target, p = ys, fr.height - fr.pad - (v - fr.y0) * fr.scale
            else:
                continue
            anchored, axis_line, drawn_on, regions = inputs.get(did, (False, False, 0, 0))
            target.append(vp.Line(did, p, vp.salience(anchored, axis_line, drawn_on, top, regions), anchored or axis_line))
        keep_x, bands_x = vp.admit(xs, fr.width - 2 * fr.pad, min_gap)
        keep_y, bands_y = vp.admit(ys, fr.height - 2 * fr.pad, min_gap)
        return {"x": keep_x, "y": keep_y, "bands_x": bands_x, "bands_y": bands_y, "total_x": len(xs), "total_y": len(ys), "pos": pos}

    @staticmethod
    def _hairlines(d: ImageDraw.ImageDraw, fr: Frame, plan: dict) -> None:
        """The labelled set-out lines inside the drawing: faint dashed hairlines, drawn FIRST so geometry and notes lie over them (a line of the
        drawing is never hidden by a construction line, and a note is never struck through)."""
        for x in plan["x"]:
            _dashed(d, [(x.pos, fr.pad), (x.pos, fr.height - fr.pad)], (0, 120, 255, 44), 1, (7.0, 6.0))
        for y in plan["y"]:
            _dashed(d, [(fr.pad, y.pos), (fr.width - fr.pad, y.pos)], (0, 160, 80, 44), 1, (7.0, 6.0))

    def _margin_labels(self, img: Image.Image, d: ImageDraw.ImageDraw, fr: Frame, plan: dict) -> dict:
        """Ticks at full strength in the margin, labels on tracks outside the drawing, moved the least that stops them touching (isotonic regression)
        and joined to their tick by a leader; crowded lines that were left out are a bracket and one label. Nothing here lies on the drawing."""
        font, small = _font(13), _font(11)
        blue, green, grey = (0, 90, 220), (0, 130, 60), (110, 110, 110)
        # ── x lines: ticks along the top edge, labels on four tracks above ───────────────────────
        xs = plan["x"]
        tracks = vp.assign_tracks(len(xs), vp.TRACKS)
        for r in range(vp.TRACKS):
            mine = [x for x, tr in zip(xs, tracks, strict=True) if tr == r]
            widths = [d.textlength(x.id, font=font) + 10 for x in mine]
            centres = vp.pack_labels([x.pos for x in mine], widths, 2.0, fr.width - 2.0)
            ty = fr.pad - 22 - 16 * r
            for x, cx, w in zip(mine, centres, widths, strict=True):
                d.line([(x.pos, fr.pad - 9), (x.pos, fr.pad)], fill=(*blue, 255), width=2)  # the tick: where the line is
                if abs(cx - x.pos) > 2:  # the dogleg to a label that had to move
                    d.line([(x.pos, fr.pad - 9), (x.pos, ty + 9), (cx, ty + 7)], fill=(*blue, 150), width=1)
                elif r:
                    d.line([(x.pos, fr.pad - 9), (x.pos, ty + 8)], fill=(*blue, 110), width=1)
                d.rounded_rectangle([cx - w / 2, ty - 8, cx + w / 2, ty + 8], radius=4, fill=(255, 255, 255, 238), outline=(*blue, 110))
                d.text((cx, ty), x.id, fill=blue, font=font, anchor="mm")
        # ── y lines: ticks down the left edge, labels in two columns beside it ─────────────────
        ys = plan["y"]
        cols = vp.assign_tracks(len(ys), 2)
        for c in range(2):
            mine = [y for y, col in zip(ys, cols, strict=True) if col == c]
            centres = vp.pack_labels([y.pos for y in mine], [16.0] * len(mine), 2.0, fr.height - 2.0, gap=1.0)
            rx = fr.pad - 16 - 54 * c
            for y, cy in zip(mine, centres, strict=True):
                w = d.textlength(y.id, font=font) + 10
                d.line([(fr.pad - 9, y.pos), (fr.pad, y.pos)], fill=(*green, 255), width=2)
                if abs(cy - y.pos) > 2:
                    d.line([(fr.pad - 9, y.pos), (rx + 8, cy)], fill=(*green, 150), width=1)
                elif c:
                    d.line([(fr.pad - 9, y.pos), (rx + 2, y.pos)], fill=(*green, 110), width=1)
                d.rounded_rectangle([rx - w, cy - 8, rx + 2, cy + 8], radius=4, fill=(255, 255, 255, 238), outline=(*green, 110))
                d.text((rx - w / 2 + 1, cy), y.id, fill=green, font=font, anchor="mm")
        # ── the lines left out where they crowd: a bracket in the margin, and the legend says which (a label there would lie on the others) ──
        for b in plan["bands_y"]:
            d.line([(fr.pad - 12, b.lo), (fr.pad - 12, b.hi)], fill=(*grey, 230), width=3)
        for b in plan["bands_x"]:
            d.line([(b.lo, fr.pad - 12), (b.hi, fr.pad - 12)], fill=(*grey, 230), width=3)
        bands = plan["bands_x"] + plan["bands_y"]
        if bands:
            words = [f"{b.first}..{b.last} ({b.count} lines)" for b in sorted(bands, key=lambda b: -b.count)]
            text = "grey brackets: lines left out where they crowd - " + ", ".join(words[:7]) + (f", +{len(words) - 7} more" if len(words) > 7 else "") + " - zoom_view a box to label them"
            row, line = [], ""
            for w in text.split(" "):
                if d.textlength((line + " " + w).strip(), font=small) > fr.width - 2 * fr.pad:
                    row.append(line)
                    line = w
                else:
                    line = (line + " " + w).strip()
            row.append(line)
            for k, ln in enumerate(row[:2]):
                d.text((fr.pad, fr.height - 70 + 14 * k), ln, fill=grey, font=small, anchor="ls")
        pos = plan["pos"]
        shown = [x.id for x in xs] + [y.id for y in ys]
        return {"lines_labelled": [{"id": k, "axis": pos[k][0], "at": round(pos[k][1], 3)} for k in shown],
                "lines_in_frame": plan["total_x"] + plan["total_y"],
                "lines_banded": [{"from": b.first, "to": b.last, "count": b.count} for b in plan["bands_x"] + plan["bands_y"]]}

    @staticmethod
    def _mark_tiles(d: ImageDraw.ImageDraw, fr: Frame, tiles) -> list[dict]:
        """The boxes of the detail tiles, dashed and named on the overview — so a picture of a part says which part of the whole it is."""
        out = []
        font = _font(15)
        for k, b in enumerate(tiles, 1):
            a, c = fr.px(b[0], b[3]), fr.px(b[2], b[1])
            _dashed(d, [a, (c[0], a[1]), c, (a[0], c[1]), a], (225, 105, 0, 255), 3, (12.0, 6.0))
            name = f"TILE_{k}"
            w = d.textlength(name, font=font) + 12
            d.rounded_rectangle([a[0] + 4, a[1] + 4, a[0] + 4 + w, a[1] + 26], radius=5, fill=(225, 105, 0, 235))
            d.text((a[0] + 10, a[1] + 15), name, fill=(255, 255, 255), font=font, anchor="lm")
            out.append({"name": name, "box": [round(v, 3) for v in b]})
        return out

    def _datum_positions(self, u, state: str) -> dict[str, tuple[str, float]]:
        """Set-out lines of the unit (id → (axis, position)): as drawn, or as the unit regenerates now."""
        an = u.an
        out = {d.id: (d.axis, d.value) for d in an.datums.values()}
        if state == "current" and u.prog is not None:
            try:
                r = regenerate_program(u.prog, self.sm._values_for(u, {}))
                out = {k: (out[k][0], v) for k, v in r.datum.items() if k in out}
            except (KeyError, ArithmeticError, ValueError):
                pass
        return out

    def _wanted_lines(self, u, positions, box) -> list[str]:
        """Which set-out lines to label: the ends of every named size, stated levels, axes — and any line crossing the crop,
        up to 90 so the picture stays legible."""
        an = u.an
        wanted: list[str] = []
        prog = u.prog
        if prog is not None:
            for p in prog.params.values():
                if p.measures:
                    wanted.extend(p.measures)
        wanted += [dd for dd, *_ in an.stated_levels] + [a for a in an.axes]
        x0, y0, x1, y1 = box
        near = [k for k, (ax, v) in positions.items() if (x0 <= v <= x1 if ax == "x" else y0 <= v <= y1)]
        seen, out = set(), []
        for k in wanted + sorted(near, key=lambda k: positions[k][1]):
            if k in positions and k not in seen:
                ax, v = positions[k]
                if (x0 <= v <= x1) if ax == "x" else (y0 <= v <= y1):
                    seen.add(k)
                    out.append(k)
            if len(out) >= 90:
                break
        return out

    def _overlay(self, d: ImageDraw.ImageDraw, fr: Frame, u, ids: str, state: str, box, drawn: set[int]) -> dict:
        info: dict = {}
        if ids == "entities":
            inv = {s: k for k, s in enumerate(u.back)}
            font = _font(11)
            taken: set[tuple[int, int]] = set()
            tagged: list[dict] = []
            for s in sorted(drawn):
                k = inv.get(s)
                if k is None:
                    continue
                it = u.sub.items[k]
                if it.dxftype in ("DIMENSION", "HATCH") and len(tagged) > 60:
                    continue
                pts = self._pts_of(s, state)
                if not pts:
                    continue
                mid = self._anchor_of(it, pts)
                x, y = fr.px(*mid)
                if not (fr.pad <= x <= fr.width - fr.pad and fr.pad <= y <= fr.height - fr.pad):
                    continue
                cell = (int(x // 46), int(y // 14))
                if cell in taken:
                    continue
                taken.add(cell)
                eid = entity_id(it)
                d.text((x + 3, y - 3), eid, fill=(190, 0, 110), font=font, stroke_width=2, stroke_fill=(255, 255, 255), anchor="lb")
                d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(190, 0, 110))
                tagged.append({"id": eid, "sheet": s, "kind": it.dxftype, "at": [round(mid[0], 3), round(mid[1], 3)]})
                if len(tagged) >= 150:
                    break
            info["entities_labelled"] = tagged
            info["entities_in_crop"] = len([s for s in drawn if s in inv])
        elif ids == "regions":
            if state == "current" and self.regenerated().changed:
                info["regions_note"] = "regions are drawn as imported; the sheet has changed values, so a map of them would not match this picture"
            else:
                from .topology import of as topology_of

                regs = topology_of(u.an).regions
                palette = [(230, 120, 120), (120, 170, 230), (130, 200, 130), (230, 190, 100), (180, 130, 220), (100, 200, 200), (220, 150, 190), (170, 170, 110)]
                shown = []
                for n, r in enumerate(sorted(regs, key=lambda r: -abs(r.area))):
                    col = palette[n % len(palette)]
                    d.polygon([fr.px(*p) for p in r.ring], fill=(*col, 70), outline=(*col, 255))
                    for hole in r.holes:
                        d.polygon([fr.px(*p) for p in hole], fill=(255, 255, 255, 255))
                    shown.append(r.id)
                for r in regs:
                    size = int(max(10, min(22, ((r.bbox[2] - r.bbox[0]) * fr.scale) / 4, ((r.bbox[3] - r.bbox[1]) * fr.scale) / 1.2)))
                    d.text(fr.px(*r.inside), r.id, fill=(0, 0, 0), font=_font(size), anchor="mm", stroke_width=2, stroke_fill=(255, 255, 255))
                info["regions_labelled"] = shown
        return info

    def _pts_of(self, sheet_index: int, state: str):
        it = self.sm.dr.items[sheet_index]
        if state == "current":
            return self.regenerated().reg.pts.get(sheet_index, it.pts)
        return it.pts

    @staticmethod
    def _anchor_of(it, pts) -> tuple[float, float]:
        """Where an entity's tag sits: the middle of its first segment (a text: its anchor)."""
        if len(pts) == 1 or it.dxftype in ("TEXT", "MTEXT", "ATTRIB", "CIRCLE", "ARC", "POINT"):
            return pts[0]
        a, b = pts[0], pts[1]
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def box_around(boxes: Iterable[tuple[float, float, float, float]], margin: float = 0.06) -> tuple[float, float, float, float]:
    bs = list(boxes)
    x0, y0 = min(b[0] for b in bs), min(b[1] for b in bs)
    x1, y1 = max(b[2] for b in bs), max(b[3] for b in bs)
    m = margin * max(x1 - x0, y1 - y0, 1e-9)
    return (x0 - m, y0 - m, x1 + m, y1 + m)
