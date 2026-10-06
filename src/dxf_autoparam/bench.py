"""Intent-recovery benchmark against independently authored parametric programs.

For each library family (exported from the Aagento kernel by tools/export_library_oracle.ts):

  1. read the BASE drawing as a plain DXF and reverse-engineer it blind;
  2. identity: regenerating at the inferred defaults must reproduce every point exactly;
  3. for each of the family's length parameters P (changed by Δ in the ground truth):
     is there ONE inferred parameter Q such that Q + k·Δ (k ∈ {1, ½, 2}) reproduces the
     ground truth's geometry? → RECOVERED. Otherwise the best partial match is reported.

Nothing about the families is visible to the engine; it sees DXF entities only.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

from .analyse import analyse
from .build import build
from .dxf_read import read_dxf
from .ir import Role
from .regen import regenerate

MATCH_TOL = 1.0  # mm


def _oracle_points(geom: dict) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for p in geom["polylines"]:
        if "CENTRE" in p["layer"].upper():
            continue
        pts.extend(tuple(q) for q in p["pts"])
    for ln in geom["lines"]:
        pts.extend([tuple(ln["a"]), tuple(ln["b"])])
    for c in geom["circles"]:
        pts.extend([tuple(c["c"]), (c["c"][0] + c["r"], c["c"][1])])
    return pts


def _model_points(model, reg) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for it in model.analysis.drawing.items:
        if it.role in (Role.REFERENCE, Role.FIXED) or it.dxftype not in ("LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE"):
            continue
        if it.dxftype == "CIRCLE":
            (cx, cy) = reg.pts[it.index][0]
            r = reg.radius.get(it.index, it.radius)
            pts.extend([(cx, cy), (cx + r, cy)])
        else:
            pts.extend(reg.pts[it.index][k] for k in it.vertex_pts)
    return pts


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _match_shape(target, ours, tol=MATCH_TOL) -> float:
    """Best match over the translations that pin a bounding-box corner, edge or centre.

    WHICH point of a drawing stays put when it grows (its left face, its centre line,
    its foundation) is an anchor choice the drawing cannot state; the shape is the intent.
    """
    if not target or not ours:
        return 0.0
    t0, o0 = _bbox(target), _bbox(ours)
    best = 0.0
    for fx in (0.0, 0.5, 1.0):
        for fy in (0.0, 0.5, 1.0):
            dx = (t0[0] + fx * (t0[2] - t0[0])) - (o0[0] + fx * (o0[2] - o0[0]))
            dy = (t0[1] + fy * (t0[3] - t0[1])) - (o0[1] + fy * (o0[3] - o0[1]))
            m = _match(target, [(x + dx, y + dy) for x, y in ours], tol)
            best = max(best, m)
            if best > 0.9999:
                return best
    return best


def _match(a, b, tol=MATCH_TOL) -> float:
    if not a or not b:
        return 0.0
    grid: dict[tuple[int, int], list] = {}
    for p in b:
        grid.setdefault((int(p[0] // tol), int(p[1] // tol)), []).append(p)

    def hit(p, g):
        cx, cy = int(p[0] // tol), int(p[1] // tol)
        return any(abs(q[0] - p[0]) <= tol and abs(q[1] - p[1]) <= tol for i in (-1, 0, 1) for j in (-1, 0, 1) for q in g.get((cx + i, cy + j), ()))

    ab = sum(hit(p, grid) for p in a) / len(a)
    grid2: dict[tuple[int, int], list] = {}
    for p in a:
        grid2.setdefault((int(p[0] // tol), int(p[1] // tol)), []).append(p)
    ba = sum(hit(p, grid2) for p in b) / len(b)
    return min(ab, ba)


@dataclass
class FamilyResult:
    id: str
    params: int
    recovered: int
    recovered_strict: int
    no_effect: int
    identity_error: float
    inferred: int
    seconds: float
    detail: list[str] = field(default_factory=list)


def run(fixtures: Path, domain: str | None = None, verbose: bool = True, only: str | None = None, no_dims: bool = False) -> list[FamilyResult]:
    out: list[FamilyResult] = []
    for src in sorted(fixtures.glob("*.json")):
        if src.name == "index.json" or (only and only not in src.stem):
            continue
        data = json.loads(src.read_text())
        dxf = fixtures / "dxf" / f"{src.stem}.dxf"
        t0 = time.perf_counter()
        dr, _ = read_dxf(str(dxf))
        if no_dims:  # geometry only: the drawing's own dimensions are withheld
            dr.items = [it for it in dr.items if it.dxftype != "DIMENSION"]
            for i, it in enumerate(dr.items):
                it.index = i
        an = analyse(dr)
        decisions = None
        if domain:
            from .domains import PACKS

            decisions = PACKS[domain](an)
        model = build(an, decisions)
        base = regenerate(model)
        ident = max(
            (math.dist(base.pts[it.index][k], it.pts[k]) for it in dr.items if it.role == Role.STRUCTURAL for k in it.vertex_pts),
            default=0.0,
        )
        base_oracle = _oracle_points(data["base"])
        res = FamilyResult(data["id"], 0, 0, 0, 0, ident, len(model.parameters), 0.0)
        for var in data["variants"]:
            if not var["ok"]:
                res.detail.append(f"{var['param']}:refused")
                continue
            target = _oracle_points(var["geom"])
            if _match(target, base_oracle) > 0.999:
                res.no_effect += 1
                res.detail.append(f"{var['param']}:no-effect")
                continue
            res.params += 1
            best, best_q, strict = 0.0, "", False
            for q in model.parameters.values():
                for k in (1.0, 0.5, 2.0):
                    nv = q.value + k * var["delta"] / dr.units_mm
                    if nv <= 0:
                        continue
                    reg = regenerate(model, {q.name: nv}, check=False)
                    ours = _model_points(model, reg)
                    m = _match_shape(target, ours)
                    if m > best:
                        best, best_q = m, f"{q.name}{'' if k == 1 else f'×{k:g}'}"
                    if m > 0.9999 and _match(target, ours) > 0.9999:
                        strict = True
                    if best > 0.9999 and strict:
                        break
                if best > 0.9999 and strict:
                    break
            if strict:
                res.recovered_strict += 1
            if best > 0.9999:
                res.recovered += 1
                res.detail.append(f"{var['param']}✓{best_q}")
            else:
                res.detail.append(f"{var['param']}✗{best:.0%}{('~' + best_q) if best_q else ''}")
        res.seconds = time.perf_counter() - t0
        out.append(res)
        if verbose:
            print(f"{res.id:<28} recovered {res.recovered:>2}/{res.params:<2} (strict {res.recovered_strict:>2}, no-effect {res.no_effect}) identity {res.identity_error:.1e}  params {res.inferred:>3}  {res.seconds:5.1f}s  {' '.join(res.detail)}")
    if verbose:
        tot = sum(r.params for r in out)
        rec = sum(r.recovered for r in out)
        strict = sum(r.recovered_strict for r in out)
        print(f"TOTAL recovered {rec}/{tot} = {rec / max(1, tot):.0%}  (strict, same anchor: {strict}/{tot} = {strict / max(1, tot):.0%})")
    return out
