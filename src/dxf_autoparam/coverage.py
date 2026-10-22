"""How parametric a unit is, part by part, measured on the drawing's own DIMENSIONS.

A dimension is what the drafter thought worth stating; a parametric drawing changes it through a value somebody named. Each DIMENSION of a unit
whose own definition points lie on two set-out lines (the analysis ties it to that gap; `status.dimension_drive` counts these same rows) gets one
status, measured by stepping values on the program — never claimed:

  driven    a value somebody named (a person or the agent) changes it
  unnamed   only values the engine measured and nobody named change it: renaming one of them (`rename_values`) makes it driven
  fixed     no value changes it: the set-out holds its two lines a constant distance apart. Binding the dimension itself
            (`define_parameters` with `dimension`) makes it an input — or it is said to stay as drawn, with why
  unread    its points are not on two set-out lines (an angle, a radius, a sloped or loose dimension)
  kept      not driven, and said to stay as drawn on purpose (the agent's or a person's `keep_dimensions`, with why)

and is sorted onto the parts whose own entities are drawn on its lines: a dimension both of whose lines carry one part sizes THAT part; one between
two parts sets one out from the other; one whose lines no part carries is `unassigned` (a level, the frame, an approach). The same computation
feeds the agent's `coverage` tool, the finish gate, the page and the benchmark. Nothing here knows what any structure is called."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .generic import is_generated
from .program import ExprError

STATUSES = ("driven", "unnamed", "fixed", "unread")


def _named(prog, name: str) -> bool:
    p = prog.params[name]
    return not (is_generated(name) and p.source != "ai")


def dimension_rows(prog, kept: set[str] | None = None, unsteppable: list[str] | None = None) -> list[dict]:
    """Every DIMENSION of the program's drawing with its two lines, its measured value and its status (module doc). A dimension measures two set-out
    lines when its own definition points lie on them — the analysis then ties it to that gap (`gap.dims`), the same tie a binding by its id uses; a
    dimension whose points lie elsewhere (the nearest line hundreds of units away) is `unread`, never guessed onto the nearest lines. `kept`:
    dimension ids a person or the agent said stay as drawn. `unsteppable`: filled with the values whose step the program cannot evaluate."""
    from .cadjson import entity_id

    an = prog.analysis
    um = an.drawing.units_mm
    kept = kept or set()
    v0 = prog.datum_values()
    tied: dict[int, list] = defaultdict(list)
    for g in an.gaps.values():
        if g.axis in ("x", "y") and g.a in v0 and g.b in v0:
            for d in g.dims:
                tied[d].append(g)
    rows: list[dict] = []
    pairs: dict[int, tuple[str, str, str]] = {}
    for it in an.drawing.items:
        if it.dxftype != "DIMENSION":
            continue
        row: dict[str, Any] = {"id": entity_id(it), "index": it.index, "text": " ".join((it.text or "").split())[:40] or "<>"}
        gs = tied.get(it.index, [])
        if gs:
            g = gs[0]
            a, b = sorted((g.a, g.b), key=lambda d: v0[d])
            pairs[len(rows)] = (a, b, g.axis)
            row.update(axis=g.axis, lines=[a, b], mm=round(abs(v0[b] - v0[a]) * um, 1))
            if len(gs) > 1:
                row["ties"] = len(gs)  # its points lie on more than one pair: the first is read, a binding by its id is refused until one is said
            written = _written(it.text or "", abs(v0[b] - v0[a]) * um)
            if written is not None:
                row["writes"] = written  # its text states another number than it measures: the number cannot follow a change of the geometry
        else:
            row.update(status="unread", mm=round(float(it.extra.get("measurement") or 0.0) * um, 1) if it.extra else None)
        rows.append(row)
    named_by: dict[int, list[str]] = defaultdict(list)
    unnamed_by: dict[int, list[str]] = defaultdict(list)
    for name, prm in prog.params.items():
        try:
            v1 = prog.datum_values({name: prm.value + 1.0})
        except (ExprError, ArithmeticError, KeyError, ValueError):
            if unsteppable is not None:
                unsteppable.append(name)  # a value whose step the program cannot evaluate drives nothing that can be measured here
            continue
        for k, (a, b, _ax) in pairs.items():
            if abs((v1[b] - v1[a]) - (v0[b] - v0[a])) > 1e-9:
                (named_by if _named(prog, name) else unnamed_by)[k].append(name)
    for k in pairs:
        row = rows[k]
        if named_by.get(k):
            row.update(status="driven", by=sorted(named_by[k])[:6])
        elif unnamed_by.get(k):
            row.update(status="kept" if row["id"] in kept else "unnamed", by=sorted(unnamed_by[k])[:6])
        else:
            row["status"] = "kept" if row["id"] in kept else "fixed"
    return rows


def _written(text: str, mm: float) -> float | None:
    """The number a dimension's own text writes when it is NOT what the dimension measures (in mm, or in m to 2–3 decimals — the forms the
    writer keeps up to date): a drafter's number over a drawing not to scale, or a dimension placed on the wrong points. None when its text is the
    measurement, or states no number at all."""
    if not text or text.strip() in ("<>", ""):
        return None
    toks = [float(t) for t in re.findall(r"\d+(?:\.\d+)?", text)]
    if not toks or any(abs(t - mm) <= 0.5 or abs(t - mm / 1000.0) <= 0.0005 for t in toks):
        return None
    return max(toks)


def _entity_parts(prog) -> dict[int, set[str]]:
    """entity → the leaf parts it is drawn for (an assembly's entities are its children's)."""
    from .assembly import part_entities

    parts = prog.intent.get("parts") or {}
    parents = {p.parent for p in parts.values() if p.parent}
    out: dict[int, set[str]] = defaultdict(set)
    for name in parts:
        if name not in parents:
            for i in part_entities(prog, parts, name):
                out[i].add(name)
    return out


def _measured_parts(prog, it, lines: list[str], axis: str, eparts: dict[int, set[str]]) -> list[set[str]]:
    """For each of a dimension's two measured LINES, the parts drawn on that line next to the dimension: among the structural entities with a
    point on the line (an edge along it, or a corner on it), the one nearest the dimension's own measured point along the line — a drafter
    places a dimension beside what it measures, and does not always start its extension lines on the outline (they can stop well short)."""
    an = prog.analysis
    other = "y" if axis == "x" else "x"
    j = 1 if other == "y" else 0  # the coordinate along the measured line
    out = []
    for k, line in zip((1, 2), lines, strict=False):
        if len(it.pts) <= k:
            out.append(set())
            continue
        at = it.pts[k][j]
        best, where = float("inf"), set()
        for i, parts in eparts.items():
            o = an.drawing.items[i]
            on = [q for q in range(len(o.pts)) if (an.slot_datum.get((i, q, axis)) or (None,))[0] == line
                  and abs(an.slot_datum[(i, q, axis)][1]) <= an.drawing.tol]
            if not on:
                continue
            span = [o.pts[q][j] for q in on]
            d = 0.0 if min(span) - an.drawing.tol <= at <= max(span) + an.drawing.tol else min(abs(at - v) for v in span)
            if d < best - 1e-9:
                best, where = d, set(parts)
            elif abs(d - best) <= 1e-9:
                where |= parts
        out.append(where)
    return out


def unit_coverage(prog, kept: set[str] | None = None, part: str | None = None, limit: int = 40, also_driven=None) -> dict:
    """The unit's dimensions sorted onto its parts, with counts — the whole picture in one bounded answer. `part`: only that part's rows in full.
    `also_driven(a, b)`: the named values that move lines a–b somewhere else the program does not see (the sheet as it stands, with the design
    intent the engine derived): a dimension they move is driven — a result of them, not a size still to bind."""
    rows = dimension_rows(prog, kept)
    if also_driven is not None:
        for r in rows:
            if r["status"] in ("fixed", "unnamed", "kept") and r.get("lines"):
                by = also_driven(*r["lines"])
                if by:
                    r.update(status="driven", by=sorted(by)[:6], as_the_sheet_stands=True)
    eparts = _entity_parts(prog)
    items = prog.analysis.drawing.items
    by_part: dict[str, dict] = {}
    unassigned: list[dict] = []
    for r in rows:
        if not r.get("lines"):
            r["parts"] = []
            unassigned.append(r)
            continue
        p1, p2 = _measured_parts(prog, items[r["index"]], r["lines"], r["axis"], eparts)
        both = p1 & p2
        r["parts"] = sorted(both) if both else sorted(p1 | p2)
        r["relation"] = "sizes" if both else ("between" if p1 and p2 else "from" if p1 or p2 else "none")
        if not r["parts"]:
            unassigned.append(r)
        for p in r["parts"]:
            slot = by_part.setdefault(p, {"total": 0, **dict.fromkeys(STATUSES, 0), "kept": 0, "rows": []})
            slot["total"] += 1
            slot[r["status"]] += 1
            slot["rows"].append(r)
    total = len(rows)
    count = {s: sum(1 for r in rows if r["status"] == s) for s in (*STATUSES, "kept")}
    parts_out = {}
    for p, slot in sorted(by_part.items(), key=lambda kv: -(kv[1]["fixed"] + kv[1]["unnamed"])):
        entry = {k: v for k, v in slot.items() if k != "rows" and (v or k in ("total", "driven"))}
        if part is None or part == p:
            open_rows = [_brief(r) for r in slot["rows"] if r["status"] in ("fixed", "unnamed")]
            if open_rows:
                entry["open"] = open_rows[: (limit if part == p else 8)]
        parts_out[p] = entry
    return {"dimensions": total, **count,
            "share_driven": round(count["driven"] / total, 3) if total else None,
            "parts": parts_out,
            "unassigned": [_brief(r) for r in unassigned if r["status"] in ("fixed", "unnamed")][:limit],
            "rows": rows}


def _brief(r: dict) -> dict:
    out = {"dimension": r["id"], "states": r["text"], "mm": r.get("mm"), "status": r["status"]}
    if r.get("writes") is not None:
        out["disagrees"] = f"writes {r['writes']:g} but measures {r['mm']:g} mm: its number will not follow — check which is meant"
    if r.get("lines"):
        out["lines"] = "–".join(r["lines"])
    if r.get("by"):
        out["moved_by"] = r["by"][:3]
    if r.get("relation") in ("between", "from"):
        out["sets_out"] = r["relation"]
    return out


def sheet_coverage(sm, units: list[str] | None = None) -> dict:
    """Per unit and over the sheet: dimensions driven / total, part by part (what the benchmark and the page report). Without `units`, the units
    that carry work (or are built already); with them, exactly those, read if need be — a drawing nobody parametrized has its dimensions too."""
    out: dict[str, Any] = {"units": {}}
    tot = drv = 0
    for uid in units or list(sm.units):
        u = sm.units[uid]
        if units is None and not u.answer and not u.built:
            continue
        unit = sm.unit(uid)
        if unit.prog is None:
            continue
        cov = unit_coverage(unit.prog, kept=set((unit.answer or {}).get("kept_dimensions", {})))
        cov.pop("rows")
        out["units"][uid] = cov
        tot += cov["dimensions"]
        drv += cov["driven"]
    out.update(dimensions=tot, driven=drv, share_driven=round(drv / tot, 3) if tot else None)
    return out
