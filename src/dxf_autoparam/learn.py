"""Learn design behaviour from an example: a drawing, and the same drawing after a designer changed it.

    lesson = learn("original.dxf", "modified.dxf", prog)    # prog: a program of the original (optional)

  1. Entities are matched (by handle, else by order when the two files hold the same entities) and every
     set-out line of the original is read again in the edited drawing.
  2. Sizes between lines (the candidate values) are compared: the ones the designer CHANGED are the inputs
     that were edited; every size that did not change is an invariant of that edit.
  3. Every region (atomic part) is measured before and after: what grew, what moved, what stayed.
  4. With a program, the parameter changes that best explain the edit are found by least squares on the
     set-out (every line is linear in the parameters), and the lines the program can NOT explain are listed
     with the parts they bound — exactly where the program's intent and the designer's differ.

The result is a set of rules ("when OpenX1 +500: R1 grows x, R4 grows x, R2 fixed …") and a verdict on the
program, both measured. Nothing here is specific to a structure type.
"""

from __future__ import annotations

import statistics

import numpy as np

from .analyse import analyse
from .dxf_read import read_dxf
from .intent import _boxes, classify, resolve_parts
from .ir import Analysis, Drawing
from .program import Program


def _match(a: Drawing, b: Drawing) -> dict[int, int]:
    """original item → edited item."""
    by_src = {}
    dup = set()
    for it in b.items:
        if it.src in by_src:
            dup.add(it.src)
        by_src[it.src] = it.index
    out = {}
    for it in a.items:
        j = by_src.get(it.src)
        if it.src and it.src not in dup and j is not None and b.items[j].dxftype == it.dxftype and len(b.items[j].pts) == len(it.pts):
            out[it.index] = j
    if len(out) < 0.8 * len(a.items) and len(a.items) == len(b.items) and all(x.dxftype == y.dxftype for x, y in zip(a.items, b.items, strict=True)):
        out = {i: i for i in range(len(a.items)) if len(a.items[i].pts) == len(b.items[i].pts)}
    return out


def read_lines(an: Analysis, edited: Drawing, match: dict[int, int]) -> tuple[dict[str, float], list[str]]:
    """Where each set-out line of the original went (drawing units); lines the edit split apart."""
    seen: dict[str, list[float]] = {}
    for (i, k, ax), (d, off) in an.slot_datum.items():
        if abs(off) > an.drawing.tol or i not in match:
            continue
        pts = edited.items[match[i]].pts
        if k < len(pts):
            seen.setdefault(d, []).append(pts[k][0 if ax == "x" else 1] * edited.units_mm / an.drawing.units_mm)
    new, split = {}, []
    for d, vs in seen.items():
        new[d] = statistics.median(vs)
        if max(vs) - min(vs) > 2 * an.drawing.tol:
            split.append(d)
    return new, split


def learn(original: str, modified: str, prog: Program | None = None) -> dict:
    a, _ = read_dxf(original)
    b, _ = read_dxf(modified)
    an = prog.analysis if prog is not None else analyse(a)
    match = _match(an.drawing, b)
    u = an.drawing.units_mm
    tol = an.drawing.tol
    new, split = read_lines(an, b, match)
    moved = {d: (new[d] - an.datums[d].value) * u for d in new if abs(new[d] - an.datums[d].value) > tol}

    sizes_changed, unchanged = [], 0
    for c in an.clusters.values():
        vals = []
        for gid in c.gaps:
            g = an.gaps[gid]
            if g.a in new and g.b in new and g.axis in ("x", "y"):
                vals.append((new[g.b] - new[g.a]) * u)
        if not vals:
            continue
        if all(abs(v - c.value * u) <= tol * u for v in vals):
            unchanged += 1
            continue
        sizes_changed.append({"candidate": c.id, "name": c.name, "kind": c.kind.value, "from": round(c.value * u, 3),
                              "to": sorted({round(v, 3) for v in vals}), "occurrences": len(vals),
                              "uniform": max(vals) - min(vals) <= tol * u})

    parts = (prog.intent.get("parts") if prog is not None else None) or resolve_parts(an, None)[0]
    dv0 = {d.id: d.value for d in an.datums.values()}
    dv1 = {**dv0, **new}
    b0 = _boxes(parts, (dv0, {}))
    b1 = _boxes(parts, (dv1, {}))
    behaviour = {}
    for name in parts:
        if b0[name] is None or b1[name] is None:
            continue
        m = classify(b0[name], b1[name], tol)
        words = [f"{m[ax]} {ax}" for ax in ("x", "y") if m[ax] != "fixed"]
        behaviour[name] = ", ".join(words) if words else "fixed"

    lesson = {"matched_entities": len(match), "entities": [len(an.drawing.items), len(b.items)],
              "lines_moved": {d: round(v, 3) for d, v in sorted(moved.items())}, "lines_split_by_the_edit": split,
              "sizes_changed": sizes_changed, "sizes_unchanged": unchanged,
              "parts": {k: v for k, v in behaviour.items() if v != "fixed"},
              "parts_fixed": sorted(k for k, v in behaviour.items() if v == "fixed")}
    if prog is not None:
        lesson["fit"] = fit(prog, new, parts)
    lesson["rules"] = _rules(lesson)
    return lesson


