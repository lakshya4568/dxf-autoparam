"""Analysis: what a static drawing says about its own design intent.

Nothing here knows a structure type. The analysis works on a few generic facts of
how 2D set-out drawings are made:

  1. DATUMS      Coordinates that coincide are one set-out line (shared x / shared y).
  2. GAPS        A size is the distance between two datums, and a draftsman's sizes
                 show up as: two parallel FACES looking at each other (a thickness or
                 an opening), consecutive vertices ALONG one edge (a step, a projection),
                 the run/rise of a SLOPED edge (a chamfer, a batter), the spacing of
                 repeated congruent members (a PITCH), and DIMENSION entities.
  3. AXES        Construction axes: drawn centre lines, the own axis of every symmetric
                 outline, and the whole drawing's mirror axis.
  4. EQUALITY    Equal gaps of the same kind on the same axis are probably one value
                 (walls of a box, girders at one spacing, both projections of a footing).
  5. EVIDENCE    Each candidate value is scored from independent evidence: a dimension
                 states it, it repeats, it is mirrored, a note states it, it is a round
                 number (design values are; derived positions usually are not).

Every result carries its evidence, so a person can review it in minutes.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass

from .ir import Analysis, Axis, Cluster, Constraint, Datum, Drawing, Evidence, Gap, GapKind, Item, Role, Status

FACE_KINDS = {GapKind.SOLID, GapKind.VOID, GapKind.OPEN}
STRONG_KINDS = FACE_KINDS | {GapKind.LEG, GapKind.PITCH, GapKind.DIM}
# Lower = stronger: decides which kind a gap found twice keeps.
KIND_RANK = {
    GapKind.ARC: 0, GapKind.SOLID: 1, GapKind.VOID: 1, GapKind.OPEN: 2, GapKind.LEG: 2, GapKind.PITCH: 3,
    GapKind.DIM: 3, GapKind.RUN: 4, GapKind.RISE: 4, GapKind.OFFSET: 5, GapKind.CHAIN: 6,
    GapKind.DIAMETER: 1, GapKind.RING: 1, GapKind.SLOPE: 4,
}
BASE_CONFIDENCE = {
    GapKind.SOLID: 0.55, GapKind.VOID: 0.55, GapKind.OPEN: 0.42, GapKind.LEG: 0.5, GapKind.PITCH: 0.55,
    GapKind.DIM: 0.6, GapKind.RUN: 0.35, GapKind.RISE: 0.35, GapKind.CHAIN: 0.38, GapKind.OFFSET: 0.38,
    GapKind.DIAMETER: 0.6, GapKind.RING: 0.55,
}
PREFIX = {
    (GapKind.SOLID, "x"): ("ThkX", "Thickness of a vertical member"),
    (GapKind.SOLID, "y"): ("ThkY", "Thickness of a horizontal member / layer"),
    (GapKind.VOID, "x"): ("OpenX", "Opening width"),
    (GapKind.VOID, "y"): ("OpenY", "Opening height"),
    (GapKind.OPEN, "x"): ("GapX", "Clear distance between faces (horizontal)"),
    (GapKind.OPEN, "y"): ("GapY", "Clear distance between faces (vertical)"),
    (GapKind.LEG, "x"): ("Leg", "Equal-leg chamfer / splay"),
    (GapKind.LEG, "y"): ("Leg", "Equal-leg chamfer / splay"),
    (GapKind.RUN, "x"): ("Run", "Horizontal run of a sloped edge"),
    (GapKind.RISE, "y"): ("Rise", "Vertical rise of a sloped edge"),
    (GapKind.CHAIN, "x"): ("StepX", "Step along a horizontal edge"),
    (GapKind.CHAIN, "y"): ("StepY", "Step along a vertical edge"),
    (GapKind.PITCH, "x"): ("PitchX", "Spacing of repeated members (horizontal)"),
    (GapKind.PITCH, "y"): ("PitchY", "Spacing of repeated members (vertical)"),
    (GapKind.OFFSET, "x"): ("OffX", "Offset from a member axis (horizontal)"),
    (GapKind.OFFSET, "y"): ("OffY", "Offset from a member axis (vertical)"),
    (GapKind.DIM, "x"): ("DimX", "Dimensioned length (horizontal)"),
    (GapKind.DIM, "y"): ("DimY", "Dimensioned length (vertical)"),
    (GapKind.DIAMETER, "r"): ("Dia", "Circle diameter"),
    (GapKind.RING, "r"): ("Ring", "Wall between concentric circles"),
}
STOP_WORDS = {"MM", "THK", "THICK", "TH", "NO", "NOS", "AND", "THE", "OF", "AT", "TO", "IN", "ON", "BY", "FOR", "WITH", "C", "CC", "X", "M", "LEVEL", "RL"}
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class AnalyseOptions:
    accept_threshold: float = 0.45
    sweep_limit: int = 400  # faces scanned per face when looking for the facing one
    symmetry_min: float = 0.6  # share of segments with a mirror image for a whole-drawing axis
    symmetry_min_drawn: float = 0.3  # the same when a centre line is drawn there
    symmetry_y_global: float = 0.9  # top-bottom symmetry needs (almost) the whole drawing: plans, not elevations
    layer_ratio: float = 8.0  # a solid this many times longer than thick is a layer that follows its neighbour


# ── geometry helpers ────────────────────────────────────────────────────────────


def point_in_poly(p: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def _bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def is_round(v_mm: float) -> int:
    """2: a multiple of 5 mm, 1: whole mm, 0: neither (probably a derived position)."""
    if abs(v_mm - round(v_mm)) > 0.01:
        return 0
    return 2 if round(v_mm) % 5 == 0 else 1


# ── the analysis ────────────────────────────────────────────────────────────────


class _Datums:
    """Clusters coordinate values into datums, one axis at a time."""

    def __init__(self, axis: Axis, tol: float):
        self.axis = axis
        self.tol = tol
        self.values: list[tuple[float, int, int]] = []  # (value, item, pt)
        self.datums: list[Datum] = []
        self._sorted: list[float] = []

    def add(self, v: float, item: int, pt: int) -> None:
        self.values.append((v, item, pt))

    def build(self) -> dict[tuple[int, int], tuple[str, float]]:
        binding: dict[tuple[int, int], tuple[str, float]] = {}
        cur: list[tuple[float, int, int]] = []

        def flush() -> None:
            if not cur:
                return
            vs = sorted(c[0] for c in cur)
            d = Datum(id=f"{self.axis}{len(self.datums)}", axis=self.axis, value=vs[len(vs) // 2])
            for v, item, pt in cur:
                d.items.add(item)
                binding[(item, pt)] = (d.id, v - d.value)
            self.datums.append(d)

        for v in sorted(self.values):
            if cur and v[0] - cur[-1][0] > self.tol:
                flush()
                cur = []
            cur.append(v)
        flush()
        self._sorted = [d.value for d in self.datums]
        return binding

    def near(self, v: float) -> Datum | None:
        i = bisect_left(self._sorted, v - self.tol)
        best = None
        while i < len(self._sorted) and self._sorted[i] <= v + self.tol:
            d = self.datums[i]
            if best is None or abs(d.value - v) < abs(best.value - v):
                best = d
            i += 1
        return best

    def nearest(self, v: float) -> Datum:
        i = bisect_left(self._sorted, v)
        cands = [self.datums[j] for j in (i - 1, i) if 0 <= j < len(self.datums)]
        return min(cands, key=lambda d: abs(d.value - v))

    def add_virtual(self, v: float, source: str) -> Datum:
        d = self.near(v)
        if d is not None:
            if d.source == "vertex":
                d.source = source
            return d
        d = Datum(id=f"a{self.axis}{len(self.datums)}", axis=self.axis, value=v, virtual=True, source=source)
        i = bisect_left(self._sorted, v)
        self.datums.insert(i, d)
        self._sorted.insert(i, v)
        return d


def analyse(dr: Drawing, opts: AnalyseOptions | None = None) -> Analysis:
    opts = opts or AnalyseOptions()
    tol = dr.tol
    items = dr.items
    notes: list[str] = []
    patterned = _drawn_patterns([it for it in items if it.role == Role.STRUCTURAL], tol)
    if patterned:
        for it in patterned:
            it.role = Role.ANNOTATION
        notes.append(f"{len(patterned)} evenly spaced identical lines read as a drawn pattern (hatching / courses), not structure.")
    structural = [it for it in items if it.role == Role.STRUCTURAL]
    reference = [it for it in items if it.role == Role.REFERENCE]

    # ── 1. datums from structural vertices, arc centres and drawn axes ──────────────
    dx, dy = _Datums("x", tol), _Datums("y", tol)
    for it in structural:
        idx = list(it.vertex_pts)
        if it.dxftype == "ARC":
            idx = [0, *idx]  # the centre sets the arc out
        for k in idx:
            x, y = it.pts[k]
            dx.add(x, it.index, k)
            dy.add(y, it.index, k)
    drawn_axis_items: list[tuple[Item, Axis]] = []
    for it in reference:
        if len(it.pts) == 2 and not it.closed:
            (x1, y1), (x2, y2) = it.pts
            if abs(x1 - x2) <= tol and abs(y1 - y2) > tol:
                dx.add(x1, it.index, 0)
                dx.add(x2, it.index, 1)
                drawn_axis_items.append((it, "x"))
            elif abs(y1 - y2) <= tol and abs(x1 - x2) > tol:
                dy.add(y1, it.index, 0)
                dy.add(y2, it.index, 1)
                drawn_axis_items.append((it, "y"))
    bx, by = dx.build(), dy.build()
    D = {"x": dx, "y": dy}
    slot_datum: dict[tuple[int, int, str], tuple[str, float]] = {}
    for (item, pt), b in bx.items():
        slot_datum[(item, pt, "x")] = b
    for (item, pt), b in by.items():
        slot_datum[(item, pt, "y")] = b
    for it, ax in drawn_axis_items:
        d = D[ax].near(it.pts[0][0] if ax == "x" else it.pts[0][1])
        if d:
            d.source = "drawn-axis"

    def did(it: Item, k: int, axis: Axis) -> str:
        return slot_datum[(it.index, k, axis)][0]

    datum_by_id: dict[str, Datum] = {d.id: d for d in [*dx.datums, *dy.datums]}

    # Loose lines: a straight line whose ends touch no other vertex (a level, water or
    # ground line drawn across a view). They do not bound members, so they must not
    # hide one face from another, and structure is not set out from them.
    owners: dict[tuple[str, str], int] = defaultdict(int)
    for it in structural:
        for k in it.vertex_pts:
            owners[(did(it, k, "x"), did(it, k, "y"))] += 1
    loose: set[int] = set()
    for it in structural:
        if len(it.pts) == 2 and not it.closed and it.dxftype in ("LINE", "LWPOLYLINE", "POLYLINE"):
            if all(owners[(did(it, k, "x"), did(it, k, "y"))] == 1 for k in (0, 1)):
                loose.add(it.index)
    for d in [*dx.datums, *dy.datums]:
        if d.items and d.items <= loose:
            d.weak = True

    # ── 2. segments ──────────────────────────────────────────────────────────────
    vert: list[tuple[float, float, float, int, str]] = []  # x, lo, hi, item, datum
    horz: list[tuple[float, float, float, int, str]] = []
    sloped: list[tuple[Item, int, int]] = []
    for it in structural:
        for i, j in it.segments:
            (x1, y1), (x2, y2) = it.pts[i], it.pts[j]
            if abs(x1 - x2) <= tol and abs(y1 - y2) > tol:
                vert.append(((x1 + x2) / 2, min(y1, y2), max(y1, y2), it.index, did(it, i, "x")))
            elif abs(y1 - y2) <= tol and abs(x1 - x2) > tol:
                horz.append(((y1 + y2) / 2, min(x1, x2), max(x1, x2), it.index, did(it, i, "y")))
            elif abs(x1 - x2) > tol and abs(y1 - y2) > tol:
                sloped.append((it, i, j))

    gaps: dict[tuple[str, str, str], Gap] = {}

    def add_gap(axis: Axis, a: str, b: str, kind: GapKind, overlap=0.0, sample=None) -> Gap | None:
        if a == b:
            return None
        va, vb = datum_by_id[a].value, datum_by_id[b].value
        if va > vb:
            a, b, va, vb = b, a, vb, va
        key = (axis, a, b)
        g = gaps.get(key)
        if g is None:
            g = Gap(id=f"g{len(gaps)}", axis=axis, a=a, b=b, value=vb - va, kind=kind, overlap=overlap, sample=sample)
            gaps[key] = g
        else:
            if KIND_RANK[kind] < KIND_RANK[g.kind]:
                g.kind = kind
                if sample is not None:
                    g.sample = sample
            g.overlap += overlap
            if g.sample is None:
                g.sample = sample
        return g

    # ── 3. facing faces (a thickness or an opening between two parallel faces) ────
    def sweep(faces, axis: Axis) -> None:
        faces.sort(key=lambda f: f[0])
        pos = [f[0] for f in faces]
        for fa in faces:
            pa, lo, hi, _, da = fa
            uncovered = [(lo, hi)]
            start = bisect_right(pos, pa + tol)
            for n, fb in enumerate(faces[start:]):
                if n > opts.sweep_limit:
                    break
                pb, lob, hib, ib, db = fb
                if ib in loose:
                    # seen through, not stopping the view; recorded where it is in view
                    for u0, u1 in uncovered:
                        o0, o1 = max(u0, lob), min(u1, hib)
                        if o1 - o0 > tol:
                            mid = (o0 + o1) / 2
                            add_gap(axis, da, db, GapKind.OPEN, overlap=o1 - o0, sample=((pa + pb) / 2, mid) if axis == "x" else (mid, (pa + pb) / 2))
                            break
                    continue
                rest = []
                total = 0.0
                piece = None
                for u0, u1 in uncovered:
                    o0, o1 = max(u0, lob), min(u1, hib)
                    if o1 - o0 > tol:
                        total += o1 - o0
                        if piece is None or o1 - o0 > piece[1] - piece[0]:
                            piece = (o0, o1)
                        if o0 - u0 > tol:
                            rest.append((u0, o0))
                        if u1 - o1 > tol:
                            rest.append((o1, u1))
                    else:
                        rest.append((u0, u1))
                if total > tol and piece is not None:
                    mid = (piece[0] + piece[1]) / 2
                    sample = ((pa + pb) / 2, mid) if axis == "x" else (mid, (pa + pb) / 2)
                    add_gap(axis, da, db, GapKind.OPEN, overlap=total, sample=sample)
                uncovered = rest
                if not uncovered:
                    break

    sweep(vert, "x")
    sweep(horz, "y")

    # ── 4. chains along straight edges (steps, projections, set-backs) ─────────────
    on_line: dict[str, list[tuple[float, str]]] = defaultdict(list)  # y-datum -> (x, x-datum) and vice versa
    for it in structural:
        for k in it.vertex_pts:
            x, y = it.pts[k]
            on_line[did(it, k, "y")].append((x, did(it, k, "x")))
            on_line[did(it, k, "x")].append((y, did(it, k, "y")))
    line_index = {k: sorted(set(v)) for k, v in on_line.items()}

    def chain(segs, axis: Axis) -> None:
        for _, lo, hi, _, d_line in segs:
            stations = line_index.get(d_line, [])
            vals = [s[0] for s in stations]
            i0, i1 = bisect_left(vals, lo - tol), bisect_right(vals, hi + tol)
            seen: list[str] = []
            for _, d in stations[i0:i1]:
                if not seen or seen[-1] != d:
                    seen.append(d)
            for a, b in zip(seen, seen[1:]):
                add_gap(axis, a, b, GapKind.CHAIN)

    chain(horz, "x")
    chain(vert, "y")

    # ── 5. sloped edges: equal legs (chamfers) or run / rise ───────────────────────
    leg_pairs: list[tuple[Gap, Gap]] = []
    # Equal legs are a CHAMFER only when the same chamfer recurs (haunch corners,
    # splays); a single 45° edge is a slope like any other and keeps its angle.
    leg_count: dict[int, int] = defaultdict(int)
    for it, i, j in sloped:
        (x1, y1), (x2, y2) = it.pts[i], it.pts[j]
        if abs(abs(x2 - x1) - abs(y2 - y1)) <= tol:
            leg_count[round(abs(x2 - x1) / (2 * tol))] += 1
    for it, i, j in sloped:
        (x1, y1), (x2, y2) = it.pts[i], it.pts[j]
        mid = ((x1 + x2) / 2, (y1 + y2) / 2)
        if abs(abs(x2 - x1) - abs(y2 - y1)) <= tol and leg_count[round(abs(x2 - x1) / (2 * tol))] >= 2:
            gx = add_gap("x", did(it, i, "x"), did(it, j, "x"), GapKind.LEG, sample=mid)
            gy = add_gap("y", did(it, i, "y"), did(it, j, "y"), GapKind.LEG, sample=mid)
            if gx and gy:
                leg_pairs.append((gx, gy))
        else:
            ratio = (x2 - x1) / (y2 - y1)
            if _nice_ratio(abs(ratio)):
                # A batter, a side slope, a splay: the drawing states an angle, not a run.
                g = add_gap("x", did(it, i, "x"), did(it, j, "x"), GapKind.SLOPE, sample=mid)
                if g is not None:  # kept even where the same lines also face each other
                    g.slope = (did(it, i, "x"), did(it, i, "y"), did(it, j, "x"), did(it, j, "y"), ratio)
            else:
                add_gap("x", did(it, i, "x"), did(it, j, "x"), GapKind.RUN, sample=mid)
            add_gap("y", did(it, i, "y"), did(it, j, "y"), GapKind.RISE, sample=mid)

    # ── 6. arcs are rigid about their centre ────────────────────────────────────
    for it in structural:
        if it.dxftype == "ARC":
            for k in (1, 2):
                for ax in ("x", "y"):
                    add_gap(ax, did(it, 0, ax), did(it, k, ax), GapKind.ARC)

    # ── 7. construction axes: drawn, each symmetric outline's own, the whole drawing's ─
    axes: list[str] = [d.id for d in [*dx.datums, *dy.datums] if d.source == "drawn-axis"]
    loop_axis: dict[int, dict[str, str]] = {}  # item -> axis -> axis datum id
    loops: list[Item] = [it for it in structural if it.closed and len(it.vertex_pts) >= 4]
    seg_keys, seg_list = _segment_keys(structural, did)
    y_symmetric = _mirror_score(seg_list, seg_keys, dy, datum_by_id, (dr.extent[1] + dr.extent[3]) / 2, "y") >= opts.symmetry_y_global
    for it in loops:
        poly = [it.pts[k] for k in it.vertex_pts]
        x0, y0, x1, y1 = _bbox(poly)
        # Left-right symmetry of an outline is design intent (centre lines). Top-bottom
        # symmetry of an outline in an elevation is a coincidence of its proportions —
        # heights are set out from below — so it is used only when the whole drawing is
        # symmetric top to bottom (a plan) or a horizontal centre line is drawn.
        own_axes = [("x", (x0 + x1) / 2)] + ([("y", (y0 + y1) / 2)] if y_symmetric else [])
        for ax, c in own_axes:
            mirrored = all(
                any(
                    abs(q[0] - (2 * c - p[0] if ax == "x" else p[0])) <= tol and abs(q[1] - (2 * c - p[1] if ax == "y" else p[1])) <= tol
                    for q in poly
                )
                for p in poly
            )
            if mirrored:
                d = D[ax].add_virtual(c, "loop-axis")
                datum_by_id[d.id] = d
                loop_axis.setdefault(it.index, {})[ax] = d.id
                if d.id not in axes:
                    axes.append(d.id)

    # whole-drawing mirror symmetry, scored on datum ids of every straight segment
    global_axis: dict[str, str | None] = {"x": None, "y": None}
    for ax in ("x", "y"):
        dat = D[ax]
        ext = (dr.extent[0], dr.extent[2]) if ax == "x" else (dr.extent[1], dr.extent[3])
        cands: list[tuple[float, bool]] = [((ext[0] + ext[1]) / 2, False)]
        cands += [(datum_by_id[a].value, True) for a in axes if datum_by_id[a].axis == ax and datum_by_id[a].source == "drawn-axis"]
        best: tuple[float, float, bool] | None = None
        for c, drawn in cands:
            score = _mirror_score(seg_list, seg_keys, dat, datum_by_id, c, ax)
            need = opts.symmetry_min_drawn if drawn else opts.symmetry_min if ax == "x" else opts.symmetry_y_global
            if score >= need and (best is None or score > best[1]):
                best = (c, score, drawn)
        if best:
            d = dat.add_virtual(best[0], "drawn-axis" if best[2] else "global-axis")
            datum_by_id[d.id] = d
            global_axis[ax] = d.id
            if d.id not in axes:
                axes.append(d.id)
            notes.append(f"Mirror symmetry about {ax} = {best[0]:.3f} ({best[1]:.0%} of edges have a mirror image{', a drawn centre line' if best[2] else ''}).")

    # ── 8. gaps centred on an axis are symmetric about it ─────────────────────────
    loop_datums: dict[int, set[str]] = {
        it.index: {did(it, k, ax) for k in it.vertex_pts for ax in ("x", "y")} for it in loops
    }
    axis_loops: dict[str, list[int]] = defaultdict(list)
    for item, m in loop_axis.items():
        for ax, a in m.items():
            axis_loops[a].append(item)
    for (axis, a, b), g in gaps.items():
        if g.kind == GapKind.ARC:
            continue
        mid = (datum_by_id[a].value + datum_by_id[b].value) / 2
        d = D[axis].near(mid)
        if d is None or d.id not in axes or d.id in (a, b):
            continue
        is_global = global_axis[axis] == d.id or d.source == "drawn-axis"
        loop_owners = axis_loops.get(d.id, [])
        if is_global or any(a in loop_datums[o] and b in loop_datums[o] for o in loop_owners):
            g.sym_axis = d.id

    # ── 9. repeated congruent members: the spacing of their axes is a value ───────
    by_shape: dict[tuple, list[int]] = defaultdict(list)
    for it in loops:
        poly = [it.pts[k] for k in it.vertex_pts]
        x0, y0, x1, y1 = _bbox(poly)
        by_shape[(len(poly), round((x1 - x0) / (2 * tol)), round((y1 - y0) / (2 * tol)))].append(it.index)
    circles = [it for it in structural if it.dxftype == "CIRCLE"]
    for c in circles:
        by_shape[("circle", round(c.radius / (2 * tol)))].append(c.index)
    for members in by_shape.values():
        if len(members) < 2:
            continue
        for ax in ("x", "y"):
            other: Axis = "y" if ax == "x" else "x"
            rows: dict[str, list[str]] = defaultdict(list)
            for m in members:
                it = items[m]
                if it.dxftype == "CIRCLE":
                    own, row = did(it, 0, ax), did(it, 0, other)
                else:
                    own = loop_axis.get(m, {}).get(ax)
                    row = loop_axis.get(m, {}).get(other) or did(it, it.vertex_pts[0], other)
                if own:
                    rows[row].append(own)
            for row_axes in rows.values():
                ordered = sorted(set(row_axes), key=lambda i: datum_by_id[i].value)
                for a, b in zip(ordered, ordered[1:]):
                    g = add_gap(ax, a, b, GapKind.PITCH)
                    if g is not None and g.sym_axis is None:
                        mid = (datum_by_id[g.a].value + datum_by_id[g.b].value) / 2
                        d = D[ax].near(mid)
                        if d is not None and global_axis[ax] == d.id:
                            g.sym_axis = d.id

    # circle centres and member axes: offset to the nearest face that sees them
    def offsets(points: list[tuple[str, str, float, float]]) -> None:
        for dxi, dyi, x, y in points:
            for faces, axis, p, q, own in ((vert, "x", x, y, dxi), (horz, "y", y, x, dyi)):
                left = right = None
                for f in faces:
                    if f[1] - tol <= q <= f[2] + tol:
                        if f[0] < p - tol and (left is None or f[0] > left[0]):
                            left = f
                        if f[0] > p + tol and (right is None or f[0] < right[0]):
                            right = f
                for f in (left, right):
                    if f is not None:
                        add_gap(axis, own, f[4], GapKind.OFFSET, sample=(x, y))

    # A line that stops short of a face (a bed line inside a cell, a level line before a
    # wall) keeps its distance from that face: its free end is set out from the face.
    for faces, segs, axis in ((vert, horz, "x"), (horz, vert, "y")):
        for pos, lo, hi, item, _ in segs:
            it = items[item]
            ends = [(lo, -1), (hi, 1)]
            for end, direction in ends:
                k = next((k for k in it.vertex_pts if abs((it.pts[k][0] if axis == "x" else it.pts[k][1]) - end) <= tol and abs((it.pts[k][1] if axis == "x" else it.pts[k][0]) - pos) <= tol), None)
                if k is None or owners[(did(it, k, "x"), did(it, k, "y"))] > 1:
                    continue
                best = None
                for f in faces:
                    if f[3] == item or not (f[1] - tol <= pos <= f[2] + tol):
                        continue
                    gap = (f[0] - end) * direction
                    if gap > tol and (best is None or gap < best[0]):
                        best = (gap, f)
                if best is not None:
                    add_gap(axis, did(it, k, axis), best[1][4], GapKind.OFFSET)

    pts_for_offset = [(did(c, 0, "x"), did(c, 0, "y"), *c.pts[0]) for c in circles]
    for item, m in loop_axis.items():
        if "x" in m:
            poly = [items[item].pts[k] for k in items[item].vertex_pts]
            x0, y0, x1, y1 = _bbox(poly)
            pts_for_offset.append((m["x"], loop_axis[item].get("y") or did(items[item], items[item].vertex_pts[0], "y"), (x0 + x1) / 2, (y0 + y1) / 2))
    if len(pts_for_offset) <= 400:
        offsets(pts_for_offset)

    # ── 10. dimensions: the draftsman's own statement of a size ───────────────────
    for it in items:
        if it.dxftype != "DIMENSION" or it.extra.get("dimtype") not in (0, 1):
            continue
        (x1, y1), (x2, y2) = it.pts[1], it.pts[2]
        if it.extra["dimtype"] == 0:
            ang = it.extra.get("angle", 0.0) % 180
            axis = "x" if abs(ang) < 1e-3 or abs(ang - 180) < 1e-3 else "y" if abs(ang - 90) < 1e-3 else None
        else:
            axis = "y" if abs(x1 - x2) <= tol else "x" if abs(y1 - y2) <= tol else None
        if axis is None:
            continue
        p, q = (x1, x2) if axis == "x" else (y1, y2)
        da, db = D[axis].near(p), D[axis].near(q)
        if da and db and da.id != db.id:
            g = add_gap(axis, da.id, db.id, GapKind.DIM, sample=((x1 + x2) / 2, (y1 + y2) / 2))
            if g is not None:
                g.dims.append(it.index)

    # ── 11. what lies between two facing faces: material, opening, or unknown ──────
    regions: list[tuple[tuple, list[tuple[float, float]], bool]] = []  # bbox, polygon, is_hatch
    for it in items:
        if it.dxftype == "HATCH":
            for poly in it.extra.get("polys", []):
                regions.append((_bbox(poly), poly, True))
    for it in loops:
        poly = [it.pts[k] for k in it.vertex_pts]
        regions.append((_bbox(poly), poly, False))
    circle_regions = [(c.pts[0], c.radius) for c in circles]

    def classify(p: tuple[float, float]) -> GapKind:
        hatched = 0
        depth = 0
        for (x0, y0, x1, y1), poly, is_hatch in regions:
            if not (x0 <= p[0] <= x1 and y0 <= p[1] <= y1):
                continue
            if point_in_poly(p, poly):
                if is_hatch:
                    hatched += 1
                else:
                    depth += 1
        for (cx, cy), r in circle_regions:
            if math.hypot(p[0] - cx, p[1] - cy) < r:
                depth += 1
        if hatched % 2 == 1:
            return GapKind.SOLID
        if depth == 0:
            return GapKind.OPEN
        return GapKind.SOLID if depth % 2 == 1 else GapKind.VOID

    gap_list = sorted(gaps.values(), key=lambda g: int(g.id[1:]))
    for g in gap_list:
        if g.kind == GapKind.OPEN and g.sample is not None:
            g.kind = classify(g.sample)
        # A thin LAYER — faces far shorter than the gap between them (a 7300 x 150 blinding
        # course) — is measured along its run, and a layer's run follows what it lies
        # against (it projects past it). A member of ordinary proportions (a flange, a
        # footing, a slab) keeps its own width as a design value.
        if g.kind in (GapKind.SOLID, GapKind.OPEN) and g.overlap > 0 and g.value > opts.layer_ratio * g.overlap:
            g.lengthwise = True

    # circles: the innermost of concentric circles has a diameter, each one outside it a ring wall
    centres: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for c in circles:
        centres[(did(c, 0, "x"), did(c, 0, "y"))].append(c)
    for (cxd, cyd), cs in centres.items():
        cs.sort(key=lambda c: c.radius)
        prev: Item | None = None
        for c in cs:
            if prev is None:
                gap_list.append(Gap(id=f"r{c.index}", axis="r", a=cxd, b=cyd, value=2 * c.radius, kind=GapKind.DIAMETER, sample=c.pts[0], circle=c.index))  # type: ignore[arg-type]
            elif c.radius - prev.radius > tol:
                gap_list.append(Gap(id=f"r{c.index}", axis="r", a=cxd, b=cyd, value=c.radius - prev.radius, kind=GapKind.RING, sample=c.pts[0], circle=c.index, inner=prev.index))  # type: ignore[arg-type]
            prev = c

    # ── 12. equal gaps → candidate parameters, scored by evidence ─────────────────
    texts = _texts(items)
    clusters = _cluster(gap_list, leg_pairs, datum_by_id, texts, dr, opts)

    constraints = _constraints(dr, structural, slot_datum, loop_axis, global_axis, datum_by_id, circles)
    datums = {d.id: d for d in [*dx.datums, *dy.datums]}
    # annotation / reference / free points follow the nearest structural vertex (both axes from it)
    _attach_free_points(dr, slot_datum, datums)
    stated = _stated_levels(dr, dy)
    sym_counts: dict[str, int] = defaultdict(int)
    for g in gap_list:
        if g.sym_axis:
            sym_counts[g.sym_axis] += 1
    return Analysis(
        drawing=dr,
        datums=datums,
        slot_datum=slot_datum,
        gaps={g.id: g for g in gap_list},
        clusters=clusters,
        constraints=constraints,
        axes=axes,
        global_axis=global_axis,
        notes=notes,
        stated_levels=stated,
        sym_counts=dict(sym_counts),
    )


def _nice_ratio(r: float) -> bool:
    """A slope a draftsman would state: 1:1, 1:1.5, 2:1, 1:12, 1:24 ... (ratio or its inverse)."""
    if r <= 0:
        return False
    for v in (r, 1 / r):
        for k in (1, 2, 4):
            n = v * k
            if round(n) >= 1 and abs(n - round(n)) <= 0.005 * n:
                return True
    return False


def _drawn_patterns(structural: list[Item], tol: float) -> list[Item]:
    """Lines that are a drawn PATTERN, not members: hatching or courses drawn as lines.

    Eight or more identical straight lines (same layer, length and direction), evenly
    spaced side by side. A member repeated a few times (piles, posts) is left alone.
    """
    groups: dict[tuple, list[tuple[float, Item]]] = defaultdict(list)
    for it in structural:
        if len(it.pts) != 2 or it.closed or it.dxftype not in ("LINE", "LWPOLYLINE", "POLYLINE"):
            continue
        (x1, y1), (x2, y2) = it.pts
        L = math.hypot(x2 - x1, y2 - y1)
        if L <= tol:
            continue
        ang = math.atan2(y2 - y1, x2 - x1) % math.pi
        nx, ny = -math.sin(ang), math.cos(ang)
        groups[(it.layer, round(L / (4 * tol)), round(math.degrees(ang) * 2))].append(((x1 * nx + y1 * ny), it))
    out: list[Item] = []
    for members in groups.values():
        if len(members) < 8:
            continue
        members.sort(key=lambda m: m[0])
        steps = [b[0] - a[0] for a, b in zip(members, members[1:])]
        mean = sum(steps) / len(steps)
        if mean > tol and all(abs(s - mean) <= max(tol, 0.02 * mean) for s in steps):
            out.extend(it for _, it in members)
    return out


def _stated_levels(dr: Drawing, dy: _Datums) -> list[tuple[str, int, str, float]]:
    """Notes that state a line's height in metres: '… 101.250' beside a line drawn at y = 101250 mm."""
    out = []
    for it in dr.items:
        if it.dxftype not in ("TEXT", "MTEXT") or not it.text:
            continue
        x, y = it.pts[0]
        h = it.text_height or 1.0
        for tok in NUM_RE.findall(it.text):
            if "." not in tok or len(tok.split(".")[1]) < 2:
                continue
            target = float(tok) * 1000 / dr.units_mm
            d = dy.near(target)
            if d is not None and not d.virtual and abs(d.value - y) <= 40 * h:
                words = " ".join(w for w in re.findall(r"[A-Za-z][A-Za-z.]*", it.text.upper()))
                out.append((d.id, it.index, words, float(tok)))
                break
    return out


