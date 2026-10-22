"""The agent's understanding of the WHOLE drawing — global first, then a view, a component or an annotation on demand —
and its working memory kept on the sheet (a checklist; facts it established, each with its evidence and the revision it
was established on), so that a new turn, a resumed run or a later run reuses what is known instead of rediscovering it.

    drawing_overview(sm)            the sheet in one compact record: views, layers, entity kinds, fidelity, existing /
                                    proposed, annotations by kind, levels, links, shared values, parametrization, decisions,
                                    checklist, learned facts (stale ones marked), open questions — no raw geometry
    view_context(sm, view)          one view: its layers, components, dimensions, notes (with what they refer to), levels,
                                    values, validation, what is unresolved
    component_context(bench, …)     one part / region / set of entities / annotation: exact geometry (sheet mm and local mm
                                    from the component's own corner), the notes on it, what touches it, what moves it — and a
                                    crop whose labels are the same ids
    parameter_review(sm, uid)       every value of a unit classified (named input, worked out, local measurement, duplicate
                                    candidate, …) with names proposed from evidence (the dimension or note that states it,
                                    the part it sizes) — proposals only; rename_values applies them, the engine checks

Everything is computed from the engine's own state and reused while its inputs are unchanged (cache.Memo); numbers are exact
(the DXF's), pictures are for reading, never for measuring.
"""

from __future__ import annotations

import json
import re
from collections import Counter

from ..cache import decisions_key, drawing_key, layout_key, values_key
from ..cadjson import entity_id, entity_index
from ..crossview import SheetError

S, N, B = {"type": "string"}, {"type": "number"}, {"type": "boolean"}
LIST = {"type": "array", "items": {"type": "string"}}
GENERIC_NAME = re.compile(r"^(Gap|Thk|Off|Step|Leg|Run|Rise|Pitch|Dim|Size|Ring|Diam|Slope|Arc)[XYR]?\d+$")


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


