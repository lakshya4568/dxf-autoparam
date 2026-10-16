"""Feature operations: change the COUNT of a repeated unit of an existing drawing — add or remove instances — as a NEW drawing.

The regeneration engine (`regen.py`) only moves entities a drawing already has; it never creates or deletes one, and the imported drawing
is never edited. A count change needs entities to appear or go, so it is a different kind of step: a DERIVED drawing.

    detect_repeats(an)           repeated congruent regions at an equal pitch, found from the analysis alone (no kind of structure named)
    plan_count(sm, uid, req)     what the change would do, and whether it can be done faithfully — nothing changes
    build_candidate(...)         the derived DXF, re-imported as a new sheet revision with the parametrization carried over by name

The operation is a periodic extension. One PERIOD of the repeated lattice (a band of one pitch along the repeat's axis, chosen so that it
cuts no member) is copied and the rest of the unit is shifted by the pitch — or the band is deleted and the rest closed up:

    entities wholly beyond the band          shifted by the pitch
    entities wholly inside the band          copied (an annotation only where another instance carries the same one) / deleted
    entities spanning the band               STRETCHED: the vertices beyond the band move; an edge that crosses it must run along the axis
    entities on the symmetry axis            moved by half the pitch (the structure stays symmetric); a per-instance axis is an instance's own
    everything else                          stays

Where this cannot be done faithfully it REFUSES, with the entity and the reason, before anything is written: an outline with detail inside
the repeated unit, a sloped edge across it, a curve, a hatch with curved boundary, a note or dimension that appears in one instance only, a
view stored as a block, another view that the grown one would run into. A change is never made by guessing geometry.

Nothing here knows what the structure is. The noun of the repeated thing (to rewrite "2 CELL" in a note) comes from the production field the
change is about (`nouns`), never from this module.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import ezdxf
import ezdxf.recover
from ezdxf.filemanagement import readfile
from ezdxf.lldxf.const import DXFError, DXFStructureError
from ezdxf.math import Vec3

from .dxf_write import _apply
from .ir import Analysis, Drawing, Role
from .regen import Regenerated
from .topology import of as topology_of

AX = {"x": 0, "y": 1}
LEFT, RIGHT, BAND, STRETCH, PARTIAL, AXIS, FIXED = (
    "left",
    "right",
    "band",
    "stretch",
    "partial",
    "axis",
    "fixed",
)
ANNOTATION = {"DIMENSION", "HATCH", "TEXT", "MTEXT", "LEADER", "ATTRIB"}
NO_STRETCH = {
    "ARC",
    "CIRCLE",
    "ELLIPSE",
    "SPLINE",
    "TEXT",
    "MTEXT",
    "POINT",
    "INSERT",
    "ATTRIB",
    "ATTDEF",
}
MAX_REFUSALS = 12


class FeatureRefused(ValueError):
    """The operation cannot be done faithfully (or not here): the reasons, and nothing was changed."""

    def __init__(self, reasons: list[str] | str, question: dict | None = None):
        self.reasons = [reasons] if isinstance(reasons, str) else list(reasons)
        self.question = question  # a decision only a person can make (the plan is then `needs_decision`, not refused)
        super().__init__("; ".join(self.reasons[:4]))


# ── repeats, from the analysis ───────────────────────────────────────────────────


@dataclass
class Repeat:
    """Congruent regions at an equal pitch along one axis (cells, piers, bays): the LATTICE a count change extends."""

    id: str
    axis: str
    pitch: float  # drawing units
    count: int
    first: float  # low edge of the first instance along the axis
    width: float  # extent of one instance along the axis
    height: float  # across the axis
    area: float
    regions: list[str]
    perp: float = 0.0  # where the row lies across the axis

    def lo(self, k: int) -> float:
        return self.first + k * self.pitch

    def describe(self, um: float = 1.0) -> dict:
        return {
            "id": self.id,
            "axis": self.axis,
            "count": self.count,
            "pitch_mm": round(self.pitch * um, 3),
            "size_mm": [round(self.width * um, 3), round(self.height * um, 3)],
            "regions": self.regions,
        }


def detect_repeats(an) -> list[Repeat]:
    """Every run of two or more congruent regions standing in a row at an equal pitch, biggest first. Read from the topology the analysis
    already has; what the regions ARE (a cell, a pier, a bay) is not looked at."""
    topo = topology_of(an)
    tol = an.drawing.tol
    t2 = 2 * tol
    clusters: list[list] = []  # [w, h, area, [region]]
    for r in sorted(topo.regions, key=lambda r: -r.area):
        w, h = r.bbox[2] - r.bbox[0], r.bbox[3] - r.bbox[1]
        for c in clusters:
            if (
                abs(w - c[0]) <= t2
                and abs(h - c[1]) <= t2
                and abs(r.area - c[2]) <= 0.01 * c[2] + t2 * max(w, h)
                and _congruent(r, c[3][0], t2)
            ):
                c[3].append(r)
                break
        else:
            clusters.append([w, h, r.area, [r]])
    found: list[Repeat] = []
    for _w, _h, area, rs in clusters:
        if len(rs) < 2:
            continue
        for name, ax in AX.items():
            rows: list[list] = []
            for r in sorted(rs, key=lambda r: r.bbox[1 - ax]):
                if rows and abs(r.bbox[1 - ax] - rows[-1][0].bbox[1 - ax]) <= t2:
                    rows[-1].append(r)
                else:
                    rows.append([r])
            for row in rows:
                row.sort(key=lambda r: r.bbox[ax])
                wid = row[0].bbox[ax + 2] - row[0].bbox[ax]
                run = [row[0]]
                step: float | None = None
                for r in row[1:]:
                    d = r.bbox[ax] - run[-1].bbox[ax]
                    if d >= wid - t2 and (step is None or abs(d - step) <= t2):
                        run.append(r)
                        step = step if step is not None else d
                        continue
                    _flush(found, run, ax, name, area)
                    run = [run[-1], r] if d >= wid - t2 else [r]
                    step = d if d >= wid - t2 else None
                _flush(found, run, ax, name, area)
    found.sort(key=lambda r: -(r.count * r.area))
    for n, r in enumerate(found, 1):
        r.id = f"Rp{n}"
    return found


def _congruent(a, b, t2: float) -> bool:
    """The same outline, moved: every vertex of one is a vertex of the other, relative to the corner of its box (a mirrored shape is not the same)."""
    pa = [(x - a.bbox[0], y - a.bbox[1]) for x, y in a.ring]
    pb = [(x - b.bbox[0], y - b.bbox[1]) for x, y in b.ring]
    if len(pa) != len(pb) or len(pa) > 400:
        return len(pa) == len(pb)
    return all(any(abs(x - u) <= t2 and abs(y - v) <= t2 for u, v in pb) for x, y in pa)


def _flush(found: list[Repeat], run: list, ax: int, name: str, area: float) -> None:
    if len(run) < 2:
        return
    r0 = run[0]
    pitch = (run[-1].bbox[ax] - r0.bbox[ax]) / (len(run) - 1)
    found.append(
        Repeat(
            id="",
            axis=name,
            pitch=pitch,
            count=len(run),
            first=r0.bbox[ax],
            width=r0.bbox[ax + 2] - r0.bbox[ax],
            height=r0.bbox[3 - ax] - r0.bbox[1 - ax],
            area=area,
            regions=[r.id for r in run],
            perp=r0.bbox[1 - ax],
        )
    )


def instances(an, rep: Repeat) -> int:
    """How many instances of this repeat the drawing shows now: regions of its size in its row, standing on its lattice."""
    t2 = 2 * an.drawing.tol
    ax = AX[rep.axis]
    n = 0
    for r in topology_of(an).regions:
        w, h = r.bbox[ax + 2] - r.bbox[ax], r.bbox[3 - ax] - r.bbox[1 - ax]
        if (
            abs(w - rep.width) > t2
            or abs(h - rep.height) > t2
            or abs(r.bbox[1 - ax] - rep.perp) > t2
        ):
            continue
        ph = (r.bbox[ax] - rep.first) % rep.pitch
        if min(ph, rep.pitch - ph) <= t2 and r.bbox[ax] >= rep.first - t2:
            n += 1
    return n


def _lattices(reps: list[Repeat], t2: float) -> list[list[Repeat]]:
    """Repeats of one pitch along one axis, the best supported first. The lattice a drawing is set out on shows itself in many of its members (the
    cells, what stands between them, their corners, the same bays in the plan), where a chance pair of equal members shows once: the support of a
    lattice is the sum over its repeats of (instances − 1)², so a third equal member at the same pitch counts for more than another pair.
    """
    out: list[list[Repeat]] = []
    for r in reps:
        for grp in out:
            if r.axis == grp[0].axis and abs(r.pitch - grp[0].pitch) <= t2:
                grp.append(r)
                break
        else:
            out.append([r])
    out.sort(key=lambda g: -_support(g))
    return out


def _support(lattice: list[Repeat]) -> int:
    return sum((r.count - 1) ** 2 for r in lattice)


STANDS_OUT = 3  # the support a lattice needs to be taken without being named: two chance pairs do not make one


# ── the request ──────────────────────────────────────────────────────────────────


def _normalise(req: dict) -> dict:
    kind = req.get("kind", "set_count")
    if kind != "set_count":
        raise FeatureRefused(
            f"unknown operation {kind!r}: this engine makes set_count (add or remove instances of a repeated unit)"
        )
    try:
        count = int(req["count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FeatureRefused(
            "count: the number of instances the drawing should show (a whole number)"
        ) from exc
    if count < 1:
        raise FeatureRefused("count must be at least 1")
    at = req.get("at", "end")
    if at not in ("end", "start") and not (
        isinstance(at, int) and not isinstance(at, bool) and at >= 0
    ):
        raise FeatureRefused(
            "at: 'end', 'start' or the index (from 0) the new instance takes / the first one removed"
        )
    out = {"kind": kind, "count": count, "at": at}
    if req.get("detached") not in (None, "move", "keep"):
        raise FeatureRefused(
            "detached: 'move' (what stands apart beyond the unit moves with it) or 'keep' (it stays where it is)"
        )
    for k in (
        "unit",
        "repeat",
        "current",
        "binding",
        "field",
        "nouns",
        "axis",
        "drop_plans",
        "detached",
    ):
        if req.get(k) is not None:
            out[k] = req[k]
    return out


def _label(it) -> str:
    return f"{it.dxftype} {it.src or it.handle} ({it.layer})"


# ── the geometry the unit has now ────────────────────────────────────────────────


@dataclass
class Base:
    """The unit the operation is worked out on: its entities, and its analysis on the geometry as it stands."""

    dr: Drawing
    path: str
    items: list[int]  # the unit's entities, as indices of `dr`
    an: Analysis  # the unit's analysis (the sheet's own: ids the parametrization uses)
    sub: Drawing


def _base(sm, uid: str) -> Base:
    u = sm.unit(uid)
    return Base(dr=sm.dr, path=sm.path, items=list(u.items), an=u.an, sub=u.sub)


# ── scanning the unit against a band ─────────────────────────────────────────────


def _extent(it, ax: int) -> tuple[float, float]:
    t = it.dxftype
    if t == "DIMENSION" and it.extra.get("dimtype") in (0, 1):
        cs = [
            it.pts[1][ax],
            it.pts[2][ax],
        ]  # the measured points: where the text sits is placement
    else:
        cs = [p[ax] for p in it.pts]
    if t in ("CIRCLE", "ARC") and it.radius:
        c = it.pts[0][ax]
        cs += [c - it.radius, c + it.radius]
    if t in ("ELLIPSE", "SPLINE"):
        cs += [p[ax] for poly in it.display for p in poly]
    return min(cs), max(cs)


def _classify(a: float, b: float, lo: float, hi: float, tol: float) -> str:
    if (
        b - a <= tol
    ):  # a point, a line across the axis: the band is half open [lo, hi), so every boundary line belongs to exactly one side
        m = (a + b) / 2
        return LEFT if m < lo - tol else RIGHT if m >= hi - tol else BAND
    if b <= lo + tol:
        return LEFT
    if a >= hi - tol:
        return RIGHT
    if a >= lo - tol and b <= hi + tol:
        return BAND
    if a <= lo + tol and b >= hi - tol:
        return STRETCH
    return PARTIAL


def _same(a, b, tol: float, shift: float, ax: int) -> bool:
    """`b` is `a` moved by `shift` along the axis: same kind, layer, text, points."""
    if (
        a.dxftype != b.dxftype
        or a.layer != b.layer
        or (a.text or "") != (b.text or "")
        or len(a.pts) != len(b.pts)
    ):
        return False
    pairs = list(zip(a.pts, b.pts, strict=True))
    if a.dxftype == "DIMENSION" and a.extra.get("dimtype") in (0, 1):
        pairs = pairs[
            1:3
        ]  # what it measures: where its line and its text sit is placement, and instances place theirs by hand
    return all(
        abs(p[ax] + shift - q[ax]) <= 2 * tol and abs(p[1 - ax] - q[1 - ax]) <= 2 * tol
        for p, q in pairs
    )


class _Twins:
    """Does another instance carry the same entity? (what makes an annotation per-instance, and so safe to copy or delete)"""

    def __init__(
        self,
        dr: Drawing,
        items: list[int],
        ax: int,
        pitch: float,
        count: int,
        tol: float,
    ):
        self.dr, self.ax, self.pitch, self.count, self.tol = dr, ax, pitch, count, tol
        self.bucket: dict[tuple, list[int]] = defaultdict(list)
        for i in items:
            it = dr.items[i]
            if it.anchor is None:
                self.bucket[(it.dxftype, it.layer, len(it.pts))].append(i)

    def has(self, i: int) -> bool:
        it = self.dr.items[i]
        for j in self.bucket[(it.dxftype, it.layer, len(it.pts))]:
            if j == i:
                continue
            o = self.dr.items[j]
            for n in range(1, self.count + 1):
                if _same(it, o, self.tol, n * self.pitch, self.ax) or _same(
                    it, o, self.tol, -n * self.pitch, self.ax
                ):
                    return True
        return False


def _stretchable(it, lo: float, hi: float, tol: float, ax: int, doc) -> str | None:
    """Why this entity cannot be stretched across the band — or None when it can."""
    t = it.dxftype
    if t in NO_STRETCH:
        return f"{_label(it)} is not a straight outline: it cannot be stretched across the repeated unit"
    if t == "DIMENSION":
        if it.extra.get("dimtype") not in (0, 1):
            return f"{_label(it)} is not a linear dimension: it cannot be stretched across the repeated unit"
        bad = [p for p in (it.pts[1], it.pts[2]) if lo + tol < p[ax] < hi - tol]
        return f"{_label(it)} measures from inside the repeated unit" if bad else None
    if any(abs(b) > 1e-9 for b in it.bulges):
        return f"{_label(it)} has curved edges: it cannot be stretched across the repeated unit"
    if t == "HATCH":
        e = doc.entitydb.get(it.handle) if doc is not None else None
        if e is None:
            return f"{_label(it)}: its boundary cannot be read"
        for path in e.paths:
            if not hasattr(path, "vertices") and any(
                type(x).__name__ != "LineEdge" for x in path.edges
            ):
                return f"{_label(it)} has a curved boundary: it cannot be stretched across the repeated unit"
        rings = it.extra.get("rings") or []
        verts = [it.pts[k][ax] for r in rings for k in r]
        edges = [
            (it.pts[r[i]], it.pts[r[(i + 1) % len(r)]])
            for r in rings
            for i in range(len(r))
        ]
    else:
        verts = [p[ax] for p in it.pts]
        n = len(it.pts)
        edges = [(it.pts[i], it.pts[i + 1]) for i in range(n - 1)] + (
            [(it.pts[-1], it.pts[0])] if it.closed and n > 2 else []
        )
    if any(lo + tol < c < hi - tol for c in verts):
        return f"{_label(it)} has vertices inside the repeated unit: stretching it would not repeat that detail"
    for p, q in edges:
        across = (p[ax] <= lo + tol and q[ax] >= hi - tol) or (
            q[ax] <= lo + tol and p[ax] >= hi - tol
        )
        if across and abs(p[1 - ax] - q[1 - ax]) > tol:
            return f"{_label(it)} has an edge across the repeated unit that is not parallel to the axis: stretching it would change its slope"
    return None


@dataclass
class Scan:
    kinds: dict[int, str]
    refusals: list[str]
    warnings: list[str]
    nested: dict[str, set[str]] = field(default_factory=dict)


def _scan(
    base: Base,
    doc,
    lo: float,
    hi: float,
    ax: int,
    tol: float,
    axis_value: float | None,
    twins: _Twins,
    items: list[int],
) -> Scan:
    dr = base.dr
    kinds: dict[int, str] = {}
    refusals: list[str] = []
    nested: dict[str, set[str]] = defaultdict(set)
    hatch_in_region = {
        base.items[h] for r in topology_of(base.an).regions for h in r.hatches
    }  # a hatch that fills a region is that region's material
    for i in items:
        it = dr.items[i]
        if (
            it.anchor is not None
        ):  # the contents of a rigid symbol follow its insertion point
            continue
        if it.role == Role.FIXED:
            kinds[i] = FIXED
            continue
        a, b = _extent(it, ax)
        kind = _classify(a, b, lo, hi, tol)
        if (
            axis_value is not None
            and b - a <= tol
            and abs((a + b) / 2 - axis_value) <= tol
            and it.dxftype != "INSERT"
            and not twins.has(i)
        ):
            kind = AXIS  # the structure's own centre: it moves with the middle, not with an instance
        if kind == PARTIAL:
            refusals.append(
                f"{_label(it)} lies across the edge of the repeated unit (it spans {a:g}…{b:g}, the unit {lo:g}…{hi:g}): "
                "it belongs to neither one instance nor the rest"
            )
        elif kind == STRETCH:
            why = _stretchable(it, lo, hi, tol, ax, doc)
            if why:
                refusals.append(why)
        elif (
            kind == BAND
            and it.dxftype in ANNOTATION
            and not (it.dxftype == "HATCH" and i in hatch_in_region)
            and not twins.has(i)
        ):
            refusals.append(
                f"{_label(it)} stands inside the repeated unit but no other instance has one like it: whether every instance "
                "carries it cannot be told, so it is neither copied nor removed"
            )
        if it.src and "/" in it.src and it.anchor is None:
            nested[it.handle].add(kind)
        kinds[i] = kind
    for top, ks in nested.items():
        movers = ks - {LEFT, FIXED}
        if not movers:
            continue
        everyone = [j for j, o in enumerate(dr.items) if o.handle == top]
        if movers != {RIGHT} or any(j not in kinds for j in everyone):
            refusals.append(
                f"the view stored in block reference {top} would be reshaped (it holds entities that stay, move, stretch or repeat): "
                "explode the block first"
            )
    return Scan(kinds=kinds, refusals=refusals, warnings=[], nested=dict(nested))


# ── the operation: which band, which entities ────────────────────────────────────


@dataclass
class Operation:
    request: dict
    uid: str
    base: Base
    rep: Repeat
    ax: int
    tol: float
    mode: str  # insert | remove
    delta: int  # instances added (+) or removed (-)
    lo: float
    hi: float
    cut: str  # insert: "left" | "right" — which side of the band the new instances go
    band: str  # which band shape was used: L (instance + the member after it) or R (the member before it + instance)
    kinds: dict[int, str]
    axis_value: float | None
    first_removed: int = 0
    warnings: list[str] = field(default_factory=list)
    notes: dict[int, str] = field(default_factory=dict)  # item → rewritten text
    doc: object = None

    @property
    def shift(self) -> float:
        """What lies beyond the band moves by this, along the axis."""
        return self.delta * self.rep.pitch

    def stays(self) -> list[int]:
        return [i for i, k in self.kinds.items() if k == LEFT]


def _band_candidates(
    rep: Repeat, mode: str, at, d: int
) -> list[tuple[float, float, str, str, int]]:
    """(lo, hi, cut, shape, index) in the order they are tried. A band is one pitch wide for an insertion (that period is copied), `d` pitches
    for a removal; the L shape is an instance with the member after it, the R shape the member before it with the instance.
    """
    n, P, w = rep.count, rep.pitch, rep.width
    out: list[tuple[float, float, str, str, int]] = []

    def L(k: int, width: int) -> tuple[float, float]:
        return rep.lo(k), rep.lo(k) + width * P

    def R(k: int, width: int) -> tuple[float, float]:
        return rep.lo(k) + w - width * P, rep.lo(k) + w

    if mode == "insert":
        i = n if at == "end" else 0 if at == "start" else min(int(at), n)
        order = (
            [("B", i), ("C", i)]
            if i == n
            else [("A", i)] if i == 0 else [("A", i), ("B", i), ("C", i), ("D", i)]
        )
        for tag, i in order:
            if tag == "A" and i <= n - 1:
                out.append((*L(i, 1), "left", "L", i))
            elif tag == "B" and i >= 1:
                out.append((*R(i - 1, 1), "right", "R", i))
            elif tag == "C" and i >= 1:
                out.append((*L(i - 1, 1), "right", "L", i))
            elif tag == "D" and 1 <= i <= n - 1:
                out.append((*R(i, 1), "left", "R", i))
    else:
        k = (
            n - d
            if at == "end"
            else 0 if at == "start" else max(0, min(int(at), n - d))
        )
        shapes = (
            [("R", k + d - 1), ("L", k)] if k + d == n else [("L", k), ("R", k + d - 1)]
        )
        for shape, j in shapes:
            lo, hi = R(j, d) if shape == "R" else L(j, d)
            out.append((lo, hi, "none", shape, k))
    return out


def _select_repeat(
    reps: list[Repeat], req: dict, tol: float, um: float
) -> tuple[Repeat | None, list[str], list[dict]]:
    """The repeat a count is about: the one named (`repeat`), else the lattice the drawing is clearly set out on — and then the repeat of it whose
    count is the one stated. Where no lattice stands out the answer is a question (the candidates, with ids), never a guess.
    """
    ax = req.get("axis")
    cands = [r for r in reps if ax is None or r.axis == ax]
    cur = req.get("current")
    if req.get("repeat"):
        pool = [r for r in reps if r.id == req["repeat"]]
        if not pool:
            return (
                None,
                [
                    f"no repeat {req['repeat']!r} in this unit (it shows {[r.id for r in reps] or 'none'})"
                ],
                [],
            )
    else:
        lats = _lattices(cands, 2 * tol)
        if not lats:
            return (
                None,
                [
                    "no repeated unit: the unit shows no two congruent regions at an equal pitch, so there is no pitch to extend"
                ],
                [],
            )
        top = lats[0]
        if _support(top) < STANDS_OUT or (
            len(lats) > 1 and _support(top) < 2 * _support(lats[1])
        ):
            return None, [], [r.describe(um) for lat in lats[:4] for r in lat[:1]]
        pool = top
    n = max(
        r.count for r in pool
    )  # the instances are the most numerous members of the lattice (what stands between them is one fewer)
    if cur is not None and n != int(cur):
        return (
            None,
            [
                f"the drawing's repeated unit shows {n} instance(s), not {int(cur)} as stated: nothing says which repeat the count is about"
            ],
            [],
        )
    return max((r for r in pool if r.count == n), key=lambda r: r.area), [], []


def _order(
    sm, uid: str, req: dict, base: Base, doc, with_texts: bool = True
) -> tuple[Operation | None, dict]:
    """The operation for a request on a unit — or None and the plan's reasons. Reads only."""
    u = sm.unit(uid)
    um = u.sub.units_mm
    tol = base.dr.tol
    info: dict = {"refusals": [], "questions": [], "warnings": [], "repeats": []}
    reps = detect_repeats(base.an)
    rep, why, ask = _select_repeat(reps, req, tol, um)
    info["repeats"] = [r.describe(um) for r in reps[:6]]
    if rep is None:
        info["refusals"] += why
        if ask:
            info["questions"].append(
                {
                    "text": "No repeated unit stands out clearly in this unit: which repeat is the count about? (pass its id as `repeat`)",
                    "options": [
                        f"{a['id']}: {a['count']} × {a['size_mm']} mm at {a['pitch_mm']} mm"
                        for a in ask
                    ],
                    "about": "repeat",
                }
            )
        return None, info
    n, m = rep.count, int(req["count"])
    info["repeat"] = rep.describe(um)
    if m == n:
        info["refusals"].append(f"the drawing already shows {n} instance(s)")
        return None, info
    mode, d = ("insert", m - n) if m > n else ("remove", n - m)
    if mode == "remove" and m < 1:
        info["refusals"].append("a drawing keeps at least one instance")
        return None, info
    ax = AX[rep.axis]
    islands = _islands(
        base,
        [r for r in reps if r.axis == rep.axis and abs(r.pitch - rep.pitch) <= 2 * tol],
    )
    ga = base.an.global_axis.get(rep.axis)
    axis_value = None
    if ga and ga in base.an.datums:
        xs = [
            p[ax]
            for k in base.items
            if base.dr.items[k].role == Role.STRUCTURAL and k not in islands
            for p in base.dr.items[k].pts
        ]
        axv = base.an.datums[ga].value
        if xs and abs(axv - (min(xs) + max(xs)) / 2) <= 2 * tol:
            axis_value = axv
    twins = _Twins(base.dr, base.items, ax, rep.pitch, n, tol)
    first_reasons: list[str] = []
    chosen = None
    tried = 0
    for lo, hi, cut, shape, k in _band_candidates(rep, mode, req["at"], d):
        tried += 1
        sc = _scan(base, doc, lo, hi, ax, tol, axis_value, twins, base.items)
        sc.refusals += _collide(sm, uid, rep, ax, mode, d, base, um)
        if not first_reasons:
            first_reasons = sc.refusals
        if not sc.refusals:
            chosen = (lo, hi, cut, shape, k, sc)
            break
    if chosen is None:
        info["refusals"] += (
            first_reasons or ["no band of the repeated unit can be placed there"]
        )[:MAX_REFUSALS]
        if tried > 1:
            info["refusals"].append(
                f"(tried {tried} placements of the unit; the reasons are those of the first)"
            )
        return None, info
    lo, hi, cut, shape, k, sc = chosen
    det = [i for i, kd in sc.kinds.items() if kd == RIGHT and i in islands]
    if det and req.get("detached") is None:
        info["questions"].append(
            {
                "text": f"{len(det)} entit(ies) beyond the repeated unit touch nothing of the structure ({', '.join(_label(base.dr.items[i]) for i in det[:3])}"
                f"{'…' if len(det) > 3 else ''}): do they move with it, or stay where they are?",
                "options": ["move", "keep"],
                "about": "detached",
            }
        )
        return None, info
    if det and req["detached"] == "keep":
        for i in det:
            sc.kinds[i] = LEFT
        runs = _runs_into(
            base, det, sc.kinds, ax, rep.pitch * d if mode == "insert" else 0.0, tol
        )
        if runs:
            info["refusals"] += runs
            return None, info
    op = Operation(
        request=req,
        uid=uid,
        base=base,
        rep=rep,
        ax=ax,
        tol=tol,
        mode=mode,
        delta=d if mode == "insert" else -d,
        lo=lo,
        hi=hi,
        cut=cut,
        band=shape,
        kinds=sc.kinds,
        axis_value=axis_value,
        first_removed=k if mode == "remove" else 0,
        doc=doc,
    )
    if with_texts:
        _count_notes(op, n, m)
    return op, info


