"""What a run says about itself: a stage for every tool, a plain sentence for every result.

These words are written by the engine from what actually happened (the call, its arguments and what the engine
answered) — never invented to look busy, and never the model's private reasoning. The model's own short "why" for a call,
if it gave one, is shown beside them as what it said it was doing.
"""

from __future__ import annotations

import json

STAGE_OF = {
    "inspect_sheet": "inspecting", "open_unit": "inspecting", "inspect_regions": "inspecting", "inspect_lines": "inspecting",
    "inspect_candidates": "inspecting", "inspect_dimensions": "inspecting", "resolve_labels": "inspecting", "find_values": "inspecting",
    "knowledge": "inspecting", "what_moves": "measuring", "inspect_assembly": "measuring", "zoom_view": "looking",
    "account_instruction": "interpreting", "describe_views": "understanding the views", "share_sizes": "linking the views", "state_plan": "stating the plan",
    "set_structure": "naming the parts", "define_parts": "naming the parts", "define_parameters": "binding values",
    "set_levels": "binding values", "set_formulas": "binding values", "set_relation": "binding values", "remove": "binding values",
    "add_constraints": "stating intent", "state_behaviours": "stating intent", "propose_plan": "planning",
    "ask_person": "asking", "finish": "validating",
    "drawing_overview": "inspecting", "inspect_view": "looking", "inspect_component": "looking", "inspect_annotations": "inspecting",
    "inspect_layers": "inspecting", "find_duplicates": "inspecting", "impact_plan": "measuring", "check_behaviour": "validating",
    "review_parameters": "inspecting", "update_checklist": "planning", "record_learned": "planning", "accept_semantics": "understanding the views",
    "rename_values": "binding values", "define_transforms": "binding values",
    "list_skills": "consulting the library", "load_skill": "consulting the library", "search_library": "consulting the library", "record_finding": "consulting the library",
}
STAGES = ("inspecting", "looking", "interpreting", "understanding the views", "naming the parts", "binding values", "stating intent", "planning",
          "measuring", "linking the views", "stating the plan", "asking", "validating", "committing", "consulting the library")
# What a person sees a stage as — planning, inspecting, applying changes (the engine WRITES to the sheet's model), validating, asking.
PHASE_OF = {"interpreting": "planning", "planning": "planning", "stating the plan": "planning",
            "inspecting": "inspecting", "looking": "inspecting", "measuring": "inspecting", "consulting the library": "inspecting",
            "understanding the views": "applying", "naming the parts": "applying", "binding values": "applying", "stating intent": "applying",
            "linking the views": "applying", "committing": "applying", "validating": "validating", "asking": "asking"}

WORDS = {
    "inspect_sheet": "looked at the sheet", "open_unit": "opened a view", "inspect_regions": "inspected regions", "inspect_lines": "inspected lines",
    "inspect_candidates": "inspected candidate sizes", "inspect_dimensions": "inspected dimensions", "resolve_labels": "resolved labels",
    "find_values": "searched for sizes", "knowledge": "consulted the knowledge pack", "what_moves": "measured what a value moves",
    "inspect_assembly": "inspected the assembly", "zoom_view": "zoomed into the drawing", "account_instruction": "read the instruction",
    "describe_views": "described the views", "share_sizes": "linked sizes across views", "state_plan": "stated the plan", "set_structure": "named the structure",
    "define_parts": "named parts", "define_parameters": "bound values", "set_levels": "named levels", "set_formulas": "wrote formulas",
    "set_relation": "related values", "remove": "removed items", "add_constraints": "stated constraints", "state_behaviours": "stated behaviour",
    "propose_plan": "proposed a plan", "ask_person": "asked you", "finish": "finished",
    "drawing_overview": "read the whole drawing", "inspect_view": "inspected a view", "inspect_component": "inspected a component", "inspect_annotations": "read the annotations",
    "inspect_layers": "read the layers", "find_duplicates": "looked for duplicates", "impact_plan": "planned the impact of a change", "check_behaviour": "checked the assembly",
    "review_parameters": "reviewed the value names", "update_checklist": "updated the checklist", "record_learned": "recorded what it learned",
    "accept_semantics": "recorded a decision", "rename_values": "renamed values", "define_transforms": "defined transforms",
    "list_skills": "listed library skills", "load_skill": "read a library skill", "search_library": "searched the library", "record_finding": "recorded library findings",
}

