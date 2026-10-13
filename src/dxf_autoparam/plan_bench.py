"""Benchmark for instruction-guided, assembly-aware parametrization — no model calls.

Drawings are GENERATED from known sizes (a multi-cell RCC box in section drawn as separate members, its foundation, a
plan view in projection with wing walls, an unrelated detail, dimensions, notes), so the INTENDED geometry after any
change is known exactly: the same generator, run with the new size and the accepted anchor. A case is an instruction
and what it must lead to (the driver, the directives, the anchor or the question to ask, what moves and what stays);
the engine is scored on what it actually does to the regenerated sheet, member by member.

    uv run dxf-autoparam plan-bench            # every case, a table and plan_bench.json

Categories are scored separately (resolution of the driver and the parts, the meaning of "do not change", anchors,
affected parts, invariants, regeneration, views, dimensions, unintended change, asking when it must) so an aggregate
cannot hide a dangerous failure; ambiguous cases count only if the engine ASKS.
"""

from __future__ import annotations

import copy
import json
import math
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import ezdxf

# ── the generator ────────────────────────────────────────────────────────────────


@dataclass
class Box:
    cells: int = 2
    span: float = 3000.0
    height: float = 2500.0
    wall: float = 350.0
    mid: float = 300.0
    top: float = 300.0
    bottom: float = 350.0
    haunch: float = 150.0
    pcc: float = 150.0  # foundation projection beyond the outer walls
    pcc_t: float = 150.0
    wing: float = 1500.0  # wing walls in plan
    wing_t: float = 300.0
    barrel: float = 6000.0  # barrel length in plan
    detail_x: float | None = None  # the unrelated detail's place (absolute: it never moves)
    plan: bool = True
    detail: bool = True

    @property
    def width(self) -> float:
        return 2 * self.wall + self.cells * self.span + (self.cells - 1) * self.mid


def members(b: Box, x0: float = 0.0, pcc_box: tuple[float, float] | None = None, wings_at: tuple[float, float] | None = None,
            centre_x: float | None = None) -> dict[str, list[tuple[float, float]]]:
    """Every member's outline (closed), by name. `x0`: where the box's left outer face is; `pcc_box`: the foundation's
    own x extent when it does not follow the box; `wings_at`: the faces the wing walls stand on when they do not follow."""
    W = b.width
    yb, yt = b.bottom, b.bottom + b.height
    out: dict[str, list[tuple[float, float]]] = {
        "BottomSlab": _rect(x0, 0, x0 + W, b.bottom),
        "TopSlab": _rect(x0, yt, x0 + W, yt + b.top),
        "LeftWall": _rect(x0, yb, x0 + b.wall, yt),
        "RightWall": _rect(x0 + W - b.wall, yb, x0 + W, yt),
    }
    h = b.haunch
    for k in range(b.cells):
        c0 = x0 + b.wall + k * (b.span + b.mid)
        c1 = c0 + b.span
        if k < b.cells - 1:
            out[f"MidWall{k + 1}"] = _rect(c1, yb, c1 + b.mid, yt)
        if h > 0:
            out[f"Haunch{k + 1}BL"] = [(c0, yb), (c0 + h, yb), (c0, yb + h)]
            out[f"Haunch{k + 1}BR"] = [(c1, yb), (c1, yb + h), (c1 - h, yb)]
            out[f"Haunch{k + 1}TL"] = [(c0, yt), (c0, yt - h), (c0 + h, yt)]
            out[f"Haunch{k + 1}TR"] = [(c1, yt), (c1 - h, yt), (c1, yt - h)]
    lo, hi = pcc_box if pcc_box else (x0 - b.pcc, x0 + W + b.pcc)
    out["Foundation"] = _rect(lo, -b.pcc_t, hi, 0)
    if b.plan:
        yp = -b.pcc_t - 3000 - b.barrel
        out["PlanBox"] = _rect(x0, yp, x0 + W, yp + b.barrel)
        lf, rf = wings_at if wings_at else (x0, x0 + W)
        out["WingLeft"] = _rect(lf - b.wing, yp + b.barrel - b.wing_t, lf, yp + b.barrel)
        out["WingRight"] = _rect(rf, yp + b.barrel - b.wing_t, rf + b.wing, yp + b.barrel)
    if b.detail:
        dx = b.detail_x if b.detail_x is not None else W + 1400
        out["PitchingDetail"] = [(dx, 0), (dx + 1500, 0), (dx + 1200, 600), (dx + 300, 600)]
    return out


