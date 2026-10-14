"""The sheet workspace over HTTP, as the page uses it: open a sheet, load its geometry once, preview (nothing
committed), apply (only the touched entities come back), undo, share, rename, export, and the project round trip."""

from __future__ import annotations

import gzip
import io
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from test_sheet import built_sheet

from dxf_autoparam.server import Session, make_handler
from dxf_autoparam.workspace import SheetSession


class _InProcessServer:
    """In-process HTTP dispatch through the real BaseHTTPRequestHandler when socket.bind is blocked by a sandbox."""

    def __init__(self, handler_cls):
        self.handler_cls = handler_cls

    def dispatch(self, path: str, data: bytes | None, headers: dict[str, str]):
        h = self.handler_cls.__new__(self.handler_cls)
        h.path = path
        h.headers = {k: v for k, v in headers.items()}
        if data is not None:
            h.headers["Content-Length"] = str(len(data))
        h.rfile = io.BytesIO(data or b"")
        h.wfile = io.BytesIO()
        status = 200
        resp_headers: dict[str, str] = {}

        def send_response(code: int, message=None):
            nonlocal status
            status = code

        def send_header(k: str, v: str):
            resp_headers[k] = v

        h.send_response = send_response
        h.send_header = send_header
        h.end_headers = lambda: None
        if data is not None:
            h.do_POST()
        else:
            h.do_GET()
        payload = h.wfile.getvalue()
        if resp_headers.get("Content-Encoding") == "gzip":
            payload = gzip.decompress(payload)
        return status, payload, resp_headers

    def shutdown(self) -> None:
        pass


def _start_server(sheet: SheetSession):
    handler_cls = make_handler(Session(None), sheet)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{httpd.server_address[1]}", httpd
    except PermissionError:
        srv = _InProcessServer(handler_cls)
        return srv, srv


def call_http(*a, **k):
    return call(*a, **k)


@pytest.fixture
def server(tmp_path):
    path = built_sheet(tmp_path / "sheet.dxf")
    sheet = SheetSession()
    base, httpd = _start_server(sheet)
    yield base, path
    httpd.shutdown()


def call(base, path, body=None, raw: bytes | None = None, gz=False):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    headers = {"Content-Type": "application/json", **({"Accept-Encoding": "gzip"} if gz else {})}
    if isinstance(base, _InProcessServer):
        return base.dispatch(path, data, headers)
    req = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET", headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            payload = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                payload = gzip.decompress(payload)
            return r.status, payload, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def j(resp):
    return json.loads(resp[1])


def test_the_workspace_page_and_an_empty_sheet(server):
    base, _ = server
    st, body, hdr = call(base, "/")
    assert st == 200 and b"Sheet Workspace" in body and "text/html" in hdr["Content-Type"]
    assert j(call(base, "/api/sheet")) == {"empty": True}
    st, body, _ = call(base, "/classic")
    assert st == 200 and b"DXF" in body


