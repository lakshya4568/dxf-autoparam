"""A sheet saved with JOINED units (views drawn in projection analysed as one unit, before local systems) made into LOCAL SYSTEMS, each view its own
unit — its work carried over, never retyped. Nothing of the joined sheet is changed: a new sheet model is built from the same drawing, and the
caller saves it as a new project.

The work of a joined unit is replayed into each of its views through the agent's own tool path — the calls a model makes, each validated by the
engine as it would be in a run (define_parts, define_parameters, set_levels, keep_dimensions) — with every reference mapped by the sheet itself:
an entity by its place in the sheet, a set-out line by its axis and coordinate in the view its entities are drawn in, a size by its two lines (or
the dimension that states it), a region by the entities on its boundary. Each view is then committed as a run commits (the design intent derived,
the sizes nobody named kept as drawn); what both views name across their projection is bound by the projection as one shared value
(projection.bind); values shared with other units are shared again; the values a person set are applied again. What could not be carried is said,
item by item, never guessed — a report a person reads before using the new project.

    new, report = separate(SheetModel.load(copy_of_the_project, dxf=...))
    new.save("<drawing>.views.autoparam.json")
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any

from .cadjson import entity_id, entity_index
from .crossview import SheetError, SheetModel
from .dxf_read import ReadOptions, read_dxf


def separate(old: SheetModel, pack=None) -> tuple[SheetModel, dict]:
    if old.systems != "joined":
        raise SheetError("the sheet is already made of local systems")
    dr, _ = read_dxf(old.path, ReadOptions(curves=old.dr.curves))
    new = SheetModel(dr, layout=copy.deepcopy(old.layout), unlinked=set(old.unlinked), systems="views")
    new.accepted = set(old.accepted)
    new.relations, new.questions, new.prefs = copy.deepcopy(old.relations), list(old.questions), copy.deepcopy(old.prefs)
    new.semantics, new.agent_notes, new.runs = copy.deepcopy(old.semantics), copy.deepcopy(old.agent_notes), list(old.runs)
    new._relayout()
    report: dict[str, Any] = {"units": {}, "shared": [], "values": [], "not_carried": []}
    if old.domain:
        report["not_carried"].append(f"{len(old.domain)} production rule binding(s): bound to the joined units — bind them again on the views")
    placed: dict[str, dict[str, str]] = {}  # old unit → local name → the new units it was defined in
    for uid, u in old.units.items():
        if not u.answer:
            continue
        if len(u.views) == 1:  # the same view, the same entities: the same analysis and ids — carried as it is
            nid = new.unit_of_view[u.views[0]]
            new.units[nid].answer = copy.deepcopy(u.answer)
            new.units[nid].prog = None
            placed[uid] = {p["name"]: [nid] for p in u.answer.get("parameters", [])} | {lv["name"]: [nid] for lv in u.answer.get("levels", [])}
            report["units"][uid] = {"to": [nid], "carried": "as it was (one view)"}
            continue
        placed[uid], report["units"][uid] = _replay(old, new, uid, pack)
        for name, nids in sorted(placed[uid].items()):  # ONE value of the joined unit drawn in several of its views: one value still
            nids = list(dict.fromkeys(nids))
            have = next((q for q in new.shared.values() if q.name == name), None)
            todo = [(nid, name) for nid in nids if have is None or not any(b.unit == nid for b in have.bindings)]
            if len(nids) < 2 or not todo or have is None and len(todo) < 2:
                continue
            try:
                new.share(name, todo, label=name, evidence=[f"one value of the joined unit {uid}"], source="joined unit")
                report["shared"].append({"value": name, "shared": True, "how": f"one value of {uid}", "units": nids})
            except SheetError as exc:
                report["shared"].append({"value": name, "shared": False, "how": f"one value of {uid}", "why": str(exc)[:300]})
    for p in old.shared.values():
        targets: list[tuple[str, str]] = []
        for b in p.bindings:
            for nid in (placed.get(b.unit, {}).get(b.param) or []) if len(old.units[b.unit].views) > 1 else [new.unit_of_view[old.units[b.unit].views[0]]]:
                if (nid, b.param) not in targets:
                    targets.append((nid, b.param))
        have = next((q for q in new.shared.values() if q.name == p.name), None)
        targets = [t for t in targets if have is None or not any(x.unit == t[0] for x in have.bindings)]
        if not targets:
            report["shared"].append({"value": p.name, "shared": True, "how": "bound by the projection"})
            continue
        try:
            new.share(p.name, targets, label=p.label, evidence=list(p.evidence), source=p.source)
            report["shared"].append({"value": p.name, "shared": True, "units": sorted({b.unit for b in new._shared_by_name()[p.name].bindings})})
        except SheetError as exc:
            report["shared"].append({"value": p.name, "shared": False, "why": str(exc)[:300]})
    for uid, vals in old.values.items():
        for name, v in vals.items():
            key = name if name in new._shared_by_name() else next((f"{nid}.{name}" for nid in (placed.get(uid, {}).get(name) or [])), None)
            if key is None:
                report["values"].append({"value": f"{uid}.{name}", "set": False, "why": "it is no value of any view now"})
                continue
            r = new.apply({key: v})
            report["values"].append({"value": key, "to": v, "set": r.ok, **({"why": "; ".join(r.errors[:2])} if not r.ok else {})})
    new.history.clear()  # a new project: it starts here (the joined one keeps its own history)
    new.future.clear()
    return new, report


def _replay(old: SheetModel, new: SheetModel, uid: str, pack) -> tuple[dict[str, list[str]], dict]:
    """The work of one joined unit, view by view (module doc). Returns where each local name went and the unit's report."""
    from .ai import agent as A
    from .ai.context import SheetScope
    from .ai.loop import Budget, LoopState, execute_calls
    from .topology import of
    from .viewimg import box_around

    u = old.units[uid]
    ans = u.answer or {}
    an = old.pristine_analysis(uid)
    item_view = {k: old.layout.item_group.get(s) for k, s in enumerate(u.back)}
    placed: dict[str, list[str]] = {}
    out: dict[str, Any] = {"to": [], "per_view": {}, "not_carried": []}
    regions_old = {r.id: r for r in of(an).regions}
    clusters = {c.id: c for c in an.clusters.values()}
    for vid in u.views:
        nid = new.unit_of_view[vid]
        nu = new.unit(nid)
        nan = new.pristine_analysis(nid)
        index_of = {s: k for k, s in enumerate(nu.back)}
        tol = max(old.dr.tol * 2, 1e-6)

        def ent(eid: str, nu=nu, index_of=index_of) -> str | None:
            k = entity_index(eid)
            s = u.back[k] if k is not None and k < len(u.back) else None
            k2 = index_of.get(s) if s is not None else None
            return entity_id(nu.sub.items[k2]) if k2 is not None else None

        def line(d: str, vid=vid, nan=nan, tol=tol) -> str | None:
            src = an.datums.get(d)
            if src is None or not any(item_view.get(i) == vid for i in src.items):
                return None
            best = min(((abs(x.value - src.value), x.id) for x in nan.datums.values() if x.axis == src.axis), default=None)
            return best[1] if best is not None and best[0] <= tol else None

        def region(rid: str, nan=nan, nu=nu, index_of=index_of) -> str | None:
            r = regions_old.get(rid)
            if r is None:
                return None
            want = {index_of[u.back[k]] for k in r.items if u.back[k] in index_of}
            if not want:
                return None
            best = max(((len(want & r2.items) / len(want | r2.items), r2.id) for r2 in of(nan).regions), default=(0.0, None))
            return best[1] if best[0] >= 0.9 else None

        calls: list[tuple[str, list[dict]]] = []
        # parts: what of each is drawn in this view; an assembly when one of its parts is
        parts = []
        for c in ans.get("components", []):
            if c.get("source") == "legend":
                continue
            ents = [e for e in (ent(x) for x in c.get("entities", [])) if e]
            regs = [r for r in (region(x) for x in c.get("regions", [])) if r]
            if ents or regs or not (c.get("entities") or c.get("regions")):
                parts.append({**{k: c[k] for k in ("name", "type", "level", "parent", "existing", "parametrize", "description", "evidence") if c.get(k) is not None},
                              "entities": ents, "regions": regs})
        names = {p["name"] for p in parts if p["entities"] or p["regions"]}
        keep = set(names)
        for p in parts:  # the assemblies above what this view draws
            q = p
            while q.get("parent"):
                keep.add(q["parent"])
                q = next((x for x in parts if x["name"] == q["parent"]), {})
        parts = [p for p in parts if p["name"] in keep]
        parts.sort(key=lambda p: (p.get("level") != "assembly", p["name"]))
        if parts:
            calls.append(("define_parts", parts))
        # values: each occurrence the view draws, by its two lines there (one cluster: a candidate with its occurrences)
        items = []
        for p in ans.get("parameters", []):
            every = clusters[p["candidate"]].gaps if p.get("candidate") in clusters else []
            occ = p.get("occurrences") or every
            occ = [occ] if isinstance(occ, str) else list(occ)
            if "all" in occ:  # every equal size of the candidate is this one value ("all", or ["all"])
                occ = list(every)
            pairs = [(an.gaps[g].a, an.gaps[g].b) for g in occ if g in an.gaps] or ([(p["from_datum"], p["to_datum"])] if p.get("from_datum") and p.get("to_datum") else [])
            mine = [(line(a), line(b)) for a, b in pairs]
            mine = [(a, b) for a, b in mine if a and b and a != b]
            if not mine:
                continue
            gaps = [g.id for g in nan.gaps.values() if (g.a, g.b) in mine or (g.b, g.a) in mine]
            cl = {nan.gaps[g].cluster for g in gaps}
            base = {k: p[k] for k in ("name", "label", "kind") if p.get(k)} | ({"part": p["component"]} if p.get("component") in names else {})
            if gaps and len(cl) == 1 and None not in cl:
                items.append({**base, "candidate": cl.pop(), "occurrences": gaps})
            else:
                items.append({**base, "from_line": mine[0][0], "to_line": mine[0][1]})
            placed.setdefault(p["name"], []).append(nid)
        if items:
            calls.append(("define_parameters", items))
        levels = [{"line": ln, "name": lv["name"], "role": lv.get("role", "site_input")} for lv in ans.get("levels", [])
                  if (ln := line(lv.get("datum") or lv.get("line") or ""))]
        for lv in levels:
            placed.setdefault(lv["name"], []).append(nid)
        if levels:
            calls.append(("set_levels", levels))
        kept = [{"dimension": e, "why": why} for d, why in (ans.get("kept_dimensions") or {}).items() if (e := ent(d))]
        if kept:
            calls.append(("keep_dimensions", kept))
        wb = A.Workbench(new.path, region=box_around([new.layout.group(vid).bbox], 0.0), start=None, drawing=nu.sub, analysis=nan,
                         scope=SheetScope(new, nid), pack=pack)
        said: dict[str, Any] = {}
        for name, its in calls:
            res, _done = execute_calls(wb, [SimpleNamespace(name=name, args={"items": its})], lambda e: None, LoopState(), Budget(), {})
            verdicts = []
            for part in res:  # what a model reads back: the call's function response, one verdict per item
                got = part.function_response.response.get("result")
                verdicts += [v for v in ((got.get("result") if isinstance(got, dict) else got) or []) if isinstance(v, dict)]
            said[name] = {"asked": len(its), "accepted": sum(1 for v in verdicts if v.get("ok")),
                          "refused": [f"{v.get('item')}: {'; '.join(v.get('rejected') or [])[:200]}" for v in verdicts if not v.get("ok")][:12]}
        try:
            res = new.commit_answer(nid, wb.answer, keep_unnamed_as_drawn=True)
            said["committed"] = True
            if res.get("projection"):
                said["projection"] = [{k: r.get(k) for k in ("value", "into", "bound", "why_not")} for r in res["projection"]]
        except SheetError as exc:
            said.update(committed=False, why=str(exc)[:400])
        out["per_view"][vid] = {"unit": nid, **said}
        out["to"].append(nid)
    carried = {n for n in placed}
    lost = [p["name"] for p in ans.get("parameters", []) if p["name"] not in carried] + [lv["name"] for lv in ans.get("levels", []) if lv["name"] not in carried]
    if lost:
        out["not_carried"].append(f"no view draws both lines of: {', '.join(lost)}")
    for k in ("line_roles", "datum_formulas", "relations", "behaviours", "constraints"):
        if ans.get(k):
            out["not_carried"].append(f"{len(ans[k])} {k.replace('_', ' ')}: written on the joined unit's lines — state them again on the view")
    if any(p.get("status") == "accepted" and (p.get("anchor") or {}).get("source") != "design intent" for p in ans.get("plans", [])):
        out["not_carried"].append("a side a person chose: choose it again on the view (the design intent is derived again)")
    return placed, out
