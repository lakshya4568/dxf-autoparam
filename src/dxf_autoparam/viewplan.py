"""How a unit is shown to a model that reads pictures: how big, in how many pieces, which set-out lines, where the labels go.

Pure functions on numbers (no drawing here): `viewimg` draws what this decides, and the tests can check the decisions on their own.

A model reads a picture through a fixed budget of tokens (Gemini 3: 1120 for an image at the default), however many pixels it has: a bigger canvas is
shrunk again and its text with it. The docs do not say how many pixels a token buys, so a picture is kept to what the budget can safely hold — MODEL_SIDE on
its longer side and MODEL_AREA pixels in all, margins included. Legibility is bought with MORE, SMALLER pictures, never with a bigger one:

  size       the text of the drawing (a quarter of its texts are this tall or smaller) should be TEXT_PX pixels tall; the picture is as big as that needs, within
             the limits above
  tiles      a unit too big for that gets an overview (structure only) and up to TILE_MAX overlapping tiles (15 %), each at the finest scale its limits allow;
             where the notes and dimensions are known, tiles of the ideal scale are placed WHERE THEY ARE (greedily, the one holding the most notes not yet in
             a tile, until nearly all are) when that takes no more tiles than cutting the box in a grid would — so a unit whose text sits in a few places is
             read at the ideal scale there, not coarsely everywhere;
             what is still too small there is for zoom_view, which the unit's overview points at (the densest notes, boxes ready to use)
  lines      the set-out lines are many (551 in one unit): each is scored — dimension anchor, axis or centre line, how much is drawn on it, how many
             regions it bounds — and only as many are labelled as fit the picture; the fine ones (a staircase, a hatch) are one band, "y21..y77 (56 lines)"
  labels     placed on four tracks outside the drawing; where labels would collide they are moved the least possible (isotonic regression, PAVA) and joined to
             their tick by a leader — no two labels ever overlap
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

TEXT_PX = 14.0  # a character this tall (pixels) is read reliably; under about 9 it is a blur
MODEL_SIDE = 1600  # the longer side of a picture the model reads without it being shrunk again
MODEL_AREA = 2_200_000  # …and its pixels in all (the budget of an image is tokens, not pixels: Gemini's documented rate, 258 tokens per 768×768 pixels, makes 1120 tokens about 2.5 million; this keeps a margin)
LEGIBLE = 0.65  # an overview whose text is at least this share of TEXT_PX needs no tiles
TILE_MAX = 6
MIN_TILE_TEXTS = 3  # a grid tile needs this many notes or dimensions in it …
MIN_TILE_SHARE = 0.08  # … and this share of all the unit's
COVER_MIN = 0.9  # tiles placed where the notes are are taken only if they hold at least this share of them (the rest is for the overview and zoom_view)
COVER_TARGET = 0.98  # … and are placed until they hold this much, or TILE_MAX are placed
OVERLAP = 0.15
GUTTER = 124  # the margin that holds the labels (four tracks along the top, two columns down the left): outside the drawing, so they never lie on it
TRACKS = 4
LABEL_GAP = 6.0
MIN_LINE_PX = 22.0  # room one labelled line needs along its axis


# ── how big ─────────────────────────────────────────────────────────────────────


def percentile(values: list[float], q: float) -> float:
    """The q-th percentile (0–100) by linear interpolation; 0.0 for nothing."""
    v = sorted(values)
    if not v:
        return 0.0
    k = (len(v) - 1) * q / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def text_height(heights: list[float], box: tuple[float, float, float, float]) -> float:
    """The drawing's own text size in this box (drawing units): the 25th percentile of its texts' heights, ignoring titles (taller than a twentieth of the
    box). With too few texts to say, a sixtieth of the box's smaller side."""
    w, h = box[2] - box[0], box[3] - box[1]
    small = [x for x in heights if 0 < x <= 0.05 * max(w, h, 1e-9)]
    return percentile(small, 25) if len(small) >= 5 else max(min(w, h), 1e-9) / 60.0


@dataclass
class Plan:
    """What to draw for one box: the picture, and the tiles when the picture alone cannot be read."""

    box: tuple[float, float, float, float]
    ideal_scale: float  # pixels per drawing unit at which the text is TEXT_PX tall
    scale: float  # what the overview achieves (pixels per drawing unit)
    width: int  # the overview's width in pixels (gutters included)
    legible: bool  # the overview's text is readable as it is
    tiles: list[tuple[float, float, float, float]] = field(default_factory=list)
    tile_scale: float = 0.0
    tile_legible: bool = True  # the tiles reach the ideal scale (False: still coarser than TEXT_PX; zoom further)
    placed: bool = False  # the tiles were placed where the text is (each has text in it); else they cut the box in a grid, and those with none are left out

    def to_dict(self) -> dict:
        return {"ideal_px_per_unit": round(self.ideal_scale, 6), "overview_px_per_unit": round(self.scale, 6), "legible": self.legible,
                "tiles": len(self.tiles), "tile_px_per_unit": round(self.tile_scale, 6), "tile_legible": self.tile_legible}