def test_open_preview_apply_undo_share_rename_export(server):
    base, path = server
    summary = j(call(base, f"/api/sheet/open?name={path.name}", raw=path.read_bytes()))
    views = {g["name"]: g for g in summary["groups"] if g["kind"] == "view"}
    assert {"ELEVATION", "PLAN", "DETAIL OF WALL"} <= set(views)
    el = views["ELEVATION"]
    assert el["unit"] == views["PLAN"]["unit"]  # drawn in projection: one unit
    geo = j(call(base, "/api/sheet/geometry", gz=True))
    assert len({p["i"] for p in geo["prims"]}) > 40 and all("v" in p for p in geo["prims"])
    uid = el["unit"]
    unit = j(call(base, f"/api/sheet/unit?id={uid}"))
    cand = next(c for c in unit["candidates"] if abs(c["value"] - 12000) < 1 and c["kind"] == "void")
    r = j(call(base, "/api/sheet/share", {"name": "ClearSpan", "targets": [[uid, cand["id"]]]}))
    assert r["ok"] and r["result"]["bindings"][0]["status"] == "drives"
    info = j(call(base, "/api/sheet/param?name=ClearSpan"))
    assert set(info["impact"]["views"]) == {el["id"], views["PLAN"]["id"]} and info["range"]["max"] > 12000
    pv = j(call(base, "/api/sheet/preview", {"changes": {"ClearSpan": 14000}}))
    assert pv["ok"] and pv["changed"] > 0 and pv["delta"]
    assert j(call(base, "/api/sheet"))["values"]["ClearSpan"] == pytest.approx(12000)  # a preview commits nothing
    ap = j(call(base, "/api/sheet/apply", {"changes": {"ClearSpan": 14000}}))
    assert ap["ok"] and ap["summary"]["values"]["ClearSpan"] == pytest.approx(14000)
    moved = {p["i"] for p in ap["delta"]}
    assert moved and len(moved) < len({p["i"] for p in geo["prims"]})  # only what the change touched comes back
    bad = call(base, "/api/sheet/apply", {"changes": {"ClearSpan": 0}})
    assert not j(bad)["ok"]
    rn = j(call(base, "/api/sheet/rename", {"old": "ClearSpan", "new": "MainOpening"}))
    assert "MainOpening" in rn["summary"]["values"]
    clash = call(base, "/api/sheet/rename", {"old": "MainOpening", "new": "lower case"})
    assert clash[0] == 409 and "PascalCase" in j(clash)["error"]
    st, dxf, hdr = call(base, "/api/sheet/export")
    assert st == 200 and dxf.startswith(b"  0") or b"SECTION" in dxf[:200]
    assert json.loads(hdr["X-Export-Report"])["audit"]["errors"] == 0
    proj = j(call(base, "/api/sheet/project"))
    assert proj["format"] == "dxf-autoparam/sheet-1" and proj["shared"][0]["name"] == "MainOpening"
    un = j(call(base, "/api/sheet/undo", {}))
    assert un["ok"] and "ClearSpan" in un["summary"]["values"]
    back = j(call(base, "/api/sheet/project", proj))
    assert back["ok"] and back["summary"]["values"]["MainOpening"] == pytest.approx(14000)


def test_a_malformed_request_is_answered_not_crashed(server):
    base, path = server
    call(base, f"/api/sheet/open?name={path.name}", raw=path.read_bytes())
    st, body, _ = call(base, "/api/sheet/share", {"targets": []})
    assert st == 400 and not json.loads(body)["ok"]
    st, body, _ = call(base, "/api/sheet/nonsense", {})
    assert st == 409 and "no such edit" in json.loads(body)["error"]


def test_the_agent_describes_the_views_in_one_run_and_what_holds_is_applied(tmp_path):
    """The old "understand the views" stage is a tool of the one session: the model describes the views it sees, the engine applies what the
    geometry allows (and says what it refused), each change undoable."""
    import time

    from dxf_autoparam.ai.scripted import ScriptedModel, call

    sheet = SheetSession(str(built_sheet(tmp_path / "sheet.dxf")))
    el = next(g for g in sheet.sm.layout.views() if g.name == "ELEVATION").id
    sheet.gem = ScriptedModel([[call("describe_views", views=[{"id": el, "name": "MAIN ELEVATION", "view_type": "elevation", "confidence": 0.9},
                                                              {"id": "V99", "name": "nothing"}])], [call("finish", summary="named")]])
    assert sheet.start_run({"instruction": "Name it.", "scope": {"kind": "drawing"}})["ok"]
    for _ in range(200):
        p = sheet.run_progress(None, 0)
        if p["status"] not in ("queued", "running", "stopping"):
            break
        time.sleep(0.05)
    call_ev = next(e for e in p["events"] if e["kind"] == "tool" and e["name"] == "describe_views")
    res = call_ev["result"]
    # what held stays applied and is said; the call is not reported as accepted when part of it was refused, and the run does not call itself complete
    assert not call_ev["ok"] and res["partial"] is True and res["applied"] == [f"{el}: name → MAIN ELEVATION"] and res["refused"] == ["V99: no such group"]
    assert p["verdict"]["state"] == "partial" and p["verdict"]["refused"][0]["item"] == "view:V99"
    assert next(g for g in sheet.summary()["groups"] if g["id"] == el)["name"] == "MAIN ELEVATION"
    assert sheet.sm.undo() and next(g for g in sheet.summary()["groups"] if g["id"] == el)["name"] != "MAIN ELEVATION"
    with pytest.raises(Exception, match="write an instruction"):
        sheet.start_run({"instruction": "  "})


