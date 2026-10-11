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