UNDERSTANDING_TOOL_SPECS = [
    ("drawing_overview", ("The whole drawing in one compact record — read it FIRST, and again only when the revision changed: views (kind, type, "
                          "name, unit, scale, what each holds), layers (colour, linetype, character, views), entity kinds, whether every visible "
                          "entity is drawn, existing / proposed classes with their evidence, annotations by kind (and how many are unresolved), stated "
                          "levels, projection links, shared values, which units are parametrized and how, the semantic decisions accepted, your "
                          "checklist and the facts you recorded (stale ones marked). No raw geometry: ask inspect_view / inspect_component for it."),
     _obj({})),
    ("inspect_view", ("One view: its layers and colours, its components (named parts, else the closed regions) with the notes that name them, its "
                      "dimensions (driving / reference / worked out, with the lines they measure), its notes and labels (kind, what each refers to, "
                      "how it behaves), levels, the unit's values (named or generic), validation, and what is unresolved. picture: true adds a picture "
                      "of the view."),
     _obj({"view": S, "picture": B}, ["view"])),
    ("inspect_component", ("One component in detail — a part (unit + part), a region (unit + R…), entities (unit + ids) or an annotation (its id): "
                           "every entity with its exact points (sheet mm, and local mm from the component's lower-left corner), layer, colour, "
                           "linetype and DXF handle; the notes attached to it; what it touches; the values that move it; whether it is held. "
                           "picture: true adds a crop whose labels are exactly these ids."),
     _obj({"unit": S, "part": S, "region": S, "entities": LIST, "annotation": S, "picture": B}, [])),
    ("inspect_annotations", ("Annotations filtered by view, kind (dimension_driving, level, component_label, material, construction_note, slope, "
                             "status, section_label, view_title, general_note, leader …) and status (resolved / ambiguous / unassociated): what each "
                             "says, what it refers to with the evidence (ranked), and how it behaves (geometry, component, datum, view, sheet, fixed)."),
     _obj({"view": S, "kinds": LIST, "status": {"type": "string", "enum": ["resolved", "ambiguous", "unassociated"]}, "limit": N, "offset": N})),
    ("inspect_layers", ("Every layer with its CAD properties and what is on it; existing / proposed / removed / construction counts and the colour "
                        "conventions this drawing itself uses (learned from its own notes, never assumed)."), _obj({})),
    ("find_duplicates", ("Entities drawn twice: exact duplicates, the same geometry in another style (layer / colour / linetype — often existing "
                         "under proposed), near duplicates and overlapping lines. Reported, never merged."), _obj({"view": S, "limit": N})),
    ("impact_plan", ("BEFORE changing a value: what a step of it moves, resizes or keeps (per component), which named sizes stay and which are worked "
                     "out from it, which notes and dimensions update, which views change, how far it can go — measured on a trial regeneration "
                     "of the sheet. name: a shared name or 'U….local'."),
     _obj({"name": S, "step": N}, ["name"])),
    ("check_behaviour", ("A change regenerated and checked category by category, nothing committed: requested values measured on every occurrence, "
                         "components (stay / translate / rotate / resize / reshape, thickness kept), named sizes kept, interfaces still touching, "
                         "held geometry, annotations behaving, views, validity. changes: {name: value}."),
     _obj({"changes": {"type": "object", "additionalProperties": N}}, ["changes"])),
    ("review_parameters", ("A unit's values classified (named input, worked out, local measurement, duplicate candidate, generic name) with names "
                           "proposed from the drawing's own evidence (the dimension or note that states the size, the part it sizes, the kind of gap) — "
                           "proposals with their evidence; rename_values applies what you accept."),
     _obj({"unit": S}, ["unit"])),
    ("search_drawing", ("Where words and numbers are stated on the WHOLE sheet — notes, dimensions, levels, titles, the views' names, and the parts and "
                        "values already named — each hit with its unit, view and the id every other tool takes. A hit has any of the words (or the number); "
                        "the best matches come first. Use it to find every place a part or a size is mentioned before you say how the views relate."),
     _obj({"words": LIST, "numbers": {"type": "array", "items": N},
           "kinds": {"type": "array", "items": {"type": "string", "enum": ["note", "title", "level", "dimension", "view", "part", "value"]}},
           "limit": N})),
    ("compare_views", ("What the views state side by side, from the engine's reading of every note, dimension and level: levels stated in several views, "
                       "levels stated at different values under the same words, sizes (dimensions and notes) stated in several views, notes with the same words "
                       "and different numbers, and vertical dimensions that run between two stated levels (a size that IS the difference of two levels). "
                       "Evidence, not a verdict: equal numbers are not one size, and the same words with two numbers are for the person. `units` narrows to "
                       "those units; `focus` to the words and numbers it names."),
     _obj({"units": LIST, "focus": S})),
    ("calculate", ("Arithmetic over the drawing's named values and levels, in millimetres (a level in metres is taken as millimetres), by the engine's safe "
                   "evaluator: numbers, names, + - * / ^ and its functions. Names are values of the open unit, of a unit you give, or shared values. Use it "
                   "to check a relation before you state it, instead of working it out in your head."),
     _obj({"expression": S, "unit": S}, ["expression"])),
    ("update_checklist", ("Your checklist for this task — what you learned, what you will do, how you will check it — kept on the sheet with the "
                          "revision of each item, shown to the person and given back to you every turn. Items with the same id are replaced."),
     _obj({"items": {"type": "array", "items": _obj({"id": S, "text": S, "status": {"type": "string", "enum": ["todo", "doing", "done", "blocked"]},
                                                     "evidence": S}, ["text", "status"])}}, ["items"])),
    ("record_learned", ("Facts you established about this drawing (what a view is, what a note refers to, which colour is proposed work, which value "
                        "is the clear span …), each with its evidence — kept on the sheet, given back to you instead of being worked out again; a "
                        "fact about geometry that changed since is marked stale."),
     _obj({"facts": {"type": "array", "items": _obj({"fact": S, "about": S, "evidence": S}, ["fact", "evidence"])}}, ["facts"])),
    ("accept_semantics", ("Semantic decisions to keep on the sheet (undoable): existing / proposed / removed / construction status by layer, by "
                          "colour or for entities — each with why. They become evidence every later analysis reads."),
     _obj({"status": {"type": "array", "items": _obj({"by": {"type": "string", "enum": ["layer", "colour", "entities"]}, "key": S, "entities": LIST,
                                                      "status": {"type": "string", "enum": ["existing", "proposed", "removed", "construction", "alternative"]},
                                                      "why": S}, ["by", "status", "why"])}}, ["status"])),
    ("rename_values", ("Give values engineering names, several in one call. `from`: the value's name as review_parameters lists it (a bare name, in the "
                       "open unit), or 'U01.name' for another unit's value, or a shared name. `to`: the new name, bare and PascalCase (ClearHeadroom — no unit "
                       "prefix). Each rename keeps the value, its bindings, formulas, plans and history (undoable). A name another unit already uses for its "
                       "own value is fine — it is a separate value there; use share_sizes if it is the same size seen again."),
     _obj({"items": {"type": "array", "items": _obj({"from": S, "to": S, "why": S}, ["from", "to"])}}, ["items"])),
]
for _n, _d, _sch in UNDERSTANDING_TOOL_SPECS:  # every call may say, for the person watching, what it is for (the model's own words)
    _sch["properties"].setdefault("why", {"type": "string", "description": "One short sentence for the person watching: what you are doing with this call and why."})
UNDERSTANDING_READ = {"drawing_overview", "inspect_view", "inspect_component", "inspect_annotations", "inspect_layers", "find_duplicates",
                      "impact_plan", "check_behaviour", "review_parameters", "search_drawing", "compare_views", "calculate"}
UNDERSTANDING_WRITE = {"update_checklist", "record_learned", "accept_semantics", "rename_values"}


# ── the sheet's working memory ─────────────────────────────────────────────────────


def notes_of(sm) -> dict:
    """The agent's notes on the sheet (not undo state: a checklist is not undone with a value; saved with the project)."""
    if not hasattr(sm, "agent_notes") or not isinstance(sm.agent_notes, dict):
        sm.agent_notes = {"checklist": [], "learned": []}
    sm.agent_notes.setdefault("checklist", [])
    sm.agent_notes.setdefault("learned", [])
    return sm.agent_notes


def _fact_key(sm) -> str:
    return f"{drawing_key(sm)}|{layout_key(sm)}"


def learned_now(sm) -> list[dict]:
    """The recorded facts, each marked stale when the drawing or its views changed since it was recorded."""
    key = _fact_key(sm)
    return [{**{k: f[k] for k in ("fact", "about", "evidence", "revision") if k in f}, **({"stale": True} if f.get("key") != key else {})}
            for f in notes_of(sm)["learned"]]


# ── global ──────────────────────────────────────────────────────────────────────────