def test_a_run_is_started_asked_answered_and_checked_over_http(tmp_path):
    """The page's routes for the agent, as HTTP: start a run, read its progress (events, state, questions), see a picture it was shown, answer, and
    read the verdict, the status, the original and the highlight — then reset a value and the drawing, and undo."""
    import time

    from dxf_autoparam.ai.scripted import ScriptedModel, call
    from dxf_autoparam.cadjson import entity_id
    from dxf_autoparam.plan_bench import Box, answer_as_calls, box_answer, box_gad

    g = box_gad(tmp_path / "box.dxf", Box())
    sheet = SheetSession(g["path"])
    uid = next(k for k, u in sheet.sm.units.items() if len(u.views) == 2)
    build = [call(n, **a) for n, a in answer_as_calls(box_answer(sheet.sm, uid, g["box"], g["handles"]))]
    eid = entity_id(next(it for it in sheet.sm.unit(uid).sub.items if it.dxftype == "LWPOLYLINE"))
    said = "Reduce the clear span to 2500 mm. Keep the foundation fixed. The wing walls follow the box. Keep the unrelated pitching detail unchanged."
    sheet.gem = ScriptedModel([
        [call("account_instruction", items=[{"quote": "Reduce the clear span to 2500 mm", "kind": "change_value", "meaning": "x", "handled_by": "plan"},
                                            {"quote": "Keep the foundation fixed", "kind": "keep", "meaning": "y", "handled_by": "plan"},
                                            {"quote": "The wing walls follow the box", "kind": "keep", "meaning": "z", "handled_by": "plan"},
                                            {"quote": "Keep the unrelated pitching detail unchanged", "kind": "keep", "meaning": "w", "handled_by": "plan"}])],
        [call("zoom_view", around=[eid]), *build], [call("inspect_assembly", parameter="ClearSpan")],
        [call("propose_plan", parameter="ClearSpan", requested_value=2500,
              directives=[{"target": "Foundation", "mode": "keep_fixed", "clause": "Keep the foundation fixed"},
                          {"target": "WingLeft", "mode": "follow", "clause": "The wing walls follow the box"},
                          {"target": "WingRight", "mode": "follow", "clause": "The wing walls follow the box"},
                          {"target": "PitchingDetail", "mode": "exclude", "clause": "Keep the unrelated pitching detail unchanged"}])],
        [call("finish", summary="x")], [call("finish", summary="x")], [call("finish", summary="x")]])
    base, httpd = _start_server(sheet)
    try:
        def wait_for(pred, rid, t=30):
            end = time.time() + t
            while time.time() < end:
                p = j(call_http(base, f"/api/sheet/ai/progress?run={rid}&since=0"))
                if pred(p):
                    return p
                time.sleep(0.05)
            raise AssertionError(p["status"])

        st, body, _ = call_http(base, "/api/sheet/ai/run", {"instruction": ""})
        assert st == 409 and "instruction" in json.loads(body)["error"]
        rid = j(call_http(base, "/api/sheet/ai/run", {"instruction": said, "scope": {"views": ["V01"]}}))["run"]
        p = wait_for(lambda q: q["status"] == "awaiting_user", rid)
        assert p["questions"] and p["questions"][0]["about"] == "anchor" and p["verdict"] is None
        img = next(e for e in p["events"] if e["kind"] == "tool" and e["name"] == "zoom_view")["image"]["id"]
        st, png, hdr = call_http(base, f"/api/sheet/ai/image?run={rid}&id={img}")
        assert st == 200 and png[:8] == b"\x89PNG\r\n\x1a\n" and hdr["Content-Type"] == "image/png"
        assert call_http(base, f"/api/sheet/ai/image?run={rid}&id=IMG999")[0] == 404
        q = p["questions"][0]
        ans = next(o for o in q["options"] if o.startswith("centered"))
        assert j(call_http(base, "/api/sheet/ai/continue", {"run": rid, "answers": {q["id"]: ans}}))["ok"]
        p = wait_for(lambda q: q["status"] == "completed", rid)
        assert p["verdict"]["state"] == "completed" and all(c["ok"] for c in p["verdict"]["criteria"])
        assert [r["id"] for r in j(call_http(base, "/api/sheet/ai/runs"))["runs"]] == [rid]
        delta = j(call_http(base, "/api/sheet/delta"))
        assert delta["summary"]["values"][f"{uid}.ClearSpan"] == 2500
        status = j(call_http(base, "/api/sheet/status"))
        assert status["overall"] == "complete" and {v["state"] for v in status["views"]} == {"complete"}
        key = f"{uid}.ClearSpan"
        info = j(call_http(base, f"/api/sheet/param?name={key}"))
        assert info["highlight"]["drives"] and set(info["highlight"]["views"]) == {"V01", "V02"} and "Foundation (keep_fixed)" in info["highlight"]["holds"]
        assert info["card"]["validated"] and info["card"]["bindings"][0]["original"]["value"] == 3000 and info["deviation"]["changed"] > 0
        assert j(call_http(base, "/api/sheet/baseline"))["changed"] == info["deviation"]["changed"] or j(call_http(base, "/api/sheet/baseline"))["prims"]
        assert j(call_http(base, "/api/sheet/prefs", {"baseline": {"on": True, "color": "#ff00ff"}}))["prefs"]["baseline"] == {"on": True, "color": "#ff00ff"}
        res = j(call_http(base, "/api/sheet/reset_value", {"name": key}))
        assert res["changed"] and res["summary"]["values"][key] == 3000 and res["delta"]
        assert not j(call_http(base, "/api/sheet/reset_value", {"name": key}))["changed"]
        st, body, _ = call_http(base, "/api/sheet/reset_drawing", {})
        assert st == 409 and "confirm" in json.loads(body)["error"]  # a full reset asks first
        res = j(call_http(base, "/api/sheet/reset_drawing", {"confirm": True}))
        assert res["summary"]["values"] == {} and j(call_http(base, "/api/sheet/status"))["overall"] == "not_started"
        assert j(call_http(base, "/api/sheet/undo", {}))["ok"] and j(call_http(base, "/api/sheet"))["can_redo"]
        revert = call_http(base, "/api/sheet/ai/revert", {"run": rid})
        assert revert[0] == 409  # the sheet moved on since the run: undo step by step, not a blind revert
    finally:
        httpd.shutdown()