def _rect(x0, y0, x1, y1) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def faces(b: Box, x0: float = 0.0) -> list[float]:
    """The wall faces across the box, left to right (the lines a plan view shares with the section)."""
    out = [x0, x0 + b.wall]
    for k in range(b.cells):
        c1 = x0 + b.wall + k * (b.span + b.mid) + b.span
        out.append(c1)
        if k < b.cells - 1:
            out.append(c1 + b.mid)
    out.append(x0 + b.width)
    return out


def box_gad(path: str | Path, b: Box | None = None) -> dict:
    """Write the drawing; return {path, box, handles: member → entity handle, centre_handle}."""
    b = b or Box()
    if b.detail_x is None:
        b = replace(b, detail_x=b.width + 1400)
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.dimstyles.new("GAD50", dxfattribs={"dimtxt": 2.5, "dimscale": 50, "dimgap": 0.6, "dimtad": 1})
    msp = doc.modelspace()
    for name, lay in (("STRUCTURE", 7), ("FOUNDATION", 3), ("CENTRE", 1), ("DIM", 2), ("TEXT", 7), ("HIDDEN", 8), ("DETAIL", 5)):
        if name not in doc.layers:
            doc.layers.add(name, color=lay)
    handles = {}
    for name, pts in members(b).items():
        layer = "FOUNDATION" if name == "Foundation" else "DETAIL" if name == "PitchingDetail" else "STRUCTURE"
        handles[name] = msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer}).dxf.handle
    W = b.width
    yt = b.bottom + b.height + b.top
    cl = msp.add_line((W / 2, -b.pcc_t - 600), (W / 2, yt + 600), dxfattribs={"layer": "CENTRE"})

    def dim(p1, p2, base, angle=0):
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle="GAD50", dxfattribs={"layer": "DIM"}).render()

    def text(s, x, y, h=150):
        msp.add_text(s, height=h, dxfattribs={"layer": "TEXT", "insert": (x, y), "halign": 1, "align_point": (x, y)})

    f = faces(b)
    for k in range(b.cells):  # clear spans, measured along the cell's mid height
        dim((f[1 + 2 * k], b.bottom + b.height / 2), (f[2 + 2 * k], b.bottom + b.height / 2), (0, yt + 500))
    dim((0, yt), (b.wall, yt), (0, yt + 900))
    dim((0, yt), (W, yt), (0, yt + 1300))
    dim((W, 0), (W, b.bottom), (W + 900, 0), 90)
    dim((W, b.bottom + b.height), (W, yt), (W + 900, 0), 90)
    text(f"{b.cells} CELL RCC BOX {b.span / 1000:.3f} X {b.height / 1000:.3f} m", W / 2, -b.pcc_t - 1100)
    text("SECTION A-A", W / 2, -b.pcc_t - 1500, 175)
    if b.plan:
        yp = -b.pcc_t - 3000 - b.barrel
        for x in f[1:-1]:
            msp.add_line((x, yp), (x, yp + b.barrel), dxfattribs={"layer": "HIDDEN"})
        dim((0, yp), (W, yp), (0, yp - 500))
        dim((0, yp), (0, yp + b.barrel), (-b.wing - 700, 0), 90)
        text("PLAN", W / 2, yp - 1300, 175)
    doc.saveas(str(path))
    return {"path": str(path), "box": b, "handles": handles, "centre_handle": cl.dxf.handle}


# ── the sheet answer a person (or the agent) gives it: parts and named sizes ──────