def _islands(base: Base, lattice: list[Repeat]) -> set[int]:
    """Structural entities that stand apart: in a piece of linework that touches no instance of the lattice. Whether such a piece belongs to the
    structure (a detail beside it) is not for the engine to say."""
    topo = topology_of(base.an)
    local = {s: k for k, s in enumerate(base.items)}
    parent = {k: k for k in range(len(base.items))}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for k, others in topo.connections.items():
        for o in others:
            parent[find(k)] = find(o)
    by_id = {r.id: r for r in topo.regions}
    members = {
        find(i) for rep in lattice for rid in rep.regions for i in by_id[rid].items
    }
    return {
        s
        for s, k in local.items()
        if base.dr.items[s].role == Role.STRUCTURAL and find(k) not in members
    }


def _runs_into(
    base: Base, kept: list[int], kinds: dict[int, str], ax: int, grow: float, tol: float
) -> list[str]:
    """What stays where it is while the structure grows over it."""
    dr = base.dr
    movers = [
        i
        for i, kd in kinds.items()
        if kd not in (FIXED,) and i not in kept and dr.items[i].role == Role.STRUCTURAL
    ]
    if not movers or grow <= 0:
        return []
    far = max(_extent(dr.items[i], ax)[1] for i in movers) + grow
    out = []
    for i in kept:
        a, b = _extent(dr.items[i], ax)
        if a < far - tol and b > far - grow + tol:
            out.append(
                f"{_label(dr.items[i])} stays where it is but the structure would grow over it (to {far:g}): it has to move, or the count stays"
            )
    return out


