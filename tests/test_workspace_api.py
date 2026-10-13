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


def test_a_gemini_stage_runs_in_the_background_and_its_result_is_applied(tmp_path):
    import time

    from test_sheet_ai import FakeGemini

    sheet = SheetSession(str(built_sheet(tmp_path / "sheet.dxf")))
    el = next(g for g in sheet.sm.layout.views() if g.name == "ELEVATION").id
    sheet.gem = FakeGemini({"structure": "test", "views": [{"id": el, "kind": "view", "name": "MAIN ELEVATION", "view_type": "elevation",
                                                             "confidence": 0.9}], "merges": [], "relations": [], "questions": []})
    assert sheet.start_ai("views", {})["ok"]
    for _ in range(100):
        p = sheet.progress(0)
        if not p["running"]:
            break
        time.sleep(0.05)
    assert not p["running"] and p["result"]["applied"] == [f"{el}: name → MAIN ELEVATION"]
    assert any(e["kind"] == "done" for e in p["events"])
    assert next(g for g in sheet.summary()["groups"] if g["id"] == el)["name"] == "MAIN ELEVATION"
    with pytest.raises(Exception, match="no Gemini stage"):
        sheet.start_ai("everything", {})


def test_a_plan_is_read_decided_applied_measured_and_undone_over_http(server, tmp_path):
    """The page's plan panel, as HTTP: an instruction is read into a plan (nothing changes), the person's two answers
    make it ready, applying it commits the value and returns what moved, the unit shows the measured plan, undo takes
    plan and value back together, and a contradictory instruction is refused with the reason."""
    from dxf_autoparam.crossview import SheetModel
    from dxf_autoparam.plan_bench import Box, box_answer, box_gad

    base, _ = server
    g = box_gad(tmp_path / "box.dxf", Box())
    local = SheetModel.open(g["path"])
    uid = next(k for k, u in local.units.items() if len(u.views) == 2)
    local.commit_answer(uid, box_answer(local, uid, g["box"], g["handles"]))
    call(base, "/api/sheet/open?name=box.dxf", raw=(tmp_path / "box.dxf").read_bytes())
    assert j(call(base, "/api/sheet/project", local.to_dict()))["ok"]
    said = ("Reduce the clear span to 2500. Maintain wall and slab thicknesses. Preserve the foundation. "
            "Update connected geometry and every affected view. Keep unrelated details unchanged.")
    plan = j(call(base, "/api/sheet/plan", {"unit": uid, "instruction": said}))["plan"]
    assert plan["status"] == "needs_decision" and {q["about"] for q in plan["questions"]} >= {"anchor"}
    review = next(q["about"] for q in plan["questions"] if q["about"].startswith("D"))  # "preserve the foundation": which meaning
    st, body, _ = call(base, "/api/sheet/plan/apply", {"unit": uid, "instruction": said})
    assert st == 409 and b"needs_decision" in body  # nothing is applied while a question is open
    res = j(call(base, "/api/sheet/plan/apply", {"unit": uid, "instruction": said, "decisions": {review: "keep_fixed", "anchor": "centered"}}))
    assert res["result"]["checks"]["ok"] and res["result"]["applied"]["value"] == 2500
    assert res["delta"] and set(res["result"]["applied"]["by_view"]) == {"V01", "V02"}
    unit = j(call(base, f"/api/sheet/unit?id={uid}"))
    assert unit["plans"][0]["status"] == "accepted" and unit["plans"][0]["checks"]["failed"] == 0
    assert j(call(base, "/api/sheet/undo", {}))["ok"]
    assert j(call(base, f"/api/sheet/unit?id={uid}"))["plans"] == []
    st, body, _ = call(base, "/api/sheet/plan/apply", {"unit": uid, "instruction": "Reduce the clear span to 2500, centred. "
                                                                                     "Keep the foundation fixed. The foundation follows the box."})
    assert st == 409 and b"cannot both hold" in body