def box_answer(sm, uid: str, b: Box, handles: dict, names: dict | None = None) -> dict:
    """Parts by region (each member's own closed outline), named sizes by the lines they lie between — found by
    position on the analysis, so ids are the sheet's. `names`: which named sizes to define (all by default)."""
    from .crossview import EMPTY_ANSWER
    from .topology import of

    u = sm.unit(uid)
    an = u.an
    um = u.sub.units_mm
    topo = of(an)
    item_of = {it.handle: k for k, it in enumerate(an.drawing.items)}
    comps = []
    region_of = {}
    for name, h in handles.items():
        k = item_of.get(h)
        if k is None:
            continue
        pts = an.drawing.items[k].pts
        box = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        best = None
        for r in topo.regions:
            d = sum(abs(a - c) for a, c in zip(r.bbox, box, strict=True))
            if d < 1e-6 * max(1.0, box[2] - box[0]) and (best is None or r.area < best.area or len(r.holes) < len(best.holes)):
                best = r
        if best is not None:
            region_of[name] = best.id
    parent = "Box"
    comps.append({"name": "Box", "type": "box", "level": "assembly", "regions": [], "confidence": 0.95})
    for name, rid in region_of.items():
        if name in ("Foundation", "PitchingDetail", "WingLeft", "WingRight", "PlanBox"):
            typ = {"Foundation": "footing", "PitchingDetail": "detail", "WingLeft": "wing_wall", "WingRight": "wing_wall", "PlanBox": "box"}[name]
            comps.append({"name": name, "type": typ, "level": "component", "regions": [rid], "confidence": 0.9})
        else:
            typ = "slab" if "Slab" in name else "wall" if "Wall" in name else "haunch"
            comps.append({"name": name, "type": typ, "level": "component", "parent": parent, "regions": [rid], "confidence": 0.9})
    # the cells: the voids the members enclose
    used = set(region_of.values())
    cells = sorted((r for r in topo.regions if r.id not in used and not r.pattern and r.bbox[1] >= b.bottom / um - 1e-6
                    and r.bbox[3] <= (b.bottom + b.height) / um + 1e-6 and r.bbox[0] >= -1e-6 and r.bbox[2] <= b.width / um + 1e-6),
                   key=lambda r: r.bbox[0])
    for k, r in enumerate(cells):
        comps.append({"name": f"Cell{k + 1}", "type": "cell", "level": "subcomponent", "parent": parent, "regions": [r.id]})
    v = {d.id: d.value * um for d in an.datums.values()}

    def line(axis, at):
        return min((d for d in an.datums.values() if d.axis == axis), key=lambda d: abs(d.value * um - at)).id

    def occ(pairs):
        ids = [(line(ax, lo), line(ax, hi)) for ax, lo, hi in pairs]
        for c in an.clusters.values():
            got = {(an.gaps[g].a, an.gaps[g].b) for g in c.gaps}
            want = set(ids)
            if want <= got:
                return c.id, [g for g in c.gaps if (an.gaps[g].a, an.gaps[g].b) in want]
        return None, ids

    f = faces(b)
    sizes = {
        "ClearSpan": [("x", f[1 + 2 * k], f[2 + 2 * k]) for k in range(b.cells)],
        "OuterWall": [("x", 0.0, b.wall), ("x", b.width - b.wall, b.width)],
        "TopSlab": [("y", b.bottom + b.height, b.bottom + b.height + b.top)],
        "BottomSlab": [("y", 0.0, b.bottom)],
    }
    params = []
    for name, pairs in sizes.items():
        if names is not None and name not in names:
            continue
        cid, gids = occ(pairs)
        if cid:
            params.append({"name": name, "label": name, "component": "Box", "kind": "length", "candidate": cid,
                           "occurrences": gids, "value": abs(pairs[0][2] - pairs[0][1])})
        else:
            a, c = gids[0]
            params.append({"name": name, "label": name, "component": "Box", "kind": "length", "from_datum": a, "to_datum": c,
                           "value": abs(v[c] - v[a])})
    ans = copy.deepcopy(EMPTY_ANSWER)
    ans.update(structure_type="RCC box culvert", family="rcc_box", components=comps, parameters=params,
               levels=[{"datum": line("y", b.bottom), "name": "BedLevel", "role": "site_input"}])
    return ans


