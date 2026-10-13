"""What the model STATES about how the sheet's views relate — a plan — and how the engine holds that statement to the sheet.

A person may ask for it ("for every component or dimension that appears in more than one view, list the views and say how they
relate"). The engine cannot read that; the model can, and says it with `state_plan`. What the engine does is check the statement
against the model as it stands, now and again at the end of the run:

  * every unit, view, part and value a link names must exist (the names are the model's own, kept as written — nothing here knows
    a structure, a family or a word of any vocabulary);
  * a link that says it is BOUND must be: by a shared value that drives each unit it names, by views drawn in projection (one unit),
    or by a relation between the views — otherwise it says it is only NOTED, and the person reads it as an assumption the model does
    not enforce;
  * what the model did and the plan leaves out is listed (a shared value, a relation between views, a name used in several units
    for the same value) — the engine counts, the model decides.

    out = apply_plan(sm, "R1", {"summary": "...", "links": [...], "assumptions": [...]})
    report = plan_report(sm)       # every stored link asked again of the sheet as it is now, and the gaps
"""

from __future__ import annotations

import copy
import difflib

from ..crossview import SheetModel

RELATIONS = ("same_component", "detail_of", "same_dimension", "same_dimension_other_scale", "derived_from", "other")
KINDS = ("component", "dimension", "level", "other")
BOUND = ("shared_value", "projection", "view_relation", "noted_only")
TOL = 5e-3  # two values are the same size when they differ by less than this fraction


def _s(x) -> str:
    """A model's field as text, whatever it sent."""
    return x.strip() if isinstance(x, str) else ("" if x is None else str(x).strip())


def _close(word: str, options, n: int = 4) -> list[str]:
    return difflib.get_close_matches(word, [o for o in options if o], n=n, cutoff=0.5)


def _names_of(u) -> dict[str, set[str]]:
    """What a unit holds that a plan may point at: its parts, and its values (named sizes, relations, levels)."""
    ans = u.answer or {}
    parts = {c.get("name") for c in ans.get("components", []) if c.get("name")}
    values = set(u.prog.params) | {r.name for r in u.prog.relations} | {lv.get("name") for lv in ans.get("levels", []) if lv.get("name")}
    return {"parts": parts, "values": values}


def resolve_place(sm: SheetModel, ref: dict) -> tuple[dict | None, str | None]:
    """One place a link says a thing appears — {unit, view, part, value} — as the engine keeps it, or why it cannot be."""
    from .agent import pascal

    if not isinstance(ref, dict):
        return None, "a place is an object {unit, view, part, value}"
    uid, vid = _s(ref.get("unit")) or None, _s(ref.get("view")) or None
    views = {g.id for g in sm.layout.views()}
    if vid is not None and vid not in views:
        return None, f"no view {vid} (views: {', '.join(sorted(views))})"
    if vid is not None:
        owner = sm.unit_of_view.get(vid)
        if uid is not None and owner is not None and owner != uid:
            return None, f"{vid} belongs to {owner}, not {uid}"
        uid = uid or owner
    if uid is None:
        return None, "name the unit or the view the thing appears in"
    if uid not in sm.units:
        return None, f"no unit {uid} (units: {', '.join(sm.units)})"
    u = sm.unit(uid)
    if not u.answer or not (u.answer.get("components") or u.answer.get("parameters")):
        return None, f"{uid} is not parametrized: there is nothing in it to point at yet"
    part, value = _s(ref.get("part")), _s(ref.get("value"))
    if not part and not value:
        return None, f"{uid}: name the part or the value of it that is the same (a link points at things the engine can find)"
    held = _names_of(u)
    if part and pascal(part) not in held["parts"]:
        near = _close(pascal(part), held["parts"])
        return None, f"{uid} has no part {part!r} (" + (f"did you mean {', '.join(near)}? " if near else "") + f"its parts: {', '.join(sorted(held['parts'])[:16])})"
    if value and value not in held["values"]:
        near = _close(value, held["values"])
        return None, f"{uid} has no value {value!r} (" + (f"did you mean {', '.join(near)}? " if near else "") + f"its values: {', '.join(sorted(held['values'])[:16])})"
    return {"unit": uid, "view": vid or (u.views[0] if len(u.views) == 1 else None), "part": pascal(part) if part else "", "value": value}, None


