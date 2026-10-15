"""What one entity IS, from every layer that knows something about it — for the inspector a person clicks and the tool the
agent calls, so both read the same record.

    entity_record(sm, i)       source (handle, block, INSERT chain, raw properties) · resolved style · geometry (mm) ·
                               the view and unit it is in · each point's set-out lines and the parameters that move them ·
                               the parts it belongs to · what is held fixed · the annotations attached to it
    resolve_handle(sm, h)      a DXF handle → the sheet entities read from it (a block's entity appears once per INSERT)

Nothing here decides anything: it gathers what the reader, the sheet, the analysis and the program already hold.
"""

from __future__ import annotations

from .cadjson import entity_id
from .graph import _reach


def _mm(v: float, u: float) -> float:
    return round(v * u, 3)


def resolve_handle(sm, handle: str) -> list[int]:
    """Every sheet entity read from this DXF handle — the entity's own handle (inside its block definition) or the
    top-level handle of the INSERT that placed it."""
    h = (handle or "").upper()
    out = []
    for it in sm.dr.items:
        src = it.extra.get("source") or {}
        if (src.get("handle") or "").upper() == h or it.handle.upper() == h or h in (x.upper() for x in src.get("inserts", [])):
            out.append(it.index)
    return out


def _unit_of(sm, i: int):
    for u in sm.units.values():
        if i in u.items:
            return u
    return None


def entity_record(sm, i: int, deep: bool = True) -> dict:
    """Everything known about sheet entity `i`. `deep`: also its parametric bindings (builds the unit's program on first use)."""
    if not 0 <= i < len(sm.dr.items):
        raise IndexError(f"no entity {i}")
    it = sm.dr.items[i]
    u_mm = sm.dr.units_mm
    gid = sm.layout.item_group.get(i, "")
    group = next((g for g in sm.layout.groups if g.id == gid), None)
    rec: dict = {
        "index": i, "id": entity_id(it), "type": it.dxftype, "layer": it.layer, "role": it.role.value,
        "source": it.extra.get("source") or {"handle": it.handle, "path": it.src},
        "path": it.src,
        "style": it.extra.get("style"),
        "geometry": {"points_mm": [[_mm(x, u_mm), _mm(y, u_mm)] for x, y in it.pts[:64]], "closed": it.closed},
        "view": {"id": gid, "name": group.name if group else "", "kind": group.kind if group else ""},
    }
    if len(it.pts) > 64:
        rec["geometry"]["points_total"] = len(it.pts)
    if it.radius:
        rec["geometry"]["radius_mm"] = _mm(it.radius, u_mm)
    if it.text:
        rec["text"] = it.text
        rec["text_height_mm"] = _mm(it.text_height or 0.0, u_mm)
    if it.dxftype == "DIMENSION":
        rec["dimension"] = {"measurement_mm": _mm(it.extra.get("measurement") or 0.0, u_mm), "override": it.text or "<>",
                            "dimtype": it.extra.get("dimtype"), "dimstyle": (it.extra.get("source") or {}).get("dimstyle")}
    if it.extra.get("parts"):
        kinds: dict[str, int] = {}
        for q in it.extra["parts"]:
            key = q.get("tag") or q["k"]
            kinds[key] = kinds.get(key, 0) + 1
        rec["drawn_with"] = kinds
    if it.extra.get("hatch"):
        h = it.extra["hatch"]
        rec["hatch"] = {"fill": h.get("fill"), "pattern": h.get("name"), "pattern_lines": len(h.get("segments", [])), "too_dense": bool(h.get("too_dense"))}
    if it.anchor is not None:
        rec["symbol_of"] = it.anchor
    unit = _unit_of(sm, i)
    if unit is None:
        rec["unit"] = None
        return rec
    rec["unit"] = unit.id
    if not deep:
        return rec
    u = sm.unit(unit.id)
    k = unit.items.index(i)
    an, prog = u.an, u.prog
    reach = _reach(prog)
    points = []
    controlled: set[str] = set()
    for p in range(len(it.pts)):
        row = {}
        for ax in ("x", "y"):
            b = an.slot_datum.get((k, p, ax))
            if b is None:
                row[ax] = None
                continue
            d, off = b
            row[ax] = {"line": d, "offset_mm": _mm(off, u.sub.units_mm), "formula": prog.formulas.get(d, ""),
                       "origin": prog.origin.get(d, "geometry"), "parameters": sorted(reach.get(d, set()))}
            controlled |= reach.get(d, set())
        points.append(row)
    origins = {r[ax]["origin"] for r in points for ax in ("x", "y") if r.get(ax)}
    rec["parametric"] = {"points": points[:32], "parameters": sorted(controlled),
                         "held": bool(origins & {"held", "existing"}), "fixed": not controlled}
    parts = prog.intent.get("parts") or {}
    rec["parts"] = sorted(name for name, part in parts.items() if k in getattr(part, "entities", set()))
    return rec


