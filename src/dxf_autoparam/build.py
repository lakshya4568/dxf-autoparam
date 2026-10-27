"""Build the parametric model: choose what drives what, then write every datum as an
expression of the parameters.

WHY A SPANNING TREE. Each axis's datums must be set out exactly once. Every gap is a
possible way to set a datum out from another, so the model is a spanning tree of the
datum graph (one root per axis). Gaps the tree does not use are RESULTS — they follow
(an overall width becomes `2·ThkX1 + OpenX1`). Which gaps the tree uses IS the design
intent, so the edges are taken in order of evidence, then locality:

    group -1  arcs (rigid about their centre)
    group  0  accepted values of strong kinds: faces (thickness / opening), equal legs,
              pitches, and anything a DIMENSION states
    group  1  accepted values of weaker kinds: steps along an edge, run / rise, offsets
    group  2  weak gaps of strong kinds        group 3  weak gaps of other kinds

and inside a group the most LOCAL first (fewest major datums strictly between its
ends) — the chain-dimensioning rule: members are sized, totals are worked out.

A gap centred on a construction axis splits half each side (`A ± G/2`), so a centred
opening grows both ways and a symmetric member stays symmetric.

Every datum becomes `const + Σ coeff·param` — linear, because set-out drawings are
chains of sizes at fixed angles. Regeneration is evaluation; no iterative solver.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .analyse import NUM_RE, STRONG_KINDS
from .ir import (
    Analysis,
    GapKind,
    LinearForm,
    Model,
    Parameter,
    Result,
    Role,
    Status,
    TreeEdge,
)

KIND_ORDER = {GapKind.SOLID: 0, GapKind.VOID: 0, GapKind.LEG: 1, GapKind.PITCH: 1, GapKind.OPEN: 2, GapKind.DIM: 3,
              GapKind.RUN: 4, GapKind.RISE: 4, GapKind.OFFSET: 5, GapKind.CHAIN: 6, GapKind.ARC: 0}


@dataclass
class Decisions:
    """What a person changed in review. Everything is optional."""

    accept: set[str] = field(default_factory=set)  # cluster ids or names to make parameters
    reject: set[str] = field(default_factory=set)  # cluster ids or names to keep as fixed offsets
    rename: dict[str, str] = field(default_factory=dict)  # cluster id or name -> new name
    anchor: dict[str, str] = field(default_factory=dict)  # axis -> "min" | "max" | "axis"
    # Datums held at a stated absolute position — an input, not a consequence (a site
    # level). datum id -> parameter name. Which ones is a DOMAIN decision (see domains/).
    pin: dict[str, str] = field(default_factory=dict)
    # Pinned datums nothing is set out FROM (a flood level is checked against, not built on).
    reference_only: set[str] = field(default_factory=set)
    # The two lines of each size named by its lines rather than by a candidate: named like an accepted candidate, so the set-out takes
    # it before a sum nobody named that runs across it.
    named_pairs: set[tuple[str, str]] = field(default_factory=set)
    # Which structure a line belongs to, where the answer has existing and new work: "existing" / "new" for a line only one of them uses. A gap from
    # one structure's line to the other's is taken last, so each is set out from its own lines, the joints they share and the levels.
    owner: dict[str, str] = field(default_factory=dict)


def _tier(g) -> int:
    if g.kind in (GapKind.SOLID, GapKind.VOID, GapKind.LEG, GapKind.PITCH, GapKind.ARC) and not g.lengthwise:
        return 0
    if g.kind == GapKind.OPEN and not g.lengthwise:
        return 1
    return 2


class _UF:
    def __init__(self) -> None:
        self.p: dict[str, str] = {}

    def find(self, a: str) -> str:
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: str, b: str) -> None:
        self.p[self.find(a)] = self.find(b)


ROOT = "__root__"


def build(an: Analysis, dec: Decisions | None = None) -> Model:
    dec = dec or Decisions()
    clusters = an.clusters
    for c in clusters.values():
        keys = {c.id, c.name}
        if keys & dec.accept:
            c.accepted = True
        if keys & dec.reject:
            c.accepted = False
        for k in keys:
            if k in dec.rename:
                c.name = dec.rename[k]
    warnings: list[str] = []
    gaps = an.gaps
    datums = an.datums

    def group(g) -> int:
        if g.kind == GapKind.ARC:
            return -1
        c = clusters.get(g.cluster) if g.cluster else None
        accepted = bool(c and c.accepted)
        if g.slope is not None and not accepted:
            return 1
        strong = (g.kind in STRONG_KINDS and not g.lengthwise) or bool(g.dims)
        weak_end = datums[g.a].weak or datums[g.b].weak
        if accepted and not weak_end:
            return 0 if strong else 1
        return 2 if strong else 3

    tree: list[TreeEdge] = []
    non_tree: list[str] = []
    roots: dict[str, str] = {}
    own_roots: dict[str, list[str]] = defaultdict(list)  # a linked view's own root on an axis the views do not share (below)
    adjacency: dict[str, list[tuple[str, TreeEdge]]] = defaultdict(list)

    for axis in ("y", "x"):  # heights first: a slope's run reads its rise
        ax_datums = sorted((d for d in datums.values() if d.axis == axis), key=lambda d: d.value)
        if not ax_datums:
            continue
        ax_gaps = [g for g in gaps.values() if g.axis == axis]
        major = sorted(
            {datums[e].value for g in ax_gaps if group(g) == 0 for e in (g.a, g.b) if not datums[e].virtual}
        )

        def between(g, major=major) -> int:
            lo, hi = datums[g.a].value, datums[g.b].value
            return max(0, bisect_left(major, hi - an.drawing.tol) - bisect_right(major, lo + an.drawing.tol))

        def conf(g) -> float:
            c = clusters.get(g.cluster) if g.cluster else None
            return c.confidence if c else 0.0

        # Inside a group: what a DIMENSION states first (the drawing's own design inputs,
        # chain dimensions before the overall ones by locality); then sizes whose material
        # is known (thickness, opening, equal legs, member spacing) before faces with
        # nothing known between them; then the most local; then the most confident.
        # A gap that reaches a pinned level (a cushion, a clearance) comes after the
        # structure's own gaps of the same strength: the structure is sized from inside,
        # then hung on the level, and what lies between two levels is worked out.
        # Between two levels a structure could hang from, an elevation is set out from
        # below (it stands on its bed / foundation), so the lower level is tried first.
        pinned_ids = {d for d in dec.pin}

        def pin_key(g, pinned_ids=pinned_ids, axis=axis) -> tuple[int, float]:
            ends = [e for e in (g.a, g.b) if e in pinned_ids]
            if not ends:
                return (0, 0.0)
            return (1, min(datums[e].value for e in ends) if axis == "y" else 0.0)

        # A gap with a level the structure is set out from strictly inside it is a SUM across that level (an overall height that runs from
        # the bottom of a box past the road level to its top): with the level an input, each side is set out from the level and the sum is
        # worked out. Taken as an inside size it would hang one side of the structure from the other through the level — the bottom slab
        # following the top slab while the road it stands under holds — and push the real size between the level and that side (a wearing
        # course) out as the result. So it comes after every gap that does not span a level, whatever its strength.
        roots_in = sorted(datums[d].value for d in pinned_ids - dec.reference_only if d in datums and datums[d].axis == axis)
        named = set(dec.rename) | set(dec.rename.values())

        def is_named(g, named=named) -> bool:
            c = clusters.get(g.cluster) if g.cluster else None
            return bool(c and c.accepted and ({c.id, c.name} & named)) or (g.a, g.b) in dec.named_pairs or (g.b, g.a) in dec.named_pairs

        # The same rule for a sum of NAMED sizes: an overall height nobody named, from the bottom of a box to its top, taken before a course
        # named inside it (a wearing course stated by a note, no dimension) hung the bottom slab from the top slab through the sum and left the
        # course worked out — on any drawing whose road level is not an input (a side choice that lets it follow made it so). Only a sum the
        # stated sizes inside it make up whole, named or dimensioned: one with a piece nobody stated (a footing's depth below a ground line, past
        # the footing's named thickness) stays the drafter's own size, and the piece is what follows. Within a view.
        ends = {e for g in ax_gaps if is_named(g) for e in (g.a, g.b)} | {e for p in dec.named_pairs for e in p if e in datums and datums[e].axis == axis}
        named_at = sorted(datums[e].value for e in ends)
        stated: dict[str, list[str]] = defaultdict(list)  # datum → the datums a named or dimensioned size joins it to
        for g in ax_gaps:
            if is_named(g) or g.dims:
                stated[g.a].append(g.b)
                stated[g.b].append(g.a)

        def summed(g, stated=stated) -> bool:
            """g's two ends joined by named or dimensioned sizes that lie within it (in its own view)."""
            lo, hi = sorted((datums[g.a].value, datums[g.b].value))
            t = an.drawing.tol
            vs = set(an.datum_views.get(g.a, ())) | set(an.datum_views.get(g.b, ()))
            seen, todo = {g.a}, [g.a]
            while todo:
                d = todo.pop()
                for e in stated.get(d, ()):
                    if e in seen or not (lo - t <= datums[e].value <= hi + t) or {d, e} == {g.a, g.b}:
                        continue
                    if vs and an.datum_views.get(e) and not vs & set(an.datum_views[e]):
                        continue
                    if e == g.b:
                        return True
                    seen.add(e)
                    todo.append(e)
            return False

        def deferred(g, roots_in=roots_in, named=named, named_at=named_at, summed=summed) -> int:
            """0: an ordinary size. 2: a sum across a level the structure is set out from, or a sum of named sizes (see above). 1: with such a
            level on this axis, an empty space between two faces that nobody named and no dimension states — the engine's own guess at a size.
            What lies between a structure and its levels is worked out from them ("sized from inside, then hung on the level"): a guessed open
            gap taken first would hang a line from the far side of the structure (a kink of the road profile set out from the top of the slab,
            2950 mm away), where its own neighbours — 300 mm away, on the level — say where it belongs."""
            lo, hi = sorted((datums[g.a].value, datums[g.b].value))
            t = an.drawing.tol
            if bisect_left(named_at, hi - t) > bisect_right(named_at, lo + t) and not is_named(g) and summed(g):
                return 2
            if not roots_in:
                return 0
            if bisect_left(roots_in, hi - t) > bisect_right(roots_in, lo + t):
                return 2
            c = clusters.get(g.cluster) if g.cluster else None
            if g.kind == GapKind.OPEN and not g.dims and not (c and ({c.id, c.name} & named)):
                return 1
            return 0

        def across(g, owner=dec.owner) -> int:
            a, b = owner.get(g.a), owner.get(g.b)
            return 1 if a and b and a != b else 0

        order = sorted(ax_gaps, key=lambda g: (across(g), deferred(g), group(g), pin_key(g), 0 if g.dims else 1, _tier(g), between(g),
                                               KIND_ORDER.get(g.kind, 9), -conf(g), g.value))
        uf = _UF()
        # The set-out origin: a pinned datum (a stated input level), else the drawing's
        # symmetry axis, else the drawn centre line most gaps are centred on, else the
        # lowest / left-most line. Which point stays put is an anchor choice, never
        # the design; a person can change it.
        pinned = [d for d in ax_datums if d.id in dec.pin]
        # a level only checked against is held where it is drawn but is never the origin, nor a line anything hangs from: with no input level
        # on the axis, the structure stands where it would with none (a box hung from a flood level, 4950 mm above its base, by drawn distance)
        inputs = [d for d in pinned if d.id not in dec.reference_only]
        centred = sorted((a for a in an.axes if datums[a].axis == axis and an.sym_counts.get(a)), key=lambda a: -an.sym_counts[a])
        drawn = [a for a in centred if datums[a].source == "drawn-axis"]
        anchor = dec.anchor.get(axis) or ("axis" if an.global_axis.get(axis) or drawn else "min")
        real = ([d for d in ax_datums if not d.virtual and d.id not in dec.reference_only] or [d for d in ax_datums if d.id not in dec.reference_only]
                or ax_datums)
        if inputs:
            root = inputs[0].id
        elif anchor == "axis" and (an.global_axis.get(axis) or drawn):
            root = an.global_axis.get(axis) or drawn[0]
        elif anchor == "max":
            root = real[-1].id
        else:
            root = real[0].id
        roots[axis] = root
        uf.union(root, ROOT)
        for d in pinned:
            uf.union(d.id, ROOT)

        def link(child: str, parent: str, e: TreeEdge) -> None:
            adjacency[child].append((parent, e))
            adjacency[parent].append((child, e))

        for g in order:
            if g.a in dec.reference_only or g.b in dec.reference_only:
                non_tree.append(g.id)
                continue
            A = g.sym_axis
            fa, fb = uf.find(g.a), uf.find(g.b)
            if A and fa != fb and fa != uf.find(A) and fb != uf.find(A):
                uf.union(g.a, A)
                uf.union(g.b, A)
                for end in (g.a, g.b):
                    e = TreeEdge(child=end, parent=A, how="symmetric", gap=g.id, param=None, sign=0.0, amount=0.5)
                    tree.append(e)
                    link(end, A, e)
            elif fa != fb:
                uf.union(g.a, g.b)
                e = TreeEdge(child=g.b, parent=g.a, how="gap", gap=g.id, param=None, sign=0.0, amount=1.0)
                tree.append(e)
                link(g.b, g.a, e)
            else:
                non_tree.append(g.id)

        # What no gap reached hangs from a datum of the SAME entity if one is set out
        # (an isolated sloped line keeps its run), else from the nearest set-out datum — of its own view, in a unit of linked views on an axis
        # they do not share: where one view's lines sit on the sheet is layout, never a size of the other's structure (a plan's width hung on the
        # elevation's road level, 23 m away, made the width "pinned by a site level"). A view nothing of which reaches the root stands on its own,
        # from its own drawn centre line (else its first line), where it is drawn.
        settled = sorted((d for d in ax_datums if uf.find(d.id) == uf.find(ROOT) and d.id not in dec.reference_only), key=lambda d: d.value)
        vals = [d.value for d in settled]
        views = an.datum_views
        for d in ax_datums:
            if uf.find(d.id) == uf.find(ROOT):
                continue
            same = [s for s in settled if s.items & d.items and uf.find(s.id) == uf.find(ROOT)]
            if same:
                p = min(same, key=lambda s: abs(s.value - d.value))
            elif views.get(d.id):
                mine = set(views[d.id])
                pool = [s for s in settled if mine & set(views.get(s.id, ()))]
                if not pool:
                    comp = [x for x in ax_datums if uf.find(x.id) == uf.find(d.id)]
                    r = next((x for x in comp if x.source == "drawn-axis"), min(comp, key=lambda x: x.value))
                    uf.union(r.id, ROOT)
                    own_roots[axis].append(r.id)
                    for x in comp:
                        i = bisect_left(vals, x.value)
                        vals.insert(i, x.value)
                        settled.insert(i, x)
                    continue
                p = min(pool, key=lambda s: abs(s.value - d.value))
            else:
                i = bisect_left(vals, d.value)
                cands = [settled[j] for j in (i - 1, i) if 0 <= j < len(settled)]
                p = min(cands, key=lambda s: abs(s.value - d.value))
            # attach the whole floating component through this datum
            uf.union(d.id, p.id)
            e = TreeEdge(child=d.id, parent=p.id, how="attach", gap=None, param=None, sign=0.0, amount=d.value - p.value)
            tree.append(e)
            link(d.id, p.id, e)
            i = bisect_left(vals, d.value)
            vals.insert(i, d.value)
            settled.insert(i, d)

    # ── parameters: accepted clusters the tree actually uses ────────────────────────
    used: dict[str, list[str]] = defaultdict(list)
    for e in tree:
        if e.gap:
            c = gaps[e.gap].cluster
            if c and clusters[c].accepted:
                used[c].append(e.gap)
    params: dict[str, Parameter] = {}
    cluster_param: dict[str, str] = {}
    taken: set[str] = set()
    for cid, c in clusters.items():
        if not c.accepted:
            continue
        if not used.get(cid) and c.kind not in (GapKind.DIAMETER, GapKind.RING):
            continue
        name = c.name
        k = 2
        while name in taken:
            name = f"{c.name}_{k}"
            k += 1
        taken.add(name)
        cluster_param[cid] = name
        params[name] = Parameter(
            name=name,
            label=c.label,
            value=c.value,
            unit="du",
            kind=c.kind.value,
            axes=sorted(c.axes),
            confidence=c.confidence,
            status=c.status.value,
            evidence=c.evidence,
            occurrences=len(c.gaps),
            suggested=c.suggested,
            min=0.0,
        )

    # ── orientation: walk out from each root, writing linear forms ────────────────
    forms: dict[str, LinearForm] = {}

    def amount_form(e: TreeEdge) -> LinearForm:
        if e.how == "attach":
            return LinearForm(e.amount)
        g = gaps[e.gap]
        cid = g.cluster
        if cid and cid in cluster_param:
            # exact at the defaults: the gap's own residual from the shared value stays a constant
            f = LinearForm(g.value - clusters[cid].value, {cluster_param[cid]: 1.0})
        else:
            f = LinearForm(g.value)
        return LinearForm(f.const * e.amount, {k: v * e.amount for k, v in f.terms.items()})

    # Pinned datums are inputs: a level in metres (y) or a position in millimetres (x).
    u = an.drawing.units_mm
    for did_, name in dec.pin.items():
        if did_ not in datums:
            continue
        d = datums[did_]
        level = d.axis == "y"
        params[name] = Parameter(
            name=name, label=f"{'Level' if level else 'Position'} ({name})",
            value=(d.value * u + an.level_offset_mm) / 1000 if level else d.value * u,
            unit="m" if level else "mm", kind="level" if level else "position", axes=[d.axis], confidence=1.0,
            status=Status.CONFIRMED.value, evidence=[], occurrences=1,
        )
        forms[did_] = LinearForm(-an.level_offset_mm / u if level else 0.0, {name: (1000 if level else 1) / u})
    defaults = {p.name: p.value for p in params.values()}
    for axis, root in roots.items():
        if root not in forms:
            forms[root] = LinearForm(datums[root].value)
        for r in own_roots[axis]:
            forms.setdefault(r, LinearForm(datums[r].value))
        starts = [root] + [d for d in dec.pin if d in datums and datums[d].axis == axis and d != root] + own_roots[axis]
        q = deque(starts)
        while q:
            p = q.popleft()
            for other, e in adjacency[p]:
                if other in forms:
                    continue
                g = gaps[e.gap] if e.gap else None
                if g is not None and g.slope and g.cluster not in cluster_param and all(y in forms for y in (g.slope[1], g.slope[3])):
                    # x(other) = x(p) + ratio · (y(other end) − y(p's end)): the angle is kept.
                    x1, y1, x2, y2, ratio = g.slope
                    rise = forms[y2].plus(forms[y1], -1.0)
                    k = ratio if (p, other) == (x1, x2) else -ratio
                    f = forms[p].plus(rise, k)
                    f.const += datums[other].value - f.evaluate(defaults)
                    e.how, e.sign, e.param = "slope", 1.0, None
                    e.parent, e.child = p, other
                    forms[other] = f
                    q.append(other)
                    continue
                step = amount_form(e)
                sign = 1.0 if datums[other].value >= datums[p].value else -1.0
                e.sign = sign
                e.parent, e.child = p, other
                e.param = next(iter(step.terms), None)
                f = forms[p].plus(step, sign)
                # The drawing must come back exactly: a centred split whose middle sits a
                # hair off its axis keeps that hair as a constant.
                f.const += datums[other].value - f.evaluate(defaults)
                forms[other] = f
                q.append(other)
    missing = [d for d in datums if d not in forms]
    for d in missing:  # cannot happen when every datum is attached; kept honest
        forms[d] = LinearForm(datums[d].value)
        warnings.append(f"datum {d} was not reached; held fixed")

    # ── results: what the tree did not need is worked out from what it did ────────
    results: list[Result] = []
    unkept = 0
    for gid in non_tree:
        g = gaps[gid]
        if g.kind == GapKind.ARC:
            continue
        f = forms[g.b].plus(forms[g.a], -1.0)
        cid = g.cluster
        own = cluster_param.get(cid) if cid else None
        if own and abs(f.const - (g.value - clusters[cid].value)) < 1e-6 and f.terms == {own: 1.0}:
            continue  # the shared value is kept by the tree anyway
        if own:
            unkept += 1
        if g.dims or (own and len(f.terms) >= 2):
            label = f"{gaps[gid].axis.upper()} {datums[g.a].value:.0f}→{datums[g.b].value:.0f}"
            results.append(Result(gap=gid, label=label, value=g.value, form=f, dimensioned=bool(g.dims)))
    if unkept:
        warnings.append(f"{unkept} occurrence(s) of shared values close a loop and follow other values instead (reported as results)")

    # ── circles: diameter of the innermost, ring walls outside it ───────────────────
    radius: dict[int, LinearForm] = {}
    for g in gaps.values():
        if g.kind not in (GapKind.DIAMETER, GapKind.RING) or g.circle is None:
            continue
        cid = g.cluster
        pname = cluster_param.get(cid) if cid else None
        base = LinearForm(g.value - clusters[cid].value, {pname: 1.0}) if pname else LinearForm(g.value)
        if g.kind == GapKind.DIAMETER:
            radius[g.circle] = LinearForm(base.const / 2, {k: v / 2 for k, v in base.terms.items()})
    for g in sorted((g for g in gaps.values() if g.kind == GapKind.RING), key=lambda g: an.drawing.items[g.circle].radius):
        inner = radius.get(g.inner) or LinearForm(an.drawing.items[g.inner].radius)
        cid = g.cluster
        pname = cluster_param.get(cid) if cid else None
        step = LinearForm(g.value - clusters[cid].value, {pname: 1.0}) if pname else LinearForm(g.value)
        radius[g.circle] = inner.plus(step)

    # ── notes whose numbers state a value follow it ────────────────────────────────
    text_links = _link_texts(an, params, gaps, clusters, cluster_param, forms)

    # ── how much each value moves ─────────────────────────────────────────────────
    moved: dict[str, set[int]] = defaultdict(set)
    for (item, _pt, _axis), (d, _off) in an.slot_datum.items():
        for p in forms[d].terms:
            moved[p].add(item)
    for item, f in radius.items():
        for p in f.terms:
            moved[p].add(item)
    for p in params.values():
        p.affects = len(moved.get(p.name, ()))
    # A value that moves nothing visible (it only sets out a construction axis no
    # entity hangs from) is folded back into a constant.
    for name in [n for n, p in params.items() if p.affects == 0]:
        v = params.pop(name).value
        for f in [*forms.values(), *radius.values(), *(r.form for r in results)]:
            if name in f.terms:
                f.const += f.terms.pop(name) * v

    return Model(
        analysis=an,
        parameters=params,
        forms=forms,
        tree=tree,
        results=results,
        roots=roots,
        radius=radius,
        text_links=text_links,
        warnings=warnings,
    )


