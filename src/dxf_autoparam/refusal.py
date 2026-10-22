"""Why the sheet refused a change: which check failed, on which entities and values, and what KIND of refusal it is.

SheetModel.regenerate tags every error with the check it comes from (`SheetRegen.failures`); `explain` adds the evidence and the kind, decided
from what the change measurably does to the lines it moves:

  invalid_edit      the change itself cannot be drawn: a size would be zero or negative; the gap a named value or a dimension of the drawing
                    owns would go through zero; lines that both follow the change close up an outline; two different parts run into each other
  incomplete_model  the change could be drawn, but the model does not carry it: a line set out through an intersection or a formula that moves
                    it many times the change (a gentle slope meeting a moved level); an entity with one end on a line that follows the change
                    and one on a line that stays, the gap between them owned by no value and no dimension; a part's own entities, or an entity
                    no part owns, running into a member; a view showing the same size that does not follow it; a value worked out there
  broken_promise    the change moves what an accepted plan says stays: the plan and the change disagree, and a person decides which holds
  rule              a production / engineering rule bound to the sheet fails at these values
  solver_failure    the program cannot be evaluated at these values (a formula outside its domain, a value it no longer has)

Every failure also says `existing`: the same check fails on the sheet as it stands, without this change. The change did not cause it; the
check, or the state the sheet is in, needs looking at (a rule that does not fit this drawing, a state saved before the check existed).

The kind is a diagnosis with its measured `basis`; it never changes what is refused — the sheet refuses every failure as before."""

from __future__ import annotations

import re

from .cadjson import entity_id
from .regen import _name

AMPLIFY = 3.0  # a line that moves more than this many times the change is set out through an intersection or a multiplying formula
KINDS = ("invalid_edit", "incomplete_model", "broken_promise", "rule", "solver_failure")
SAY = {"invalid_edit": "the edit cannot be drawn", "incomplete_model": "the model does not carry this change",
       "broken_promise": "an accepted plan says otherwise", "rule": "a rule bound to the sheet fails", "solver_failure": "the program cannot be evaluated"}


def explain(sm, r, changes: dict[str, float]) -> list[dict]:
    """Every failure of the regeneration `r` of `changes`, with its kind, basis, entities and values, and whether the sheet as it stands fails it
    too (module doc)."""
    out = classify(sm, r.failures, changes, r)
    mark_existing(sm, out)
    return out


def classify(sm, failures: list[dict], changes: dict[str, float], r=None) -> list[dict]:
    """The kind and basis of each tagged failure, measured on the sheet as it is now (a refused commit: with the refused answer still in place)."""
    ctx: dict[str, dict | None] = {}
    out = []
    for f in failures:
        g = dict(f)
        uid = g.get("unit")
        if uid not in ctx:
            ctx[uid] = _context(sm, uid, changes, r) if r is not None and uid in sm.units and sm.units[uid].built else None
        HOW.get(g["check"], _as_is)(g, ctx[uid])
        g.setdefault("kind", "invalid_edit")
        g["says"] = SAY[g["kind"]]
        out.append(g)
    return out


def compact(failures: list[dict], n: int = 5) -> list[dict]:
    """Failures for a model to read: the check, the kind and why, the entities by id — no sheet indices, no per-line numbers."""
    keep = ("check", "kind", "says", "unit", "message", "basis", "existing", "entities", "parts", "values")
    return [{k: (f[k][:400] if k == "basis" and isinstance(f.get(k), str) else f[k][:6] if isinstance(f.get(k), list) else f[k])
             for k in keep if f.get(k) not in (None, [], "")} for f in failures[:n]]


def summary(failures: list[dict]) -> str:
    """One line for a banner: how many checks failed, of which kind, and whether any already failed before the change."""
    if not failures:
        return ""
    kinds: dict[str, int] = {}
    for f in failures:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    old = sum(1 for f in failures if f.get("existing"))
    first = failures[0]
    return (f"{len(failures)} check(s) failed — " + ", ".join(f"{n} {SAY[k]}" for k, n in kinds.items())
            + (f"; {old} already failed before this change" if old else "") + f". First: {first['message']}"
            + (f" ({first['basis']})" if first.get("basis") else ""))[:600]


