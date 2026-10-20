"""The demo app: open a DXF, parametrize it (geometry engine, then Gemini + validator), edit, export.

    uv run dxf-autoparam serve [drawing.dxf]        → http://127.0.0.1:8765

The page computes no geometry: everything it shows comes from the engine.
"""

from __future__ import annotations

import errno
import json
import signal
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .analyse import analyse
from .cadjson import cad_json
from .display import scene
from .dxf_read import read_dxf
from .dxf_write import audit, write_dxf
from .graph import affects, dependency_graph
from .learn import learn
from .program import ExprError, Program
from .regen import regenerate_program
from .topology import of as topology_of
from .validator import Report, baseline, check_regeneration
from .views import detect_views, restrict

STATIC = Path(__file__).parent / "static"


class Session:
    def __init__(self, path: str | None):
        self.lock = threading.Lock()
        self.path = path
        self.region: tuple[float, float, float, float] | None = None
        self.views: list[dict] = []
        self.prog: Program | None = None
        self.report: Report | None = None
        self.values: dict[str, float] = {}
        self.mode = "geometry"  # geometry | ai
        self.ai_info: dict | None = None
        self.hold_existing = False
        self.selection: dict | None = None  # None: the AI's recommendation
        # One Gemini client per drawing / view: its prompt cache serves the follow-ups ("revise") on the same facts.
        self.gem = None
        self.instructions = ""  # the person's standing instructions for Gemini
        self.history: list[dict] = []  # what was asked of Gemini, in order
        self.checking: Program | None = None  # the program whose background regeneration check is running
        self.pending: str | None = None  # a drawing to open when the classic page first asks for it
        self.job: dict = {"running": False, "events": [], "error": None, "kind": None, "started": 0.0, "stop": threading.Event()}
        if path:
            self.open(path)

    def _drop_gemini(self) -> None:
        if self.gem is not None:
            self.gem.close()
            self.gem = None

    def busy(self) -> bool:
        return bool(self.job["running"])

    def require_path(self) -> str:
        if self.path is None:
            raise RuntimeError("no drawing is open")
        return self.path

    def require_program(self) -> Program:
        if self.prog is None:
            raise RuntimeError("no program is loaded")
        return self.prog
    def open(self, path: str) -> None:
        self._drop_gemini()
        self.history = []
        self.path = path
        self.region = None
        dr, _ = read_dxf(path)
        self.views = detect_views(dr)
        self.baseline(drawing=dr)  # the drawing just read: a big sheet takes seconds to read again

    def baseline(self, selection: dict | None = None, drawing=None) -> None:
        if self.path is None and drawing is None:
            raise RuntimeError("no drawing is open")
        dr = (
            drawing
            if drawing is not None and not self.region
            else read_dxf(self.path or "")[0]
        )
        if self.region:
            restrict(dr, self.region)
        an = analyse(dr)
        self.report = Report()
        self.prog = baseline(an, rep=self.report, selection=selection)
        self._check_later(self.prog, self.report)
        self.values = self.prog.defaults()
        self.mode = "geometry"
        self.ai_info = None
        self.selection = selection

    def _check_later(self, prog: Program, rep: Report) -> None:
        """The ±10 % regeneration check of every value (V5/V8) runs after the drawing is shown: on a big sheet it is
        hundreds of regenerations, and nothing on screen waits for it. Its findings join the report when it finishes,
        if the drawing is still the one it checked."""
        self.checking = prog

        def work() -> None:
            found = Report()
            try:
                check_regeneration(prog, found)
            except Exception:  # noqa: BLE001 — a background check's boundary: logged, the drawing stays usable
                traceback.print_exc()
            with self.lock:
                if self.prog is prog:
                    rep.findings.extend(found.findings)
                    for k, v in found.rejected.items():
                        rep.rejected[k] = rep.rejected.get(k, 0) + v
                    self.checking = None

        threading.Thread(target=work, daemon=True, name="regeneration-check").start()

    def set_region(self, region) -> None:
        self._drop_gemini()  # other facts, other prompt cache
        self.region = region
        self.baseline()

    def stop_ai(self) -> bool:
        """Ask the running job to stop: it does at Gemini's next streamed message."""
        if not self.busy():
            return False
        self.job["stop"].set()
        self.job["events"].append({"kind": "note", "text": "stopping at Gemini's next message…", "t": round(time.time() - self.job["started"], 1)})
        return True

    def start_ai(self, kind: str, rounds: int = 2, instructions: str | None = None, request: str = "") -> None:
        """Run Gemini in the background ("run": a fresh parametrization following the instructions; "revise": the
        current answer changed as the person asks). Progress — thought summaries, calls, each round's verdict — is
        collected in self.job for the page to follow."""
        from .ai.agent import agent_parametrize
        from .ai.vertex import Gemini, GeminiStopped

        if self.busy():
            raise RuntimeError("Gemini is already working on this drawing")
        if kind == "revise" and not (self.mode == "ai" and self.ai_info):
            raise RuntimeError("there is no Gemini answer to revise yet: run Gemini first")
        if instructions is not None and kind == "run":
            self.instructions = instructions
        job = {"running": True, "events": [], "error": None, "kind": kind, "started": time.time(), "stop": threading.Event()}
        self.job = job

        def push(event: dict) -> None:
            if len(job["events"]) < 4000:
                job["events"].append({**event, "t": round(time.time() - job["started"], 1)})

        if self.path is None:
            raise RuntimeError("no drawing is open")
        path, region, hold, standing = self.path, self.region, self.hold_existing, self.instructions
        previous = (self.ai_info or {}).get("answer")

        def work() -> None:
            try:
                if self.gem is None:
                    self.gem = Gemini()
                log = lambda *a: push({"kind": "log", "text": " ".join(str(x) for x in a)})
                # the tool-using agent: small checked edits instead of one big answer (ai_parametrize / ai_refine remain for scripts)
                prog, rep, info = agent_parametrize(path, region=region, instructions=standing, hold_existing=hold, gem=self.gem,
                                                    on_event=push, stop=job["stop"].is_set, log=log,
                                                    **({"start": previous, "request": request} if kind == "revise" else {}))
                info["instructions"] = standing
                with self.lock:
                    self.prog, self.report, self.ai_info = prog, rep, info
                    self.values = prog.defaults()
                    self.mode = "ai"
                    self.selection = None
                    self.history.append({"kind": kind, "text": standing if kind == "run" else request, "at": time.strftime("%H:%M"),
                                         "rejected": sum(rep.rejected.values()), "tokens_in": info["tokens_in"], "tokens_out": info["tokens_out"]})
                push({"kind": "done", "accepted": rep.accepted, "rejected": rep.rejected, "tokens_in": info["tokens_in"],
                      "tokens_out": info["tokens_out"], "tokens_cached": info.get("tokens_cached", 0), "seconds": info["seconds"]})
            except GeminiStopped:
                push({"kind": "stopped", "text": "Stopped. Nothing changed: the parametrization you had is kept. "
                      "(Tokens Gemini generated before the stop are billed.)"})
            except Exception as exc:  # noqa: BLE001 — the job boundary: traceback logged, the error shown in the app
                traceback.print_exc()
                job["error"] = f"{type(exc).__name__}: {exc}"
                push({"kind": "error", "text": job["error"]})
            finally:
                job["running"] = False

        threading.Thread(target=work, daemon=True, name=f"gemini-{kind}").start()

    def load_answer(self, answer_path: str) -> None:
        """A saved Gemini answer (e.g. from `dxf-autoparam ai --answer-out`), validated again — no AI call."""
        self.ai_info = {"answer": json.loads(Path(answer_path).read_text()), "usage": [], "seconds": 0, "tokens_in": 0, "tokens_out": 0}
        self.mode = "ai"
        self.selection = None
        self.reapply()

    def reapply(self) -> None:
        """The validated answer again, with the person's current choices — no new AI call."""
        from .ai.parametrize import reapply

        if self.mode == "ai" and self.ai_info:
            if self.path is None:
                raise RuntimeError("no drawing is open")
            self.prog, self.report = reapply(self.path, self.ai_info["answer"], self.region, hold_existing=self.hold_existing,
                                             selection=self.selection)
            self.values = self.prog.defaults()
        else:
            self.baseline(self.selection)

    def set_hold_existing(self, on: bool) -> None:
        self.hold_existing = on
        if self.mode == "ai":
            self.reapply()

    def set_selection(self, selection: dict | None) -> None:
        """Which parts are parametric, which values stay as drawn, which constraints are dropped."""
        self.selection = selection
        self.reapply()

    # ── payloads ──────────────────────────────────────────────────────────────

    def geometry(self, values: dict[str, float]) -> tuple[list[dict], list[str], dict]:
        if self.prog is None:
            raise RuntimeError("no program is loaded")
        r = regenerate_program(self.prog, values)
        return scene(self.prog.analysis, r.pts, r.radius, r.texts), r.issues, r.texts

    def state(self) -> dict:
        prog = self.prog
        if prog is None:
            raise RuntimeError("no program is loaded")
        an = prog.analysis
        u = an.drawing.units_mm
        reach = affects(prog)
        parts = prog.intent.get("parts") or {}
        topo = topology_of(an)
        params = []
        for p in prog.params.values():
            named = p.source == "ai" or p.kind == "level"
            params.append({
                "name": p.name, "label": p.label, "value": p.value, "unit": p.unit, "kind": p.kind, "component": p.component or ("Levels" if p.kind == "level" else ""),
                "named": named, "source": p.source, "confidence": p.confidence, "occurrences": p.occurrences, "evidence": p.evidence[:4], "note": p.note,
                # a big sheet: a size can move thousands of entities × hundreds of sizes (15 MB) — long lists are fetched on hover
                "influence": ents if len(ents := reach.get(p.name, {}).get("entities", [])) <= 300 else None, "influence_n": len(ents),
                "parts": (pp := reach.get(p.name, {}).get("parts", []))[:12], "parts_n": len(pp),
                "relations": reach.get(p.name, {}).get("relations", []), "texts": len(reach.get(p.name, {}).get("texts", [])),
            })
        params.sort(key=lambda q: (not q["named"], q["component"], -q["influence_n"]))
        rep = self.report or Report()
        return {
            "file": Path(self.require_path()).name,
            "mode": self.mode,
            "region": self.region,
            "views": self.views,
            "units_mm": u,
            "structure": prog.structure,
            "components": [
                {
                    "name": c.name,
                    "type": c.type,
                    "description": c.description,
                    "level": c.level,
                    "parent": c.parent,
                    "regions": c.regions,
                    "existing": c.existing,
                    "parametrize": c.parametrize,
                    "held": c.held,
                    "confidence": c.confidence,
                    "evidence": c.evidence,
                    "items": sorted(
                        set().union(
                            *(
                                topo.by_id()[r].items
                                for r in c.regions
                                if r in topo.by_id()
                            )
                        )
                        if c.regions
                        else set()
                    ),
                }
                for c in prog.components
            ],
            "regions": [
                {
                    "id": r.id,
                    "inside": r.inside,
                    "items": sorted(r.items),
                    "width": r.bbox[2] - r.bbox[0],
                    "height": r.bbox[3] - r.bbox[1],
                    "fill": r.pattern,
                    "parent": r.parent,
                }
                for r in topo.regions
            ],
            "hold_existing": self.hold_existing,
            "instructions": self.instructions,
            "history": self.history,
            "ai_job": {
                "running": self.busy(),
                "kind": self.job["kind"],
                "events": len(self.job["events"]),
                "error": self.job["error"],
                "stopping": self.job["stop"].is_set(),
            },
            "thoughts": [
                {
                    "label": u.get("label"),
                    "model": u.get("model"),
                    "thinking": u.get("thinking"),
                    "cached": u.get("cached"),
                    "prompt_cache": u.get("prompt_cache"),
                    "thoughts": u.get("thoughts", []),
                }
                for u in (self.ai_info or {}).get("usage", [])
            ],
            "selection": prog.intent.get("selection") or self.selection or {},
            "intent": {k: v for k, v in prog.intent.items() if k not in ("parts",)},
            "part_names": sorted(parts),
            "parameters": params,
            "relations": [
                {
                    "name": r.name,
                    "label": r.label,
                    "expr": r.expr,
                    "enforced": r.enforced,
                    "dimensioned": r.dimensioned,
                    "check": r.check,
                }
                for r in prog.relations
                if not r.name.startswith("R_")
            ][:30]
            + [
                {
                    "name": r.label,
                    "label": "worked out",
                    "expr": r.expr,
                    "enforced": True,
                    "dimensioned": r.dimensioned,
                    "check": r.check,
                }
                for r in prog.relations
                if r.name.startswith("R_")
            ][:30],
            "formulas_ai": [
                {"datum": d, "expr": e}
                for d, e in prog.formulas.items()
                if prog.origin.get(d) == "ai"
            ],
            "validation": {
                "accepted": rep.accepted,
                "rejected": rep.rejected,
                "findings": [f.as_dict() for f in rep.findings][:60],
                "checking": self.checking is not None and self.checking is self.prog,
            },
            "ai": (
                {
                    k: v
                    for k, v in (self.ai_info or {}).items()
                    if k in ("usage", "seconds", "tokens_in", "tokens_out")
                }
                if self.ai_info
                else None
            ),
            "reader_notes": an.drawing.notes + an.notes,
            "unsupported": an.drawing.unsupported,
            "entities": len(an.drawing.items),
        }

    def relation_values(self, values: dict[str, float]) -> list[dict]:
        if self.prog is None:
            raise RuntimeError("no program is loaded")
        out = []
        for r in self.prog.relations:
            name = r.name if not r.name.startswith("R_") else r.label
            try:
                out.append({"name": name, "value": self.prog.relation_value(r, values)})
            except (ExprError, ArithmeticError, KeyError) as exc:  # shown as not computable, never silently dropped
                out.append({"name": name, "value": None, "error": f"{type(exc).__name__}: {exc}"})
        return out