def _collide(
    sm, uid: str, rep: Repeat, ax: int, mode: str, d: int, base: Base, um: float
) -> list[str]:
    """Another view the grown one would run into (the drawing is never rearranged around it)."""
    if mode != "insert":
        return []
    u = sm.units[uid]
    boxes = [sm.layout.group(v).bbox for v in u.views]
    ub = (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
    grown = list(ub)
    grown[ax + 2] += d * rep.pitch
    out = []
    for g in sm.layout.groups:
        if g.id in u.views or g.kind == "title_block":
            continue
        gb = g.bbox
        if (
            gb[0] <= grown[2]
            and gb[2] >= grown[0]
            and gb[1] <= grown[3]
            and gb[3] >= grown[1]
            and not (
                gb[0] <= ub[2] and gb[2] >= ub[0] and gb[1] <= ub[3] and gb[3] >= ub[1]
            )
        ):
            out.append(
                f"the view would grow by {d * rep.pitch * um:g} mm into {g.id}{' (' + g.name + ')' if g.name else ''}: it is not moved — "
                "make room first, or keep the drawing as it is"
            )
    return out


def _count_notes(op: Operation, n: int, m: int) -> None:
    """Notes that state the old count with the noun of the repeated thing are rewritten; any other note naming the old count is said, not changed."""
    nouns = [str(x).lower() for x in (op.request.get("nouns") or []) if str(x).strip()]
    dr = op.base.dr
    for i in op.base.items:
        it = dr.items[i]
        if (
            it.dxftype not in ("TEXT", "MTEXT")
            or not it.text
            or op.kinds.get(i) not in (LEFT, RIGHT, AXIS, STRETCH, BAND)
        ):
            continue
        text = it.text
        if nouns:
            pat = re.compile(
                rf"(?<![\d.]){n}(?![\d.])(\s*[-–]?\s*)(?=(?:{'|'.join(map(re.escape, nouns))})\b)",
                re.IGNORECASE,
            )
            if pat.search(text) and op.kinds[i] != BAND:
                op.notes[i] = pat.sub(lambda mo: f"{m}{mo.group(1)}", text, count=1)
                continue
        if re.search(rf"(?<![\d.]){n}(?![\d.])", text):
            op.warnings.append(
                f"the note '{text.splitlines()[0][:50]}' contains {n}: if it states the count, it is left as drawn — correct it by hand"
            )


# ── writing the derived drawing ──────────────────────────────────────────────────


@dataclass
class Derived:
    path: str
    copies: dict[int, list[str]]  # base item → handles of its copies (in order)
    deleted: list[int]
    report: dict


def _moved(pts, d: float, ax: int) -> list[tuple[float, float]]:
    return [(p[0] + d, p[1]) if ax == 0 else (p[0], p[1] + d) for p in pts]


def _stretched(it, op: Operation) -> list[tuple[float, float]]:
    ax, D = op.ax, op.shift
    out = []
    for p in it.pts:
        c = p[ax]
        d = (
            0.0 if c <= op.lo + op.tol else D if c >= op.hi - op.tol else D / 2
        )  # inside the band only a placement (a dimension's text) can be
        out.append((p[0] + d, p[1]) if ax == 0 else (p[0], p[1] + d))
    return out


def derive(op: Operation, out_path: str) -> Derived:
    base = op.base
    try:
        doc, _ = ezdxf.recover.readfile(base.path)
    except DXFStructureError:
        doc = readfile(base.path)
    db = doc.entitydb
    dr = base.dr
    ax, D, P = op.ax, op.shift, op.rep.pitch
    report = {
        "updated": 0,
        "dimensions_rendered": 0,
        "dimension_render_failed": 0,
        "texts_changed": 0,
        "kept": 0,
        "blocks_exploded": 0,
        "blocks_moved": 0,
        "symbols_moved": 0,
        "_units_mm": dr.units_mm,
        "_item_units_mm": {},
    }
    reg = Regenerated(values={}, datum={}, pts={}, radius={}, texts=dict(op.notes))
    copies: dict[int, list[str]] = {}
    deleted: list[int] = []
    moved_blocks: set[str] = set()
    for i, kind in op.kinds.items():
        it = dr.items[i]
        if kind in (LEFT, FIXED):
            continue
        e = db.get(it.handle)
        if e is None:
            raise FeatureRefused(
                f"{_label(it)}: the entity is not in the file it was read from"
            )
        nested = bool(it.src and "/" in it.src)
        if (
            nested
        ):  # a view block that moves as one piece: its insertion point moves, once
            if it.handle not in moved_blocks and kind == RIGHT:
                moved_blocks.add(it.handle)
                ins = e.dxf.insert
                e.dxf.insert = ins + Vec3(*((D, 0, 0) if ax == 0 else (0, D, 0)))
                report["blocks_moved"] += 1
            continue
        reg.texts = {**reg.texts}
        if kind == RIGHT:
            _place(e, it, _moved(it.pts, D, ax), reg, report)
        elif kind == AXIS:
            _place(e, it, _moved(it.pts, D / 2, ax), reg, report)
        elif kind == STRETCH:
            _place(e, it, _stretched(it, op), reg, report)
        elif kind == BAND and op.mode == "remove":
            layout = cast(Any, e).get_layout()
            if e.dxftype() == "DIMENSION" and e.dxf.hasattr("geometry"):
                block = e.dxf.geometry
                layout.delete_entity(e)
                if block in doc.blocks:
                    doc.blocks.delete_block(block, safe=False)
            else:
                layout.delete_entity(e)
            deleted.append(i)
        elif kind == BAND:
            offsets = [(0 if op.cut == "left" else P) + j * P for j in range(op.delta)]
            own = D if op.cut == "left" else 0.0
            handles = []
            layout = cast(Any, e).get_layout()
            for off in offsets:
                c = e.copy()
                layout.add_entity(c)
                if c.dxftype() == "HATCH" and c.dxf.hasattr("associative"):
                    c.dxf.associative = 0
                _place(c, it, _moved(it.pts, off, ax), reg, report)
                handles.append(c.dxf.handle)
            copies[i] = handles
            if own:
                _place(e, it, _moved(it.pts, own, ax), reg, report)
    if report["dimension_render_failed"]:
        raise FeatureRefused(
            "a dimension could not be re-drawn at its new place: "
            + "; ".join(report.get("dimension_render_errors", [])[:2])
        )
    doc.saveas(out_path)
    for k in ("_units_mm", "_item_units_mm"):
        report.pop(k, None)
    return Derived(path=out_path, copies=copies, deleted=deleted, report=report)


def _place(e, it, pts, reg: Regenerated, report: dict) -> None:
    if e.dxftype() == "INSERT":
        e.dxf.insert = Vec3(pts[0][0], pts[0][1], e.dxf.insert.z)
        report["symbols_moved"] += 1
        return
    _apply(e, it, pts, reg, report)


# ── what the plan says ───────────────────────────────────────────────────────────


def _effects(op: Operation) -> dict:
    c = Counter(op.kinds.values())
    return {
        "stay": c.get(LEFT, 0) + c.get(FIXED, 0),
        "shift": c.get(RIGHT, 0),
        "stretch": c.get(STRETCH, 0),
        "on_axis": c.get(AXIS, 0),
        "copied" if op.mode == "insert" else "deleted": c.get(BAND, 0)
        * (abs(op.delta) if op.mode == "insert" else 1),
    }


def plan_summary(op: Operation, um: float) -> dict:
    n = op.rep.count
    m = int(op.request["count"])
    return {
        "axis": op.rep.axis,
        "from_count": n,
        "to_count": m,
        "mode": op.mode,
        "pitch_mm": round(op.rep.pitch * um, 3),
        "grows_mm": round(op.shift * um, 3),
        "band_mm": [round(op.lo * um, 3), round(op.hi * um, 3)],
        "band": op.band,
        "effects": _effects(op),
        "notes_rewritten": [
            {"from": (op.base.dr.items[i].text or "")[:60], "to": t[:60]}
            for i, t in op.notes.items()
        ],
    }


def request_digest(sm, uid: str, req: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            [sm.fingerprint(), sm.revision, uid, req], sort_keys=True, default=str
        ).encode()
    ).hexdigest()[:12]


