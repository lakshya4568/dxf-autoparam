"""What the drawing was, and the way back to it — and which geometry a value belongs to.

The imported DXF is never edited: every entity of the sheet keeps its drawn points (`sm.dr`), and everything else — a
parameter's value, a plan, a view's name — is a decision laid on top of it. So the BASELINE is not a copy that could
drift: it is the file's own geometry, and a parameter's ORIGINAL value is what its two set-out lines measure on that
geometry (`u.an` is the analysis of the unmodified view). Nothing here reconstructs an original from regenerated
points.

    original_of(sm, uid, "ClearSpan")      # {"value": 3000, "basis": "measured between x4 and x9 on the imported drawing", …}
    reset_value(sm, "ClearSpan")           # back to it, regenerated and checked on the whole sheet — or refused, nothing changed
    reset_drawing(sm)                      # the imported state: values, plans, parametrization, sharing, view corrections
    highlight(sm, "ClearSpan")             # the geometry it controls / moves / leaves, per view, for the canvas
    deviation(sm)                          # how far the current drawing is from the imported one, per view

Reset is not undo. Undo reverses the last step; a reset goes back to the source whatever came between, and is itself one
undoable step (so a reset by mistake is one Ctrl-Z away; the redo stack, as for any new edit, is cleared).
"""

from __future__ import annotations

import copy
import math

from .graph import affects
from .program import ExprError, names_in


def _SheetError():  # the exception lives with the model; imported late so the model can import this module
    from .crossview import SheetError

    return SheetError


def targets(sm, name: str) -> list[tuple[str, str]]:
    """The (unit, local name) pairs a key stands for: a shared name is every unit it is bound in, unit.name is one."""
    shared = sm._shared_by_name().get(name)
    if shared is not None:
        return [(b.unit, b.param) for b in shared.bindings]
    if "." in name:
        uid, local = name.split(".", 1)
        if uid in sm.units:
            return [(uid, local)]
    raise _SheetError()(f"no value {name}: a shared name, or unit.name")


# ── the original value ──────────────────────────────────────────────────────────


def original_of(sm, uid: str, local: str) -> dict:
    """A value as the imported drawing has it, and how sure that is. The program's value reproduces the drawing as drawn
    (the validator refuses it otherwise), and for a value measured between two set-out lines it is checked here against the
    distance on the unmodified analysis — a value that does not match is reported as unreliable, never silently trusted."""
    u = sm.unit(uid)
    prm = u.prog.params.get(local)
    if prm is None:
        return {"value": None, "reliable": False, "basis": f"{local} is not a value of {uid}: it was worked out, or removed"}
    if prm.kind == "level":
        return {"value": prm.value, "unit": prm.unit, "reliable": True, "basis": "the level stated on the imported drawing"}
    if prm.measures:
        a, b = prm.measures
        dat = u.an.datums
        if a in dat and b in dat:
            drawn = abs(dat[b].value - dat[a].value) * u.sub.units_mm
            if abs(drawn - prm.value) <= max(0.5, 1e-4 * abs(prm.value)):
                return {"value": prm.value, "unit": prm.unit, "reliable": True, "basis": f"measured between {a} and {b} on the imported drawing"}
            return {"value": prm.value, "unit": prm.unit, "reliable": False,
                    "basis": f"the value is {prm.value:g} but the imported drawing measures {drawn:g} between {a} and {b}"}
    return {"value": prm.value, "unit": prm.unit, "reliable": prm.source in ("geometry", "dimension"),
            "basis": "the program's baseline value (it reproduces the drawing as drawn); no single pair of lines to measure it on"}


def current_of(sm, uid: str, local: str) -> float | None:
    u = sm.unit(uid)
    prm = u.prog.params.get(local)
    if prm is None:
        return None
    return sm.values.get(uid, {}).get(local, prm.value)


def overrides(sm, name: str) -> list[tuple[str, str]]:
    return [(uid, local) for uid, local in targets(sm, name) if local in sm.values.get(uid, {})]


# ── reset ───────────────────────────────────────────────────────────────────────


def reset_value(sm, name: str) -> dict:
    """One value back to the one the imported drawing has. Only this value: every other value a person set stays. The sheet
    is regenerated at the result and must hold (a shared size, a plan's promise, a view that follows) — otherwise nothing
    changes and the reason is said. One undoable step."""
    err = _SheetError()
    tg = targets(sm, name)
    over = [(uid, local) for uid, local in tg if local in sm.values.get(uid, {})]
    rows = []
    for uid, local in tg:
        o = original_of(sm, uid, local)
        rows.append({"unit": uid, "param": local, "original": o["value"], "reliable": o["reliable"], "basis": o["basis"],
                     "was": current_of(sm, uid, local)})
    if not over:
        return {"ok": True, "changed": False, "name": name, "bindings": rows, "reason": "it is already at its original value"}
    bad = [r for r in rows if r["original"] is None]
    if bad:
        raise err(f"{name}: no original value can be named for {', '.join(r['unit'] for r in bad)} ({bad[0]['basis']}): nothing was reset")
    saved = copy.deepcopy(sm.values)
    try:
        for uid, local in over:
            sm.values[uid].pop(local, None)
            if not sm.values[uid]:
                del sm.values[uid]
        trial = sm.regenerate(units={uid for uid, _l in over})
    finally:
        sm.values = saved
    if not trial.ok:
        raise err("refused, nothing changed: " + "; ".join(trial.errors[:3]))
    sm._push()
    for uid, local in over:
        sm.values[uid].pop(local, None)
        if not sm.values[uid]:
            del sm.values[uid]
    return {"ok": True, "changed": True, "name": name, "bindings": rows, "entities_moved": len(trial.changed), "by_view": trial.by_view}


