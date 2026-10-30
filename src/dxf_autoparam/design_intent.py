"""Design intent: WHICH SIDE of a size stays when it changes, and what goes with each side — decided from what the drawing itself shows, never
left to whichever chain of lines the set-out happened to be built along.

A named size is two lines of the drawing. When its value grows, something has to give: one end moves and the other stays, or both move
half, and everything drawn against the moving end goes with it. Left implicit, that is decided by accident (the set-out is a tree rooted at
the left-most line, so almost every size grew rightwards: a symmetric box widened on one side only, a slab thickened into the cell below it).
Here it is decided per assembly and axis, by evidence, in this order — and every decision says which evidence it rests on:

  1. SYMMETRY   the faces of the assembly mirror about a line (a drawn centre line, the drawing's axis of symmetry, the centre of a closed
                outline): the assembly stays about it, each side moves half. A symmetric structure stays symmetric.
  2. FIXED      lines that must not move (a stated level, existing work, a stated slope that cannot be solved either way) allow only one
                side to stay: that side stays.
  3. EXISTING   the size belongs to new work that abuts existing work: the existing side stays, the new work grows away from it.
  4. CONVENTION nothing in the drawing says: the left / bottom side stays (a structure stands on its base), and the decision is marked
                PROVISIONAL, so it is shown to the person as an assumption, not as a fact, and is theirs to change.

What touches the assembly moves with its side (a backfill against a wall, a slab on it); what is only hung on its lines by the set-out stays
where it is drawn. Each candidate is tried for real — the plans written, the unit built, every promise of every plan measured on the
regenerated geometry — and the first that holds is kept; a candidate that does not hold says why. The decision is stored as ordinary accepted
plans (source "design intent"), so it is measured every time, undone with the step it belongs to, and replaced by anything a person chooses
(a person's plan always outranks it). Nothing here names a unit, a value or a coordinate.
"""

from __future__ import annotations

import contextlib
import copy
import json
import re
import time
from collections import Counter
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from .assembly import (
    AXIS_SOURCES,
    MID,
    assembly_lines,
    centre_candidates,
    held_root,
    is_axis,
    level_of,
    line_values_mm,
    mirror_stats,
    mirrored,
    protected_lines,
    rates,
)
from .plan import accept, build_plan, core_parts, drives_pairs, pairs_of
from .program import Program

SOURCE = "design intent"
SIDES = {"x": ("left", "right"), "y": ("bottom", "top")}
FOLLOW = {"target": "connected", "kind": "generic", "mode": "follow", "source": SOURCE,
          "clause": "what touches the assembly moves with its side"}

Build = Callable[[dict], tuple[Program, Any]]  # an answer → (the program it makes, the report): how a candidate is tried for real


@dataclass
class Driver:
    name: str
    axis: str
    pairs: list[tuple[str, str]]  # the lines it drives now, low → high as drawn
    extra: list[tuple[str, str]] = field(default_factory=list)  # occurrences it was asked for and could not follow in the plain set-out


@dataclass
class Assembly:
    """Lines that move as one structure on an axis (a view of a section, a detail beside it), with the sizes that grow it."""

    id: str  # its lowest line: a stable name for it
    members: set[str]
    drivers: list[Driver]  # each with only the occurrences that lie in this assembly
    cores: list[tuple[tuple[str, str], set[str]]] = field(default_factory=list)  # per occurrence: the lines of the structure it is a size of
    plan_like: bool = False  # the unit is drawn in plan: symmetry about a line is design intent there, not a coincidence of proportions


@dataclass
class AxisDecision:
    axis: str
    assembly: str
    policy: str  # centered | start_fixed | end_fixed | as_set_out
    centre: str | None
    status: str  # decided | provisional | person | undecided
    evidence: list[str]
    drivers: list[str]
    dropped: list[dict] = field(default_factory=list)  # sizes left out of it (they keep the set-out's direction), and why
    tried: list[dict] = field(default_factory=list)  # what was tried before this and why it did not hold
    blocked: list[dict] = field(default_factory=list)  # undecided: the lines nothing may move that stood in the way, and what sets each (kind, name)

    def as_dict(self) -> dict:
        return {"axis": self.axis, "assembly": self.assembly, "policy": self.policy, "centre": self.centre, "status": self.status,
                "evidence": self.evidence, "drivers": self.drivers, "dropped": self.dropped, "tried": self.tried, "blocked": self.blocked}


@dataclass
class Intent:
    plans: list[dict] = field(default_factory=list)
    axes: list[AxisDecision] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"axes": [a.as_dict() for a in self.axes], "plans": len(self.plans)}


class OutOfTime(Exception):
    """A search given a time (`within`) ran past it: what it had found so far is not an answer, and the caller says so."""


_DEADLINE: ContextVar[float | None] = ContextVar("design_intent_deadline", default=None)


@contextlib.contextmanager
def within(seconds: float):
    """Every attempt started inside this block is refused (OutOfTime) once `seconds` have passed. For a question a person waits on with the sheet
    held — the ways to settle one value tried for real, each a whole unit built — never for a commit, which decides with no limit."""
    token = _DEADLINE.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def _in_time() -> None:
    end = _DEADLINE.get()
    if end is not None and time.monotonic() > end:
        raise OutOfTime("the time given to this search ran out")


def stored(answer: dict) -> Intent | None:
    """The intent an answer records — derived when it was committed (its plans and `intent_axes`) — or None when it records none, or a record
    from before what was tried was kept (the ways to settle an axis are read from that)."""
    if answer.get("intent_axes") is None or any("tried" not in a for a in answer["intent_axes"]):
        return None
    keys = AxisDecision.__dataclass_fields__
    axes = [AxisDecision(**{"dropped": [], "tried": [], "blocked": [], "centre": None, **{k: v for k, v in a.items() if k in keys}})
            for a in answer["intent_axes"]]
    return Intent(plans=[copy.deepcopy(p) for p in answer.get("plans", []) if derived(p)], axes=axes)


