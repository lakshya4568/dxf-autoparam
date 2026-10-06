"""One call from a DXF to a reviewed, validated parametric model — and back to DXF.

    model = autoparametrize("box.dxf", domain="bridge")
    report = validate(model)
    reg = regenerate(model, {"OpenX1": 4000})
    write_dxf(model, reg, "box_4000.dxf")
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict

from .analyse import AnalyseOptions, analyse
from .build import Decisions, build, format_form
from .dxf_read import ReadOptions, read_dxf
from .ir import Model, Role
from .regen import regenerate
from .views import detect_views, restrict


def autoparametrize(
    path: str,
    domain: str | None = None,
    decisions: Decisions | None = None,
    read: ReadOptions | None = None,
    options: AnalyseOptions | None = None,
    region: tuple[float, float, float, float] | None = None,
    view: int | None = None,
) -> Model:
    """DXF → parametric model. `view` picks one of `detect_views`, `region` a box; else the whole sheet."""
    t0 = time.perf_counter()
    dr, _ = read_dxf(path, read)
    if view is not None and region is None:
        views = detect_views(dr)
        region = views[view]["bbox"] if 0 <= view < len(views) else None
    if region is not None:
        restrict(dr, region)
    an = analyse(dr, options)
    dec = decisions or Decisions()
    if domain:
        from .domains import PACKS

        pack = PACKS[domain](an)
        # A person's own decisions win over the pack's suggestions.
        pack.accept |= dec.accept
        pack.reject |= dec.reject
        pack.rename.update(dec.rename)
        pack.anchor.update(dec.anchor)
        pack.pin.update(dec.pin)
        pack.reference_only |= dec.reference_only
        dec = pack
    model = build(an, dec)
    model.warnings.append(f"built in {time.perf_counter() - t0:.2f} s")
    return model


def validate(model: Model, step: float = 0.1) -> dict:
    """Identity, then every value grown and shrunk: does the drawing stay a valid drawing?"""
    an = model.analysis
    dr = an.drawing
    base = regenerate(model)
    identity = max(
        (math.dist(base.pts[it.index][k], p) for it in dr.items if it.index in base.pts for k, p in enumerate(it.pts)),
        default=0.0,
    )
    order0 = {ax: [d for d, _ in sorted(((d, v) for d, v in base.datum.items() if an.datums[d].axis == ax), key=lambda t: t[1])] for ax in ("x", "y")}
    per_param = []
    for p in model.parameters.values():
        if p.kind in ("level", "position"):
            deltas = [1.0 if p.kind == "level" else 1000.0, -(1.0 if p.kind == "level" else 1000.0)]
        else:
            deltas = [max(p.value * step, 10 / dr.units_mm), -max(p.value * step, 10 / dr.units_mm)]
        row = {"name": p.name, "value": p.value, "ok": True, "issues": [], "moved_entities": p.affects, "order_changes": 0}
        for dv in deltas:
            r = regenerate(model, {p.name: p.value + dv})
            if r.issues:
                row["ok"] = False
                row["issues"].extend(r.issues[:3])
            for ax in ("x", "y"):
                vals = [r.datum[d] for d in order0[ax]]
                swaps = sum(1 for a, b in zip(vals, vals[1:]) if b < a - dr.tol)
                row["order_changes"] = max(row["order_changes"], swaps)
        per_param.append(row)
    return {
        "identity_max_error": identity,
        "parameters": len(model.parameters),
        "regenerate_ok": sum(1 for r in per_param if r["ok"]),
        "per_parameter": per_param,
        "structural_entities": sum(1 for it in dr.items if it.role == Role.STRUCTURAL),
        "entities": len(dr.items),
        "unsupported": dr.unsupported,
    }


def model_to_json(model: Model) -> dict:
    """The parametric IR as data: values, how every datum is set out, what follows."""
    an = model.analysis
    u = an.drawing.units_mm
    return {
        "format": "dxf-autoparam/1",
        "source": an.drawing.path,
        "units_mm_per_drawing_unit": u,
        "tolerance": an.drawing.tol,
        "parameters": [
            {**{k: v for k, v in asdict(p).items() if k != "evidence"}, "value_mm": p.value * u if p.kind not in ("level", "position") else None,
             "evidence": [asdict(e) for e in p.evidence]}
            for p in model.parameters.values()
        ],
        "datums": {
            d: {"axis": an.datums[d].axis, "value": an.datums[d].value, "source": an.datums[d].source, "expr": format_form(f, 1.0),
                "const": f.const, "terms": f.terms}
            for d, f in model.forms.items()
        },
        "tree": [asdict(e) for e in model.tree],
        "results": [{"label": r.label, "value": r.value, "dimensioned": r.dimensioned, "expr": format_form(r.form, u)} for r in model.results],
        "candidates": [
            {"id": c.id, "name": c.name, "label": c.label, "kind": c.kind.value, "value": c.value, "occurrences": len(c.gaps),
             "confidence": c.confidence, "status": c.status.value, "accepted": c.accepted, "suggested": c.suggested,
             "evidence": [asdict(e) for e in c.evidence]}
            for c in an.clusters.values()
        ],
        "constraints": [asdict(c) for c in an.constraints],
        "bindings": [
            {"item": it, "pt": k, "axis": ax, "datum": d, "offset": off}
            for (it, k, ax), (d, off) in an.slot_datum.items()
        ],
        "notes": an.notes,
        "warnings": model.warnings,
    }


def save_model(model: Model, path: str) -> None:
    with open(path, "w") as f:
        json.dump(model_to_json(model), f, indent=1, default=str)