# ── context: what the change does to one unit's lines ────────────────────────────


def _context(sm, uid: str, changes: dict[str, float], r) -> dict:
    from .coverage import _entity_parts

    u = sm.unit(uid)
    prog = u.prog
    now = {**prog.defaults(), **sm._values_for(u, {})}
    new = {**now, **sm._values_for(u, changes)}
    steps = [abs(new[n] - now[n]) * (1000.0 if prog.params[n].kind == "level" else 1.0)
             for n in new if n in prog.params and abs(new[n] - now[n]) > 1e-12 and prog.params[n].kind in ("length", "level")]
    try:
        d0, d1 = prog.datum_values(now), prog.datum_values(new)
    except (KeyError, ValueError, ArithmeticError):
        d0 = d1 = {}
    return {"u": u, "prog": prog, "an": u.an, "um": u.sub.units_mm, "d0": d0, "d1": d1, "delta": max(steps, default=0.0),
            "eparts": _entity_parts(prog), "names": {_name(it): it for it in u.sub.items}, "pts": r.reg.pts}


def _ref(c: dict, it) -> str:
    """An entity as a person finds it: the unit's id for it, and its DXF handle (a block's entities: handle/k)."""
    return f"{entity_id(it)} ({it.src or it.handle})"


def _moves(c: dict, it) -> dict[str, float]:
    """The set-out lines of an entity's points and how far the change moves each (mm)."""
    out = {}
    for k in range(len(it.pts)):
        for ax in ("x", "y"):
            s = c["an"].slot_datum.get((it.index, k, ax))
            if s and s[0] in c["d1"] and s[0] in c["d0"]:
                out[s[0]] = round((c["d1"][s[0]] - c["d0"][s[0]]) * c["um"], 3)
    return out


def _amplified(c: dict, moves: dict[str, float]) -> str:
    """The line that moves the most for this change, when it moves more than AMPLIFY times the change itself — said with its formula."""
    if c["delta"] <= 0 or not moves:
        return ""
    d, v = max(moves.items(), key=lambda kv: abs(kv[1]))
    if abs(v) <= AMPLIFY * c["delta"]:
        return ""
    return (f"{d} moves {v:+.1f} mm for a change of {c['delta']:g} mm (×{abs(v) / c['delta']:.0f}): it is set out as {d} = "
            f"{c['prog'].formulas.get(d, '?')} — through an intersection or a formula that multiplies the change, not by the size that changed; "
            f"inspect_lines {d} shows its chain, set it out from the line it should follow")


def _owners(c: dict, a: str, b: str) -> list[str]:
    """What owns the gap between two lines: the values bound to exactly them (any of their occurrences), and the drawing's dimensions on it."""
    from .plan import pairs_of

    prog, an = c["prog"], c["an"]
    if "pairs" not in c:
        c["pairs"] = {n: [set(q) for q in pairs_of(prog, c["u"].answer, n)] or ([set(p.measures)] if p.measures else []) for n, p in prog.params.items()}
    named = [n for n, qs in c["pairs"].items() if {a, b} in qs]
    stated = [entity_id(an.drawing.items[k]) for g in an.gaps.values() if {g.a, g.b} == {a, b} for k in g.dims]
    return named + [f"dimension {d}" for d in stated]


def _parts(c: dict, i: int) -> list[str]:
    return sorted(c["eparts"].get(i, ()))


def _from_drawn(c: dict, line: str | None) -> float:
    """How far a line stands at these values from where it is drawn (mm)."""
    d = c["an"].datums.get(line) if line else None
    return (c["d1"][line] - d.value) * c["um"] if d is not None and line in c["d1"] else 0.0


