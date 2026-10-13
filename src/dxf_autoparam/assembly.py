"""The assembly a size belongs to, and how it moves when the size changes: which lines go with it, which side stays
(the ANCHOR), and what must not change on the way — computed, explained and checked, never left to whichever chain of
lines the set-out happened to pick.

A set-out drawing is lines chained by sizes. When one size changes, something has to give, and WHAT gives is a design
decision. Left implicit, it is decided by accident: a choice made for one size's two lines (its start stays, its end
moves) leaves every other line hanging where the old set-out hung it, so a middle wall between two cells thickens by
what the cell lost. An anchor policy states the decision for the whole assembly on one axis —

    centered      the assembly stays about a line (a drawn axis at its middle): each side moves half of what grows
    start_fixed   its start stays (left / bottom): every size pushes everything beyond it
    end_fixed     its end stays (right / top): every size pushes everything before it
    as_set_out    whatever the set-out does now (kept as it is)

— and `stack` rewrites the set-out of the assembly's lines on that axis so the drawing does exactly that: the anchor
line stays, every occurrence of the driving size moves what lies beyond it by the change, lines inside an opening stay
with the face they belong to, and every other size keeps its drawn value (walls, haunches, slabs, projections). Each
line is set out from one already placed by a size the drawing itself has (an existing formula, the driving size, a
named size) wherever one is consistent with the policy, else by its drawn distance. Closed form, exact at the drawn
values, no solver; nothing outside the assembly is rewritten; a line a person, the AI, a slope, a site level or a held
part sets is never rewritten — when it would have to move, the policy is refused with the reason.

    members = assembly_lines(prog, parts, core, "x")
    st = stack(prog, "x", [Driver("ClearSpan", pairs, "start_fixed")], members)
"""

from __future__ import annotations

import ast
import heapq
from dataclasses import dataclass, field
from itertools import pairwise

from .intent import Part, descendants
from .program import ExprError, Program, _num, names_in
from .topology import of

POLICIES = ("centered", "start_fixed", "end_fixed", "as_set_out")
POLICY_WORDS = {
    "centered": "stays about its centre line: each side moves half",
    "start_fixed": "its start stays (left / bottom): everything beyond each occurrence moves with it",
    "end_fixed": "its end stays (right / top): everything before each occurrence moves with it",
    "as_set_out": "as the engine's set-out does it now",
}
KEEP_ORIGINS = ("ai", "held", "existing", "slope")  # set by a person / the AI, existing work, a slope: never rewritten here
AXIS_SOURCES = ("drawn-axis", "loop-axis", "global-axis")
EPS = 1e-6


# ── linear forms ─────────────────────────────────────────────────────────────────