# What each tool is doing while it runs, in the present tense (WORDS above is the past tense, for a finished call).
DOING = {
    "inspect_sheet": "Reading the sheet's views and units", "open_unit": "Opening a view's unit", "inspect_regions": "Inspecting regions",
    "inspect_lines": "Inspecting set-out lines", "inspect_candidates": "Inspecting candidate sizes", "inspect_dimensions": "Reading the dimensions",
    "resolve_labels": "Resolving labels to geometry", "find_values": "Searching for sizes", "knowledge": "Consulting the knowledge pack",
    "what_moves": "Measuring what a value moves", "inspect_assembly": "Inspecting the assembly", "zoom_view": "Looking at a picture of the drawing",
    "account_instruction": "Reading the instruction clause by clause", "describe_views": "Identifying and naming the views", "share_sizes": "Linking sizes across views",
    "state_plan": "Stating the plan across views", "set_structure": "Naming the structure", "define_parts": "Naming the parts", "define_parameters": "Binding values to dimensions",
    "set_levels": "Naming levels", "set_formulas": "Writing formulas", "set_relation": "Relating values", "remove": "Removing items", "add_constraints": "Stating constraints",
    "state_behaviours": "Stating how the assembly should behave", "propose_plan": "Proposing and measuring the plan", "ask_person": "Asking you", "finish": "Checking the criteria to finish",
    "drawing_overview": "Reading the whole drawing at a glance", "inspect_view": "Inspecting a view", "inspect_component": "Inspecting a component",
    "inspect_annotations": "Reading the annotations", "inspect_layers": "Reading layers and existing/proposed status", "find_duplicates": "Looking for duplicate geometry",
    "impact_plan": "Planning what a change would touch", "check_behaviour": "Checking the whole assembly under a change", "review_parameters": "Reviewing the value names",
    "update_checklist": "Updating its checklist", "record_learned": "Recording what it learned", "accept_semantics": "Recording an existing/proposed decision",
    "rename_values": "Renaming values", "define_transforms": "Defining rotations, translations and scales",
    "list_skills": "Listing matching library skills", "load_skill": "Reading a library skill", "search_library": "Searching the library", "record_finding": "Recording what the library gave",
}


def stage_of(name: str) -> str | None:
    return STAGE_OF.get(name)


def phase_of(stage: str | None) -> str | None:
    return PHASE_OF.get(stage or "")


def doing(name: str) -> str:
    return DOING.get(name) or WORDS.get(name, name).capitalize()


def _n(x) -> int:
    return len(x) if hasattr(x, "__len__") else 0


def _ids(v, k: int = 4) -> str:
    v = list(v or [])
    return ", ".join(str(x) for x in v[:k]) + (f" +{len(v) - k}" if len(v) > k else "")


def _verdicts(res) -> list[dict]:
    if isinstance(res, dict) and isinstance(res.get("result"), list):
        return [v for v in res["result"] if isinstance(v, dict)]
    if isinstance(res, list):
        return [v for v in res if isinstance(v, dict)]
    if isinstance(res, dict) and "ok" in res:
        return [res]
    return []