def strip(answer: dict) -> dict:
    """The answer without the plans the engine derived, and without its record of having derived them: what is left is what a person or the agent wrote."""
    out = copy.deepcopy(answer)
    if "plans" in out:
        out["plans"] = [p for p in out["plans"] if (p.get("anchor") or {}).get("source") != SOURCE]
    out.pop("intent_axes", None)
    return out


def derived(plan: dict) -> bool:
    return (plan.get("anchor") or {}).get("source") == SOURCE


def _add(answer: dict, plan: dict) -> dict:
    """The answer with this plan added (a derived plan is replaced only by one of the same id: one value may have a plan per assembly)."""
    out = copy.deepcopy(answer)
    out["plans"] = [p for p in out.get("plans", []) if p.get("id") != plan.get("id")] + [plan]
    return out


def drivers(prog: Program, answer: dict) -> list[Driver]:
    """The named lengths that GROW something: measured between two lines, driving at least one pair 1 mm per mm, on one axis (the axis
    most of their occurrences lie on). Levels are not sizes; a value that is only worked out between lines other inputs fix is a reading."""
    an = prog.analysis
    frozen = {r.get("name") for r in answer.get("frozen", []) if isinstance(r, dict)}
    rows = {p.get("name"): p for p in answer.get("parameters", []) if isinstance(p, dict)}
    out: list[Driver] = []
    for name, prm in prog.params.items():
        if prm.kind == "level" or prm.source not in ("ai", "dimension", "person") or name in frozen or not prm.measures:
            continue
        pairs = pairs_of(prog, answer, name)
        if not pairs or any(a not in an.datums or b not in an.datums for a, b in pairs):
            continue
        axis = Counter(an.datums[a].axis for a, _b in pairs).most_common(1)[0][0]
        pairs = [p for p in pairs if an.datums[p[0]].axis == axis]
        lost = set(drives_pairs(prog, name, pairs))
        driven = [p for p in pairs if p not in lost]
        if not driven:
            continue
        asked: list[tuple[str, str]] = []
        for g in (rows.get(name) or {}).get("occurrences_asked") or []:  # what the model asked for and the plain set-out could not follow
            gap = an.gaps.get(g)
            if gap is not None and gap.axis == axis:
                pr = (gap.a, gap.b) if an.datums[gap.a].value <= an.datums[gap.b].value else (gap.b, gap.a)
                if pr not in driven and pr not in asked:
                    asked.append(pr)
        out.append(Driver(name, axis, driven, asked))
    return out


def assemblies(prog: Program, parts: dict, axis: str, group: list[Driver], sheet: dict | None = None) -> list[Assembly]:
    """The structures the sizes of an axis belong to, told apart: sizes whose assemblies share a line are one structure; two views of a unit, or
    a detail beside a section, are two — each stays about ITS own centre, and neither pushes the other."""
    v = line_values_mm(prog)
    items = []
    for d in group:
        for pr, extra in [(p, False) for p in d.pairs] + [(p, True) for p in d.extra]:
            core = core_parts(parts, [pr], prog) if parts else set()
            items.append((d, pr, extra, assembly_lines(prog, parts or None, core or None, axis, seed=set(pr))))
    root = list(range(len(items)))

    def find(i: int) -> int:
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    seen: dict[str, int] = {}
    for i, (_d, _p, _e, lines) in enumerate(items):
        for ln in lines:
            if ln in seen:
                root[find(i)] = find(seen[ln])
            else:
                seen[ln] = i
    by_root: dict[int, list[int]] = {}
    for i in range(len(items)):
        by_root.setdefault(find(i), []).append(i)
    out = []
    types = (sheet or {}).get("view_types") or []
    for idx in by_root.values():
        members = set().union(*(items[i][3] for i in idx))
        per: dict[str, Driver] = {}
        for i in idx:
            d, pr, extra, _l = items[i]
            drv = per.setdefault(d.name, Driver(d.name, axis, [], []))
            (drv.extra if extra else drv.pairs).append(pr)
        out.append(Assembly(min(members, key=lambda x: (v[x], x)), members, list(per.values()), [(items[i][1], items[i][3]) for i in idx],
                            plan_like=bool(types) and set(types) == {"plan"}))
    out.sort(key=lambda a: v[a.id])
    return out


def _person_choice(answer: dict, asm: Assembly, axis: str, prog: Program) -> dict | None:
    """An anchor a person (or the agent, with a person's say-so) chose for a size of this assembly: it governs the whole assembly."""
    an = prog.analysis
    for p in answer.get("plans", []):
        a = p.get("anchor") or {}
        pairs = (p.get("driver") or {}).get("pairs") or []
        if p.get("status") == "accepted" and a.get("policy") and a.get("source") != SOURCE and pairs and pairs[0][0] in an.datums \
                and an.datums[pairs[0][0]].axis == axis and any(x in asm.members for pr in pairs for x in pr):
            return {**a, "driver": (p.get("driver") or {}).get("parameter")}
    return None


def _centre_kind(prog: Program, c: str) -> str:
    if c not in prog.analysis.datums:  # the middle of the size itself (assembly.MID): a construction, not a line of the drawing
        return "the middle of the size itself"
    src = prog.analysis.datums[c].source
    return {"drawn-axis": "a drawn centre line", "global-axis": "the drawing's axis of symmetry",
            "loop-axis": "the centre of a closed outline"}.get(src, "a line")