def max_scale(w: float, h: float, side: int = MODEL_SIDE, area: int = MODEL_AREA, pad: int = GUTTER) -> float:
    """The largest scale (pixels per drawing unit) at which a w × h box, with its margins, fits the picture the model reads: neither side over
    `side`, and (w·s + 2·pad)(h·s + 2·pad) at most `area`."""
    p2 = 2 * pad
    by_side = (side - p2) / max(w, h, 1e-12)
    a, b, c = w * h, p2 * (w + h), p2 * p2 - area
    disc = b * b - 4 * a * c
    by_area = (-b + math.sqrt(disc)) / (2 * a) if a > 1e-12 and disc >= 0 else by_side
    return max(min(by_side, by_area), 1e-12)


def picture_width(box: tuple[float, float, float, float], ideal_scale: float, side: int = MODEL_SIDE, pad: int = GUTTER) -> int:
    """The width in pixels of a picture of the box at the ideal scale — or at the finest the model's limits allow — never under a floor that keeps a
    small box a picture."""
    w, h = box[2] - box[0], box[3] - box[1]
    scale = min(ideal_scale, max_scale(w, h, side, pad=pad))
    return max(480, min(side, math.ceil(w * scale + 2 * pad)))


def _split(span: float, n: int, overlap: float) -> float:
    """The length of each of n tiles that cover `span` with each pair overlapping by `overlap` of a tile."""
    return span / (1 + (n - 1) * (1 - overlap))


def _cells(box: tuple[float, float, float, float], nx: int, ny: int, tx: float, ty: float) -> list[tuple[float, float, float, float]]:
    """The nx × ny tiles of size tx × ty that cover the box, top row first, left to right."""
    x0, y0, x1, y1 = box
    sx = (x1 - x0 - tx) / (nx - 1) if nx > 1 else 0.0
    sy = (y1 - y0 - ty) / (ny - 1) if ny > 1 else 0.0
    return [(x0 + i * sx, y0 + j * sy, x0 + i * sx + tx, y0 + j * sy + ty) for j in range(ny - 1, -1, -1) for i in range(nx)]


def _kept(tiles: list[tuple[float, float, float, float]], texts: list[tuple[float, float]]) -> list[tuple[float, float, float, float]]:
    counts = [sum(1 for x, y in texts if t[0] <= x <= t[2] and t[1] <= y <= t[3]) for t in tiles]
    return [t for t, n in zip(tiles, counts, strict=True) if n >= MIN_TILE_TEXTS and n >= MIN_TILE_SHARE * len(texts)]


def with_text(tiles: list[tuple[float, float, float, float]], texts: list[tuple[float, float]]) -> list[tuple[float, float, float, float]]:
    """The tiles that have something to read: at least MIN_TILE_TEXTS notes or dimensions (anchor points `texts`), and MIN_TILE_SHARE of all of them —
    the busiest one when none does. A tile with next to nothing in it is not made: its geometry is in the overview, its numbers in the tables."""
    kept = _kept(tiles, texts)
    if kept or not tiles or not texts:  # a unit with no note or dimension at all has nothing to make a close-up of: the overview is its picture
        return kept
    counts = [sum(1 for x, y in texts if t[0] <= x <= t[2] and t[1] <= y <= t[3]) for t in tiles]
    return [tiles[counts.index(max(counts))]]