def summarise(name: str, a: dict, res) -> str:
    """One plain sentence for the timeline, from the call and what came back."""
    a = a or {}
    try:
        if isinstance(res, dict) and res.get("refused"):
            return f"refused: {str(res['refused'])[:160]}"
        if isinstance(res, dict) and res.get("error"):
            return f"error: {str(res['error'])[:160]}"
        if name == "zoom_view" and isinstance(res, dict) and res.get("group"):
            return f"picture {res.get('image', '?')} of {res['group'].get('id')} ({res['group'].get('kind')}), revision {res.get('revision', '?')}"
        if name == "zoom_view":
            r = res if isinstance(res, dict) else {}
            return (f"picture {r.get('image', '?')} of {r.get('view') or r.get('unit') or 'the sheet'}"
                    f"{' around ' + _ids(a.get('around')) if a.get('around') else ''} — {r.get('entities_labelled_count', 0)} entities tagged, "
                    f"revision {r.get('revision', '?')}")
        if name in ("inspect_regions", "inspect_lines", "inspect_candidates") and isinstance(res, dict):
            return f"{_n(a.get('ids'))} item(s): {_ids(a.get('ids'))}"
        if name == "inspect_dimensions":
            return f"{_n(res)} dimension row(s)"
        if name == "find_values":
            return f"{_n(res)} candidate(s) near {a.get('value_mm', a.get('region', 'the request'))}"
        if name == "inspect_sheet" and isinstance(res, dict):
            other = res.get("other_groups") or []
            doubted = sum(1 for g in other if g.get("doubt"))
            return (f"{_n(res.get('views'))} views, {_n(other)} other groups" + (f" ({doubted} doubted)" if doubted else "") +
                    f", {_n(res.get('units'))} units, revision {res.get('revision')}")
        if name == "open_unit" and isinstance(res, dict):
            c = res.get("committed_previous")
            return f"{res.get('unit')} ({', '.join(res.get('views', []))}){'; previous unit ' + ('applied' if c and c.get('ok') else 'kept pending' + (': ' + str(c.get('why'))[:80] if c else '')) if c is not None else ''}"
        if name == "what_moves" and isinstance(res, dict):
            moves = res.get("moves", {})
            return f"{a.get('parameter')}: {sum(1 for v in moves.values() if 'grows' in v or 'moves' in v)} part(s) move; drawing {'valid' if res.get('drawing_valid') else 'INVALID'}"
        if name == "inspect_assembly" and isinstance(res, dict):
            return f"{res.get('parameter')}: {_n(res.get('core_parts'))} core part(s), {_n(res.get('tied_to_it'))} tied, {_n(res.get('anchors'))} anchor option(s)"
        vs = _verdicts(res)
        if name == "state_plan" and vs:
            v = vs[0]
            return (f"{len(v.get('applied') or [])} kept in the plan" + (f"; {len(v.get('refused') or [])} refused ({str((v.get('refused') or ['?'])[0])[:90]})" if v.get("refused") else "")
                    + (f"; not yet in the plan: {str((v.get('not_yet_in_the_plan') or [''])[0])[:90]}" if v.get("not_yet_in_the_plan") else ""))
        if name in ("describe_views", "share_sizes") and vs:
            v = vs[0]
            return f"{len(v.get('applied') or [])} applied" + (f"; {len(v.get('refused') or [])} refused ({str((v.get('refused') or ['?'])[0])[:90]})" if v.get("refused") else "")
        if name == "inspect_annotations" and isinstance(res, dict) and "total" in res:
            return f"{res['total']} annotation(s)"
        if name == "inspect_layers" and isinstance(res, dict) and isinstance(res.get("layers"), list):
            return f"{len(res['layers'])} layer(s)"
        if name in ("define_parts", "define_parameters", "set_levels", "set_formulas", "add_constraints", "state_behaviours", "account_instruction",
                    "define_transforms", "update_checklist", "record_learned", "accept_semantics", "rename_values") and vs:
            ok = [v for v in vs if v.get("ok")]
            bad = [v for v in vs if not v.get("ok")]
            names = _ids([v.get("item") for v in ok])
            tail = f"; {len(bad)} refused ({str((bad[0].get('rejected') or ['?'])[0])[:70]})" if bad else ""
            return f"{len(ok)} accepted{' — ' + names if names else ''}{tail}"
        if name == "propose_plan" and vs:
            v = vs[0]
            anchor = (v.get("anchor") or {}).get("policy")
            if v.get("plan") == "accepted and measured":
                c = v.get("checks") or {}
                return f"plan accepted and measured ({c.get('passed', '?')} checks passed, {c.get('failed', 0)} failed); anchor {anchor}"
            if v.get("ok") is False:
                return f"plan refused: {str((v.get('rejected') or ['?'])[0])[:120]}"
            return f"plan {v.get('plan')}: {_n(v.get('questions'))} question(s) for you" + (f", {_n(v.get('conflicts'))} conflict(s)" if v.get("conflicts") else "")
        if name == "ask_person":
            return f"asked: {str(a.get('question', ''))[:120]}"
        if name == "finish":
            r = res if isinstance(res, dict) else {}
            return "finished" if r.get("done") else f"not finished yet: {str(r.get('hint') or r.get('waiting_for') or '')[:140]}"
        if name == "set_structure":
            return f"{a.get('structure_type', '')} ({a.get('family', '')})"
        if name == "remove":
            return str((vs[0] if vs else {}).get("engine") or "removed")[:80]
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):  # a summary is never allowed to break a run
        return ""
    return ""


def shrink(obj, depth: int = 0, limit_list: int = 14, limit_str: int = 500):
    """A bounded copy of any result for the timeline: long lists and strings cut (and said to be), depth capped, bytes dropped —
    so a person can expand what a tool really returned without a single call weighing megabytes."""
    if isinstance(obj, (bytes, bytearray)):
        return f"<{len(obj)} bytes>"
    if isinstance(obj, str):
        return obj if len(obj) <= limit_str else obj[:limit_str] + f"… (+{len(obj) - limit_str} chars)"
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    if depth >= 6:
        return "…"
    if isinstance(obj, dict):
        items = list(obj.items())
        out = {str(k): shrink(v, depth + 1, limit_list, limit_str) for k, v in items[:40] if not str(k).startswith("_")}
        if len(items) > 40:
            out["…"] = f"+{len(items) - 40} more keys"
        return out
    if isinstance(obj, (list, tuple, set)):
        seq = list(obj)
        out = [shrink(v, depth + 1, limit_list, limit_str) for v in seq[:limit_list]]
        if len(seq) > limit_list:
            out.append(f"… +{len(seq) - limit_list} more")
        return out
    return shrink(json.loads(json.dumps(obj, default=str)), depth + 1, limit_list, limit_str)