def drawing_overview(sm) -> dict:
    from ..understanding import duplicates, layers, sheet_annotations, statuses

    def compute() -> dict:
        u_mm = sm.dr.units_mm
        cov = sm.dr.coverage or {}
        anns = sheet_annotations(sm)
        st = statuses(sm)
        by_view: dict[str, Counter] = {}
        for a in anns:
            by_view.setdefault(a.get("view") or "", Counter())[a["kind"]] += 1
        views = []
        for g in sm.layout.groups:
            uid = sm.unit_of_view.get(g.id)
            u = sm.units.get(uid) if uid else None
            row = {"id": g.id, "kind": g.kind, "type": g.view_type, "name": g.name[:60], "unit": uid, "entities": len(g.items),
                   "bbox_mm": [round(v * (g.units_mm or u_mm)) for v in g.bbox]}
            if g.scale:
                row["scale"] = f"1:{g.scale:g}"
            if by_view.get(g.id):
                row["annotations"] = dict(by_view[g.id].most_common(6))
            if u is not None:
                row["parametrized"] = bool(u.answer)
            views.append(row)
        levels = []
        for uid, u in sm.units.items():
            an = u.an
            if an is None:
                continue
            for d, ti, words, v in an.stated_levels[:12]:
                levels.append({"unit": uid, "line": d, "level_m": v, "note": words[:40]})
        units = []
        for uid, u in sm.units.items():
            row = {"id": uid, "views": u.views, "parametrized": bool(u.answer)}
            if u.built:
                names = list(u.prog.params)
                row["values"] = len(names)
                row["named"] = [n for n in names if not GENERIC_NAME.match(n)][:16]
                row["generic"] = sum(1 for n in names if GENERIC_NAME.match(n))
            units.append(row)
        dup = duplicates(sm)
        return {
            "drawing": {"file": sm.path.rsplit("/", 1)[-1], "revision": sm.revision, "mm_per_unit": u_mm, "layout": sm.dr.layout,
                        "extent_mm": [round(v * u_mm) for v in sm.dr.extent], "faithful": cov.get("faithful", True),
                        "not_drawn": cov.get("problems", [])[:4], "layouts": [{"name": lo["name"], "entities": lo["entities"], "viewports": len(lo["viewports"])}
                                                                               for lo in cov.get("layouts", [])][:6]},
            "entities": {r["type"]: r["read"] for r in cov.get("types", []) if r["read"]},
            "layers": [{"name": r["name"], "colour": r["color"], "linetype": r["linetype"], "entities": r["entities"], "character": r["character"],
                        "views": list(r["views"])[:4], **({"name_says": r["name_says"]} if r.get("name_says") else {}),
                        **({"off": True} if not r["on"] else {}), **({"frozen": True} if r["frozen"] else {})}
                       for r in layers(sm) if r["entities"] or not r["on"] or r["frozen"]],
            "status": {"counts": st["counts"], "learned_colours": {k: {"status": v["status"], "notes": v["count"], "contrary": v.get("contrary", 0)}
                                                                   for k, v in st["learned_colours"].items()}},
            "views": views,
            "links": [{"views": [lk["a"], lk["b"]], "axis": lk["axis"], "shared_lines": lk["planes"], "one_unit": sm.is_linked(lk)} for lk in sm.links],
            "shared_values": [{"name": p.name, "value_mm": round(p.value, 1), "units": [b.unit for b in p.bindings]} for p in sm.shared.values()],
            "levels": levels[:40],
            "annotations": {"total": len(anns), "by_kind": dict(Counter(a["kind"] for a in anns).most_common()),
                            "ambiguous": sum(1 for a in anns if a["status"] == "ambiguous"),
                            "unassociated": sum(1 for a in anns if a["status"] == "unassociated")},
            "duplicates": {**dup["summary"], "style_pairs": dict(list(dup["style_pairs"].items())[:4])},
            "units": units,
            "decisions": {"status": len(sm.semantics.get("status", [])), "annotations": len(sm.semantics.get("annotations", {}))},
            "values_changed": {k: v for k, v in sm.values.items() if v},
            "questions": sm.questions[:8],
        }

    for uid in sm.units:  # the analyses the overview reads (cheap: no programs are built)
        sm.analysis(uid)
    out = sm.memo.get("drawing_overview", (drawing_key(sm), layout_key(sm), decisions_key(sm), values_key(sm), sm.revision), compute)
    return {**out, "checklist": notes_of(sm)["checklist"], "learned": learned_now(sm)}


# ── one view ────────────────────────────────────────────────────────────────────────


