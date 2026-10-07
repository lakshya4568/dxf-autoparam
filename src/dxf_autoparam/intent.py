"""Design intent, checked by measurement: the parts, what each parameter does to them, what must stay true,
and what a person chose to keep as drawn.

The AI says what is SUPPOSED to happen ("when ClearSpan increases the top slab grows, the walls keep their
thickness, the bed level stays"). This module never takes that on trust: it changes each parameter in the
model, regenerates, measures every part, and compares. A constraint the model does not keep is enforced by
rewriting one set-out formula when that is possible in closed form (distance, symmetry, centring, equality,
fixed); otherwise it is reported back.

    parts   = resolve_parts(prog, answer)               # name → Part (regions, entities, set-out lines)
    impact  = measure_impact(prog, parts)               # param → part → {"x": grows|shrinks|moves|fixed, …}
    rows    = check_behaviours(prog, answer, parts, impact, rep)
    rows    = check_constraints(prog, answer, parts, rep)
    apply_selection(prog, parts, hold, exclude, rep)
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass, field

from .cadjson import entity_index
from .ir import Datum
from .program import ExprError, Program, names_in
from .regen import regenerate_program
from .topology import DatumIndex, of

AXES = ("x", "y")


@dataclass
class Part:
    name: str
    type: str = ""
    level: str = "component"
    parent: str | None = None
    datums: set[str] = field(default_factory=set)  # set-out lines it is drawn on (its own outline's, not its neighbours')
    nodes: set[tuple[str, str]] = field(default_factory=set)  # its outline's corners, as (x line, y line)
    edges: list[tuple[tuple[str, str], tuple[str, str]]] = field(default_factory=list)  # outline edges between corners
    circles: set[int] = field(default_factory=set)  # circles / arcs on its outline (centre + radius)
    regions: list[str] = field(default_factory=list)
    entities: set[int] = field(default_factory=set)  # entities named as its own
    existing: bool = False
    parametrize: bool = True
    own_datums: set[str] = field(default_factory=set)  # its own outline's lines, before an assembly gathers its parts'


# ── parts ────────────────────────────────────────────────────────────────────────


def resolve_parts(an, answer: dict | None) -> tuple[dict[str, Part], list[str]]:
    """Each named part with its outline (corners on set-out lines) and the lines it is drawn on; an assembly holds
    what its descendants hold. Without an answer, every region is a part of its own (what geometry alone can say).

    A part is measured on its OWN outline: an entity drawn along the edge two regions share (a slab's soffit that
    is also the cell's top) belongs to both outlines, but its far end does not make the neighbour part of it."""
    topo = of(an)
    regions = topo.by_id()
    dix = DatumIndex(an)
    items = an.drawing.items
    unknown: list[str] = []
    parts: dict[str, Part] = {}
    comps = (answer or {}).get("components") or [{"name": r.id, "regions": [r.id], "level": "component"} for r in topo.regions]
    for c in comps:
        p = Part(name=c.get("name", ""), type=c.get("type", ""), level=c.get("level", "component"), parent=c.get("parent"),
                 existing=bool(c.get("existing")), parametrize=c.get("parametrize", True) is not False)
        for rid in c.get("regions", []):
            r = regions.get(rid)
            if r is None:
                unknown.append(rid)
                continue
            p.regions.append(rid)
            for ring in [r.ring, *r.holes]:
                corners = [(dix.at("x", q[0]), dix.at("y", q[1])) for q in ring]
                for k, nd in enumerate(corners):
                    if nd[0] and nd[1]:
                        p.nodes.add(nd)
                        p.datums.update(nd)
                        nxt = corners[(k + 1) % len(corners)]
                        if nxt[0] and nxt[1] and nxt != nd:
                            p.edges.append((nd, nxt))
            p.circles |= {i for i in r.items if items[i].dxftype in ("CIRCLE", "ARC")}
        for eid in list(c.get("entities", [])) + list(c.get("outlines", [])):
            i = entity_index(eid)
            if i is None or not 0 <= i < len(items):
                unknown.append(eid)
                continue
            p.entities.add(i)
            if items[i].dxftype in ("CIRCLE", "ARC"):
                p.circles.add(i)
            for k in items[i].vertex_pts or range(len(items[i].pts)):
                bx, by = an.slot_datum.get((i, k, "x")), an.slot_datum.get((i, k, "y"))
                if bx and by and abs(bx[1]) <= an.drawing.tol and abs(by[1]) <= an.drawing.tol:
                    p.nodes.add((bx[0], by[0]))
                    p.datums.update((bx[0], by[0]))
        for d in c.get("datums", []):
            if d in an.datums:
                p.datums.add(d)
            else:
                unknown.append(d)
        p.own_datums = set(p.datums)
        parts[p.name] = p
    children: dict[str, list[str]] = {}
    for p in parts.values():
        if p.parent and p.parent in parts and p.parent != p.name:
            children.setdefault(p.parent, []).append(p.name)

    def fill(name: str, seen: set[str]) -> None:
        for ch in children.get(name, []):
            if ch in seen:
                continue
            fill(ch, seen | {ch})
            q = parts[name]
            q.nodes |= parts[ch].nodes
            q.datums |= parts[ch].datums
            q.edges += parts[ch].edges
            q.circles |= parts[ch].circles

    for name in list(parts):
        fill(name, {name})
    return parts, unknown


def descendants(parts: dict[str, Part], name: str) -> set[str]:
    out, stack = set(), [name]
    while stack:
        n = stack.pop()
        for p in parts.values():
            if p.parent == n and p.name not in out and p.name != name:
                out.add(p.name)
                stack.append(p.name)
    return out


# ── measuring ────────────────────────────────────────────────────────────────────


def _geometry(prog: Program, values: dict[str, float] | None = None) -> tuple[dict[str, float], dict[int, tuple]]:
    """Set-out lines (drawing units) and circles (centre, radius) for these values — closed form, no regeneration."""
    an = prog.analysis
    dv = {d.id: d.value for d in an.datums.values()}
    dv.update(prog.datum_values(values))
    radii = prog.radii(values)
    circles = {}
    for it in an.drawing.items:
        if it.dxftype in ("CIRCLE", "ARC"):
            bx, by = an.slot_datum.get((it.index, 0, "x")), an.slot_datum.get((it.index, 0, "y"))
            if bx and by:
                circles[it.index] = (dv[bx[0]] + bx[1], dv[by[0]] + by[1], radii.get(it.index, it.radius or 0.0))
    return dv, circles


def _boxes(parts: dict[str, Part], geo) -> dict[str, tuple[float, float, float, float] | None]:
    dv, circles = geo
    out = {}
    for name, p in parts.items():
        xs = [dv[x] for x, _y in p.nodes]
        ys = [dv[y] for _x, y in p.nodes]
        for i in p.circles:
            if i in circles:
                cx, cy, r = circles[i]
                xs += [cx - r, cx + r]
                ys += [cy - r, cy + r]
        out[name] = (min(xs), min(ys), max(xs), max(ys)) if xs and ys else None
    return out


def _thr(prog: Program) -> float:
    an = prog.analysis
    return max(an.drawing.tol * an.drawing.units_mm * 2, 0.5)  # mm


def delta_of(prog: Program, name: str) -> float:
    p = prog.params[name]
    return 0.5 if p.kind == "level" else max(abs(p.value) * 0.1, 50.0)


def classify(b0, b1, thr_units: float) -> dict:
    """How a part's extent changed, per axis: grows / shrinks / moves / fixed, with the numbers (mm in `d`)."""
    out = {}
    for k, ax in enumerate(AXES):
        s0, s1 = b0[k + 2] - b0[k], b1[k + 2] - b1[k]
        c0, c1 = (b0[k] + b0[k + 2]) / 2, (b1[k] + b1[k + 2]) / 2
        if s1 - s0 > thr_units:
            out[ax] = "grows"
        elif s0 - s1 > thr_units:
            out[ax] = "shrinks"
        elif abs(c1 - c0) > thr_units:
            out[ax] = "moves"
        else:
            out[ax] = "fixed"
        out[f"d{ax}"] = (s1 - s0, c1 - c0, b1[k] - b0[k], b1[k + 2] - b0[k + 2])  # size, centre, low side, high side
    return out


def measure_impact(prog: Program, parts: dict[str, Part], params: list[str] | None = None) -> dict:
    """param → part → classification, for a +step on each parameter. The engine's own answer to 'what changes'."""
    an = prog.analysis
    thr = _thr(prog) / an.drawing.units_mm
    b0 = _boxes(parts, _geometry(prog))
    out: dict = {"_step": {}, "_base": b0}
    for name in params if params is not None else list(prog.params):
        if name not in prog.params:
            continue
        dv = delta_of(prog, name)
        geo = _geometry(prog, {name: prog.params[name].value + dv})
        b1 = _boxes(parts, geo)
        g0 = _geometry(prog)[0]
        row = {}
        for pn, part in parts.items():
            if b0[pn] is None or b1[pn] is None:
                continue
            m = classify(b0[pn], b1[pn], thr)
            # a part whose outer box stays but whose corners move changes shape inside it (a soffit rising between two
            # fixed levels): that is not "fixed"
            m["inside"] = sum(1 for xd, yd in part.nodes if abs(geo[0][xd] - g0[xd]) > thr or abs(geo[0][yd] - g0[yd]) > thr)
            row[pn] = m
        out[name] = row
        out["_step"][name] = (dv, geo)
    return out


def impact_summary(impact: dict, parts: dict[str, Part]) -> dict[str, dict[str, str]]:
    """param → part → 'grows x, moves y' (only parts that change), for people."""
    out: dict[str, dict[str, str]] = {}
    for name, row in impact.items():
        if name.startswith("_"):
            continue
        out[name] = {}
        for pn, m in row.items():
            if parts[pn].level == "subcomponent" and parts[pn].parent in row:
                continue
            words = [f"{m[ax]} {ax}" for ax in AXES if m[ax] != "fixed"]
            if not words and m.get("inside"):
                words = [f"reshapes inside ({m['inside']} corners move)"]
            if words:
                out[name][pn] = ", ".join(words)
    return out


# ── behaviours ───────────────────────────────────────────────────────────────────


def _angles(part: Part, dv: dict[str, float], tol: float) -> list[float]:
    """Angles of the part's inclined outline edges."""
    out = []
    for (xa, ya), (xb, yb) in part.edges:
        dx, dy = dv[xb] - dv[xa], dv[yb] - dv[ya]
        if abs(dx) > tol and abs(dy) > tol:
            out.append(math.degrees(math.atan2(dy, dx)) % 180.0)
    return out


def _touching(b1, b2, thr: float) -> bool:
    return b1[0] - thr <= b2[2] and b2[0] - thr <= b1[2] and b1[1] - thr <= b2[3] and b2[1] - thr <= b1[3]


def _mirror_partner(parts_b0: dict, name: str, axis_value: float, thr: float) -> str | None:
    b = parts_b0.get(name)
    if b is None:
        return None
    for other, o in parts_b0.items():
        if o is None:
            continue
        if abs(o[0] - (2 * axis_value - b[2])) <= thr and abs(o[2] - (2 * axis_value - b[0])) <= thr and abs(o[1] - b[1]) <= thr and abs(o[3] - b[3]) <= thr:
            return other
    return None


def check_behaviours(prog: Program, answer: dict, parts: dict[str, Part], impact: dict, rep, held: set[str]) -> list[dict]:
    an = prog.analysis
    u = an.drawing.units_mm
    thr = _thr(prog) / u
    level_datum = {lv.get("name"): lv.get("datum") for lv in answer.get("levels", [])}
    relations = {r.name: r for r in prog.relations}
    b0 = impact.get("_base", {})
    axis_x = an.global_axis.get("x")
    rows = []
    for beh in answer.get("behaviours", []):
        pname = beh.get("parameter")
        if pname not in prog.params:
            rep.warn("V12", str(pname), f"behaviour of {pname}: no such parameter (it may have been rejected or frozen)")
            continue
        dv, geo1 = impact["_step"].get(pname, (None, None))
        if geo1 is None:
            continue
        row_imp = impact.get(pname, {})
        for eff in beh.get("effects", []):
            target, want, axis = eff.get("target"), eff.get("behaviour"), eff.get("axis")
            res = {"parameter": pname, "target": target, "behaviour": want, "axis": axis, "status": "unchecked", "measured": ""}
            axes = AXES if axis in (None, "both") else (axis,)
            if target in held:
                res.update(status="held", measured="held as drawn by your selection")
            elif target in relations and target not in row_imp:  # a name that is both a part and a quantity is the part
                v0 = prog.relation_value(relations[target])
                v1 = prog.relation_value(relations[target], {pname: prog.params[pname].value + dv})
                got = "grows" if v1 - v0 > _thr(prog) else "shrinks" if v0 - v1 > _thr(prog) else "fixed"
                ok = got == want or (want in ("keeps_thickness", "keeps_level") and got == "fixed")
                res.update(status="confirmed" if ok else "contradicted", measured=f"{target} {got} ({v0:g} → {v1:g})")
            elif target in level_datum and level_datum[target] in an.datums:
                d = level_datum[target]
                y0 = prog.datum_values()[d] if d in prog.formulas else an.datums[d].value
                y1 = prog.datum_values({pname: prog.params[pname].value + dv}).get(d, y0)
                moved = abs(y1 - y0) > thr
                got = "moves" if moved else "fixed"
                ok = (want in ("fixed", "keeps_level") and not moved) or (want == "moves" and moved)
                res.update(status="confirmed" if ok else "contradicted", measured=f"{target} {got} ({(y1 - y0) * u:+.0f} mm)")
            elif target in row_imp:
                m = row_imp[target]
                res["measured"] = ", ".join(f"{m[ax]} {ax}" for ax in AXES)
                if want in ("grows", "shrinks", "moves"):

                    def has(ax: str, m=m, want=want) -> bool:
                        return abs(m[f"d{ax}"][1]) > thr if want == "moves" else m[ax] == want

                    ok = any(has(ax) for ax in AXES) if axis is None else all(has(ax) for ax in axes)
                elif want == "fixed":
                    ok = all(m[ax] == "fixed" for ax in axes)
                elif want == "keeps_thickness":
                    if axis in (None, "both"):  # its thinner direction is its thickness
                        bb = b0.get(target)
                        k = "x" if bb and (bb[2] - bb[0]) <= (bb[3] - bb[1]) else "y"
                        ok = abs(m[f"d{k}"][0]) <= thr
                    else:
                        ok = all(abs(m[f"d{ax}"][0]) <= thr for ax in axes)
                elif want == "keeps_level":
                    ok = abs(m["dy"][2]) <= thr
                elif want == "stays_centred":
                    ok = all(abs(m[f"d{ax}"][1]) <= thr for ax in (axes if axis not in (None,) else ("x",)))
                elif want == "stays_symmetric":
                    if axis_x is None:
                        res.update(status="unchecked", measured="the drawing has no symmetry axis")
                        rows.append(res)
                        continue
                    a = an.datums[axis_x].value
                    partner = _mirror_partner(b0, target, a, thr)
                    if partner is None:
                        res.update(status="unchecked", measured="no mirrored partner on this drawing")
                        rows.append(res)
                        continue
                    b1 = _boxes({k: parts[k] for k in {target, partner}}, geo1)
                    ax_new = prog.datum_values({pname: prog.params[pname].value + dv}).get(axis_x, a)
                    ok = _mirror_partner(b1, target, ax_new, thr) == partner
                elif want == "stays_connected":
                    b1 = _boxes(parts, geo1)
                    lost = [o for o, ob in b0.items() if o != target and ob is not None and b0.get(target) is not None
                            and o not in descendants(parts, target) and target not in descendants(parts, o)
                            and _touching(b0[target], ob, thr) and not _touching(b1[target], b1[o], thr)]
                    ok = not lost
                    if lost:
                        res["measured"] += f"; no longer touches {', '.join(lost[:3])}"
                elif want == "keeps_slope":
                    tol_u = an.drawing.tol
                    a0, a1 = _angles(parts[target], _geometry(prog)[0], tol_u), _angles(parts[target], geo1[0], tol_u)
                    ok = len(a0) == len(a1) and all(abs(x - y) < 0.01 for x, y in zip(a0, a1, strict=True))
                    res["measured"] += "; inclined edges keep their angle" if ok else "; an inclined edge changes its angle"
                else:
                    ok = False
                res["status"] = "confirmed" if ok else "contradicted"
            else:
                rep.warn("V12", f"{pname}→{target}", f"behaviour target {target!r} is not a component, level or relation")
                rows.append(res)
                continue
            if res["status"] == "confirmed":
                rep.ok("behaviour")
            elif res["status"] == "contradicted":
                rep.bad("behaviour", "V12", f"{pname}→{target}",
                        f"you said {target} {want}{'' if axis in (None, 'both') else ' in ' + axis} when {pname} increases; the model: {res['measured']}. "
                        f"Give the datum formulas that make it so (set its lines out from what it should follow), or correct the claim.")
            rows.append(res)
    return rows


# ── constraints ─────────────────────────────────────────────────────────────────


def _residual(c: dict, dv: dict[str, float], scope: dict[str, float], prog: Program) -> float | None:
    """How far a datum constraint is from holding (mm); None when it is not a datum constraint."""
    t, ds = c.get("type"), c.get("datums", [])
    try:
        if t == "distance" and len(ds) >= 2 and c.get("value"):
            from .program import evaluate

            return abs(dv[ds[1]] - dv[ds[0]]) - evaluate(c["value"], scope)
        if t in ("symmetric", "centred") and len(ds) >= 3:
            return dv[ds[0]] + dv[ds[1]] - 2 * dv[ds[2]]
        if t == "equal" and len(ds) >= 4:
            return (dv[ds[1]] - dv[ds[0]]) - (dv[ds[3]] - dv[ds[2]])
    except (KeyError, ExprError, ZeroDivisionError):
        return math.nan
    return None


def _datum_mm(prog: Program, values: dict[str, float] | None = None) -> dict[str, float]:
    an = prog.analysis
    u = an.drawing.units_mm
    out = {d.id: d.value * u for d in an.datums.values()}
    out.update({d: v * u for d, v in prog.datum_values(values).items()})
    return out


def _holds(prog: Program, c: dict, parts: dict[str, Part], tol: float, length_only: bool = False) -> tuple[bool | None, list[str]]:
    """(holds on the drawing now, parameters under which it breaks)."""
    t = c.get("type")
    scope0 = prog.defaults()
    # what must hold, must hold under the DESIGN INPUTS (named values, levels); leftover generic sizes nobody named are not inputs
    named = [n for n, p in prog.params.items() if p.source != "geometry" or p.kind == "level"]
    names = [n for n in (named or list(prog.params)) if not (length_only and prog.params[n].kind == "level")]

    def check(values: dict[str, float] | None) -> bool | None:
        scope = {**scope0, **(values or {})}
        dv = _datum_mm(prog, values)
        if t == "fixed":
            base = _datum_mm(prog)
            return all(abs(dv[d] - base[d]) <= tol for d in c.get("datums", []) if d in dv)
        res = _residual(c, dv, scope, prog)
        if res is not None:
            return not math.isnan(res) and abs(res) <= tol
        if t == "connected" and len(c.get("components", [])) >= 2:
            a, b = c["components"][:2]
            if a not in parts or b not in parts:
                return None
            bx = _boxes({a: parts[a], b: parts[b]}, _geometry(prog, values))
            return bx[a] is not None and bx[b] is not None and _touching(bx[a], bx[b], tol / prog.analysis.drawing.units_mm)
        if t == "slope" and c.get("components"):
            g0, g1 = _geometry(prog)[0], _geometry(prog, values)[0]
            for name in c["components"]:
                if name not in parts:
                    return None
                a0, a1 = _angles(parts[name], g0, prog.analysis.drawing.tol), _angles(parts[name], g1, prog.analysis.drawing.tol)
                if len(a0) != len(a1) or any(abs(x - y) > 0.01 for x, y in zip(a0, a1, strict=True)):
                    return False
            return True
        if t in ("parallel", "perpendicular", "collinear") and len(c.get("entities", [])) >= 2:
            pts = regenerate_program(prog, values, check=False).pts
            dirs = []
            for eid in c["entities"][:2]:
                i = entity_index(eid)
                if i is None or i not in pts or len(pts[i]) < 2:
                    return None
                (x0, y0), (x1, y1) = pts[i][0], pts[i][1]
                dirs.append(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0)
            diff = abs(dirs[0] - dirs[1]) % 180.0
            diff = min(diff, 180 - diff)
            return diff < 0.05 if t != "perpendicular" else abs(diff - 90) < 0.05
        return None

    now = check(None)
    if now is None:
        return None, []
    broken = []
    for n in names:
        if check({n: prog.params[n].value + delta_of(prog, n)}) is False:
            broken.append(n)
    return now, broken


def _enforce(prog: Program, c: dict, protected: set[str]) -> str | None:
    """Rewrite one set-out formula so the constraint holds by construction. Returns the datum rewritten."""
    t, ds = c.get("type"), c.get("datums", [])
    dmm = _datum_mm(prog)
    options: list[tuple[str, str]] = []
    if t == "distance" and len(ds) >= 2 and c.get("value"):
        a, b = ds[0], ds[1]
        sb = "+" if dmm.get(b, 0) >= dmm.get(a, 0) else "-"
        sa = "-" if sb == "+" else "+"
        options = [(b, f"{a} {sb} ({c['value']})"), (a, f"{b} {sa} ({c['value']})")]
    elif t in ("symmetric", "centred") and len(ds) >= 3:
        options = [(ds[1], f"2 * {ds[2]} - {ds[0]}"), (ds[0], f"2 * {ds[2]} - {ds[1]}")]
    elif t == "equal" and len(ds) >= 4:
        options = [(ds[3], f"{ds[2]} + ({ds[1]} - {ds[0]})"), (ds[2], f"{ds[3]} - ({ds[1]} - {ds[0]})")]
    elif t == "fixed":
        options = [(d, f"{dmm[d]:.6f}".rstrip("0").rstrip(".")) for d in ds if d in dmm]
    done = None
    for d, expr in options:
        if d not in prog.formulas or d in protected:
            continue
        try:
            ast.parse(expr, mode="eval")
        except SyntaxError:
            continue
        old, old_origin = prog.formulas[d], prog.origin.get(d)
        prog.formulas[d] = expr
        prog.invalidate()
        try:
            prog.order()
            ok = abs(prog.datum_values()[d] * prog.analysis.drawing.units_mm - dmm[d]) <= 1e-6 + _thr(prog) * 0.01
        except (ExprError, KeyError, ZeroDivisionError):
            ok = False
        if ok:
            prog.origin[d] = "constraint"
            done = d
            if t != "fixed":
                break
            continue
        prog.formulas[d] = old
        if old_origin is not None:
            prog.origin[d] = old_origin
        prog.invalidate()
    return done


def check_constraints(prog: Program, answer: dict, parts: dict[str, Part], rep) -> list[dict]:
    tol = _thr(prog)
    known = set(prog.analysis.datums)
    rows = []
    levels = {n for n, p in prog.params.items() if p.kind == "level"}
    # lines the AI, a slope, a held part or a site level set out are not rewritten to satisfy another claim
    pinned = {d for d, o in prog.origin.items() if o in ("ai", "dimension", "existing", "held", "slope", "kept")} \
        | {d for d, e in prog.formulas.items() if names_in(e) & levels}
    for c in answer.get("constraints", []):
        t = c.get("type")
        label = c.get("description") or f"{t} {' '.join(c.get('datums') or c.get('components') or c.get('entities') or [])}"
        row = {"type": t, "label": label, "datums": c.get("datums", []), "components": c.get("components", []),
               "value": c.get("value"), "confidence": c.get("confidence"), "status": "unchecked", "enforced_on": None, "breaks_under": []}
        bad = [d for d in c.get("datums", []) if d not in known] + [p for p in c.get("components", []) if p not in parts]
        if c.get("value"):
            bad += [n for n in names_in(c["value"]) if n not in prog.params] if _parses(c["value"]) else [c["value"]]
        if bad:
            rep.bad("constraint", "V13", label, f"{label}: unknown ids or names {bad[:4]}")
            row["status"] = "rejected"
            rows.append(row)
            continue
        c = _named_value(prog, c, tol)
        now, broken = _holds(prog, c, parts, tol, length_only=(t == "fixed"))
        if now is None:
            rep.warn("V13", label, f"{label}: cannot be checked on this geometry")
            rows.append(row)
            continue
        if not now:
            rep.bad("constraint", "V13", label, f"{label} does not hold on the drawing as drawn")
            row["status"] = "false"
            rows.append(row)
            continue
        if broken:
            d = _enforce(prog, c, pinned)
            if d is not None:
                now, broken = _holds(prog, c, parts, tol, length_only=(t == "fixed"))
                row["enforced_on"] = d
                pinned.add(d)
        row["breaks_under"] = broken
        if broken:
            row["status"] = "now_only"
            sets = "; ".join(f"{d} = {prog.formulas.get(d, 'as drawn')}" for d in c.get("datums", [])[:4] if d in prog.formulas)
            rep.bad("constraint", "V13", label, f"{label} holds as drawn but not when {', '.join(broken[:4])} change"
                    + (f" (its lines: {sets})" if sets else "")
                    + " — two inputs set the same thing: make one a result (remove it or set its line from the other), or drop this")
        else:
            row["status"] = "always"
            rep.ok("constraint")
        rows.append(row)
    return rows


def _named_value(prog: Program, c: dict, tol: float) -> dict:
    """distance a→b = 400 where a named size of 400 drives a→b means 'stays that size': the number is that name."""
    if c.get("type") != "distance" or len(c.get("datums", [])) < 2 or not c.get("value"):
        return c
    try:
        v = float(c["value"])
    except (TypeError, ValueError):
        return c
    a, b = c["datums"][:2]
    an = prog.analysis
    v0 = {**{d.id: d.value for d in an.datums.values()}, **prog.datum_values()}
    for n, p in prog.params.items():
        if p.kind != "level" and abs(p.value - v) <= tol and _drives(prog, n, a, b, v0):
            return {**c, "value": n}
    return c


def _parses(expr: str) -> bool:
    try:
        ast.parse(expr, mode="eval")
        return True
    except SyntaxError:
        return False


# ── keeping the drawing valid when a value grows ─────────────────────────────────


def _same_axis_parent(prog: Program, d: str) -> str | None:
    an = prog.analysis
    ax = an.datums[d].axis
    for n in sorted(names_in(prog.formulas.get(d, ""))):
        if n in an.datums and an.datums[n].axis == ax and n != d:
            return n
    return None


def _still(prog: Program, parts: dict[str, Part], step: dict[str, float]) -> set[str]:
    """Parts that do not change at all for this step."""
    thr = _thr(prog) / prog.analysis.drawing.units_mm
    b0, b1 = _boxes(parts, _geometry(prog)), _boxes(parts, _geometry(prog, step))
    return {n for n in parts if b0[n] is not None and b1[n] is not None and all(v == "fixed" for k, v in classify(b0[n], b1[n], thr).items() if k in AXES)}


def heal_growth_breaks(prog: Program, names: list[str], protected: set[str], parts: dict[str, Part] | None = None,
                       may_move: dict[str, set[str]] | None = None) -> list[str]:
    """A named value that breaks an entity when it grows — one of the entity's lines follows the value, another
    is set out from something independent (a slope's foot hung on a far axis) — is healed by re-anchoring the
    independent line's chain on the line that moves, keeping its drawn offset. The nearest line of the chain that
    makes the drawing valid again is chosen; lines the AI, a slope, a held part or a site level set are not touched,
    and a heal may not set in motion a part that stood still unless the AI said it moves with that value
    (`may_move`: value → parts claimed to grow / shrink / move). Returns what was done, in words."""
    import re

    an = prog.analysis
    u = an.drawing.units_mm
    done: list[str] = []
    for name in names:
        if name not in prog.params:
            continue
        for _round in range(3):  # a heal can uncover the next break of the same value
            step = {name: prog.params[name].value + delta_of(prog, name)}
            r = regenerate_program(prog, step)
            if not r.issues:
                break
            m = re.match(r"\S+ (\S+) \(", r.issues[0])
            it = next((i for i in an.drawing.items if m and i.handle == m.group(1)), None)
            if it is None:
                break
            v0, v1 = prog.datum_values(), prog.datum_values(step)
            still = _still(prog, parts, step) if parts else set()
            allowed = _allowed(parts or {}, (may_move or {}).get(name, set()))
            ds = {an.slot_datum[(it.index, k, ax)][0] for k in it.vertex_pts for ax in AXES if (it.index, k, ax) in an.slot_datum}
            healed = False
            for axis in AXES:
                line = [d for d in ds if d in v0 and an.datums[d].axis == axis]
                moved = [d for d in line if abs(v1[d] - v0[d]) * u > 0.01]
                stayed = [d for d in line if d not in moved]
                if not moved or not stayed:
                    continue
                for d in stayed:
                    anchor = min(moved, key=lambda a, d=d: abs(v0[a] - v0[d]))
                    chain, x = [], d
                    while x and x not in chain and len(chain) < 8:
                        chain.append(x)
                        x = _same_axis_parent(prog, x)
                    for cand in chain:
                        if cand in protected or cand == anchor or cand not in prog.formulas or anchor in _depends_on(prog, cand):
                            continue
                        old = prog.formulas[cand]
                        off = (v0[cand] - v0[anchor]) * u
                        prog.formulas[cand] = f"{anchor} {'+' if off >= 0 else '-'} {abs(off):.6f}".rstrip("0").rstrip(".")
                        prog.invalidate()
                        try:
                            ok = not regenerate_program(prog, step).issues and not regenerate_program(prog).issues
                            if ok and parts:  # parts that stood still and nobody said move with this value stay still
                                ok = not ((still - _still(prog, parts, step)) - allowed)
                        except ExprError:
                            ok = False
                        if ok:
                            prog.origin[cand] = "kept"
                            done.append(f"{name}: {entity_label(it)} stayed valid by setting {cand} out from {anchor} "
                                         f"({off:+.0f} mm as drawn) instead of {old}")
                            healed = True
                            break
                        prog.formulas[cand] = old
                        prog.invalidate()
                    if healed:
                        break
                if healed:
                    break
            if not healed:
                break
    return done


def _allowed(parts: dict[str, Part], claimed: set[str]) -> set[str]:
    """Parts a claim covers: the part, what it is made of, and what it is part of."""
    out = set()
    for n in claimed:
        if n in parts:
            out |= {n} | descendants(parts, n) | set(_ancestors(parts, n))
    return out


def _drives(prog: Program, name: str, a: str, b: str, v0: dict[str, float]) -> bool:
    """True when the distance a→b grows exactly with the value (1 mm per mm)."""
    an = prog.analysis
    u = an.drawing.units_mm
    try:
        v1 = prog.datum_values({name: prog.params[name].value + 1.0})
    except ExprError:
        return False
    da = (v1.get(a, v0.get(a, 0.0)) - v0.get(a, 0.0)) * u
    db = (v1.get(b, v0.get(b, 0.0)) - v0.get(b, 0.0)) * u
    return abs(abs(db - da) - 1.0) < 1e-6


def _set_exact(prog: Program, d: str, expr: str, want_mm: float) -> None:
    """d = expr, plus the tiny constant that keeps the drawing exactly as drawn."""
    prog.formulas[d] = expr
    prog.invalidate()
    got = prog.datum_values()[d] * prog.analysis.drawing.units_mm
    if abs(want_mm - got) > 1e-6:
        c = want_mm - got
        prog.formulas[d] = f"{expr} {'+' if c > 0 else '-'} {abs(c):.6f}"
        prog.invalidate()


def drive_dimensions(prog: Program, dims: dict[str, list[tuple[str, str, str | None]]], protected: set[str]) -> dict[str, str]:
    """A NAMED DIMENSION DRIVES ITS GEOMETRY — the rule every parametric CAD system follows, applied the same way to
    any drawing. For each occurrence (a, b) of a named value that does not yet move with it, one end is set out from
    the other plus the value: both ends about the axis when the size is centred on one, else the end that can move
    (not a site level, an AI formula, a slope, a held part) without a cycle, reproducing the drawing exactly, and
    keeping the drawing valid when the value changes (an option that breaks it is used only when nothing else works).
    Returns, for values that cannot drive, the reason — which inputs fix both ends — in words."""
    an = prog.analysis
    u = an.drawing.units_mm
    problems: dict[str, str] = {}
    for name, pairs in dims.items():
        if name not in prog.params:
            continue
        P = prog.params[name].value
        for a, b, axis in pairs:
            if a not in an.datums or b not in an.datums:
                continue
            v0 = {**{d.id: d.value for d in an.datums.values()}, **prog.datum_values()}
            if _drives(prog, name, a, b, v0):
                continue
            if v0[b] < v0[a]:
                a, b = b, a
            wa, wb = v0[a] * u, v0[b] * u
            options: list[list[tuple[str, str, float]]] = []
            if axis and axis in an.datums and axis not in (a, b):
                options.append([(a, f"{axis} - 0.5 * {name}", wa), (b, f"{axis} + 0.5 * {name}", wb)])
            options += [[(b, f"{a} + {name}", wb)], [(a, f"{b} - {name}", wa)]]
            chosen, fallback = None, None
            for opt in options:
                if any(d in protected or d not in prog.formulas for d, _e, _w in opt):
                    continue
                saved = {d: (prog.formulas[d], prog.origin.get(d)) for d, _e, _w in opt}
                try:
                    for d, e, w in opt:
                        _set_exact(prog, d, e, w)
                    prog.order()
                    v = prog.datum_values()
                    exact = all(abs(v[d] * u - w) <= 1e-6 for d, _e, w in opt)
                    drives = exact and _drives(prog, name, a, b, {**{x.id: x.value for x in an.datums.values()}, **v})
                except (ExprError, KeyError, ZeroDivisionError):
                    exact = drives = False
                if drives:
                    valid = not regenerate_program(prog, {name: P + delta_of(prog, name)}).issues
                    if valid:
                        chosen = opt
                        break
                    if fallback is None:
                        fallback = opt
                for d, (f, o) in saved.items():
                    prog.formulas[d] = f
                    if o is None:
                        prog.origin.pop(d, None)
                    else:
                        prog.origin[d] = o
                prog.invalidate()
            if chosen is None and fallback is not None:
                for d, e, w in fallback:
                    _set_exact(prog, d, e, w)
                chosen = fallback
            if chosen is None:
                problems[name] = _why_fixed(prog, name, a, b, protected)
                break
            for d, _e, _w in chosen:
                prog.origin[d] = "dimension"
                protected.add(d)  # a line a named value drives is not taken over by the next one
    return problems


def _why_fixed(prog: Program, name: str, a: str, b: str, protected: set[str]) -> str:
    def by(d: str) -> str:
        origin = prog.origin.get(d, "geometry")
        drivers = sorted(n for n in names_in(prog.formulas.get(d, "")) if n in prog.params)
        if origin in ("ai", "dimension", "slope", "held", "existing", "constraint"):
            return f"{d} (set by {'your formula' if origin == 'ai' else 'another named value' if origin == 'dimension' else origin}: {prog.formulas.get(d)})"
        if drivers:
            return f"{d} (follows {', '.join(drivers)})"
        return f"{d} ({prog.formulas.get(d, 'as drawn')})"

    return (f"{name} lies between {by(a)} and {by(b)}: both ends are fixed by other inputs, so it is worked out, not an input. "
            f"Make one end follow it (set_formulas {b} = {a} + {name}), or report it as a relation.")


def _depends_on(prog: Program, d: str) -> set[str]:
    """Every set-out line d is set out from, through the formulas."""
    out, stack = set(), [d]
    while stack:
        x = stack.pop()
        for n in names_in(prog.formulas.get(x, "")):
            if n in prog.formulas and n not in out:
                out.add(n)
                stack.append(n)
    return out


def entity_label(it) -> str:
    from .cadjson import entity_id

    return entity_id(it)


# ── a person's selection ─────────────────────────────────────────────────────────


def _substitute(expr: str, values: dict[str, float]) -> str:
    tree = ast.parse(expr, mode="eval")

    class Sub(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name):
            if node.id in values:
                return ast.copy_location(ast.Constant(values[node.id]), node)
            return node

    return ast.unparse(Sub().visit(tree))


def freeze_params(prog: Program, names: set[str], rep) -> None:
    """Keep these values as drawn: they stop being inputs; everything that used them keeps the number."""
    vals = {n: prog.params[n].value for n in names if n in prog.params}
    if not vals:
        return
    for d, e in list(prog.formulas.items()):
        if names_in(e) & vals.keys():
            prog.formulas[d] = _substitute(e, vals)
    for k, e in list(prog.radius.items()):
        if names_in(e) & vals.keys():
            prog.radius[k] = _substitute(e, vals)
    for r in prog.relations:
        if names_in(r.expr) & vals.keys():
            r.expr = _substitute(r.expr, vals)
    for n, v in vals.items():
        prog.params.pop(n)
        rep.findings.append(_finding("SEL", "info", n, f"{n} kept as drawn ({v:g}) by your selection"))
    prog.invalidate()


def hold_parts(prog: Program, parts: dict[str, Part], names: set[str], rep) -> int:
    """Lines only held parts use become constants: those parts keep their drawn size and place. Lines a held part
    shares with a free part follow the free part, so the two stay connected."""
    an = prog.analysis
    u = an.drawing.units_mm
    held_names = set(names)
    for n in names:
        held_names |= descendants(parts, n)
    free = [p for p in parts.values() if p.name not in held_names and p.datums]
    held_d, free_d = set(), set()
    for n in held_names:
        held_d |= parts[n].datums if n in parts else set()
    for p in free:
        if not any(a in held_names for a in _ancestors(parts, p.name)):
            free_d |= p.own_datums  # an assembly's gathered lines include its held parts' lines: only its own count
    count = 0
    levels = {n for n, p in prog.params.items() if p.kind == "level"}
    count += _split_shared_lines(prog, parts, held_names, held_d & free_d, levels)
    for d in held_d - free_d:
        if d in prog.formulas and not (names_in(prog.formulas[d]) & levels) and prog.origin.get(d) != "existing":
            prog.formulas[d] = f"{an.datums[d].value * u:.6f}".rstrip("0").rstrip(".")
            prog.origin[d] = "held"
            count += 1
    if count:
        prog.invalidate()
        rep.findings.append(_finding("SEL", "info", "held", f"{count} set-out lines of {len(held_names)} held part(s) kept as drawn"))
    elif names:
        rep.findings.append(_finding("SEL", "info", "held", f"{', '.join(sorted(names)[:4])}: every line is shared with parts that stay "
                                     "parametric, so the held part still follows them where they touch"))
    return count


def _split_shared_lines(prog: Program, parts: dict[str, Part], held: set[str], shared: set[str], levels: set[str]) -> int:
    """A line a held part shares with a free one (an extension drawn on the old box's soffit) is split: entities
    that belong ONLY to held parts move to a copy of the line that stays put; the free part keeps the original."""
    an = prog.analysis
    topo = of(an)
    held_regions = {r for n in held if n in parts for r in parts[n].regions}
    # An entity belongs to the held side when most of its length borders held regions: an existing outline that
    # touches the new work along one short edge is still the existing outline, and it keeps its drawn place.
    own = {i for i, border in topo.item_border.items()
           if sum(L for r, L in border.items() if r in held_regions) > sum(L for r, L in border.items() if r not in held_regions)}
    own |= {i for n in held if n in parts for i in parts[n].entities}
    u = an.drawing.units_mm
    split = 0
    for d in sorted(shared):
        if d not in prog.formulas or names_in(prog.formulas[d]) & levels:
            continue
        slots = [key for key, (dd, _off) in an.slot_datum.items() if dd == d and key[0] in own]
        if not slots:
            continue
        nd = f"{d}h"
        src = an.datums[d]
        an.datums[nd] = Datum(id=nd, axis=src.axis, value=src.value, source="held", items={k[0] for k in slots})
        for key in slots:
            an.slot_datum[key] = (nd, an.slot_datum[key][1])
        prog.formulas[nd] = f"{src.value * u:.6f}".rstrip("0").rstrip(".")
        prog.origin[nd] = "held"
        for n in held:  # the held parts are now drawn on the copy
            q = parts.get(n)
            if q is None or d not in q.datums:
                continue
            swap = (lambda nd_pair, d=d, nd=nd: tuple(nd if v == d else v for v in nd_pair))
            q.datums = (q.datums - {d}) | {nd}
            q.nodes = {swap(x) for x in q.nodes}
            q.edges = [(swap(a), swap(b)) for a, b in q.edges]
        split += 1
    return split


def _ancestors(parts: dict[str, Part], name: str) -> list[str]:
    out, seen = [], {name}
    p = parts.get(name)
    while p is not None and p.parent and p.parent not in seen:
        out.append(p.parent)
        seen.add(p.parent)
        p = parts.get(p.parent)
    return out


def _finding(code: str, severity: str, item: str, message: str):
    from .validator import Finding

    return Finding(code, severity, item, message)