def _gap_now(c: dict, a: str | None, b: str | None) -> float:
    """How far apart two lines are as the sheet stands (mm)."""
    if a in c["d0"] and b in c["d0"]:
        return abs(c["d0"][b] - c["d0"][a]) * c["um"]
    return float("nan")


def _outermost(c: dict, line: str) -> bool:
    """Whether a line is the unit's first or last set-out line on its axis as drawn: where the drawing itself ends (a cut ground line, the
    edge of the fill) — not a member's face."""
    an = c["an"]
    d = an.datums.get(line)
    if d is None:
        return False
    same = [e.value for e in an.datums.values() if e.axis == d.axis]
    return d.value in (min(same), max(same))


# ── one check each ───────────────────────────────────────────────────────────────


def _geometry(g: dict, c: dict | None) -> None:
    ent, _, what = (g.get("issue") or "").rpartition(": ")
    it = c["names"].get(ent) if c else None
    if it is None:
        g.update(kind="invalid_edit", basis="the outline is not drawable at these values")
        return
    g.update(entities=[_ref(c, it)], items=[c["u"].back[it.index]], parts=_parts(c, it.index))
    moves = _moves(c, it)
    g["lines"] = moves
    amp = _amplified(c, moves)
    if amp:
        g.update(kind="incomplete_model", basis=amp)
        return
    edge = _failing_edge(c, it)
    if edge is None:
        g.update(kind="invalid_edit", basis=f"{entity_id(it)}: {what} with every line following the change — the outline is not drawable there")
        return
    a, b, l0, l1 = edge
    owners = _owners(c, a, b) if a and b else []
    ma = moves.get(a, 0.0) if a else 0.0
    mb = moves.get(b, 0.0) if b else 0.0
    by_change = abs(ma) > 0.01 or abs(mb) > 0.01
    if not by_change:  # this change moves neither line (the entity already fails as the sheet stands): measure from where they are drawn
        ma, mb = _from_drawn(c, a), _from_drawn(c, b)
    if owners:
        g.update(kind="invalid_edit", basis=f"{entity_id(it)} spans {a}–{b}, the size of {', '.join(owners[:3])}: {l0:.1f} mm as drawn, {l1:.1f} mm "
                                            "at these values — through zero")
    elif (abs(ma) > 0.01) != (abs(mb) > 0.01):
        go, stay = (a, b) if abs(ma) > 0.01 else (b, a)
        where = f"of {', '.join(_parts(c, it.index))}" if _parts(c, it.index) else "of no part"
        apart = f"{abs(l0):.1f} mm apart as drawn" + (f", {_gap_now(c, a, b):.1f} mm as the sheet stands" if abs(_gap_now(c, a, b) - abs(l0)) > 0.05 else "")
        shift = ma if go == a else mb
        moved = f"{go}, which the change moves {shift:+.1f} mm" if by_change else f"{go}, {shift:+.1f} mm from where it is drawn"
        if _outermost(c, stay):
            g.update(kind="invalid_edit",
                     basis=f"{entity_id(it)} ({where}) runs from {moved}, to {stay} — the view's outermost line on that side as drawn ({apart}): the "
                           "change runs past where the drawing ends; it is larger than the drawn extent allows")
        else:
            g.update(kind="incomplete_model",
                     basis=f"{entity_id(it)} ({where}) ends on {moved}, and on {stay}, which stays — {apart}, and no value or dimension owns that gap: "
                           f"the entity does not follow the member it is drawn for. If it should, set {stay} out from {go} (set_formulas); if {stay} "
                           "must stay, the change is larger than the drawing allows there")
    else:
        how = "both its lines follow the change" if by_change else "both its lines stand away from where they are drawn"
        g.update(kind="invalid_edit", basis=f"{entity_id(it)}: {how} ({a} {ma:+.1f} mm, {b} {mb:+.1f} mm) and the edge between them goes from "
                                            f"{l0:.1f} mm to {l1:.1f} mm")


