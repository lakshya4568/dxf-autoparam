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
"""

from __future__ import annotations

import gzip
import json
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
        if path:
            self.open(path)

    # ── state ─────────────────────────────────────────────────────────────────

    def open(self, path: str) -> dict:
        t = time.perf_counter()
        self.sm = SheetModel.open(path)
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

    def unit(self, uid: str) -> dict:
        sm = self._sm()
        u = sm.unit(uid)
        from .graph import affects

        reach = affects(u.prog)
        bound = {b.param: p.name for p in sm.shared.values() for b in p.bindings if b.unit == uid}
        params = []
        for name, prm in u.prog.params.items():
            r = reach.get(name, {})
            ents = [u.back[k] for k in r.get("entities", [])]
            params.append({"name": name, "key": bound.get(name) or f"{uid}.{name}", "shared": name in bound, "label": prm.label,
                           "value": sm.values.get(uid, {}).get(name, prm.value), "drawn": prm.value, "unit": prm.unit, "kind": prm.kind,
                           "source": prm.source, "measures": prm.measures, "confidence": prm.confidence, "evidence": prm.evidence[:4],
                           "occurrences": prm.occurrences, "entities": len(ents), "views": sorted({sm.layout.item_group.get(s, "") for s in ents} - {""}),
                           "parts": r.get("parts", [])[:12]})
        params.sort(key=lambda q: (not q["shared"], q["source"] != "ai", -q["entities"]))
        rep = u.report
        return {"id": uid, "views": u.views, "params": params, "relations": [{"name": r.name, "label": r.label, "expr": r.expr} for r in u.prog.relations][:40],
                "components": [{"name": c.name, "type": c.type, "regions": c.regions} for c in u.prog.components],
                "findings": [f.as_dict() for f in (rep.findings if rep else [])][:80], "dropped": u.dropped,
                "candidates": sorted(({"id": c.id, "value": round(c.value * u.sub.units_mm, 1), "kind": c.kind.value, "axes": sorted(c.axes),
                                       "status": c.status.value, "name": c.name, "evidence": [e.kind for e in c.evidence]}
                                      for c in u.an.clusters.values()), key=lambda c: -c["value"])[:200]}

    def param(self, name: str) -> dict:
        sm = self._sm()
        out = {"impact": sm.impact(name)}
        try:
            out["growth"] = sm.growth(name)
        except SheetError as exc:
            out["growth"] = [{"mode": "none", "why": str(exc)}]
        out["range"] = sm.valid_range(name)
        r = sm.regenerate({name: out["impact"]["value"] + out["impact"]["step"]})
        out["moves"] = sorted(r.changed)[:5000]
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
                if path == "/api/sheet/export":
                    out = Path(tempfile.mkdtemp()) / (Path(sheet._sm().path).stem + "_parametric.dxf")
                    rep = sheet._sm().export(str(out))
                    if rep["audit"]["errors"] or rep["errors"]:
                        return handler._json({"ok": False, "error": "the export did not pass its checks", "report": rep}, 409) or True
                    return handler._send(200, out.read_bytes(), "application/dxf",
                                         {"Content-Disposition": f'attachment; filename="{out.name}"', "X-Export-Report": json.dumps(rep)[:4000]}) or True
                if path == "/api/sheet/project":
                    body = json.dumps(sheet._sm().to_dict(), indent=1, default=list).encode()
                    return handler._send(200, body, "application/json",
                                         {"Content-Disposition": f'attachment; filename="{Path(sheet._sm().path).stem}.autoparam.json"'}) or True
            if method == "POST":
                raw = handler._body()
                if path == "/api/sheet/open":
                    name = q.get("name", ["upload.dxf"])[0]
                    tmp = Path(tempfile.mkdtemp()) / Path(name).name
                    tmp.write_bytes(raw)
                    return handler._json(sheet.open(str(tmp))) or True
                body = json.loads(raw or b"{}")
                if path == "/api/sheet/preview":
                    return handler._json(sheet.preview(body.get("changes", {}))) or True
                if path == "/api/sheet/apply":
                    return handler._json(sheet.apply(body.get("changes", {}))) or True
                if path in ("/api/sheet/undo", "/api/sheet/redo"):
                    return handler._json(sheet.history(path.rsplit("/", 1)[1])) or True
                if path == "/api/sheet/project":
                    tmp = Path(tempfile.mkdtemp()) / "project.json"
                    tmp.write_text(json.dumps(body))
                    sheet.sm = SheetModel.load(str(tmp), dxf=sheet._sm().path)
                    sheet.shown = set()
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
