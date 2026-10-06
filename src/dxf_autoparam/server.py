"""The demo canvas: a local web app over the pipeline (stdlib only, no framework).

    uv run dxf-autoparam serve drawing.dxf --domain bridge      → http://127.0.0.1:8765

Open a DXF → views and candidate values are shown with their evidence → accept,
reject or rename → change a value and the drawing regenerates → export the DXF.
Everything the page shows comes from the engine; the page computes no geometry.
"""

from __future__ import annotations

import errno
import json
import math
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .build import Decisions, format_form
from .dxf_read import read_dxf
from .dxf_write import audit, write_dxf
from .ir import Model
from .pipeline import autoparametrize, model_to_json, validate
from .regen import Regenerated, regenerate
from .views import detect_views

STATIC = Path(__file__).parent / "static"


class Session:
    def __init__(self, path: str | None, domain: str | None):
        self.lock = threading.Lock()
        self.path = path
        self.domain = domain
        self.region: tuple[float, float, float, float] | None = None
        self.decisions = Decisions()
        self.model: Model | None = None
        self.values: dict[str, float] = {}
        self.views: list[dict] = []
        self.validation: dict | None = None
        if path:
            self.open(path)

    def open(self, path: str) -> None:
        self.path = path
        self.region = None
        self.decisions = Decisions()
        dr, _ = read_dxf(path)
        self.views = detect_views(dr)
        self.rebuild()

    def rebuild(self) -> None:
        self.model = autoparametrize(self.path, domain=self.domain, decisions=self.decisions, region=self.region)
        self.values = self.model.defaults()
        self.validation = validate(self.model)

    # ── payloads ──────────────────────────────────────────────────────────────

    def state(self) -> dict:
        m = self.model
        an = m.analysis
        u = an.drawing.units_mm
        influence: dict[str, set[int]] = {}
        for (item, _pt, _ax), (d, _o) in an.slot_datum.items():
            for p in m.forms[d].terms:
                influence.setdefault(p, set()).add(item)
        for item, f in m.radius.items():
            for p in f.terms:
                influence.setdefault(p, set()).add(item)
        params = sorted(m.parameters.values(), key=lambda p: (p.kind in ("level", "position"), -p.affects))
        return {
            "file": Path(self.path).name,
            "domain": self.domain,
            "region": self.region,
            "views": self.views,
            "units_mm": u,
            "parameters": [
                {
                    "name": p.name, "label": p.label, "value": p.value, "display": p.value if p.kind in ("level", "position") else p.value * u,
                    "unit": p.unit if p.kind in ("level", "position") else "mm", "kind": p.kind, "status": p.status, "confidence": p.confidence,
                    "occurrences": p.occurrences, "affects": p.affects, "suggested": p.suggested,
                    "evidence": [{"kind": e.kind, "weight": e.weight, "detail": e.detail} for e in p.evidence],
                    "influence": sorted(influence.get(p.name, ())),
                }
                for p in params
            ],
            "candidates": [
                {"id": c.id, "name": c.name, "label": c.label, "value_mm": c.value * u, "status": c.status.value, "confidence": c.confidence,
                 "occurrences": len(c.gaps), "accepted": c.accepted, "kind": c.kind.value}
                for c in sorted(an.clusters.values(), key=lambda c: -c.confidence)
                if c.name not in m.parameters
            ][:60],
            "results": [{"label": r.label, "value": r.value * u, "expr": format_form(r.form, u), "dimensioned": r.dimensioned} for r in m.results[:40]],
            "constraints": [{"kind": c.kind, "detail": c.detail, "kept_by": c.kept_by} for c in an.constraints],
            "notes": an.notes + m.warnings,
            "validation": {k: v for k, v in (self.validation or {}).items() if k != "per_parameter"}
            | {"failing": [r for r in (self.validation or {}).get("per_parameter", []) if not r["ok"]][:20]},
            "unsupported": an.drawing.unsupported,
        }

    def geometry(self, reg: Regenerated) -> list[dict]:
        an = self.model.analysis
        out = []
        for it in an.drawing.items:
            pts = reg.pts.get(it.index, it.pts)
            e: dict = {"i": it.index, "t": it.dxftype, "role": it.role.value, "layer": it.layer}
            if it.dxftype in ("LINE", "LWPOLYLINE", "POLYLINE", "LEADER", "SOLID", "TRACE"):
                e["pts"] = pts
                e["closed"] = it.closed
                if it.bulges and any(abs(b) > 1e-9 for b in it.bulges):
                    e["pts"] = _bulged(pts, it.bulges, it.closed)
            elif it.dxftype == "CIRCLE":
                e["c"] = pts[0]
                e["r"] = reg.radius.get(it.index, it.radius)
            elif it.dxftype == "ARC":
                e["c"] = pts[0]
                e["r"] = reg.radius.get(it.index, it.radius)
                e["a0"], e["a1"] = it.extra.get("start_angle", 0), it.extra.get("end_angle", 0)
            elif it.dxftype in ("TEXT", "MTEXT"):
                e["at"] = pts[0]
                e["text"] = _plain(reg.texts.get(it.index, it.text or ""))
                e["h"] = it.text_height or 1.0
            elif it.dxftype == "DIMENSION":
                p1, p2, dl = pts[1], pts[2], pts[0]
                horizontal = it.extra.get("dimtype") == 0 and abs(math.sin(math.radians(it.extra.get("angle", 0)))) < 0.5
                vertical = it.extra.get("dimtype") == 0 and not horizontal
                if horizontal:
                    a, b = (p1[0], dl[1]), (p2[0], dl[1])
                    meas = abs(p2[0] - p1[0])
                elif vertical:
                    a, b = (dl[0], p1[1]), (dl[0], p2[1])
                    meas = abs(p2[1] - p1[1])
                else:
                    a, b = p1, p2
                    meas = math.dist(p1, p2)
                e["dim"] = {"p1": p1, "p2": p2, "a": a, "b": b, "text": f"{meas * an.drawing.units_mm:.0f}"}
            elif it.dxftype == "HATCH":
                e["polys"] = it.extra.get("polys", [])
                e["pts"] = pts
            elif it.dxftype in ("INSERT", "POINT", "ELLIPSE"):
                e["at"] = pts[0]
            else:
                continue
            out.append(e)
        return out