def linear(expr: str) -> tuple[dict[str, float], float] | None:
    """expr as const + Σ coef·name, or None when it is not linear (min / max / a product of two names …)."""
    try:
        tree = ast.parse(expr, mode="eval").body
    except SyntaxError:
        return None

    def lin(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return {}, float(n.value)
        if isinstance(n, ast.Name):
            return {n.id: 1.0}, 0.0
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            r = lin(n.operand)
            if r is None:
                return None
            s = -1.0 if isinstance(n.op, ast.USub) else 1.0
            return {k: s * v for k, v in r[0].items()}, s * r[1]
        if isinstance(n, ast.BinOp):
            a, b = lin(n.left), lin(n.right)
            if a is None or b is None:
                return None
            if isinstance(n.op, (ast.Add, ast.Sub)):
                s = 1.0 if isinstance(n.op, ast.Add) else -1.0
                c = dict(a[0])
                for k, v in b[0].items():
                    c[k] = c.get(k, 0.0) + s * v
                return {k: v for k, v in c.items() if abs(v) > 1e-12}, a[1] + s * b[1]
            if isinstance(n.op, ast.Mult):
                if not a[0]:
                    return {k: a[1] * v for k, v in b[0].items()}, a[1] * b[1]
                if not b[0]:
                    return {k: b[1] * v for k, v in a[0].items()}, a[1] * b[1]
                return None
            if isinstance(n.op, ast.Div) and not b[0] and b[1] != 0:
                return {k: v / b[1] for k, v in a[0].items()}, a[1] / b[1]
        return None

    return lin(tree)


def expr_of(base: str | None, coefs: dict[str, float], const: float = 0.0) -> str:
    """`base + Σ coef·name + const`, written as a person would ("x2 + ClearSpan", "x6 - 0.5 * ThkX4")."""
    out = base or ""
    for n, c in sorted(coefs.items()):
        if abs(c) < 1e-12:
            continue
        mag = "" if abs(abs(c) - 1) < 1e-12 else f"{_num(abs(c))} * "
        out = f"{out} {'+' if c > 0 else '-'} {mag}{n}" if out else (f"{mag}{n}" if c > 0 else f"-{mag}{n}")
    if abs(const) > 1e-9 or not out:
        out = f"{out} {'+' if const >= 0 else '-'} {_num(abs(const))}" if out else _num(const)
    return out


# ── the assembly: which lines move together ──────────────────────────────────────


@dataclass
class Driver:
    name: str  # the parameter
    pairs: list[tuple[str, str]]  # its occurrences on this axis, (low, high) as drawn
    policy: str = "as_set_out"
    centre: str | None = None  # the line it stays about (centered)


@dataclass
class Stack:
    ok: bool
    axis: str
    policy: str = ""
    root: str | None = None  # the line that stays: the anchor
    written: dict[str, tuple[str, str]] = field(default_factory=dict)  # line → (formula before, formula now)
    expected: dict[str, dict[str, float]] = field(default_factory=dict)  # driver → member line → mm moved per mm of it
    by_drawn_distance: list[str] = field(default_factory=list)  # lines no size of the drawing could place: set by their drawn distance
    why: str = ""
    conflicts: list[str] = field(default_factory=list)


def line_values_mm(prog: Program) -> dict[str, float]:
    an = prog.analysis
    u = an.drawing.units_mm
    out = {d.id: d.value * u for d in an.datums.values()}
    out.update({d: v * u for d, v in prog.datum_values().items()})
    return out


def rates(prog: Program, name: str, lines: set[str] | None = None) -> dict[str, float]:
    """mm each line moves per unit of `name` (a length: per mm; a level: per m), in the program as it is."""
    an = prog.analysis
    u = an.drawing.units_mm
    v0 = prog.datum_values()
    v1 = prog.datum_values({name: prog.params[name].value + 1.0})
    keys = lines if lines is not None else v0.keys()
    return {d: (v1[d] - v0[d]) * u for d in keys if d in v0 and abs(v1[d] - v0[d]) * u > 1e-9}


def level_lines(prog: Program) -> set[str]:
    levels = {n for n, p in prog.params.items() if p.kind == "level"}
    out = set()
    for d, e in prog.formulas.items():
        try:
            if names_in(e) & levels:
                out.add(d)
        except ExprError:
            continue
    return out


def protected_lines(prog: Program, fixed: set[str] | None = None) -> dict[str, str]:
    """Lines the stacking never rewrites, with why: set by a person / the AI, a slope, a held part or existing work, a
    site level, a formula that is not a plain chain (min / max, the other axis), and lines a person keeps fixed."""
    an = prog.analysis
    out: dict[str, str] = {}
    lv = level_lines(prog)
    for d, e in prog.formulas.items():
        o = prog.origin.get(d, "geometry")
        if o in KEEP_ORIGINS:
            out[d] = {"ai": "a person's or the AI's formula", "held": "a held part", "existing": "existing work", "slope": "a stated slope"}[o]
        elif d in lv:
            out[d] = "a site level"
        else:
            lf = linear(e)
            if lf is None:
                out[d] = "a formula that is not a plain chain"
            elif any(n in an.datums and an.datums[n].axis != an.datums[d].axis for n in lf[0]):
                out[d] = "set out from the other axis (a slope or a projection)"
    for d in fixed or ():
        out.setdefault(d, "kept fixed")
    return out


def assembly_lines(prog: Program, parts: dict[str, Part] | None, core: set[str] | None, axis: str,
                   seed: set[str] | None = None, exclude: set[str] | None = None) -> set[str]:
    """The lines on `axis` that move as one assembly.

    With parts: the lines of the `core` parts (an assembly brings its whole subtree), less the lines that belong only to
    `exclude` parts (held / outside the edit). Without parts: the connected structure the `seed` lines are drawn in —
    regions whose linework is connected to them, and the regions nested inside those. Either way the axis lines
    (a drawn centre line, a cell's own centre) lying within the assembly are part of it."""
    an = prog.analysis
    out: set[str] = set()
    if parts and core:
        names = set()
        for n in core:
            if n in parts:
                names |= {n} | descendants(parts, n)
        for n in names:
            out |= {d for d in parts[n].datums if d in an.datums and an.datums[d].axis == axis}
        if exclude:
            keep = set()
            for n in names:
                keep |= parts[n].own_datums
            for n in exclude:
                if n in parts and n not in names:
                    out -= parts[n].own_datums - keep
    else:
        topo = of(an)
        from .intent import resolve_parts

        regions, _ = resolve_parts(an, None)
        seed = set(seed or ())
        by_id = topo.by_id()
        hit = {r for r, p in regions.items() if p.datums & seed}
        pieces = {by_id[r].component for r in hit}
        chosen = {r.id for r in topo.regions if r.component in pieces}
        grew = True
        while grew:  # nesting both ways: cells inside the box, the box inside nothing
            grew = False
            for r in topo.regions:
                if r.id not in chosen and (r.parent in chosen or any(c.parent == r.id and c.id in chosen for c in topo.regions)
                                           and r.component in pieces):
                    chosen.add(r.id)
                    grew = True
        for r in chosen:
            out |= {d for d in regions[r].datums if an.datums[d].axis == axis}
        # open linework drawn onto the structure (a loose line touching it) belongs to it too
        on = {i for r in chosen for i in by_id[r].items}
        for i in topo.open_items:
            if topo.connections.get(i, set()) & on:
                for k in range(len(an.drawing.items[i].pts)):
                    b = an.slot_datum.get((i, k, axis))
                    if b and abs(b[1]) <= an.drawing.tol:
                        out.add(b[0])
        out |= {d for d in seed if d in an.datums and an.datums[d].axis == axis}
    if out:
        v = line_values_mm(prog)
        lo, hi = min(v[d] for d in out if d in v), max(v[d] for d in out if d in v)
        out |= {d.id for d in an.datums.values() if d.axis == axis and d.id in prog.formulas
                and (d.source in AXIS_SOURCES or d.virtual) and lo < v[d.id] < hi}
    return {d for d in out if d in prog.formulas}


def centre_candidates(prog: Program, members: set[str], pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Lines an assembly could stay centred on, best first, with what supports each: a line at the middle of the
    assembly (or of its one occurrence) — a drawn centre line before a derived one."""
    an = prog.analysis
    u = an.drawing.units_mm
    v = line_values_mm(prog)
    tol = max(an.drawing.tol * u * 2, 0.5)
    spans = []
    if len(pairs) == 1:
        a, b = pairs[0]
        spans.append(((v[a] + v[b]) / 2, f"the middle of {a}–{b}"))
    if members:
        lo, hi = min(v[d] for d in members), max(v[d] for d in members)
        spans.append(((lo + hi) / 2, "the middle of the assembly"))
    axis = an.datums[pairs[0][0]].axis if pairs else None
    out: list[tuple[str, str]] = []
    rank = {"drawn-axis": 0, "global-axis": 1, "loop-axis": 2}
    for mid, where in spans:
        cands = sorted((d for d in an.datums.values() if d.axis == axis and d.id in prog.formulas and abs(v[d.id] - mid) <= tol),
                       key=lambda d: (rank.get(d.source, 3), d.id))
        for d in cands:
            if all(d.id != c for c, _w in out):
                kind = {"drawn-axis": "a drawn centre line", "global-axis": "the drawing's axis of symmetry",
                        "loop-axis": "the centre of a closed outline"}.get(d.source, "a set-out line")
                out.append((d.id, f"{kind} at {where}"))
    return out


def symmetric_about(prog: Program, members: set[str], centre: str) -> bool:
    """Whether the assembly's lines mirror each other about `centre` (evidence for a centred design)."""
    an = prog.analysis
    v = line_values_mm(prog)
    tol = max(an.drawing.tol * an.drawing.units_mm * 2, 0.5)
    c = v[centre]
    pos = sorted(v[d] - c for d in members if d != centre)
    return bool(pos) and all(any(abs(p + q) <= tol for q in pos) for p in pos)


def _segments_on(prog: Program, axis: str) -> list[tuple[float, float]]:
    """Every straight structural segment as the span it covers on `axis` (mm, low → high), from the lines its two
    ends are drawn on."""
    an = prog.analysis
    v = line_values_mm(prog)
    tol = an.drawing.tol
    out = []
    for it in an.drawing.items:
        if it.role.value != "structural":
            continue
        segs = it.segments or [(k, k + 1) for k in range(len(it.vertex_pts) - 1)]
        for i, j in segs:
            bi, bj = an.slot_datum.get((it.index, i, axis)), an.slot_datum.get((it.index, j, axis))
            if bi and bj and abs(bi[1]) <= tol and abs(bj[1]) <= tol and bi[0] != bj[0]:
                lo, hi = sorted((v[bi[0]], v[bj[0]]))
                out.append((lo, hi))
    return out


def cut_of(prog: Program, a: str, b: str, inside: list[str], segs: list[tuple[float, float]]) -> float:
    """Where an occurrence takes its change: the widest stretch between the lines inside it that no SHORT drawn
    segment crosses (a short segment cut there would stretch or turn over: a joint, a cut-off wall, a haunch). Long
    segments — the occurrence's own edges, running its whole length — are what resizes. Returns the cut position (mm)."""
    v = line_values_mm(prog)
    L = v[b] - v[a]
    short = [(lo, hi) for lo, hi in segs if hi - lo < 0.5 * L and hi > v[a] and lo < v[b]]
    stops = sorted({v[a], v[b], *(v[d] for d in inside)})
    best = None
    for lo, hi in pairwise(stops):
        if hi - lo <= 1e-9:
            continue
        crossing = sum(1 for s0, s1 in short if s0 <= lo + 1e-6 and s1 >= hi - 1e-6)
        key = (crossing, -(hi - lo))
        if best is None or key < best[0]:
            best = (key, (lo + hi) / 2)
    return best[1] if best else (v[a] + v[b]) / 2


def predicted(prog: Program, drv: Driver, members: set[str], cur: dict[str, float] | None = None) -> dict[str, float]:
    """mm each member line moves per mm of the driver under its policy — the plan's own statement of the behaviour,
    which the stacking builds and the verification measures."""
    v = line_values_mm(prog)
    pairs = [(a, b) if v[a] <= v[b] else (b, a) for a, b in drv.pairs]
    cur = cur if cur is not None else rates(prog, drv.name, members)
    if drv.policy == "as_set_out":
        return {s: cur.get(s, 0.0) for s in members}
    tol = max(prog.analysis.drawing.tol * prog.analysis.drawing.units_mm, 1e-6)
    A = v[drv.centre] if drv.centre else None

    def outer(x: float) -> float:
        if drv.policy == "start_fixed":
            return float(sum(1 for a, b in pairs if v[b] <= x + tol))
        if drv.policy == "end_fixed":
            return -float(sum(1 for a, b in pairs if v[a] >= x - tol))
        if x >= A - tol:
            return sum(1.0 for a, b in pairs if v[a] >= A - tol and v[b] <= x + tol) \
                + sum(0.5 for a, b in pairs if v[a] < A - tol and v[b] > A + tol and v[b] <= x + tol)
        return -(sum(1.0 for a, b in pairs if v[b] <= A + tol and v[a] >= x - tol)
                 + sum(0.5 for a, b in pairs if v[a] < A - tol and v[b] > A + tol and v[a] >= x - tol))

    an = prog.analysis
    mtol = max(an.drawing.tol * an.drawing.units_mm * 2, 0.5)
    out = {}
    cuts: dict[tuple[str, str], float] = {}
    segs: list[tuple[float, float]] | None = None
    for s in members:
        x = v[s]
        inside = next(((a, b) for a, b in pairs if v[a] + tol < x < v[b] - tol), None)
        if not inside:
            out[s] = outer(x)
            continue
        a, b = inside
        if abs(2 * x - v[a] - v[b]) <= mtol and (an.datums[s].source in AXIS_SOURCES or an.datums[s].virtual):
            out[s] = (outer(v[a]) + outer(v[b])) / 2  # a centre line stays in the middle of its opening
            continue
        if (a, b) not in cuts:
            if segs is None:
                segs = _segments_on(prog, an.datums[a].axis)
            cuts[(a, b)] = cut_of(prog, a, b, [d for d in members if v[a] + tol < v[d] < v[b] - tol], segs)
        out[s] = outer(v[a]) if x < cuts[(a, b)] else outer(v[b])
    return out


def _chain_edges(prog: Program, axis: str) -> dict[str, list[tuple[str, dict[str, float], float, str]]]:
    """For each line, the lines it can be set out from by a size the drawing's own set-out already states: its formula
    `s = p + E` (E without other lines), and the same relation read the other way round."""
    an = prog.analysis
    adj: dict[str, list[tuple[str, dict[str, float], float, str]]] = {}
    for s, e in prog.formulas.items():
        if s not in an.datums or an.datums[s].axis != axis:
            continue
        lf = linear(e)
        if lf is None:
            continue
        coefs, const = lf
        ds = [n for n in coefs if n in prog.formulas]
        if len(ds) != 1 or abs(coefs[ds[0]] - 1.0) > 1e-12 or an.datums[ds[0]].axis != axis:
            continue
        p = ds[0]
        rest = {k: c for k, c in coefs.items() if k != p}
        adj.setdefault(p, []).append((s, rest, const, "formula"))
        adj.setdefault(s, []).append((p, {k: -c for k, c in rest.items()}, -const, "formula"))
    return adj


def stack(prog: Program, axis: str, drivers: list[Driver], members: set[str], still: set[str] | None = None,
          named: dict[str, list[tuple[str, str]]] | None = None) -> Stack:
    """Rewrite the set-out of `members` (lines on `axis`) so every driver behaves as its policy says (one policy for
    the assembly: `drivers` share it). `still`: lines that must not move (a part a person keeps fixed is drawn on them):
    a policy that would move one is refused. `named`: named sizes and their pairs (kept as the sizes they are). On
    success the program is changed (origin "plan" on every line rewritten) and the result says which lines were
    rewritten and what each is expected to do; on refusal nothing changes."""
    an = prog.analysis
    u = an.drawing.units_mm
    policy = drivers[0].policy if drivers else "as_set_out"
    st = Stack(ok=False, axis=axis, policy=policy)
    if not drivers or policy == "as_set_out":
        st.ok, st.why = True, "kept as set out"
        for drv in drivers:
            st.expected[drv.name] = predicted(prog, drv, members)
        return st
    if any(d.policy != policy for d in drivers):
        st.why = f"one assembly, one anchor: {', '.join(f'{d.name} {d.policy}' for d in drivers)} disagree"
        return st
    v = line_values_mm(prog)
    tol_mm = max(an.drawing.tol * u * 2, 0.5)
    members = {d for d in members if d in prog.formulas and an.datums[d].axis == axis}
    for drv in drivers:
        miss = [x for pr in drv.pairs for x in pr if x not in members]
        if miss:
            members |= {x for x in miss if x in prog.formulas}
    protect = protected_lines(prog)
    rer = {d for d in members if d not in protect}
    cur = {drv.name: rates(prog, drv.name) for drv in drivers}
    pred = {drv.name: predicted(prog, drv, members, cur[drv.name]) for drv in drivers}
    st.expected = pred

    # the anchor: the line that stays
    if policy == "centered":
        root = drivers[0].centre
        if not root or root not in prog.formulas:
            st.why = "no centre line to stay about"
            return st
        members.add(root)
        if root not in protect:
            rer.add(root)
        for drv in drivers:
            pred[drv.name][root] = 0.0
    else:
        pool = sorted(members, key=lambda d: (v[d], d))
        root = pool[0] if policy == "start_fixed" else pool[-1]
    st.root = root

    # what depends on a line that may be rewritten (it cannot be a parent: that would close a loop)
    order = prog.order()
    tainted: set[str] = set()
    for d in order:
        if d in rer or any(n in tainted or n in rer for n in names_in(prog.formulas[d]) if n in prog.formulas):
            tainted.add(d)
    # a line nobody may rewrite that hangs on one that is rewritten (a slope's foot, a person's formula) follows its own
    # set-out: what it is expected to do is what its parent does, plus its own share of the driver
    for d in order:
        if d in members and d not in rer and d in tainted:
            lf = linear(prog.formulas[d])
            if lf is None:
                continue
            par = [n for n in lf[0] if n in prog.formulas and an.datums[n].axis == axis]
            if len(par) == 1 and abs(lf[0][par[0]] - 1.0) < 1e-12:
                for drv in drivers:
                    pred[drv.name][d] = pred[drv.name].get(par[0], cur[drv.name].get(par[0], 0.0)) + lf[0].get(drv.name, 0.0)
    placed: dict[str, dict[str, float]] = {}
    parent: dict[str, tuple[str | None, dict[str, float], float, str]] = {}
    for d in prog.formulas:
        if an.datums.get(d) is None or an.datums[d].axis != axis or d in rer or d in tainted:
            continue
        placed[d] = {n: cur[n].get(d, 0.0) for n in cur}
    # protected members that stand on their own must already do what the policy asks of them (those hanging on a
    # rewritten line are measured after)
    for d in members - rer - tainted:
        for drv in drivers:
            want, got = pred[drv.name].get(d, 0.0), cur[drv.name].get(d, 0.0)
            if abs(want - got) > 1e-6:
                st.conflicts.append(f"{d} is set by {protect.get(d, 'something fixed')} and moves {got:+g} mm per mm of {drv.name}; "
                                    f"{POLICY_WORDS[policy]} needs {want:+g}")
    for d in sorted((still or set()) & members):
        for drv in drivers:
            k = pred[drv.name].get(d, 0.0)
            if abs(k) > 1e-9:
                st.conflicts.append(f"{d} must stay (a part kept fixed is drawn on it), but {POLICY_WORDS[policy]} moves it "
                                    f"{k:+g} mm per mm of {drv.name}")
    if st.conflicts:
        st.why = st.conflicts[0]
        return st

    def consistent(k_p: dict[str, float], coefs: dict[str, float], s: str) -> bool:
        return all(abs(k_p[n] + coefs.get(n, 0.0) - pred[n].get(s, 0.0)) <= 1e-9 for n in pred)

    # the root: on what it already stands on when that stays, else where it is drawn
    if root in rer:
        lf = linear(prog.formulas[root])
        refs = [n for n in (lf[0] if lf else {}) if n in prog.formulas]
        stays = lf is not None and all(n in placed for n in refs) and all(abs(cur[n].get(root, 0.0)) <= 1e-9 for n in cur)
        if stays:
            parent[root] = (None, {}, 0.0, "kept")
        else:
            anchor = min((d for d in placed if all(abs(placed[d][n]) <= 1e-9 for n in cur)), key=lambda d: abs(v[d] - v[root]), default=None)
            parent[root] = (anchor, {}, v[root] - (v[anchor] if anchor else 0.0), "anchor")
        placed[root] = {n: 0.0 for n in cur}

    adj = _chain_edges(prog, axis)
    extra: dict[str, list[tuple[str, dict[str, float], float, str]]] = {}
    for drv in drivers:
        for a, b in drv.pairs:
            lo, hi = (a, b) if v[a] <= v[b] else (b, a)
            extra.setdefault(lo, []).append((hi, {drv.name: 1.0}, v[hi] - v[lo] - prog.params[drv.name].value, "driver"))
            extra.setdefault(hi, []).append((lo, {drv.name: -1.0}, v[lo] - v[hi] + prog.params[drv.name].value, "driver"))
            if policy == "centered" and v[lo] + tol_mm < v[root] < v[hi] - tol_mm:
                half = prog.params[drv.name].value / 2
                extra.setdefault(root, []).append((lo, {drv.name: -0.5}, v[lo] - v[root] + half, "driver"))
                extra.setdefault(root, []).append((hi, {drv.name: 0.5}, v[hi] - v[root] - half, "driver"))
    for q, pairs in (named or {}).items():
        if q not in prog.params or q in pred:
            continue
        for a, b in pairs:
            if a in members and b in members and an.datums[a].axis == axis:
                lo, hi = (a, b) if v[a] <= v[b] else (b, a)
                extra.setdefault(lo, []).append((hi, {q: 1.0}, v[hi] - v[lo] - prog.params[q].value, "named"))
                extra.setdefault(hi, []).append((lo, {q: -1.0}, v[lo] - v[hi] + prog.params[q].value, "named"))
    rank = {"driver": 0, "named": 0, "formula": 1}
    heap: list = []
    seq = 0

    def push(p: str) -> None:
        nonlocal seq
        for s, coefs, const, kind in adj.get(p, []) + extra.get(p, []):
            if s in rer and s not in placed:
                seq += 1
                heapq.heappush(heap, (rank[kind], abs(v[s] - v[p]), seq, p, s, coefs, const, kind))

    for p in list(placed):
        push(p)
    while len([d for d in rer if d not in placed]):
        while heap:
            _r, _dist, _q, p, s, coefs, const, kind = heapq.heappop(heap)
            if s in placed or not consistent(placed[p], coefs, s):
                continue
            placed[s] = {n: placed[p][n] + coefs.get(n, 0.0) for n in pred}
            parent[s] = (p, coefs, const, kind)
            push(s)
        left = [d for d in rer if d not in placed]
        if not left:
            break
        # nothing the drawing states places these: one is set by its drawn distance — from a line that moves exactly as it
        # must (a plain offset), of the assembly itself before anything outside it, the nearest first; only when no line
        # moves as it must is the driver's share written into the offset
        def fit(sp: tuple[str, str]) -> tuple:
            s_, p_ = sp
            same_ = all(abs(placed[p_][n] - pred[n].get(s_, 0.0)) <= 1e-9 for n in pred)
            return (0 if same_ else 1, 0 if p_ in members else 1, abs(v[s_] - v[p_]), s_, p_)

        s, p = min(((s, p) for s in left for p in placed), key=fit)
        coefs = {n: pred[n].get(s, 0.0) - placed[p][n] for n in pred}
        coefs = {n: c for n, c in coefs.items() if abs(c) > 1e-12}
        const = v[s] - v[p] - sum(c * prog.params[n].value for n, c in coefs.items())
        placed[s] = {n: pred[n].get(s, 0.0) for n in pred}
        parent[s] = (p, coefs, const, "drawn")
        st.by_drawn_distance.append(s)
        push(s)

    # write what changed (a line whose formula already says the same is left alone); every constant is worked out from
    # the drawn positions, so the drawing stays exactly as drawn at the current values
    saved = {d: (prog.formulas[d], prog.origin.get(d)) for d in parent}
    vals = prog.defaults()
    try:
        for s, (p, coefs, _const, kind) in parent.items():
            if kind == "kept":
                continue
            old = prog.formulas[s]
            const = v[s] - (v[p] if p else 0.0) - sum(c * vals[n] for n, c in coefs.items())
            if abs(const) < 1e-7:
                const = 0.0
            want = dict(coefs)
            if p:
                want[p] = want.get(p, 0.0) + 1.0
            lf = linear(old)
            if lf is not None and set(lf[0]) == set(want) and all(abs(lf[0][k] - want[k]) <= 1e-12 for k in want) and abs(lf[1] - const) <= 1e-6:
                continue
            prog.formulas[s] = expr_of(p, coefs, const)
            prog.origin[s] = "plan"
            st.written[s] = (old, prog.formulas[s])
        prog.invalidate()
        prog.order()
        now = prog.datum_values()
        bad = [d for d in members if d in now and abs(now[d] * u - v[d]) > 1e-6]
        if bad:
            raise ExprError(f"{', '.join(sorted(bad)[:4])} no longer drawn where they are")
    except (ExprError, KeyError, ZeroDivisionError) as exc:
        for d, (f, o) in saved.items():
            prog.formulas[d] = f
            if o is None:
                prog.origin.pop(d, None)
            else:
                prog.origin[d] = o
        prog.invalidate()
        st.written, st.why = {}, f"the set-out could not be rewritten: {exc}"
        return st
    # measured, not assumed: the drivers now do what the policy says on every member line
    for drv in drivers:
        got = rates(prog, drv.name, members)
        off = [d for d in members if abs(got.get(d, 0.0) - pred[drv.name].get(d, 0.0)) > 1e-6]
        if off:
            st.conflicts += [f"{d} moves {got.get(d, 0.0):+g} mm per mm of {drv.name}, not {pred[drv.name].get(d, 0.0):+g} "
                             f"({protect.get(d) or 'it follows ' + (prog.formulas[d][:40])})" for d in sorted(off)[:6]]
    st.ok = not st.conflicts
    if not st.ok:  # refused: the set-out is put back exactly as it was
        st.why = st.conflicts[0]
        for d, (f, o) in saved.items():
            prog.formulas[d] = f
            if o is None:
                prog.origin.pop(d, None)
            else:
                prog.origin[d] = o
        prog.invalidate()
        st.written = {}
        return st
    # every line the plan placed is the plan's from now on: later repairs (healing, constraints) do not take it over
    for d in parent:
        if prog.origin.get(d, "geometry") in ("geometry", "kept", "constraint"):
            prog.origin[d] = "plan"
    return st


# ── interfaces: which parts touch, and on which line ─────────────────────────────


def interfaces(prog: Program, parts: dict[str, Part]) -> list[dict]:
    """Observed contacts between parts, from their own outlines: a FACE when both have an edge along the same line over
    a common length (a slab on a wall), a CORNER when they only share a corner point. Measured, so every row is
    evidence, never an assumption that touching parts move together."""
    an = prog.analysis
    u = an.drawing.units_mm
    v = line_values_mm(prog)
    leaf = {n: p for n, p in parts.items() if not any(q.parent == n for q in parts.values())}

    def faces(p: Part) -> dict[str, list[tuple[float, float]]]:
        out: dict[str, list[tuple[float, float]]] = {}
        for (xa, ya), (xb, yb) in p.edges:
            if xa == xb and ya != yb:
                lo, hi = sorted((v[ya], v[yb]))
                out.setdefault(xa, []).append((lo, hi))
            elif ya == yb and xa != xb:
                lo, hi = sorted((v[xa], v[xb]))
                out.setdefault(ya, []).append((lo, hi))
        return out

    fc = {n: faces(p) for n, p in leaf.items()}
    rows = []
    names = sorted(leaf)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            common = set(fc[a]) & set(fc[b])
            for d in sorted(common):
                over = sum(max(0.0, min(h1, h2) - max(l1, l2)) for l1, h1 in fc[a][d] for l2, h2 in fc[b][d])
                if over > an.drawing.tol * u:
                    rows.append({"parts": [a, b], "line": d, "axis": an.datums[d].axis, "kind": "face", "length_mm": round(over, 1),
                                 "status": "observed", "evidence": f"both outlines run along {d} for {over:.0f} mm"})
            shared = leaf[a].nodes & leaf[b].nodes
            if shared and not common:
                x, y = min(shared)
                rows.append({"parts": [a, b], "line": None, "axis": None, "kind": "corner", "at": [x, y], "status": "observed",
                             "evidence": f"they share the corner {x}/{y}"})
    return rows


def part_entities(prog: Program, parts: dict[str, Part], name: str) -> set[int]:
    """The entities that are a part's own: drawn mostly along its regions' boundaries (an edge shared with a neighbour
    counts for the side it borders more), and the entities named as its own."""
    an = prog.analysis
    topo = of(an)
    names = {name} | descendants(parts, name)
    regs = {r for n in names if n in parts for r in parts[n].regions}
    # an outline two regions share in full (a cell's outline is also the box's hole) belongs to both
    out = {i for i, border in topo.item_border.items()
           if sum(L for r, L in border.items() if r in regs) > 0
           and sum(L for r, L in border.items() if r in regs) >= sum(L for r, L in border.items() if r not in regs)}
    for n in names:
        if n in parts:
            out |= parts[n].entities
    return {i for i in out if an.drawing.items[i].role.value in ("structural", "reference")}


def entity_lines(prog: Program, ents: set[int], axis: str) -> set[str]:
    """The lines these entities are drawn on (a point exactly on the line) — what holding them in place would fix.
    A part's REGION also has corners where a neighbour merely touches it (a box standing on a footing makes corners on
    the footing's top edge): those lines are the neighbour's, not the part's."""
    an = prog.analysis
    out = set()
    for i in ents:
        for k in range(len(an.drawing.items[i].pts)):
            b = an.slot_datum.get((i, k, axis))
            if b and abs(b[1]) <= an.drawing.tol:
                out.add(b[0])
    return out
