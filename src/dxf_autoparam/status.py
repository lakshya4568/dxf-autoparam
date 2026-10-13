"""How far each view, part and value of the sheet really is — derived from the model, never from a message.

The page used to say "Done" when a run stopped, whatever the engine had checked: a refused edit, a value still without
its binding and a measurement still running could sit next to a success banner. Here there is one source: the sheet's own
state (answers, programs, plans and their measured checks, shared bindings) and the verdicts of the runs that worked on it.
A state is claimed only when what it names has been measured:

  not_analyzed           no parametrization of this view yet (the engine may have read it; nobody has decided anything)
  analyzing              a run is reading it now
  components_identified  its parts are named; no value of its own yet
  awaiting_user          a plan or a run waits for a decision
  parametrizing          a run is naming its values now
  partial                values exist but something named by the work is unfinished (a problem, a failed check, a refusal)
  validated              it builds without problems, regenerates at the current values, every accepted plan measured right,
                         every shared value still drives it
  complete               validated, and the last run that worked on it ended complete (its own criteria all met)
  refused / failed       the last run's edits were refused / the run failed, and nothing since has repaired it

    report = sheet_status(sm, active={"U01_02": "parametrizing"})
    report["sentence"]       # "Half elevation: validated. Half section: validated. Plan view: not yet analyzed. 3 relationships require review."
"""

from __future__ import annotations

from .graph import affects

STATE_WORDS = {"not_analyzed": "not yet analyzed", "analyzing": "being analyzed", "components_identified": "parts identified",
               "awaiting_user": "waiting for your decision", "parametrizing": "being parametrized", "partial": "partly done",
               "validated": "validated", "complete": "complete", "refused": "refused", "failed": "failed"}


def last_run(sm, uid: str) -> dict | None:
    return next((r for r in reversed(sm.runs) if uid in (r.get("units") or []) and r.get("kind", "run") == "run"), None)


def unit_checks(sm, uid: str) -> dict:
    """What the sheet can say about one parametrized unit right now — each item measured or read off the engine's report."""
    u = sm.units[uid]
    prog = u.prog
    problems = [f"{e['code']} {e['item']}: {e['message']}"[:160] for e in (u.report.errors() if u.report else [])]
    plans = (u.answer or {}).get("plans", [])
    plan_rows = {r["id"]: r for r in (prog.intent.get("plans", []) if prog else [])}
    open_q = [q["text"][:140] for p in plans if p.get("status") != "accepted" for q in p.get("questions", [])]
    failed = []
    for p in plans:
        row = plan_rows.get(p.get("id")) or {}
        if p.get("status") == "accepted":
            failed += [f"{c['check']} {c['target']}: {c['measured']}"[:160] for c in row.get("checks", []) if c.get("status") == "fail"]
            failed += [str(x)[:160] for x in (row.get("compiled") or {}).get("problems") or []]
    sr = sm.regenerate(units={uid})
    shared_bad = [f"{p.name}: {b.status}" for p in sm.shared.values() for b in p.bindings if b.unit == uid and b.status != "drives"]
    return {"problems": problems, "open_questions": open_q, "failed_checks": failed, "regenerates": sr.ok, "regen_errors": sr.errors[:3],
            "shared_not_driving": shared_bad, "plans": len(plans), "plans_accepted": sum(1 for p in plans if p.get("status") == "accepted")}


def unit_state(sm, uid: str, active: dict | None = None) -> tuple[str, dict]:
    u = sm.units[uid]
    active = active or {}
    if uid in active:
        return active[uid], {}
    last = last_run(sm, uid)
    if not u.answer:
        if last and last.get("status") in ("failed",):
            return "failed", {"why": (last.get("verdict") or {}).get("remaining", [])[:2]}
        return "not_analyzed", {}
    sm.unit(uid)
    c = unit_checks(sm, uid)
    parts = u.answer.get("components") or []
    named = [p for p in u.prog.params.values() if p.source == "ai"]
    detail = dict(c)
    if c["open_questions"] or (last and last.get("status") == "awaiting_user"):
        return "awaiting_user", detail
    clean = not c["problems"] and not c["failed_checks"] and c["regenerates"] and not c["shared_not_driving"]
    if last and last.get("status") == "failed" and not clean:
        return "failed", detail
    if last and (last.get("verdict") or {}).get("refused") and not clean:
        return "refused", detail
    if not named:
        return ("components_identified" if parts else "not_analyzed"), detail
    if not clean:
        return "partial", detail
    if last and last.get("status") == "completed":
        return "complete", detail
    return "validated", detail


