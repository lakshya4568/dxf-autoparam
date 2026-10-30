"""What the agent is told about WHERE it works, before it looks at anything: the drawing (and the sheet revision) it
works on, the view(s) and the unit they form, units and frames, the references it may use (regions, lines, candidates
and their occurrences, annotations, the labels on its pictures), what is already decided (named values, formulas and
who owns each line), how this unit is tied to the rest of the sheet (projection links, shared sizes), what must not
move (held parts, fixed lines) and what is still open.

Compact on purpose — rows, not objects, and no geometry (the inspect tools answer from the authoritative analysis on
demand). Built from the same analysis and program the tools and the validator use, so every id in it resolves.

    ctx = drawing_context(an, prog, labels)                 # a drawing on its own
    ctx = unit_context(sm, "U01_03", an, prog, labels)      # one unit of a sheet: adds the sheet relationships
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..ir import GapKind
from ..program import ExprError, Program, names_in
from ..topology import of

# who sets a line, in words the agent and a person both read
OWNER_WORDS = {"ai": "your formula", "dimension": "a named size", "slope": "a stated slope", "held": "a held part (kept as drawn)",
               "existing": "existing work (kept as built)", "constraint": "a constraint", "kept": "kept as drawn", "geometry": "the set-out"}
FIXED_ORIGINS = ("held", "existing")


def _r(v: float) -> float:
    return round(float(v), 1)


def level_lines(prog: Program) -> dict[str, str]:
    """Lines set by a level input alone (a site level): line → level name. A size never moves them."""
    levels = {n for n, p in prog.params.items() if p.kind == "level"}
    out = {}
    for d, e in prog.formulas.items():
        try:
            ns = names_in(e)
        except ExprError:
            continue
        if ns and ns <= levels:
            out[d] = min(ns)
    return out


def owner(prog: Program, d: str) -> str:
    """Who sets a line, by name where there is one: the named size, the constraint, or — for a line set out by the geometry — the values it follows."""
    o = prog.origin.get(d, "geometry")
    lv = level_lines(prog).get(d)
    if lv:
        return f"level {lv}"
    why = prog.origin_why.get(d)
    if o == "dimension" and why:
        return f"the named size {why}"
    if o == "constraint" and why:
        return f"the constraint '{why[:50]}'"
    if o == "geometry":
        try:
            follows = sorted(n for n in names_in(prog.formulas.get(d, "")) if n in prog.params)
        except ExprError:
            follows = []
        if follows:
            return f"the set-out ({d} follows {', '.join(follows[:3])})"
    return OWNER_WORDS.get(o, o)


def fixed_lines(prog: Program, held_parts: set[str] | None = None) -> dict[str, str]:
    """Lines that must not move when a size changes, with why: held / existing work, site levels, and — while the agent
    builds — the lines of parts it marked keep-as-drawn (parametrize=false; the hold is applied at the end)."""
    out = {d: OWNER_WORDS[prog.origin[d]] for d in prog.formulas if prog.origin.get(d) in FIXED_ORIGINS}
    for d, lv in level_lines(prog).items():
        out.setdefault(d, f"level {lv}")
    parts = prog.intent.get("parts") or {}
    for n in held_parts or ():
        if n in parts:
            for d in parts[n].datums:
                out.setdefault(d, f"part {n} is kept as drawn")
    return out


def held_part_names(answer: dict | None) -> set[str]:
    return {c.get("name") for c in (answer or {}).get("components", []) if c.get("parametrize") is False}


def occurrence_pairs(an) -> dict[tuple[str, str], list[str]]:
    """(line, line) → the occurrences (gap ids) measured between them, either order."""
    out: dict[tuple[str, str], list[str]] = {}
    for gid, g in an.gaps.items():
        if g.axis in ("x", "y"):
            out.setdefault(tuple(sorted((g.a, g.b))), []).append(gid)
    return out


def drawing_context(an, prog: Program, labels: dict | None = None, answer: dict | None = None, report=None) -> dict:
    dr = an.drawing
    u = dr.units_mm
    topo = of(an)
    src = Path(dr.path)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:16] if src.exists() else None
    named = []
    for n, p in prog.params.items():
        if p.source != "ai" and p.kind != "level":
            continue
        named.append([n, _r(p.value), p.unit, "-".join(p.measures) if p.measures else "", p.kind])
    decided = [[d, e, owner(prog, d)] for d, e in sorted(prog.formulas.items()) if prog.origin.get(d, "geometry") != "geometry"][:60]
    multi = []
    for c in sorted(an.clusters.values(), key=lambda c: (-len(c.gaps), -c.confidence)):
        xy = [g for g in c.gaps if an.gaps[g].axis in ("x", "y")]
        if len(xy) > 1 and c.kind not in (GapKind.DIAMETER, GapKind.RING):
            multi.append([c.id, _r(c.value * u), c.kind.value, [f"{g}:{an.gaps[g].a}-{an.gaps[g].b}" for g in xy[:8]]])
        if len(multi) >= 30:
            break
    held = held_part_names(answer)
    fixed = fixed_lines(prog, held)
    unresolved = [f"{e['code']} {e['item']}: {e['message']}"[:200] for e in (report.errors() if report else [])][:8]
    unresolved += [f"review {r['kind']} {r['name']} (confidence {r['confidence']})" for r in (prog.intent.get("review") or [])][:4]
    unlinked_notes = 0
    links = prog.text_links or {}
    for it in dr.items:
        if it.dxftype in ("TEXT", "MTEXT") and it.text and any(ch.isdigit() for ch in it.text) and it.index not in links:
            unlinked_notes += 1
    return {
        "drawing": {"file": src.name, "sha256_16": digest, "entities": len(dr.items)},
        "frames": {"units": f"1 drawing unit = {u:g} mm; at_mm / sizes are in mm; +x right, +y up",
                   "levels": f"RL (m) = (y_mm + {an.level_offset_mm:g}) / 1000" if an.stated_levels else "no stated levels",
                   "extent_mm": [_r(v * u) for v in dr.extent]},
        "references": {"regions": f"R… ({len(topo.regions)}) — the region map picture", "lines": f"x… / y… / ax… ({len(an.datums)})",
                       "candidates": f"c… ({len(an.clusters)}); each has occurrences g… (one per place it is measured)",
                       "annotations": "entity ids of dimensions / notes (inspect_dimensions)",
                       "labelled_on_set_out_picture": sorted(labels or {}),
                       "resolve": "resolve_labels(labels) says what any label you see or read refers to"},
        "named_values [name, mm, unit, between lines, kind]": named,
        "decided_lines [line, formula, set by]": decided,
        "equal_sizes [candidate, mm, kind, occurrences g:from-to] (bind only the occurrences you mean)": multi,
        "held_parts": sorted(held),
        "fixed_lines [line, why]": [[d, w] for d, w in sorted(fixed.items())][:40],
        "unresolved": unresolved + ([f"{unlinked_notes} note(s) state a number tied to no unique pair of lines: not bindable"]
                                    if unlinked_notes else []),
    }


def unit_context(sm, uid: str, an, prog: Program, labels: dict | None = None, report=None) -> dict:
    """drawing_context for one unit of a sheet, plus: the sheet revision the work starts from, the unit's views (names,
    types, scales), its projection links, the sizes it shares with other views (and whether they drive here), the
    relations a person or the views stage found, and the questions still open."""
    u = sm.units[uid]
    ctx = drawing_context(an, prog, labels, u.answer, report)
    ctx["drawing"].update({"sheet_revision": sm.revision, "unit": uid})
    views = []
    for v in u.views:
        g = sm.layout.group(v)
        views.append({"id": v, "name": g.name, "type": g.view_type, "scale": f"1:{g.scale:g}" if g.scale else None,
                      "own_units_mm": g.units_mm, "questions": g.questions[:3]})
    ctx["views"] = views
    from ..projection import described

    ctx["projection"] = described(sm, u.views)
    shared = []
    for p in sm.shared.values():
        mine = [b for b in p.bindings if b.unit == uid]
        if not mine:
            continue
        shared.append({"name": p.name, "here_as": mine[0].param, "status_here": mine[0].status, "value_mm": _r(p.value),
                       "also_in": sorted({b.unit for b in p.bindings if b.unit != uid}),
                       "rule": "keep this name driving its lines here: the other views follow it"})
    ctx["shared_sizes"] = shared
    ctx["view_relations"] = [r for r in sm.relations if r.get("a") in u.views or r.get("b") in u.views]
    ctx["unresolved"] = ctx["unresolved"] + [q for q in sm.questions][:5] + ([u.dropped] if u.dropped else [])
    ctx["committed_values"] = {k: _r(v) for k, v in sm.values.get(uid, {}).items()}
    return ctx


class SheetScope:
    """The sheet a unit belongs to, as the agent's tools see it — read-only: which views an entity of the unit is on,
    the sizes it shares with other views, and whether the sheet changed since the work began (its revision)."""

    def __init__(self, sm, uid: str):
        self.sm, self.uid = sm, uid
        self.revision = sm.revision
        self.back = list(sm.units[uid].back)

    def stale(self) -> bool:
        return self.sm.revision != self.revision

    def shared_here(self) -> dict[str, str]:
        """This unit's local value name → the shared name other views follow."""
        return {b.param: p.name for p in self.sm.shared.values() for b in p.bindings if b.unit == self.uid}

    def other_units(self, local: str) -> list[str]:
        name = self.shared_here().get(local)
        p = next((q for q in self.sm.shared.values() if q.name == name), None)
        return sorted({b.unit for b in p.bindings if b.unit != self.uid}) if p else []

    def namesakes(self, name: str) -> list[tuple[str, float | None]]:
        """The other units that already carry a value of this name, with its number (a shared name is not here: its units are joined already)."""
        if any(p.name == name for p in self.sm.shared.values()):
            return []
        return self.sm.namesakes(name, {self.uid})

    def dimension_values(self) -> dict[int, list[tuple[str, str, float]]]:
        """What every unit's DIMENSIONS state, in mm at its own scale, by the rounded number: {mm: [(unit, dimension id, mm)]}. Read from the
        units already analysed (the sheet keeps them); a unit never opened is not analysed for this."""
        from ..cadjson import entity_id

        if getattr(self, "_dims", None) is not None:
            return self._dims
        out: dict[int, list[tuple[str, str, float]]] = {}
        for uid, u in self.sm.units.items():
            an = getattr(u, "an", None)
            if an is None:
                continue
            um = an.drawing.units_mm
            for it in an.drawing.items:
                if it.dxftype == "DIMENSION" and it.extra.get("measurement"):
                    mm = float(it.extra["measurement"]) * um
                    out.setdefault(round(mm), []).append((uid, entity_id(it), round(mm, 1)))
        self._dims = out
        return out

    def drivers(self, a: str, b: str) -> list[str]:
        """The values somebody named that move the distance between two set-out lines of this unit AS THE SHEET STANDS — its committed
        answer with the design intent the engine derived (which side of each size stays): a size they move is a result of them (a sum, a
        difference), not a free input. Empty for a unit nothing was committed for. Measured once per revision, every named value stepped."""
        from ..generic import is_generated

        if getattr(self, "_drv_rev", None) != self.sm.revision:
            self._drv_rev, self._drv = self.sm.revision, None
            u = self.sm.units.get(self.uid)
            if u is not None and u.answer and u.answer.get("parameters"):
                prog = self.sm.unit(self.uid).prog
                vals = {**prog.defaults(), **self.sm._values_for(u, {})}
                try:
                    v0 = prog.datum_values(vals)
                    steps = {n: prog.datum_values({**vals, n: float(vals[n]) + (1e-3 if p.kind == "level" else 1.0)})
                             for n, p in prog.params.items() if p.kind in ("length", "level") and not (is_generated(n) and p.source != "ai")}
                except (KeyError, ValueError, ArithmeticError) as exc:  # a program that cannot be stepped drives nothing that can be measured here
                    steps, v0 = {}, {}
                    self._drv_error = f"{type(exc).__name__}: {exc}"[:160]
                self._drv = (v0, steps)
        if not self._drv:
            return []
        v0, steps = self._drv
        if a not in v0 or b not in v0:
            return []
        return sorted(n for n, v1 in steps.items() if abs((v1[b] - v1[a]) - (v0[b] - v0[a])) > 1e-9)

    def views_of_items(self, items) -> list[str]:
        group = self.sm.layout.item_group
        return sorted({group.get(self.back[i]) for i in items if 0 <= i < len(self.back)} - {None})

    def knows(self, label: str) -> bool:
        return label in self.sm.units or any(g.id == label for g in self.sm.layout.groups)

    def describe(self, label: str) -> dict:
        if label in self.sm.units:
            u = self.sm.units[label]
            return {"is": "unit", "views": u.views, "this_unit": label == self.uid}
        g = self.sm.layout.group(label)
        return {"is": g.kind, "name": g.name, "type": g.view_type, "unit": self.sm.unit_of_view.get(label),
                "in_this_unit": self.sm.unit_of_view.get(label) == self.uid}