def _related_views(sm: SheetModel) -> list[tuple[str, str]]:
    """Views the sheet holds as related: the model's own relations (same structure, detail of) and views drawn in projection."""
    pairs = [(r["a"], r["b"]) for r in sm.relations if r.get("a") and r.get("b")]
    pairs += [(lk["a"], lk["b"]) for lk in sm.links if lk["strong"] and (lk["a"], lk["b"]) not in sm.unlinked]
    for u in sm.units.values():  # views the engine took as one unit are related by construction
        pairs += [(a, b) for i, a in enumerate(u.views) for b in u.views[i + 1:]]
    return pairs


def _connected(views: list[str], pairs: list[tuple[str, str]]) -> bool:
    views = list(dict.fromkeys(v for v in views if v))
    if len(views) < 2:
        return True
    adj: dict[str, set[str]] = {}
    for a, b in pairs:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    seen, todo = {views[0]}, [views[0]]
    while todo:
        for nxt in adj.get(todo.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return all(v in seen for v in views)


def check_link(sm: SheetModel, link: dict) -> list[str]:
    """Why a link does not hold on the sheet as it is (an empty list: it holds). Used when it is stated and again at the end."""
    problems: list[str] = []
    places = []
    for ref in link.get("appears_in") or []:
        p, why = resolve_place(sm, ref)
        if why:
            problems.append(why)
        else:
            places.append(p)
    if problems:
        return problems
    spots = {(p["unit"], p["view"] or "") for p in places}
    if len(spots) < 2:
        return ["a link is about something that appears in at least two views: name two places"]
    units = {p["unit"] for p in places}
    bound = link.get("bound_by")
    if bound not in BOUND:
        return [f"bound_by is one of {', '.join(BOUND)}"]
    if bound == "shared_value":
        name = (link.get("shared_value") or "").strip()
        sp = next((s for s in sm.shared.values() if s.name == name), None)
        if sp is None:
            shared = ", ".join(s.name for s in sm.shared.values()) or "none"
            return [f"no shared value {name!r} on the sheet (shared: {shared}): share it with share_sizes first, or say bound_by noted_only"]
        by_unit = {b.unit: b for b in sp.bindings}
        missing = sorted(units - set(by_unit))
        if missing:
            problems.append(f"{name} is shared by {', '.join(sorted(by_unit))}, not by {', '.join(missing)}")
        stopped = [u for u in sorted(units & set(by_unit)) if by_unit[u].status != "drives"]
        if stopped:
            problems.append(f"{name} does not drive {', '.join(stopped)} ({by_unit[stopped[0]].reason or by_unit[stopped[0]].status})")
        for p in places:
            if p["value"] and p["unit"] in by_unit and p["value"] != by_unit[p["unit"]].param:
                problems.append(f"in {p['unit']} the shared value is called {by_unit[p['unit']].param}, not {p['value']}: cite that name (or the part)")
    elif bound == "projection":
        if len(units) != 1:
            problems.append(f"views drawn in projection are one unit; these places are in {', '.join(sorted(units))}")
    elif bound == "view_relation":
        if not _connected([p["view"] or sm.unit(p["unit"]).views[0] for p in places], _related_views(sm)):
            problems.append("the views of these places are not related on the sheet (describe_views with a relation: same_structure, detail_of, projection), "
                            "or say bound_by noted_only")
    return problems


def _key(what: str) -> str:
    return " ".join((what or "").lower().split())


def apply_plan(sm: SheetModel, run_id: str, a: dict) -> dict:
    """Take the links that hold, keep them in the sheet's plan (one undoable step), and say what was refused and why. A call adds to the plan
    of THIS run, link by link (a link with the same `what` is replaced); a plan of an earlier run is not carried over."""
    cur = sm.stated_plan if sm.stated_plan.get("run") == run_id else {}
    plan = copy.deepcopy(cur) if cur else {"run": run_id, "summary": "", "links": [], "assumptions": []}
    applied, refused, refused_items, keys = [], [], [], []
    for raw in a.get("links") or []:
        if not isinstance(raw, dict):
            refused.append("a link is an object {what, relation, appears_in, bound_by}")
            refused_items.append({"key": "plan:?", "why": refused[-1]})
            continue
        what = _s(raw.get("what"))
        if not what:
            refused.append("a link needs `what`: your own name for the component or dimension")
            refused_items.append({"key": "plan:?", "why": refused[-1]})
            continue
        link = {"what": what, "kind": raw.get("kind") if raw.get("kind") in KINDS else "other",
                "relation": raw.get("relation") if raw.get("relation") in RELATIONS else "other",
                "bound_by": raw.get("bound_by"), "shared_value": _s(raw.get("shared_value")),
                "evidence": [str(e)[:300] for e in (raw.get("evidence") if isinstance(raw.get("evidence"), list) else [])[:4]], "note": _s(raw.get("note"))[:600],
                "appears_in": []}
        problems = []
        for ref in raw.get("appears_in") if isinstance(raw.get("appears_in"), list) else []:
            p, why = resolve_place(sm, ref)
            if why:
                problems.append(why)
            else:
                link["appears_in"].append(p)
        problems = problems or check_link(sm, link)
        key = f"plan:{_key(what)}"
        if problems:
            refused.append(f"{what}: " + "; ".join(problems))
            refused_items.append({"key": key, "why": refused[-1], "what": what, "shared_value": link["shared_value"], "bound_by": link["bound_by"]})
            continue
        plan["links"] = [x for x in plan["links"] if _key(x["what"]) != _key(what)] + [link]
        applied.append(f"{what}: {link['relation'].replace('_', ' ')} — " + ", ".join(f"{p['unit']}" + (f" {p['part']}" if p["part"] else "") + (f" {p['value']}" if p["value"] else "")
                                                                                       for p in link["appears_in"]) + f" ({link['bound_by'].replace('_', ' ')})")
        keys.append(key)
    for s in a.get("assumptions") if isinstance(a.get("assumptions"), list) else []:
        text = _s(s.get("text") if isinstance(s, dict) else s)
        if text and all(_key(x["text"]) != _key(text) for x in plan["assumptions"]):
            plan["assumptions"].append({"text": text[:600], "about": _s(s.get("about") if isinstance(s, dict) else "")[:200],
                                        "why": _s(s.get("why") if isinstance(s, dict) else "")[:400]})
            applied.append("assumption: " + text[:100])
    if _s(a.get("summary")):
        plan["summary"] = _s(a["summary"])[:3000]
        applied.append("summary")
    if applied:
        sm.set_plan(plan)
        sm.stated_plan["revision"] = sm.revision
    gaps = plan_gaps(sm, sm.stated_plan if sm.stated_plan.get("run") == run_id else plan)
    return {"applied": applied, "refused": refused, "refused_items": refused_items, "applied_keys": keys, "gaps": gaps,
            "links": len((sm.stated_plan if applied else plan).get("links", []))}


def plan_gaps(sm: SheetModel, plan: dict) -> dict:
    """What the model did across views that its plan does not mention. The engine only counts: a shared value, a relation between views,
    and a name the model used in several units for the same value or the same part."""
    links = plan.get("links", [])
    named_shared = {x.get("shared_value") for x in links if x.get("shared_value")}
    in_plan_units = [{p["unit"] for p in x.get("appears_in", [])} for x in links]
    unit_of = sm.unit_of_view
    unmentioned_shared = [s.name for s in sm.shared.values() if s.name not in named_shared]
    unmentioned_relations = []
    for r in sm.relations:
        ua, ub = unit_of.get(r.get("a")), unit_of.get(r.get("b"))
        if ua and ub and ua != ub and not any({ua, ub} <= s for s in in_plan_units):
            unmentioned_relations.append({"a": r["a"], "b": r["b"], "relation": r.get("relation")})
    bound = {(b.unit, b.param) for s in sm.shared.values() for b in s.bindings}
    said_values = {(p["unit"], p["value"]) for x in links for p in x.get("appears_in", []) if p.get("value")}
    said_parts = {(p["unit"], p["part"]) for x in links for p in x.get("appears_in", []) if p.get("part")}
    values: dict[str, list[tuple[str, float]]] = {}
    parts: dict[str, list[str]] = {}
    for uid, u in sm.units.items():
        if not u.built or not u.answer:
            continue
        for n, prm in u.prog.params.items():
            if prm.source == "ai":
                values.setdefault(n, []).append((uid, prm.value))
        for c in u.answer.get("components", []):
            if c.get("name"):
                parts.setdefault(c["name"], []).append(uid)
    alike_values = []
    for n, rows in values.items():
        free = [(uid, v) for uid, v in rows if (uid, n) not in bound and (uid, n) not in said_values]
        if len({uid for uid, _ in free}) >= 2 and all(abs(v - free[0][1]) <= TOL * max(1.0, abs(free[0][1])) for _u, v in free):
            alike_values.append({"name": n, "units": [uid for uid, _ in free], "value_mm": round(free[0][1], 1)})
    alike_parts = []
    for n, uids in parts.items():
        free = [uid for uid in dict.fromkeys(uids) if (uid, n) not in said_parts]
        if len(free) >= 2:
            alike_parts.append({"name": n, "units": free})
    return {"unmentioned_shared": unmentioned_shared, "unmentioned_relations": unmentioned_relations,
            "same_value_name_in_several_units": alike_values, "same_part_name_in_several_units": alike_parts}


def gap_lines(gaps: dict) -> list[str]:
    """The gaps as sentences, for the model (a hint) and for the person (a note): one line for each kind, the names joined."""
    out = []
    if gaps.get("unmentioned_shared"):
        out.append("shared values the plan does not mention: " + ", ".join(gaps["unmentioned_shared"]))
    rels = gaps.get("unmentioned_relations", [])
    if rels:
        out.append("views related on the sheet whose plan lists no component or dimension that appears in both: " +
                   ", ".join(f"{r['a']}–{r['b']} ({str(r.get('relation')).replace('_', ' ')})" for r in rels[:8]))
    vals = gaps.get("same_value_name_in_several_units", [])
    if vals:
        out.append("named alike with the same value in several units, neither shared nor in the plan: " +
                   ", ".join(f"{v['name']} ({', '.join(v['units'])}: {v['value_mm']:g} mm)" for v in vals[:8]))
    parts = gaps.get("same_part_name_in_several_units", [])
    if parts:
        out.append("parts named alike in several units, and the plan does not say how they relate: " +
                   ", ".join(f"{p['name']} ({', '.join(p['units'])})" for p in parts[:10]))
    return out


def plan_report(sm: SheetModel, run_id: str | None = None) -> dict:
    """The stored plan with every link asked again of the sheet as it is now — what the person reads."""
    plan = copy.deepcopy(sm.stated_plan or {})
    if run_id is not None and plan.get("run") != run_id:
        plan = {}
    rows = []
    for link in plan.get("links", []):
        why = check_link(sm, link)
        rows.append({**link, "holds": not why, "why": "; ".join(why)})
    return {"stated": bool(plan.get("links") or plan.get("summary") or plan.get("assumptions")), "run": plan.get("run"), "summary": plan.get("summary", ""),
            "links": rows, "assumptions": plan.get("assumptions", []), "gaps": plan_gaps(sm, plan)}


def group_facts(sm: SheetModel, include_labels: bool = False) -> list[dict]:
    """The sheet's groups that are not views, as the engine counted them (drawn items, dimensions, texts) — with a doubt where the counts are
    those of a drawn view and not of what the group was taken for. The engine only counts and says so: the model looks and decides."""
    out = []
    for g in sm.layout.groups:
        if g.kind == "view":
            continue
        c = g.counts or {}
        geom, texts, dims, curved = c.get("geometry", 0), c.get("texts", 0), c.get("dimensions", 0), c.get("curves", 0)
        doubt = None
        if geom >= 20 and (dims >= 3 or geom > 2 * max(texts, 1)):
            doubt = (f"{g.id} is taken for a {g.kind} but holds {geom} drawn items ({curved} curved), {dims} dimensions and {texts} texts — "
                     f"the content of a drawn view, not of a {g.kind}: look at it (zoom_view), and say what it is (describe_views kind)")
        if g.kind == "label" and not doubt and not include_labels:
            continue
        out.append({"id": g.id, "kind": g.kind, "name": g.name, "entities": len(g.items), "drawn": geom, "curved": curved, "dimensions": dims,
                    "texts": texts, **({"doubt": doubt} if doubt else {})})
    return out