def _segment_keys(structural: list[Item], did) -> tuple[set[frozenset], list[tuple[str, str, str, str]]]:
    keys: set[frozenset] = set()
    segs: list[tuple[str, str, str, str]] = []
    for it in structural:
        for i, j in it.segments:
            k = (did(it, i, "x"), did(it, i, "y"), did(it, j, "x"), did(it, j, "y"))
            segs.append(k)
            keys.add(frozenset([(k[0], k[1]), (k[2], k[3])]))
    return keys, segs


def _mirror_score(seg_list, seg_keys, dat: _Datums, datum_by_id, c: float, ax: str) -> float:
    """Share of straight edges whose mirror image about `ax = c` is also an edge."""

    def mirror(d_id: str) -> str | None:
        m = dat.near(2 * c - datum_by_id[d_id].value)
        return m.id if m else None

    hit = 0
    for k in seg_list:
        if ax == "x":
            a, b = mirror(k[0]), mirror(k[2])
            if a and b and frozenset([(a, k[1]), (b, k[3])]) in seg_keys:
                hit += 1
        else:
            a, b = mirror(k[1]), mirror(k[3])
            if a and b and frozenset([(k[0], a), (k[2], b)]) in seg_keys:
                hit += 1
    return hit / max(1, len(seg_list))


