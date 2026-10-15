"""How an assembly behaves when values change — predicted before an edit (impact_plan) and checked after it
(behaviour_report): per value occurrence, per component, per interface, per annotation, per view. Always measured on the
regenerated geometry (closed form, no solver), never taken from what a plan or a model says should happen.

    impact_plan(sm, "ClearSpan")                  what a step of the value moves, resizes, keeps; what it changes that
                                                  was not asked; which notes follow, update or stay; how far it can go
    behaviour_report(sm, {"ClearSpan": 6500})     the change regenerated (nothing committed) and checked, category by
                                                  category — a correct span next to a torn wall is two findings, not one

Categories (each pass / fail / not checked, with what was expected and what was measured):
  requested    every occurrence of a changed value measures the value asked for
  components   each part (named parts, else the closed regions of the structure) stays, translates, rotates, resizes or
               reshapes — and whether its thickness (its thin extent) is kept
  invariants   named sizes nobody changed keep their length; sizes worked out from the change are listed as such
  interfaces   parts that touched still touch
  held         held / existing geometry does not move
  annotations  a leader's tip stays on what it points at, a label stays with its part, a level note follows its line,
               a title or a sheet note does not move, a dimension reads its new length
  views        the views that change, and every shared value measured in each unit that binds it
  validity     no outline collapses, inverts or crosses itself; no value leaves its valid range
"""

from __future__ import annotations

import math

from .regen import apply_transforms, place

FAIL, PASS, SKIP = "fail", "pass", "not checked"


def _seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _segments(it, pts) -> list:
    n = len(pts)
    if it.dxftype == "LINE" and n >= 2:
        return [(pts[0], pts[1])]
    if it.dxftype in ("LWPOLYLINE", "POLYLINE"):
        pairs = list(it.segments) or [(k, k + 1) for k in range(n - 1)]
        return [(pts[i], pts[j]) for i, j in pairs if i < n and j < n]
    return []