def plan_count(sm, uid: str, request: dict, workdir: Path | None = None) -> dict:
    """What a change of count would do on this unit, and whether it can be done faithfully — through the whole chain (the derived drawing, its
    re-import, the parametrization carried over, the production guards at the new count), without changing the sheet. `status`: ready |
    refused | needs_decision. A plan is accepted by `accept(plan)` and applied by `SheetModel.apply_feature`, which builds it again.
    """
    own = workdir is None
    work = Path(workdir or tempfile.mkdtemp(prefix="feature-plan-"))
    try:
        plan = build_candidate(sm, uid, request, work).plan
        plan.pop(
            "derived", None
        )  # the file is gone with the work folder: a plan describes, it leaves nothing behind
        return plan
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)


def accept_plan(plan: dict, by: str = "person") -> dict:
    if plan.get("status") != "ready":
        raise ValueError(
            f"plan {plan.get('id')} is {plan.get('status')}: "
            + "; ".join(
                [q["text"] for q in plan.get("questions", [])][:2]
                + plan.get("refusals", [])[:2]
            )
        )
    out = copy.deepcopy(plan)
    out["status"] = "accepted"
    out["accepted_by"] = by
    return out


# ── the candidate: derived drawing → new sheet revision, parametrization carried over ─


@dataclass
class Candidate:
    plan: dict
    new: Any | None = None  # the new SheetModel (built, validated) when ready
    path: str | None = None