def view_context(sm, vid: str) -> dict:
    from ..understanding import sheet_annotations, statuses

    g = next((x for x in sm.layout.groups if x.id == vid), None)
    if g is None:
        raise KeyError(f"no view {vid}")
    u_mm = g.units_mm or sm.dr.units_mm
    items = set(g.items)
    anns = [a for a in sheet_annotations(sm) if a.get("view") == vid]
    st = statuses(sm)
    layers_c = Counter(sm.dr.items[i].layer for i in g.items)
    colours = Counter(("ACI 7" if (sm.dr.items[i].extra.get("style") or {}).get("fg") else (sm.dr.items[i].extra.get("style") or {}).get("color", "?"))
                      for i in g.items)
    status_c = Counter(st["entities"].get(i, {}).get("status", "unclassified") for i in g.items)
    out: dict = {"view": {"id": vid, "kind": g.kind, "type": g.view_type, "name": g.name, "scale": f"1:{g.scale:g}" if g.scale else None,
                          "bbox_mm": [round(v * u_mm) for v in g.bbox], "entities": len(g.items)},
                 "layers": dict(layers_c.most_common(10)), "colours": dict(colours.most_common(6)), "status": dict(status_c)}
    uid = sm.unit_of_view.get(vid)
    if uid:
        u = sm.units[uid]
        out["view"]["unit"] = uid
        out["view"]["unit_views"] = u.views
        try:  # the view's own coordinates, as the person's view tab shows them: where 0,0 is, what it is set from, and the level a height reads
            from ..frames import view_frame

            fr = view_frame(sm, vid)
            (x0, y0), (x1, y1) = fr.to_local(g.bbox[0], g.bbox[1]), fr.to_local(g.bbox[2], g.bbox[3])
            rl0 = fr.rl(fr.origin[1])
            out["view"]["frame"] = {"x_from": fr.x_from, "y_from": fr.y_from, "local_bbox_mm": [round(v, 1) for v in (x0, y0, x1, y1)],
                                    **({"level_at_y0_m": round(rl0, 3), "level_from": fr.level.get("name")} if rl0 is not None and fr.level else {}),
                                    "origin_dxf": [round(v, 3) for v in fr.origin], "mm_per_dxf_unit": fr.mm_per_unit,
                                    "how": "the person's view tab shows this view in these coordinates: local mm = (DXF point − origin_dxf) × mm_per_dxf_unit"
                                           + ("; a height y (mm) in it is at level level_at_y0_m + y/1000" if rl0 is not None else "")}
        except (KeyError, ValueError, ArithmeticError, AttributeError) as exc:
            out["view"]["frame"] = {"unavailable": f"{type(exc).__name__}: {exc}"[:160]}
        an = sm.analysis(uid)
        comps = []
        labels_on: dict[int, list[str]] = {}
        for a in anns:
            for t in a.get("targets") or []:
                if t.get("index") is not None and a["kind"] not in ("dimension_driving", "dimension_reference", "dimension_derived"):
                    labels_on.setdefault(t["index"], []).append(a["text"][:40])
        parts = (u.prog.intent.get("parts") or {}) if u.built else {}
        if parts:
            from ..assembly import part_entities

            for name, p in parts.items():
                ents = part_entities(u.prog, parts, name)
                sheet_ents = [u.back[i] for i in ents]
                comps.append({"id": name, "kind": "part", "type": p.type, "entities": len(ents), "existing": p.existing,
                              "labels": sorted({t for i in sheet_ents for t in labels_on.get(i, [])})[:4]})
        else:
            from ..topology import of

            topo = of(an)
            for r in sorted(topo.regions, key=lambda r: -r.area)[:30]:
                sheet_ents = [u.back[i] for i in r.items]
                comps.append({"id": r.id, "kind": "region", "area_m2": round(r.area * u.sub.units_mm ** 2 / 1e6, 3),
                              "bbox_mm": [round(v * u.sub.units_mm) for v in r.bbox], "fill": (r.hatches[0] if r.hatches else None),
                              "labels": sorted({t for i in sheet_ents for t in labels_on.get(i, [])})[:4]})
        out["components"] = comps
        out["levels"] = [{"line": d, "level_m": v, "note": w[:40]} for d, _ti, w, v in an.stated_levels[:20]]
        if u.built:
            out["values"] = [{"name": n, "value": round(p.value, 3), "unit": p.unit, "kind": p.kind, "label": p.label if p.label != n else None,
                              "named": not GENERIC_NAME.match(n), "source": p.source} for n, p in list(u.prog.params.items())[:60]]
            rep = u.report
            if rep is not None:
                out["validation"] = {"errors": [e["message"][:160] for e in rep.errors()][:8],
                                     "warnings": [f.message[:160] for f in rep.findings if f.severity == "warning"][:6]}
    dims = [a for a in anns if a["kind"].startswith("dimension")]
    out["dimensions"] = [{"id": a["id"], "kind": a["kind"], "mm": (a.get("quantity") or {}).get("measured_mm"), "text": a["text"][:30],
                          "between": (a.get("quantity") or {}).get("between")} for a in dims[:50]]
    notes = [a for a in anns if not a["kind"].startswith("dimension")]
    out["notes"] = [{"id": a["id"], "kind": a["kind"], "text": a["text"][:70], "attachment": a["attachment"], "status": a["status"],
                     "target": (a.get("targets") or [{}])[0].get("ref")} for a in notes[:50]]
    out["unresolved"] = [a["id"] for a in anns if a["status"] != "resolved"][:30]
    out["entity_ids"] = "entity ids (L…, PL…, T…, D…) are the open unit's ids; inspect_component takes them"
    del items
    return out


# ── one component ───────────────────────────────────────────────────────────────────