def reset_drawing(sm) -> dict:
    """The imported state: values, accepted plans and every parametrization, shared sizes, links a person took or
    refused, relations and questions, and the corrections made to the views (names, types, merges, splits) — back to what
    the file alone gives. One undoable step; the undo history before it is kept (a full reset is never a point of no return),
    the redo stack is cleared (as for any new edit), and the saved project file is untouched until it is saved again."""
    st = sm.import_state
    had = {"values": sum(len(v) for v in sm.values.values()), "answers": sum(1 for u in sm.units.values() if u.answer),
           "shared": len(sm.shared), "plans": sum(len((u.answer or {}).get("plans", [])) for u in sm.units.values())}
    sm._push()
    sm.values, sm.shared, sm.unlinked = {}, {}, set(st["unlinked"])
    sm.accepted, sm.relations, sm.questions = set(), [], []
    sm.layout.groups = copy.deepcopy(st["groups"])
    sm._relayout()
    for u in sm.units.values():
        u.answer, u.prog, u.report, u.dropped = None, None, None, ""
    return {"ok": True, "reset": had, "views": [g.id for g in sm.layout.views()]}


# ── what a value controls ───────────────────────────────────────────────────────


def _formula_names(expr: str) -> set[str]:
    try:
        return names_in(expr)
    except ExprError:
        return set()


def _unit_entities(sm, u, items) -> set[int]:
    return {u.back[k] for k in items if 0 <= k < len(u.back)}


def highlight(sm, name: str, step: float | None = None) -> dict:
    """The geometry a value belongs to, in the categories the canvas draws, as SHEET entity indices:

      drives    entities set out from the lines the value's own formula names (the lines it spans)
      follows   entities that move with it through other lines — decided by measurement: change it by `step`, regenerate,
                see what moved (a line the formulas reach but nothing moves is not claimed)
      texts     dimensions and notes that state it or read lines it moves
      holds     parts a plan keeps fixed or outside the edit (what stays, and why it matters here), by part
      open      parts a plan could not settle: a question waits on them
      views     per view: the same sets cut to that view, and the box they occupy now — so the canvas can fit and a person
                can go to the other views a shared value moves"""
    from .assembly import part_entities
    from .plan import FIXED_MODES, _parts

    tg = targets(sm, name)
    cur = sm.current()
    drives: set[int] = set()
    reach_all: set[int] = set()
    texts: set[int] = set()
    holds: dict[str, set[int]] = {}
    open_: dict[str, set[int]] = {}
    for uid, local in tg:
        u = sm.unit(uid)
        prog = u.prog
        reach = affects(prog).get(local, {})
        direct_d = {d for d, e in prog.formulas.items() if local in _formula_names(e)}
        drives |= _unit_entities(sm, u, {i for (i, _k, _ax), (d, _o) in prog.analysis.slot_datum.items() if d in direct_d})
        reach_all |= _unit_entities(sm, u, reach.get("entities", []))
        texts |= _unit_entities(sm, u, reach.get("texts", []))
        parts = _parts(prog)
        for p in (u.answer or {}).get("plans", []):
            for d in p.get("directives", []):
                if d.get("kind") == "part" and d.get("target") in parts and d.get("status") == "accepted" and d.get("mode") in FIXED_MODES:
                    holds.setdefault(f"{d['target']} ({d['mode']})", set()).update(_unit_entities(sm, u, part_entities(prog, parts, d["target"])))
            for q in p.get("questions", []):
                about = str(q.get("about", ""))
                part = about.split(":", 1)[1] if about.startswith("attached:") else ""
                if part in parts:
                    open_.setdefault(part, set()).update(_unit_entities(sm, u, part_entities(prog, parts, part)))
    moves: set[int] = set()
    dv = None
    if name in cur:
        dv = step if step else max(abs(cur[name]) * 0.05, 10.0)
        moves = set(sm.regenerate({name: cur[name] + dv}).changed)
    follows = (moves | reach_all) - drives if moves else reach_all - drives
    text_types = ("TEXT", "MTEXT", "ATTRIB", "DIMENSION")
    for group_ in (drives, follows):
        for i in [i for i in group_ if sm.dr.items[i].dxftype in text_types]:
            group_.discard(i)
            texts.add(i)
    held = set().union(*holds.values()) if holds else set()
    group = sm.layout.item_group
    sr = sm.regenerate()
    views: dict[str, dict] = {}
    for label, ents in (("drives", drives), ("follows", follows), ("texts", texts), ("holds", held)):
        for i in ents:
            views.setdefault(group.get(i) or "", {"drives": [], "follows": [], "texts": [], "holds": []})[label].append(i)
    for v, row in views.items():
        for k in ("drives", "follows", "texts", "holds"):
            row[k].sort()
        pts = [p for i in {*row["drives"], *row["follows"], *row["texts"]} for p in sr.reg.pts.get(i, sm.dr.items[i].pts)]
        row["box"] = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)] if pts else None
        row["name"] = next((g.name for g in sm.layout.groups if g.id == v), "")
    return {"name": name, "units": sorted({uid for uid, _l in tg}), "shared": name in sm._shared_by_name(),
            "drives": sorted(drives), "follows": sorted(follows), "texts": sorted(texts),
            "holds": {k: sorted(v) for k, v in sorted(holds.items())}, "open": {k: sorted(v) for k, v in sorted(open_.items())},
            "views": views, "measured_moves": len(moves), "step": dv}


