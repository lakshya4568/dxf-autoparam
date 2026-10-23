"""Regeneration: values → datums → every point of every entity. Closed form.

Then the invariants a regenerated drawing must keep — checked, never assumed:

  * no closed outline turns inside out or collapses (signed area keeps its sign)
  * no edge collapses to nothing or flips direction
  * no closed outline starts crossing itself
  * every value stays positive
Horizontal / vertical / shared points / collinear edges are kept BY CONSTRUCTION
(their points share datums), so they cannot break.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .ir import Item, Model, Role
from .program import ExprError


@dataclass
class Regenerated:
    values: dict[str, float]
    datum: dict[str, float]
    pts: dict[int, list[tuple[float, float]]]
    radius: dict[int, float]
    texts: dict[int, str]
    issues: list[str] = field(default_factory=list)
    turns: dict[int, float] = field(default_factory=dict)  # degrees an entity was turned by a component transform (texts, arcs)
    # entities not drawn at these values: what a size of 0 takes away with it (an outline, its hatch, the dimension of it) — drawn again when the
    # size is above 0 (check_invariants)
    absent: set[int] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.issues


def regenerate(model: Model, values: dict[str, float] | None = None, check: bool = True) -> Regenerated:
    an = model.analysis
    vals = model.defaults()
    if values:
        unknown = [k for k in values if k not in vals]
        if unknown:
            raise KeyError(f"no such value: {', '.join(unknown)}")
        vals.update(values)
    datum = {d: f.evaluate(vals) for d, f in model.forms.items()}
    pts = place(an, datum)
    radius = {i: f.evaluate(vals) for i, f in model.radius.items()}
    texts: dict[int, str] = {}
    u = an.drawing.units_mm
    for idx, links in model.text_links.items():
        text = an.drawing.items[idx].text or ""
        for tok, ref, dec in links:
            if ref.startswith("datum:"):
                v = datum[ref[6:]] * u / 1000
            elif ref.startswith("m:"):
                v = vals[ref[2:]] * u / 1000
            elif ref.startswith("len:"):  # the distance between two set-out lines, as drawn now
                a, b = ref[4:].split(":")
                v = abs(datum[b] - datum[a]) * u
            else:
                v = vals[ref] * u
            new = f"{v:.{dec}f}" if dec else f"{round(v)}"
            text = re.sub(rf"(?<![\d.]){re.escape(tok)}(?![\d.])", new, text, count=1)
        texts[idx] = text
    out = Regenerated(values=vals, datum=datum, pts=pts, radius=radius, texts=texts)
    if check:
        out.issues = check_invariants(model, out)
    return out


def place(an, datum: dict[str, float], only=None) -> dict[int, list[tuple[float, float]]]:
    """Every entity point from its datums (+ offset); a rigid symbol moves with its insertion point.
    `only`: place just these entities (no symbols) — for checks that know what moved."""
    pts: dict[int, list[tuple[float, float]]] = {}
    items = an.drawing.items
    for it in items if only is None else only:
        if it.role == Role.FIXED or it.anchor is not None:
            continue
        new = []
        for k, (x, y) in enumerate(it.pts):
            bx = an.slot_datum.get((it.index, k, "x"))
            by = an.slot_datum.get((it.index, k, "y"))
            new.append((datum[bx[0]] + bx[1] if bx else x, datum[by[0]] + by[1] if by else y))
        pts[it.index] = new
    if only is not None:
        return pts
    for it in items:
        if it.anchor is None or it.role == Role.FIXED:
            continue
        a = items[it.anchor]
        moved = pts.get(a.index, a.pts)
        dx, dy = moved[0][0] - a.pts[0][0], moved[0][1] - a.pts[0][1]
        pts[it.index] = [(x + dx, y + dy) for x, y in it.pts]
    return pts


def _area(poly: list[tuple[float, float]]) -> float:
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))


def _crosses(p1, p2, p3, p4) -> bool:
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2, d3, d4 = orient(p3, p4, p1), orient(p3, p4, p2), orient(p1, p2, p3), orient(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and all(abs(d) > 1e-9 for d in (d1, d2, d3, d4))


def _self_crossings(poly) -> int:
    n = len(poly)
    if n > 64:
        return 0
    c = 0
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _crosses(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                c += 1
    return c


def _vanishes(it: Item, pts, tol: float) -> bool:
    """Whether an entity drawn with extent is drawn with none at these points: a closed outline of no area, a hatch whose boundary has none, a
    dimension measuring nothing, a line of no length."""
    if pts is None or not it.pts:
        return False
    if it.dxftype == "HATCH":
        rings = [ring for ring in it.extra.get("rings", []) if len(ring) >= 3 and all(k < len(pts) for k in ring)]
        return bool(rings) and all(abs(_area([pts[k] for k in ring])) <= tol * tol < abs(_area([it.pts[k] for k in ring])) for ring in rings)
    if it.dxftype == "DIMENSION":
        return len(pts) > 2 and math.dist(pts[1], pts[2]) <= tol < math.dist(it.pts[1], it.pts[2])
    if it.closed and len(it.vertex_pts) >= 3:
        return abs(_area([pts[k] for k in it.vertex_pts])) <= tol * tol < abs(_area([it.pts[k] for k in it.vertex_pts]))
    if it.segments:
        return all(math.dist(pts[i], pts[j]) <= tol for i, j in it.segments) and any(math.dist(it.pts[i], it.pts[j]) > tol for i, j in it.segments)
    return False


def check_invariants(model: Model, r: Regenerated, items=None, zero_ok: set[str] | None = None) -> list[str]:
    """`items`: only these entities (the rest are known not to have moved). `zero_ok`: the values that may be 0 — a size of material whose part is
    then not drawn (`r.absent`), and is drawn again when the value is above 0; an opening, a spacing or a level never is."""
    an = model.analysis
    tol = an.drawing.tol
    issues: list[str] = []
    zero = False
    for name, v in r.values.items():
        if v < 0 or (v == 0 and name not in (zero_ok or ())):
            issues.append(f"{name} must stay positive (is {v:g})")
        elif v == 0:
            zero = True
    for it in an.drawing.items if items is None else items:
        if zero and _vanishes(it, r.pts.get(it.index), tol):
            r.absent.add(it.index)  # what the size of 0 takes away: not drawn, and nothing to check
            continue
        if it.role != Role.STRUCTURAL:
            continue
        old = [it.pts[k] for k in it.vertex_pts]
        new = [r.pts[it.index][k] for k in it.vertex_pts]
        for i, j in it.segments:
            (a0, b0), (a1, b1) = (it.pts[i], it.pts[j]), (r.pts[it.index][i], r.pts[it.index][j])
            L0 = math.dist(a0, b0)
            L1 = math.dist(a1, b1)
            if L0 > tol and L1 <= tol:
                if zero:
                    continue  # two corners that meet at a size of 0 (a course gone from under a wall's outline): the outline is still drawn
                issues.append(f"{_name(it)}: an edge collapses")
                break
            if L0 > tol and ((b0[0] - a0[0]) * (b1[0] - a1[0]) + (b0[1] - a0[1]) * (b1[1] - a1[1])) < 0:
                issues.append(f"{_name(it)}: an edge flips direction")
                break
        if it.closed and len(old) >= 3:
            A0, A1 = _area(old), _area(new)
            if abs(A0) > tol * tol and (A0 > 0) != (A1 > 0) or abs(A1) <= tol * tol < abs(A0):
                issues.append(f"{_name(it)}: the outline turns inside out")
            elif _self_crossings(new) > _self_crossings(old):
                issues.append(f"{_name(it)}: the outline crosses itself")
        if it.dxftype == "CIRCLE" and r.radius.get(it.index, it.radius or 1) <= 0:
            issues.append(f"{_name(it)}: radius becomes zero")
    return issues[:20]


def _name(it: Item) -> str:
    """How an issue names an entity: its source path — the handle, or handle/k… inside a block reference, where every
    entity shares the block's handle — so the entity can be found again."""
    return f"{it.dxftype} {it.src or it.handle} ({it.layer})"