def _centres(prog: Program, asm: Assembly) -> list[tuple[str, int, int]]:
    """Lines the assembly could stay about, best first, with how many faces mirror about each. Judged on the STRUCTURE each size belongs to (its
    own parts' faces), not on everything that touches it: a box is symmetric although the backfill against one wall is not. A line counts only
    when EVERY face of that structure has a mirror image about it (an axis that was drawn ranks before one that was derived)."""
    rank = {"drawn-axis": 0, "global-axis": 1, "loop-axis": 2}
    best: dict[str, int] = {}
    total: dict[str, int] = {}
    axis = asm.drivers[0].axis if asm.drivers else "x"
    for pr, core in asm.cores:
        for c in {c for c, _w in centre_candidates(prog, core, [pr])} | {c for c, _w in centre_candidates(prog, core, [])}:
            n = mirrored(prog, core, c)
            if not n:
                continue
            if not is_axis(prog, c):  # a plain line at the middle can match by coincidence (two layers of the same thickness): it needs more
                n_all = mirror_stats(prog, core, c)[1]
                if axis == "y" and not asm.plan_like:  # heights are set out from below: top-bottom symmetry in a section is no evidence
                    continue
                if n < n_all and n < 0.75 * n_all:
                    continue
            best[c] = max(best.get(c, 0), n)
            total[c] = mirror_stats(prog, core, c)[1]
    out = [(c, n, total[c]) for c, n in best.items()]
    out.sort(key=lambda t: (rank.get(prog.analysis.datums[t[0]].source, 3), -t[1], t[0]))
    return out


def _existing_side(prog: Program, parts: dict, axis: str, asm: Assembly) -> str | None:
    """`start_fixed` / `end_fixed` when the sizes belong to new work and the existing work it abuts lies wholly on one side of them."""
    if not parts:
        return None
    pairs = [p for d in asm.drivers for p in d.pairs]
    core = core_parts(parts, pairs, prog)
    if not core or any(parts[n].existing for n in core if n in parts):
        return None
    v = line_values_mm(prog)
    new_lines: set[str] = set()
    old_lines: set[str] = set()
    for n, p in parts.items():
        if any(q.parent == n for q in parts.values()):
            continue
        ls = {d for d in p.own_datums if d in asm.members and prog.analysis.datums[d].axis == axis and not is_axis(prog, d)}
        (old_lines if p.existing else new_lines).update(ls)
    old_only = old_lines - new_lines
    if not old_only:
        return None
    tol = max(prog.analysis.drawing.tol * prog.analysis.drawing.units_mm * 2, 0.5)
    lo, hi = min(v[a] for a, _b in pairs), max(v[b] for _a, b in pairs)
    below = [d for d in old_only if v[d] <= lo + tol]
    above = [d for d in old_only if v[d] >= hi - tol]
    if below and not above:
        return "start_fixed"
    if above and not below:
        return "end_fixed"
    return None


def _named(prog: Program, blocked: list[dict]) -> list[dict]:
    """The lines that stood in the way, with what sets each said by name: a site level its name, a held part the part that keeps it."""
    parts = prog.intent.get("parts") or {}
    out: list[dict] = []
    for b in blocked:
        row = {"line": b["line"], "kind": b.get("kind")}
        if b.get("kind") == "level" and (name := level_of(prog, b["line"])):
            row["level"] = name
        elif b.get("kind") == "held" and (part := held_root(parts, b["line"])):
            row["part"] = part
        if row not in out:
            out.append(row)
    return out


def _plans_for(prog: Program, base: dict, sheet: dict | None, group: list[Driver], asm: str, suffix: str, policy: str, centre: str | None,
               evidence: list[str], status: str, follow_all: bool, memo: dict | None = None,
               projected: list[str] | None = None) -> tuple[list[dict] | None, str, str | None, dict]:
    """One accepted plan per driver of the group, all with this anchor: (plans, "", None, {}); or (None, why, the driver that has none, what stood
    in the way: {names: the sizes it is about, blocked: the lines nothing may move}). `memo`: plans already built for the same request on the
    same program — a driver's plan depends on its own request only, not on the others of the group, and the group is tried again as it shrinks."""

    def plan_of(req: dict) -> dict:
        if memo is None:
            return build_plan(prog, base, req, sheet=sheet, reader=False)
        key = json.dumps(req, sort_keys=True, default=str)
        if key not in memo:
            memo[key] = build_plan(prog, base, req, sheet=sheet, reader=False)
        return copy.deepcopy(memo[key])  # the caller writes into the plan it gets

    plans: list[dict] = []
    for d in group:
        req: dict = {"id": f"I_{d.name}{suffix}", "driver": {"parameter": d.name, "pairs": [list(p) for p in d.pairs],
                                                             "extra_pairs": [list(p) for p in d.extra]},
                     "anchor": {"policy": policy, "centre": centre, "source": SOURCE}, "directives": [dict(FOLLOW)],
                     **({"members_from_projection": sorted(projected)} if projected else {})}
        plan = plan_of(req)
        if plan["status"] == "needs_decision":
            if any(not str(q["about"]).startswith("attached:") for q in plan["questions"]):
                return None, "; ".join(q["text"] for q in plan["questions"][:1]), d.name, {"names": [d.name]}
            req["decisions"] = {q["about"]: ("follow" if follow_all else q.get("recommended") or "follow") for q in plan["questions"]}
            plan = plan_of(req)
        if plan["status"] != "ready":
            alt = next((a for a in (plan.get("anchor") or {}).get("alternatives", []) if a.get("policy") == policy and a.get("centre") == centre), None)
            why = "; ".join((plan["conflicts"] + [q["text"] for q in plan["questions"]])[:1]) or f"the plan is {plan['status']}"
            return None, why, d.name, {"names": [d.name], "blocked": _named(prog, (alt or {}).get("blocked", []))}
        plan["anchor"].update(evidence=list(evidence), status=status, assembly=asm)
        plans.append(accept(plan, by=SOURCE))
    return plans, "", None, {}