# ── how far the drawing is from the imported one ────────────────────────────────


def deviation(sm, entities: set[int] | None = None) -> dict:
    """The current drawing against the imported one: entities whose points or words differ, how far the furthest moved
    (mm), per view. `entities`: only these (a value's reach)."""
    sr = sm.regenerate()
    units = {s: u.sub.units_mm for u in sm.units.values() for s in u.items}
    by_view: dict[str, dict] = {}
    worst = 0.0
    n = 0
    for i in sr.changed:
        if entities is not None and i not in entities:
            continue
        it = sm.dr.items[i]
        pts = sr.reg.pts.get(i, it.pts)
        shift = max((math.dist(a, b) for a, b in zip(pts, it.pts, strict=False)), default=0.0) * units.get(i, sm.dr.units_mm)
        text_changed = i in sr.reg.texts and sr.reg.texts[i] != it.text
        v = sm.layout.item_group.get(i) or ""
        row = by_view.setdefault(v, {"entities": 0, "max_shift_mm": 0.0, "texts_changed": 0})
        row["entities"] += 1
        row["max_shift_mm"] = round(max(row["max_shift_mm"], shift), 3)
        row["texts_changed"] += int(text_changed)
        worst = max(worst, shift)
        n += 1
    return {"changed": n, "max_shift_mm": round(worst, 3), "by_view": by_view}


# ── the card a click on a value shows ───────────────────────────────────────────


def card(sm, name: str) -> dict:
    """Everything the page says about one value: where it stands now, what the imported drawing has, what it came from (the
    evidence), what it drives, whether it is VALIDATED (changed a little either way, the sheet regenerates, and something moves) —
    one measured claim, never a label."""
    from .status import parameters_of

    cur = sm.current()
    rows = []
    for uid, local in targets(sm, name):
        u = sm.unit(uid)
        prm = u.prog.params.get(local)
        if prm is None:
            rel = next((r for r in u.prog.relations if r.name == local or r.label == local), None)
            rows.append({"unit": uid, "param": local, "state": "worked_out", "why": f"worked out from other values: {rel.expr}" if rel else f"{local} is not a value of {uid}"})
            continue
        reach = affects(u.prog).get(local, {})
        state = next((p["state"] for p in parameters_of(sm, uid) if p["name"] == local), "named")
        rows.append({"unit": uid, "param": local, "label": prm.label, "kind": prm.kind, "unit_of_measure": prm.unit, "source": prm.source,
                     "confidence": round(prm.confidence, 2), "evidence": list(prm.evidence)[:6], "occurrences": prm.occurrences, "part": prm.component,
                     "measures": list(prm.measures) if prm.measures else None, "original": original_of(sm, uid, local),
                     "drives": {"lines": reach.get("datums", [])[:24], "parts": reach.get("parts", []), "relations": reach.get("relations", []),
                                "notes": len(reach.get("texts", [])), "entities": len(reach.get("entities", []))},
                     "set_out": {d: u.prog.formulas[d] for d in reach.get("datums", [])[:12] if d in u.prog.formulas}, "state": state})
    out = {"name": name, "value": cur.get(name), "bindings": rows, "changed": any(local in sm.values.get(uid, {}) for uid, local in targets(sm, name))}
    if name in cur and rows and all(r.get("state") != "worked_out" for r in rows):
        v = cur[name]
        dv = max(abs(v) * 0.05, 10.0)
        up, down = sm.regenerate({name: v + dv}), sm.regenerate({name: max(v - dv, 1e-6)})
        out["validated"] = bool(up.ok and down.ok and up.changed and down.changed)
        out["validation"] = {"+": {"ok": up.ok, "moves": len(up.changed), "why": up.errors[:2]}, "-": {"ok": down.ok, "moves": len(down.changed), "why": down.errors[:2]}, "step": dv}
        if out["validated"]:
            for r in rows:
                r["state"] = "validated"
    return out
