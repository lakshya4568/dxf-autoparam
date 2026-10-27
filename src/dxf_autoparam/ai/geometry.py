"""What the agent reads of a unit's geometry: the numbers in the view's own frame and what lies where — never the sheet's own coordinates.

A sheet places every view somewhere far from its origin (541 448 mm across is a box's outer wall); a drafter reads a view in its own frame —
millimetres across from its centre line or its left face, and the reduced level up wherever the view states one. So each line is said where it is
in that frame and with what lies on it (the faces of the regions it bounds, the level written on it); each region with where it is, what fills it
and the labels whose leaders point at it; and each axis as a RULER — its lines in order, the distance from one to the next and what fills that gap.
A section read up its vertical ruler is the stack it was built as (a course, a slab, an opening, a slab, a cushion, a formation), with the level
on each line: which size sits between which levels is read off the drawing, not inferred from ids.

Generic: nothing here knows what any part is called; every word is the drawing's own.
"""

from __future__ import annotations

from ..cadjson import entity_id
from ..topology import DatumIndex, of
from . import labels

AXIS_SOURCES = ("drawn-axis", "global-axis", "loop-axis")  # a drawn centre line first: the drafter's own (as frames.py)
FACE = {"x": ("left", "right"), "y": ("bottom", "top")}


def _r(v: float) -> float:
    return round(v, 1)


class Frame:
    """The unit's own frame, in mm: x across from its centre line (or its left-most structural line), y up from its lowest structural line —
    with the reduced level (m) beside it on the lines of the views that state levels. zoom_view's `box_local` is in the same numbers."""

    def __init__(self, an):
        topo = of(an)
        self.u = an.drawing.units_mm
        boxes = [r.bbox for r in topo.regions] or [an.drawing.extent]
        lo_x, lo_y = min(b[0] for b in boxes), min(b[1] for b in boxes)
        hi_x = max(b[2] for b in boxes)
        axes = [d for d in an.datums.values() if d.axis == "x" and d.source in AXIS_SOURCES and lo_x <= d.value <= hi_x]
        if axes:
            d = min(axes, key=lambda d: (AXIS_SOURCES.index(d.source), abs(d.value - (lo_x + hi_x) / 2)))
            self.x0, self.x_from = d.value, f"{d.id} ({'its drawn centre line' if d.source == 'drawn-axis' else 'its axis of symmetry'})"
        else:
            self.x0, self.x_from = lo_x, "the left-most structural line"
        self.y0 = lo_y
        self.offset = an.level_offset_mm
        stated = {d for d, *_ in an.stated_levels}
        views = {v for d in stated for v in an.datum_views.get(d, ())}
        # a line is read as a level where the unit states levels: in its own views when its views are known (a plan drawn with a section is not)
        self.level_lines = {d.id for d in an.datums.values() if d.axis == "y" and stated
                            and (not an.datum_views.get(d.id) or set(an.datum_views[d.id]) & views or not views)}

    def x(self, v: float) -> float:
        return _r((v - self.x0) * self.u)

    def y(self, d: str, v: float) -> str:
        up = f"{_r((v - self.y0) * self.u):g} up"
        return f"{up} (RL {(v * self.u + self.offset) / 1000:.3f})" if d in self.level_lines else up

    def pos(self, d, v: float) -> str:
        return f"{self.x(v):g} across" if d.axis == "x" else self.y(d.id, v)

    def to_sheet(self, lx: float, ly: float) -> tuple[float, float]:
        """A point of the frame (mm across, mm up) on the sheet, in drawing units."""
        return self.x0 + lx / self.u, self.y0 + ly / self.u

    def words(self) -> dict:
        return {"x": f"mm across from {self.x_from} (+ right)", "y": "mm up from the lowest structural line"
                + ("; RL (m) beside it on the lines of the views that state levels" if self.level_lines else ""),
                "note": "the view's own numbers (zoom_view box_local takes them); ids (x…, y…, R…, c…) are what the other tools take"}