def component_context(sm, uid: str | None = None, part: str | None = None, region: str | None = None, entities: list | None = None,
                      annotation: str | None = None) -> tuple[dict, str, list[int], tuple]:
    """(record, unit id, sheet entity indices, box in drawing units) for a part, a region, entities, or an annotation."""
    from ..topology import of
    from ..understanding import sheet_annotations

    ann = None
    if annotation:
        ann = next((a for a in sheet_annotations(sm) if a["id"] == annotation), None)
        if ann is None:
            raise KeyError(f"no annotation {annotation}")
        uid = uid or ann.get("unit")
    if not uid or uid not in sm.units:
        raise KeyError(f"name the unit (inspect_sheet lists them): {uid!r}")
    u = sm.unit(uid)
    an, prog = u.an, u.prog
    local: list[int] = []
    what = ""
    if part:
        parts = prog.intent.get("parts") or {}
        if part not in parts:
            raise KeyError(f"no part {part} in {uid} (parts: {', '.join(sorted(parts)[:12]) or 'none named yet'})")
        from ..assembly import part_entities

        local = sorted(part_entities(prog, parts, part))
        what = f"part {part}"
    elif region:
        r = of(an).by_id().get(region)
        if r is None:
            raise KeyError(f"no region {region} in {uid}")
        local = sorted(r.items)
        what = f"region {region}"
    elif entities:
        for eid in entities:
            k = entity_index(str(eid))
            if k is None or not 0 <= k < len(u.sub.items) or entity_id(u.sub.items[k]) != str(eid):
                raise KeyError(f"no entity {eid} in {uid}")
            local.append(k)
        what = f"entities {', '.join(map(str, entities[:6]))}"
    elif ann is not None:
        back = {s: k for k, s in enumerate(u.back)}
        local = [back[i] for i in ann["items"] if i in back]
        for t in ann.get("targets") or []:
            if t.get("index") is not None and t["index"] in back:
                local.append(back[t["index"]])
        what = f"annotation {annotation}"
    if not local:
        raise KeyError("name a part, a region, entities or an annotation")
    um = u.sub.units_mm
    pts = [p for k in local for p in u.sub.items[k].pts]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    from ..graph import _reach

    reach = _reach(prog)
    controlling: set[str] = set()
    held = False
    ents = []
    for k in local[:80]:
        it = u.sub.items[k]
        st = it.extra.get("style") or {}
        lines = set()
        for p in range(len(it.pts)):
            for ax in ("x", "y"):
                b = an.slot_datum.get((k, p, ax))
                if b:
                    lines.add(b[0])
                    controlling |= reach.get(b[0], set())
                    held = held or prog.origin.get(b[0]) in ("held", "existing")
        row = {"id": entity_id(it), "type": it.dxftype, "layer": it.layer, "colour": "ACI 7" if st.get("fg") else st.get("color"),
               "linetype": st.get("lt"), "handle": (it.extra.get("source") or {}).get("handle", it.handle),
               "points_mm": [[round(x * um, 1), round(y * um, 1)] for x, y in it.pts[:12]],
               "local_mm": [[round((x - x0) * um, 1), round((y - y0) * um, 1)] for x, y in it.pts[:12]], "lines": sorted(lines)[:8]}
        if it.text:
            row["text"] = it.text[:60]
        ents.append(row)
    sheet_ents = {u.back[k] for k in local}
    notes = []
    for a in sheet_annotations(sm):
        if a.get("unit") != uid:
            continue
        if any(t.get("index") in sheet_ents for t in a.get("targets") or []) or set(a["items"]) & sheet_ents:
            notes.append({"id": a["id"], "kind": a["kind"], "text": a["text"][:60], "attachment": a["attachment"], "status": a["status"]})
    touching = []
    parts = prog.intent.get("parts") or {}
    if part and parts:
        from ..assembly import interfaces

        touching = [{"with": r["parts"][1] if r["parts"][0] == part else r["parts"][0], "kind": r["kind"], "evidence": r["evidence"]}
                    for r in interfaces(prog, parts) if part in r["parts"]][:12]
    rec = {"component": {"what": what, "unit": uid, "view": sm.layout.item_group.get(u.back[local[0]], ""),
                         "bbox_mm": [round(v * um, 1) for v in (x0, y0, x1, y1)], "local_origin_mm": [round(x0 * um, 1), round(y0 * um, 1)]},
           "entities": ents, "entities_total": len(local), "notes": notes[:20], "touches": touching,
           "moved_by": sorted(controlling)[:20], "held": held}
    return rec, uid, sorted(sheet_ents), (x0, y0, x1, y1)


# ── the values of a unit, reviewed ────────────────────────────────────────────────


KIND_WORDS = {"solid": "Thickness", "void": "Opening", "open": "Offset", "pitch": "Spacing", "leg": "Haunch", "chain": "Step", "slope": "SlopeRun",
              "diameter": "Diameter", "ring": "RingWall", "dim": "Length", "run": "Run", "rise": "Rise", "offset": "Offset"}


def _pascal(words: str) -> str:
    toks = [t for t in re.split(r"[^A-Za-z0-9]+", words) if t and not t.isdigit()]
    return "".join(t[:1].upper() + t[1:].lower() for t in toks)[:40]


