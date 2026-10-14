"""The sheet workspace behind the CAD page: one SheetModel, and the HTTP routes the page uses.

The page loads the whole sheet's geometry ONCE, then only what a change touches comes back (the entities that moved,
and the ones that move back), so a 20 000-entity sheet stays interactive. Previews never commit; `apply`, renames,
shares, anchors, links and view corrections are transactions with undo / redo.

    GET  /api/sheet                       the views, units, links, shared and local values, what to review
    GET  /api/sheet/geometry              every primitive (once; gzip)
    POST /api/sheet/open?name=…           a DXF (its bytes) — the sheet is read and its views found
    POST /api/sheet/preview  {changes}    regenerated, checked, NOT committed: the entities that would change
    POST /api/sheet/apply    {changes}    committed only if the whole sheet holds
    POST /api/sheet/undo | redo
    GET  /api/sheet/unit?id=…             one unit's values, parts, findings (analysed on first use)
    GET  /api/sheet/param?name=…          what a value moves (per view), how it grows, how far it can go
    POST /api/sheet/share | unshare | rename | anchor | link | view | merge | split
    GET  /api/sheet/proposals?units=…     sizes two views both state
    GET  /api/sheet/export                the edited DXF
    GET  /api/sheet/project               the parametric project (JSON); POST it back to restore
    GET  /api/sheet/status                how far each view, part and value really is (derived from the model, never from a message)
    GET  /api/sheet/baseline[?all=1]      the imported geometry of what has changed (or of everything): the dotted comparison layer
    POST /api/sheet/reset_value {name}    one value back to the imported drawing's (regenerated and checked, or refused)
    POST /api/sheet/reset_drawing {confirm}   the imported state; one undoable step
    POST /api/sheet/prefs                 what a person chose to see (saved with the project)

The agent — ONE instruction, one session (ai/run.py):
    GET  /api/sheet/ai/usage?period=today|all              tokens and cost per model, from the usage ledger
    GET  /api/sheet/ai/library                             the engineering libraries, and the one this sheet's printed words match
    GET  /api/sheet/ai/models                              the models the picker offers (and the default)
    POST /api/sheet/ai/run {instruction, scope, options}   start a run (options.model: one of those models)
    GET  /api/sheet/ai/progress?run=R1&since=n             its events, state, budget, questions, verdict
    POST /api/sheet/ai/continue {run, answers, note}       after it asked, or after a budget pause
    POST /api/sheet/ai/stop | apply | revert {run}
    GET  /api/sheet/ai/runs                                the history; GET /api/sheet/ai/image?run=R1&id=IMG3
"""

from __future__ import annotations

import gzip
import json
import shutil
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs

from .crossview import SheetError, SheetModel, SheetRegen

STATIC = Path(__file__).parent / "static"


def _r(v: float) -> float:
    return round(v, 4)


