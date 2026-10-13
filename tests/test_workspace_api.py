"""The sheet workspace over HTTP, as the page uses it: open a sheet, load its geometry once, preview (nothing
committed), apply (only the touched entities come back), undo, share, rename, export, and the project round trip."""

from __future__ import annotations

import gzip
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from test_sheet import built_sheet

from dxf_autoparam.server import Session, make_handler
from dxf_autoparam.workspace import SheetSession


def call_http(*a, **k):
    return call(*a, **k)


@pytest.fixture
def server(tmp_path):
    path = built_sheet(tmp_path / "sheet.dxf")
    sheet = SheetSession()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Session(None), sheet))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, path
    httpd.shutdown()


def call(base, path, body=None, raw: bytes | None = None, gz=False):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json", **({"Accept-Encoding": "gzip"} if gz else {})})
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
    from http.server import ThreadingHTTPServer

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
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Session(None), sheet))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
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