def components_of(sm, uid: str) -> list[dict]:
    u = sm.units[uid]
    if not u.answer:
        return []
    sm.unit(uid)
    reach = affects(u.prog)
    parts_hit = {part: n for p, r in reach.items() if p in u.prog.params and u.prog.params[p].source == "ai" for part in r["parts"]
                 for n in [p]}
    asked = {str(q.get("about", "")).split(":", 1)[-1] for p in (u.answer.get("plans") or []) if p.get("status") != "accepted" for q in p.get("questions", [])}
    held = {d["target"]: d["mode"] for p in (u.answer.get("plans") or []) if p.get("status") == "accepted" for d in p.get("directives", [])
            if d.get("kind") == "part" and d.get("status") == "accepted" and d.get("mode") in ("exclude", "no_parameter")}
    out = []
    for c in u.answer.get("components", []):
        n = c.get("name")
        if n in held or c.get("existing") or c.get("parametrize") is False:
            state = "excluded"
        elif n in asked:
            state = "unresolved"
        elif n in parts_hit:
            state = "bound"
        else:
            state = "identified"
        out.append({"name": n, "type": c.get("type", ""), "state": state, "level": c.get("level", "component"), "parent": c.get("parent"),
                    "why": held.get(n, "") or ("existing work, kept as built" if c.get("existing") else "")})
    return out


def parameters_of(sm, uid: str) -> list[dict]:
    u = sm.units[uid]
    if not u.built:
        return []
    shared = {b.param: p.name for p in sm.shared.values() for b in p.bindings if b.unit == uid}
    reach = affects(u.prog)
    last = last_run(sm, uid)
    refused = {str(r.get("item")) for r in ((last or {}).get("verdict") or {}).get("refused", [])}
    out = []
    for name, p in u.prog.params.items():
        n_ent = len(reach.get(name, {}).get("entities", []))
        state = "refused" if name in refused else "bound" if (p.source in ("ai", "person") and n_ent) else "found" if p.source in ("geometry", "dimension") else "named"
        out.append({"name": name, "key": shared.get(name) or f"{uid}.{name}", "state": state, "source": p.source, "entities": n_ent,
                    "changed": name in sm.values.get(uid, {}), "shared": name in shared})
    return out


def sheet_status(sm, active: dict | None = None) -> dict:
    """Per view, unit, part and value, and overall — one report, one source."""
    active = active or {}
    units = {}
    for uid in sm.units:
        state, detail = unit_state(sm, uid, active)
        units[uid] = {"id": uid, "views": sm.units[uid].views, "state": state, "label": STATE_WORDS[state], "detail": detail,
                      "components": components_of(sm, uid) if sm.units[uid].answer else [],
                      "last_run": (last_run(sm, uid) or {}).get("id")}
    views = []
    for g in sm.layout.views():
        uid = sm.unit_of_view.get(g.id)
        st = units[uid] if uid else None
        views.append({"id": g.id, "name": g.name or g.id, "unit": uid, "state": st["state"] if st else "not_analyzed",
                      "label": st["label"] if st else STATE_WORDS["not_analyzed"]})
    by_state: dict[str, int] = {}
    for v in views:
        by_state[v["state"]] = by_state.get(v["state"], 0) + 1
    open_q = sum(len(u["detail"].get("open_questions", [])) for u in units.values())
    refused = sum(len(((last_run(sm, uid) or {}).get("verdict") or {}).get("refused", [])) for uid in units)
    failed_checks = sum(len(u["detail"].get("failed_checks", [])) for u in units.values())
    parts = [c for u in units.values() for c in u["components"]]
    params = [p for uid in units if sm.units[uid].built for p in parameters_of(sm, uid) if p["source"] == "ai"]
    plans = [p for u in sm.units.values() for p in (u.answer or {}).get("plans", [])]
    sentence = " ".join(f"{v['name']}: {v['label']}." for v in views)
    review = open_q + failed_checks + refused
    if review:
        sentence += f" {review} item{'s' if review != 1 else ''} require review."
    done = [v for v in views if v["state"] in ("validated", "complete")]
    overall = ("not_started" if all(v["state"] == "not_analyzed" for v in views) else
               "complete" if views and len(done) == len(views) and not review else
               "in_progress" if any(v["state"] in ("analyzing", "parametrizing") for v in views) else "partial")
    sentence += {"complete": " Everything is validated.", "partial": " The parametrization is partial.", "in_progress": " Work is in progress.",
                 "not_started": " Nothing is parametrized yet."}[overall]
    return {"revision": sm.revision, "overall": overall, "views": views, "units": units, "by_state": by_state,
            "counts": {"views": len(views), "components": len(parts), "parameters_named": len(params), "parameters_bound": sum(1 for p in params if p["state"] == "bound"),
                       "plans_accepted": sum(1 for p in plans if p.get("status") == "accepted"), "plans_total": len(plans),
                       "questions_open": open_q, "failed_checks": failed_checks, "refused": refused},
            "sentence": sentence}