def _region_labels(an, topo) -> dict[str, list[str]]:
    """region → the notes whose leader points at its outline (the region the leader's best target borders most; "?" where the engine is not sure of
    the target), and the words written inside it."""
    model = an.cache.get("annotations")
    if model is None:  # a copy of an analysis drops its caches: the notes are associated again (the analysis' own rule, annotations.associate)
        from ..annotations import associate

        titles = {it.index for it in an.drawing.items if it.extra.get("view_title")}
        model = an.cache["annotations"] = associate(an.drawing, an.slot_datum, an.datums, an.stated_levels, titles=titles)
    out: dict[str, list[str]] = {}
    for a in (model.annotations if model is not None else []):
        if a.kind not in (*labels.LABEL_KINDS, "slope") or a.status != "resolved" or not (a.text or "").strip():
            continue
        t = next((t for t in a.targets if t.kind == "entity" and t.index is not None), None)
        at = topo.region_at(a.anchor) if a.anchor is not None else None  # where the leader's tip lies, when it lies in a region
        border = topo.item_border.get(t.index, {}) if t is not None else {}
        rid = at.id if at is not None else max(border, key=lambda k: border[k]) if border else None
        if rid is None:
            continue
        s = " ".join(a.text.split())[:50] + ("" if t is not None and t.score >= 0.5 else " (?)")
        if s not in out.setdefault(rid, []):
            out[rid].append(s)
    for t in an.drawing.items:
        if t.dxftype in ("TEXT", "MTEXT", "ATTRIB") and (t.text or "").strip():
            r = topo.region_at(t.pts[0])
            if r is not None:
                s = " ".join((t.text or "").split())[:40]
                if s not in out.setdefault(r.id, []):
                    out[r.id].append(s)
    return out


def geometry(an, base, named_pairs: dict[tuple[str, str], str] | None = None, ruler_lines: int = 60) -> dict:
    """The unit's geometry as the agent reads it (module doc): {frame, lines rows, regions rows, rulers}. `named_pairs`: (low line, high line) →
    the value named on it, so a ruler says which gaps already have a name."""
    topo = of(an)
    dix = DatumIndex(an)
    fr = Frame(an)
    u = an.drawing.units_mm
    named_pairs = named_pairs or {}
    on: dict[str, list[str]] = {}
    edges: dict[str, tuple[str | None, str | None, str | None, str | None]] = {}
    for r in topo.regions:
        e = tuple(dix.at(ax, v) for ax, v in (("x", r.bbox[0]), ("x", r.bbox[2]), ("y", r.bbox[1]), ("y", r.bbox[3])))
        edges[r.id] = e
        for d, face in zip(e, ("left", "right", "bottom", "top"), strict=True):
            if d:
                on.setdefault(d, []).append(f"{r.id} {face}")
    words = {}
    for d, _i, w, _m in an.stated_levels:
        words.setdefault(d, " ".join(w.split())[:40])
    lines = []
    for d in sorted(an.datums.values(), key=lambda d: (d.axis, d.value)):
        faces = on.get(d.id, [])
        lines.append([d.id, fr.pos(d, d.value), "; ".join(faces[:5]) + (f" +{len(faces) - 5}" if len(faces) > 5 else ""),
                      words.get(d.id, ""), base.formulas.get(d.id, "as drawn")])
    labs = _region_labels(an, topo)
    regions = []
    for r in topo.regions:
        neighbours = r.neighbours
        xl, yb, xr, yt = r.bbox
        where = f"x {fr.x(xl):g}..{fr.x(xr):g}; y {fr.y(edges[r.id][2] or '', yb)}..{fr.y(edges[r.id][3] or '', yt)}"
        regions.append([r.id, _r((xr - xl) * u), _r((yt - yb) * u), where, "/".join(str(x or "?") for x in edges[r.id]), r.pattern or "",
                        r.parent or "", " ".join(f"{k}:{region_side(r, topo.by_id()[k], an.drawing.tol)[0]}" for k in sorted(neighbours, key=lambda k: -neighbours[k])[:6]),
                        "; ".join(labs.get(r.id, [])[:3])])
    return {"frame": fr.words(), "lines": lines, "regions": regions, "rulers": rulers(an, fr, edges, named_pairs, ruler_lines)}


