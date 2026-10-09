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


@dataclass
class Regenerated:
    values: dict[str, float]
    datum: dict[str, float]
    pts: dict[int, list[tuple[float, float]]]
    radius: dict[int, float]
    texts: dict[int, str]
    issues: list[str] = field(default_factory=list)

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


def check_invariants(model: Model, r: Regenerated, items=None) -> list[str]:
    """`items`: only these entities (the rest are known not to have moved)."""
    an = model.analysis
    tol = an.drawing.tol
    issues: list[str] = []
    for name, v in r.values.items():
        if v <= 0:
            issues.append(f"{name} must stay positive (is {v:g})")
    for it in an.drawing.items if items is None else items:
        if it.role != Role.STRUCTURAL:
            continue
        old = [it.pts[k] for k in it.vertex_pts]
        new = [r.pts[it.index][k] for k in it.vertex_pts]
        for i, j in it.segments:
            (a0, b0), (a1, b1) = (it.pts[i], it.pts[j]), (r.pts[it.index][i], r.pts[it.index][j])
            L0 = math.dist(a0, b0)
            L1 = math.dist(a1, b1)
            if L0 > tol and L1 <= tol:
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
    return f"{it.dxftype} {it.handle} ({it.layer})"


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
    u = an.drawing.units_mm
    texts: dict[int, str] = {}
    for idx, links in prog.text_links.items():
        text = an.drawing.items[idx].text or ""
        for tok, ref, dec in links:
            if ref.startswith("datum:"):
                v = (datum[ref[6:]] * u + an.level_offset_mm) / 1000
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
    out = Regenerated(values=vals, datum=datum, pts=pts, radius=radius, texts=texts)
    if check:
        out.issues = _check_program(prog, out)
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
    sub = [an.drawing.items[i] for i in sorted(moved) if an.drawing.items[i].role != Role.FIXED and an.drawing.items[i].anchor is None]
    r = Regenerated(values=vals, datum=datum, pts=place(an, datum, sub), radius=prog.radii(values), texts={})

    class _M:
        analysis = an

    issues = check_invariants(_M, r, sub)  # type: ignore[arg-type]
    return [i for i in issues if not any(i.startswith(f"{p.name} must") for p in prog.params.values() if p.kind == "level")]


def _check_program(prog, r: Regenerated) -> list[str]:
    class _M:  # check_invariants reads .analysis only, plus positivity of values
        analysis = prog.analysis

    issues = check_invariants(_M, r)  # type: ignore[arg-type]
    return [i for i in issues if not any(i.startswith(f"{p.name} must") for p in prog.params.values() if p.kind == "level")]
