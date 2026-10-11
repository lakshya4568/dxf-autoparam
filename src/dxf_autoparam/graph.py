"""The parametric dependency graph, from the program itself (never from what the AI says about it).

    parameter ──► set-out line ──► set-out line … ──► entity points ──► part
        │                                   └──────► notes that state it
        └──► relation (reported quantity)

`dependency_graph(prog)` gives the nodes and edges; `affects(prog)` the per-parameter summary a person reads:
which lines, entities, parts, relations and notes move when it changes.
"""

from __future__ import annotations

from .program import Program, names_in


def _reach(prog: Program) -> dict[str, set[str]]:
    """datum → every parameter it depends on, through the formulas."""
    memo: dict[str, set[str]] = {}

    def of(d: str, stack: frozenset[str]) -> set[str]:
        if d in memo:
            return memo[d]
        out: set[str] = set()
        for n in names_in(prog.formulas.get(d, "")):
            if n in prog.params:
                out.add(n)
            elif n in prog.formulas and n not in stack:
                out |= of(n, stack | {n})
        memo[d] = out
        return out

    for d in prog.formulas:
        of(d, frozenset({d}))
    return memo


def _text_refs(prog: Program, ref: str, reach: dict[str, set[str]]) -> set[str]:
    if ref.startswith("datum:"):
        return reach.get(ref[6:], set())
    if ref.startswith("len:"):
        a, b = ref[4:].split(":")
        return reach.get(a, set()) | reach.get(b, set())
    if ref.startswith("rel:"):
        r = next((r for r in prog.relations if r.name == ref[4:]), None)
        return {n for n in names_in(r.expr) if n in prog.params} if r else set()
    ref = ref.removeprefix("m:")
    return {ref} if ref in prog.params else set()


def affects(prog: Program) -> dict[str, dict]:
    an = prog.analysis
    reach = _reach(prog)
    out = {p: {"datums": set(), "entities": set(), "parts": set(), "relations": [], "texts": []} for p in prog.params}
    for d, ps in reach.items():
        for p in ps:
            out[p]["datums"].add(d)
    for (item, _k, _ax), (d, _o) in an.slot_datum.items():
        for p in reach.get(d, ()):
            out[p]["entities"].add(item)
    for name, part in (prog.intent.get("parts") or {}).items():
        for p in set().union(*(reach.get(d, set()) for d in part.datums)) if part.datums else ():
            out[p]["parts"].add(name)
    for r in prog.relations:
        for n in names_in(r.expr):
            if n in out:
                out[n]["relations"].append(r.name if not r.name.startswith("R_") else r.label)
    for item, links in prog.text_links.items():
        for _tok, ref, _d in links:
            for p in _text_refs(prog, ref, reach):
                if item not in out[p]["texts"]:
                    out[p]["texts"].append(item)
    return {p: {"datums": sorted(v["datums"]), "entities": sorted(v["entities"]), "parts": sorted(v["parts"]),
                "relations": v["relations"], "texts": v["texts"]} for p, v in out.items()}


def dependency_graph(prog: Program) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    for p in prog.params.values():
        nodes.append({"id": f"P:{p.name}", "kind": "parameter", "label": p.label or p.name, "value": p.value, "unit": p.unit})
    for d, e in prog.formulas.items():
        deps = names_in(e)
        if not deps:
            continue
        nodes.append({"id": f"D:{d}", "kind": "set_out_line", "formula": e, "origin": prog.origin.get(d, "geometry")})
        for n in deps:
            if n in prog.params:
                edges.append({"from": f"P:{n}", "to": f"D:{d}"})
            elif n in prog.formulas:
                edges.append({"from": f"D:{n}", "to": f"D:{d}"})
    for name, part in (prog.intent.get("parts") or {}).items():
        nodes.append({"id": f"C:{name}", "kind": "part", "level": part.level, "parent": part.parent})
        for d in sorted(part.datums):
            if d in prog.formulas and names_in(prog.formulas[d]):
                edges.append({"from": f"D:{d}", "to": f"C:{name}"})
        if part.parent:
            edges.append({"from": f"C:{name}", "to": f"C:{part.parent}", "kind": "part_of"})
    for r in prog.relations:
        rid = f"R:{r.name}"
        nodes.append({"id": rid, "kind": "relation", "label": r.label, "expr": r.expr})
        for n in names_in(r.expr):
            if n in prog.params:
                edges.append({"from": f"P:{n}", "to": rid})
    return {"nodes": nodes, "edges": edges, "affects": affects(prog)}