# ── the sheet's semantics (reused while their inputs are unchanged) ─────────────────


def sheet_annotations(sm) -> list[dict]:
    """Every annotation on the sheet: per unit from its analysis (classified, paired, targeted, with its behaviour), and
    the notes, tables and title block outside the views as sheet furniture. Sheet entity indices throughout."""
    from .cache import decisions_key, drawing_key, layout_key

    def compute() -> list[dict]:
        from .annotations import TEXT_TYPES, classify_text, text_states

        out: list[dict] = []
        seen: set[int] = set()
        for uid, u in sm.units.items():
            an = sm.analysis(uid)
            model = an.cache.get("annotations")
            if model is None:
                continue
            for a in model.annotations:
                d = a.to_dict(back=u.back)
                d["unit"] = uid
                d["view"] = sm.layout.item_group.get(d["items"][0], "") if d["items"] else ""
                out.append(d)
                seen.update(d["items"])
        kind_of = {i: g.kind for g in sm.layout.groups for i in g.items}
        for it in sm.dr.items:
            if it.index in seen or it.dxftype not in TEXT_TYPES or not (it.text or "").strip():
                continue
            gk = kind_of.get(it.index, "")
            kind, why = classify_text(it.text, gk or "notes", False)
            out.append({"id": entity_id(it), "kind": kind, "text": " ".join(it.text.split())[:160], "attachment": "sheet", "status": "resolved",
                        "items": [it.index], "evidence": [*why, f"outside the views ({gk or 'loose'}): stays where it is on the sheet"],
                        "states": text_states(it.text), "unit": None, "view": sm.layout.item_group.get(it.index, "")})
        return out

    return sm.memo.get("sheet_annotations", (drawing_key(sm), layout_key(sm), decisions_key(sm, "annotations")), compute)


def layers(sm) -> list[dict]:
    from .cache import drawing_key, layout_key
    from .layers import layer_report

    return sm.memo.get("layers", (drawing_key(sm), layout_key(sm)), lambda: layer_report(sm.dr, sm.layout))


def statuses(sm) -> dict:
    from .cache import decisions_key, drawing_key, layout_key
    from .layers import classify_status

    return sm.memo.get("statuses", (drawing_key(sm), layout_key(sm), decisions_key(sm, "status"), decisions_key(sm, "annotations")),
                       lambda: classify_status(sm.dr, sm.layout, sheet_annotations(sm), sm.semantics.get("status", [])))


def duplicates(sm, view: str | None = None) -> dict:
    from .cache import drawing_key, layout_key
    from .duplicates import find_duplicates

    def compute():
        items = sm.layout.group(view).items if view else None
        return find_duplicates(sm.dr, items=items, group_of=sm.layout.item_group)

    return sm.memo.get(f"duplicates:{view or '*'}", (drawing_key(sm), layout_key(sm)), compute)