def build_candidate(sm, uid: str, request: dict, workdir: Path) -> Candidate:
    """Derive, re-import and carry the sheet's state over — or say why not. Never touches `sm`. Files go to `workdir/<plan id>/`; a refusal leaves
    none of them behind."""
    from .feature_carry import bake, carry

    plan: dict = {
        "id": "",
        "kind": "set_count",
        "unit": uid,
        "status": "refused",
        "revision": sm.revision,
        "refusals": [],
        "warnings": [],
        "questions": [],
    }
    work: Path | None = None
    try:
        req = _normalise(request)
        if uid not in sm.units:
            raise FeatureRefused(f"no unit {uid!r}")
        plan["request"] = req
        plan["id"] = f"F_{uid}_{req['count']}_{request_digest(sm, uid, req)}"
        work = workdir / plan["id"]
        work.mkdir(parents=True, exist_ok=True)
        if any(
            v for v in sm.values.values()
        ):  # a changed value is geometry from here on: the sheet as the person sees it is what is extended
            sm, baked = cast(Any, bake(sm, work, req)), True
        else:
            baked = False
        base = _base(sm, uid)
        try:
            doc, _ = ezdxf.recover.readfile(base.path)
        except DXFStructureError:
            doc = readfile(base.path)
        op, info = _order(sm, uid, req, base, doc)
        plan.update({k: info[k] for k in ("repeats", "questions") if info.get(k)})
        if info.get("repeat"):
            plan["repeat"] = info["repeat"]
        if op is None:
            plan["refusals"] = info["refusals"]
            if info["questions"]:
                plan["status"] = "needs_decision"
            _discard(work)
            return Candidate(plan=plan)
        um = sm.units[uid].sub.units_mm
        plan.update(plan_summary(op, um))
        plan["warnings"] = list(op.warnings)
        out = work / f"{Path(sm.path).stem}.{plan['id']}.dxf"
        derived = derive(op, str(out))
        new, notes = carry(sm, op, derived)
        plan["warnings"] += notes
        plan["status"] = "ready"
        plan["derived"] = str(out)
        if baked:
            Path(base.path).unlink(missing_ok=True)
            plan["warnings"].append(
                "values changed since the import are now part of the drawing (the new revision starts from them)"
            )
        return Candidate(plan=plan, new=new, path=str(out))
    except FeatureRefused as exc:
        plan["refusals"] = exc.reasons[:MAX_REFUSALS]
        if exc.question:
            plan["questions"] = [exc.question]
            plan["status"] = "needs_decision"
    except (
        DXFError,
        OSError,
        ValueError,
        KeyError,
        ArithmeticError,
    ) as exc:  # a drawing the writer or reader cannot handle is a refusal, not a crash
        plan["refusals"] = [
            f"the derived drawing could not be made: {type(exc).__name__}: {str(exc)[:200]}"
        ]
    _discard(work)
    return Candidate(plan=plan)


def _discard(work: Path | None) -> None:
    if work is not None:
        shutil.rmtree(work, ignore_errors=True)
        try:
            work.parent.rmdir()  # the revisions folder too, when this was all it held
        except OSError:
            pass


def discard(cand: Candidate) -> None:
    """A candidate that is not applied leaves nothing on the disk."""
    if cand.path:
        _discard(Path(cand.path).parent)


def default_dir(sm) -> Path:
    """Where a sheet's derived revisions are kept: beside its DXF, in a folder of its own."""
    p = Path(sm.path)
    return p.parent / f"{p.stem}.revisions"


__all__ = [
    "FeatureRefused",
    "Repeat",
    "accept_plan",
    "build_candidate",
    "default_dir",
    "detect_repeats",
    "plan_count",
]
