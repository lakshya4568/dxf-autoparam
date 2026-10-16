"""A sheet as LOGICAL VIEWS: found, named and classified, without cutting anything out of the drawing.

A general arrangement sheet holds many drawings of one structure (elevations, sections, plans, details) next to
tables, notes, a title block and the frame. Each view is found as a cluster of geometry that white space or the
sheet's own panel rules separate from the others; it is then named from its title, typed from drafting words, and
given its own scale. A view is a list of entity indices of the ONE drawing: nothing is split, copied or lost.

    layout = segment(dr)                                  # frame, panel rules, views, tables, notes, title block
    sub, back = view_drawing(dr, layout.group("V03"))     # one view as a standalone Drawing + its indices on the sheet

How (generic drafting conventions only — no structure type, no values):
  FRAME       the smallest axis-aligned rectangle that holds nearly every entity (a double border is one frame);
              anything outside it is STRAY: kept, never parametrized
  RULES       long straight lines joined to the frame through other long lines (a notes column, the title block's
              rules): they part the sheet into panels, and views never grow across them
  WATERMARK   one text repeated across the sheet (a converter's stamp): noise
  ATOMS       the structural geometry rasterized on a grid; touching pieces are one atom
  GAPS        a wave grown from every atom at once meets the others: the white space between each pair is measured,
              and the view gap is read off those gaps (the drawing's own spacing, not a constant)
  ANNOTATION  dimensions join the view of the points they measure, leaders the view they point into, texts the
              nearest view in reach; what is left alone is notes
  KINDS       table (straight rules on a grid with words), notes (words), title block (its ownership words),
              view (geometry). A view's type comes from its title's words (plan, section, elevation, detail).
  SCALE       "SCALE 1:25" in the title; drawing units per view from the view's own dimensions
Anything unsure is said, not decided: two titles in one cluster, a view with no title, a view at another scale.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import statistics
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .ir import Drawing, Item, Role

TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}
VOCAB = json.loads((Path(__file__).parent / "knowledge" / "drafting.json").read_text())
SCALE_RE = re.compile(VOCAB["scale_pattern"], re.IGNORECASE)
NUMBER_ONLY = re.compile(r"^[\s\d.,:+\-xX×/()%°]*$")


def _words_re(words: list[str]) -> re.Pattern:
    return re.compile(r"(?<![A-Z])(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")(?![A-Z])", re.IGNORECASE)


TYPE_RE = {t: _words_re(ws) for t, ws in VOCAB["view_types"].items()}
TABLE_RE = _words_re(VOCAB["table_words"])
NOTES_RE = _words_re(VOCAB["notes_words"])
TITLE_BLOCK_RE = _words_re(VOCAB["title_block_words"])
NTS_RE = _words_re(VOCAB["not_to_scale"])


@dataclass
class Group:
    """A logical part of the sheet: a view, a table, a block of notes, the title block, or a stray label."""

    id: str
    kind: str  # view | table | notes | title_block | label
    items: list[int]
    bbox: tuple[float, float, float, float]
    name: str = ""
    view_type: str = "unknown"  # plan | section | elevation | detail | arrangement | composite | unknown
    view_types: list[str] = field(default_factory=list)
    titles: list[int] = field(default_factory=list)
    scale: float | None = None  # the stated drawing scale 1:N (None: not stated / not to scale)
    units_mm: float | None = None  # millimetres per drawing unit measured from its own dimensions (None: the sheet's)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    split: list[list[int]] = field(default_factory=list)  # a proposed split into views, when unsure
    counts: dict[str, int] = field(default_factory=dict)
    key: str = ""  # a content hash: the same entities give the same key in every session

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "name": self.name, "view_type": self.view_type, "view_types": self.view_types,
                "bbox": [round(v, 3) for v in self.bbox], "entities": len(self.items), "titles": self.titles, "scale": self.scale,
                "units_mm": self.units_mm, "confidence": round(self.confidence, 2), "evidence": self.evidence, "questions": self.questions,
                "split": [len(s) for s in self.split], "counts": self.counts, "key": self.key}


@dataclass
class SheetLayout:
    frame: tuple[float, float, float, float] | None
    frame_items: list[int]
    rules: list[int]  # panel rules (fixed; they part the sheet)
    stray: list[int]  # outside the frame
    watermark: list[int]
    groups: list[Group]
    cell: float  # raster cell, drawing units
    gap: float  # the white space that separates views on this sheet, drawing units
    gaps: list[float]  # every measured gap between geometry pieces (the evidence for `gap`)
    notes: list[str] = field(default_factory=list)
    item_group: dict[int, str] = field(default_factory=dict)

    def group(self, gid: str) -> Group:
        return next(g for g in self.groups if g.id == gid)

    def views(self) -> list[Group]:
        return [g for g in self.groups if g.kind == "view"]

    def furniture(self) -> list[int]:
        return sorted(set(self.frame_items) | set(self.rules) | set(self.stray) | set(self.watermark))

    def to_dict(self) -> dict:
        return {"frame": self.frame, "frame_items": len(self.frame_items), "rules": len(self.rules), "stray": len(self.stray),
                "watermark": len(self.watermark), "cell": self.cell, "gap": self.gap, "notes": self.notes,
                "groups": [g.to_dict() for g in self.groups]}


# ── geometry of an item, for the raster ──────────────────────────────────────────


def _bbox(pts) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def text_outline(it: Item) -> list[tuple[float, float]]:
    """A text's footprint: its words' rectangle (rotated), estimated from the height and the longest line, hung from its
    anchor the way CAD hangs it — an MTEXT by its attachment point (top / middle / bottom × left / centre / right), a
    TEXT by its alignment (baseline / bottom / middle / top × left / centre / right, aligned and fit across both points)."""
    h = it.text_height or 1.0
    lines = (it.text or "").split("\n") or [""]
    n = len(lines)
    w = 0.62 * h * max(1, max(len(s) for s in lines)) * float(it.extra.get("wf", 1.0) or 1.0)
    a = math.radians(it.extra.get("rotation", 0.0) or 0.0)
    ox, oy = it.pts[0]
    if it.dxftype == "MTEXT":
        k = min(max(int(it.extra.get("attach", 1) or 1), 1), 9) - 1
        col, row = k % 3, k // 3
        H = h + (n - 1) * 1.667 * h * float(it.extra.get("spacing", 1.0) or 1.0)
        x0 = (0.0, -w / 2, -w)[col]
        ylo, yhi = ((-H, 0.0), (-H / 2, H / 2), (0.0, H))[row]
        local = [(x0, ylo), (x0 + w, ylo), (x0 + w, yhi), (x0, yhi)]
    else:
        ha, va = int(it.extra.get("halign", 0) or 0), int(it.extra.get("valign", 0) or 0)
        if (ha or va) and len(it.pts) > 1:
            ox, oy = it.pts[1]
            if ha in (3, 5):  # aligned / fit: the text runs from the insertion point to the alignment point
                ox, oy = (it.pts[0][0] + it.pts[1][0]) / 2, (it.pts[0][1] + it.pts[1][1]) / 2
        x0 = -w / 2 if ha in (1, 3, 4, 5) else -w if ha == 2 else 0.0
        if ha == 4 or va == 2:
            ylo, yhi = -0.65 * h, 0.65 * h
        elif va == 3:
            ylo, yhi = -1.3 * h, 0.0
        elif va == 1:
            ylo, yhi = 0.0, 1.3 * h
        else:
            ylo, yhi = -0.2 * h, 1.1 * h
        local = [(x0, ylo), (x0 + w, ylo), (x0 + w, yhi), (x0, yhi)]
    ca, sa = math.cos(a), math.sin(a)
    return [(ox + x * ca - y * sa, oy + x * sa + y * ca) for x, y in local]


def item_lines(it: Item) -> list[list[tuple[float, float]]]:
    """The polylines that draw an item (for the raster and hit tests): straight geometry, curves flattened, a text's bounds."""
    t = it.dxftype
    if not it.pts:
        return []
    if t in TEXT_TYPES:
        b = text_outline(it)
        return [[*b, b[0]]]
    if t in ("LINE", "LEADER", "SOLID", "TRACE", "3DFACE"):
        return [list(it.pts)]
    if t in ("LWPOLYLINE", "POLYLINE"):
        return [list(it.pts) + ([it.pts[0]] if it.closed else [])]
    if t in ("CIRCLE", "ARC") and it.radius:
        c, r = it.pts[0], it.radius
        a0, a1 = (0.0, 360.0) if t == "CIRCLE" else (it.extra.get("start_angle", 0.0), it.extra.get("end_angle", 360.0))
        if a1 <= a0:
            a1 += 360.0
        n = max(8, int((a1 - a0) / 10))
        return [[(c[0] + r * math.cos(math.radians(a0 + (a1 - a0) * k / n)), c[1] + r * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]]
    if t == "HATCH":
        return [[*p, p[0]] for p in it.extra.get("polys", []) if len(p) >= 3]
    if it.display:
        return [list(d) for d in it.display if len(d) >= 2]
    return [[p] for p in it.pts]


def anchor_points(it: Item) -> list[tuple[float, float]]:
    """Where an annotation belongs: what a dimension measures, where a leader points, a text's middle."""
    t = it.dxftype
    if t == "DIMENSION" and len(it.pts) >= 3:
        return [it.pts[1], it.pts[2]]
    if t == "LEADER":
        return [it.pts[0]]
    if t in TEXT_TYPES:
        b = text_outline(it)
        return [((b[0][0] + b[2][0]) / 2, (b[0][1] + b[2][1]) / 2)]
    if t == "HATCH":
        polys = it.extra.get("polys") or []
        if polys and polys[0]:
            x0, y0, x1, y1 = _bbox(polys[0])
            return [((x0 + x1) / 2, (y0 + y1) / 2)]
    return list(it.pts[:1])


# ── the raster ───────────────────────────────────────────────────────────────────


class _Grid:
    def __init__(self, bounds: tuple[float, float, float, float], cell: float):
        self.x0, self.y0, self.cell = bounds[0], bounds[1], cell
        self.nx = math.ceil((bounds[2] - bounds[0]) / cell) + 1
        self.ny = math.ceil((bounds[3] - bounds[1]) / cell) + 1

    def cell_of(self, p) -> int | None:
        ix, iy = int((p[0] - self.x0) // self.cell), int((p[1] - self.y0) // self.cell)
        if 0 <= ix < self.nx and 0 <= iy < self.ny:
            return iy * self.nx + ix
        return None

    def cells(self, polys: list[list[tuple[float, float]]]) -> np.ndarray:
        """Every cell a polyline passes through (sampled at half a cell)."""
        out = []
        step = self.cell / 2
        for poly in polys:
            if len(poly) == 1:
                out.append(np.array([poly[0]]))
                continue
            for a, b in itertools.pairwise(poly):
                n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
                if n > 20000:  # a line far longer than the sheet (stray): its ends only
                    n = 1
                t = np.linspace(0.0, 1.0, n + 1)
                out.append(np.column_stack((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)))
        if not out:
            return np.zeros(0, dtype=np.int64)
        p = np.concatenate(out)
        ix = np.floor((p[:, 0] - self.x0) / self.cell).astype(np.int64)
        iy = np.floor((p[:, 1] - self.y0) / self.cell).astype(np.int64)
        ok = (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)
        return np.unique(iy[ok] * self.nx + ix[ok])


def _label(mask: np.ndarray, nx: int, four: bool = False) -> np.ndarray:
    """Connected components of the marked cells (8-connected, or 4-connected for open areas walled by lines, which
    must not leak through the corner where two lines cross): label per cell (-1 where unmarked)."""
    lab = np.full(mask.shape, -1, dtype=np.int64)
    ny = mask.size // nx
    steps = [(0, -1), (0, 1), (-1, 0), (1, 0)] if four else [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
    nxt = 0
    for start in np.flatnonzero(mask):
        if lab[start] >= 0:
            continue
        lab[start] = nxt
        q = deque([start])
        while q:
            c = q.popleft()
            cy, cx = divmod(c, nx)
            for dy, dx in steps:
                yy, xx = cy + dy, cx + dx
                if 0 <= yy < ny and 0 <= xx < nx:
                    n = yy * nx + xx
                    if mask[n] and lab[n] < 0:
                        lab[n] = nxt
                        q.append(n)
        nxt += 1
    return lab


def _wave(atom: np.ndarray, wall: np.ndarray, nx: int, reach: int) -> tuple[np.ndarray, np.ndarray, dict[tuple[int, int], int]]:
    """Grow every atom at once (one cell per step, never through a wall): each empty cell learns its nearest atom and
    the distance to it; where two waves meet, the white space between those atoms is measured (in cells)."""
    ny = atom.size // nx
    owner = atom.copy()
    dist = np.where(atom >= 0, 0, 1 << 30).astype(np.int64)
    q = deque(np.flatnonzero(atom >= 0).tolist())
    gaps: dict[tuple[int, int], int] = {}
    while q:
        c = q.popleft()
        a, d = owner[c], dist[c]
        cy, cx = divmod(c, nx)
        for dy in (-1, 0, 1):
            yy = cy + dy
            if yy < 0 or yy >= ny:
                continue
            for dx in (-1, 0, 1):
                xx = cx + dx
                if xx < 0 or xx >= nx or (dx == 0 and dy == 0):
                    continue
                n = yy * nx + xx
                if wall[n]:
                    continue
                o = owner[n]
                if o < 0:
                    if d < reach:
                        owner[n] = a
                        dist[n] = d + 1
                        q.append(n)
                elif o != a:
                    k = (a, o) if a < o else (o, a)
                    g = int(d + dist[n])
                    if g < gaps.get(k, 1 << 30):
                        gaps[k] = g
    return owner, dist, gaps


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a: int, b: int) -> bool:
        a, b = self.find(a), self.find(b)
        if a == b:
            return False
        self.p[b] = a
        return True


# ── the sheet ────────────────────────────────────────────────────────────────────


def _rect(it: Item) -> tuple[float, float, float, float] | None:
    """The bounds of an axis-aligned rectangle drawn as one closed polyline."""
    if it.dxftype not in ("LWPOLYLINE", "POLYLINE") or len(it.pts) < 4:
        return None
    pts = list(it.pts)
    if math.dist(pts[0], pts[-1]) < 1e-9:
        pts = pts[:-1]
    if len(pts) != 4 or not (it.closed or len(it.pts) == 5):
        return None
    x0, y0, x1, y1 = _bbox(pts)
    tol = 1e-3 * max(x1 - x0, y1 - y0, 1e-9)
    if all(min(abs(p[0] - x0), abs(p[0] - x1)) < tol and min(abs(p[1] - y0), abs(p[1] - y1)) < tol for p in pts):
        return x0, y0, x1, y1
    return None


def _robust_bounds(items: list[Item]) -> tuple[float, float, float, float]:
    xs = sorted(p[0] for it in items for p in it.pts)
    ys = sorted(p[1] for it in items for p in it.pts)
    n = len(xs)
    lo, hi = int(0.003 * n), max(0, int(0.997 * n) - 1)
    return xs[lo], ys[lo], xs[hi], ys[hi]


def _frame(dr: Drawing, centres: dict[int, tuple[float, float]]) -> tuple[tuple | None, list[int]]:
    """The sheet frame: the outermost rectangle that holds nearly every entity, and every border line on it."""
    items = [it for it in dr.items if it.pts]
    if not items:
        return None, []
    rx0, ry0, rx1, ry1 = _robust_bounds(items)
    area = max((rx1 - rx0) * (ry1 - ry0), 1e-9)
    rects = [(it.index, r) for it in items if (r := _rect(it)) and (r[2] - r[0]) * (r[3] - r[1]) > 0.25 * area]
    n = len(centres)
    best = None
    for idx, r in rects:
        inside = sum(1 for i, c in centres.items() if i != idx and r[0] <= c[0] <= r[2] and r[1] <= c[1] <= r[3])
        if inside >= 0.8 * n and (best is None or (r[2] - r[0]) * (r[3] - r[1]) > (best[2] - best[0]) * (best[3] - best[1])):
            best = r
    if best is None:  # border drawn as loose lines: the reader already holds them fixed
        fixed = [it for it in items if it.role == Role.FIXED and len(it.pts) >= 2]
        if not fixed:
            return None, []
        best = _bbox([p for it in fixed for p in it.pts])
    W, H = best[2] - best[0], best[3] - best[1]
    tol = 0.02 * max(W, H)
    frame_items = []
    for it in items:
        if it.dxftype not in ("LINE", "LWPOLYLINE", "POLYLINE") or len(it.pts) < 2:
            continue
        x0, y0, x1, y1 = _bbox(it.pts)
        near = lambda v, w: abs(v - w) < tol
        whole = (x1 - x0) > 0.6 * W and (y1 - y0) > 0.6 * H
        hside = (x1 - x0) > 0.6 * W and (y1 - y0) < tol and (near(y0, best[1]) or near(y1, best[3]))
        vside = (y1 - y0) > 0.6 * H and (x1 - x0) < tol and (near(x0, best[0]) or near(x1, best[2]))
        if whole or hside or vside:
            frame_items.append(it.index)
    return best, frame_items


def _segments(it: Item) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    pts = list(it.pts)
    if it.dxftype in ("LINE",) and len(pts) >= 2:
        return [(pts[0], pts[1])]
    if it.dxftype in ("LWPOLYLINE", "POLYLINE") and not any(abs(b) > 1e-9 for b in it.bulges):
        segs = list(itertools.pairwise(pts))
        if it.closed and len(pts) > 2:
            segs.append((pts[-1], pts[0]))
        return segs
    return []


def _rules(dr: Drawing, frame: tuple, frame_items: list[int], skip: set[int]) -> list[int]:
    """Panel rules: long straight lines (or whole outlines made of them) joined to the frame through other long lines.
    A centre or axis line is never one: it is a construction axis that runs THROUGH a drawing (a track's centre line
    ends near the sheet's margin like an inner border does), while a rule parts the sheet and nothing is drawn across it."""
    W, H = frame[2] - frame[0], frame[3] - frame[1]
    tol = 0.004 * max(W, H)
    longs: dict[int, list] = {}
    for it in dr.items:
        if it.index in skip or it.index in frame_items or it.dxftype not in ("LINE", "LWPOLYLINE", "POLYLINE"):
            continue
        if it.role == Role.REFERENCE:
            continue
        segs = _segments(it)
        if not segs:
            continue
        ok = []
        for a, b in segs:
            if abs(a[1] - b[1]) < tol and abs(a[0] - b[0]) > 0.1 * W or abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) > 0.1 * H:
                ok.append((a, b))
        if ok and len(ok) == len(segs):  # every edge long and straight: a rule, or a panel drawn as one outline
            longs[it.index] = ok

    def on(p, seg) -> bool:
        (a, b) = seg
        if abs(a[1] - b[1]) < tol:  # horizontal
            return abs(p[1] - a[1]) < tol and min(a[0], b[0]) - tol <= p[0] <= max(a[0], b[0]) + tol
        return abs(p[0] - a[0]) < tol and min(a[1], b[1]) - tol <= p[1] <= max(a[1], b[1]) + tol

    fx0, fy0, fx1, fy1 = frame
    border = [((fx0, fy0), (fx1, fy0)), ((fx1, fy0), (fx1, fy1)), ((fx1, fy1), (fx0, fy1)), ((fx0, fy1), (fx0, fy0))]
    for idx in frame_items:
        border.extend(_segments(dr.items[idx]))
    # inner borders sit a little inside the outer one: an end within 2 % of the frame touches it
    near_frame = 0.02 * max(W, H)
    joined: set[int] = set()
    anchors = list(border)
    changed = True
    while changed:
        changed = False
        for idx, segs in longs.items():
            if idx in joined:
                continue
            ends = [p for s in segs for p in s]
            touch = any(on(p, s) for p in ends for s in anchors) or any(
                min(abs(p[0] - fx0), abs(p[0] - fx1), abs(p[1] - fy0), abs(p[1] - fy1)) < near_frame for p in ends)
            if touch:
                joined.add(idx)
                anchors.extend(segs)
                changed = True
    return sorted(joined)


def _watermark(dr: Drawing, frame: tuple) -> list[int]:
    """One text repeated across the sheet (a converter's or a vendor's stamp) is noise. Numbers repeat by design and
    are never a watermark; neither is a short label."""
    W, H = frame[2] - frame[0], frame[3] - frame[1]
    by_text: dict[str, list[Item]] = defaultdict(list)
    for it in dr.items:
        if it.dxftype in TEXT_TYPES and it.text:
            key = re.sub(r"\s+", " ", it.text.strip().upper())
            if len(key) >= 6 and not NUMBER_ONLY.match(key):
                by_text[key].append(it)
    out = []
    for its in by_text.values():
        if len(its) < 4:
            continue
        xs = [it.pts[0][0] for it in its]
        ys = [it.pts[0][1] for it in its]
        if max(xs) - min(xs) > 0.4 * W or max(ys) - min(ys) > 0.4 * H:
            out.extend(it.index for it in its)
    # a layer holding nothing but such texts is the stamp's layer: all of it goes
    if out:
        layers = Counter(dr.items[i].layer for i in out)
        for lay, n in layers.items():
            on_layer = [it.index for it in dr.items if it.layer == lay]
            if all(dr.items[i].dxftype in TEXT_TYPES for i in on_layer) and n >= 0.5 * len(on_layer):
                out.extend(on_layer)
    return sorted(set(out))


def _type_of(text: str) -> list[str]:
    """The drafting view types a title names, in the order its words come."""
    hits = []
    for t, rx in TYPE_RE.items():
        for m in rx.finditer(text):
            hits.append((m.start(), t))
    seen, out = set(), []
    for _p, t in sorted(hits):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _primary(types: list[str], text: str) -> str:
    if not types:
        return "unknown"
    if len(types) > 1 and re.search(r"\bHALF\b", text, re.IGNORECASE) and {"section", "elevation"} <= set(types):
        return "composite"
    # the noun comes last ("SECTIONAL ELEVATION" is an elevation; "SECTION OF TOE WALL" a section)
    last = max(types, key=lambda t: max(m.start() for m in TYPE_RE[t].finditer(text)))
    return last


def _clean_title(text: str) -> str:
    """A title without its scale line; brackets that belong to the name (a section mark) are kept."""
    t = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    t = re.sub(r"\(\s*" + VOCAB["scale_pattern"] + r"\s*\)", "", t, flags=re.IGNORECASE)
    t = re.sub(VOCAB["scale_pattern"], "", t, flags=re.IGNORECASE).strip(" -:,")
    while t.endswith("(") or (t.endswith(")") and t.count(")") > t.count("(")):
        t = t[:-1].rstrip(" -:,")
    while t.startswith(")") or (t.startswith("(") and t.count("(") > t.count(")")):
        t = t[1:].lstrip(" -:,")
    if t.count("(") > t.count(")"):
        t += ")"
    return t


def _title_candidates(dr: Drawing, skip: set[int]) -> list[Item]:
    """Texts that title a view: they name a view type and are not the title block's, a table's or a note's words."""
    out = []
    for it in dr.items:
        if it.index in skip or it.dxftype not in TEXT_TYPES or not it.text:
            continue
        text = it.text.strip()
        if len(text) > 90 or not _type_of(text) or TITLE_BLOCK_RE.search(text):
            continue
        if NOTES_RE.search(text) and not re.search(r"\b(SECTION|ELEVATION|PLAN)\b", text, re.IGNORECASE):
            continue
        out.append(it)
    return out


LINE_TYPES = ("LINE", "LWPOLYLINE", "POLYLINE", "LEADER")


def _clips(px, py, qx, qy, x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    """Which of the segments (p→q, as arrays) meet the rectangle [x0,x1]×[y0,y1] (Liang–Barsky, all at once)."""
    dx, dy = qx - px, qy - py
    t0, t1 = np.zeros_like(px), np.ones_like(px)
    alive = np.ones(px.shape, dtype=bool)
    for p, q in ((-dx, px - x0), (dx, x1 - px), (-dy, py - y0), (dy, y1 - py)):
        parallel = np.abs(p) < 1e-12
        alive &= ~(parallel & (q < 0))
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where(parallel, 0.0, q / np.where(parallel, 1.0, p))
        t0 = np.where(~parallel & (p < 0), np.maximum(t0, r), t0)
        t1 = np.where(~parallel & (p > 0), np.minimum(t1, r), t1)
    return alive & (t0 <= t1)


def _local(o, u, v, x, y):
    """Coordinates (x, y) in a text's own frame: origin at its lower-left corner, u along the words, v up."""
    return (x - o[0]) * u[0] + (y - o[1]) * u[1], (x - o[0]) * v[0] + (y - o[1]) * v[1]


def _drawn_labels(dr: Drawing, texts: list[Item], skip: set[int]) -> tuple[set[int], set[int]]:
    """Texts that may belong to a drawing rather than title one — a title stands on clear paper, beside its view.
      · CALLOUTS: the text rests on a leader's landing (the leader points from it to what it names). Never a title.
      · EMBEDDED: lines of the drawing run THROUGH the text (a cut label on a centre line, a level on a datum). That is
        evidence, not proof — a view's own axis may run through its real title — so such a text only ranks behind any
        title that is not crossed. Lines that end at a title, or underline it, do not count.
    (callout indices, embedded indices)"""
    segs: list[tuple[float, float, float, float]] = []
    landings: list[tuple[float, float, float, float, float, float]] = []  # a leader's last leg (from, to) and its tip
    for it in dr.items:
        if it.index in skip or it.dxftype not in LINE_TYPES or it.role == Role.FIXED or len(it.pts) < 2:
            continue
        for a, b in itertools.pairwise(it.pts):
            segs.append((a[0], a[1], b[0], b[1]))
        if it.dxftype == "LEADER":
            landings.append((*it.pts[-2], *it.pts[-1], *it.pts[0]))
    if not texts or (not segs and not landings):
        return set(), set()
    arr = np.array(segs, dtype=float).reshape(-1, 4)
    leg = np.array(landings, dtype=float).reshape(-1, 6)
    callouts: set[int] = set()
    embedded: set[int] = set()
    for t in texts:
        c = text_outline(t)
        o = np.array(c[0])
        u, v = np.array(c[1]) - o, np.array(c[3]) - o
        w, hb = float(np.hypot(*u)), float(np.hypot(*v))
        if w < 1e-9 or hb < 1e-9:
            continue
        u, v = u / w, v / hb
        h = t.text_height or hb
        if leg.size:
            m = 0.6 * h  # the landing runs under (or through) the words, a few tenths of a height off them
            ax, ay = _local(o, u, v, leg[:, 0], leg[:, 1])
            bx, by = _local(o, u, v, leg[:, 2], leg[:, 3])
            tx, ty = _local(o, u, v, leg[:, 4], leg[:, 5])
            on_words = _clips(ax, ay, bx, by, -m, -m, w + m, hb + m)
            points_away = ~((tx >= -1.5 * h) & (tx <= w + 1.5 * h) & (ty >= -1.5 * h) & (ty <= hb + 1.5 * h))
            if (on_words & points_away).any():
                callouts.add(t.index)
                continue
        if not arr.size:
            continue
        px, py = _local(o, u, v, arr[:, 0], arr[:, 1])
        qx, qy = _local(o, u, v, arr[:, 2], arr[:, 3])
        core = _clips(px, py, qx, qy, 0.08 * w, 0.2 * hb, 0.92 * w, 0.8 * hb)  # the middle of the words, clear of a baseline rule
        outside = ~(((px >= 0) & (px <= w) & (py >= 0) & (py <= hb)) | ((qx >= 0) & (qx <= w) & (qy >= 0) & (qy <= hb)))
        if (core & outside).any():
            embedded.add(t.index)
    return callouts, embedded


def _above(it: Item, k: float) -> tuple[float, float]:
    """A point k text heights 'above' a text in its own frame (a rotated title stands beside its view)."""
    b = text_outline(it)
    cx, cy = (b[0][0] + b[2][0]) / 2, (b[0][1] + b[2][1]) / 2
    a = math.radians(it.extra.get("rotation", 0.0) or 0.0)
    h = it.text_height or 1.0
    return cx - math.sin(a) * k * h, cy + math.cos(a) * k * h


def _title_rays(t: Item, grid2d: np.ndarray, g: _Grid, find) -> list[tuple[float, int, int]]:
    """Candidate pieces for a title: cast straight 'up' and 'down' from it (in its own frame) across its width, and
    note the first two pieces met each way: (cost, piece, side). A view usually stands over its title, a table hangs
    under its heading — the other way round costs 1.6×."""
    b = text_outline(t)
    x0, y0, x1, y1 = _bbox(b)
    h = t.text_height or g.cell
    rot = (t.extra.get("rotation", 0.0) or 0.0) % 360
    vertical = 45 < rot % 180 < 135
    c0 = max(0, int((x0 - g.x0) // g.cell))
    c1 = min(g.nx - 1, int((x1 - g.x0) // g.cell))
    r0 = max(0, int((y0 - g.y0) // g.cell))
    r1 = min(g.ny - 1, int((y1 - g.y0) // g.cell))
    limit = max(4, int(20 * h / g.cell))
    tabular = bool(TABLE_RE.search(t.text or ""))
    out = []
    for sign in (1, -1):
        seen: set[int] = set()
        weight = (1.6 if sign > 0 else 1.0) if tabular else (1.0 if sign > 0 else 1.6)
        for step in range(1, limit + 1):
            if vertical:  # the text's 'up' is the sheet's left (rotated 90°) or right (270°)
                col = (c0 - step if rot < 180 else c1 + step) if sign > 0 else (c1 + step if rot < 180 else c0 - step)
                if col < 0 or col >= g.nx:
                    break
                line = grid2d[r0: r1 + 1, col]
            else:
                row = r1 + step if sign > 0 else r0 - step
                if row < 0 or row >= g.ny:
                    break
                line = grid2d[row, c0: c1 + 1]
            for a in {int(v) for v in line[line >= 0]}:
                pc = find(a)
                if pc not in seen:
                    seen.add(pc)
                    out.append((step * weight, pc, sign))
            if len(seen) >= 2:
                break
    return out


def _underlines(dr: Drawing, titles: list[Item]) -> dict[int, int]:
    """Lines that underline a title (just under its words, about as long): part of the title, not of the drawing."""
    out: dict[int, int] = {}
    flat = [it for it in dr.items if it.dxftype in ("LINE", "LWPOLYLINE") and len(it.pts) == 2 and abs(it.pts[0][1] - it.pts[1][1]) < 1e-6]
    flat.sort(key=lambda it: it.pts[0][1])
    ys = [it.pts[0][1] for it in flat]
    for t in titles:
        if (t.extra.get("rotation", 0.0) or 0.0) % 180:
            continue
        x0, y0, x1, _y1 = _bbox(text_outline(t))
        h = t.text_height or 1.0
        k = np.searchsorted(ys, y0 - 1.5 * h)
        while k < len(flat) and ys[k] <= y0 + 0.4 * h:
            ln = flat[k]
            lx0, lx1 = sorted((ln.pts[0][0], ln.pts[1][0]))
            w = x1 - x0
            if lx1 - lx0 >= 0.4 * w and lx1 - lx0 <= 1.6 * w and lx0 <= x0 + 0.5 * w and lx1 >= x1 - 0.5 * w:
                out[ln.index] = t.index
            k += 1
    return out


def segment(dr: Drawing, grid: int = 800, trace: list | None = None) -> SheetLayout:
    items = dr.items
    notes: list[str] = []
    centres: dict[int, tuple[float, float]] = {}
    for it in items:
        if it.pts:
            x0, y0, x1, y1 = _bbox(it.pts)
            centres[it.index] = ((x0 + x1) / 2, (y0 + y1) / 2)
    if not centres:
        return SheetLayout(None, [], [], [], [], [], 1.0, 0.0, [], ["empty drawing"])
    frame, frame_items = _frame(dr, centres)
    work = frame if frame else _robust_bounds([it for it in items if it.pts])
    W, H = max(work[2] - work[0], 1e-9), max(work[3] - work[1], 1e-9)
    if frame:
        notes.append(f"sheet frame {W:.0f} × {H:.0f} drawing units ({len(frame_items)} border item(s))")
    m = 0.01 * max(W, H)
    stray = sorted(i for i, c in centres.items() if not (work[0] - m <= c[0] <= work[2] + m and work[1] - m <= c[1] <= work[3] + m))
    if stray:
        notes.append(f"{len(stray)} entit(ies) lie outside the sheet: kept, not part of any view")
    watermark = _watermark(dr, work)
    if watermark:
        notes.append(f"{len(watermark)} repeated stamp text(s) treated as a watermark")
    skip = set(stray) | set(watermark) | set(frame_items)
    rules = _rules(dr, work, frame_items, skip) if frame else []
    if rules:
        notes.append(f"{len(rules)} panel rule(s) part the sheet into panels")
    skip |= set(rules)

    candidates = _title_candidates(dr, skip)
    callouts, embedded = _drawn_labels(dr, candidates, skip)
    titles = [t for t in candidates if t.index not in callouts]
    if callouts:
        notes.append(f"{len(callouts)} text(s) with view words sit on a leader: callouts of a drawing, not titles")
    underline = _underlines(dr, titles)
    cell = max(W, H) / grid
    g = _Grid((work[0] - cell, work[1] - cell, work[2] + cell, work[3] + cell), cell)
    wall = np.zeros(g.nx * g.ny, dtype=bool)
    for i in frame_items + rules:
        wall[g.cells(item_lines(items[i]))] = True
    geom_cells: dict[int, np.ndarray] = {}
    occ = np.zeros(g.nx * g.ny, dtype=bool)
    for it in items:
        if it.index in skip or not it.pts or it.anchor is not None:
            continue
        if it.role in (Role.STRUCTURAL, Role.REFERENCE) and it.dxftype not in TEXT_TYPES and it.index not in underline:
            c = g.cells(item_lines(it))
            c = c[~wall[c]]
            if c.size:
                geom_cells[it.index] = c
                occ[c] = True
    atom = _label(occ, g.nx)
    n_atoms = int(atom.max()) + 1 if atom.size and atom.max() >= 0 else 0
    reach = max(4, round(0.05 * max(g.nx, g.ny)))
    owner, dist, pair_gaps = _wave(atom, wall, g.nx, reach)

    # the atoms' extents and sizes (cells)
    cells_at = np.flatnonzero(atom >= 0)
    lab = atom[cells_at]
    cy, cx = np.divmod(cells_at, g.nx)
    a_count = np.bincount(lab, minlength=n_atoms).astype(np.int64)
    a_bounds = np.zeros((n_atoms, 4), dtype=np.int64)
    a_bounds[:, 0] = np.iinfo(np.int64).max
    a_bounds[:, 1] = np.iinfo(np.int64).max
    np.minimum.at(a_bounds[:, 0], lab, cx)
    np.minimum.at(a_bounds[:, 1], lab, cy)
    np.maximum.at(a_bounds[:, 2], lab, cx)
    np.maximum.at(a_bounds[:, 3], lab, cy)

    # each atom's set-out coordinates (its vertices' x and y, to a quarter cell)
    q4 = cell / 4
    a_xs: dict[int, set[int]] = defaultdict(set)
    a_ys: dict[int, set[int]] = defaultdict(set)
    for idx, c in geom_cells.items():
        labs = atom[c]
        labs = labs[labs >= 0]
        if not labs.size:
            continue
        a = int(np.bincount(labs).argmax())
        it = items[idx]
        for k in it.vertex_pts or range(len(it.pts)):
            a_xs[a].add(round(it.pts[k][0] / q4))
            a_ys[a].add(round(it.pts[k][1] / q4))

    # PIECES: geometry closer than a tight gap (half a percent of the sheet) is one piece
    g0 = max(2, round(0.005 * max(g.nx, g.ny)))
    uf = _UF(n_atoms)
    merges = []
    for (a, b), w in sorted(pair_gaps.items(), key=lambda kv: kv[1]):
        if uf.union(a, b):
            merges.append(w)
    uf = _UF(n_atoms)
    for (a, b), w in pair_gaps.items():
        if w <= g0:
            uf.union(a, b)

    # TITLES anchor views
    # each title to one piece, cheapest first; a piece takes a second title only beside its first (halves of a figure)
    grid2d = atom.reshape(g.ny, g.nx)
    pairs = []
    for t in titles:
        for cost, pc, side in _title_rays(t, grid2d, g, uf.find):
            pairs.append((cost, t.index, pc, side))
    pairs.sort(key=lambda x: (x[0], x[1]))
    title_piece: dict[int, int] = {}
    piece_title: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for _cost, ti, pc, side in pairs:
        if ti in title_piece:
            continue
        if piece_title[pc]:
            t0, side0 = piece_title[pc][0]
            h = items[ti].text_height or cell
            y_new, y_old = _bbox(text_outline(items[ti]))[1], _bbox(text_outline(items[t0]))[1]
            if side != side0 or abs(y_new - y_old) > 2.5 * h:
                continue
        title_piece[ti] = pc
        piece_title[pc].append((ti, side))
    title_atom = dict(title_piece)  # a piece's root is one of its atoms

    class P:  # a piece of the sheet being assembled into a view
        __slots__ = ("atoms", "bounds", "count", "titles", "xs", "ys")

        def __init__(self):
            self.atoms: list[int] = []
            self.bounds = [1 << 60, 1 << 60, -(1 << 60), -(1 << 60)]
            self.count = 0
            self.titles: set[int] = set()
            self.xs: set[int] = set()
            self.ys: set[int] = set()

    pieces: dict[int, P] = {}
    for a in range(n_atoms):
        r = uf.find(a)
        p = pieces.get(r)
        if p is None:
            p = pieces[r] = P()
        p.atoms.append(a)
        p.count += int(a_count[a])
        p.xs |= a_xs.get(a, set())
        p.ys |= a_ys.get(a, set())
        b = a_bounds[a]
        p.bounds = [min(p.bounds[0], b[0]), min(p.bounds[1], b[1]), max(p.bounds[2], b[2]), max(p.bounds[3], b[3])]
    for ti, a in title_atom.items():
        pieces[uf.find(a)].titles.add(ti)
    # gaps between pieces
    pgap: dict[tuple[int, int], int] = {}
    for (a, b), w in pair_gaps.items():
        ra, rb = uf.find(a), uf.find(b)
        if ra != rb:
            k = (ra, rb) if ra < rb else (rb, ra)
            if w < pgap.get(k, 1 << 30):
                pgap[k] = w
    nbrs: dict[int, dict[int, int]] = defaultdict(dict)
    for (a, b), w in pgap.items():
        nbrs[a][b] = w
        nbrs[b][a] = w

    def inside_frac(p: P, q: P, pad: int) -> float:
        """How much of p lies within q's extent (by its atoms' middles, weighted by size)."""
        x0, y0, x1, y1 = q.bounds[0] - pad, q.bounds[1] - pad, q.bounds[2] + pad, q.bounds[3] + pad
        tot = inn = 0
        for a in p.atoms:
            b = a_bounds[a]
            n = int(a_count[a])
            tot += n
            if x0 <= (b[0] + b[2]) / 2 <= x1 and y0 <= (b[1] + b[3]) / 2 <= y1:
                inn += n
        return inn / max(tot, 1)

    def extent(p: P) -> int:
        return max(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) + 1

    # MERGE: a piece lying mostly inside a bigger piece's extent (a section's level lines, the parts of a figure), or a
    # small satellite close to one (a dimension chain, a mark), belongs to it — never across two different titles
    if trace is not None:
        for r, p in pieces.items():
            if p.count >= 20:
                trace.append(
                    {
                        "piece": r,
                        "count": p.count,
                        "bounds": [
                            (
                                round(g.x0 + v * cell)
                                if k % 2 == 0
                                else round(g.y0 + v * cell)
                            )
                            for k, v in enumerate(p.bounds)
                        ],
                        "titles": [(items[i].text or "")[:40] for i in p.titles],
                    }
                )
    changed = True
    while changed:
        changed = False
        for r in sorted(pieces, key=lambda r: pieces[r].count):
            p = pieces.get(r)
            if p is None:
                continue
            best = None
            mx, my = (p.bounds[0] + p.bounds[2]) / 2, (p.bounds[1] + p.bounds[3]) / 2
            cands = dict(nbrs.get(r, {}))
            for s, q in pieces.items():  # pieces whose extent holds this one, touching or not
                if s != r and s not in cands and q.bounds[0] - g0 <= mx <= q.bounds[2] + g0 and q.bounds[1] - g0 <= my <= q.bounds[3] + g0:
                    cands[s] = 1 << 30
            for s, w in cands.items():
                q = pieces.get(s)
                if q is None or q.count < p.count or (p.titles and q.titles and p.titles != q.titles):
                    continue
                ix = max(0, min(p.bounds[2], q.bounds[2]) - max(p.bounds[0], q.bounds[0]) + 1) * max(0, min(p.bounds[3], q.bounds[3]) - max(p.bounds[1], q.bounds[1]) + 1)
                pa = (p.bounds[2] - p.bounds[0] + 1) * (p.bounds[3] - p.bounds[1] + 1)
                contained = (inside_frac(p, q, g0) >= 0.6 and (w <= 8 * g0 or inside_frac(p, q, 0) >= 0.95)) or (pa >= 16 and ix >= 0.5 * pa)
                satellite = w <= 3 * g0 and extent(p) <= 0.6 * extent(q) and p.count <= 0.2 * q.count
                # a titled piece right next to an untitled one: the title names the whole drawing
                titled_part = bool(p.titles) and not q.titles and w <= 2 * g0
                # a thin piece set out on the other's lines: its dimension chain, its level lines
                bw, bh = p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]
                along = p.xs if bh <= max(2, 0.05 * bw) else p.ys if bw <= max(2, 0.05 * bh) else None
                aligned = (along is not None and len(along) >= 2 and w <= 8 * g0
                           and len(along & (q.xs if along is p.xs else q.ys)) >= 0.6 * len(along))
                if contained or satellite or titled_part or aligned:
                    score = (contained, -w, q.count)
                    if best is None or score > best[0]:
                        best = (score, s)
            if best is None:
                continue
            s = best[1]
            q = pieces[s]
            q.atoms.extend(p.atoms)
            q.count += p.count
            q.bounds = [min(q.bounds[0], p.bounds[0]), min(q.bounds[1], p.bounds[1]), max(q.bounds[2], p.bounds[2]), max(q.bounds[3], p.bounds[3])]
            q.titles |= p.titles
            q.xs |= p.xs
            q.ys |= p.ys
            del pieces[r]
            for t, w in nbrs.pop(r, {}).items():
                nbrs[t].pop(r, None)
                if t != s and w < nbrs[s].get(t, 1 << 30):
                    nbrs[s][t] = w
                    nbrs[t][s] = w
            changed = True
    piece_of_atom = np.full(n_atoms, -1, dtype=np.int64)
    for r, p in pieces.items():
        piece_of_atom[p.atoms] = r

    members: dict[int, list[int]] = defaultdict(list)
    for idx, c in geom_cells.items():
        labs = atom[c]
        labs = labs[labs >= 0]
        if labs.size:
            members[int(piece_of_atom[int(np.bincount(labs).argmax())])].append(idx)

    # ANNOTATION joins the view of what it marks, within reach: three tight gaps, or — dimensions are placed a few text
    # heights off what they measure — eight of the sheet's text heights, whichever is more (four of its own for a word)
    hs_all = [it.text_height for it in items if it.dxftype in TEXT_TYPES and it.text_height and it.index not in skip]
    med_h = statistics.median(hs_all) if hs_all else 0.0
    annot_reach = max(3 * g0, int(8 * med_h / cell))
    # The wave above stops at 5% of the sheet; an annotation may stand further off what it marks (eight text heights).
    # A coarse grid of geometry cells, with each coarse cell's nearest geometry found once (a breadth-first sweep from every
    # geometry cell at once), lets such an annotation find its nearest geometry in constant time, within its own reach.
    coarse = 8
    cnx, cny = g.nx // coarse + 1, g.ny // coarse + 1
    coarse_cells: dict[int, list[int]] = defaultdict(list)
    for cidx in np.flatnonzero(atom >= 0).tolist():
        cyy, cxx = divmod(cidx, g.nx)
        coarse_cells[(cyy // coarse) * cnx + cxx // coarse].append(cidx)
    nearest_coarse = np.full(cnx * cny, -1, dtype=np.int64)
    frontier = deque()
    for key in coarse_cells:
        nearest_coarse[key] = key
        frontier.append(key)
    while frontier:
        key = frontier.popleft()
        ky, kx = divmod(key, cnx)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yy, xx = ky + dy, kx + dx
                if 0 <= yy < cny and 0 <= xx < cnx and nearest_coarse[yy * cnx + xx] < 0:
                    nearest_coarse[yy * cnx + xx] = nearest_coarse[key]
                    frontier.append(yy * cnx + xx)

    def near_atom(points, limit_cells: int) -> tuple[int, int] | None:
        found = None
        for pnt in points:
            c = g.cell_of(pnt)
            if c is None:
                continue
            py, px = divmod(c, g.nx)
            key = (py // coarse) * cnx + px // coarse
            src = int(nearest_coarse[key]) if 0 <= key < nearest_coarse.size else -1
            if src < 0:
                continue
            for h_ in coarse_cells[src]:
                hy, hx = divmod(h_, g.nx)
                d = max(abs(hx - px), abs(hy - py))
                if d <= limit_cells and (found is None or d < found[1]):
                    found = (int(piece_of_atom[int(atom[h_])]), d)
        return found

    loose: list[int] = []
    for it in items:
        if it.index in skip or it.index in geom_cells or not it.pts or it.anchor is not None:
            continue
        pts = anchor_points(it)
        if it.dxftype in TEXT_TYPES:
            b = text_outline(it)
            pts = pts + b + [((b[k][0] + b[(k + 1) % 4][0]) / 2, (b[k][1] + b[(k + 1) % 4][1]) / 2) for k in range(4)]
        limit = annot_reach
        if it.dxftype in TEXT_TYPES and it.text_height:
            limit = max(limit, int(4 * it.text_height / cell))
        best = None
        for pnt in pts:
            c = g.cell_of(pnt)
            if c is None or owner[c] < 0 or dist[c] > limit:
                continue
            if best is None or dist[c] < best[1]:
                best = (int(piece_of_atom[int(owner[c])]), int(dist[c]))
        if best is None:  # beyond the wave's reach but within the annotation's: the nearest geometry, found directly
            best = near_atom(pts, limit)
        if it.index in title_atom:  # a title goes with the view it titles, its underline with it
            best = (int(piece_of_atom[title_atom[it.index]]), 0)
        elif underline.get(it.index) in title_atom:
            best = (int(piece_of_atom[title_atom[underline[it.index]]]), 0)
        if best is None:
            loose.append(it.index)
        else:
            members[best[0]].append(it.index)
    for it in items:  # a rigid symbol's parts go where its insertion point went
        if it.anchor is not None and it.index not in skip:
            for mem in members.values():
                if it.anchor in mem:
                    mem.append(it.index)
                    break
            else:
                loose.append(it.index)

    # loose words. Words in a GRID of small walled panels (a table or a title block drawn with the frame's own rules)
    # are one group; the rest are paragraphs of notes and labels, grouped by closeness, never across a rule.
    groups_raw: list[tuple[list[int], str | None]] = [(sorted(v), None) for v in members.values()]
    if loose:
        panel = _label(~wall, g.nx, four=True)
        n_pan = int(panel.max()) + 1 if panel.size and panel.max() >= 0 else 0
        area = np.bincount(panel[panel >= 0], minlength=n_pan)
        small = area < 0.04 * max(1, int((panel >= 0).sum()))
        pan_uf = _UF(n_pan)
        wy, wx = np.divmod(np.flatnonzero(wall), g.nx)
        for dy, dx in ((0, 1), (1, 0)):  # a one-cell wall between two small panels makes them neighbours
            ya, xa, yb, xb = wy - dy, wx - dx, wy + dy, wx + dx
            ok = (ya >= 0) & (xa >= 0) & (yb < g.ny) & (xb < g.nx)
            la, lb = panel[ya[ok] * g.nx + xa[ok]], panel[yb[ok] * g.nx + xb[ok]]
            both = (la >= 0) & (lb >= 0) & (la != lb)
            for a, b in zip(la[both].tolist(), lb[both].tolist()):
                if small[a] and small[b]:
                    pan_uf.union(a, b)
        boxes = {i: _bbox([p for line in item_lines(items[i]) for p in line] or items[i].pts) for i in loose}
        pan = {}
        for i in loose:
            b = boxes[i]
            c = g.cell_of(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
            pan[i] = int(panel[c]) if c is not None and panel[c] >= 0 else -1
        grids: dict[int, list[int]] = defaultdict(list)
        for i in loose:
            if pan[i] >= 0 and small[pan[i]]:
                grids[pan_uf.find(pan[i])].append(i)
        in_grid: set[int] = set()
        for its in grids.values():
            cells_used = {pan[i] for i in its}
            if len(cells_used) < 4 or len(its) < 4:
                continue
            words = " ".join(items[i].text or "" for i in its)
            xs = sorted({round(boxes[i][0] / (8 * cell)) for i in its})
            ys = sorted({round(boxes[i][1] / (4 * cell)) for i in its})
            if len({m.group(0).upper() for m in TITLE_BLOCK_RE.finditer(words)}) >= 3:
                kind = "title_block"
            elif len(xs) >= 2 and len(ys) >= 3:
                kind = "table"
            else:
                kind = "notes"
            groups_raw.append((sorted(its), kind))
            in_grid.update(its)
        rest = [i for i in loose if i not in in_grid]
        hs = [items[i].text_height or 0 for i in rest if items[i].text_height]
        reachw = 2.5 * (statistics.median(hs) if hs else cell * 3)
        ufl = _UF(len(rest))
        order = sorted(range(len(rest)), key=lambda k: boxes[rest[k]][0])
        active: list[int] = []
        for k in order:
            b = boxes[rest[k]]
            active = [j for j in active if boxes[rest[j]][2] + reachw >= b[0]]
            for j in active:
                o = boxes[rest[j]]
                if pan[rest[j]] == pan[rest[k]] and o[1] - reachw <= b[3] and b[1] - reachw <= o[3]:
                    ufl.union(j, k)
            active.append(k)
        lg: dict[int, list[int]] = defaultdict(list)
        for k, i in enumerate(rest):
            lg[ufl.find(k)].append(i)
        groups_raw.extend((sorted(v), None) for v in lg.values())

    groups = [_describe(dr, mem, kind) for mem, kind in groups_raw if mem]
    _titles(dr, groups, cell, callouts, embedded)
    _absorb_labels(groups, max(g0 * cell, 2 * med_h))
    _title_block(dr, groups)
    _name_ids(groups)
    item_group = {i: gr.id for gr in groups for i in gr.items}
    for gr in groups:  # a title stays with its view (annotations.py reads this mark on the unit's copy of the item)
        for t in gr.titles:
            if 0 <= t < len(dr.items):
                dr.items[t].extra["view_title"] = gr.id
    lay = SheetLayout(frame=frame, frame_items=frame_items, rules=rules, stray=stray, watermark=watermark, groups=groups, cell=cell,
                      gap=g0 * cell, gaps=[w * cell for w in merges], notes=notes, item_group=item_group)
    _units(dr, lay)
    return lay


def _title_block(dr: Drawing, groups: list[Group]) -> None:
    """The title block: the corner of the sheet where its ownership words gather (drawing number, signatures, the
    authority…). Every word group whose middle lies in that corner joins it."""
    items = dr.items
    hits = [(g, i) for g in groups if g.kind in ("notes", "label", "title_block") for i in g.items
            if items[i].dxftype in TEXT_TYPES and items[i].text and TITLE_BLOCK_RE.search(items[i].text)]
    if len({i for _g, i in hits}) < 3:
        return
    pts = [items[i].pts[0] for _g, i in hits]
    xs, ys = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
    # the densest half of them: the corner, not a stray word in a note
    n = len(pts)
    cx, cy = xs[n // 2], ys[n // 2]
    spread = sorted(math.hypot(p[0] - cx, p[1] - cy) for p in pts)[max(0, int(0.75 * n) - 1)]
    near = [(g, i) for (g, i), p in zip(hits, pts) if math.hypot(p[0] - cx, p[1] - cy) <= spread * 1.05]
    bounds = _bbox([q for _g, i in near for q in text_outline(items[i])])
    pad = 0.15 * max(bounds[2] - bounds[0], bounds[3] - bounds[1])
    bounds = (bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad)
    tb = [g for g in groups if g.kind in ("notes", "label", "title_block")
          and bounds[0] <= (g.bbox[0] + g.bbox[2]) / 2 <= bounds[2] and bounds[1] <= (g.bbox[1] + g.bbox[3]) / 2 <= bounds[3]]
    if len(tb) < 2:
        return
    keep = tb[0]
    for g in tb[1:]:
        keep.items = sorted(set(keep.items) | set(g.items))
        g.items = []
    keep.kind = "title_block"
    keep.bbox = _bbox([q for i in keep.items for line in item_lines(items[i]) for q in line] or [q for i in keep.items for q in items[i].pts])
    keep.name = "title block"
    keep.confidence = 0.8
    keep.evidence = [f"{len(near)} title-block words gather here"]
    groups[:] = [g for g in groups if g.items]


def _describe(dr: Drawing, mem: list[int], forced: str | None = None) -> Group:
    """What kind of thing a cluster is, from what it holds (or what its panels already said)."""
    items = dr.items
    texts = [items[i] for i in mem if items[i].dxftype in TEXT_TYPES]
    geom = [items[i] for i in mem if items[i].role in (Role.STRUCTURAL, Role.REFERENCE) and items[i].dxftype not in TEXT_TYPES]
    dims = sum(1 for i in mem if items[i].dxftype == "DIMENSION")
    hatches = sum(1 for i in mem if items[i].dxftype == "HATCH")
    segs = [s for it in geom for s in _segments(it)]
    curved = sum(1 for it in geom if it.dxftype in ("ARC", "CIRCLE", "ELLIPSE", "SPLINE") or any(abs(b) > 1e-9 for b in it.bulges))
    pts = [p for i in mem for line in item_lines(items[i]) for p in line] or [p for i in mem for p in items[i].pts]
    bounds = _bbox(pts)
    bw, bh = max(bounds[2] - bounds[0], 1e-9), max(bounds[3] - bounds[1], 1e-9)
    tol = 1e-3 * max(bw, bh)
    axis = [s for s in segs if abs(s[0][0] - s[1][0]) < tol or abs(s[0][1] - s[1][1]) < tol]
    long_h = sum(1 for a, b in axis if abs(a[1] - b[1]) < tol and abs(a[0] - b[0]) > 0.5 * bw)
    long_v = sum(1 for a, b in axis if abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) > 0.5 * bh)
    words = " ".join(t.text or "" for t in texts)
    tb_words = len({m.group(0).upper() for m in TITLE_BLOCK_RE.finditer(words)})
    straight = len(axis) / max(1, len(segs))
    counts = {"geometry": len(geom), "texts": len(texts), "dimensions": dims, "hatches": hatches, "curves": curved,
              "segments": len(segs), "long_h": long_h, "long_v": long_v}
    if tb_words >= 3 and len(texts) >= 4:
        kind = "title_block"
    elif len(texts) >= 4 and straight >= 0.9 and curved <= 0.1 * max(1, len(segs)) and long_h >= 3 and long_v >= 2 and hatches == 0 and dims == 0:
        kind = "table"  # straight rules on a grid with words in the cells (rounded corners allowed); a table has no dimensions — a drawn view does
    elif texts and len(geom) <= max(2, len(texts) // 4) and dims == 0:
        kind = "notes" if len(texts) >= 2 else "label"
    elif len(geom) >= 3 or dims:
        kind = "view"
    else:
        kind = "label"
    if forced:
        kind = forced
    grp = Group(id="", kind=kind, items=sorted(mem), bbox=bounds, counts=counts)
    if kind == "table" and TABLE_RE.search(words):
        grp.evidence.append("table words in it")
    if kind == "notes" and NOTES_RE.search(words):
        grp.evidence.append("notes words in it")
    if kind == "title_block":
        grp.evidence.append(f"{tb_words} title-block words")
    return grp


def _titles(
    dr: Drawing,
    groups: list[Group],
    cell: float,
    callouts: set[int] | frozenset[int] = frozenset(),
    embedded: set[int] | frozenset[int] = frozenset(),
) -> None:
    """Name each view from its title: a text with view words just below (or above) it, often underlined, often the
    largest words there, often followed by its scale. Words already part of a table or a note are not titles."""
    items = dr.items
    views = [g for g in groups if g.kind == "view"]
    claimed: dict[int, tuple[float, Group]] = {}
    under = [it for it in items if it.dxftype in ("LINE", "LWPOLYLINE") and len(it.pts) >= 2 and abs(it.pts[0][1] - it.pts[-1][1]) < 1e-6]
    under_by_y = sorted(under, key=lambda it: it.pts[0][1])
    ys = [it.pts[0][1] for it in under_by_y]
    pool = [it for it in items if it.dxftype in TEXT_TYPES and it.text]
    owner = {i: g for g in groups for i in g.items}
    for v in views:
        x0, y0, x1, y1 = v.bbox
        w, h = x1 - x0, y1 - y0
        hs = [
            items[i].text_height or 0.0
            for i in v.items
            if items[i].dxftype in TEXT_TYPES and items[i].text_height
        ]
        med = statistics.median(hs) if hs else 0.0
        for it in pool:
            o = owner.get(it.index)
            if it.index in callouts or (o is not None and o is not v and o.kind in ("table", "title_block", "view")):
                continue
            text_value = it.text or ""
            types = (
                _type_of(text_value) if not TITLE_BLOCK_RE.search(text_value) else []
            )
            stated = SCALE_RE.search(text_value) or NTS_RE.search(text_value)
            if (not types and not stated) or (o is not None and o is not v and not types):
                continue
            b = text_outline(it)
            tx0, ty0, tx1, ty1 = _bbox(b)
            cx, cy = (tx0 + tx1) / 2, (ty0 + ty1) / 2
            in_reach = x0 - 0.25 * w <= cx <= x1 + 0.25 * w and y0 - 0.35 * h - 20 * cell <= cy <= y1 + 0.2 * h + 10 * cell
            rot = (it.extra.get("rotation", 0.0) or 0.0) % 180
            if 45 < rot < 135:  # a vertical title stands to the side of its view
                in_reach = in_reach or (y0 - 0.25 * h <= cy <= y1 + 0.25 * h and x0 - 0.35 * w - 20 * cell <= cx <= x1 + 0.35 * w + 20 * cell)
            if not in_reach and o is not v:
                continue
            inside = (x0 <= cx <= x1 and y0 <= cy <= y1) or o is v
            score = 2.0 * bool(types) + 0.5 * bool(stated) + 1.0 * (o is v)
            if cy < y0 + 0.15 * h:
                score += 1.0  # titles sit below their drawing
            if med and it.text_height and it.text_height >= 1.2 * med:
                score += 0.5
            k = np.searchsorted(ys, ty0 - 1.2 * (it.text_height or 1.0))
            for ln in under_by_y[max(0, k - 2): k + 6]:
                lx0, lx1 = sorted((ln.pts[0][0], ln.pts[-1][0]))
                if ty0 - 1.2 * (it.text_height or 1) <= ln.pts[0][1] <= ty0 + 0.3 * (it.text_height or 1) and lx1 - lx0 >= 0.5 * (tx1 - tx0) and lx0 <= cx <= lx1:
                    score += 1.0  # underlined
                    break
            if not inside:
                # distance from the view (a title near its own view beats one near another's)
                dx = max(x0 - cx, 0, cx - x1) / max(w, 1e-9)
                dy = max(y0 - cy, 0, cy - y1) / max(h, 1e-9)
                score -= 1.5 * (dx + dy)
            if score >= 2.0 and (it.index not in claimed or score > claimed[it.index][0]):
                claimed[it.index] = (score, v)
    by_view: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for idx, (score, v) in claimed.items():
        by_view[id(v)].append((score, idx))
    for v in views:
        cands = sorted(by_view.get(id(v), []), reverse=True)
        if not cands:
            v.questions.append("no title found: name this view")
            v.confidence = 0.5
            continue
        # a text the drawing runs through (a cut label on an axis) ranks behind any title that stands on clear paper
        cands.sort(key=lambda si: si[1] in embedded)
        named = [(s, i) for s, i in cands if _type_of(items[i].text or "")]
        titles = named or cands[:1]
        # several titles side by side: halves of one figure, or separate views
        chosen = [titles[0]]
        for s, i in titles[1:]:
            if i in embedded and titles[0][1] not in embedded:
                continue
            if s >= titles[0][0] - 1.0 and abs(text_outline(items[i])[0][1] - text_outline(items[titles[0][1]])[0][1]) < 0.15 * (v.bbox[3] - v.bbox[1]):
                chosen.append((s, i))
        chosen.sort(key=lambda si: text_outline(items[si[1]])[0][0])
        v.titles = [i for _s, i in chosen]
        for _s, i in cands:  # its scale line, if separate
            if i not in v.titles and (
                SCALE_RE.search(items[i].text or "")
                or NTS_RE.search(items[i].text or "")
            ):
                v.titles.append(i)
                break
        names = [
            _clean_title(items[i].text or "")
            for i in v.titles
            if _type_of(items[i].text or "")
        ]
        v.name = " | ".join(n for n in names if n) or _clean_title(
            items[v.titles[0]].text or ""
        )
        text = " ".join(items[i].text or "" for i in v.titles)
        v.view_types = _type_of(text)
        v.view_type = "composite" if len(names) > 1 and {"section", "elevation"} <= set(v.view_types) else _primary(v.view_types, text)
        sc = SCALE_RE.search(text)
        if sc:
            v.scale = float(sc.group(1))
            v.evidence.append(f"scale 1:{sc.group(1)} stated")
        elif NTS_RE.search(text):
            v.evidence.append("not to scale")
        v.evidence.append(f"title: {v.name!r}")
        v.confidence = min(0.95, 0.6 + 0.1 * chosen[0][0])
        if len(names) > 1:
            v.questions.append(f"{len(names)} titles in one cluster ({'; '.join(names)}): one figure drawn in parts, or separate views?")
        for i in v.titles:  # the title belongs to the view it names
            for g in groups:
                if g is not v and i in g.items:
                    g.items.remove(i)
            if i not in v.items:
                v.items.append(i)
        v.items.sort()
    for g in groups:
        if g.kind != "view":
            words = " ".join(items[i].text or "" for i in g.items if items[i].dxftype in TEXT_TYPES)
            head = max((items[i] for i in g.items if items[i].dxftype in TEXT_TYPES and items[i].text), key=lambda it: (it.text_height or 0, it.pts[0][1]), default=None)
            if head is not None:
                g.name = _clean_title(head.text or "")[:80]
            g.confidence = 0.8 if (g.kind == "table" and TABLE_RE.search(words)) or (g.kind == "notes" and NOTES_RE.search(words)) or g.kind == "title_block" else 0.6


def _absorb_labels(groups: list[Group], gap: float) -> None:
    """A lone label, a few words, or a scrap of geometry with no title (a mark, a stub of a level line) next to a view
    belong to it; empty groups go."""
    scraps = [g for g in groups if g.kind == "view" and not g.titles and g.counts.get("geometry", 0) <= 5 and len(g.items) <= 8]
    for g in scraps:
        g.kind = "label"
    views = [g for g in groups if g.kind == "view"]
    for g in [g for g in groups if g.kind == "label"]:
        cx, cy = (g.bbox[0] + g.bbox[2]) / 2, (g.bbox[1] + g.bbox[3]) / 2
        best = None
        for v in views:
            dx = max(v.bbox[0] - cx, 0, cx - v.bbox[2])
            dy = max(v.bbox[1] - cy, 0, cy - v.bbox[3])
            d = math.hypot(dx, dy)
            if d <= 4 * gap and (best is None or d < best[0]):
                best = (d, v)
        if best:
            best[1].items = sorted(set(best[1].items) | set(g.items))
            g.items = []
    for g in scraps:  # a small drawing with no view near it to join is a view of its own
        if g.items:
            g.kind = "view"
    groups[:] = [g for g in groups if g.items]


def _name_ids(groups: list[Group]) -> None:
    """Stable ids in reading order (top to bottom, left to right) per kind: V01…, T01…, N01…, TB, L01…"""
    prefix = {"view": "V", "table": "T", "notes": "N", "title_block": "TB", "label": "L"}
    for kind, pre in prefix.items():
        gs = [g for g in groups if g.kind == kind]
        if not gs:
            continue
        band = max((g.bbox[3] - g.bbox[1]) for g in gs) * 0.25 or 1.0
        gs.sort(key=lambda g: (-round(g.bbox[3] / band), g.bbox[0]))
        for n, g in enumerate(gs, 1):
            g.id = pre if pre == "TB" and len(gs) == 1 else f"{pre}{n:02d}"
    order = {"view": 0, "table": 1, "notes": 2, "title_block": 3, "label": 4}
    groups.sort(key=lambda g: (order[g.kind], g.id))


def _units(dr: Drawing, lay: SheetLayout) -> None:
    """Each view's own drawing unit, from its own dimensions (a detail at 1:25 on a 1:100 sheet reads 4× finer);
    a group key from the handles it holds (the same entities → the same key, session after session)."""
    items = dr.items
    for g in lay.groups:
        g.key = hashlib.sha1(",".join(items[i].src or items[i].handle for i in g.items).encode()).hexdigest()[:12]
        if g.kind != "view":
            continue
        ratios = []
        for i in g.items:
            it = items[i]
            if it.dxftype == "DIMENSION" and it.extra.get("dimtype") in (0, 1) and len(it.pts) >= 3:
                drawn = abs(it.pts[1][0] - it.pts[2][0]) if abs(math.cos(math.radians(it.extra.get("angle", 0.0)))) > 0.5 else abs(it.pts[1][1] - it.pts[2][1])
                if it.extra.get("dimtype") == 1:
                    drawn = math.dist(it.pts[1], it.pts[2])
                nums = re.findall(r"\d+(?:\.\d+)?", (it.text or "").replace("<>", ""))
                stated = float(nums[0]) if nums else 0.0
                if drawn > 0 and stated > 0:
                    ratios.append(stated / drawn)
        if len(ratios) >= 3 and dr.units_mm > 0:
            ratios.sort()
            r = statistics.median(ratios)
            agree = sum(1 for x in ratios if abs(x / r - 1) < 0.02)
            k = r / dr.units_mm
            # its own scale only when most of its dimensions agree on it, and it is a drafting ratio (1:5 … 5:1 of the sheet)
            if agree >= max(3, 0.6 * len(ratios)) and 0.2 <= k <= 5 and abs(k - 1) > 0.05:
                g.units_mm = r
                g.evidence.append(f"its dimensions read {r:g} mm per drawing unit (the sheet: {dr.units_mm:g})")
                if not any("another scale" in q for q in g.questions):
                    g.questions.append(f"drawn at another scale than the sheet ({r / dr.units_mm:g}×): its sizes are read at its own scale")


def view_drawing(dr: Drawing, g: Group | list[int]) -> tuple[Drawing, list[int]]:
    """One view as a standalone Drawing (items re-indexed 0…n-1) and, for each of its items, the index on the sheet.
    The sheet is not touched; the view's analysis, program and regeneration work on this copy only."""
    keep = sorted(set(g.items if isinstance(g, Group) else g))
    local = {s: k for k, s in enumerate(keep)}
    out: list[Item] = []
    for s in keep:
        it = dr.items[s]
        anchor = local.get(it.anchor) if it.anchor is not None else None
        role = it.role if it.anchor is None or anchor is not None else Role.FIXED
        out.append(replace(it, index=local[s], anchor=anchor, role=role, pts=list(it.pts), extra=dict(it.extra),
                           vertex_pts=list(it.vertex_pts), segments=list(it.segments), bulges=list(it.bulges)))
    pts = [it.pts[k] for it in out if it.role == Role.STRUCTURAL for k in it.vertex_pts]
    if not pts:
        pts = [p for it in out for p in it.pts]
    units = g.units_mm if isinstance(g, Group) and g.units_mm else dr.units_mm
    sub = Drawing(path=dr.path, units_mm=units, tol=dr.tol, items=out, extent=_bbox(pts) if pts else dr.extent,
                  unsupported=dict(dr.unsupported), notes=list(dr.notes), layout=dr.layout)
    return sub, keep