class SheetSession:
    def __init__(self, path: str | None = None):
        self.lock = threading.RLock()
        self.sm: SheetModel | None = None
        self.shown: set[int] = set()  # entities the page draws changed (the committed state)
        self.opened = 0.0
        self.gem = None  # one Gemini client per sheet: its prompt cache serves the follow-ups
        self.gem_model: str | None = None  # the model the client was made for
        self.gem_factory = None  # a test (or another provider) supplies the model here
        self.gem_per_run = False
        self.pictures = None
        self.runs: dict = {}
        self.run_n = 0
        self.current_run: str | None = None
        if path:
            self.open(path)

    # ── state ─────────────────────────────────────────────────────────────────

    def open(self, path: str) -> dict:
        if self.running():
            raise SheetError("the agent is working on this sheet: stop it first")
        if self.gem is not None:
            self.gem.close()
            self.gem = None
        self.gem_model = None
        t = time.perf_counter()
        self.sm = SheetModel.open(path)
        self.pictures = None
        self.runs, self.current_run, self.run_n = {}, None, 0
        self.shown = set()
        self.opened = time.perf_counter() - t
        return self.summary()

    def _sm(self) -> SheetModel:
        if self.sm is None:
            raise SheetError("open a DXF first")
        return self.sm

    def summary(self) -> dict:
        sm = self._sm()
        lay = sm.layout
        units = []
        for uid, u in sm.units.items():
            units.append({"id": uid, "views": u.views, "built": u.built, "entities": len(u.items), "parametrized": bool(u.answer),
                          "params": len(u.prog.params) if u.built else None, "dropped": u.dropped})
        return {
            "file": Path(sm.path).name, "path": sm.path, "units_mm": sm.dr.units_mm, "extent": sm.dr.extent, "frame": lay.frame,
            "opened_s": round(self.opened, 2), "entities": len(sm.dr.items), "notes": lay.notes + sm.dr.notes,
            "groups": [{**g.to_dict(), "unit": sm.unit_of_view.get(g.id)} for g in lay.groups],
            "furniture": {"frame": lay.frame_items, "rules": lay.rules, "stray": lay.stray, "watermark": lay.watermark},
            "links": sm.links, "unlinked": sorted(list(k) for k in sm.unlinked), "units": units,
            "shared": [{"id": p.id, "name": p.name, "label": p.label, "value": p.value, "unit": p.unit, "evidence": p.evidence,
                        "bindings": [{"unit": b.unit, "param": b.param, "status": b.status, "reason": b.reason, "candidate": b.candidate,
                                      "datums": b.datums, "views": sm.units[b.unit].views if b.unit in sm.units else []} for b in p.bindings]}
                       for p in sm.shared.values()],
            "values": sm.current(), "can_undo": bool(sm.history), "can_redo": bool(sm.future),
            "relations": sm.relations, "questions": sm.questions, "accepted": sorted(list(k) for k in sm.accepted),
            "ai_running": self.running(), "current_run": self.current_run, "prefs": sm.prefs,
        }

    def _prims(self, entities, sr: SheetRegen | None) -> list[dict]:
        """Primitives of these entities, from a regeneration's points (or as drawn)."""
        sm = self._sm()
        from .display import primitives

        units_of = {s: u.sub.units_mm for u in sm.units.values() for s in u.items}
        out = []
        for i in sorted(entities):
            it = sm.dr.items[i]
            if it.dxftype == "INSERT":
                continue
            pts = sr.reg.pts.get(i, it.pts) if sr else it.pts
            radius = sr.reg.radius.get(i) if sr else None
            text = sr.reg.texts.get(i) if sr else None
            for p in primitives(it, pts, radius, text, units_of.get(i, sm.dr.units_mm)):
                out.append(self._compact(p, sm.layout.item_group.get(i, "")))
        return out

    @staticmethod
    def _compact(p: dict, gid: str) -> dict:
        q = {"i": p["i"], "k": p["k"], "r": p.get("role", ""), "l": p.get("layer", ""), "v": gid}
        if "pts" in p:
            q["p"] = [c for xy in p["pts"] for c in (_r(xy[0]), _r(xy[1]))]
        if p.get("closed"):
            q["c"] = 1
        if p.get("dim"):
            q["d"] = 1
        if p["k"] == "t":
            q["at"] = [_r(p["at"][0]), _r(p["at"][1])]
            q["t"] = p.get("text", "")
            q["h"] = p.get("h")
            q["rot"] = p.get("rot") or 0.0
            for k in ("ha", "va", "wf", "ls"):
                if p.get(k) and p[k] not in ("l", "b"):
                    q[k] = p[k]
        if p.get("pattern"):
            q["pat"] = p["pattern"]
        return q

    def geometry(self) -> dict:
        sm = self._sm()
        sr = sm.regenerate()
        self.shown = set(sr.changed)
        return {"prims": self._prims(range(len(sm.dr.items)), sr), "extent": sm.dr.extent, "frame": sm.layout.frame}

    def _commit_delta(self) -> dict:
        """After a committed change: the entities that moved, and those that moved back, as they now stand."""
        sm = self._sm()
        sr = sm.regenerate()
        now = set(sr.changed)
        touched = now | self.shown
        self.shown = now
        return {"delta": self._prims(touched, sr), "errors": sr.errors}

    # ── actions ───────────────────────────────────────────────────────────────

    def preview(self, changes: dict) -> dict:
        sm = self._sm()
        sr = sm.preview({k: float(v) for k, v in changes.items()})
        return {"ok": sr.ok, "errors": sr.errors[:20], "warnings": sr.warnings, "by_view": sr.by_view, "measured": sr.measured,
                "changed": len(sr.changed), "delta": self._prims(set(sr.changed) | self.shown, sr)}

    def apply(self, changes: dict) -> dict:
        sm = self._sm()
        sr = sm.apply({k: float(v) for k, v in changes.items()})
        if not sr.ok:
            return {"ok": False, "errors": sr.errors[:20]}
        return {"ok": True, **self._commit_delta(), "summary": self.summary(), "by_view": sr.by_view}

    def history(self, which: str) -> dict:
        sm = self._sm()
        ok = sm.undo() if which == "undo" else sm.redo()
        return {"ok": ok, **self._commit_delta(), "summary": self.summary()}

    def edit(self, op: str, body: dict) -> dict:
        """The model edits (each one undoable): share, unshare, rename, anchor, link, view, merge, split."""
        sm = self._sm()
        result = None
        if op == "share":
            p = sm.share(body["name"], [tuple(t) for t in body["targets"]], label=body.get("label", ""), evidence=body.get("evidence"),
                         source=body.get("source", "person"))
            result = {"id": p.id, "bindings": [{"unit": b.unit, "status": b.status, "reason": b.reason} for b in p.bindings]}
        elif op == "unshare":
            sm.unshare(body["name"])
        elif op == "rename":
            sm.rename(body["old"], body["new"])
        elif op == "anchor":
            result = sm.anchor(body["name"], body["unit"], body["mode"])
        elif op == "link":
            sm.link(body["a"], body["b"], bool(body["linked"]))
        elif op == "view":
            sm.set_view(body["id"], name=body.get("name"), view_type=body.get("view_type"), kind=body.get("kind"))
        elif op == "merge":
            result = {"id": sm.merge_views(body["ids"])}
        elif op == "split":
            result = {"id": sm.split_view(body["id"], tuple(body["box"]), body.get("name", ""))}
        else:
            raise SheetError(f"no such edit: {op}")
        return {"ok": True, "result": result, **self._commit_delta(), "summary": self.summary()}

    # ── the agent: one instruction, one session (ai/run.py) ─────────────────────

    def running(self) -> bool:
        from .ai.run import ACTIVE

        return any(r.status in ACTIVE for r in self.runs.values())

    def get_gem(self, model: str | None = None):
        """The model: one client per sheet and per chosen model (its prompt cache serves the follow-ups)."""
        if self.gem_factory is not None and self.gem_per_run:
            return self.gem_factory()  # an offline demo: every run gets its own script
        target = model or None
        if self.gem_factory is None and (target is not None or self.gem_model is not None):
            from .ai.vertex import model_choices

            target = target or model_choices()["default"]
        if self.gem is not None and (target is not None or self.gem_model is not None) and self.gem_model != target:
            self.gem.close()  # another model was picked: the old client's caches belong to the old model
            self.gem = None
        if self.gem is None:
            if self.gem_factory is not None:
                self.gem = self.gem_factory()
                self.gem_model = target
            else:
                from .ai.vertex import MODEL_CHOICES, Gemini, config

                choice = next((m for m in MODEL_CHOICES if m["id"] == target), None)
                if choice and choice.get("provider") == "gateway":
                    from .ai.gateway import Gateway, GatewayConfig

                    self.gem = Gateway(GatewayConfig(model=choice["gateway_model"], thinking=choice["thinking"]))
                    self.gem_model = target
                else:
                    cfg = config(target)
                    self.gem = Gemini(cfg)
                    self.gem_model = cfg.model
        return self.gem

    def library_info(self) -> dict:
        """The engineering libraries a run may use, and — from this sheet's own printed words — the one whose cues it matches (with the words).
        A suggestion only: the person's choice goes with the run (options.domain)."""
        from .ai import domain, library

        out, suggested = [], None
        texts = library.drawing_texts(self.sm.dr.items) if self.sm is not None else []
        for name in library.domains():
            lib = library.open_domain(name)
            if lib is None or domain.name_of(name) is None:  # a library works with the domain pack of the same name
                continue
            out.append({"name": name, "title": lib.title, "skills": len(lib.skills)})
            top = lib.discover(texts, top=1) if texts else []
            if top and top[0]["strong"] and suggested is None:
                suggested = {"domain": name, "skill": top[0]["skill"], "score": top[0]["score"], "because": list(dict.fromkeys(b["printed"] for b in top[0]["because"]))}
        return {"domains": out, "suggested": suggested}

    def models(self) -> dict:
        from .ai.vertex import model_choices

        return model_choices()

    def get_pictures(self):
        from .viewimg import Pictures

        if self.pictures is None or self.pictures.sm is not self.sm:
            self.pictures = Pictures(self._sm())
        return self.pictures

    def _run(self, rid: str | None):
        from .ai.run import RunError

        rid = rid or self.current_run
        run = self.runs.get(rid or "")
        if run is None:
            raise RunError(f"no such run: {rid}" if rid else "no run yet")
        return run

    def start_run(self, body: dict) -> dict:
        """ONE instruction (and where it applies) starts a run: the model decides what the task needs. Returns at once; the run
        works in the background and its progress is read with `run_progress`."""
        from .ai.run import RESUMABLE, Run

        sm = self._sm()
        if self.running():
            raise SheetError("the agent is already working on this sheet: stop it, or wait for it")
        for r in self.runs.values():  # a run left waiting is closed by a new one: it was decided on a sheet that is about to change
            if r.status in RESUMABLE:
                r.close("superseded by a newer run")
        self.get_pictures()
        run = Run(self, f"R{self.run_n + 1}", body.get("instruction", ""), body.get("scope"), body.get("options"), parent=body.get("parent"))
        self.run_n += 1  # an id is used up only by a run that exists
        self.runs[run.id] = run
        self.current_run = run.id
        run.start()
        return {"ok": True, "run": run.id, "revision": sm.revision}

    def continue_run(self, body: dict) -> dict:
        run = self._run(body.get("run"))
        if self.running():
            raise SheetError("the agent is already working on this sheet")
        run.resume(answers=body.get("answers"), note=body.get("note", ""), more_turns=body.get("more_turns"))
        self.current_run = run.id
        return {"ok": True, "run": run.id}

    def stop_run(self, body: dict) -> dict:
        run = self._run(body.get("run"))
        run.stop()
        return {"ok": True, "run": run.id, "status": run.status}

    def apply_run(self, body: dict) -> dict:
        run = self._run(body.get("run"))
        v = run.apply_valid()
        return {"ok": True, "run": run.id, "verdict": v, **self._commit_delta(), "summary": self.summary()}

    def revert_run(self, body: dict) -> dict:
        run = self._run(body.get("run"))
        res = run.revert()
        return {"ok": True, "run": run.id, **res, **self._commit_delta(), "summary": self.summary()}

    def run_progress(self, rid: str | None, since: int) -> dict:
        if not self.runs:
            return {"run": None, "status": "idle", "events": [], "next": 0}
        return self._run(rid).progress(since)

    def run_list(self) -> dict:
        """This session's runs (newest first), then the history saved with the project that this session did not make."""
        live = [r.summary() for r in self.runs.values()][::-1]
        have = {r["id"] for r in live}
        saved = [r for r in reversed(self.sm.runs if self.sm else []) if r.get("id") not in have]
        return {"runs": live + saved, "current": self.current_run}

    def run_image(self, rid: str | None, img_id: str) -> bytes | None:
        pics = self.pictures
        if pics is None:
            with self.lock:
                pics = self.get_pictures()
        return pics.png_of(img_id)

    def record_run(self, run) -> None:
        """A finished run goes into the project's history (a log: undo does not touch it)."""
        sm = self._sm()
        sm.runs = [r for r in sm.runs if r.get("id") != run.id or r.get("session") != id(self)] + [{**run.summary(), "session": id(self)}]
        sm.runs = [{k: v for k, v in r.items() if k != "session"} for r in sm.runs][-200:]

    def status(self) -> dict:
        from .status import sheet_status

        active = {}
        for r in self.runs.values():
            active.update(r.active_states())
        return sheet_status(self._sm(), active)

    # ── the baseline, reset and what a person chose to see ──────────────────────

    def baseline(self, everything: bool = False) -> dict:
        """The imported geometry — the dotted layer under the current drawing. By default only what has changed (everything
        else coincides with it); `everything` sends every entity."""
        sm = self._sm()
        sr = sm.regenerate()
        ents = range(len(sm.dr.items)) if everything else sr.changed
        return {"prims": self._prims(ents, None), "changed": len(sr.changed), "revision": sm.revision, "deviation": sm.deviation()}

    def reset_value(self, body: dict) -> dict:
        sm = self._sm()
        res = sm.reset_value(body["name"])
        return {**res, **self._commit_delta(), "summary": self.summary()}

    def reset_drawing(self, body: dict) -> dict:
        if not body.get("confirm"):
            raise SheetError("resetting the drawing returns it to the imported state: say confirm")
        if self.running():
            raise SheetError("the agent is working on this sheet: stop it first")
        sm = self._sm()
        res = sm.reset_drawing()
        return {**res, **self._commit_delta(), "summary": self.summary()}

    def set_prefs(self, body: dict) -> dict:
        sm = self._sm()
        b = body.get("baseline") or {}
        if "on" in b:
            sm.prefs["baseline"]["on"] = bool(b["on"])
        if isinstance(b.get("color"), str) and b["color"].startswith("#") and len(b["color"]) in (4, 7):
            sm.prefs["baseline"]["color"] = b["color"]
        return {"ok": True, "prefs": sm.prefs}

    def unit(self, uid: str) -> dict:
        sm = self._sm()
        u = sm.unit(uid)
        from .graph import affects

        reach = affects(u.prog)
        bound = {b.param: p.name for p in sm.shared.values() for b in p.bindings if b.unit == uid}
        params = []
        from .status import parameters_of

        state = {p["name"]: p["state"] for p in parameters_of(sm, uid)}
        for name, prm in u.prog.params.items():
            r = reach.get(name, {})
            ents = [u.back[k] for k in r.get("entities", [])]
            params.append({"name": name, "key": bound.get(name) or f"{uid}.{name}", "shared": name in bound, "label": prm.label, "state": state.get(name, "named"),
                           "changed": name in sm.values.get(uid, {}),
                           "value": sm.values.get(uid, {}).get(name, prm.value), "drawn": prm.value, "unit": prm.unit, "kind": prm.kind,
                           "source": prm.source, "measures": prm.measures, "confidence": prm.confidence, "evidence": prm.evidence[:4],
                           "occurrences": prm.occurrences, "entities": len(ents), "views": sorted({sm.layout.item_group.get(s, "") for s in ents} - {""}),
                           "parts": r.get("parts", [])[:12]})
        params.sort(key=lambda q: (not q["shared"], q["source"] != "ai", -q["entities"]))
        rep = u.report
        checked = {r["id"]: r for r in u.prog.intent.get("plans", [])}
        plans = [{"id": p.get("id"), "status": p.get("status"), "instruction": p.get("instruction", ""),
                  "driver": (p.get("driver") or {}).get("parameter"), "requested": (p.get("driver") or {}).get("requested_value"),
                  "anchor": {k: (p.get("anchor") or {}).get(k) for k in ("policy", "centre", "source")},
                  "directives": [f"{d['target']}: {d['mode']}" for d in p.get("directives", []) if d.get("status") == "accepted"][:20],
                  "questions": [q["text"] for q in p.get("questions", [])][:6],
                  "checks": (checked.get(p.get("id")) or {}).get("summary"),
                  "failed": [f"{c['check']} {c['target']}: {c['measured']}" for c in (checked.get(p.get("id")) or {}).get("checks", []) if c["status"] == "fail"][:6]}
                 for p in (u.answer or {}).get("plans", [])]
        return {"id": uid, "views": u.views, "params": params, "plans": plans, "relations": [{"name": r.name, "label": r.label, "expr": r.expr} for r in u.prog.relations][:40],
                "components": [{"name": c.name, "type": c.type, "regions": c.regions} for c in u.prog.components],
                "findings": [f.as_dict() for f in (rep.findings if rep else [])][:80], "dropped": u.dropped,
                "candidates": sorted(({"id": c.id, "value": round(c.value * u.sub.units_mm, 1), "kind": c.kind.value, "axes": sorted(c.axes),
                                       "status": c.status.value, "name": c.name, "evidence": [e.kind for e in c.evidence]}
                                      for c in u.an.clusters.values()), key=lambda c: -c["value"])[:200]}

    def param(self, name: str) -> dict:
        """Everything a click on a value shows: what it moves (measured), how it grows, how far it can go, the geometry it belongs to by
        category, what the imported drawing has, where it came from and whether it is validated."""
        sm = self._sm()
        out = {"impact": sm.impact(name)}
        try:
            out["growth"] = sm.growth(name)
        except SheetError as exc:
            out["growth"] = [{"mode": "none", "why": str(exc)}]
        out["range"] = sm.valid_range(name)
        h = sm.highlight(name, out["impact"]["step"])
        out["highlight"] = h
        out["card"] = sm.card(name)
        out["deviation"] = sm.deviation(set(h["drives"]) | set(h["follows"]) | set(h["texts"]))
        return out