def apply_transforms(prog, pts: dict[int, list], vals: dict[str, float], datum: dict[str, float], radius: dict[int, float] | None = None) -> tuple[dict[int, float], list[str]]:
    """The program's component transforms, applied after the set-out: each rotates / translates / scales its entities
    about its pivot by (its value now − its value as drawn) — exact at the defaults, closed form. Annotations carried by
    a transformed part (a leader on it, a label on it) move with the point they hang on, keeping their reading direction.
    Returns (turns in degrees per entity, issues)."""
    if not getattr(prog, "transforms", None):
        return {}, []
    from .program import evaluate

    an = prog.analysis
    u = an.drawing.units_mm
    d0 = prog.datum_values()
    scope0 = {**prog.defaults(), **{d: v * u for d, v in d0.items()}}
    scope1 = {**vals, **{d: v * u for d, v in datum.items()}}
    turns: dict[int, float] = {}
    issues: list[str] = []
    for t in prog.transforms:
        try:
            kind = t["kind"]
            if kind == "rotate":
                a = math.radians(evaluate(t["angle"], scope1) - evaluate(t["angle"], scope0))
                px, py = evaluate(t["pivot"][0], scope1) / u, evaluate(t["pivot"][1], scope1) / u
                c, s = math.cos(a), math.sin(a)

                def fn(p, px=px, py=py, c=c, s=s):
                    return (px + c * (p[0] - px) - s * (p[1] - py), py + s * (p[0] - px) + c * (p[1] - py))

                turn = math.degrees(a)
            elif kind == "translate":
                dx = (evaluate(t["dx"], scope1) - evaluate(t["dx"], scope0)) / u
                dy = (evaluate(t["dy"], scope1) - evaluate(t["dy"], scope0)) / u

                def fn(p, dx=dx, dy=dy):
                    return (p[0] + dx, p[1] + dy)

                turn = 0.0
            elif kind == "scale":
                sx = evaluate(t["sx"], scope1) / evaluate(t["sx"], scope0)
                sy = evaluate(t["sy"], scope1) / evaluate(t["sy"], scope0)
                px, py = evaluate(t["pivot"][0], scope1) / u, evaluate(t["pivot"][1], scope1) / u

                def fn(p, sx=sx, sy=sy, px=px, py=py):
                    return (px + sx * (p[0] - px), py + sy * (p[1] - py))

                turn = 0.0
                if radius is not None and abs(sx - sy) <= 1e-12:
                    for i in t["entities"]:
                        if i in radius:
                            radius[i] *= sx
            else:
                issues.append(f"transform {t.get('name')}: unknown kind {kind}")
                continue
        except (ExprError, ZeroDivisionError, KeyError) as exc:
            issues.append(f"transform {t.get('name')}: {exc}")
            continue
        for i in t["entities"]:
            if i in pts:
                pts[i] = [fn(p) for p in pts[i]]
                if turn:
                    turns[i] = turns.get(i, 0.0) + turn
        for i, (ax, ay) in (t.get("carried") or {}).items():
            i = int(i)
            if i in pts:
                nx, ny = fn((ax, ay))
                pts[i] = [(p[0] + nx - ax, p[1] + ny - ay) for p in pts[i]]
    return turns, issues


