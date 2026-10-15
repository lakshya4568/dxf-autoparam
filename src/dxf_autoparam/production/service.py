"""The production knowledge as the sheet and the agent use it: one place that ties the manifests, the bridge and the bindings together.

    status()                                  what is available here: knowledge, its freshness, whether the rules can run
    accept(binding, state)                    check a binding on the drawing as it stands, choose its guards → (binding, report)
    report(binding, state)                    evaluate it (as drawn, or on regenerated units)
    guard_errors(binding, state)              what stops a change: a guarded relation that no longer holds, or can no longer be verified

`state` is a binding.SheetState: every unit the binding reads, as drawn or regenerated.

A guard is something that HELD on the drawing when the binding was accepted, on fresh knowledge, by the production code: an output the drawing
and the engine agreed on, or the engine's validation where the drawing's own values decide it. A change that breaks the agreement is refused
(the drawing as it was is kept). An output that differed is a conflict to resolve — never a guard, never "fixed" by moving a line.
"""

from __future__ import annotations

from . import manifest as M
from .binding import Binding, BindingError, SheetState, evaluate, message_key
from .binding import guard_errors as _guard_errors
from .bridge import default_bridge


class ProductionRefusal(ValueError):
    """A binding that cannot be accepted (unknown family, malformed, refers to what the units do not have, or knowledge that is stale)."""


def status() -> dict:
    pk = M.knowledge()
    if not pk.available():
        return {"knowledge": False, "why": f"no production knowledge in {pk.dir}"}
    br = default_bridge().status()
    return {"knowledge": True, "families": len(pk.family_keys()), "source": pk.index.get("source"), "bridge": br}


def _family(key: str) -> M.FamilyKnowledge:
    try:
        return M.knowledge().family(key)
    except M.KnowledgeError as exc:
        raise ProductionRefusal(str(exc)) from exc


def parse(binding: dict | Binding) -> Binding:
    try:
        return binding if isinstance(binding, Binding) else Binding.from_json(binding)
    except BindingError as exc:
        raise ProductionRefusal(str(exc)) from exc


def report(binding: dict | Binding, state: SheetState, only: list[str] | None = None) -> dict:
    b = parse(binding)
    fam = _family(b.family)
    return evaluate(fam, b, state, default_bridge(), only=only, freshness=M.knowledge().freshness(b.family))


def accept(binding: dict, state: SheetState, guard: bool = True) -> tuple[dict, dict]:
    """The binding as it will be kept (id, guards, the knowledge it was accepted against) and the evaluation that decided it."""
    b = parse({k: v for k, v in binding.items() if k not in ("guards", "validation_baseline", "guard_validation")})
    fam = _family(b.family)
    fresh = M.knowledge().freshness(b.family)
    rep = evaluate(fam, b, state, default_bridge(), freshness=fresh)
    if rep["status"] in ("refused", "stale"):
        raise ProductionRefusal("; ".join(rep.get("problems") or [rep.get("why", "")])[:600])
    b.id = b.id or f"{b.family}@{b.unit}"
    b.knowledge_digest = fam.data["source"]["sources_digest"]
    holds = [n for n, r in (rep.get("outputs") or {}).items() if r["result"] == "holds"]
    val = rep.get("validation") or {}
    can = guard and rep["status"] not in ("unavailable", "error") and fresh.get("state") == "fresh"
    b.guards = holds if can else []
    b.guard_validation = bool(can and val.get("ran"))
    b.validation_baseline = sorted({message_key(m["msg"]) for m in val.get("messages", []) if m["sev"] == "err" and m["decided_by_drawing"]})
    if not guard:
        rep["guards_note"] = "kept as a record: no guards (asked)"
    elif rep["status"] in ("unavailable", "error"):
        rep["guards_note"] = f"no guards: nothing was evaluated ({rep.get('why')})"
    elif fresh.get("state") != "fresh":
        rep["guards_note"] = f"no guards: the knowledge is {fresh.get('state')} — relations are reported, not enforced, until it is re-extracted"
    else:
        parts = []
        if holds:
            parts.append(f"{len(holds)} relation(s) held on the drawing and are now guarded")
        if b.guard_validation:
            parts.append("the engine's validation is guarded (a new error the drawing's values decide refuses a change"
                         + (f"; {len(b.validation_baseline)} error(s) the drawing already has are known, not new" if b.validation_baseline else "") + ")")
        rep["guards_note"] = ("; ".join(parts) + ": a change that breaks one is refused") if parts else "nothing held, so nothing is guarded"
    conflicts = [n for n, r in (rep.get("outputs") or {}).items() if r["result"] == "differs"]
    if conflicts:
        rep["conflicts"] = conflicts
        rep["conflicts_note"] = ("these outputs differ between the production engine and the drawing: the drawing wins, nothing is moved — check the "
                                 "binding (the right lines? the right level datum? this drawing's own convention?) or record the conflict")
    rep["binding"] = b.id
    rep["guards"] = b.guards
    rep["guard_validation"] = b.guard_validation
    return b.to_json(), rep


def guard_errors(binding: dict, state: SheetState) -> list[str]:
    try:
        b = Binding.from_json(binding)
    except BindingError as exc:
        return [f"production rule binding {binding.get('id', '?')}: {exc}"]
    try:
        fam = M.knowledge().family(b.family)
    except M.KnowledgeError as exc:
        return [f"production rule binding {b.id}: the knowledge it was accepted against is gone ({exc})"]
    if b.knowledge_digest and b.knowledge_digest != fam.data["source"]["sources_digest"]:
        return [f"production rule binding {b.id}: accepted against other knowledge (re-extracted since): rebind before changing the drawing"]
    return _guard_errors(fam, b, state, default_bridge(), freshness=M.knowledge().freshness(b.family))