# ── the cases ────────────────────────────────────────────────────────────────────


@dataclass
class Case:
    id: str
    instruction: str
    box: Box = field(default_factory=Box)
    decisions: dict = field(default_factory=dict)  # what the person answers to the questions the engine must ask
    expect_driver: str | None = "ClearSpan"
    expect_value: float | None = None
    expect_modes: dict = field(default_factory=dict)  # part / value → mode the reading must give it
    expect_questions: list[str] = field(default_factory=list)  # "anchor", "D…", "attached:…": must be ASKED (ambiguous)
    expect_anchor: str | None = None  # the policy the plan ends with
    foundation: str = "follow"  # how the foundation is expected to behave: follow | keep_fixed
    wings: str = "follow"
    ambiguous: bool = False  # the right outcome is a question, not an edit
    category: str = "supported"


CASES = [
    Case("C01", "Reduce the clear span to 2500 mm. Maintain the outer wall thickness. Keep the foundation fixed. "
                "Keep the cells centred about the centre line.",
         expect_value=2500, expect_modes={"OuterWall": "keep_value", "Foundation": "keep_fixed"}, expect_anchor="centered",
         foundation="keep_fixed", decisions={"attached:WingLeft": "follow", "attached:WingRight": "follow"}),
    Case("C02", "Increase the clear span to 3600. The left side stays fixed. Wing walls follow the box. Maintain wall and slab thicknesses.",
         expect_value=3600, expect_anchor="start_fixed", expect_modes={"WingLeft": "follow", "WingRight": "follow"},
         decisions={"attached:Foundation": "follow"}),
    Case("C03", "Set the clear span to 2750 mm, grow to the left. Keep the bed level fixed. Update connected geometry and every affected view. "
                "Do not modify the unrelated pitching detail.",
         expect_value=2750, expect_anchor="end_fixed", expect_modes={"BedLevel": "keep_fixed", "PitchingDetail": "exclude"}),
    Case("C04", "Reduce the clear span to 2600. Do not touch the foundation.", expect_value=2600,
         expect_questions=["anchor"], ambiguous=True, category="ambiguous"),
    Case("C05", "Reduce the clear span. Maintain wall and slab thicknesses. Keep the designated bed level fixed. Preserve the foundation. "
                "Update connected geometry and every affected view. Keep unrelated details unchanged.",
         expect_questions=["anchor"], ambiguous=True, category="ambiguous"),
    Case("C06", "Reduce the clear span to 2400, symmetric about the centre line. Leave the foundation as it is.",
         expect_value=2400, expect_anchor="centered", ambiguous=True, category="ambiguous"),
    Case("C07", "Increase the clear span by 400, centred. Keep the foundation fixed. Wing walls stay attached to the box.",
         box=Box(cells=3, span=2500, mid=250), expect_value=2900, expect_anchor="centered", foundation="keep_fixed",
         expect_modes={"Foundation": "keep_fixed", "WingLeft": "follow", "WingRight": "follow"}),
    Case("C08", "Change the clear span to 3500, right side fixed. The foundation follows the box. Wing walls follow the box.",
         box=Box(cells=1, span=3000), expect_value=3500, expect_anchor="end_fixed",
         expect_modes={"Foundation": "follow", "WingLeft": "follow", "WingRight": "follow"}),
    Case("C09", "Widen the opening to 3300 mm.", expect_driver="ClearSpan", expect_value=3300, expect_questions=["anchor"],
         ambiguous=True, category="ambiguous"),
    Case("C10", "Reduce the barrel width to 2500.", expect_driver=None, expect_questions=["driver"], ambiguous=True, category="unsupported"),
]


# generated cases: every phrasing of every part of a request, on boxes of 1 to 4 cells — the expectations follow from
# the case's own parameters (the generator draws the intended result), never written by hand
DRIVERS = [("Reduce the clear span to {v} mm", "abs"), ("Set the clear span to {v}", "abs"), ("Change the clear span to {v} mm", "abs"),
           ("ClearSpan = {v}", "abs"), ("Increase the clear span by {d}", "by+"), ("Decrease the clear span by {d}", "by-")]