def rulers(an, fr: Frame, edges: dict, named_pairs: dict, cap: int) -> dict[str, list[str]]:
    """Per axis (and per view on an axis the views do not share), the lines that bound regions in order, each step as
    `—<mm> <candidate> <named value> [regions that fill exactly that gap, with their fill]→` before the next line."""
    topo = of(an)
    u = an.drawing.units_mm
    fill = {r.id: r.pattern or "" for r in topo.regions}
    spans: dict[tuple[str, str], list[str]] = {}
    for rid, (xl, xr, yb, yt) in edges.items():
        for a, b in ((xl, xr), (yb, yt)):
            if a and b:
                spans.setdefault((a, b), []).append(rid + (f" {fill[rid]}" if fill[rid] else ""))
    cluster = {}
    for g in an.gaps.values():
        if g.cluster and g.axis in ("x", "y"):
            cluster.setdefault((g.a, g.b), g.cluster)
    out: dict[str, list[str]] = {}
    for axis in ("x", "y"):
        used = {d for e in edges.values() for d in (e[:2] if axis == "x" else e[2:]) if d}
        groups: dict[str, list] = {}
        for d in sorted((an.datums[x] for x in used if x in an.datums), key=lambda d: d.value):
            key = axis if axis == "x" or not an.datum_views.get(d.id) else f"y in {'+'.join(an.datum_views[d.id])}"
            groups.setdefault(key, []).append(d)
        for key, ds in groups.items():
            steps: list[str] = []
            for k, d in enumerate(ds[:cap]):
                head = f"{d.id} [{fr.pos(d, d.value)}{(' ' + _said(an, d.id)) if _said(an, d.id) else ''}]"
                steps.append(head)
                if k + 1 < min(len(ds), cap):
                    nxt = ds[k + 1]
                    pair = (d.id, nxt.id)
                    bits = [f"{_r((nxt.value - d.value) * u):g}"]
                    if pair in cluster:
                        bits.append(cluster[pair])
                    if pair in named_pairs:
                        bits.append(named_pairs[pair])
                    if pair in spans:
                        bits.append("[" + ", ".join(spans[pair][:3]) + "]")
                    steps.append("—" + " ".join(bits) + "→")
            if len(ds) > cap:
                steps.append(f"… {len(ds) - cap} more lines (inspect_lines)")
            # what spans more than one step: a named value, a region (a cell's opening runs past the haunch lines in it) — its two ends and size
            order = {d.id: k for k, d in enumerate(ds)}
            longer = [f"{named_pairs[(a, b)]} {a}→{b} {_r((an.datums[b].value - an.datums[a].value) * u):g}" for (a, b) in named_pairs
                      if a in order and b in order and order[b] - order[a] > 1]
            longer += [f"{', '.join(rs[:3])} {a}→{b} {_r((an.datums[b].value - an.datums[a].value) * u):g}" for (a, b), rs in spans.items()
                       if a in order and b in order and order[b] - order[a] > 1]
            if longer:
                steps.append("across several steps: " + "; ".join(longer[:14]))
            out[key] = steps
    return out


def _said(an, d: str) -> str:
    w = next((" ".join(w.split()) for dd, _i, w, _m in an.stated_levels if dd == d), "")
    return f"“{w[:30]}”" if w else ""


def region_side(r, other, tol) -> str:
    """Where `other` lies from region `r`: above / below / right / left, inside (nested), else beside."""
    a, b = r.bbox, other.bbox
    if abs(b[1] - a[3]) <= 2 * tol:
        return "above"
    if abs(b[3] - a[1]) <= 2 * tol:
        return "below"
    if abs(b[0] - a[2]) <= 2 * tol:
        return "right"
    if abs(b[2] - a[0]) <= 2 * tol:
        return "left"
    return "inside" if r.parent == other.id or other.parent == r.id else "beside"


def text_rows(an, limit: int = 160) -> list[list]:
    """[id, text, region it is written in] — the drawing's words as data."""
    topo = of(an)
    rows = []
    for t in an.drawing.items:
        if t.dxftype in ("TEXT", "MTEXT", "ATTRIB") and (t.text or "").strip():
            r = topo.region_at(t.pts[0])
            rows.append([entity_id(t), " ".join((t.text or "").split())[:70], r.id if r else None])
    return rows[:limit]
