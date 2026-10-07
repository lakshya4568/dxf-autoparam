"""What the AI is told about a drawing: compact, id-addressed, measured — never asked to measure.

Every number here comes from the geometry. The AI's job is to say what things ARE and
which sizes drive which; anything it claims back is checked against these ids and values.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from .ir import Role
from .program import Program


def _r(v: float) -> float:
    return round(v, 1)


def build_facts(prog: Program, max_datums: int = 260, max_texts: int = 220, max_candidates: int = 120) -> dict:
    an = prog.analysis
    dr = an.drawing
    u = dr.units_mm
    items = dr.items
    mm = lambda v: _r(v * u)

    # which entities touch each datum, and how
    touching: dict[str, Counter] = defaultdict(Counter)
    for (i, k, ax), (d, off) in an.slot_datum.items():
        it = items[i]
        if it.role != Role.STRUCTURAL or abs(off) > dr.tol:
            continue
        touching[d][f"{it.layer}"] += 1
    stated = {d: (words, v) for d, _i, words, v in an.stated_levels}

    # datums the model uses (in parameters, candidates, formulas with parameters), then the rest by value
    important: set[str] = set()
    for p in prog.params.values():
        if p.measures:
            important.update(p.measures)
    for d, e in prog.formulas.items():
        if any(n in prog.params for n in e.replace("*", " ").replace("-", " ").replace("+", " ").split()):
            important.add(d)
    for c in an.clusters.values():
        for gid in c.gaps[:4]:
            g = an.gaps.get(gid)
            if g is not None and g.axis in ("x", "y"):
                important.update((g.a, g.b))
    order = sorted(an.datums.values(), key=lambda d: (d.id not in important, d.axis, d.value))
    chosen = order[:max_datums]
    datums = []
    for d in sorted(chosen, key=lambda d: (d.axis, d.value)):
        row = {"id": d.id, "axis": d.axis, "at_mm": mm(d.value), "on_layers": dict(touching[d.id].most_common(3))}
        if d.source != "vertex":
            row["kind"] = d.source
        if d.weak:
            row["loose_line_only"] = True
        if d.id in stated:
            row["stated_level"] = {"text": stated[d.id][0], "value_m": stated[d.id][1]}
        if d.id in prog.formulas:
            row["formula"] = prog.formulas[d.id]
        datums.append(row)

    loops = []
    for it in items:
        if it.role != Role.STRUCTURAL or not it.closed or len(it.vertex_pts) < 3:
            continue
        pts = [it.pts[k] for k in it.vertex_pts]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        loops.append({
            "id": f"L{it.index}", "layer": it.layer, "vertices": len(pts),
            "bbox_mm": [mm(min(xs)), mm(min(ys)), mm(max(xs)), mm(max(ys))],
            "x_datums": sorted({an.slot_datum[(it.index, k, 'x')][0] for k in it.vertex_pts}),
            "y_datums": sorted({an.slot_datum[(it.index, k, 'y')][0] for k in it.vertex_pts}),
        })
    for it in items:
        if it.role == Role.STRUCTURAL and it.dxftype == "CIRCLE":
            loops.append({"id": f"C{it.index}", "layer": it.layer, "circle_diameter_mm": mm(2 * (it.radius or 0)),
                          "centre": [an.slot_datum[(it.index, 0, 'x')][0], an.slot_datum[(it.index, 0, 'y')][0]]})

    texts = []
    for it in items:
        if it.dxftype not in ("TEXT", "MTEXT", "ATTRIB") or not (it.text or "").strip():
            continue
        x, y = it.pts[0]
        bx = an.slot_datum.get((it.index, 0, "x"))
        by = an.slot_datum.get((it.index, 0, "y"))
        texts.append({"id": f"T{it.index}", "text": " ".join((it.text or "").split())[:90], "at_mm": [mm(x), mm(y)],
                      "near": [bx[0] if bx else None, by[0] if by else None]})
        if len(texts) >= max_texts:
            break

    dims = []
    for it in items:
        if it.dxftype != "DIMENSION":
            continue
        a = an.slot_datum.get((it.index, 1, "x")), an.slot_datum.get((it.index, 1, "y"))
        b = an.slot_datum.get((it.index, 2, "x")), an.slot_datum.get((it.index, 2, "y"))
        dx = abs(it.pts[2][0] - it.pts[1][0])
        dy = abs(it.pts[2][1] - it.pts[1][1])
        axis = "x" if dy < dr.tol and dx > dr.tol else "y" if dx < dr.tol and dy > dr.tol else ("x" if abs(math.sin(math.radians(it.extra.get("angle", 0)))) < 0.5 else "y")
        k = 0 if axis == "x" else 1
        ends = [a[k][0] if a[k] and abs(a[k][1]) <= dr.tol else None, b[k][0] if b[k] and abs(b[k][1]) <= dr.tol else None]
        dims.append({"id": f"D{it.index}", "value_mm": _r((it.extra.get("measurement") or math.dist(it.pts[1], it.pts[2])) * u),
                     "text": (it.text or "").strip() or "<measured>", "axis": axis, "between": ends})

    cands = []
    for c in sorted(an.clusters.values(), key=lambda c: (-c.confidence, -len(c.gaps)))[:max_candidates]:
        pairs = []
        for gid in c.gaps[:6]:
            g = an.gaps.get(gid)
            if g is not None and g.axis in ("x", "y"):
                pairs.append([g.a, g.b])
        cands.append({
            "id": c.id, "current_name": c.name if c.name in prog.params else None, "kind": c.kind.value,
            "axes": sorted(c.axes), "value_mm": mm(c.value),
            "occurrences": len(c.gaps), "between": pairs, "confidence": c.confidence, "drawing_says": c.suggested,
            "evidence": [e.detail for e in c.evidence][:4],
        })

    params = [{"name": p.name, "value": p.value, "unit": p.unit, "measures": list(p.measures) if p.measures else None,
               "occurrences": p.occurrences} for p in prog.params.values()]
    rels = [{"label": r.label, "expr": r.expr, "check": r.check, "dimensioned": r.dimensioned} for r in prog.relations[:60]]
    return {
        "drawing": {"file": dr.path.split("/")[-1], "units": "millimetres (levels in metres)", "layout": dr.layout,
                    "extent_mm": [mm(v) for v in dr.extent], "entities": len(items),
                    "structural_entities": sum(1 for i in items if i.role == Role.STRUCTURAL), "reader_notes": dr.notes,
                    "geometry_notes": an.notes},
        "datums": datums,
        "datums_omitted": max(0, len(an.datums) - len(chosen)),
        "outlines": loops[:150],
        "texts": texts,
        "dimensions": dims[:200],
        "candidate_values": cands,
        "baseline_parameters": params,
        "baseline_relations": rels,
    }