def make_handler(session: Session, sheet=None):
    from .workspace import SheetSession, handle

    if sheet is None:
        sheet = SheetSession()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # The page reloaded or moved on before the answer arrived; nothing to send it to.
                pass

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length", 0) or 0)
            return self.rfile.read(n) if n else b""

        def do_GET(self):
            url = urlparse(self.path)
            if handle(self, sheet, "GET", url):  # the sheet workspace (the main page) and /api/sheet/*
                return
            try:
                if url.path == "/classic":  # the single-view page, with its Gemini panel
                    return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                if url.path == "/api/state":
                    with session.lock:
                        if session.prog is None and session.pending:  # opened on first use: the workspace read it already
                            session.open(session.pending)
                            session.pending = None
                        if session.prog is None:
                            return self._json({"empty": True})
                        st = session.state()
                        geom, issues, _ = session.geometry(session.values)
                        st.update(geometry=geom, values=session.values, issues=issues, relation_values=session.relation_values(session.values))
                        return self._json(st)
                if url.path == "/api/influence":
                    name = parse_qs(url.query).get("name", [""])[0]
                    with session.lock:
                        prog = session.require_program()
                        return self._json(
                            {
                                "name": name,
                                "entities": affects(prog)
                                .get(name, {})
                                .get("entities", []),
                            }
                        )
                if url.path == "/api/validation":  # light: the page follows the background check without the drawing
                    with session.lock:
                        rep = session.report or Report()
                        return self._json({"accepted": rep.accepted, "rejected": rep.rejected, "findings": [f.as_dict() for f in rep.findings][:60],
                                           "checking": session.checking is not None and session.checking is session.prog})
                if url.path == "/api/ai/progress":
                    since = int(parse_qs(url.query).get("since", ["0"])[0])
                    job = session.job
                    return self._json({"running": job["running"], "kind": job["kind"], "error": job["error"], "stopping": job["stop"].is_set(),
                                       "events": job["events"][since:], "next": len(job["events"])})
                if url.path == "/api/answer.json":  # the AI's answer as validated: re-open later with serve --answer
                    with session.lock:
                        body = json.dumps((session.ai_info or {}).get("answer") or {}, indent=1).encode()
                    return self._send(200, body, "application/json", {"Content-Disposition": 'attachment; filename="gemini-answer.json"'})
                if url.path == "/api/program.json":
                    with session.lock:
                        body = json.dumps(
                            session.require_program().to_json(), default=str, indent=1
                        ).encode()
                    return self._send(200, body, "application/json", {"Content-Disposition": 'attachment; filename="parametric-program.json"'})
                if url.path in ("/api/cad.json", "/api/graph.json"):
                    with session.lock:
                        prog = session.require_program()
                        doc = (
                            cad_json(prog.analysis, prog)
                            if url.path == "/api/cad.json"
                            else dependency_graph(prog)
                        )
                        body = json.dumps(doc, default=str, indent=1).encode()
                    name = Path(session.require_path()).stem + (
                        "_cad.json" if url.path == "/api/cad.json" else "_graph.json"
                    )
                    return self._send(200, body, "application/json", {"Content-Disposition": f'attachment; filename="{name}"'})
                if url.path == "/api/export.dxf":
                    q = parse_qs(url.query)
                    with session.lock:
                        prog = session.require_program()
                        vals = {
                            **session.values,
                            **{
                                k: float(v)
                                for k, v in json.loads(
                                    q.get("values", ["{}"])[0]
                                ).items()
                                if k in prog.params
                            },
                        }
                        reg = regenerate_program(prog, vals)
                        tmp = Path(tempfile.mkdtemp()) / "regenerated.dxf"
                        write_dxf(prog, reg, str(tmp))
                        name = Path(session.require_path()).stem + "_parametric.dxf"
                    return self._send(200, tmp.read_bytes(), "application/dxf", {"Content-Disposition": f'attachment; filename="{name}"'})
            except Exception as exc:  # noqa: BLE001 — the request boundary: traceback logged, the error returned to the page
                traceback.print_exc()
                return self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            return self._send(404, b"not found", "text/plain")

        def do_POST(self):
            url = urlparse(self.path)
            if handle(self, sheet, "POST", url):
                return
            try:
                if url.path == "/api/upload":
                    name = parse_qs(url.query).get("name", ["upload.dxf"])[0]
                    fname = Path(name).name
                    if not fname or fname in (".", ".."):
                        fname = "upload.dxf"
                    tmp = Path(tempfile.mkdtemp()) / fname
                    tmp.write_bytes(self._body())
                    if session.busy():
                        return self._json({"ok": False, "error": "Gemini is working on this drawing; wait for it to finish"}, 409)
                    with session.lock:
                        session.open(str(tmp))
                    return self._json({"ok": True})
                if url.path == "/api/learn":
                    name = parse_qs(url.query).get("name", ["edited.dxf"])[0]
                    fname = Path(name).name
                    if not fname or fname in (".", ".."):
                        fname = "edited.dxf"
                    tmp = Path(tempfile.mkdtemp()) / fname
                    tmp.write_bytes(self._body())
                    with session.lock:
                        lesson = learn(
                            session.require_path(), str(tmp), session.require_program()
                        )
                    return self._json({"ok": True, "lesson": lesson})
                body = json.loads(self._body() or b"{}")
                if url.path == "/api/selection":
                    with session.lock:
                        session.set_selection(body.get("selection"))
                    return self._json({"ok": True})
                if url.path == "/api/regen":
                    with session.lock:
                        prog = session.require_program()
                        vals = dict(session.values)
                        for k, v in body.get("values", {}).items():
                            if k in prog.params:
                                vals[k] = float(v)
                        geom, issues, _ = session.geometry(vals)
                        if not issues:
                            session.values = vals
                        return self._json({"ok": not issues, "issues": issues, "values": vals, "geometry": geom,
                                           "relation_values": session.relation_values(vals)})
                if url.path == "/api/region":
                    if session.busy():
                        return self._json({"ok": False, "error": "Gemini is working on this view; wait for it to finish"}, 409)
                    with session.lock:
                        if body.get("view") is not None:
                            session.set_region(tuple(session.views[int(body["view"])]["bbox"]))
                        else:
                            session.set_region(tuple(body["region"]) if body.get("region") else None)
                    return self._json({"ok": True})
                if url.path == "/api/ai/stop":
                    return self._json({"ok": True, "stopping": session.stop_ai()})
                if url.path in ("/api/ai", "/api/ai/revise"):
                    with session.lock:
                        if url.path == "/api/ai":
                            session.start_ai("run", rounds=int(body.get("rounds", 2)), instructions=str(body.get("instructions", "")))
                        else:
                            request = str(body.get("request", "")).strip()
                            if not request:
                                return self._json({"ok": False, "error": "say what Gemini should change"}, 400)
                            session.start_ai("revise", rounds=int(body.get("rounds", 2)), request=request)
                    return self._json({"ok": True, "started": True})
                if url.path == "/api/hold-existing":
                    with session.lock:
                        session.set_hold_existing(bool(body.get("on")))
                    return self._json({"ok": True})
                if url.path == "/api/geometry-only":
                    if session.busy():
                        return self._json({"ok": False, "error": "Gemini is working; wait for it to finish"}, 409)
                    with session.lock:
                        session.baseline()
                    return self._json({"ok": True})
                if url.path == "/api/audit":
                    with session.lock:
                        reg = regenerate_program(session.prog, session.values)
                        tmp = Path(tempfile.mkdtemp()) / "check.dxf"
                        rep = write_dxf(session.prog, reg, str(tmp))
                    return self._json({"write": rep, "audit": audit(str(tmp))})
            except Exception as exc:  # noqa: BLE001 — the request boundary: traceback logged, the error returned to the page
                traceback.print_exc()
                return self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            return self._send(404, b"not found", "text/plain")

    return Handler