def fit(prog: Program, new: dict[str, float], parts: dict) -> dict:
    """The parameter changes that explain the edit best, and the lines they cannot explain."""
    an = prog.analysis
    u = an.drawing.units_mm
    names = list(prog.params)
    lines = [d for d in prog.formulas if d in new]
    if not names or not lines:
        return {"changes": {}, "explained": 0, "unexplained": []}
    base = prog.datum_values()
    J = np.zeros((len(lines), len(names)))
    for j, n in enumerate(names):
        step = 1.0  # mm (m for levels): the set-out is linear, one step gives the column
        moved = prog.datum_values({n: prog.params[n].value + step})
        for i, d in enumerate(lines):
            J[i, j] = (moved[d] - base[d]) * u / step
    target = np.array([(new[d] - base[d]) * u for d in lines])
    dp, *_ = np.linalg.lstsq(J, target, rcond=None)
    tol_mm = max(an.drawing.tol * u * 2, 0.5)
    changes = {n: round(float(v), 3) for n, v in zip(names, dp, strict=True) if abs(v) > 1e-6}
    check = prog.datum_values({n: prog.params[n].value + v for n, v in changes.items()})
    unexplained = []
    for i, d in enumerate(lines):
        off = (new[d] - check[d]) * u
        if abs(off) > tol_mm:
            unexplained.append({"datum": d, "by_mm": round(off, 3), "parts": sorted(p for p, q in parts.items() if d in q.datums)[:6]})
    return {"changes": changes, "explained": len(lines) - len(unexplained), "lines": len(lines), "unexplained": unexplained}


def _rules(lesson: dict) -> list[str]:
    out = []
    changed = ", ".join(f"{s['name'] or s['candidate']} {s['from']:g} → {'/'.join(f'{v:g}' for v in s['to'])}" for s in lesson["sizes_changed"][:8])
    if changed:
        out.append(f"The edit changed: {changed}.")
    if lesson["parts"]:
        out.append("Parts: " + "; ".join(f"{k} {v}" for k, v in list(lesson["parts"].items())[:12]) + ".")
    if lesson["parts_fixed"]:
        out.append(f"Stayed as drawn: {', '.join(lesson['parts_fixed'][:12])}.")
    out.append(f"{lesson['sizes_unchanged']} other sizes did not change (invariants of this edit).")
    f = lesson.get("fit")
    if f:
        if f["changes"]:
            out.append("The program explains it as: " + ", ".join(f"{k} {v:+g}" for k, v in f["changes"].items()) + ".")
        if f["unexplained"]:
            out.append(f"{len(f['unexplained'])} set-out line(s) moved in a way the program does not: "
                       + "; ".join(f"{x['datum']} off by {x['by_mm']:g} mm ({', '.join(x['parts']) or 'no part'})" for x in f["unexplained"][:6]) + ".")
        else:
            out.append("The program reproduces the edit exactly.")
    return out