def _gzip(handler, body: bytes, ctype: str, extra: dict | None = None) -> None:
    if "gzip" in (handler.headers.get("Accept-Encoding") or "") and len(body) > 4096:
        handler._send(200, gzip.compress(body, 5), ctype, {**(extra or {}), "Content-Encoding": "gzip"})
    else:
        handler._send(200, body, ctype, extra)


def handle(handler, sheet: SheetSession, method: str, url) -> bool:
    """Serve the workspace page and /api/sheet/*; False for any other path (the classic page's routes)."""
    path = url.path
    if method == "GET" and path in ("/", "/workspace", "/index.html"):
        handler._send(200, (STATIC / "workspace.html").read_bytes(), "text/html; charset=utf-8")
        return True
    if not path.startswith("/api/sheet"):
        return False
    q = parse_qs(url.query)
    try:
        if method == "GET":
            if path == "/api/sheet/ai/progress":
                return handler._json(sheet.run_progress(q.get("run", [None])[0], int(q.get("since", ["0"])[0]))) or True
            if path == "/api/sheet/ai/image":
                png = sheet.run_image(q.get("run", [None])[0], q.get("id", [""])[0])
                if png is None:
                    return handler._json({"ok": False, "error": "that picture is no longer kept: ask the agent to look again"}, 404) or True
                return handler._send(200, png, "image/png", {"Cache-Control": "max-age=3600"}) or True
            if path == "/api/sheet/ai/usage":
                from .ai.usage import summary

                return handler._json(summary(q.get("period", ["all"])[0])) or True
            if path == "/api/sheet/ai/library":
                return handler._json(sheet.library_info()) or True
            if path == "/api/sheet/ai/models":
                return handler._json(sheet.models()) or True
        if method == "POST" and path == "/api/sheet/ai/stop":
            body = json.loads(handler._body() or b"{}")
            return handler._json(sheet.stop_run(body)) or True
        with sheet.lock:
            if method == "GET":
                if path == "/api/sheet":
                    return handler._json(sheet.summary() if sheet.sm else {"empty": True}) or True
                if path == "/api/sheet/geometry":
                    return _gzip(handler, json.dumps(sheet.geometry()).encode(), "application/json") or True
                if path == "/api/sheet/unit":
                    return handler._json(sheet.unit(q.get("id", [""])[0])) or True
                if path == "/api/sheet/param":
                    return handler._json(sheet.param(q.get("name", [""])[0])) or True
                if path == "/api/sheet/proposals":
                    units = [u for u in q.get("units", [""])[0].split(",") if u] or None
                    return handler._json({"proposals": sheet._sm().shared_proposals(units)}) or True
                if path == "/api/sheet/ai/runs":
                    return handler._json(sheet.run_list()) or True
                if path == "/api/sheet/status":
                    return handler._json(sheet.status()) or True
                if path == "/api/sheet/delta":
                    return handler._json({"ok": True, **sheet._commit_delta(), "summary": sheet.summary()}) or True
                if path == "/api/sheet/baseline":
                    return handler._json(sheet.baseline(q.get("all", ["0"])[0] == "1")) or True
                if path == "/api/sheet/export":
                    tmpdir = Path(tempfile.mkdtemp())
                    try:
                        out = tmpdir / (Path(sheet._sm().path).stem + "_parametric.dxf")
                        rep = sheet._sm().export(str(out))
                        if rep["audit"]["errors"] or rep["errors"]:
                            return handler._json({"ok": False, "error": "the export did not pass its checks", "report": rep}, 409) or True
                        data = out.read_bytes()
                    finally:
                        shutil.rmtree(tmpdir, ignore_errors=True)
                    return handler._send(200, data, "application/dxf",
                                         {"Content-Disposition": f'attachment; filename="{out.name}"', "X-Export-Report": json.dumps(rep)[:4000]}) or True
                if path == "/api/sheet/project":
                    body = json.dumps(sheet._sm().to_dict(), indent=1, default=list).encode()
                    return handler._send(200, body, "application/json",
                                         {"Content-Disposition": f'attachment; filename="{Path(sheet._sm().path).stem}.autoparam.json"'}) or True
            if method == "POST":
                raw = handler._body()
                if path == "/api/sheet/open":
                    name = q.get("name", ["upload.dxf"])[0]
                    fname = Path(name).name
                    if not fname or fname in (".", ".."):
                        fname = "upload.dxf"
                    tmp = Path(tempfile.mkdtemp()) / fname
                    tmp.write_bytes(raw)
                    return handler._json(sheet.open(str(tmp))) or True
                body = json.loads(raw or b"{}")
                if path == "/api/sheet/preview":
                    return handler._json(sheet.preview(body.get("changes", {}))) or True
                if path == "/api/sheet/apply":
                    return handler._json(sheet.apply(body.get("changes", {}))) or True
                if path in ("/api/sheet/undo", "/api/sheet/redo"):
                    return handler._json(sheet.history(path.rsplit("/", 1)[1])) or True
                if path == "/api/sheet/ai/run":
                    return handler._json(sheet.start_run(body)) or True
                if path == "/api/sheet/ai/continue":
                    return handler._json(sheet.continue_run(body)) or True
                if path == "/api/sheet/ai/apply":
                    return handler._json(sheet.apply_run(body)) or True
                if path == "/api/sheet/ai/revert":
                    return handler._json(sheet.revert_run(body)) or True
                if path == "/api/sheet/reset_value":
                    return handler._json(sheet.reset_value(body)) or True
                if path == "/api/sheet/reset_drawing":
                    return handler._json(sheet.reset_drawing(body)) or True
                if path == "/api/sheet/prefs":
                    return handler._json(sheet.set_prefs(body)) or True
                if path == "/api/sheet/project":
                    if sheet.running():
                        raise SheetError("the agent is working on this sheet: stop it first")
                    tmpdir = Path(tempfile.mkdtemp())
                    try:
                        tmp = tmpdir / "project.json"
                        tmp.write_text(json.dumps(body))
                        sheet.sm = SheetModel.load(str(tmp), dxf=sheet._sm().path)
                    finally:
                        shutil.rmtree(tmpdir, ignore_errors=True)
                    if sheet.gem is not None:
                        sheet.gem.close()
                        sheet.gem = None
                    sheet.gem_model = None
                    sheet.shown = set()
                    sheet.pictures, sheet.runs, sheet.current_run = None, {}, None  # runs belong to the sheet model they worked on
                    return handler._json({"ok": True, "summary": sheet.summary()}) or True
                op = path.rsplit("/", 1)[1]
                return handler._json(sheet.edit(op, body)) or True
    except SheetError as exc:
        handler._json({"ok": False, "error": str(exc)}, 409)
        return True
    except (KeyError, ValueError, TypeError) as exc:  # a malformed request: said, never a crash of the server
        handler._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)
        return True
    handler._json({"ok": False, "error": f"no route {method} {path}"}, 404)
    return True