def parameter_review(sm, uid: str) -> dict:
    """Each value of the unit: what it is (with evidence), and a name proposed from the drawing's own words when there is one."""
    from ..understanding import sheet_annotations

    u = sm.unit(uid)
    an, prog = u.an, u.prog
    um = u.sub.units_mm
    shared = {b.param: p.name for p in sm.shared.values() for b in p.bindings if b.unit == uid}
    dims_by_pair: dict[tuple, list[dict]] = {}
    for a in sheet_annotations(sm):
        if a.get("unit") == uid and a["kind"].startswith("dimension") and (a.get("quantity") or {}).get("between"):
            dims_by_pair.setdefault(tuple(sorted(a["quantity"]["between"])), []).append(a)
    worked = {r.name for r in prog.relations}
    values = list(prog.params.items())
    rows = []
    for name, p in values:
        row = {"name": name, "value": round(p.value, 3), "unit": p.unit, "kind": p.kind, "source": p.source}
        evidence = []
        generic = bool(GENERIC_NAME.match(name))
        pair = tuple(sorted(p.measures)) if p.measures else None
        stated = dims_by_pair.get(pair, []) if pair else []
        same = [n for n, q in values if n != name and q.kind == p.kind and q.unit == p.unit and abs(q.value - p.value) <= max(0.5, 1e-4 * abs(p.value))]
        if name in shared:
            cls = "shared"
            evidence.append(f"shared across units as {shared[name]}")
        elif p.source in ("person", "ai") and not generic:
            cls = "named_input"
            evidence.append(f"named by {'a person' if p.source == 'person' else 'the agent'}")
        elif p.kind == "level":
            cls = "level"
        elif name in worked:
            cls = "worked_out"
        elif same:
            cls = "duplicate_candidate"
            evidence.append(f"equal to {', '.join(same[:3])} (equal is not the same design value unless something says so)")
        elif generic and not stated and p.occurrences <= 1:
            cls = "local_measurement"
            evidence.append("one occurrence, no dimension or note states it")
        else:
            cls = "independent_input" if not generic else "generic_input"
        if stated:
            evidence.append("stated by " + ", ".join(f"{d['id']} ({d['text'][:24]})" for d in stated[:3]))
        row["class"] = cls
        # a name from the drawing's own words: the override text of a dimension that states it, else the part it sizes + the kind of size
        proposal = None
        for d in stated:
            words = re.sub(r"[\d.,]+\s*(MM|M)?", " ", d["text"] or "", flags=re.IGNORECASE)
            if re.search(r"[A-Za-z]{3,}", words) and "<>" not in (d.get("quantity") or {}).get("override", ""):
                proposal = (_pascal(words), f"the dimension {d['id']} says '{d['text'][:30]}'")
                break
        if proposal is None and p.component:
            kind_word = KIND_WORDS.get(_gap_kind(an, name, p) or "", "Size")
            proposal = (_pascal(p.component) + kind_word, f"it sizes {p.component} ({kind_word.lower()})")
        if proposal is None and generic:
            label = _nearby_label(sm, uid, p)
            if label:
                kind_word = KIND_WORDS.get(_gap_kind(an, name, p) or "", "Size")
                proposal = (_pascal(label) + kind_word, f"the note '{label}' names the part it sizes")
        if proposal and proposal[0] and proposal[0] != name and proposal[0] not in prog.params:
            row["proposed_name"], row["because"] = proposal
        row["evidence"] = evidence
        if p.measures:
            row["between"] = list(p.measures)
            row["measured_mm"] = round(abs(an.datums[p.measures[1]].value - an.datums[p.measures[0]].value) * um, 2) if all(m in an.datums for m in p.measures) else None
        rows.append(row)
    counts = Counter(r["class"] for r in rows)
    cleanup = [{"value": r["name"], "class": r["class"], "suggest": "rename" if r.get("proposed_name") else "review",
                "evidence": r["evidence"]} for r in rows if r["class"] in ("local_measurement", "duplicate_candidate", "generic_input")][:30]
    kept = len((sm.units[uid].answer or {}).get("frozen", []))
    return {"unit": uid, "values": rows, "counts": dict(counts), "cleanup": cleanup,
            **({"kept_as_drawn": f"{kept} more measured sizes nobody named are kept as drawn (not inputs; the drawing is as it was)"} if kept else {}),
            "rules": ["rename_values takes a value's name here exactly as listed (bare, in the open unit); the new name is bare too",
                      "a value is renamed, never re-made: rename_values keeps its bindings, formulas, plans and history",
                      "equal values stay separate inputs unless the drawing (a dimension, a note, a symmetry) says they are one",
                      "a value is removed only when nothing reads it and it is not the person's: removing an input freezes its geometry as drawn"]}


def _gap_kind(an, name: str, p) -> str | None:
    if not p.measures:
        return None
    a, b = sorted(p.measures)
    for g in an.gaps.values():
        if sorted((g.a, g.b)) == [a, b]:
            return g.kind.value
    return None


def _nearby_label(sm, uid: str, p) -> str | None:
    """A component label whose target lies on one of the value's two lines."""
    from ..understanding import sheet_annotations

    if not p.measures:
        return None
    u = sm.units[uid]
    an = u.an
    lines = set(p.measures)
    for a in sheet_annotations(sm):
        if a.get("unit") != uid or a["kind"] not in ("component_label", "material") or a["status"] != "resolved":
            continue
        for t in a.get("targets") or []:
            idx = t.get("index")
            if idx is None:
                continue
            back = {s: k for k, s in enumerate(u.back)}
            k = back.get(idx)
            if k is None:
                continue
            on = {an.slot_datum[(k, q, ax)][0] for q in range(len(u.sub.items[k].pts)) for ax in ("x", "y") if (k, q, ax) in an.slot_datum}
            if on & lines:
                words = re.sub(r"[\d.,]+\s*(MM|M|THK\.?|THICK)?", " ", a["text"], flags=re.IGNORECASE)
                if re.search(r"[A-Za-z]{3,}", words):
                    return words.strip()
    return None


# ── the session the run's bench routes to ────────────────────────────────────────


