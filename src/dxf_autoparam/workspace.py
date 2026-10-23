"""The sheet workspace behind the CAD page: one SheetModel, and the HTTP routes the page uses.

The page loads the whole sheet's geometry ONCE, then only what a change touches comes back (the entities that moved,
and the ones that move back), so a 20 000-entity sheet stays interactive. Previews never commit; `apply`, renames,
shares, anchors, links and view corrections are transactions with undo / redo.

    GET  /api/sheet                       the views, units, links, shared and local values, what to review
    GET  /api/sheet/geometry              every primitive (once; gzip)
    POST /api/sheet/open?name=…[&fresh=1] a DXF (its bytes) — the sheet is read and its views found; work saved for the same drawing is
                                          opened with it (fresh=1: not — it is kept aside under a dated name). The read is outside the sheet lock
    GET  /api/sheet/loading               the drawing being read, if any, and for how long (asked while the open request is out)
    POST /api/sheet/reopen   {fresh}      the open drawing again from its own file (fresh: as drawn, the saved work kept aside)
    POST /api/sheet/preview  {changes}    regenerated, checked, NOT committed: the entities that would change
    POST /api/sheet/apply    {changes[,live]} committed only if the whole sheet holds (live: one person stepping a value — the steps are one undo)
    GET  /api/sheet/original              the entities that differ from the drawing as read, as that drawing has them (the dotted original)
    POST /api/sheet/undo | redo
    GET  /api/sheet/unit?id=…             one unit's values, parts, findings (analysed on first use)
    GET  /api/sheet/param?name=…          what a value moves (per view), how it grows, how far it can go
    POST /api/sheet/share | unshare | rename | anchor | link | view | merge | split
    POST /api/sheet/intent   {unit?}      the design intent derived again (which side of each size stays, decided from the drawing) — one undoable step
    GET  /api/sheet/proposals?units=…     sizes two views both state
    GET  /api/sheet/export                the edited DXF
    GET  /api/sheet/project               the parametric project (JSON); POST it back to restore
    GET  /api/sheet/status                how far each view, part and value really is (derived from the model, never from a message)
    GET  /api/sheet/coverage              what the DXF held and what of it is read, drawn, editable, exported (by type, by handle)
    GET  /api/sheet/agent_notes           the agent's checklist and the facts it recorded (stale ones marked)
    GET  /api/sheet/autosave              where the work is kept, when it was last written, what was opened from there (null: autosave is off)
    GET  /  (and /app/…)                  the interactive workspace (web/, built into static/app); /legacy the previous page
    GET  /api/sheet/entity?i=…            one entity: source handle / block / properties, style, view, unit, set-out lines, parameters
    GET  /api/sheet/resolve?handle=…      a DXF handle → the sheet entities read from it
    GET  /api/sheet/annotations[?view=]   every annotation: kind, what it refers to (ranked evidence), how it behaves
    GET  /api/sheet/layers                layers: CAD properties, contents, views, character; existing / proposed counts
    GET  /api/sheet/statuses              existing / proposed / removed … per entity, with the evidence
    GET  /api/sheet/duplicates[?view=]    entities drawn twice: exact, restyled, near, overlapping (never merged)
    GET  /api/sheet/impact?name=…         before an edit: what a step of the value moves, resizes, keeps, updates
    POST /api/sheet/behaviour {changes}   a change regenerated and checked category by category (nothing committed)
    POST /api/sheet/decide {kind, …}      a semantic decision (existing / proposed status) — undoable, kept with who and why
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
    POST /api/sheet/ai/note {run, note}                    something said while it works: read at its next turn (no stop)
    POST /api/sheet/ai/stop | apply | revert {run}
    GET  /api/sheet/ai/runs                                the history; GET /api/sheet/ai/image?run=R1&id=IMG3
    GET  /api/sheet/ai/requests?run=R1&since=0&limit=50    (&brief=1) every model call: what it was made of, what was the same as the call before, what it cost and
                                                           how much of it the provider cached; &call=57 is that request whole (pictures' bytes left out)
"""

from __future__ import annotations