_PLAN_OF = re.compile(r"plan I_([A-Za-z0-9]+)")


def _holds(prog1: Program, base: dict, plans: list[dict], build: Build, group: list[Driver],
           watch: list[Driver] | None = None) -> tuple[bool, str, str | None, dict]:
    """Try the plans for real: the unit built with them, every promise measured (V16), every size of the unit — not only the ones planned — still
    growing 1 mm per mm of its value (an anchor that rewrites the line a size drives turns that input into a reading, and says nothing).
    (True, "", None, {}); or (False, why, the size it is about, when the message says; what stood in the way: {names, blocked})."""
    trial = base
    for p in plans:
        trial = _add(trial, p)
    try:
        prog2, rep = build(trial)
    except Exception as exc:  # noqa: BLE001 — a candidate that does not even build is a candidate that does not hold
        return False, f"it does not build: {type(exc).__name__}: {exc}", None, {}
    bad = [e["message"] for e in rep.errors() if e.get("code") == "V16"]
    if bad:
        m = _PLAN_OF.search(bad[0])
        blocked = [b for row in prog2.intent.get("plans", []) for b in (((row.get("compiled") or {}).get("stack")) or {}).get("blocked", [])]
        return False, bad[0], m.group(1) if m else None, {"names": [m.group(1)] if m else [], "blocked": _named(prog2, blocked)}
    seen: set[str] = set()
    every = {w.name: w.pairs for w in watch or []}  # all the occurrences of a size, in every assembly: the group's own carry only this assembly's
    for d in [*group, *(watch or [])]:
        if d.name in seen:
            continue
        seen.add(d.name)
        if d.name not in prog2.params:
            return False, f"{d.name} would stop being an input (it would be worked out from the lines)", d.name, {"names": [d.name]}
        lost = drives_pairs(prog2, d.name, every.get(d.name) or d.pairs)
        if lost:
            return False, f"{d.name} would no longer drive {', '.join(f'{a}–{b}' for a, b in lost[:3])}", d.name, {"names": [d.name]}
    # independence: a size that did not move with a value before must not start to (it would be an input in name only)
    for d in group:
        before, after = rates(prog1, d.name), rates(prog2, d.name)
        for w in watch or []:
            if w.name == d.name:
                continue
            for lo, hi in w.pairs:
                if abs(after.get(hi, 0.0) - after.get(lo, 0.0)) > 1e-6 and abs(before.get(hi, 0.0) - before.get(lo, 0.0)) <= 1e-6:
                    return False, f"{w.name} would change when {d.name} does (it would hang on what {d.name} moves)", d.name, {"names": [w.name, d.name]}
    return True, "", None, {}


def _culprit(prog: Program, base: dict, sheet: dict | None, build: Build, asm: Assembly, suffix: str, policy: str, centre: str | None,
             evidence: list[str], status: str, group: list[Driver], watch: list[Driver] | None, memo: dict | None = None,
             projected: list[str] | None = None) -> Driver | None:
    """The size of the group the rest can do without: with it left out the candidate holds. None when no single size is the cause. `memo`: the
    attempt's plans per driver (each depends on its own request only) — leaving each size out in turn otherwise built every other one's again."""
    for d in group:
        rest = [x for x in group if x is not d]
        plans, _why, _who, _x = _plans_for(prog, base, sheet, rest, asm.id, suffix, policy, centre, evidence, status, False, memo, projected)
        if plans is not None and _holds(prog, base, plans, build, rest, watch)[0]:
            return d
    return None


def _attempt(prog: Program, base: dict, sheet: dict | None, build: Build, asm: Assembly, suffix: str, policy: str, centre: str | None,
             evidence: list[str], status: str, tried: list[dict], watch: list[Driver] | None = None,
             projected: list[str] | None = None) -> tuple[list[dict], list[dict]] | None:
    """This anchor for the assembly: (its plans, the sizes left out of it), or None. A size that breaks it is left out — it keeps the set-out's
    direction, and is said — and the rest are tried again: one size must not undo the intent of all the others."""
    group = list(asm.drivers)
    dropped: list[dict] = []
    memo: dict = {}  # each driver's plan for this anchor, built once while the group shrinks
    while group:
        _in_time()  # each round builds the whole unit: a question a person waits on stops here when its time is up
        who: str | None = None
        why = ""
        for follow_all in (False, True):  # a part only hung on the assembly by the set-out stays; when that breaks a binding, it follows
            plans, why, who, extra = _plans_for(prog, base, sheet, group, asm.id, suffix, policy, centre, evidence, status, follow_all, memo, projected)
            if plans is None:
                tried.append({"policy": policy, "centre": centre, "why": why, "left_out": [d["name"] for d in dropped],
                              "names": extra.get("names", []), "blocked": extra.get("blocked", [])})
                break  # no plan can be made: following does not change that
            ok, why, who, extra = _holds(prog, base, plans, build, group, watch)
            if ok:
                return plans, dropped
            tried.append({"policy": policy, "centre": centre, "why": why + (" [parts hung on it follow]" if follow_all else " [parts hung on it stay]"),
                          "left_out": [d["name"] for d in dropped], "names": extra.get("names", []), "blocked": extra.get("blocked", [])})
        if len(group) == 1:
            return None
        if who and any(d.name == who for d in group):
            dropped.append({"name": who, "why": why})
            group = [d for d in group if d.name != who]
            continue
        # a size that is NOT being planned lost its binding (or now hangs on what the others move): one size of the group is the cause
        culprit = _culprit(prog, base, sheet, build, asm, suffix, policy, centre, evidence, status, group, watch, memo, projected)
        if culprit is None:
            return None
        dropped.append({"name": culprit.name, "why": f"it would take the binding of {who or 'another size'} away: {why}"})
        group = [d for d in group if d is not culprit]
    return None