def _failing_edge(c: dict, it) -> tuple[str | None, str | None, float, float] | None:
    """The first edge of the entity that collapses or flips at these values: its two lines along the edge and its length as drawn / now (mm)."""
    new = c["pts"].get(c["u"].back[it.index])
    if not new:
        return None
    tol = c["an"].drawing.tol
    for i, j in it.segments:
        a0, b0, a1, b1 = it.pts[i], it.pts[j], new[i], new[j]
        ax = 0 if abs(b0[0] - a0[0]) >= abs(b0[1] - a0[1]) else 1
        s0, s1 = b0[ax] - a0[ax], b1[ax] - a1[ax]
        dot = (b0[0] - a0[0]) * (b1[0] - a1[0]) + (b0[1] - a0[1]) * (b1[1] - a1[1])
        if abs(s0) > tol and (dot < 0 or abs(s1) <= tol):
            key = "xy"[ax]
            la, lb = c["an"].slot_datum.get((it.index, i, key)), c["an"].slot_datum.get((it.index, j, key))
            return (la[0] if la else None, lb[0] if lb else None, abs(s0) * c["um"], (s1 if s0 > 0 else -s1) * c["um"])
    return None


def _clash(g: dict, c: dict | None) -> None:
    if c is None or not g.get("pair"):
        g.update(kind="invalid_edit", basis="two members run into each other at these values")
        return
    i, j = g["pair"]
    a, b = c["u"].sub.items[i], c["u"].sub.items[j]
    g.update(entities=[_ref(c, a), _ref(c, b)], items=[c["u"].back[i], c["u"].back[j]])
    ma, mb = _moves(c, a), _moves(c, b)
    g["lines"] = {**mb, **ma}
    amp = _amplified(c, {**ma, **mb})
    pa, pb = set(_parts(c, i)), set(_parts(c, j))
    g["parts"] = sorted(pa | pb)
    if amp:
        g.update(kind="incomplete_model", basis=amp)
    elif pa & pb:
        g.update(kind="incomplete_model", basis=f"{entity_id(a)} and {entity_id(b)} are both {', '.join(sorted(pa & pb))}: a part's own lines run into "
                                                "each other — they are not set out together")
    elif not pa or not pb:
        lone = entity_id(b) if not pb else entity_id(a)
        g.update(kind="incomplete_model", basis=f"{lone} belongs to no part: the engine cannot tell a member the change must not reach from a detail "
                                                "that should follow it — define_parts, then check again")
    else:
        g.update(kind="invalid_edit", basis=f"{', '.join(sorted(pa))} runs into {', '.join(sorted(pb))} at these values: different members collide")


def _positive(g: dict, c: dict | None) -> None:
    m = re.match(r"(\w+) must stay positive \(is ([^)]*)\)", g.get("issue") or "")
    if m:
        g["values"] = [m.group(1)]
    g.update(kind="invalid_edit", basis=f"{m.group(1)} would be {m.group(2)}: a size cannot be zero or negative" if m else "a size would not be positive")


def _plan(g: dict, c: dict | None) -> None:
    issue = g.get("issue") or ""
    m = re.match(r"plan (\S+): (\w+)", issue)
    g["plan"] = m.group(1) if m else None
    line = m.group(2) if m else None
    if c and line and line in c["d0"]:
        users = sorted({it.index for it in c["u"].sub.items for k in range(len(it.pts)) for ax in ("x", "y")
                        if (s := c["an"].slot_datum.get((it.index, k, ax))) and s[0] == line})
        g.update(entities=[_ref(c, c["u"].sub.items[k]) for k in users[:12]], items=[c["u"].back[k] for k in users[:200]])
    g.update(kind="broken_promise", basis=f"accepted plan {g['plan']} says it stays; the change moves it — change the plan, or the change"
                                          if g.get("plan") else "an accepted plan and the change disagree")