class UnderstandingSession:
    def __init__(self, bench):
        self.bench = bench
        self.sm = bench.sm
        self.results: dict[str, dict] = {}

    def call(self, name: str, a: dict) -> dict:
        sm = self.sm
        with self.bench._lock():
            if name == "drawing_overview":
                return drawing_overview(sm)
            if name == "inspect_view":
                out = view_context(sm, a["view"])
                if a.get("picture"):
                    pic = self.bench.zoom_view(view=a["view"], labels="none")
                    out["picture"] = {k: pic[k] for k in ("image", "box_mm", "size_px", "mm_per_px") if k in pic}
                    for k in ("_image", "_images", "pictures_already_shown"):  # the picture itself, or the word that the model still has it
                        if k in pic:
                            out[k] = pic[k]
                return out
            if name == "inspect_component":
                rec, uid, _ents, box = component_context(sm, a.get("unit"), a.get("part"), a.get("region"), a.get("entities"), a.get("annotation"))
                if a.get("picture"):
                    from ..viewimg import box_around

                    pic = sm_picture(self.bench, uid, box_around([box], 0.25))
                    rec["picture"] = {"image": pic["id"], "frame": pic["meta"]["frame"], "labels": "entity ids, the same as in `entities`"}
                    rec["_image"] = {"png": pic["png"], "id": pic["id"], "meta": pic["meta"]}
                    self.bench.run.note_image(pic, "inspect_component")
                return rec
            if name == "inspect_annotations":
                from ..understanding import sheet_annotations

                rows = sheet_annotations(sm)
                if a.get("view"):
                    rows = [r for r in rows if r.get("view") == a["view"]]
                if a.get("kinds"):
                    rows = [r for r in rows if r["kind"] in set(a["kinds"])]
                if a.get("status"):
                    rows = [r for r in rows if r["status"] == a["status"]]
                off, lim = int(a.get("offset") or 0), int(a.get("limit") or 40)
                return {"total": len(rows), "offset": off, "annotations": rows[off: off + lim]}
            if name == "inspect_layers":
                from ..understanding import layers, statuses

                st = statuses(sm)
                return {"layers": layers(sm), "status": {"counts": st["counts"], "learned_colours": st["learned_colours"]}}
            if name == "find_duplicates":
                from ..understanding import duplicates

                rep = duplicates(sm, a.get("view"))
                return {**rep, "groups": rep["groups"][: int(a.get("limit") or 30)]}
            if name == "impact_plan":
                from ..behaviour import impact_plan

                return impact_plan(sm, a["name"], a.get("step"))
            if name == "check_behaviour":
                from ..behaviour import behaviour_report

                rep = behaviour_report(sm, {k: float(v) for k, v in (a.get("changes") or {}).items()})
                # only what failed is given in full; what passed is counted (the model does not need every pass every time). A row that names its
                # entities by id (refs) does not need their sheet indices too: those are for the page to zoom to
                cats = {k: {"status": c["status"], "failed": [{x: v for x, v in r.items() if not (x == "entities" and r.get("refs"))}
                                                              for r in c["items"] if r["status"] == "fail"][:8],
                            "passed": sum(1 for r in c["items"] if r["status"] == "pass")} for k, c in rep["categories"].items()}
                return {"ok": rep["ok"], "failed": rep["failed"], "categories": cats, "changed_entities": rep["changed_entities"]}
            if name == "review_parameters":
                return parameter_review(sm, a["unit"])
            if name == "search_drawing":
                from .crosscheck import search_drawing

                return search_drawing(sm, a.get("words"), a.get("numbers"), a.get("kinds"), a.get("limit") or 40)
            if name == "compare_views":
                from .crosscheck import compare_views

                return compare_views(sm, [str(u) for u in a.get("units") or []] or None, str(a.get("focus") or ""))
            if name == "calculate":
                from .crosscheck import calculate

                return calculate(a.get("expression", ""), lambda n: self.bench.value_of(n, a.get("unit") or None))
        raise KeyError(name)

    def write(self, name: str, a: dict) -> tuple[str, str]:
        sm = self.sm
        notes = notes_of(sm)
        if name == "update_checklist":
            items = a.get("items") or []
            for k, it in enumerate(items):
                iid = str(it.get("id") or f"C{len(notes['checklist']) + k + 1}")
                row = {"id": iid, "text": (it.get("text") or "")[:200], "status": it.get("status", "todo"), "revision": sm.revision}
                if it.get("evidence"):
                    row["evidence"] = str(it["evidence"])[:200]
                notes["checklist"] = [c for c in notes["checklist"] if c["id"] != iid] + [row]
            self.results["checklist"] = {"ok": True, "items": len(notes["checklist"])}
            return "checklist", f"{len(items)} item(s) kept"
        if name == "record_learned":
            key = _fact_key(sm)
            for f in a.get("facts") or []:
                fact = (f.get("fact") or "").strip()
                if not fact or not (f.get("evidence") or "").strip():
                    continue
                notes["learned"] = [x for x in notes["learned"] if x["fact"] != fact] + [
                    {"fact": fact[:240], "about": (f.get("about") or "")[:60], "evidence": f["evidence"][:240], "revision": sm.revision, "key": key}]
            self.results["learned"] = {"ok": True, "facts": len(notes["learned"])}
            return "learned", f"{len(notes['learned'])} fact(s) on record"
        if name == "accept_semantics":
            from ..layers import STATUS

            rows = []
            refused = []
            for d in a.get("status") or []:
                by, st = d.get("by"), d.get("status")
                if st not in STATUS or by not in ("layer", "colour", "entities") or not (d.get("why") or "").strip():
                    refused.append(f"{d}: by layer / colour / entities, a status and why")
                    continue
                if by == "layer" and d.get("key") not in {it.layer for it in sm.dr.items}:
                    refused.append(f"no layer {d.get('key')!r} with entities")
                    continue
                ents = []
                if by == "entities":
                    for eid in d.get("entities") or []:
                        k = entity_index(str(eid))
                        if k is None:
                            refused.append(f"no entity {eid}")
                            continue
                        ents.append(k)
                rows.append({"by": by, "key": d.get("key"), "entities": ents, "status": st, "who": "agent", "why": d["why"][:200], "revision": sm.revision})
            if rows:
                with self.bench._lock():
                    sm._push()
                    sm.semantics.setdefault("status", []).extend(rows)
                    self.bench.sync_revision()
            self.results["semantics"] = {"ok": not refused, "accepted": len(rows), **({"rejected": refused} if refused else {})}
            return "semantics", f"{len(rows)} decision(s) kept"
        if name == "rename_values":
            done, refused, notes = [], [], []
            for r in a.get("items") or []:
                old, new = (r.get("from") or "").strip(), (r.get("to") or "").strip()
                try:
                    with self.bench._lock():
                        old_key, new_name = resolve_rename(sm, old, new, self.bench.active)
                        sm.rename(old_key, new_name)
                        self.bench.sync_revision()
                        same = sm.namesakes(new_name, {old_key.split(".", 1)[0]} if "." in old_key else None)
                    done.append(f"{old} → {new_name}")
                    if same:
                        notes.append(f"{new_name} is also a value of " + ", ".join(f"{u}{'' if v is None else f' ({v:g})'}" for u, v in same[:4])
                                     + ": a separate value here — if it is the same size seen again, share_sizes joins them")
                except (SheetError, KeyError, ValueError) as exc:  # the sheet's refusal (a taken or malformed name) is that item's result
                    refused.append(f"{old} → {new}: {exc}")
            self.results["rename"] = {"ok": not refused, "renamed": done, **({"rejected": refused} if refused else {}), **({"note": notes} if notes else {})}
            return "rename", "; ".join(done)[:200]
        raise KeyError(name)

    def verdict(self, item: str) -> dict:
        key = {"checklist": "checklist", "learned": "learned", "semantics": "semantics", "rename": "rename"}.get(item, item)
        return self.results.get(key, {"ok": True})