ANCHORS = {"centered": ["centred", "symmetric about the centre line", "keep it centred", "about the centerline"],
           "start_fixed": ["the left side stays fixed", "keep the left end in place", "grow to the right"],
           "end_fixed": ["the right side stays fixed", "grow to the left", "keep the right end in place"]}
FOUNDATION = {"keep_fixed": ["Keep the foundation fixed", "The foundation stays where it is", "Do not move the foundation", "Hold the foundation"],
              "follow": ["The foundation follows the box", "The foundation moves with the box"],
              "ambiguous": ["Do not touch the foundation", "Leave the foundation alone", "Preserve the foundation"]}
WINGS = ["Wing walls follow the box", "The wing walls move with the box", "Wing walls stay attached to the box"]
DETAIL = ["Do not modify the unrelated pitching detail", "Exclude the pitching detail", "Ignore the pitching detail"]


def generated_cases(n: int = 40, seed: int = 7) -> list[Case]:
    import random

    rnd = random.Random(seed)
    out = []
    for k in range(n):
        cells = rnd.choice([1, 2, 2, 3, 4])
        span = rnd.choice([2000.0, 2500.0, 3000.0, 3500.0])
        b = Box(cells=cells, span=span, wall=rnd.choice([250.0, 300.0, 350.0, 400.0]), mid=rnd.choice([250.0, 300.0]),
                height=rnd.choice([2000.0, 2500.0, 3000.0]), haunch=rnd.choice([0.0, 150.0, 150.0]))
        d = rnd.choice([200.0, 300.0, 500.0])
        drv, how = rnd.choice(DRIVERS)
        if how == "by-" or (how == "abs" and rnd.random() < 0.5):
            value = span - d
        else:
            value = span + d
        text = drv.format(v=f"{value:g}", d=f"{d:g}")
        policy = rnd.choice(list(ANCHORS))
        found = rnd.choice(["keep_fixed", "keep_fixed", "follow", "ambiguous"])
        clauses = [f"{text}, {rnd.choice(ANCHORS[policy])}", rnd.choice(FOUNDATION[found]), rnd.choice(WINGS), rnd.choice(DETAIL)]
        rnd.shuffle(clauses[1:])
        amb = found == "ambiguous"
        out.append(Case(f"G{k + 1:02d}", ". ".join(clauses) + ".", box=b, expect_value=value, expect_anchor=None if amb else policy,
                        expect_modes={} if amb else {"Foundation": found, "WingLeft": "follow", "PitchingDetail": "exclude"},
                        expect_questions=["D"] if amb else [], foundation="keep_fixed" if amb else found, ambiguous=amb,
                        category="ambiguous" if amb else "supported"))
    return out


# ── real drawings: no ground truth to compare with — the engine must ask where the drawing does not say, and what it
# does must measure right ─────────────────────────────────────────────────────────