def _motion(p0: list, p1: list, tol: float, u: float) -> dict:
    """How a set of points moved: stay, translate (by), rotate (about, by), resize (per axis), reshape."""
    if not p0:
        return {"kind": "stay"}
    deltas = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(p0, p1, strict=False)]
    if all(abs(dx) <= tol and abs(dy) <= tol for dx, dy in deltas):
        return {"kind": "stay"}
    dx0, dy0 = deltas[0]
    if all(abs(dx - dx0) <= tol and abs(dy - dy0) <= tol for dx, dy in deltas):
        return {"kind": "translate", "by_mm": [round(dx0 * u, 2), round(dy0 * u, 2)]}
    k = max(1, len(p0) // 16)
    sample = list(range(0, len(p0), k))[:16]
    rigid = all(abs(math.dist(p0[i], p0[j]) - math.dist(p1[i], p1[j])) <= tol for i in sample for j in sample if i < j)
    if rigid:
        i, j = max(((i, j) for i in sample for j in sample if i < j), key=lambda ij: math.dist(p0[ij[0]], p0[ij[1]]), default=(0, 0))
        a0 = math.atan2(p0[j][1] - p0[i][1], p0[j][0] - p0[i][0])
        a1 = math.atan2(p1[j][1] - p1[i][1], p1[j][0] - p1[i][0])
        return {"kind": "rotate", "angle_deg": round(math.degrees((a1 - a0 + math.pi) % (2 * math.pi) - math.pi), 4)}
    xs0, ys0 = [p[0] for p in p0], [p[1] for p in p0]
    xs1, ys1 = [p[0] for p in p1], [p[1] for p in p1]
    w0, h0, w1, h1 = max(xs0) - min(xs0), max(ys0) - min(ys0), max(xs1) - min(xs1), max(ys1) - min(ys1)
    axes = {}
    if abs(w1 - w0) > tol:
        axes["x"] = round((w1 - w0) * u, 2)
    if abs(h1 - h0) > tol:
        axes["y"] = round((h1 - h0) * u, 2)
    thin0, thin1 = min(w0, h0), (w1 if w0 <= h0 else h1)
    out = {"kind": "resize" if axes else "reshape", "size_mm": {"from": [round(w0 * u, 1), round(h0 * u, 1)], "to": [round(w1 * u, 1), round(h1 * u, 1)]}}
    if axes:
        out["axes"] = axes
    out["thickness_kept"] = abs(thin1 - thin0) <= tol
    return out


def _components(sm, uid: str) -> tuple[dict[str, set[int]], str]:
    """The unit's components, unit-local entity indices: its named parts (leaves), else the closed regions of its structure."""
    u = sm.unit(uid)
    parts = u.prog.intent.get("parts") or {}
    if parts:
        from .assembly import part_entities

        leaf = [n for n in parts if not any(q.parent == n for q in parts.values())]
        return {n: part_entities(u.prog, parts, n) for n in leaf}, "named parts"
    from .topology import of

    topo = of(u.an)
    return {r.id: set(r.items) for r in topo.regions[:300]}, "regions of the structure (no parts named yet)"


def _unit_state(sm, uid: str, changes: dict[str, float]):
    u = sm.unit(uid)
    vals0 = sm._values_for(u, {})
    vals1 = sm._values_for(u, changes)
    an = u.an
    base = {d.id: d.value for d in an.datums.values()}
    dv0, dv1 = u.prog.datum_values(vals0), u.prog.datum_values(vals1)
    d0, d1 = {**base, **dv0}, {**base, **dv1}
    p0, p1 = place(an, d0), place(an, d1)
    full0, full1 = {**u.prog.defaults(), **vals0}, {**u.prog.defaults(), **vals1}
    apply_transforms(u.prog, p0, full0, dv0)  # a turned / moved part is where its transform puts it
    apply_transforms(u.prog, p1, full1, dv1)
    return u, vals0, vals1, d0, d1, p0, p1


def behaviour_report(sm, changes: dict[str, float], sr=None, plans: bool = True) -> dict:
    """The change regenerated (or `sr`, a regeneration already made) and checked category by category. Nothing is committed."""
    sr = sr if sr is not None else sm.preview(changes)
    cats: dict[str, dict] = {
        k: {"status": SKIP, "items": []} for k in ("requested", "components", "invariants", "interfaces", "held", "annotations", "views", "validity")
    }

    def note(cat: str, ok: bool | None, row: dict) -> None:
        c = cats[cat]
        c["items"].append({**row, "status": PASS if ok else FAIL if ok is False else SKIP})
        if ok is False:
            c["status"] = FAIL
        elif ok and c["status"] == SKIP:
            c["status"] = PASS

    touched = sm._touched(changes)
    for uid in sorted(touched):
        u, vals0, vals1, d0, d1, pts0, pts1 = _unit_state(sm, uid, changes)
        an, prog = u.an, u.prog
        um = u.sub.units_mm
        tol = max(an.drawing.tol * 2, 0.5 / max(um, 1e-9))
        changed = {k for k in vals1 if abs(vals1[k] - vals0.get(k, prog.params[k].value)) > 1e-9}
        # requested: each changed value measures what was asked, on every occurrence
        from .plan import pairs_of

        for k in sorted(changed):
            p = prog.params[k]
            pairs = pairs_of(prog, u.answer, k) or ([tuple(p.measures)] if p.measures else [])
            if not pairs:
                note("requested", None, {"unit": uid, "value": k, "why": "no occurrence to measure (a level or a ratio)"})
                continue
            for a, b in pairs:
                if a not in d1 or b not in d1:
                    continue
                got = abs(d1[b] - d1[a]) * um
                note(
                    "requested",
                    abs(got - vals1[k]) <= max(0.5, 1e-4 * abs(vals1[k])),
                    {"unit": uid, "value": k, "between": [a, b], "expected_mm": round(vals1[k], 3), "measured_mm": round(got, 3)},
                )
        # invariants: named sizes not changed keep their length; those that follow the change are worked out from it
        for k, p in prog.params.items():
            if k in changed or not p.measures or p.kind == "level":
                continue
            a, b = p.measures
            if a not in d0 or b not in d1:
                continue
            g0, g1 = abs(d0[b] - d0[a]) * um, abs(d1[b] - d1[a]) * um
            same = abs(g1 - g0) <= max(0.5, 1e-4 * g0)
            if same:
                note("invariants", True, {"unit": uid, "value": k, "kept_mm": round(g0, 1)})
            else:
                named = p.source in ("ai", "person", "dimension")
                note(
                    "invariants",
                    False if named else None,
                    {
                        "unit": uid,
                        "value": k,
                        "from_mm": round(g0, 1),
                        "to_mm": round(g1, 1),
                        "why": "a named size nobody changed has changed: it is set out from what moved"
                        if named
                        else "worked out from the change (a candidate size, not named)",
                    },
                )
        # components
        comps, basis = _components(sm, uid)
        items = an.drawing.items
        moved_any = False
        for name, ents in sorted(comps.items()):
            ents = [i for i in ents if items[i].role.value in ("structural", "reference")]
            if not ents:
                continue
            p0 = [p for i in ents for p in pts0.get(i, items[i].pts)]
            p1 = [p for i in ents for p in pts1.get(i, items[i].pts)]
            m = _motion(p0, p1, tol, um)
            if m["kind"] != "stay":
                moved_any = True
            ok = None if m["kind"] in ("stay", "translate", "rotate") else (True if m.get("thickness_kept", True) else None)
            row = {"unit": uid, "component": name, **m, "entities": [u.back[i] for i in ents][:400]}  # sheet indices: what a view zooms to
            if m["kind"] in ("resize", "reshape") and not m.get("thickness_kept", True):
                row["why"] = "its thin extent changed: if it is a wall or slab, its thickness followed the change"
            note("components", ok if ok is not None else (True if m["kind"] in ("stay", "translate", "rotate") else None), row)
        cats["components"]["basis"] = basis
        if not moved_any and changed:
            cats["components"].setdefault("notes", []).append(f"{uid}: no component moved")
        # interfaces between named parts: what touched still touches
        parts = prog.intent.get("parts") or {}
        if parts:
            from .assembly import interfaces

            for row in interfaces(prog, parts)[:80]:
                a, b = row["parts"]
                ea = [i for i in comps.get(a, ()) if items[i].role.value == "structural"]
                eb = [i for i in comps.get(b, ()) if items[i].role.value == "structural"]
                if not ea or not eb:
                    continue
                segs_a = [s for i in ea for s in _segments(items[i], pts1.get(i, items[i].pts))]
                pts_b = [p for i in eb for p in pts1.get(i, items[i].pts)]
                dmin = min((_seg_dist(p, s[0], s[1]) for p in pts_b for s in segs_a), default=math.inf)
                note(
                    "interfaces",
                    dmin <= tol * 2,
                    {"unit": uid, "parts": [a, b], "kind": row["kind"], "gap_mm": round(dmin * um, 2) if dmin < math.inf else None},
                )
        # held / existing geometry
        held_lines = {d for d, o in prog.origin.items() if o in ("held", "existing")}
        if held_lines:
            moved = [d for d in held_lines if d in d0 and d in d1 and abs(d1[d] - d0[d]) > tol]
            note("held", not moved, {"unit": uid, "held_lines": len(held_lines), "moved": moved[:6]})
        # annotations
        model = an.cache.get("annotations")
        if model is not None:
            _annotations(model, items, pts0, pts1, tol, um, uid, u.back, note)
    # views: what changes where; shared values in every unit
    cats["views"]["changed"] = {k or "(no view)": v for k, v in sorted(sr.by_view.items())}
    for name, per in (sr.measured or {}).items():
        want = changes.get(name)
        for uid, got in per.items():
            note(
                "views",
                want is None or abs(got - want) <= max(0.5, 1e-4 * abs(want)),
                {"shared": name, "unit": uid, "measured_mm": round(got, 2), "expected_mm": want},
            )
    if not sr.measured:
        note("views", None, {"why": "no shared value is bound in more than one unit: each view follows its own values"})
    # validity
    if sr.errors:
        for e in sr.errors[:12]:
            note("validity", False, {"issue": e})
    else:
        note("validity", True, {"issue": "every outline stays valid; every check of the sheet holds"})
    if plans:
        cats["validity"]["warnings"] = sr.warnings[:8]
    failed = [k for k, c in cats.items() if c["status"] == FAIL]
    return {"ok": not failed, "failed": failed, "changes": changes, "categories": cats, "changed_entities": len(sr.changed)}


def _annotations(model, items, pts0, pts1, tol, um, uid, back, note) -> None:
    for a in model.annotations:
        main = a.items[0]
        moved = [i for i in a.items if any(math.dist(p, q) > tol for p, q in zip(pts0.get(i, items[i].pts), pts1.get(i, items[i].pts), strict=False))]
        row = {"unit": uid, "annotation": a.id, "kind": a.kind, "attachment": a.attachment, "text": a.text[:60], "entity": back[main]}
        if a.kind.startswith("dimension"):
            it = items[main]
            if len(it.pts) >= 3:
                p = pts1.get(main, it.pts)
                q0 = math.dist(it.pts[1], it.pts[2]) * um
                q1 = math.dist(p[1], p[2]) * um
                if abs(q1 - q0) > 0.5:
                    note("annotations", True, {**row, "reads": f"{q0:.0f} → {q1:.0f} mm"})
            continue
        if a.attachment in ("view", "sheet", "fixed"):
            if moved:
                note("annotations", False, {**row, "why": f"a {a.attachment}-attached note moved"})
            continue
        if not moved:
            continue
        t = a.targets[0] if a.targets else None
        if a.attachment in ("geometry", "component") and t is not None and t.index is not None:
            tgt = items[t.index]
            segs = _segments(tgt, pts1.get(t.index, tgt.pts))
            anchor0 = a.anchor
            if anchor0 is None or not segs:
                continue
            # the attaching point after the change: the leader's tip, or the note's own anchor carried with it
            k_item = a.items[1] if a.attachment == "geometry" and len(a.items) > 1 else main
            it_k = items[k_item]
            p_after = pts1.get(k_item, it_k.pts)[0]
            d0 = min(_seg_dist(anchor0, *s) for s in _segments(tgt, tgt.pts)) if _segments(tgt, tgt.pts) else 0.0
            d1 = min(
                _seg_dist(p_after if a.attachment == "geometry" else (anchor0[0] + p_after[0] - it_k.pts[0][0], anchor0[1] + p_after[1] - it_k.pts[0][1]), *s)
                for s in segs
            )
            ok = abs(d1 - d0) <= tol * 2
            note(
                "annotations",
                ok,
                {
                    **row,
                    "target": t.ref,
                    "distance_mm": [round(d0 * um, 1), round(d1 * um, 1)],
                    **({} if ok else {"why": "it no longer sits where it pointed / was written"}),
                },
            )
        elif a.attachment == "datum":
            note("annotations", True, {**row, "follows": a.targets[0].ref if a.targets else ""})


def impact_plan(sm, name: str, step: float | None = None) -> dict:
    """Before an edit: what a step of `name` (a shared name or "U….local") moves, resizes and keeps; what else it
    changes; which notes follow, update or stay; how far the value can go — measured on a trial regeneration."""
    cur = sm.current()
    if name not in cur:
        from .crossview import SheetError

        raise SheetError(f"no value {name}")
    v = cur[name]
    dv = step if step else max(abs(v) * 0.05, 10.0)
    trial = behaviour_report(sm, {name: v + dv}, plans=False)
    rng = sm.valid_range(name)
    imp = sm.impact(name, dv)
    comps: dict[str, list[str]] = {"translate": [], "rotate": [], "resize": [], "reshape": [], "stay": []}
    thickness: list[str] = []
    for row in trial["categories"]["components"]["items"]:
        comps.setdefault(row["kind"], []).append(f"{row['unit']}:{row['component']}")
        if row["kind"] in ("resize", "reshape") and not row.get("thickness_kept", True):
            thickness.append(f"{row['unit']}:{row['component']}")
    inv = trial["categories"]["invariants"]["items"]
    ann = trial["categories"]["annotations"]["items"]
    occurrences = [r for r in trial["categories"]["requested"]["items"] if r.get("between")]
    questions = []
    if thickness:
        questions.append(f"{len(thickness)} part(s) change their thin extent with {name} ({', '.join(thickness[:4])}): is that thickness meant to follow?")
    worked = [r for r in inv if r["status"] != PASS]
    if any(r["status"] == FAIL for r in worked):
        questions.append(
            "named sizes nobody asked to change would change: "
            + ", ".join(f"{r['value']} {r['from_mm']}→{r['to_mm']}" for r in worked if r["status"] == FAIL)[:200]
        )
    return {
        "name": name,
        "value": v,
        "step": dv,
        "occurrences": occurrences,
        "views": imp["views"],
        "views_unchanged": imp["stays"],
        "entities": imp["entities"],
        "components": {k: v_ for k, v_ in comps.items() if v_},
        "thickness_changes": thickness,
        "invariants_kept": [r["value"] for r in inv if r["status"] == PASS][:40],
        "worked_out": [{"value": r["value"], "from_mm": r["from_mm"], "to_mm": r["to_mm"]} for r in worked][:20],
        "annotations": {
            "updating": [r for r in ann if r.get("reads")][:20],
            "problems": [r for r in ann if r["status"] == FAIL][:20],
            "following": sum(1 for r in ann if r["status"] == PASS and not r.get("reads")),
        },
        "valid_range": {k: rng[k] for k in ("min", "max", "min_reason", "max_reason") if k in rng},
        "trial_ok": trial["ok"],
        "trial_failed": trial["failed"],
        "questions": questions,
    }