_WHAT = {"level": "a site level", "held": "a held part", "existing": "existing work", "ai": "set by a formula somebody wrote", "slope": "a stated slope",
         "kept": "a part kept fixed", "formula": "a formula that is not a plain chain", "axis": "set out from the other axis", "follows": "it follows what moves"}


def wording(b: dict) -> str:
    """One blocking line in words: "y94 (a site level, FormationLevel)"."""
    name = b.get("level") or b.get("part")
    return f"{b['line']} ({_WHAT.get(b.get('kind'), 'fixed')}{', ' + name if name else ''})"


def _why_undecided(tried: list[dict], sides: tuple[str, str]) -> tuple[str, list[dict]]:
    """What stood in the way of every side, in words, and the distinct lines that did: for each way the structure could grow, the lines that would
    have to move and could not (from the first attempt, the one with every size in it); a failure that is not a line says what it measured."""
    first: dict[tuple, dict] = {}
    for t in tried:
        first.setdefault((t["policy"], t.get("centre")), t)
    order = {"start_fixed": 0, "end_fixed": 1, "centered": 2}
    parts: list[str] = []
    ways: list[str | None] = []  # per side reported: what failed, or None when it was lines that could not move
    blocked: list[dict] = []
    centred = False
    for (pol, centre), t in sorted(first.items(), key=lambda kv: (order.get(kv[0][0], 3), str(kv[0][1]))):
        lead = (f"for the {sides[0]} to stay" if pol == "start_fixed" else f"for the {sides[1]} to stay" if pol == "end_fixed"
                else f"to grow equally about {centre}")
        if pol == "centered":
            if centred:
                continue
            centred = True
        bl = t.get("blocked") or []
        if bl:
            lines = list(dict.fromkeys(wording(b) for b in bl))
            parts.append(f"{lead}, {', '.join(lines[:3])}{' …' if len(lines) > 3 else ''} would have to move")
            blocked += [b for b in bl if b not in blocked]
            ways.append(None)
        else:
            w = t["why"].split(" [")[0]
            parts.append(f"{lead}: {w if len(w) <= 150 else w[:147] + '…'}")
            ways.append(w)
    if len(ways) > 1 and None not in ways and len(set(ways)) == 1:  # every side fails the same way: it is about the structure, not about which side stays
        return f"whichever side stays the same thing breaks, so it is about the structure and not the side: {ways[0] if len(ways[0]) <= 150 else ways[0][:147] + '…'}", blocked
    return "; ".join(parts[:3]), blocked


def _settled_for(answer: dict, axis: str, names: set[str]) -> list[dict]:
    """The choices a person made that were about this assembly's sizes (`settled`, kept in the answer)."""
    return [s for s in answer.get("settled", []) if s.get("axis") == axis and set(s.get("drivers") or []) & names]


_GROWS = {"start_fixed": "keeps its start", "end_fixed": "keeps its end", "centered": "grows about its centre"}