def plan_tiles(box: tuple[float, float, float, float], ideal_scale: float, side: int = MODEL_SIDE, pad: int = GUTTER, k_max: int = TILE_MAX,
               overlap: float = OVERLAP) -> tuple[list[tuple[float, float, float, float]], float]:
    """Cut the box into the fewest overlapping tiles (at most k_max) at which the text reaches the ideal scale — or into the finest the limit allows.
    Returns (tiles in reading order, the scale each achieves in pixels per unit)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    best = None
    for nx in range(1, k_max + 1):
        for ny in range(1, k_max // nx + 1):
            tx, ty = _split(w, nx, overlap), _split(h, ny, overlap)
            scale = max_scale(tx, ty, side, pad=pad)
            ok = scale >= ideal_scale - 1e-12
            key = (ok, -nx * ny if ok else scale, -nx * ny)  # enough scale with the fewest tiles; else the finest scale, then the fewest
            if best is None or key > best[0]:
                best = (key, nx, ny, tx, ty, scale)
    assert best is not None
    _key, nx, ny, tx, ty, scale = best
    return _cells(box, nx, ny, tx, ty), scale


def tile_size(ideal_scale: float, landscape: bool = True, side: int = MODEL_SIDE, pad: int = GUTTER, area: int = MODEL_AREA) -> tuple[float, float]:
    """The biggest tile (width, height in drawing units) whose picture at the ideal scale still fits what the model reads — its side and its area."""
    inner = side - 2 * pad
    short_px = max(1.0, min(float(inner), area / (inner + 2 * pad) - 2 * pad))
    long_, short_ = inner / ideal_scale, short_px / ideal_scale
    return (long_, short_) if landscape else (short_, long_)


def cover_tiles(box: tuple[float, float, float, float], texts: list[tuple[float, float]], ideal_scale: float, k_max: int = TILE_MAX,
                side: int = MODEL_SIDE, pad: int = GUTTER) -> tuple[list[tuple[float, float, float, float]], float]:
    """Tiles of the ideal scale placed where the notes and dimensions are: greedily the tile that holds the most not yet in one, until COVER_TARGET of them
    are in a tile or k_max are placed. Returns (tiles in reading order, the share of the notes they hold). Where the text sits in a few places this reads
    all of it at the ideal scale with fewer tiles than a grid by extent needs — and the places with nothing to read get none."""
    x0, y0, x1, y1 = box
    if not texts or x1 <= x0 or y1 <= y0:
        return [], 0.0
    tw, th = tile_size(ideal_scale, landscape=(x1 - x0) >= (y1 - y0), side=side, pad=pad)
    tw, th = min(tw, x1 - x0), min(th, y1 - y0)
    left = list(texts)
    tiles: list[tuple[float, float, float, float]] = []
    while left and len(tiles) < k_max and 1 - len(left) / len(texts) < COVER_TARGET:
        best = (0, None)
        for cx, cy in left:  # a tile centred on a note not yet held (shifted to stay inside the box)
            bx, by = min(max(cx - tw / 2, x0), x1 - tw), min(max(cy - th / 2, y0), y1 - th)
            n = sum(1 for x, y in left if bx <= x <= bx + tw and by <= y <= by + th)
            if n > best[0]:
                best = (n, (bx, by, bx + tw, by + th))
        if best[1] is None:
            break
        tiles.append(best[1])
        left = [(x, y) for x, y in left if not (best[1][0] <= x <= best[1][2] and best[1][1] <= y <= best[1][3])]
    row = max(th / 2, 1e-12)
    tiles.sort(key=lambda t: (-round((t[1] + t[3]) / 2 / row), t[0]))  # top row first, left to right
    return tiles, 1 - len(left) / len(texts)


def plan_pictures(box: tuple[float, float, float, float], text_h: float, side: int = MODEL_SIDE, pad: int = GUTTER,
                  texts: list[tuple[float, float]] | None = None) -> Plan:
    """The overview for this box, and tiles if its text could not be read in it: the overview is legible when its text is at least LEGIBLE of
    TEXT_PX tall; a box much wider than tall counts too (its text is small for its width). `texts`: where the notes and dimensions are — tiles are then
    placed where they are (cover_tiles) when those hold COVER_MIN of them and take no more tiles than a grid by extent, or reach a scale it cannot."""
    w, h = box[2] - box[0], box[3] - box[1]
    ideal = TEXT_PX / max(text_h, 1e-12)
    scale = min(ideal, max_scale(w, h, side, pad=pad))
    width = max(480, min(side, math.ceil(w * scale + 2 * pad)))
    legible = scale >= LEGIBLE * ideal
    aspect = max(w / max(h, 1e-12), h / max(w, 1e-12))
    plan = Plan(box=box, ideal_scale=ideal, scale=scale, width=width, legible=legible)
    if not legible or aspect > 2.4 and scale < ideal:
        grid, grid_scale = plan_tiles(box, ideal, side, pad)
        placed, held = cover_tiles(box, texts or [], ideal, TILE_MAX, side, pad)
        if placed and held >= COVER_MIN and (grid_scale < ideal - 1e-12 or len(placed) < len(grid)):
            plan.tiles, plan.tile_scale, plan.placed = placed, ideal, True
        else:
            plan.tiles, plan.tile_scale = grid, grid_scale
        plan.tile_legible = plan.tile_scale >= LEGIBLE * ideal
        if len(plan.tiles) == 1 and plan.tiles[0][2] - plan.tiles[0][0] >= 0.99 * w and plan.tiles[0][3] - plan.tiles[0][1] >= 0.99 * h:
            plan.tiles = []  # a tile that is the whole box is the overview again
    return plan


# ── which set-out lines ─────────────────────────────────────────────────────────


def salience(anchors_dimension: bool, axis_or_centre: bool, drawn_on: int, drawn_on_max: int, major_regions: int) -> float:
    """How much a set-out line matters: 3 for anchoring a dimension, 2 for being an axis or centre line, up to 1.5 for how much is drawn on it,
    1 for each major region it bounds."""
    return 3.0 * anchors_dimension + 2.0 * axis_or_centre + 1.5 * (drawn_on / drawn_on_max if drawn_on_max else 0.0) + 1.0 * major_regions


@dataclass
class Line:
    id: str
    pos: float  # pixels along its axis
    score: float
    anchor: bool  # a dimension, a named size, a stated level or an axis stands on it: always labelled


@dataclass
class Band:
    first: str
    last: str
    lo: float
    hi: float
    count: int

    @property
    def label(self) -> str:
        return f"{self.first}..{self.last} ({self.count} lines — zoom)"


def admit(lines: list[Line], span_px: float, min_gap: float = MIN_LINE_PX, dense_px: float = 6.0) -> tuple[list[Line], list[Band]]:
    """Which lines to label along an axis `span_px` long: no more than fit (a label needs `min_gap` px) — the anchors first, the best of them if there are
    more than fit, then the best of the rest — never two lines closer than 2 px. The ones left out, where they crowd (a run of at least three, less than
    `dense_px` apart), are a band."""
    capacity = max(1, int(span_px // min_gap))
    keep: list[Line] = []
    ranked = sorted(lines, key=lambda x: (not x.anchor, -x.score, x.pos))  # anchors first, each group best first
    for x in ranked:
        if len(keep) >= capacity:
            break
        if all(abs(x.pos - k.pos) >= 2.0 for k in keep):  # two lines on one pixel are one tick
            keep.append(x)
    keep.sort(key=lambda x: x.pos)
    kept = {x.id for x in keep}
    left = sorted((x for x in lines if x.id not in kept), key=lambda x: x.pos)
    bands: list[Band] = []
    run: list[Line] = []
    for x in left:
        if run and x.pos - run[-1].pos > dense_px:
            if len(run) >= 3:
                bands.append(Band(run[0].id, run[-1].id, run[0].pos, run[-1].pos, len(run)))
            run = []
        run.append(x)
    if len(run) >= 3:
        bands.append(Band(run[0].id, run[-1].id, run[0].pos, run[-1].pos, len(run)))
    return keep, bands


# ── where the labels go ─────────────────────────────────────────────────────────


def pava(z: list[float], w: list[float] | None = None) -> list[float]:
    """Isotonic regression (pool adjacent violators): the non-decreasing sequence nearest to z in weighted least squares, in linear time."""
    w = w or [1.0] * len(z)
    blocks: list[list[float]] = []  # [mean, weight, count]
    for zi, wi in zip(z, w, strict=True):
        blocks.append([zi, wi, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0] + 1e-12:
            m2, w2, c2 = blocks.pop()
            m1, w1, c1 = blocks.pop()
            blocks.append([(m1 * w1 + m2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
    out: list[float] = []
    for m, _wt, c in blocks:
        out.extend([m] * int(c))
    return out


def pack_labels(targets: list[float], widths: list[float], lo: float, hi: float, gap: float = LABEL_GAP) -> list[float]:
    """The centres nearest the targets (in squared distance) at which labels of these widths, in this order, do not overlap — each at least `gap`
    from the next — and lie within [lo, hi]. Solved by isotonic regression on the targets less the spacing the neighbours need. If the labels cannot
    all fit (they are wider together than the span), they are spread evenly across it."""
    n = len(targets)
    if n == 0:
        return []
    need = [(widths[i] + widths[i + 1]) / 2 + gap for i in range(n - 1)]
    offset = [0.0]
    for s in need:
        offset.append(offset[-1] + s)
    room = hi - lo - widths[0] / 2 - widths[-1] / 2
    if offset[-1] > room + 1e-9:  # more than fits: even spacing, the best that can be done
        return [lo + widths[0] / 2 + (room * i / max(n - 1, 1)) for i in range(n)]
    # In y = x − offset the labels' order is "y non-decreasing" and the span is the one interval [lo + w₀/2, hi − wₙ/2 − offset] for every label (the
    # first and last bounds imply the rest): the best answer under a uniform interval is the unbounded isotonic fit, clipped.
    low, high = lo + widths[0] / 2, hi - widths[-1] / 2 - offset[-1]
    y = [min(max(v, low), high) for v in pava([t - o for t, o in zip(targets, offset, strict=True)])]
    return [yi + o for yi, o in zip(y, offset, strict=True)]


def assign_tracks(count: int, tracks: int = TRACKS) -> list[int]:
    """Neighbouring labels on different tracks: the label k of the order goes on track k mod `tracks`, so each track has `tracks` times the room."""
    return [k % tracks for k in range(count)]