import gzip
import json
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import cast
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
        self.drawing = None  # the revision of the drawing the page shows: a feature operation (or its undo) changes it, and entity indices with it
        self.opened = 0.0
        self.gem = None  # one Gemini client per sheet: its prompt cache serves the follow-ups
        self.gem_model: str | None = None  # the model the client was made for
        self.gem_factory = None  # a test (or another provider) supplies the model here
        self.gem_per_run = False
        self.autosave = None  # autosave.Autosave: keeps the work on disk while it is made (the server sets it; a test or script does without)
        self.loading: dict | None = None  # the drawing being read right now: {name, since} (read by the page while the request is out)
        self._dims: dict[str, tuple[object, dict]] = {}  # per unit: how many dimensions its values drive, for the program it was measured on (not asked again per step)
        self._opening = threading.Lock()  # one drawing is read at a time
        self.pictures = None
        self.runs: dict = {}
        self.run_n = 0
        self.current_run: str | None = None
        # The resolved CAD styles the page has been sent (colour, linetype dash pattern, lineweight, alpha, font): each
        # primitive names one by index, so a 20k-entity sheet sends a handful of styles, not one per line.
        self.styles: list[dict] = []
        self._style_ix: dict[tuple, int] = {}
        if path:
            self.open(path)

    # ── state ─────────────────────────────────────────────────────────────────

    def open(self, path: str, project: str | None = None, fresh: bool = False, progress=None) -> dict:
        """Read a DXF. With `project`, the saved parametric project opens with it; otherwise the work kept for this same drawing (autosave) does —
        unless `fresh`, which keeps that work aside under a dated name and starts from the drawing as drawn.

        The drawing is read and analysed WITHOUT the sheet lock (a big one takes many seconds, and the page asks other things — and must be able to
        say what is going on — meanwhile); the lock is taken only to put the new sheet in the place of the old. One drawing is read at a time."""
        from . import autosave as keep

        if self.running():
            raise SheetError("the agent is working on this sheet: stop it first")
        if not self._opening.acquire(blocking=False):
            raise SheetError("a drawing is already being read: wait for it")
        try:
            self.loading = {"name": Path(path).name, "since": time.time()}
            t = time.perf_counter()
            sm, restored = None, None
            if project:
                sm = SheetModel.load(project, dxf=path)
                restored = {"from": "a project file", "path": project, "revision": sm.revision, "problems": []}
            elif self.autosave is not None and not fresh:
                sm, restored = keep.restore(path, self.autosave.root)
            sm = sm or SheetModel.open(path)
            derived = sm.derive_missing_intent(progress)  # saved work from before the design intent existed: which side of each size stays, worked out (no undo step of the person's)
            with self.lock:
                if self.running():  # an agent started while the drawing was being read
                    raise SheetError("the agent is working on this sheet: stop it first")
                if self.autosave is not None and fresh and not project:
                    # a clean start keeps the saved work aside — at the swap, not before the read: what the old sheet changed in the last second is written
                    # first (so it is what is kept), and nothing of the old sheet is written over the clean one afterwards
                    self.autosave.flush()
                    kept = keep.set_aside(path, self.autosave.root)
                    restored = {"from": None, "kept_as": str(kept) if kept else None, "problems": []}
                if self.gem is not None:
                    self.gem.close()
                    self.gem = None
                self.gem_model = None
                self.sm = sm
                if self.autosave is not None:
                    self.autosave.restored = restored if restored and (restored.get("from") or restored.get("problems")) else None
                    self.autosave.rebase()
                    if derived:  # what was worked out is part of the work now: written, so that the next opening does not work it out again
                        self.autosave.touch()
                self.pictures = None
                self.runs, self.current_run, self.run_n = {}, None, 0
                self.shown = set()
                self.styles, self._style_ix = [], {}
                self.opened = time.perf_counter() - t
                return self.summary()
        finally:
            self.loading = None
            self._opening.release()

    def reopen(self, fresh: bool = False) -> dict:
        """The open drawing again, from its own file. With `fresh`: from the drawing as drawn, the saved work kept aside under a dated name (nothing is lost)."""
        with self.lock:
            path = self._sm().path
        return self.open(path, fresh=fresh)

    def loading_status(self) -> dict:
        """What the page shows while a drawing is read: the name and how long it has taken (read without the sheet lock, so it can always be asked)."""
        cur = self.loading
        return {"loading": cur is not None, **({"name": cur["name"], "elapsed_s": round(time.time() - cur["since"], 1)} if cur else {})}

    def _sm(self) -> SheetModel:
        if self.sm is None:
            raise SheetError("open a DXF first")
        return self.sm

    def summary(self) -> dict:
        sm = self._sm()
        lay = sm.layout
        units = []
        for uid, u in sm.units.items():
            units.append(
                {
                    "id": uid,
                    "views": u.views,
                    "built": u.built,
                    "entities": len(u.items),
                    "parametrized": bool(u.answer),
                    "params": (
                        (len(u.prog.params) if u.prog is not None else None)
                        if u.built
                        else None
                    ),
                    "kept_as_drawn": len((u.answer or {}).get("frozen", [])),
                    "dropped": u.dropped,
                }
            )
        from .frames import frames as view_frames

        frames = view_frames(sm)  # each view in its own frame (mm from its own origin, RL where it states a level); units not read yet: their box
        return {
            "file": Path(sm.path).name, "path": sm.path, "units_mm": sm.dr.units_mm, "extent": sm.dr.extent, "frame": lay.frame,
            "opened_s": round(self.opened, 2), "entities": len(sm.dr.items), "notes": lay.notes + sm.dr.notes,
            "groups": [{**g.to_dict(), "unit": sm.unit_of_view.get(g.id), **({"local": frames.get(g.id)} if g.id in frames else {})} for g in lay.groups],
            "furniture": {"frame": lay.frame_items, "rules": lay.rules, "stray": lay.stray, "watermark": lay.watermark},
            "links": sm.links, "unlinked": sorted(list(k) for k in sm.unlinked), "units": units,
            "shared": [{"id": p.id, "name": p.name, "label": p.label, "value": p.value, "unit": p.unit, "evidence": p.evidence,
                        "bindings": [{"unit": b.unit, "param": b.param, "status": b.status, "reason": b.reason, "candidate": b.candidate,
                                      "datums": b.datums, "views": sm.units[b.unit].views if b.unit in sm.units else []} for b in p.bindings]}
                       for p in sm.shared.values()],
            "values": sm.current(), "can_undo": bool(sm.history), "can_redo": bool(sm.future),
            "relations": sm.relations, "questions": sm.questions, "accepted": sorted(list(k) for k in sm.accepted),
            "ai_running": self.running(), "current_run": self.current_run, "prefs": sm.prefs, "revision": sm.revision,
            "autosave": self.autosave.status() if self.autosave is not None else None,
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
            if pts is None:
                continue
            if sr and i in sr.reg.absent:  # not drawn at these values: the page drops what it drew for it (no points, nothing to draw)
                out.append({"i": i, "k": "p", "r": it.role.value, "l": it.layer, "v": sm.layout.item_group.get(i, ""), "gone": 1})
                continue
            radius = sr.reg.radius.get(i) if sr else None
            text = sr.reg.texts.get(i) if sr else None
            turn = sr.reg.turns.get(i, 0.0) if sr else 0.0
            for p in primitives(it, pts, radius, text, units_of.get(i, sm.dr.units_mm), turn):
                out.append(self._compact(p, sm.layout.item_group.get(i, "")))
        return out

    def _style(self, st: dict) -> int:
        key = (st.get("color"), st.get("fg"), st.get("alpha"), st.get("lw"), st.get("lt"), tuple(st.get("dash") or ()), st.get("font", ""))
        ix = self._style_ix.get(key)
        if ix is None:
            ix = self._style_ix[key] = len(self.styles)
            q = {"c": st.get("color", "#ffffff"), "w": st.get("lw", 0.25), "lt": st.get("lt", "CONTINUOUS")}
            if st.get("fg"):
                q["fg"] = 1
            if st.get("alpha", 1.0) < 1.0:
                q["a"] = st["alpha"]
            if st.get("dash"):
                q["d"] = [_r(v) for v in st["dash"]]
            if st.get("font"):
                q["f"] = st["font"]
            self.styles.append(q)
        return ix

    def _compact(self, p: dict, gid: str) -> dict:
        q = {"i": p["i"], "k": p["k"], "r": p.get("role", ""), "l": p.get("layer", ""), "v": gid}
        if "pts" in p:
            q["p"] = [c for xy in p["pts"] for c in (_r(xy[0]), _r(xy[1]))]
        if p["k"] == "m":
            q["m"] = [_r(c) for seg in p["segs"] for c in seg]
        if p.get("closed"):
            q["c"] = 1
        if p.get("dim"):
            q["d"] = 1
        if p.get("s"):
            q["s"] = self._style(p["s"])
        if p.get("tag") in ("arrow", "hatch", "band", "text"):
            q["tag"] = p["tag"]
        if p.get("mask"):
            q["mask"] = 1
        if p.get("fill"):
            q["fill"] = p["fill"]
        if p["k"] == "t":
            q["at"] = [_r(p["at"][0]), _r(p["at"][1])]
            q["t"] = p.get("text", "")
            q["h"] = p.get("h")
            q["rot"] = p.get("rot") or 0.0
            for k in ("ha", "va", "wf", "ls", "width", "oblique"):
                if p.get(k) and p[k] not in ("l", "b"):
                    q[k] = p[k]
        if p.get("pattern"):
            q["pat"] = p["pattern"]
        return q

    def geometry(self) -> dict:
        sm = self._sm()
        sr = sm.regenerate()
        self.shown = set(sr.changed)
        self.drawing = sm.dr
        prims = self._prims(range(len(sm.dr.items)), sr)
        return {"prims": prims, "styles": self.styles, "extent": sm.dr.extent, "frame": sm.layout.frame}

    def _commit_delta(self) -> dict:
        """After a committed change: the entities that moved, and those that moved back, as they now stand."""
        sm = self._sm()
        if self.drawing is not None and sm.dr is not self.drawing:  # another revision: no entity of the page's is this one's — it loads the sheet again
            self.drawing, self.shown, self.pictures = sm.dr, set(), None
            return {"reload": True, "delta": [], "errors": []}
        sr = sm.regenerate()
        now = set(sr.changed)
        touched = now | self.shown
        self.shown = now
        # `differs`: every entity that now differs from the drawing as read — the page keeps the original of those (fetched once per entity) and
        # drops the rest, so the dashed original shows exactly what changed without being read again at every step
        return {"delta": self._prims(touched, sr), "styles": self.styles, "errors": sr.errors, "differs": sorted(now)}

    # ── actions ───────────────────────────────────────────────────────────────

    def preview(self, changes: dict) -> dict:
        sm = self._sm()
        asked = {k: float(v) for k, v in changes.items()}
        sr = sm.preview(asked)
        delta = self._prims(set(sr.changed) | self.shown, sr)
        return {"ok": sr.ok, "errors": sr.errors[:20], "warnings": sr.warnings, "by_view": sr.by_view, "measured": sr.measured,
                "changed": len(sr.changed), "delta": delta, "styles": self.styles, **({} if sr.ok else {"failures": sm.explain(sr, asked)[:20]})}

    def apply(self, changes: dict, live: bool = False) -> dict:
        sm = self._sm()
        sr = sm.apply({k: float(v) for k, v in changes.items()}, live=live)
        if not sr.ok:
            return {"ok": False, "errors": sr.errors[:20], "failures": sr.failures[:20]}
        return {"ok": True, **self._commit_delta(), "summary": self.summary(), "by_view": sr.by_view, "warnings": sr.warnings[:8]}

    def original(self) -> dict:
        """The entities that now differ from the drawing as it was read, as that drawing has them (the dotted original a person can show)."""
        self._sm()
        return {"prims": self._prims(self.shown, None), "styles": self.styles}

    def settle_options(self, name: str, unit: str) -> dict:
        """The ways to settle a value whose direction of growth could not be decided, each tried for real (SheetModel.settle_options): nothing changes."""
        if self.running():
            raise SheetError("the agent is working on this sheet: stop it first")
        return self._sm().settle_options(name, unit)

    def history(self, which: str) -> dict:
        sm = self._sm()
        ok = sm.undo() if which == "undo" else sm.redo()
        return {"ok": ok, **self._commit_delta(), "summary": self.summary()}

    def edit(self, op: str, body: dict) -> dict:
        """The model edits (each one undoable): share, unshare, rename, anchor, intent, settle, unsettle, link, view, merge, split."""
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
        elif op == "intent":
            if self.running():
                raise SheetError("the agent is working on this sheet: stop it first")
            result = sm.resolve_intent(body.get("unit"))
        elif op in ("settle", "unsettle"):
            if self.running():
                raise SheetError("the agent is working on this sheet: stop it first")
            if op == "settle":
                result = sm.settle(body["name"], body["unit"], body["choice"], bool(body.get("discard_values")))
            else:
                result = sm.unsettle(body["unit"], body["choice"])
        elif op == "link":
            sm.link(body["a"], body["b"], bool(body["linked"]))
        elif op == "view":
            sm.set_view(body["id"], name=body.get("name"), view_type=body.get("view_type"), kind=body.get("kind"))
        elif op == "merge":
            result = {"id": sm.merge_views(body["ids"])}
        elif op == "split":
            result = {"id": sm.split_view(body["id"], tuple(body["box"]), body.get("name", ""))}
        elif op in ("purge_generic", "release_frozen", "unlock_part"):
            if self.running():
                raise SheetError("the agent is working on this sheet: stop it first")
            if op == "purge_generic":
                result = sm.purge_unclaimed_generic_values(body.get("unit"), bool(body.get("dry_run")))
            elif op == "release_frozen":
                result = sm.release_frozen(body["unit"], body.get("names"))
            else:
                result = sm.unlock_part(body["unit"], body["part"])
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
                from .ai.vertex import Gemini, choice_for, config

                choice = choice_for(target) if target else None
                if choice and choice.get("provider") in ("gateway", "tokenharbor"):
                    from .ai.gateway import Gateway, GatewayConfig

                    self.gem = Gateway(GatewayConfig(model=choice["gateway_model"], thinking=choice["thinking"], provider=choice["provider"], price=choice.get("price")))
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

    def production_info(self) -> dict:
        """The production rule engines as this sheet stands: whether the knowledge and the bridge are available, the families the sheet's printed
        words point at, and every binding kept on the sheet evaluated now (what the agent's bind_production_model kept; read only)."""
        from .ai import library
        from .production import manifest, service

        st = service.status()
        if not st.get("knowledge"):
            return {"available": False, **st}
        texts = library.drawing_texts(self.sm.dr.items) if self.sm is not None else []
        return {"available": st["bridge"]["available"], "status": st, "match_this_drawing": manifest.knowledge().discover(texts) if texts else [],
                "bindings": self.sm.domain_report() if self.sm is not None and self.sm.domain else []}

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

    def note_run(self, body: dict) -> dict:
        """What the person says while the agent works: read at its next turn (no stop, no lost call)."""
        return self._run(body.get("run")).say(body.get("note", ""))

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

    def run_requests(self, rid: str | None, since: int = 0, limit: int = 50, brief: bool = False) -> dict:
        if not self.runs:
            return {"run": None, "requests": [], "next": 0, "totals": {}}
        return self._run(rid).requests_listing(since, limit, brief)

    def run_request_payload(self, rid: str | None, n: int) -> str | None:
        return self._run(rid).request_payload(n) if self.runs else None

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
        return {"prims": self._prims(ents, None), "styles": self.styles, "changed": len(sr.changed), "revision": sm.revision, "deviation": sm.deviation()}

    def agent_notes(self) -> dict:
        """The agent's checklist and the facts it recorded (stale ones marked) — what the agent panel shows."""
        from .ai.understanding_tools import learned_now, notes_of

        sm = self._sm()
        return {"checklist": notes_of(sm)["checklist"], "learned": learned_now(sm), "revision": sm.revision}

    def coverage(self) -> dict:
        """What the file held and what of it is read, drawn, editable and exportable (fidelity.coverage_report)."""
        sm = self._sm()
        return {"file": Path(sm.path).name, **sm.dr.coverage}

    def entity(self, i: int) -> dict:
        from .understanding import entity_record

        return entity_record(self._sm(), i)

    def resolve(self, handle: str) -> dict:
        from .understanding import resolve_handle

        return {"handle": handle, "entities": resolve_handle(self._sm(), handle)}

    def annotations(self, view: str | None = None) -> dict:
        from .understanding import sheet_annotations

        rows = sheet_annotations(self._sm())
        if view:
            rows = [a for a in rows if a.get("view") == view]
        kinds: dict[str, int] = {}
        for a in rows:
            kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
        return {"annotations": rows, "kinds": kinds, "revision": self._sm().revision}

    def layers(self) -> dict:
        from .understanding import layers, statuses

        st = statuses(self._sm())
        return {"layers": layers(self._sm()), "status": {"counts": st["counts"], "learned_colours": st["learned_colours"]}}

    def statuses(self) -> dict:
        from .understanding import statuses

        st = statuses(self._sm())
        return {"counts": st["counts"], "learned_colours": st["learned_colours"],
                "entities": {str(i): {"status": v["status"], "evidence": v["evidence"][:3]} for i, v in st["entities"].items()}}

    def duplicates(self, view: str | None = None) -> dict:
        from .understanding import duplicates

        return duplicates(self._sm(), view)

    def impact(self, name: str, step: float | None = None) -> dict:
        from .behaviour import impact_plan

        return impact_plan(self._sm(), name, step)

    def behaviour(self, changes: dict) -> dict:
        from .behaviour import behaviour_report

        return behaviour_report(self._sm(), {k: float(v) for k, v in changes.items()})

    def decide(self, body: dict) -> dict:
        """A semantic decision a person makes (one undoable step): an existing / proposed status for a layer, a colour or
        entities — kept with who and why; the analyses read it from then on."""
        sm = self._sm()
        kind = body.get("kind")
        if kind != "status":
            raise SheetError(f"unknown decision {kind!r} (status)")
        status = body.get("status")
        from .layers import STATUS

        if status not in STATUS:
            raise SheetError(f"status must be one of {', '.join(STATUS)}")
        dec = {"by": body.get("by", "entities"), "key": body.get("key"), "entities": [int(i) for i in body.get("entities", [])],
               "status": status, "who": body.get("who", "person"), "why": (body.get("why") or "").strip() or "set in the workspace",
               "revision": sm.revision}
        if dec["by"] in ("layer", "colour") and not dec["key"]:
            raise SheetError("a layer or colour decision names the layer / colour (key)")
        sm._push()
        sm.semantics.setdefault("status", []).append(dec)
        return {"ok": True, "decision": dec, "summary": self.summary()}

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

    def _dimension_drive(self, uid: str, u) -> dict:
        """What the page shows of how parametric a unit is. It depends on the unit's program (its parts and values, at the drawn sizes), not on the sizes a
        person has stepped them to, so it is measured once per program: stepping a value re-reads the unit at every step."""
        from .status import dimension_drive

        cached = self._dims.get(uid)
        if cached is None or cached[0] is not u.prog:
            cached = (u.prog, dimension_drive(u.prog))
            self._dims[uid] = cached
        return cached[1]

    def unit(self, uid: str) -> dict:
        sm = self._sm()
        u = sm.unit(uid)
        assert u.prog is not None
        assert u.an is not None
        from .generic import is_generated
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
                           "source": prm.source, "generic": prm.source != "ai" and is_generated(name),  # the engine's own measurement, nobody named it
                           "measures": prm.measures, "confidence": prm.confidence, "evidence": prm.evidence[:4],
                           "occurrences": prm.occurrences, "entities": len(ents), "views": sorted({sm.layout.item_group.get(s, "") for s in ents} - {""}),
                           "parts": r.get("parts", [])[:12]})
        params.sort(key=lambda q: (not q["shared"], q["source"] != "ai", -q["entities"]))
        measured = self._measured(u)
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
        return cast(
            dict[str, object],
            {
                "id": uid,
                "revision": sm.revision,
                "views": u.views,
                "params": params,
                "measured": measured,
                "frozen": list((u.answer or {}).get("frozen", []))[:600],
                "settled": list({s["choice"]: {"choice": s["choice"], "title": s["title"], "kind": s["kind"]} for s in (u.answer or {}).get("settled", [])}.values()),
                "plans": plans,
                "dimensions": self._dimension_drive(uid, u) if u.answer else None,
                "relations": [
                    {"name": r.name, "label": r.label, "expr": r.expr}
                    for r in u.prog.relations
                ][:40],
                "components": self._components(u),
                "findings": [f.as_dict() for f in (rep.findings if rep else [])][:80],
                "dropped": u.dropped,
                "candidates": sorted(
                    (
                        {
                            "id": c.id,
                            "value": round(c.value * u.sub.units_mm, 1),
                            "kind": c.kind.value,
                            "axes": sorted(c.axes),
                            "status": c.status.value,
                            "name": c.name,
                            "evidence": [e.kind for e in c.evidence],
                        }
                        for c in u.an.clusters.values()
                    ),
                    key=lambda c: -c["value"],
                )[:200],
            },
        )

    @staticmethod
    def _measured(u) -> list[dict]:
        """The named quantities that are measured, not inputs: a size of work kept as drawn, a size the set-out fixes at both ends, a sum the agent
        wrote down. Each says what it is measured between and which part it belongs to (so the page can offer to unlock a held part)."""
        from .program import ExprError

        out = []
        assert u.prog is not None
        for r in u.prog.relations:
            if r.name.startswith("R_"):  # the engine's own sums of sizes: not something a person names
                continue
            try:
                value = u.prog.relation_value(r)
            except ExprError:
                continue
            ends = [x.strip() for x in (r.check or "").split(" - ")] if r.check else []
            part = next((c for c in u.prog.components if len(ends) == 2 and ends[0] in c.datums and ends[1] in c.datums), None)
            out.append({"name": r.name, "label": r.label or r.name, "value": value, "unit": "mm", "expr": r.expr, "between": ends if len(ends) == 2 else None,
                        "part": part.name if part else None, "held": bool(part and part.held), "existing": bool(part and part.existing)})
        return out

    @staticmethod
    def _components(u) -> list[dict]:
        """The unit's parts as the page lists them: the tree (parent, level), existing or not, the sheet entities each is drawn with (a click shows
        them), and what the drawing's own labels on its outline call it — with the doubt when they say something else (ai/labels.py)."""
        from .ai import labels
        from .assembly import part_entities

        parts = u.prog.intent.get("parts") or {}
        rows = {c.get("name"): c for c in (u.answer or {}).get("components", [])}
        pointed = labels.pointed_labels(u.an)
        out = []
        for c in u.prog.components:
            row = rows.get(c.name, {"name": c.name, "type": c.type})
            ents = sorted(u.back[i] for i in part_entities(u.prog, parts, c.name)) if c.name in parts else []
            said = labels.part_labels(u.prog, parts, c.name, pointed) if c.name in parts else []
            leaf = c.level != "assembly" and not any(p.parent == c.name for p in parts.values())
            doubt = labels.conflict(row, said) if leaf else None
            out.append({"name": c.name, "type": c.type, "regions": c.regions, "parent": c.parent, "level": c.level, "existing": c.existing,
                        "entities": ents[:4000], "drawing_says": [lab["text"] for lab in said[:3]],
                        **({"label_doubt": labels.sentence(doubt)} if doubt else {}),
                        **({"label_checked": row["label_checked"]} if row.get("label_checked") else {})})
        return out

    def param(self, name: str) -> dict:
        """Everything a click on a value shows: what it moves (measured), how it grows, how far it can go, the geometry it belongs to by
        category, what the imported drawing has, where it came from and whether it is validated."""
        sm = self._sm()
        impact = sm.impact(name)
        out: dict[str, object] = {"impact": impact}
        try:
            out["growth"] = sm.growth(name)
        except SheetError as exc:
            out["growth"] = [{"mode": "none", "why": str(exc)}]
        out["range"] = sm.valid_range(name)
        h = sm.highlight(name, impact["step"])
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
    app = STATIC / "app"
    if method == "GET" and path in ("/", "/workspace", "/index.html", "/app", "/app/"):
        # the interactive workspace (web/, built into static/app) when it is built; the previous page otherwise and at /legacy
        if (app / "index.html").exists() and path != "/workspace":
            handler._send(200, (app / "index.html").read_bytes(), "text/html; charset=utf-8", {"Cache-Control": "no-cache"})
        else:
            handler._send(200, (STATIC / "workspace.html").read_bytes(), "text/html; charset=utf-8")
        return True
    if method == "GET" and path == "/legacy":
        handler._send(200, (STATIC / "workspace.html").read_bytes(), "text/html; charset=utf-8")
        return True
    if method == "GET" and path.startswith("/app/"):
        target = (app / path[len("/app/"):]).resolve()
        if not target.is_relative_to(app.resolve()) or not target.is_file():  # nothing outside the built app is served
            handler._send(404, b"not found", "text/plain")
            return True
        ctype = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".woff2": "font/woff2", ".json": "application/json", ".html": "text/html; charset=utf-8"}.get(target.suffix, "application/octet-stream")
        handler._send(200, target.read_bytes(), ctype, {"Cache-Control": "max-age=31536000, immutable" if "/assets/" in path else "no-cache"})
        return True
    if not path.startswith("/api/sheet"):
        return False
    q = parse_qs(url.query)
    try:
        if method == "GET":
            if path == "/api/sheet/ai/progress":
                return handler._json(sheet.run_progress(q.get("run", [None])[0], int(q.get("since", ["0"])[0]))) or True
            if path == "/api/sheet/ai/requests":
                if q.get("call"):
                    body = sheet.run_request_payload(q.get("run", [None])[0], int(q["call"][0]))
                    if body is None:
                        return handler._json({"ok": False, "error": "that request is no longer kept whole: only the last few calls are"}, 404) or True
                    return handler._send(200, body.encode(), "application/json") or True
                return handler._json(sheet.run_requests(q.get("run", [None])[0], int(q.get("since", ["0"])[0]), int(q.get("limit", ["50"])[0]), q.get("brief", ["0"])[0] == "1")) or True
            if path == "/api/sheet/ai/image":
                png = sheet.run_image(q.get("run", [None])[0], q.get("id", [""])[0])
                if png is None:
                    return handler._json({"ok": False, "error": "that picture is no longer kept: ask the agent to look again"}, 404) or True
                return handler._send(200, png, "image/png", {"Cache-Control": "max-age=3600"}) or True
            if path == "/api/sheet/autosave":
                return handler._json(sheet.autosave.status() if sheet.autosave is not None else None) or True
            if path == "/api/sheet/loading":  # no sheet lock: it is asked while a drawing is being read
                return handler._json(sheet.loading_status()) or True
            if path == "/api/sheet/ai/usage":
                from .ai.usage import summary

                return handler._json(summary(q.get("period", ["all"])[0])) or True
            if path == "/api/sheet/ai/library":
                return handler._json(sheet.library_info()) or True
            if path == "/api/sheet/ai/models":
                return handler._json(sheet.models()) or True
            if path == "/api/sheet/production":
                with sheet.lock:
                    return handler._json(sheet.production_info()) or True
        if method == "POST" and path == "/api/sheet/ai/stop":
            body = json.loads(handler._body() or b"{}")
            return handler._json(sheet.stop_run(body)) or True
        if method == "POST" and path == "/api/sheet/ai/note":  # like stop, outside the sheet lock: the person can always speak to a run that is busy
            body = json.loads(handler._body() or b"{}")
            try:
                return handler._json(sheet.note_run(body)) or True
            except SheetError as exc:
                return handler._json({"ok": False, "error": str(exc)}, 409) or True
        if method == "POST" and path == "/api/sheet/open":  # the drawing is read before the sheet lock is taken (SheetSession.open)
            raw = handler._body()
            name = q.get("name", ["upload.dxf"])[0]
            fname = Path(name).name
            if not fname or fname in (".", ".."):
                fname = "upload.dxf"
            tmp = Path(tempfile.mkdtemp()) / fname
            tmp.write_bytes(raw)
            return handler._json(sheet.open(str(tmp), fresh=q.get("fresh", ["0"])[0] == "1")) or True
        if method == "POST" and path == "/api/sheet/reopen":
            body = json.loads(handler._body() or b"{}")
            return handler._json(sheet.reopen(bool(body.get("fresh")))) or True
        with sheet.lock:
            if method == "GET":
                if path == "/api/sheet":
                    return handler._json(sheet.summary() if sheet.sm else {"empty": True}) or True
                if path == "/api/sheet/geometry":
                    return _gzip(handler, json.dumps(sheet.geometry()).encode(), "application/json") or True
                if path == "/api/sheet/original":
                    return _gzip(handler, json.dumps(sheet.original()).encode(), "application/json") or True
                if path == "/api/sheet/unit":
                    return handler._json(sheet.unit(q.get("id", [""])[0])) or True
                if path == "/api/sheet/param":
                    return handler._json(sheet.param(q.get("name", [""])[0])) or True
                if path == "/api/sheet/settle":
                    return handler._json(sheet.settle_options(q.get("name", [""])[0], q.get("unit", [""])[0])) or True
                if path == "/api/sheet/proposals":
                    units = [u for u in q.get("units", [""])[0].split(",") if u] or None
                    return handler._json({"proposals": sheet._sm().shared_proposals(units)}) or True
                if path == "/api/sheet/ai/runs":
                    return handler._json(sheet.run_list()) or True
                if path == "/api/sheet/status":
                    return handler._json(sheet.status()) or True
                if path == "/api/sheet/coverage":
                    return handler._json(sheet.coverage()) or True
                if path == "/api/sheet/agent_notes":
                    return handler._json(sheet.agent_notes()) or True
                if path == "/api/sheet/entity":
                    return handler._json(sheet.entity(int(q.get("i", ["-1"])[0]))) or True
                if path == "/api/sheet/resolve":
                    return handler._json(sheet.resolve(q.get("handle", [""])[0])) or True
                if path == "/api/sheet/annotations":
                    return handler._json(sheet.annotations(q.get("view", [None])[0])) or True
                if path == "/api/sheet/layers":
                    return handler._json(sheet.layers()) or True
                if path == "/api/sheet/statuses":
                    return handler._json(sheet.statuses()) or True
                if path == "/api/sheet/duplicates":
                    return handler._json(sheet.duplicates(q.get("view", [None])[0])) or True
                if path == "/api/sheet/impact":
                    step = q.get("step", [None])[0]
                    return handler._json(sheet.impact(q.get("name", [""])[0], float(step) if step else None)) or True
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
                body = json.loads(raw or b"{}")
                if path == "/api/sheet/preview":
                    return handler._json(sheet.preview(body.get("changes", {}))) or True
                if path == "/api/sheet/apply":
                    return handler._json(sheet.apply(body.get("changes", {}), live=bool(body.get("live")))) or True
                if path == "/api/sheet/behaviour":
                    return handler._json(sheet.behaviour(body.get("changes", {}))) or True
                if path == "/api/sheet/decide":
                    return handler._json(sheet.decide(body)) or True
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
        handler._json({"ok": False, "error": str(exc), **({"failures": exc.failures[:20]} if exc.failures else {})}, 409)
        return True
    except (KeyError, ValueError, TypeError, IndexError) as exc:  # a malformed request: said, never a crash of the server
        handler._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)
        return True
    handler._json({"ok": False, "error": f"no route {method} {path}"}, 404)
    return True
