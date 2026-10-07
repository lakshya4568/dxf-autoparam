"""Does the engine hold on ANY drawing? The same properties checked on every view of every DXF, no AI, no cost.

    rows = check_all(paths)          # one row per view: what holds, what does not, and why

Properties (none mentions a structure type):
  P1 the drawing reads, its regions / CAD JSON / overview build;
  P2 the generic program reproduces the drawing exactly;
  P3 naming the strongest measured sizes as parameters (through the same validator the AI's edits go through), each
     one DRIVES the geometry or is reported as worked out WITH ITS REASON — never silently lost;
  P4 each driving value can grow 10 % and the drawing stays valid (or the break is explained by V8);
  P5 a changed drawing exports and re-opens cleanly.
A new drawing that fails one of these shows a gap in the ENGINE (fixed once, for all drawings), not a reason to add
a rule for that drawing.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from .ai.agent import overview
from .ai.parametrize import prepare
from .build import Decisions, build
from .cadjson import cad_json
from .dxf_read import read_dxf
from .dxf_write import audit, write_dxf
from .ir import GapKind
from .program import from_model
from .regen import regenerate_program
from .validator import apply
from .views import detect_views

KINDS = {GapKind.SOLID, GapKind.VOID, GapKind.OPEN, GapKind.CHAIN, GapKind.PITCH, GapKind.DIM}
NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliet", "Kilo", "Lima", "Mike", "November"]


def check_view(path: str, region=None, k: int = 12, out_dir: str | None = None) -> dict:
    t0 = time.perf_counter()
    row: dict = {"drawing": Path(path).name, "region": region}
    an, base, region, _snap = prepare(path, None, region)
    u = an.drawing.units_mm
    json.dumps(cad_json(an, base, for_ai=True), default=str)
    json.dumps(overview(an, base), default=str)
    from .topology import of

    row["entities"], row["regions"], row["candidates"] = len(an.drawing.items), len(of(an).regions), len(an.clusters)
    r0 = regenerate_program(from_model(build(an, Decisions())))
    row["identity_mm"] = max((math.dist(r0.pts[it.index][j], p) for it in an.drawing.items if it.index in r0.pts for j, p in enumerate(it.pts)),
                             default=0.0) * u
    picks = [c for c in sorted(an.clusters.values(), key=lambda c: (-c.confidence, -len(c.gaps)))
             if c.kind in KINDS and any(an.gaps[g].axis in ("x", "y") for g in c.gaps) and c.value * u >= 1.0][:k]
    answer = {"structure_type": "", "family": "other", "views": [], "summary": "", "components": [], "levels": [], "datum_formulas": [],
              "relations": [], "behaviours": [], "constraints": [], "questions": [],
              "parameters": [{"name": f"Size{NAMES[i]}", "label": "", "component": "", "candidate": c.id, "value": round(c.value * u, 1)}
                             for i, c in enumerate(picks)]}
    an2, *_ = prepare(path, None, region)
    prog, rep = apply(an2, answer, selection={"hold": [], "exclude": [], "drop": []})
    names = [p["name"] for p in answer["parameters"]]
    worked = {r.name for r in prog.relations}
    reasons = {f.item for f in rep.findings if f.code == "V9"}
    row["named"] = len(names)
    row["driving"] = [n for n in names if n in prog.params]
    row["worked_out"] = [n for n in names if n in worked]
    row["lost"] = [n for n in names if n not in prog.params and n not in worked]
    row["unexplained"] = [n for n in row["worked_out"] if n not in reasons]
    row["errors"] = [f"{e['code']} {e['item']}: {e['message'][:120]}" for e in rep.errors()]
    breaks = {}
    for n in row["driving"]:
        r = regenerate_program(prog, {n: prog.params[n].value * 1.1})
        if r.issues:
            breaks[n] = r.issues[0]
    row["breaks"] = breaks
    row["breaks_explained"] = all(any(f.code == "V8" and f.item == n for f in rep.findings) for n in breaks)
    ok_param = next((n for n in row["driving"] if n not in breaks), None)
    if ok_param and out_dir:
        r = regenerate_program(prog, {ok_param: prog.params[ok_param].value * 1.1})
        out = Path(out_dir) / f"{Path(path).stem}_{abs(hash(str(region))) % 10000}.dxf"
        w = write_dxf(prog, r, str(out))
        a = audit(str(out))
        row["export"] = {"param": ok_param, "updated": w.get("updated", 0), "audit_errors": a.get("errors", 0)}
    row["seconds"] = round(time.perf_counter() - t0, 1)
    row["passed"] = (row["identity_mm"] < 1e-3 and not row["lost"] and not row["unexplained"] and row["breaks_explained"]
                     and (not row.get("export") or (row["export"]["updated"] > 0 and row["export"]["audit_errors"] == 0)))
    return row


def views_of(path: str, max_entities: int = 600) -> list:
    dr, _ = read_dxf(path)
    vs = [v for v in detect_views(dr) if 15 <= v["entities"] <= max_entities]
    if len(dr.items) <= max_entities and len(vs) <= 1:
        return [None]
    return [tuple(v["bbox"]) for v in sorted(vs, key=lambda v: -v["entities"])[:3]]


def check_all(paths: list[str], out_dir: str, k: int = 12) -> list[dict]:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rows = []
    for p in paths:
        for region in views_of(p):
            try:
                rows.append(check_view(p, region, k, out_dir))
            except Exception as exc:  # noqa: BLE001 — the check's boundary: a crash on a drawing is a finding, reported in the table
                rows.append({"drawing": Path(p).name, "region": region, "passed": False, "crash": f"{type(exc).__name__}: {exc}"[:200]})
    return rows