def resolve_rename(sm, old: str, new: str, active: str | None) -> tuple[str, str]:
    """What rename_values means by its two names, in the words review_parameters speaks: `from` may be a bare name (a value of the open unit — else
    the one unit that has it), 'U01.name' or a shared name; `to` is a bare name, and a unit prefix copied from `from` is dropped. Returns (the name
    SheetModel.rename takes, the bare new name) or raises SheetError saying which of the two names is wrong, and why."""
    old, new = old.strip(), new.strip()
    shared = {p.name for p in sm.shared.values()}

    def has(uid: str, local: str) -> bool:
        u = sm.unit(uid)
        return u.prog is not None and (local in u.prog.params or any(r.name == local for r in u.prog.relations))

    def kept(uid: str, local: str) -> bool:
        return any(r.get("name") == local for r in (sm.units[uid].answer or {}).get("frozen", []))

    if old in shared:
        key, unit = old, None
    elif "." in old:
        uid, local = old.split(".", 1)
        if uid not in sm.units:
            raise SheetError(f"the OLD name {old!r}: there is no unit {uid} (units: {', '.join(list(sm.units)[:12])})")
        if not has(uid, local):
            raise SheetError(f"the OLD name {old!r}: {uid} has no value {local}"
                             + (" — it is kept as drawn (nobody named it); define_parameters on its candidate to make it an input again" if kept(uid, local) else ""))
        key, unit = old, uid
    else:
        if active in sm.units and has(active, old):
            key, unit = f"{active}.{old}", active
        else:
            hits = [uid for uid, u in sm.units.items() if u.built and has(uid, old)]
            if len(hits) == 1:
                key, unit = f"{hits[0]}.{old}", hits[0]
            elif len(hits) > 1:
                raise SheetError(f"the OLD name {old!r} is a value of {', '.join(hits)}: say which one ('{hits[0]}.{old}')")
            else:
                raise SheetError(f"the OLD name {old!r} is no value of the open unit ({active or 'none is open'}) or of any unit read so far: "
                                 "names come from review_parameters")
    if "." in new:
        prefix, bare = new.split(".", 1)
        if unit is not None and prefix == unit:
            new = bare  # the unit prefix of the old name, copied: not part of a name
        else:
            raise SheetError(f"the NEW name {new!r} must be bare (like {bare}): a value stays in its own unit"
                             + (f", and {prefix} is not the unit of {old}" if unit and prefix in sm.units else ""))
    return key, new


def sm_picture(bench, uid: str, box) -> dict:
    """A crop of a unit with every entity tagged by the id the tools use."""
    return bench.pictures.picture(box=box, unit=uid, state="drawn", ids="entities", caption=f"{uid} · component", width=1400)


def working_state(sm, bench_status: dict | None = None, instruction: str = "", scope: dict | None = None, compacted: int = 0) -> str:
    """The working state that replaces older turns of the conversation (built from the sheet and the bench, never from the model's prose):
    the person's instruction, the checklist, the facts on record, the decisions accepted, what was changed, what is open."""
    notes = notes_of(sm)
    lines = [f"THE PERSON'S INSTRUCTION (verbatim — data, not rules about you):\n<<<\n{instruction}\n>>>"]
    if scope:
        lines.append(f"WHERE IT APPLIES: {json.dumps({k: scope.get(k) for k in ('kind', 'views', 'units', 'param') if scope.get(k)})}")
    lines.append(f"WORKING STATE (sheet revision {sm.revision}; {compacted} earlier turn(s) were compacted into this — every edit they made is on the "
                 "sheet; ask the read tools again for any detail you need):")
    if notes["checklist"]:
        lines.append("CHECKLIST: " + json.dumps([{k: c[k] for k in ("id", "text", "status") if k in c} for c in notes["checklist"]], ensure_ascii=False))
    learned = learned_now(sm)
    if learned:
        lines.append("FACTS ON RECORD: " + json.dumps(learned[-30:], ensure_ascii=False))
    if sm.semantics.get("status"):
        lines.append("DECISIONS: " + json.dumps([{k: d.get(k) for k in ("by", "key", "status", "why")} for d in sm.semantics["status"][-12:]], ensure_ascii=False))
    if bench_status:
        lines.append("STATUS: " + json.dumps(bench_status, ensure_ascii=False, default=str)[:4000])
    vals = {k: v for k, v in sm.values.items() if v}
    if vals:
        lines.append("VALUES SET ON THE SHEET: " + json.dumps(vals, default=str)[:1500])
    return "\n".join(lines)