# ── evidence from notes ───────────────────────────────────────────────────────


def _texts(items: list[Item]) -> list[tuple[tuple[float, float], list[float], list[str], float]]:
    out = []
    for it in items:
        if it.dxftype in ("TEXT", "MTEXT") and it.text:
            raw = re.sub(r"\\[A-Za-z][^;]*;|[{}]|\\P", " ", it.text)  # strip MTEXT formatting codes
            nums = [float(n) for n in NUM_RE.findall(raw)]
            words = [w for w in re.findall(r"[A-Za-z]{3,}", raw.upper()) if w not in STOP_WORDS]
            if nums:
                out.append((it.pts[0], nums, words, it.text_height or 0.0))
    return out


def _states(text_nums: list[float], v_mm: float) -> bool:
    return any(abs(n - v_mm) <= 0.5 or (abs(n * 1000 - v_mm) <= 0.5 and n != int(n)) for n in text_nums)


def _cluster(gaps, leg_pairs, datum_by_id, texts, dr: Drawing, opts: AnalyseOptions) -> dict[str, Cluster]:
    tol = dr.tol
    ext = max(dr.extent[2] - dr.extent[0], dr.extent[3] - dr.extent[1], 1.0)
    groups: dict[tuple, list[Gap]] = defaultdict(list)
    leg_partner: dict[str, str] = {}
    for gx, gy in leg_pairs:
        if gx.kind == GapKind.LEG and gy.kind == GapKind.LEG:
            leg_partner[gx.id] = gy.id
            leg_partner[gy.id] = gx.id
    for g in gaps:
        if g.kind in (GapKind.ARC, GapKind.SLOPE) or g.value <= tol:
            continue
        key = (g.kind, "xy" if g.kind == GapKind.LEG else g.axis)
        groups[key].append(g)
    clusters: dict[str, Cluster] = {}
    counters: dict[str, int] = defaultdict(int)
    raw: list[Cluster] = []
    for (kind, axis), gs in groups.items():
        gs.sort(key=lambda g: g.value)
        cur: list[Gap] = []
        runs: list[list[Gap]] = []
        for g in gs:
            if cur and g.value - cur[0].value > tol:
                runs.append(cur)
                cur = []
            cur.append(g)
        if cur:
            runs.append(cur)
        for members in runs:
            value = sorted(m.value for m in members)[len(members) // 2]
            v_mm = value * dr.units_mm
            ev: list[Evidence] = []
            conf = BASE_CONFIDENCE.get(kind, 0.35)
            n_dims = sum(len(m.dims) for m in members)
            if n_dims:
                conf += 0.35
                ev.append(Evidence("dimension", 0.35, f"{n_dims} dimension(s) state {v_mm:g}"))
            n = len(members)
            if n > 1:
                w = 0.07 * min(4, n - 1)
                conf += w
                ev.append(Evidence("repeat", w, f"occurs {n} times"))
            if any(m.sym_axis for m in members):
                conf += 0.1
                ev.append(Evidence("symmetric", 0.1, "centred on a symmetry / member axis"))
            r = is_round(v_mm)
            if r == 2:
                conf += 0.05
                ev.append(Evidence("round", 0.05, f"{v_mm:g} mm is a round design value"))
            elif r == 0:
                conf -= 0.3
                ev.append(Evidence("not-round", -0.3, f"{v_mm:.3f} mm looks derived, not designed"))
            if v_mm < 1:
                conf -= 0.5
            if kind in FACE_KINDS:
                ev.append(Evidence("material" if kind == GapKind.SOLID else "void" if kind == GapKind.VOID else "overlap", 0.0, f"faces {kind.value}"))
            suggested = None
            radius = 8.0
            for m in members[:60]:
                if m.sample is None:
                    continue
                for (tx, ty), nums, words, h in texts:
                    lim = max(radius * (h or 0), 0.08 * ext)
                    if abs(tx - m.sample[0]) <= lim and abs(ty - m.sample[1]) <= lim and _states(nums, v_mm):
                        if not any(e.kind == "text" for e in ev):
                            conf += 0.08
                            ev.append(Evidence("text", 0.08, f"a note near it states {v_mm:g}"))
                        if words and suggested is None:
                            suggested = "".join(w.capitalize() for w in words[:2])
            conf = max(0.02, min(0.99, conf))
            status = Status.CONFIRMED if conf >= 0.85 else Status.PROBABLE if conf >= 0.65 else Status.CANDIDATE if conf >= opts.accept_threshold else Status.WEAK
            prefix, label = PREFIX.get((kind, axis if axis != "xy" else "x"), (f"V{axis.upper()}", "Value"))
            c = Cluster(
                id=f"c{len(raw)}",
                name=prefix,
                label=label,
                kind=kind,
                axes={axis} if axis != "xy" else {"x", "y"},
                value=value,
                gaps=[m.id for m in members],
                confidence=round(conf, 3),
                status=status,
                evidence=ev,
                suggested=suggested,
                accepted=status != Status.WEAK,
            )
            for m in members:
                m.cluster = c.id
            raw.append(c)
    # Names: per prefix, largest influence first (more members, then larger value).
    raw.sort(key=lambda c: (c.name, -len(c.gaps), -c.value))
    for c in raw:
        counters[c.name] += 1
        c.name = f"{c.name}{counters[c.name]}"
        clusters[c.id] = c
    return clusters


# ── geometric constraints, reported ─────────────────────────────────────────────


def _constraints(dr, structural, slot_datum, loop_axis, global_axis, datum_by_id, circles) -> list[Constraint]:
    tol = dr.tol
    out: list[Constraint] = []
    horiz, verti = [], []
    by_dir: dict[int, list[int]] = defaultdict(list)
    by_len: dict[tuple, list[int]] = defaultdict(list)
    vertex_owners: dict[tuple[str, str], set[int]] = defaultdict(set)
    lines_on: dict[str, set[int]] = defaultdict(set)
    corners = 0
    for it in structural:
        dirs = []
        for i, j in it.segments:
            (x1, y1), (x2, y2) = it.pts[i], it.pts[j]
            L = math.hypot(x2 - x1, y2 - y1)
            if L <= tol:
                continue
            ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
            if abs(y1 - y2) <= tol:
                horiz.append(it.index)
                lines_on[slot_datum[(it.index, i, "y")][0]].add(it.index)
            elif abs(x1 - x2) <= tol:
                verti.append(it.index)
                lines_on[slot_datum[(it.index, i, "x")][0]].add(it.index)
            else:
                by_dir[round(ang * 10)].append(it.index)
            by_len[(round(L / (2 * tol)), round(ang))].append(it.index)
            dirs.append(ang)
        for k in it.vertex_pts:
            if (it.index, k, "x") in slot_datum:
                vertex_owners[(slot_datum[(it.index, k, "x")][0], slot_datum[(it.index, k, "y")][0])].add(it.index)
        for a, b in zip(dirs, dirs[1:] + (dirs[:1] if it.closed else [])):
            if abs(abs(a - b) - 90) < 0.05:
                corners += 1
    if horiz:
        out.append(Constraint("horizontal", sorted(set(horiz)), 1.0, "construction", f"{len(horiz)} horizontal edges stay horizontal (each end on one y datum)"))
    if verti:
        out.append(Constraint("vertical", sorted(set(verti)), 1.0, "construction", f"{len(verti)} vertical edges stay vertical"))
    if corners:
        out.append(Constraint("perpendicular", [], 1.0, "construction", f"{corners} right-angle corners kept by shared datums"))
    shared = [v for v in vertex_owners.values() if len(v) > 1]
    if shared:
        out.append(Constraint("coincident", sorted({i for s in shared for i in s}), 1.0, "construction", f"{len(shared)} points shared by several entities stay shared"))
    coll = [s for s in lines_on.values() if len(s) > 1]
    if coll:
        out.append(Constraint("collinear", sorted({i for s in coll for i in s}), 1.0, "construction", f"{len(coll)} lines carry edges of several entities"))
    for k, v in by_dir.items():
        if len(set(v)) > 1:
            out.append(Constraint("parallel", sorted(set(v)), 0.9, "reported", f"{len(v)} sloped edges at {k / 10:.1f}°"))
    eq = [v for v in by_len.values() if len(set(v)) > 1]
    if eq:
        out.append(Constraint("equal_length", sorted({i for s in eq for i in s}), 0.7, "parameter", f"{len(eq)} groups of equal edges (kept where their sizes share a parameter)"))
    centres: dict[tuple, list[int]] = defaultdict(list)
    for c in circles:
        centres[(slot_datum[(c.index, 0, "x")][0], slot_datum[(c.index, 0, "y")][0])].append(c.index)
    for v in centres.values():
        if len(v) > 1:
            out.append(Constraint("concentric", v, 1.0, "construction", "circles share a centre"))
    if loop_axis:
        out.append(Constraint("symmetric", sorted(loop_axis), 0.95, "parameter", f"{len(loop_axis)} outlines are mirror-symmetric about their own axis"))
    for ax, d in global_axis.items():
        if d:
            out.append(Constraint("symmetric", [], 0.9, "parameter", f"the drawing is mirror-symmetric about {ax} = {datum_by_id[d].value:.3f}"))
    return out


# ── everything else follows the structure ───────────────────────────────────────


def _attach_free_points(dr: Drawing, slot_datum, datums: dict[str, Datum]) -> None:
    """Annotation, reference and leftover points follow the nearest structural vertex.

    A point is bound to that vertex's x and y datums with fixed offsets — so a note
    beside a wall moves with the wall, and a dimension's extension points (which sit
    exactly on vertices) move with what they measure.
    """
    cell = max(dr.extent[2] - dr.extent[0], dr.extent[3] - dr.extent[1], 1.0) / 64
    grid: dict[tuple[int, int], list[tuple[float, float, str, str]]] = defaultdict(list)
    for (item, pt, axis), (d, _) in slot_datum.items():
        if axis != "x":
            continue
        it = dr.items[item]
        if it.role != Role.STRUCTURAL:
            continue
        x, y = it.pts[pt]
        grid[(int(x // cell), int(y // cell))].append((x, y, d, slot_datum[(item, pt, "y")][0]))
    if not grid:
        return

    def nearest(x: float, y: float):
        cx, cy = int(x // cell), int(y // cell)
        best = None
        for r in range(0, 200):
            for gx in range(cx - r, cx + r + 1):
                for gy in (cy - r, cy + r) if r else (cy,):
                    for v in grid.get((gx, gy), ()):
                        d2 = (v[0] - x) ** 2 + (v[1] - y) ** 2
                        if best is None or d2 < best[0]:
                            best = (d2, v)
                if r:
                    for gy in range(cy - r + 1, cy + r):
                        for gx in (cx - r, cx + r):
                            for v in grid.get((gx, gy), ()):
                                d2 = (v[0] - x) ** 2 + (v[1] - y) ** 2
                                if best is None or d2 < best[0]:
                                    best = (d2, v)
            if best is not None and best[0] <= (r * cell) ** 2:
                return best[1]
        return best[1] if best else None

    for it in dr.items:
        if it.role == Role.FIXED:
            continue
        for k, (x, y) in enumerate(it.pts):
            if (it.index, k, "x") in slot_datum and (it.index, k, "y") in slot_datum:
                continue
            v = nearest(x, y)
            if v is None:
                continue
            _, _, ddx, ddy = v
            if (it.index, k, "x") not in slot_datum:
                slot_datum[(it.index, k, "x")] = (ddx, x - datums[ddx].value)
            if (it.index, k, "y") not in slot_datum:
                slot_datum[(it.index, k, "y")] = (ddy, y - datums[ddy].value)