def _link_texts(an: Analysis, params, gaps, clusters, cluster_param, forms) -> dict[int, list[tuple[str, str, int]]]:
    """A number in a note that states a value (or a level) is rewritten when it changes.

    Unambiguous matches only: one parameter of that size, or the one whose occurrence
    is nearest the note. Numbers with 2+ decimals that equal a horizontal datum read as
    a level in metres follow that datum ("RL 56.388" stays the level of its line).
    """
    dr = an.drawing
    links: dict[int, list[tuple[str, str, int]]] = {}
    by_value: dict[int, list[str]] = defaultdict(list)
    for name, p in params.items():
        if p.kind not in ("level", "position"):
            by_value[round(p.value * dr.units_mm)].append(name)
    occurrences: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for cid, name in cluster_param.items():
        for gid in clusters[cid].gaps:
            s = gaps[gid].sample
            if s:
                occurrences[name].append(s)
    ydatums = sorted((d for d in an.datums.values() if d.axis == "y" and not d.virtual), key=lambda d: d.value)
    for it in dr.items:
        if it.dxftype not in ("TEXT", "MTEXT") or not it.text:
            continue
        x, y = it.pts[0]
        h = it.text_height or 1.0
        found: list[tuple[str, str, int]] = []
        for tok in NUM_RE.findall(it.text):
            v = float(tok)
            dec = len(tok.split(".")[1]) if "." in tok else 0
            if dec >= 2:
                level = next((d for d in ydatums if abs(d.value * dr.units_mm + an.level_offset_mm - v * 1000) <= 0.5 and abs(d.value - y) <= 40 * h), None)
                if level is not None:
                    found.append((tok, f"datum:{level.id}", dec))
                    continue
                # a size written in metres ("2.500 X 2.000 m") states the value it equals
                metres = by_value.get(round(v * 1000), [])
                if len(metres) == 1:
                    found.append((tok, f"m:{metres[0]}", dec))
                continue
            cands = by_value.get(round(v), []) if dec == 0 else []
            if len(cands) == 1:
                found.append((tok, cands[0], 0))
            elif len(cands) > 1:
                best = min(cands, key=lambda n: min(((sx - x) ** 2 + (sy - y) ** 2 for sx, sy in occurrences[n]), default=1e30))
                dmin = min(((sx - x) ** 2 + (sy - y) ** 2 for sx, sy in occurrences[best]), default=1e30) ** 0.5
                if dmin <= 15 * h:
                    found.append((tok, best, 0))
        if found:
            links[it.index] = found
    return links