def _decide(prog: Program, base: dict, sheet: dict | None, build: Build, axis: str, asm: Assembly, suffix: str,
            watch: list[Driver], prefer: dict[str, dict] | None = None) -> tuple[list[dict], AxisDecision]:
    """The anchor of one assembly on one axis: its plans, and the decision with its evidence. `prefer`: the side a size already has in a view drawn
    in projection with this one (projection.preferred) — tried before anything this view's own drawing says, after a person's choice here."""
    parts = prog.intent.get("parts") or {}
    names = [d.name for d in asm.drivers]
    sides = SIDES[axis]
    tried: list[dict] = []
    mine = list(dict.fromkeys(f"your choice: {s['title']}" for s in _settled_for(base, axis, set(names))))  # what a person settled for these sizes comes first

    def done(got: tuple[list[dict], list[dict]], policy: str, centre: str | None, status: str, ev: list[str]) -> tuple[list[dict], AxisDecision]:
        ev = mine + ev
        for p in got[0]:  # the plans say what the decision says: who, on what evidence (an attempt is made before it is known which one is kept)
            p["anchor"].update(evidence=list(ev), status=status)
        return got[0], AxisDecision(axis, asm.id, policy, centre, status, ev, [d.name for d in asm.drivers if d.name not in {x["name"] for x in got[1]}],
                                    got[1], tried)

    person = _person_choice(base, asm, axis, prog)
    if person:  # a person's choice governs the assembly: the sizes without a plan of their own adopt it
        pol, centre = person["policy"], person.get("centre")
        ev = [f"chosen by {person.get('source') or 'a person'} for {person.get('driver')}: {pol.replace('_', ' ')}{' about its own middle' if centre == MID else ' about ' + centre if centre else ''}"]
        mine_asm = Assembly(asm.id, asm.members, [d for d in asm.drivers if d.name != person.get("driver")])
        if pol != "as_set_out" and mine_asm.drivers:
            got = _attempt(prog, base, sheet, build, mine_asm, suffix, pol, centre, ev, "person", tried, watch)
            if got:
                return got[0], AxisDecision(axis, asm.id, pol, centre, "person", ev, names, got[1], tried)
        return [], AxisDecision(axis, asm.id, pol, centre, "person", ev, names, [], tried)

    # 0. drawn in projection with a view where a size of this assembly already grows one way: the two views show one structure, and grow alike
    pref = next(((d.name, (prefer or {})[d.name]) for d in asm.drivers if d.name in (prefer or {})), None)
    if pref is not None:
        who, p = pref
        ev = [f"drawn in projection with {p['view']}, where {'a person chose that ' if p.get('person') else ''}{who} {_GROWS[p['policy']]}"
              + (f" ({p['centre']} here)" if p.get("centre") and p["policy"] == "centered" else "") + ": the views grow alike"]
        # the faces the other view moves with this value are members here too (projection.preferred): both views move them alike
        got = _attempt(prog, base, sheet, build, asm, suffix, p["policy"], p.get("centre"), ev, "decided", tried, watch, p.get("members"))
        if got:
            return done(got, p["policy"], p.get("centre"), "decided", ev)
    for c, n, total in _centres(prog, asm):  # 1. symmetry
        of_all = f"{n} of the {total} faces" if n < total else f"the {n} faces"
        ev = [f"{of_all} of the structure mirror about {c} ({_centre_kind(prog, c)}): it stays about it, each side moves half"]
        got = _attempt(prog, base, sheet, build, asm, suffix, "centered", c, ev, "decided", tried, watch)
        if got:
            return done(got, "centered", c, "decided", ev)
    # 2./3. what must stay, existing work: which side may stay
    fixed = sorted(d for d in (set(protected_lines(prog)) & asm.members) if not is_axis(prog, d))
    results: dict[str, tuple[list[dict], list[dict]]] = {}
    for pol in ("start_fixed", "end_fixed"):
        got = _attempt(prog, base, sheet, build, asm, suffix, pol, None, [], "decided", tried, watch)
        if got:
            results[pol] = got
    stays = {"start_fixed": sides[0], "end_fixed": sides[1]}
    if len(results) == 1:
        pol = next(iter(results))
        ev = [f"only the {stays[pol]} side can stay: the other would have to move {', '.join(fixed[:4]) or 'what is fixed'}"]
        return done(results[pol], pol, None, "decided", ev)
    if results:
        side = _existing_side(prog, parts, axis, asm)
        if side in results:
            ev = [f"the size belongs to new work against existing work on its {stays[side]} side: the existing work stays, the new work grows away from it"]
            return done(results[side], side, None, "decided", ev)
        best = min(results, key=lambda p: (len(results[p][1]), p != "start_fixed"))  # the one that has to leave fewer sizes out; then the base
        who = f"{names[0]} and the others" if len(names) > 1 else names[0]
        ev = [f"nothing in the drawing says which side of {who} is the datum: the {stays[best]} side stays (assumed — a person can change it)"]
        return done(results[best], best, None, "provisional", ev)
    why, blocked = _why_undecided(tried, sides)
    return [], AxisDecision(axis, asm.id, "as_set_out", None, "undecided",
                            mine + ["no side could stay without breaking something" + (f" ({why})" if why else "") + ": the set-out decides, as drawn"],
                            names, [], tried, blocked)


def resolve(prog: Program, answer: dict, build: Build, sheet: dict | None = None, axes: tuple[str, ...] = ("x", "y"),
            seed: list[dict] | None = None, prefer: dict[str, dict] | None = None) -> Intent:
    """The design intent of every assembly of a unit. `prog` is the program of `answer` WITHOUT derived plans; `build(answer)` makes the program of
    any other answer (to try a candidate for real). Nothing is changed: the plans come back, the caller stores them.
    `axes`: only these are decided; `seed`: the derived plans of the others, already decided, which the ones decided here are tried beside;
    `prefer`: size → the side it has in a view drawn in projection with this one ({policy, centre, view, person}), tried first (_decide)."""
    base = strip(answer)
    for p in seed or []:
        base = _add(base, p)
    intent = Intent()
    parts = prog.intent.get("parts") or {}
    found = drivers(prog, base)
    for axis in axes:
        group = [d for d in found if d.axis == axis]
        if not group:
            continue
        asms = assemblies(prog, parts, axis, group, sheet)
        for asm in asms:
            suffix = f"@{asm.id}" if len(asms) > 1 else ""
            plans, decision = _decide(prog, base, sheet, build, axis, asm, suffix, found, prefer)
            intent.plans += plans
            intent.axes.append(decision)
            for p in plans:  # the next assembly is tried with this one's plans in place
                base = _add(base, p)
    return intent


def with_intent(answer: dict, intent: Intent) -> dict:
    """The answer with the engine's own plans replaced by these (a person's plans are never touched), and a record of what was decided — also of what
    could not be (`undecided`), which no plan says — that tells a later open the intent has been derived."""
    out = strip(answer)
    for p in intent.plans:
        out = _add(out, p)
    out["intent_axes"] = [a.as_dict() for a in intent.axes]  # what was tried too: the ways to settle an undecided axis are read from it (`stored`)
    return out


def sentence(ax: dict) -> str:
    """One decision of `Intent.as_dict()["axes"]` in words, for a person: which side stays, on what evidence."""
    low, high = SIDES.get(ax.get("axis"), ("lower", "upper"))
    policy = ax.get("policy")
    how = (f"grow equally on both sides about {ax.get('centre')}" if policy == "centered"
           else f"keep the {low} side and grow toward the {high}" if policy == "start_fixed"
           else f"keep the {high} side and grow toward the {low}" if policy == "end_fixed"
           else "keep the direction the set-out gave them")
    why = "; ".join(str(e) for e in ax.get("evidence") or [])
    return f"{', '.join(ax.get('drivers') or [])} {how}" + (f" — {why}" if why else "")


def explain(answer: dict, name: str) -> dict | None:
    """What an accepted plan says of how `name` grows: policy, the line it stays about, who decided, the evidence."""
    for p in answer.get("plans", []):
        if (p.get("driver") or {}).get("parameter") == name and p.get("status") == "accepted":
            a = p.get("anchor") or {}
            return {"policy": a.get("policy"), "centre": a.get("centre"), "source": a.get("source"), "status": a.get("status"),
                    "evidence": a.get("evidence") or [], "line": a.get("line"), "assembly": a.get("assembly"),
                    "settled": list(dict.fromkeys(s["title"] for s in answer.get("settled", []) if name in (s.get("drivers") or [])))}
    return None