def real_cases(fixtures: Path | None = None) -> list[dict]:
    from .crossview import EMPTY_ANSWER
    from .topology import of

    root = Path(__file__).resolve().parents[2]
    out = []
    path = root / "examples" / "two_cell_box_section.dxf"
    if path.exists():
        def two_cell(sm):
            uid = next(iter(sm.units))
            u = sm.unit(uid)
            regions = of(u.an).regions
            concrete = max(regions, key=lambda r: len(r.holes))
            cells = sorted((r for r in regions if r.parent == concrete.id), key=lambda r: r.bbox[0])
            pcc = next(r for r in regions if r is not concrete and r not in cells)
            um = u.sub.units_mm
            span = next(c for c in u.an.clusters.values() if c.kind.value == "void" and round(c.value * um) == 3000 and c.axes == {"x"})
            ans = {**copy.deepcopy(EMPTY_ANSWER), "components": [
                {"name": "Box", "type": "box", "level": "assembly", "regions": [concrete.id]},
                {"name": "CellLeft", "type": "cell", "level": "subcomponent", "parent": "Box", "regions": [cells[0].id]},
                {"name": "CellRight", "type": "cell", "level": "subcomponent", "parent": "Box", "regions": [cells[1].id]},
                {"name": "PccCourse", "type": "courses", "regions": [pcc.id]}],
                "parameters": [{"name": "ClearSpan", "label": "", "component": "Box", "candidate": span.id, "occurrences": "all", "value": 3000.0}]}
            sm.commit_answer(uid, ans)
            return uid
        out += [{"id": "R1", "path": str(path), "setup": two_cell, "instruction": "Reduce the clear span to 2600 mm.", "expect": "asks anchor"},
                {"id": "R2", "path": str(path), "setup": two_cell, "instruction": "Reduce the clear span to 2600 mm, centred. The PCC course follows the box.",
                 "expect": "verified"}]
    gad = (fixtures or root.parent / "aagento-bridge" / "public" / "test-fixtures" / "dxf") / "gad_ezdxf_a.dxf"
    if gad.exists():
        def barrel(sm):
            sec = next(g.id for g in sm.layout.views() if g.name == "LONGITUDINAL SECTION(X-X)")
            uid = sm.unit_of_view[sec]
            u = sm.unit(uid)
            cid = min((c for c in u.an.clusters.values() if c.axes == {"x"}), key=lambda c: abs(c.value * u.sub.units_mm - 11740)).id
            sm.share("BarrelLength", [(uid, cid)])
            return uid
        out += [{"id": "R3", "path": str(gad), "setup": barrel, "instruction": "Increase the barrel length to 13000.", "expect": "asks anchor"},
                {"id": "R4", "path": str(gad), "setup": barrel, "instruction": "Increase the barrel length to 13000, the upstream end stays fixed.",
                 "expect": "verified"}]
    return out


def run_real(case: dict) -> dict:
    from .crossview import SheetError, SheetModel

    t0 = time.perf_counter()
    sm = SheetModel.open(case["path"])
    uid = case["setup"](sm)
    out = {"id": case["id"], "category": "real drawing", "instruction": case["instruction"], "scores": {}, "notes": ["no ground truth: measured promises only"]}
    plan = sm.plan(uid, {"instruction": case["instruction"]})
    out["plan_status"] = plan["status"]
    out["questions"] = [q["text"][:160] for q in plan["questions"]]
    if case["expect"] == "asks anchor":
        out["scores"]["asks instead of guessing"] = any(q["about"] == "anchor" for q in plan["questions"]) and plan["status"] != "ready"
    else:
        decisions = {q["about"]: q.get("recommended") or (q["options"] or [""])[0] for q in plan["questions"]}
        try:
            res = sm.apply_plan(uid, {"instruction": case["instruction"], "decisions": decisions})
            out["scores"]["applied"] = True
            out["scores"]["verified"] = bool(res["checks"] and res["checks"]["ok"])
            out["failed_checks"] = [f"{c['check']} {c['target']}: {c['measured']}" for c in (res["checks"] or {}).get("checks", []) if c["status"] == "fail"]
        except SheetError as exc:
            out["scores"]["applied"] = False
            out["refused"] = str(exc)[:400]
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


# ── scoring ──────────────────────────────────────────────────────────────────────


def _expected_points(b: Box, value: float, anchor: str, foundation: str, wings: str) -> dict[str, list[tuple[float, float]]]:
    nb = replace(b, span=value)
    W0, W1 = b.width, nb.width
    x0 = 0.0 if anchor == "start_fixed" else W0 - W1 if anchor == "end_fixed" else (W0 - W1) / 2
    pcc = (-b.pcc, W0 + b.pcc) if foundation == "keep_fixed" else None
    wa = (0.0, W0) if wings == "keep_fixed" else None
    return members(nb, x0, pcc_box=pcc, wings_at=wa)