def regenerate_program(prog, values: dict[str, float] | None = None, check: bool = True) -> Regenerated:
    """Regenerate from a parametric Program (formulas in mm, levels in m)."""
    vals = prog.defaults()
    if values:
        unknown = [k for k in values if k not in vals]
        if unknown:
            raise KeyError(f"no such value: {', '.join(unknown)}")
        vals.update(values)
    an = prog.analysis
    datum = prog.datum_values(vals)
    pts = place(an, datum)
    radius = prog.radii(vals)
    turns, t_issues = apply_transforms(prog, pts, vals, datum, radius)
    u = an.drawing.units_mm
    texts: dict[int, str] = {}
    for idx, links in prog.text_links.items():
        text = an.drawing.items[idx].text or ""
        for tok, ref, dec in links:
            if ref.startswith("datum:"):
                v = (datum[ref[6:]] * u + an.level_offset_mm) / 1000
            elif ref.startswith("len:"):  # the distance between two set-out lines, as drawn now
                a, b = ref[4:].split(":")
                v = abs(datum[b] - datum[a]) * u if a in datum and b in datum else float("nan")
            elif ref.startswith("m:"):
                v = vals.get(ref[2:], float("nan")) / 1000
            elif ref.startswith("rel:"):
                rel = next((r for r in prog.relations if r.name == ref[4:]), None)
                v = prog.relation_value(rel, vals) if rel is not None else float("nan")
            else:
                v = vals.get(ref, float("nan"))
            if math.isnan(v):  # a value the program no longer has: leave the note as written
                continue
            new = f"{v:.{dec}f}" if dec else f"{round(v)}"
            text = re.sub(rf"(?<![\d.]){re.escape(tok)}(?![\d.])", new, text, count=1)
        texts[idx] = text
    out = Regenerated(values=vals, datum=datum, pts=pts, radius=radius, texts=texts, turns=turns)
    if check:
        out.issues = t_issues + _check_program(prog, out)
    return out