# ── settling an axis that could not be decided ─────────────────────────────────────────────────────────────────────


@dataclass
class Edit:
    """One change to what was written that can unblock an axis, and that only a person decides: a pinned level left free (it follows the structure
    and stops being an input), a held part released (its sizes are inputs again), a size read instead of set (it stops being an input)."""

    kind: str  # level | part | reading
    target: str  # the level's, part's or size's name
    lines: list[str] = field(default_factory=list)  # the lines that stood in the way and this takes away

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.target}"


def choice_id(edits: list[Edit]) -> str:
    return "+".join(sorted(e.id for e in edits))


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def title_of(edits: list[Edit]) -> str:
    """What the choice does, as a person says it: "Let FormationLevel follow the structure"."""
    bits = []
    if lv := [e.target for e in edits if e.kind == "level"]:
        bits.append(f"let {_and(lv)} follow the structure")
    if pt := [e.target for e in edits if e.kind == "part"]:
        bits.append(f"stop keeping {_and(pt)} as drawn")
    if rd := [e.target for e in edits if e.kind == "reading"]:
        bits.append(f"work out {_and(rd)} from the lines instead of setting {'it' if len(rd) == 1 else 'them'}")
    text = " and ".join(bits)
    return text[:1].upper() + text[1:]


def names_of(d: AxisDecision) -> set[str]:
    """Every size a decision is about: those that grow with it and those left out of it."""
    return set(d.drivers) | {x["name"] for x in d.dropped}


def decisions_of(intent: Intent, axis: str, names: set[str]) -> list[AxisDecision]:
    return [a for a in intent.axes if a.axis == axis and names_of(a) & names]


def edits_for(answer: dict, decision: AxisDecision, limit: int = 8) -> tuple[list[list[Edit]], list[str]]:
    """The changes worth trying for an axis that ended undecided, in the order to try them, and what cannot be offered (said). A side can stay once every
    line that would have to move for it is free: a pinned level can be left free, a held part released — those come from what stood in the way
    (`decision.tried`, per way of growing). Where the attempts broke on sizes that cannot all be inputs, one of those sizes can be read instead of set.
    Every one is only a candidate: `apply_edits` writes it and the resolver decides whether it settles anything."""
    sides = SIDES[decision.axis]
    pinned = {r.get("name") for r in answer.get("levels", []) if r.get("role") in ("site_input", "check_only") and r.get("name")}
    held = {c.get("name") for c in answer.get("components", []) if c.get("parametrize") is False and c.get("name")}
    first: dict[tuple, dict] = {}
    for t in decision.tried:  # the first attempt of each way of growing has every size in it
        first.setdefault((t["policy"], t.get("centre")), t)
    sets: list[list[Edit]] = []
    notes: list[str] = []
    for (pol, centre), t in first.items():
        bl = t.get("blocked") or []
        if not bl:
            continue
        side = (f"the {sides[0]} cannot stay" if pol == "start_fixed" else f"the {sides[1]} cannot stay" if pol == "end_fixed"
                else f"it cannot grow equally about {centre}")
        edits: list[Edit] = []
        stuck: list[dict] = []
        for b in bl:
            e = (Edit("level", b["level"], [b["line"]]) if b.get("kind") == "level" and b.get("level") in pinned
                 else Edit("part", b["part"], [b["line"]]) if b.get("kind") == "held" and b.get("part") in held else None)
            if e is None:
                stuck.append(b)
            elif (same := next((x for x in edits if x.id == e.id), None)) is not None:
                same.lines.append(b["line"])
            else:
                edits.append(e)
        if stuck:
            notes.append(f"{side}: {', '.join(wording(b) for b in stuck[:2])} is not something to release here")
        elif edits:
            sets.append(edits)
            if len(edits) > 1:
                sets += [[e] for e in edits]
    broke: Counter[str] = Counter(n for t in decision.tried for n in t.get("names", []))
    rows = {p.get("name"): p for p in answer.get("parameters", []) if isinstance(p, dict)}
    readings = sorted((n for n in decision.drivers if n in rows and rows[n].get("recommended") is not False), key=lambda n: (-broke[n], n))
    sets += [[Edit("reading", n)] for n in readings[:4]]
    out: list[list[Edit]] = []
    for es in sets:
        if choice_id(es) not in {choice_id(o) for o in out}:
            out.append(es)
    return out[:limit], notes


def _subtree(components: list[dict], name: str) -> set[str]:
    out, todo = {name}, [name]
    while todo:
        cur = todo.pop()
        for c in components:
            if c.get("parent") == cur and c.get("name") not in out:
                out.add(c["name"])
                todo.append(c["name"])
    return out