def _plain(text: str) -> str:
    import re

    return re.sub(r"\\[A-Za-z][^;]*;|[{}]|\\P", " ", text or "").strip()


def _bulged(pts, bulges, closed):
    """Polyline arcs (bulges) as short chords, for display only."""
    from ezdxf.math import Vec2, bulge_to_arc

    out = []
    n = len(pts)
    last = n if closed else n - 1
    for i in range(last):
        a, b = pts[i], pts[(i + 1) % n]
        out.append(a)
        bg = bulges[i] if i < len(bulges) else 0
        if abs(bg) > 1e-9 and math.dist(a, b) > 1e-9:
            c, a0, a1, r = bulge_to_arc(Vec2(a), Vec2(b), bg)
            if a1 < a0:
                a1 += 2 * math.pi
            for k in range(1, 12):
                t = a0 + (a1 - a0) * k / 12
                out.append((c.x + r * math.cos(t), c.y + r * math.sin(t)))
            if bg < 0:  # clockwise: the samples run the other way
                seg = out[-11:]
                out[-11:] = seg[::-1]
    if not closed and pts:
        out.append(pts[-1])
    return out


def make_handler(session: Session):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
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
            if url.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if url.path == "/api/state":
                with session.lock:
                    if session.model is None:
                        return self._json({"empty": True})
                    st = session.state()
                    st["geometry"] = session.geometry(regenerate(session.model, session.values, check=False))
                    st["values"] = session.values
                    return self._json(st)
            if url.path == "/api/model.json":
                with session.lock:
                    return self._send(200, json.dumps(model_to_json(session.model), default=str, indent=1).encode(), "application/json",
                                      {"Content-Disposition": 'attachment; filename="parametric-model.json"'})
            if url.path == "/api/export.dxf":
                q = parse_qs(url.query)
                with session.lock:
                    vals = json.loads(q.get("values", ["{}"])[0]) or session.values
                    reg = regenerate(session.model, {k: float(v) for k, v in vals.items() if k in session.model.parameters})
                    tmp = Path(tempfile.mkdtemp()) / "regenerated.dxf"
                    write_dxf(session.model, reg, str(tmp))
                    name = Path(session.path).stem + "_parametric.dxf"
                    return self._send(200, tmp.read_bytes(), "application/dxf", {"Content-Disposition": f'attachment; filename="{name}"'})
            return self._send(404, b"not found", "text/plain")

        def do_POST(self):
            url = urlparse(self.path)
            try:
                if url.path == "/api/upload":
                    name = parse_qs(url.query).get("name", ["upload.dxf"])[0]
                    tmp = Path(tempfile.mkdtemp()) / Path(name).name
                    tmp.write_bytes(self._body())
                    with session.lock:
                        session.open(str(tmp))
                    return self._json({"ok": True})
                body = json.loads(self._body() or b"{}")
                if url.path == "/api/regen":
                    with session.lock:
                        vals = dict(session.values)
                        for k, v in body.get("values", {}).items():
                            if k in session.model.parameters:
                                vals[k] = float(v)
                        reg = regenerate(session.model, vals)
                        if not reg.issues:
                            session.values = vals
                        an = session.model.analysis
                        u = an.drawing.units_mm
                        return self._json({
                            "ok": reg.ok, "issues": reg.issues, "values": vals,
                            "geometry": session.geometry(reg),
                            "results": [{"label": r.label, "value": r.form.evaluate(vals) * u, "expr": format_form(r.form, u), "dimensioned": r.dimensioned} for r in session.model.results[:40]],
                        })
                if url.path == "/api/analyse":
                    with session.lock:
                        if "region" in body:
                            session.region = tuple(body["region"]) if body["region"] else None
                        if "view" in body and body["view"] is not None:
                            session.region = tuple(session.views[int(body["view"])]["bbox"])
                        if "domain" in body:
                            session.domain = body["domain"] or None
                        d = body.get("decisions") or {}
                        session.decisions = Decisions(
                            accept=set(d.get("accept", [])), reject=set(d.get("reject", [])), rename=dict(d.get("rename", {})),
                            anchor=dict(d.get("anchor", {})),
                        )
                        session.rebuild()
                    return self._json({"ok": True})
                if url.path == "/api/audit":
                    with session.lock:
                        reg = regenerate(session.model, session.values)
                        tmp = Path(tempfile.mkdtemp()) / "check.dxf"
                        rep = write_dxf(session.model, reg, str(tmp))
                        return self._json({"write": rep, "audit": audit(str(tmp))})
            except Exception as exc:  # report to the page, keep serving
                return self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            return self._send(404, b"not found", "text/plain")

    return Handler


def serve(path: str | None, domain: str | None, host: str = "127.0.0.1", port: int = 8765) -> None:
    session = Session(path, domain)
    # Another demo (or anything else) may already hold the port: take the next free one and say so.
    for candidate in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer((host, candidate), make_handler(session))
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            print(f"port {candidate} is in use, trying {candidate + 1}")
    else:
        raise SystemExit(f"no free port between {port} and {port + 19}; pass --port")
    port = candidate
    print(f"dxf-autoparam demo on http://{host}:{port}  ({path or 'no file yet — open one in the page'})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