def run_case(case: Case, workdir: Path) -> dict:
    from .crossview import SheetError, SheetModel
    from .plan import build_plan

    t0 = time.perf_counter()
    g = box_gad(workdir / f"{case.id}.dxf", case.box)
    b = g["box"]
    sm = SheetModel.open(g["path"])
    uid = next((k for k, u in sm.units.items() if len(u.views) >= 2), None) or max(sm.units, key=lambda k: len(sm.units[k].items))
    sm.commit_answer(uid, box_answer(sm, uid, b, g["handles"]))
    u = sm.unit(uid)
    out: dict = {"id": case.id, "category": case.category, "instruction": case.instruction, "scores": {}, "notes": []}
    plan = build_plan(u.prog, u.answer, {"instruction": case.instruction}, sheet=sm._plan_sheet(uid))
    sc = out["scores"]
    drv = (plan.get("driver") or {}).get("parameter")
    sc["driver"] = drv == case.expect_driver
    if case.expect_value is not None:
        sc["value"] = abs(((plan.get("driver") or {}).get("requested_value") or math.nan) - case.expect_value) < 1e-6
    modes: dict[str, set[str]] = {}  # a part may have a behaviour and an invariant (follow + keep its thickness)
    for d in plan["directives"]:
        if d["kind"] != "generic":
            modes.setdefault(d["target"], set()).add(d["mode"])
    for tgt, m in case.expect_modes.items():
        sc[f"mode {tgt}"] = m in modes.get(tgt, set())
    asked = {q["about"] for q in plan["questions"]}
    for q in case.expect_questions:  # "D": a question about some directive (the ambiguous one)
        sc[f"asks {q}"] = q in asked or any(a.startswith(q) for a in asked)
    out["plan_status"] = plan["status"]
    out["questions"] = [q["text"][:160] for q in plan["questions"]]
    out["conflicts"] = plan["conflicts"]
    if case.ambiguous and case.category != "ambiguous":
        sc["no edit without a decision"] = plan["status"] != "ready"
    if case.category in ("ambiguous", "unsupported"):
        sc["asks instead of guessing"] = plan["status"] in ("needs_decision", "conflict", "draft")
        out["seconds"] = round(time.perf_counter() - t0, 2)
        return out
    # the person's answers to what had to be asked, then apply
    decisions = dict(case.decisions)
    if plan["status"] == "needs_decision":
        for q in plan["questions"]:  # the person: the foundation and wings as the case intends, anything else as recommended
            if q["about"] not in decisions and q["about"].startswith("attached:"):
                part = q["about"].split(":", 1)[1]
                decisions[q["about"]] = (case.foundation if part == "Foundation" else case.wings if part.startswith("Wing")
                                         else q.get("recommended") or "keep_fixed")
        plan = build_plan(u.prog, u.answer, {"instruction": case.instruction, "decisions": decisions}, sheet=sm._plan_sheet(uid))
    anc = (plan.get("anchor") or {}).get("policy")
    if case.expect_anchor:
        sc["anchor"] = anc == case.expect_anchor
    # where the intended box would run into the unrelated detail, the right outcome is a refusal, not an edit
    W1 = replace(b, span=case.expect_value).width
    x0 = 0.0 if case.expect_anchor == "start_fixed" else b.width - W1 if case.expect_anchor == "end_fixed" else (b.width - W1) / 2
    must_refuse = b.detail and x0 + W1 > b.detail_x
    try:
        res = sm.apply_plan(uid, {"instruction": case.instruction, "decisions": decisions})
    except SheetError as exc:
        out["refused"] = str(exc)[:400]
        if must_refuse:
            sc["refuses a clash"] = "clash" in str(exc)
        else:
            sc["applied"] = False
        out["seconds"] = round(time.perf_counter() - t0, 2)
        return out
    if must_refuse:
        sc["refuses a clash"] = False
        out["seconds"] = round(time.perf_counter() - t0, 2)
        return out
    sc["applied"] = True
    checks = res["checks"] or {}
    sc["verified"] = bool(checks.get("ok"))
    out["failed_checks"] = [f"{c['check']} {c['target']}: {c['measured']}" for c in checks.get("checks", []) if c["status"] == "fail"]
    # the regenerated sheet against the generator's own drawing of the new size
    sr = sm.regenerate()
    want = _expected_points(b, case.expect_value, anc or "centered", case.foundation, case.wings)
    hidx = {it.handle: it.index for it in sm.dr.items}
    worst, wrong = 0.0, []
    for name, h in g["handles"].items():
        pts = sr.reg.pts.get(hidx[h], sm.dr.items[hidx[h]].pts)
        exp = want[name]
        d = max(min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in exp) for p in pts[:len(exp)])
        worst = max(worst, d)
        if d > 0.5:
            wrong.append(f"{name} off by {d:.1f} mm")
    sc["geometry matches intent"] = not wrong
    out["wrong_members"] = wrong[:8]
    cl = sm.dr.items[hidx[g["centre_handle"]]]
    cpts = sr.reg.pts.get(cl.index, cl.pts)
    W1 = replace(b, span=case.expect_value).width
    x0 = 0.0 if anc == "start_fixed" else b.width - W1 if anc == "end_fixed" else (b.width - W1) / 2
    sc["centre line follows the box"] = abs(cpts[0][0] - (x0 + W1 / 2)) <= 0.5
    views = res["applied"]["by_view"] if res.get("applied") else {}
    sc["both views follow"] = len([v for v in views if v]) >= (2 if b.plan else 1)
    labels = _dim_texts(sm, sr)
    sc["dimensions read the new span"] = labels.count(f"{case.expect_value:g}") >= b.cells
    # the person's value survives a refused edit: try a plan that must be refused, then check
    before = dict(sm.values.get(uid, {}))
    try:
        sm.apply_plan(uid, {"instruction": "Change the clear span to 100000. The left side stays fixed."})
        sc["refusal keeps the person's values"] = False
    except SheetError:
        sc["refusal keeps the person's values"] = sm.values.get(uid, {}) == before
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