def _say(message: str) -> None:
    try:
        print(message, flush=True)
    except OSError:  # the terminal is gone (it was closed): the message has nowhere to go, and the work is already saved
        return


def _end_like_ctrl_c() -> None:
    """Closing the terminal (SIGHUP) or `kill` (SIGTERM) end the server the way Ctrl+C does, so the work is saved first. A SIGHUP that was set to be
    ignored (nohup) stays ignored: whoever started the server that way wants it to outlive its terminal."""
    def stop(_signum, _frame) -> None:
        raise SystemExit(0)

    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None and signal.getsignal(sig) == signal.SIG_DFL:
            signal.signal(sig, stop)


def serve(path: str | None, domain: str | None = None, host: str = "127.0.0.1", port: int = 8765, answer: str | None = None,
          project: str | None = None, autosave: bool = True, fresh: bool = False, state_dir: str | None = None) -> None:
    from . import autosave as keep
    from .workspace import SheetSession

    if answer and path:
        session = Session(path)
        session.load_answer(answer)
    else:
        session = Session(None)
        session.pending = path  # the classic page opens it when it is first used
    sheet = SheetSession()
    if autosave:  # the work is kept on disk while it is made, and opened again with the same drawing
        sheet.autosave = keep.Autosave(sheet, root=Path(state_dir).expanduser() if state_dir else None)
    if path:  # a saved parametric project (parts, sizes, plans) opens with its drawing; else the work kept for it
        sheet.open(path, project=project, fresh=fresh, progress=_say)
        info = sheet.autosave.restored if sheet.autosave is not None else None
        if info and info.get("from"):
            _say(f"opened the saved work on this drawing ({info['from']}): revision {info.get('revision')}")
        elif info and info.get("kept_as"):
            _say(f"starting from the drawing as drawn; the saved work is kept as {info['kept_as']}")
        for problem in (info or {}).get("problems", []):
            _say(f"could not open saved work: {problem}")
    if sheet.autosave is not None:
        sheet.autosave.start()
        _say(f"the work is kept in {sheet.autosave.root or keep.state_dir()}")
    for candidate in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer((host, candidate), make_handler(session, sheet))
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            _say(f"port {candidate} is in use, trying {candidate + 1}")
    else:
        raise SystemExit(f"no free port between {port} and {port + 19}; pass --port")
    if sheet.autosave is not None:
        sheet.autosave.announce(candidate)  # the work of this drawing is this server's: another one can tell it is alive by its port
    _end_like_ctrl_c()  # before the address is announced: whoever reads it may close the terminal that very moment
    _say(f"dxf-autoparam on http://{host}:{candidate}  ({path or 'open a DXF in the page'})")
    try:
        httpd.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        if sheet.autosave is not None:
            sheet.autosave.stop()  # the last look: what was changed in the final second is written too
            _say(f"the work is saved in {sheet.autosave.path}" if sheet.autosave.saved_at else "nothing was changed since the drawing was opened: nothing new to save")