def datum_users(an) -> dict[str, set[int]]:
    """Set-out line → the entities with a point on it."""
    users: dict[str, set[int]] = {}
    for (idx, _k, _ax), (d, _off) in an.slot_datum.items():
        users.setdefault(d, set()).add(idx)
    return users


def check_change(prog, values: dict[str, float], base_datum: dict[str, float], users: dict[str, set[int]], plan=None) -> list[str]:
    """The issues regenerate_program(prog, values) would report, found on the entities the change MOVES only (an entity
    whose points all stay where they are cannot collapse, flip or cross itself). Linear in what moves, so checking every
    value of a 20k-entity sheet stays fast."""
    vals = prog.defaults()
    vals.update(values)
    datum = prog.datum_values_changed(values, plan) if plan is not None else prog.datum_values(values)
    an = prog.analysis
    moved = {i for d, v in datum.items() if abs(v - base_datum.get(d, v)) > 1e-12 for i in users.get(d, ())}
    moved |= set(prog.radius)
    for t in getattr(prog, "transforms", ()):  # a transform moves its entities without moving any set-out line
        moved |= set(t["entities"])
    sub = [an.drawing.items[i] for i in sorted(moved) if an.drawing.items[i].role != Role.FIXED and an.drawing.items[i].anchor is None]
    pts = place(an, datum, sub)
    radius = prog.radii(values)
    apply_transforms(prog, pts, vals, datum, radius)
    r = Regenerated(values=vals, datum=datum, pts=pts, radius=radius, texts={})

    class _M:
        analysis = an

    issues = check_invariants(_M, r, sub)  # type: ignore[arg-type]
    return [i for i in issues if not any(i.startswith(f"{p.name} must") for p in prog.params.values() if p.kind == "level")]


# the kinds of gap that are not a size of material: at 0 an opening closes, repeated members coincide, a circle is gone, an overall size is nothing
NO_ZERO = {"void", "pitch", "diameter", "dim"}


def zero_allowed(prog) -> set[str]:
    """The values that may be 0 — whatever the person asks, as long as the drawing can still be drawn (nothing turns inside out or crosses): what
    collapses to nothing is not drawn (a course, a haunch, a projection with its hatch), and is drawn again above 0. Not a level, and not a gap
    that is no size at 0 (its candidate's kind, else the kind of the gap between its two lines): a hole in an outline, a spacing of repeats, a
    circle's size, an overall size."""
    an = prog.analysis
    by_lines: dict[frozenset, set[str]] = {}
    for g in an.gaps.values():
        by_lines.setdefault(frozenset((g.a, g.b)), set()).add(g.kind.value)
    out = set()
    for n, p in prog.params.items():
        if p.kind == "level":
            continue
        kinds = {p.kind} if p.kind not in ("length", "") else by_lines.get(frozenset(p.measures or ()), set())
        if not kinds & NO_ZERO:
            out.add(n)
    return out


def _check_program(prog, r: Regenerated) -> list[str]:
    class _M:  # check_invariants reads .analysis only, plus positivity of values
        analysis = prog.analysis

    issues = check_invariants(_M, r, zero_ok=zero_allowed(prog) if any(v == 0 for v in r.values.values()) else None)  # type: ignore[arg-type]
    return [i for i in issues if not any(i.startswith(f"{p.name} must") for p in prog.params.values() if p.kind == "level")]
