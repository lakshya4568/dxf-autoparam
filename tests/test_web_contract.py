"""The contract between the React workspace (web/) and the engine: every key web/src/api/types.ts lists in CONTRACT is sent by
the server, on a parametrized sheet, through HTTP as the page calls it. And the built app is served at / (the previous page at
/legacy), with nothing outside the built app reachable through /app/."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_workspace_api import _start_server, call, j

from dxf_autoparam.plan_bench import Box
from dxf_autoparam.production.bench import _sheet
from dxf_autoparam.workspace import STATIC, SheetSession

ROOT = Path(__file__).resolve().parents[1]
TYPES = ROOT / "web" / "src" / "api" / "types.ts"


def contract() -> dict[str, list[str]]:
    """CONTRACT as types.ts declares it (read from the file, so the two sides cannot drift apart unnoticed)."""
    body = re.search(r"export const CONTRACT = \{(.*?)\} as const;", TYPES.read_text(), re.DOTALL)
    assert body, "types.ts declares CONTRACT"
    return {k: re.findall(r'"([^"]+)"', v) for k, v in re.findall(r"(\w+):\s*\[([^\]]*)\]", body.group(1))}


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    sm, us, _up, _g = _sheet(Box(cells=2), tmp_path_factory.mktemp("web"), "c")
    sheet = SheetSession()
    sheet.sm = sm
    base, httpd = _start_server(sheet)
    yield base, us, sm
    httpd.shutdown()


def missing(obj: dict, keys: list[str]) -> list[str]:
    return [k for k in keys if k not in obj]


def test_contract_is_declared():
    c = contract()
    assert {"summary", "geometry", "prim", "style", "delta", "entity", "annotation", "layer", "behaviour", "coverage", "notes"} <= set(c)
    assert all(c.values())


def test_every_contract_key_is_sent(served):
    base, us, _sm = served
    c = contract()
    summary = j(call(base, "/api/sheet"))
    assert not missing(summary, c["summary"])
    geo = j(call(base, "/api/sheet/geometry", gz=True))
    assert not missing(geo, c["geometry"])
    assert geo["prims"] and all(not missing(p, c["prim"]) for p in geo["prims"])
    assert geo["styles"] and all(not missing(s, c["style"]) for s in geo["styles"])
    unit = j(call(base, f"/api/sheet/unit?id={us}"))
    p = next(p for p in unit["params"] if p["unit"] == "mm" and p["value"] > 50 and p["kind"] != "level")
    assert {"name", "key", "value", "drawn", "unit", "label"} <= set(p)
    pv = j(call(base, "/api/sheet/preview", {"changes": {p["key"]: p["value"] * 1.05}}))
    assert not missing(pv, c["delta"]) and pv["ok"] and pv["delta"]
    i = next(q["i"] for q in geo["prims"] if q["r"] == "structural")
    assert not missing(j(call(base, f"/api/sheet/entity?i={i}")), c["entity"])
    anns = j(call(base, "/api/sheet/annotations"))["annotations"]
    assert anns and all(not missing(a, c["annotation"]) for a in anns)
    assert all("<>" not in a["text"] for a in anns if a["kind"].startswith("dimension")), "a dimension reads its measured value"
    layers = j(call(base, "/api/sheet/layers"))
    assert layers["layers"] and all(not missing(r, c["layer"]) for r in layers["layers"]) and "status" in layers
    beh = j(call(base, "/api/sheet/behaviour", {"changes": {p["key"]: p["value"] * 1.05}}))
    assert not missing(beh, c["behaviour"])
    comps = beh["categories"]["components"]["items"]
    assert comps and all(isinstance(r.get("entities"), list) for r in comps), "a component row names its sheet entities (the page zooms to them)"
    assert not missing(j(call(base, "/api/sheet/coverage")), c["coverage"])
    assert not missing(j(call(base, "/api/sheet/agent_notes")), c["notes"])
    assert j(call(base, "/api/sheet"))["revision"] == summary["revision"], "reading changes no revision"


def test_the_built_app_is_served_and_nothing_outside_it(served):
    base, _us, _sm = served
    built = (STATIC / "app" / "index.html").exists()
    st, body, hdr = call(base, "/")
    assert st == 200 and "text/html" in hdr["Content-Type"] and b"Sheet Workspace" in body
    st, legacy, _ = call(base, "/legacy")
    assert st == 200 and legacy == (STATIC / "workspace.html").read_bytes()
    if not built:
        pytest.skip("web/ is not built (cd web && bun run build): / serves the previous page")
    assert b"/app/assets/" in body
    asset = re.search(rb"/app/assets/[\w.-]+\.js", body).group().decode()
    st, js, hdr = call(base, asset)
    assert st == 200 and hdr["Content-Type"].startswith("text/javascript") and len(js) > 1000
    for bad in ("/app/../workspace.py", "/app/%2e%2e/workspace.html", "/app/../../server.py", "/app/assets/nothing.js"):
        assert call(base, bad)[0] == 404, bad