def apply_edits(answer: dict, edits: list[Edit], axis: str, drivers: list[str]) -> dict:
    """The answer with these changes written as the person's own decision, and a record of each in `settled` (what it was, what it is, for which sizes)
    so it is shown, kept and can be taken back. The engine's own plans are not in it: they are derived again around the choice."""
    out = strip(answer)
    cid, title = choice_id(edits), title_of(edits)
    rows = [r for r in out.get("settled", []) if r.get("choice") != cid]
    for e in edits:
        row = {"choice": cid, "id": e.id, "kind": e.kind, "target": e.target, "axis": axis, "drivers": list(drivers), "title": title, "by": "person"}
        if e.kind == "level":
            lv = next(r for r in out.get("levels", []) if r.get("name") == e.target)
            rows.append({**row, "was": {"role": lv.get("role")}})
            lv["role"] = "derived"  # a line the structure's own sizes set out: free, and no longer an input
        elif e.kind == "part":
            comps = out.get("components", [])
            names = _subtree(comps, e.target)
            released = [c["name"] for c in comps if c.get("name") in names and c.get("parametrize") is False]
            for c in comps:
                if c.get("name") in released:
                    c["parametrize"] = True
            freed = []
            for q in out.get("parameters", []):
                if q.get("component") in names and q.get("recommended") is False:
                    q["recommended"] = True
                    freed.append(q["name"])
            rows.append({**row, "was": {"parts": released, "parameters": freed}})
        else:
            q = next(r for r in out.get("parameters", []) if r.get("name") == e.target)
            rows.append({**row, "was": {"recommended": q.get("recommended")}})
            q["recommended"] = False  # kept as drawn: a named quantity measured between its lines, not an input
    out["settled"] = rows
    return out


def take_back(answer: dict, cid: str) -> dict:
    """The answer as it was before this choice: every change it made written back."""
    out = strip(answer)
    rows = [r for r in out.get("settled", []) if r.get("choice") == cid]
    if not rows:
        raise ValueError(f"no choice {cid}")
    for r in rows:
        was = r.get("was") or {}
        if r["kind"] == "level":
            for lv in out.get("levels", []):
                if lv.get("name") == r["target"]:
                    lv["role"] = was.get("role")
        elif r["kind"] == "part":
            for c in out.get("components", []):
                if c.get("name") in (was.get("parts") or []):
                    c["parametrize"] = False
            for q in out.get("parameters", []):
                if q.get("name") in (was.get("parameters") or []):
                    q["recommended"] = False
        else:
            for q in out.get("parameters", []):
                if q.get("name") == r["target"]:
                    if was.get("recommended") is None:
                        q.pop("recommended", None)
                    else:
                        q["recommended"] = was["recommended"]
    out["settled"] = [r for r in out.get("settled", []) if r.get("choice") != cid]
    if not out["settled"]:
        del out["settled"]
    return out


def inputs_of(prog: Program) -> set[str]:
    """The values somebody named: what a person types, set by the agent or a person (not the engine's own measurements), and the levels."""
    return {n for n, p in prog.params.items() if p.source in ("ai", "person") or p.kind == "level"}


def _words(axis: str, ka: float, kb: float, name: str) -> str:
    low, high = ("left", "right") if axis == "x" else ("bottom", "top")
    if abs(ka - kb) < 1e-9:
        return f"{name} moves toward the {high if kb > 0 else low} ({abs(kb):g} mm per mm)"
    if abs(ka) < 1e-9:
        return f"{name} grows toward the {high if kb > 0 else low}"
    if abs(kb) < 1e-9:
        return f"{name} grows toward the {low if ka < 0 else high}"
    return f"{name} grows on both sides" if ka < 0 < kb else f"{name} grows ({low} side {ka:+g}, {high} side {kb:+g} mm per mm)"


def moves_of(prog: Program, axis: str, driver: str, limit: int = 4) -> list[str]:
    """What a mm of `driver` does to each part, on the program as it stands: the parts that grow and the parts that move, in words."""
    parts = prog.intent.get("parts") or {}
    an = prog.analysis
    v = line_values_mm(prog)
    r = rates(prog, driver)
    grows: list[str] = []
    moves: list[str] = []
    for n, p in parts.items():
        if any(q.parent == n for q in parts.values()):
            continue
        ls = [d for d in p.datums if d in v and an.datums[d].axis == axis]
        if len(ls) < 2:
            continue
        lo, hi = min(ls, key=lambda d: v[d]), max(ls, key=lambda d: v[d])
        ka, kb = r.get(lo, 0.0), r.get(hi, 0.0)
        if abs(ka) < 1e-9 and abs(kb) < 1e-9:
            continue
        (moves if abs(ka - kb) < 1e-9 else grows).append(_words(axis, ka, kb, n))
    out = grows + moves
    return out[:limit] + ([f"and {len(out) - limit} more"] if len(out) > limit else [])


def describe(before: Program, after: Program, edits: list[Edit], decision: AxisDecision, asked: str | None) -> dict:
    """What a verified choice would do, measured on the programs before and after it: which side stays, what moves with the size the person is looking
    at, which sizes are left out of the structure's growth, what stops being an input and what becomes one."""
    sides = SIDES[decision.axis]
    stays = (f"the {sides[0]} side stays" if decision.policy == "start_fixed" else f"the {sides[1]} side stays" if decision.policy == "end_fixed"
             else f"it grows equally on both sides about {decision.centre}")
    lost, gained = sorted(inputs_of(before) - set(after.params)), sorted(inputs_of(after) - inputs_of(before))
    driver = asked if asked in decision.drivers else (decision.drivers[0] if decision.drivers else None)
    return {"policy": decision.policy, "centre": decision.centre, "status": decision.status, "stays": stays, "evidence": decision.evidence,
            "driver": driver, "moves": moves_of(after, decision.axis, driver) if driver and driver in after.params else [],
            "left_out": [{"name": x["name"], "why": x["why"]} for x in decision.dropped],
            "stops_being_input": lost, "become_inputs": gained, "collateral": sorted(set(lost) - {e.target for e in edits})}


__all__ = ["AXIS_SOURCES", "SOURCE", "Assembly", "AxisDecision", "Driver", "Edit", "Intent", "apply_edits", "assemblies", "choice_id", "decisions_of", "derived", "describe",
           "drivers", "edits_for", "explain", "inputs_of", "names_of", "resolve", "sentence", "strip", "take_back", "title_of", "with_intent", "wording"]