def test_model_choices_and_per_run_config(monkeypatch):
    """The picker offers 3.8 Flash and 4 Argon at high thinking; a chosen model is never swapped for a cheaper fallback."""
    from dxf_autoparam.ai import vertex

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.delenv("VERTEX_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    got = vertex.model_choices()
    assert got["default"] == "gemini-3.8-flash"
    assert [m["id"] for m in got["models"]] == ["gemini-3.8-flash", "gemini-4-argon"]
    argon = vertex.config("gemini-4-argon")
    assert (argon.model, argon.thinking, argon.fallback_model) == ("gemini-4-argon", "high", "")
    assert argon.explicit_cache is False and vertex.config("gemini-3.8-flash").explicit_cache is True
    assert vertex.config("gemini-3.8-flash").fallback_model == "gemini-3.7-flash"
    import pytest

    with pytest.raises(ValueError):
        vertex.config("gemini-nope")


def test_get_gem_switches_back_to_default_and_preserves_cache_for_same_model(monkeypatch):
    """Switching from Argon back to default (None) closes Argon and opens Flash; passing None then explicit Flash keeps the same client."""
    from dxf_autoparam.ai import vertex

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.delenv("VERTEX_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    created = []
    closed = []

    class FakeGemini:
        def __init__(self, cfg):
            self.cfg = cfg
            created.append(cfg.model)

        def close(self):
            closed.append(self.cfg.model)
            return []

    monkeypatch.setattr(vertex, "Gemini", FakeGemini)
    sheet = SheetSession()
    g1 = sheet.get_gem(None)
    assert g1.cfg.model == "gemini-3.8-flash" and sheet.gem_model == "gemini-3.8-flash"
    g2 = sheet.get_gem("gemini-3.8-flash")
    assert g2 is g1 and closed == []  # same canonical model: prompt cache is kept
    g3 = sheet.get_gem("gemini-4-argon")
    assert g3 is not g1 and g3.cfg.model == "gemini-4-argon" and closed == ["gemini-3.8-flash"]
    g4 = sheet.get_gem(None)
    assert g4 is not g3 and g4.cfg.model == "gemini-3.8-flash" and closed == ["gemini-3.8-flash", "gemini-4-argon"]


def test_usage_summary_costs_each_model_from_the_ledger(tmp_path, monkeypatch):
    """Uncached input, cached input and output (answer + thinking) are priced separately; cut-off errors keep their billed tokens; stopped calls do not inflate calls."""
    import json

    import pytest

    from dxf_autoparam.ai.usage import summary

    monkeypatch.delenv("VERTEX_PRICES", raising=False)
    rows = [{"model": "gemini-4-argon", "input_tokens": 1_000_000, "vertex_cached_tokens": 400_000, "output_tokens": 50_000, "thinking_tokens": 50_000, "at": "2026-10-13 10:00:00"},
            {"model": "gemini-4-argon", "error": "429", "at": "2026-10-13 10:01:00"},
            {"model": "gemini-4-argon", "error": "no complete JSON (finish_reason=MAX_TOKENS)", "input_tokens": 100_000, "output_tokens": 10_000, "thinking_tokens": 10_000, "at": "2026-10-13 10:02:00"},
            {"model": "gemini-4-argon", "stopped": True, "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "at": "2026-10-13 10:03:00"},
            {"model": "gemini-3.8-flash", "input_tokens": 10, "output_tokens": 5, "at": "2026-10-12 09:00:00"}]
    ledger = tmp_path / "usage.jsonl"
    ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    s = summary("all", ledger)
    argon = next(m for m in s["models"] if m["model"] == "gemini-4-argon")
    assert (argon["input"], argon["cached"], argon["output"], argon["calls"], argon["errors"]) == (700_000, 400_000, 120_000, 1, 2)
    assert argon["cost"] == pytest.approx(0.7 * 2.0 + 0.4 * 0.10 + 0.12 * 10.0)
    assert next(m for m in s["models"] if m["model"] == "gemini-3.8-flash")["cost"] is None and s["unpriced"] == ["gemini-3.8-flash"]
    monkeypatch.setenv("VERTEX_PRICES", json.dumps({"gemini-3.8-flash": {"input": 1, "output": 4}}))
    assert summary("all", ledger)["unpriced"] == []


def test_split_shared_lines_restores_datums_and_slots_on_rebuild(tmp_path):
    """Holding a part splits shared datums (adding <id>h); rebuilding without hold_parts restores original datums and slot bindings."""
    from dxf_autoparam.ai.parametrize import _restore, _snapshot
    from dxf_autoparam.crossview import SheetModel
    from dxf_autoparam.plan_bench import Box, box_answer, box_gad

    g = box_gad(tmp_path / "box.dxf", Box())
    sm = SheetModel.open(g["path"])
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    u = sm.unit(uid)
    orig_datums = set(u.an.datums)
    orig_slots = dict(u.an.slot_datum)

    ans_held = box_answer(sm, uid, g["box"], g["handles"])
    ans_held["plans"] = [{"id": "P1", "status": "accepted", "driver": {"parameter": "ClearSpan"},
                          "anchor": {"policy": "as_set_out", "source": "person"},
                          "directives": [{"kind": "part", "target": "RightWall", "mode": "exclude", "status": "accepted"}]}]
    sm.set_answer(uid, ans_held)
    assert any(d.endswith("h") for d in sm.unit(uid).an.datums)

    # Pristine analysis and un-holding must restore the original datums and slot bindings cleanly
    pristine = sm.pristine_analysis(uid)
    assert set(pristine.datums) == orig_datums
    assert pristine.slot_datum == orig_slots

    ans_unheld = box_answer(sm, uid, g["box"], g["handles"])
    sm.set_answer(uid, ans_unheld)
    assert set(sm.unit(uid).an.datums) == orig_datums
    assert sm.unit(uid).an.slot_datum == orig_slots

    # Also check ai/parametrize.py _snapshot / _restore
    snap = _snapshot(pristine)
    pristine.datums["x0h"] = pristine.datums["x0"]
    _restore(pristine, snap)
    assert "x0h" not in pristine.datums


def test_project_save_and_load_preserves_rekinded_and_merged_views_and_weak_links(tmp_path):
    """Re-kinding a table/notes group to a view (or merging views) and saving/loading the project preserves its unit and answers; weak links toggle cleanly."""
    from dxf_autoparam.crossview import SheetError, SheetModel

    path = built_sheet(tmp_path / "sheet.dxf")
    sm = SheetModel.open(str(path))
    non_view = next(g for g in sm.layout.groups if g.kind != "view")
    nid = non_view.id
    sm.set_view(nid, name="EXTRA VIEW", view_type="detail", kind="view")
    uid = sm.unit_of_view[nid]
    assert uid in sm.units
    sm.units[uid].answer = {"structure_type": "TestDetail", "family": "other", "components": [], "parameters": []}

    proj_file = tmp_path / "proj.autoparam.json"
    sm.save(str(proj_file))
    loaded = SheetModel.load(str(proj_file), dxf=str(path))
    assert nid in loaded.unit_of_view
    loaded_uid = loaded.unit_of_view[nid]
    assert loaded.units[loaded_uid].answer and loaded.units[loaded_uid].answer["structure_type"] == "TestDetail"

    # Weak projection link toggling via sm.link()
    sm2 = SheetModel.open(str(path))
    lk = sm2.links[0]
    lk["strong"] = False
    sm2._group_units()
    assert sm2.unit_of_view[lk["a"]] != sm2.unit_of_view[lk["b"]]
    sm2.link(lk["a"], lk["b"], True)
    assert sm2.is_linked(lk) and sm2.unit_of_view[lk["a"]] == sm2.unit_of_view[lk["b"]]
    sm2.link(lk["a"], lk["b"], False)
    assert not sm2.is_linked(lk) and sm2.unit_of_view[lk["a"]] != sm2.unit_of_view[lk["b"]]
    with pytest.raises(SheetError, match="no projection link"):
        sm2.link("V01", "V99", True)


def test_workbench_remove_normalizes_parameter_names_and_guards_work(tmp_path):
    """Workbench.write('remove', ...) normalizes parameter names to PascalCase when pruning parameters and relations."""
    from dxf_autoparam.ai.agent import Workbench
    from dxf_autoparam.crossview import SheetModel
    from dxf_autoparam.plan_bench import Box, box_gad

    g = box_gad(tmp_path / "box.dxf", Box())
    sm = SheetModel.open(g["path"])
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    wb = Workbench(g["path"], analysis=sm.pristine_analysis(uid))
    cand = next(c.id for c in wb.an.clusters.values() if len(c.gaps) == 1)
    wb.write("define_parameter", {"name": "clear_span", "candidate": cand})
    wb.write("set_relation", {"name": "total_width", "expr": "ClearSpan * 2"})
    assert any(p["name"] == "ClearSpan" for p in wb.answer["parameters"])
    assert any(r["name"] == "TotalWidth" for r in wb.answer["relations"])
    wb.write("remove", {"parameters": ["clear_span", "total_width"]})
    assert not any(p["name"] == "ClearSpan" for p in wb.answer["parameters"])
    assert not any(r["name"] == "TotalWidth" for r in wb.answer["relations"])