def describe(model: Model) -> str:
    """A plain-language account of the model."""
    an = model.analysis
    dr = an.drawing
    u = dr.units_mm
    lines = [(f"{dr.path}: {len(dr.items)} entities, {sum(1 for i in dr.items if i.role == Role.STRUCTURAL)} structural; "
              f"{len(an.datums)} datums, {len([g for g in an.gaps.values() if g.axis in ('x', 'y')])} candidate relationships, {len(an.clusters)} candidate values.")]
    for n in an.notes:
        lines.append(f"  {n}")
    lines.append(f"PARAMETERS ({len(model.parameters)}):")
    for p in sorted(model.parameters.values(), key=lambda p: (-p.affects, p.name)):
        sug = f"  [drawing says: {p.suggested}]" if p.suggested else ""
        lines.append(f"  {p.name:<10} = {p.value * u:>10.1f} mm  {p.status:<9} {p.confidence:.2f}  ×{p.occurrences:<3} moves {p.affects:>3} entities  {p.label}{sug}")
    if model.results:
        lines.append(f"DISCOVERED RELATIONSHIPS ({len(model.results)}):")
        for r in model.results[:30]:
            lines.append(f"  {'[dim] ' if r.dimensioned else ''}{r.label:<18} {r.value * u:>9.1f} = {format_form(r.form, u)}")
    for w in model.warnings:
        lines.append(f"  note: {w}")
    return "\n".join(lines)


def format_form(f: LinearForm, u: float = 1.0) -> str:
    parts = []
    for p, c in sorted(f.terms.items(), key=lambda t: -abs(t[1])):
        coef = "" if abs(c - 1) < 1e-9 else "-" if abs(c + 1) < 1e-9 else f"{c:g}·"
        parts.append(f"{coef}{p}")
    if abs(f.const * u) > 1e-6 or not parts:
        parts.append(f"{f.const * u:.1f}")
    s = " + ".join(parts)
    return re.sub(r"\+ -", "- ", s)