def _follow(g: dict, c: dict | None) -> None:
    g["values"] = [g.get("value")]
    g.update(kind="incomplete_model", basis=f"{g.get('unit')} shows {g.get('value')} but its set-out does not carry it: its lines measure "
                                            f"{g.get('measured_mm')} mm, not {g.get('wanted_mm'):g} — set its lines out from the shared value there")


def _worked_out(g: dict, c: dict | None) -> None:
    g["values"] = [g.get("value")]
    g.update(kind="incomplete_model", basis=f"{g.get('value')} is worked out in {g.get('unit')}, not an input there: that view cannot take a new value "
                                            "until it is bound as an input (or the value is changed where it is one)")


def _rule(g: dict, c: dict | None) -> None:
    g.update(kind="rule", basis="a production / engineering rule bound to the sheet does not hold at these values")


def _solver(g: dict, c: dict | None) -> None:
    g.update(kind="solver_failure", basis="the program cannot be evaluated at these values: a formula outside its domain, or a value it no longer has")


def _unbound(g: dict, c: dict | None) -> None:
    g["values"] = [g.get("value")]
    g.update(kind="incomplete_model", basis=f"the new answer does not keep the shared {g.get('value')} driving {g.get('unit')}'s own lines: the views "
                                            "that share it would no longer follow — bind it there again (its two lines), or unlink the views on purpose")


def _values(g: dict, c: dict | None) -> None:
    g.update(kind="broken_promise", basis="a person set these values and the new answer has no such value: a person's edit is never dropped silently — "
                                          "keep them, or confirm discarding them")


def _as_is(g: dict, c: dict | None) -> None:
    g.setdefault("kind", "invalid_edit")


HOW = {"GEOMETRY": _geometry, "CLASH": _clash, "POSITIVE": _positive, "PLAN": _plan, "FOLLOW": _follow, "WORKED_OUT": _worked_out, "RULE": _rule,
       "SOLVER": _solver, "UNBOUND": _unbound, "VALUES": _values}


# ── does the sheet as it stands fail it too? ─────────────────────────────────────


def _key(f: dict) -> tuple:
    """What makes two failures the same check on the same thing: the entity, pair, value or plan line it is about — never the numbers a message
    carries (how far a line moves), and never a message with its digits stripped (two entities' handles would read alike)."""
    check, unit, issue = f["check"], f.get("unit"), f.get("issue") or ""
    if check == "GEOMETRY":
        about = issue
    elif check == "CLASH":
        about = tuple(sorted(f.get("pair") or ()))
    elif check == "POSITIVE":
        about = issue.split(" must stay positive", 1)[0]
    elif check == "PLAN":
        m = re.match(r"plan (\S+): (\S+)", issue)
        about = m.groups() if m else issue
    elif check in ("FOLLOW", "WORKED_OUT", "UNBOUND"):
        about = f.get("value")
    elif check == "VALUES":
        about = tuple(f.get("values") or ())
    else:  # a rule's or the solver's own words: the numbers in them are the values tried
        about = re.sub(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?", "#", f.get("message", ""))
    return (check, unit, about)


def mark_existing(sm, failures: list[dict]) -> None:
    """Whether the sheet AS IT STANDS (a refused commit: after its state is restored) fails each check too: the change did not cause it."""
    units = {f["unit"] for f in failures if f.get("unit") in sm.units}
    if not units:
        for f in failures:
            f["existing"] = False
        return
    base = sm.regenerate({}, units=units)
    old = {_key(f) for f in base.failures}
    for f in failures:
        f["existing"] = _key(f) in old
        if f["existing"]:
            f["basis"] = ("it fails on the sheet as it stands too — this change did not cause it; the check, or the state the sheet is in, needs "
                          "looking at first. " + (f.get("basis") or ""))[:900]


__all__ = ["AMPLIFY", "KINDS", "SAY", "classify", "compact", "explain", "mark_existing", "summary"]