def _dim_texts(sm, sr) -> list[str]:
    from .display import primitives

    out = []
    for it in sm.dr.items:
        if it.dxftype != "DIMENSION":
            continue
        for p in primitives(it, sr.reg.pts.get(it.index, it.pts), None, None, sm.dr.units_mm):
            if p["k"] == "t":
                out.append(p["text"])
    return out


CATEGORY = {"driver": "instruction → parameter", "value": "instruction → parameter", "mode": "instruction → parts / exclusions",
            "asks": "asks when it must", "anchor": "anchor", "applied": "regeneration and commit", "verified": "invariants (measured)",
            "geometry matches intent": "whole assembly follows intent", "centre line follows the box": "affected components",
            "both views follow": "cross-view", "dimensions read the new span": "dimensions and annotations",
            "refusal keeps the person's values": "protection of a person's values", "no edit without a decision": "asks when it must",
            "asks instead of guessing": "asks when it must", "refuses a clash": "regeneration and commit"}


def run(out_path: str | None = None, cases: list[Case] | None = None, generated: int = 40, real: bool = True) -> dict:
    work = Path(tempfile.mkdtemp(prefix="plan-bench-"))
    todo = cases if cases is not None else CASES + generated_cases(generated)
    rows = []
    for c in todo:
        d = work / c.id
        d.mkdir(exist_ok=True)
        rows.append(run_case(c, d))
    if real and cases is None:
        rows += [run_real(c) for c in real_cases()]
    cats: dict[str, list[bool]] = {}
    for r in rows:
        for k, ok in r["scores"].items():
            cats.setdefault(CATEGORY.get(k.split(" ")[0] if k.split(" ")[0] in ("mode", "asks") else k, k), []).append(bool(ok))
    summary = {c: {"passed": sum(v), "of": len(v), "rate": round(sum(v) / len(v), 3)} for c, v in sorted(cats.items())}
    by_kind = {}
    for kind in ("supported", "ambiguous", "unsupported", "real drawing"):
        rs = [r for r in rows if r["category"] == kind]
        allv = [ok for r in rs for ok in r["scores"].values()]
        by_kind[kind] = {"cases": len(rs), "checks_passed": sum(allv), "of": len(allv),
                         "cases_fully_right": sum(all(r["scores"].values()) for r in rs)}
    res = {"cases": rows, "by_category": summary, "by_kind": by_kind}
    if out_path:
        Path(out_path).write_text(json.dumps(res, indent=1, default=str))
    return res
