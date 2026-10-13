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

from .cadjson import entity_id
from .display import primitives
from .regen import regenerate_program

MAX_PX = 2400


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

    # ── state ───────────────────────────────────────────────────────────────────

    def _sync(self) -> None:
        if self.sm.revision != self._rev:
            self._rev = self.sm.revision
            self._cache.clear()
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
                cur.extend(primitives(it, pts, (sr.reg.radius.get(it.index) if sr else None), (sr.reg.texts.get(it.index) if sr else None), mm))
                drawn.add(it.index)
            if moved:
                ghost.extend(primitives(it, it.pts, None, None, mm))
        return cur, ghost, drawn

    # ── drawing ─────────────────────────────────────────────────────────────────

    def picture(self, *, box: tuple[float, float, float, float], unit: str | None = None, state: str = "current", ids: str = "none",
                highlight: Iterable[int] = (), baseline: bool = False, caption: str = "", sheet: bool = False, width: int = 1600) -> dict:
        """Draw (or recall) a picture. `ids`: none | lines (the unit's set-out lines x… y…) | entities (the unit's entity ids)
        | regions (R…, as drawn). `highlight`: sheet entity indices drawn in orange. `baseline`: the original geometry of
        what moved, dotted. `sheet`: the views boxed and named. Returns {"id", "png", "meta"}."""
        self._sync()
        if state not in ("current", "drawn"):
            raise ValueError("state is current or drawn")
        hl = tuple(sorted({int(i) for i in highlight}))
        key = (tuple(round(v, 3) for v in box), unit, state, ids, hl, baseline, sheet, width, caption)
        if key in self._cache:
            png, meta = self._cache[key]
            return {"id": meta["id"], "png": png, "meta": self.meta(meta["id"])}
        pid = f"IMG{self._n + 1}"  # drawn on the picture itself, so the id the model reads in a message is the one it sees
        png, meta = self._draw(box, unit, state, ids, set(hl), baseline, f"{pid} · {caption}" if caption else pid, sheet, width)
        self._n += 1
        meta["id"] = pid
        self._made[meta["id"]] = meta
        self._png[meta["id"]] = png
        for old_id in list(self._png)[:-80]:  # the last pictures only: a long run does not fill memory
            del self._png[old_id]
        self._cache[key] = (png, meta)
        return {"id": meta["id"], "png": png, "meta": self.meta(meta["id"])}

    def _draw(self, box, unit, state, ids, highlight, baseline, caption, sheet, width) -> tuple[bytes, dict]:
        sm = self.sm
        fr = make_frame(box, width)
        cur, ghost, drawn = self._prims(box, state)
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

        if baseline and ghost:  # what the drawing was, dotted, under what it is
            for p in ghost:
                if p["k"] == "p" and len(p["pts"]) >= 2:
                    line = [P(q) for q in p["pts"]] + ([P(p["pts"][0])] if p.get("closed") else [])
                    if inside(line):
                        _dashed(d, line, (60, 90, 255, 200), 1, (3.0, 3.0))
        for p in cur:  # fills first
            if p["k"] == "g" and len(p["pts"]) >= 3:
                poly = [P(q) for q in p["pts"]]
                if inside(poly):
                    d.polygon(poly, fill=(120, 120, 220, 38))
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
        # what the labels name
        meta_ids: dict = {}
        u = sm.units.get(unit) if unit else None
        if u is not None and ids != "none":
            meta_ids = self._overlay(d, fr, u, ids, state, box, drawn)
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
        meta = {"revision": sm.revision, "state": state, "unit": unit, "view_ids": self._views_in(box), "box": [round(v, 3) for v in box],
                "frame": fr.to_dict(), "mm_per_unit": sm.dr.units_mm, "entities_drawn": len(drawn),
                "differs_from_drawn": bool(sr and sr.changed), "fingerprint": h.hexdigest()[:16], "ids": ids, "baseline": baseline, **meta_ids}
        return buf.getvalue(), meta

    def _views_in(self, box) -> list[str]:
        x0, y0, x1, y1 = box
        out = []
        for g in self.sm.layout.groups:
            gx0, gy0, gx1, gy1 = g.bbox
            if g.kind == "view" and not (gx1 < x0 or gx0 > x1 or gy1 < y0 or gy0 > y1):
                out.append(g.id)
        return out

    def _text(self, img, d, fr: Frame, p: dict, highlight: set[int]) -> None:
        h_px = (p.get("h") or 1.0) * fr.scale
        if h_px < 4.5 and p["i"] not in highlight:
            return
        size = int(max(8, min(26, h_px)))
        text = (p["text"] or "").split("\n")[0][:60]
        x, y = fr.px(*p["at"])
        if not (fr.pad - 80 <= x <= fr.width - fr.pad + 80 and fr.pad - 80 <= y <= fr.height - fr.pad + 80):
            return
        col = (255, 130, 0) if p["i"] in highlight else (70, 120, 190) if p.get("dim") else (95, 95, 95)
        font = _font(size)
        rot = float(p.get("rot") or 0.0)
        if abs(rot) < 0.5 or abs(abs(rot) - 360) < 0.5:
            d.text((x, y), text, fill=col, font=font, anchor="ls")
            return
        w = int(d.textlength(text, font=font)) + 8
        tile = Image.new("RGBA", (w, size * 2 + 6), (255, 255, 255, 0))
        ImageDraw.Draw(tile).text((4, size + 2), text, fill=(*col, 255), font=font, anchor="ls")
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
        if ids == "lines":
            pos = self._datum_positions(u, state)
            shown = self._wanted_lines(u, pos, box)
            lab = _font(13)
            used_x: list[float] = []
            used_y: list[float] = []
            for did in sorted(shown, key=lambda k: pos[k][1]):
                axis, v = pos[did]
                if axis == "x":
                    px = fr.pad + (v - fr.x0) * fr.scale
                    d.line([(px, fr.pad - 8), (px, fr.height - fr.pad + 8)], fill=(0, 120, 255, 80), width=1)
                    row = sum(1 for q in used_x if abs(q - px) < 34) % 3
                    d.text((px, fr.pad - 12 - 15 * row), did, fill=(0, 90, 220), font=lab, anchor="ms")
                    used_x.append(px)
                else:
                    py = fr.height - fr.pad - (v - fr.y0) * fr.scale
                    d.line([(fr.pad - 8, py), (fr.width - fr.pad + 8, py)], fill=(0, 160, 80, 80), width=1)
                    col = sum(1 for q in used_y if abs(q - py) < 15) % 3
                    d.text((fr.pad - 12 - 40 * col, py), did, fill=(0, 130, 60), font=lab, anchor="rm")
                    used_y.append(py)
            info["lines_labelled"] = [{"id": k, "axis": pos[k][0], "at": round(pos[k][1], 3)} for k in shown]
        elif ids == "entities":
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
