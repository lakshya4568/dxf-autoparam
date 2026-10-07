"""DXF → CAD JSON: the drawing in a form a model can reason about without measuring anything.

    doc = cad_json(analysis, program)            # everything, ids stable within one reading
    doc = cad_json(analysis, program, for_ai=True)  # the same, trimmed to what reasoning needs

Sections (each can be written as its own file with `write_split`):

  drawing        units, extent, layers (with what is on them), entity counts, reader notes
  entities       every entity: type-specific geometry (start/end/length/angle, vertices/area/
                 perimeter, centre/radius/sweep, pattern, measurement, text), layer, colour,
                 linetype, lineweight, bbox, block path, the set-out lines its points sit on,
                 the entities it meets and the regions it bounds
  topology       closed REGIONS (atomic parts: area, perimeter, interior point, boundary
                 entities, holes, nesting, the regions they share an edge with and on which
                 side, the hatch that fills them, the set-out lines they span), OPEN features
  datums         the set-out lines (x = vertical, y = horizontal) with stated levels
  annotations    dimensions (what they measure: points, set-out lines, entities, candidate),
                 texts (what they say parsed: level, sizes, slope, existing/proposed; where:
                 region, nearest entity), leaders (what they point at)
  relationships  candidates the geometry supports, each with evidence and a confidence:
                 thickness / opening / offset / pitch / step / slope between set-out lines (and
                 the region across), repeated distances, parallel / perpendicular / collinear /
                 equal-length / concentric / symmetric entities, mirrored and repeated regions,
                 regions resting on / beside / inside others, regions on stated levels
  candidates     sizes the engine measured, grouped when equal (the ids parameters name)
  baseline       the generic parametric model the engine built (what the AI improves on)

All lengths in millimetres, levels in metres, angles in degrees (0° = +x, counter-clockwise).
"""

from __future__ import annotations

import itertools
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from .facts import build_facts
from .ir import Analysis, GapKind, Item, Role
from .program import Program
from .topology import DatumIndex, Region, Topology, of, point_in_ring

PREFIX = {"LINE": "L", "LWPOLYLINE": "PL", "POLYLINE": "PL", "ARC": "A", "CIRCLE": "C", "HATCH": "H", "DIMENSION": "D",
          "TEXT": "T", "MTEXT": "T", "ATTRIB": "T", "INSERT": "B", "LEADER": "LD", "POINT": "PT", "SOLID": "S", "TRACE": "S",
          "3DFACE": "S", "ELLIPSE": "E", "SPLINE": "SP"}

GAP_TYPE = {GapKind.SOLID: "thickness", GapKind.VOID: "opening", GapKind.OPEN: "offset", GapKind.PITCH: "pitch",
            GapKind.CHAIN: "step", GapKind.SLOPE: "slope_run", GapKind.LEG: "chamfer", GapKind.RUN: "run", GapKind.RISE: "rise",
            GapKind.OFFSET: "offset_from_axis", GapKind.DIM: "dimensioned", GapKind.ARC: "arc", GapKind.DIAMETER: "diameter",
            GapKind.RING: "ring_wall"}

LEVEL_RE = re.compile(r"\b(?:R\.?L|LEVEL|LVL|H\.?F\.?L|L\.?W\.?L|EL)\b\.?\D{0,12}?([+-]?\d{1,4}\.\d{2,3})", re.IGNORECASE)
NUM_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])")
SLOPE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\(?\s*([VH])\s*\)?\s*[:/]\s*(\d+(?:\.\d+)?)\s*\(?\s*([VH])", re.IGNORECASE)
STATUS_RE = re.compile(r"\b(EXIST(?:ING|\.)?|EXG\.?|OLD|PROP(?:OSED|\.)?|NEW|DISMANTL\w*|TO BE \w+)\b", re.IGNORECASE)


def entity_id(it: Item) -> str:
    return f"{PREFIX.get(it.dxftype, 'E')}{it.index}"


def entity_index(eid: str) -> int | None:
    """'PL12', 'L12', 'R…' → 12 for entity ids (any letter prefix); None for anything else."""
    m = re.fullmatch(r"[A-Z]{1,2}(\d+)", eid or "")
    return int(m.group(1)) if m else None


def _r(v: float, nd: int = 1) -> float:
    return round(float(v), nd)


class _Ctx:
    def __init__(self, an: Analysis, topo: Topology):
        self.an = an
        self.dr = an.drawing
        self.u = an.drawing.units_mm
        self.topo = topo
        self.dix = DatumIndex(an)
        self.item_regions: dict[int, list[str]] = defaultdict(list)
        for r in topo.regions:
            for i in r.items:
                self.item_regions[i].append(r.id)
        self.ids = {it.index: entity_id(it) for it in an.drawing.items}

    def mm(self, v: float) -> float:
        return _r(v * self.u)

    def pt(self, p) -> list[float]:
        return [self.mm(p[0]), self.mm(p[1])]

    def bbox(self, pts) -> list[float]:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return [self.mm(min(xs)), self.mm(min(ys)), self.mm(max(xs)), self.mm(max(ys))]

    def datums_of(self, it: Item) -> dict[str, list[str]]:
        out: dict[str, set[str]] = {"x": set(), "y": set()}
        for k in it.vertex_pts or range(len(it.pts)):
            for ax in ("x", "y"):
                b = self.an.slot_datum.get((it.index, k, ax))
                if b and abs(b[1]) <= self.dr.tol:
                    out[ax].add(b[0])
        return {ax: sorted(v) for ax, v in out.items() if v}

    def region_side(self, r: Region, other: Region) -> str:
        """Where `other` lies relative to r, judged from the edge they share."""
        a, b = r.bbox, other.bbox
        tol = self.dr.tol * 2
        if abs(b[1] - a[3]) <= tol:
            return "above"
        if abs(b[3] - a[1]) <= tol:
            return "below"
        if abs(b[0] - a[2]) <= tol:
            return "right"
        if abs(b[2] - a[0]) <= tol:
            return "left"
        dx, dy = other.inside[0] - r.inside[0], other.inside[1] - r.inside[1]
        return ("right" if dx > 0 else "left") if abs(dx) > abs(dy) else ("above" if dy > 0 else "below")


# ── entities ─────────────────────────────────────────────────────────────────────


def _props(it: Item) -> dict:
    p = it.extra.get("props") or {}
    return {k: v for k, v in p.items() if v not in (None, "")}


def _entity(c: _Ctx, it: Item, compact: bool) -> dict:
    t = it.dxftype
    e: dict = {"id": c.ids[it.index], "type": t, "layer": it.layer}
    if not compact or it.role not in (Role.STRUCTURAL, Role.ANNOTATION):
        e["role"] = it.role.value
    props = _props(it)
    if props and not compact:
        e["props"] = props
    elif props.get("linetype") not in (None, "CONTINUOUS", "BYLAYER"):
        e["linetype"] = props["linetype"]
    if "/" in (it.src or ""):
        e["in_block"] = it.extra.get("block_path") or it.src.split("/")[0]
    pts = it.pts
    if t == "LINE" and len(pts) >= 2:
        (x0, y0), (x1, y1) = pts[0], pts[1]
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0
        e.update(start=c.pt(pts[0]), end=c.pt(pts[1]), length=c.mm(math.dist(pts[0], pts[1])), angle=_r(ang, 2),
                 orientation="horizontal" if min(ang, 180 - ang) < 0.05 else "vertical" if abs(ang - 90) < 0.05 else "inclined")
    elif t in ("LWPOLYLINE", "POLYLINE"):
        vs = [pts[k] for k in (it.vertex_pts or range(len(pts)))]
        e["closed"] = it.closed
        e["n_vertices"] = len(vs)
        if not compact or len(vs) <= 16:
            e["vertices"] = [c.pt(p) for p in vs]
        if it.bulges and any(abs(b) > 1e-9 for b in it.bulges):
            e["has_arcs"] = True
        segs = [(vs[i], vs[i + 1]) for i in range(len(vs) - 1)] + ([(vs[-1], vs[0])] if it.closed and len(vs) > 2 else [])
        e["perimeter" if it.closed else "length"] = c.mm(sum(math.dist(a, b) for a, b in segs))
        if it.closed and len(vs) >= 3:
            a = 0.0
            for i, (x0, y0) in enumerate(vs):
                x1, y1 = vs[(i + 1) % len(vs)]
                a += x0 * y1 - x1 * y0
            e["area_m2"] = _r(abs(a) / 2 * c.u * c.u / 1e6, 4)
        incl = sum(1 for a, b in segs if abs(a[0] - b[0]) > c.dr.tol and abs(a[1] - b[1]) > c.dr.tol)
        if incl:
            e["inclined_segments"] = incl
    elif t in ("ARC", "CIRCLE"):
        r = it.radius or 0.0
        e.update(center=c.pt(pts[0]), radius=c.mm(r))
        if t == "ARC":
            a0, a1 = it.extra.get("start_angle", 0.0), it.extra.get("end_angle", 0.0)
            sweep = (a1 - a0) % 360.0 or 360.0
            e.update(start_angle=_r(a0, 2), end_angle=_r(a1, 2), sweep=_r(sweep, 2), arc_length=c.mm(r * math.radians(sweep)))
        else:
            e.update(diameter=c.mm(2 * r))
    elif t == "HATCH":
        e["pattern"] = it.extra.get("pattern") or "SOLID"
        rings = it.extra.get("rings", [])
        e["boundary_loops"] = len(rings)
        e["fills_regions"] = sorted((r.id for r in c.topo.regions if it.index in r.hatches), key=lambda s: int(s[1:]))
    elif t == "DIMENSION":
        e.update(_dimension(c, it))
    elif t in ("TEXT", "MTEXT", "ATTRIB"):
        e.update(_text(c, it))
    elif t == "INSERT":
        e.update(block=it.extra.get("block"), insert=c.pt(pts[0]))
    elif t == "LEADER" and pts:
        e["points"] = [c.pt(p) for p in pts]
        tip = pts[0]
        hit = c.topo.items_at(tip)
        reg = c.topo.region_at(tip)
        e["points_at"] = {"entities": sorted(c.ids[i] for i in hit)[:6], "region": reg.id if reg else None}
    if pts and t not in ("LINE", "TEXT", "MTEXT", "ATTRIB") and not (compact and t in ("ARC", "CIRCLE", "INSERT")):
        e["bbox"] = c.bbox(pts)
    if it.role in (Role.STRUCTURAL, Role.REFERENCE):
        ds = c.datums_of(it)
        if ds:
            e["datums"] = ds
        conn = c.topo.connections.get(it.index)
        if conn:
            e["connects_to"] = sorted((c.ids[i] for i in conn), key=lambda s: (len(s), s))[: 12 if compact else 60]
        regs = c.item_regions.get(it.index)
        if regs:
            e["bounds_regions"] = sorted(regs, key=lambda s: int(s[1:]))
    return e


def _dimension(c: _Ctx, it: Item) -> dict:
    out: dict = {"dimtype": it.extra.get("dimtype"), "measurement": c.mm(it.extra.get("measurement") or 0.0),
                 "text": (it.text or "").strip() or "<>"}
    if len(it.pts) >= 3:
        p1, p2 = it.pts[1], it.pts[2]
        out["definition_points"] = [c.pt(p1), c.pt(p2)]
        out["dimension_line_at"] = c.pt(it.pts[0])
        dx, dy = abs(p2[0] - p1[0]), abs(p2[1] - p1[1])
        ang = it.extra.get("angle", 0.0)
        axis = "x" if dy < c.dr.tol < dx else "y" if dx < c.dr.tol < dy else ("x" if abs(math.sin(math.radians(ang))) < 0.5 else "y")
        out["axis"] = axis
        k = 0 if axis == "x" else 1
        ends = [c.dix.at(axis, p1[k]), c.dix.at(axis, p2[k])]
        out["between_datums"] = ends
        ents = sorted({c.ids[i] for p in (p1, p2) for i in c.topo.items_at(p)})
        if ents:
            out["measures_entities"] = ents[:8]
        for g in c.an.gaps.values():
            if it.index in g.dims and g.cluster:
                out["candidate"] = g.cluster
                break
    return out


def parse_text(s: str) -> dict:
    """What a note states, without deciding what it means."""
    out: dict = {}
    m = LEVEL_RE.search(s)
    if m:
        out["level_m"] = float(m.group(1))
    nums = [float(x) for x in NUM_RE.findall(s)]
    if nums:
        out["numbers"] = nums[:6]
    m = SLOPE_RE.search(s)
    if m and {m.group(2).upper(), m.group(4).upper()} == {"V", "H"}:
        v, h = (float(m.group(1)), float(m.group(3))) if m.group(2).upper() == "V" else (float(m.group(3)), float(m.group(1)))
        out["slope_h_per_v"] = _r(h / v, 4) if v else None
    st = STATUS_RE.search(s)
    if st:
        w = st.group(1).upper()
        out["status"] = "existing" if w.startswith(("EXIST", "EXG", "OLD")) else "proposed" if w.startswith(("PROP", "NEW")) else w.lower()
    return out


def _text(c: _Ctx, it: Item) -> dict:
    s = " ".join((it.text or "").split())
    out: dict = {"text": s[:160], "at": c.pt(it.pts[0]), "height": c.mm(it.text_height or 0.0)}
    rot = it.extra.get("rotation", 0.0)
    if abs(rot) > 0.01:
        out["rotation"] = _r(rot, 2)
    parsed = parse_text(s)
    if parsed:
        out["states"] = parsed
    reg = c.topo.region_at(it.pts[0])
    if reg:
        out["inside_region"] = reg.id
    return out


def _nearest_structural(c: _Ctx, p, limit: float) -> tuple[str | None, float]:
    best, bd = None, limit
    for u, v, its in c.topo.edges:
        a, b = c.topo.nodes[u], c.topo.nodes[v]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        d = math.dist(p, (a[0] + t * dx, a[1] + t * dy))
        if d < bd:
            best, bd = c.ids[min(its)], d
    return best, bd


# ── regions ──────────────────────────────────────────────────────────────────────


def _region(c: _Ctx, r: Region, compact: bool) -> dict:
    xs, ys = c.dix.of_ring(r.ring)
    out = {
        "id": r.id, "area_m2": _r(r.area * c.u * c.u / 1e6, 4), "perimeter": c.mm(r.perimeter),
        "bbox": [c.mm(v) for v in r.bbox], "width": c.mm(r.bbox[2] - r.bbox[0]), "height": c.mm(r.bbox[3] - r.bbox[1]),
        "inside_point": c.pt(r.inside), "n_vertices": len(r.ring),
        "bounded_by": sorted((c.ids[i] for i in r.items), key=lambda s: (len(s), s))[: 16 if compact else 200],
        "fill": r.pattern or "none",
        "datums": {"x": xs[:14], "y": ys[:14]},
        "layers": dict(Counter(c.dr.items[i].layer for i in r.items).most_common(3)),
    }
    if not compact or len(r.ring) <= 12:
        out["outline"] = [c.pt(p) for p in r.ring]
    if r.holes:
        out["holes"] = len(r.holes)
    if r.parent:
        out["inside_region"] = r.parent
    inclined = sum(1 for i in range(len(r.ring)) if abs(r.ring[i][0] - r.ring[(i + 1) % len(r.ring)][0]) > c.dr.tol
                   and abs(r.ring[i][1] - r.ring[(i + 1) % len(r.ring)][1]) > c.dr.tol)
    if inclined:
        out["inclined_edges"] = inclined
    regions = c.topo.by_id()
    out["touches"] = [{"region": k, "side": c.region_side(r, regions[k]), "shared_length": c.mm(v)}
                      for k, v in sorted(r.neighbours.items(), key=lambda kv: -kv[1])][:10]
    return out


# ── relationship candidates ─────────────────────────────────────────────────────


def _relationships(c: _Ctx, compact: bool) -> list[dict]:
    an, topo = c.an, c.topo
    rel: list[dict] = []
    cap = 400 if compact else 4000

    # sizes between set-out lines, and the region they cross
    datum_items = {d.id: d.items for d in an.datums.values()}
    for cl in sorted(an.clusters.values(), key=lambda cl: (-cl.confidence, -len(cl.gaps))):
        for gid in cl.gaps[:6]:
            g = an.gaps.get(gid)
            if g is None or g.axis not in ("x", "y"):
                continue
            row: dict = {"type": GAP_TYPE.get(g.kind, g.kind.value), "datums": [g.a, g.b], "value": c.mm(g.value),
                         "candidate": cl.id, "repeats": len(cl.gaps), "confidence": round(cl.confidence, 2)}
            if g.sample is not None:
                k = 0 if g.axis == "x" else 1
                va, vb = an.datums[g.a].value, an.datums[g.b].value
                mid = list(g.sample)
                mid[k] = (va + vb) / 2
                reg = topo.region_at(tuple(mid))
                if reg:
                    row["across_region"] = reg.id
                faces = [sorted(c.ids[i] for i in datum_items.get(d, ()) if an.drawing.items[i].role == Role.STRUCTURAL)[:3] for d in (g.a, g.b)]
                if any(faces):
                    row["faces"] = faces
            if g.sym_axis:
                row["centred_on"] = g.sym_axis
            if g.dims:
                row["dimensioned_by"] = [c.ids[i] for i in g.dims][:3]
            if g.slope:
                row["ratio_h_per_v"] = _r(g.slope[4], 4)
            ev = [e.detail for e in cl.evidence][:3]
            if ev:
                row["evidence"] = ev
            rel.append(row)

    # entity constraints the geometry shows
    by_kind: dict[str, list] = defaultdict(list)
    for k in an.constraints:
        if k.kind in ("horizontal", "vertical", "coincident"):
            continue
        by_kind[k.kind].append(k)
    for kind, ks in by_kind.items():
        for k in sorted(ks, key=lambda k: -len(k.items))[: 30 if compact else 400]:
            rel.append({"type": kind, "entities": [c.ids[i] for i in k.items][:12], "confidence": round(k.confidence, 2),
                        "kept_by": k.kept_by, **({"detail": k.detail} if k.detail else {})})

    regions = topo.regions
    tol = an.drawing.tol * 2

    def dims(r):
        return (r.bbox[2] - r.bbox[0], r.bbox[3] - r.bbox[1])

    # mirrored regions about each symmetry axis
    for ax_id in an.axes:
        ad = an.datums.get(ax_id)
        if ad is None:
            continue
        k = 0 if ad.axis == "x" else 1
        a = ad.value
        done: set[str] = set()
        for r in regions:
            if r.id in done:
                continue
            lo, hi = r.bbox[k], r.bbox[k + 2]
            for s in regions:
                if s is r or s.id in done:
                    continue
                if abs(s.bbox[k] - (2 * a - hi)) <= tol and abs(s.bbox[k + 2] - (2 * a - lo)) <= tol and \
                        abs(s.bbox[1 - k] - r.bbox[1 - k]) <= tol and abs(s.bbox[3 - k] - r.bbox[3 - k]) <= tol and abs(s.area - r.area) <= max(r.area * 0.01, tol * tol):
                    rel.append({"type": "mirrored_regions", "regions": [r.id, s.id], "about": ax_id, "confidence": 0.95})
                    done.update((r.id, s.id))
                    break

    # repeated (congruent) regions: cells, piers, rings
    groups: dict[tuple, list[Region]] = defaultdict(list)
    for r in regions:
        w, h = dims(r)
        groups[(round(w / tol), round(h / tol), round(r.area / max(tol * tol, 1e-12) / 50))].append(r)
    for rs in groups.values():
        if len(rs) >= 2:
            rs = sorted(rs, key=lambda r: (r.bbox[0], r.bbox[1]))
            steps = sorted({c.mm(b.bbox[0] - a.bbox[0]) for a, b in itertools.pairwise(rs)} - {0.0})
            rel.append({"type": "repeated_regions", "regions": [r.id for r in rs], "size": [c.mm(dims(rs[0])[0]), c.mm(dims(rs[0])[1])],
                        **({"pitch_x": steps[:3]} if steps else {}), "confidence": 0.9})

    # how regions sit on each other
    for r in regions:
        for k, L in r.neighbours.items():
            s = topo.by_id()[k]
            side = c.region_side(r, s)
            if side == "below" and L * c.u > 1:
                rel.append({"type": "rests_on", "regions": [r.id, k], "shared_length": c.mm(L), "confidence": 0.9})
            elif side == "right" and L * c.u > 1:
                rel.append({"type": "beside", "regions": [r.id, k], "shared_length": c.mm(L), "confidence": 0.9})
        if r.parent:
            rel.append({"type": "inside", "regions": [r.id, r.parent], "confidence": 1.0})

    # regions bounded by a stated level
    stated = {d: (w, v) for d, _i, w, v in an.stated_levels}
    for r in regions:
        lo = c.dix.at("y", r.bbox[1])
        hi = c.dix.at("y", r.bbox[3])
        for d, where in ((lo, "bottom"), (hi, "top")):
            if d in stated:
                rel.append({"type": "on_level", "region": r.id, "edge": where, "datum": d, "level_text": stated[d][0],
                            "level_m": stated[d][1], "confidence": 0.95})
    if compact:  # minor sizes and adjacency (already on each region) are trimmed; the strong ones stay whole
        minor = {"offset": 30, "step": 30, "offset_from_axis": 20, "run": 12, "rise": 12, "rests_on": 0, "beside": 0}
        seen: Counter = Counter()
        kept = []
        for row in rel:
            t = row["type"]
            if t in minor:
                seen[t] += 1
                if seen[t] > minor[t]:
                    continue
            kept.append(row)
        rel = kept
    return rel[:cap]


# ── the document ─────────────────────────────────────────────────────────────────


def cad_json(an: Analysis, prog: Program | None = None, for_ai: bool = False) -> dict:
    topo = of(an)
    c = _Ctx(an, topo)
    dr = an.drawing
    items = dr.items

    layers: dict[str, dict] = {}
    for it in items:
        L = layers.setdefault(it.layer, {"name": it.layer, "entities": 0, "types": Counter(), "roles": Counter()})
        L["entities"] += 1
        L["types"][it.dxftype] += 1
        L["roles"][it.role.value] += 1
        p = it.extra.get("props") or {}
        if "layer_color" in p:
            L["color"] = p["layer_color"]
        if "layer_linetype" in p:
            L["linetype"] = p["layer_linetype"]
    for L in layers.values():
        L["types"], L["roles"] = dict(L["types"]), dict(L["roles"])

    def keep(it: Item) -> bool:
        if not for_ai:
            return True
        if it.role in (Role.STRUCTURAL, Role.REFERENCE):
            return True
        return it.dxftype in ("TEXT", "MTEXT", "ATTRIB", "DIMENSION", "HATCH", "LEADER", "INSERT")

    entities = [_entity(c, it, for_ai) for it in items if keep(it)]
    if for_ai:  # where each note sits relative to the structure
        lim = max(dr.extent[2] - dr.extent[0], dr.extent[3] - dr.extent[1]) * 0.08
        for e in entities:
            if e["type"] in ("TEXT", "MTEXT", "ATTRIB") and "inside_region" not in e:
                i = entity_index(e["id"])
                near, d = _nearest_structural(c, items[i].pts[0], lim)
                if near:
                    e["nearest_entity"] = near
                    e["distance"] = c.mm(d)
    omitted = Counter(f"{it.dxftype} on {it.layer}" for it in items if not keep(it))

    datums = []
    stated = {d: (w, v) for d, _i, w, v in an.stated_levels}
    for d in sorted(an.datums.values(), key=lambda d: (d.axis, d.value)):
        row: dict = {"id": d.id, "axis": d.axis, "at": c.mm(d.value)}
        if d.source != "vertex":
            row["kind"] = d.source
        if d.weak:
            row["loose_lines_only"] = True
        if d.id in stated:
            row["stated_level"] = {"text": stated[d.id][0], "value_m": stated[d.id][1]}
        if not for_ai:
            row["entities"] = sorted(c.ids[i] for i in d.items)[:40]
        if prog is not None and d.id in prog.formulas:
            row["formula"] = prog.formulas[d.id]
        datums.append(row)

    doc: dict = {
        "format": "dxf-autoparam/cad-json-1",
        "drawing": {
            "file": Path(dr.path).name, "units": "mm", "units_mm_per_drawing_unit": dr.units_mm, "levels": "metres",
            "level_datum_mm": an.level_offset_mm, "extent": [c.mm(v) for v in dr.extent], "layout": dr.layout,
            "entities": len(items), "by_type": dict(Counter(it.dxftype for it in items)),
            "by_role": dict(Counter(it.role.value for it in items)), "layers": sorted(layers.values(), key=lambda L: -L["entities"]),
            "reader_notes": dr.notes, "unsupported": dr.unsupported,
            "symmetry_axes": {ax: d for ax, d in an.global_axis.items() if d},
        },
        "entities": entities,
        "topology": {
            "regions": [_region(c, r, for_ai) for r in topo.regions],
            "open_features": [c.ids[i] for i in topo.open_items],
            "notes": topo.notes,
        },
        "datums": datums,
        "relationships": _relationships(c, for_ai),
    }
    if omitted:
        doc["drawing"]["summarised_not_listed"] = dict(omitted.most_common(20))
    if prog is not None:
        facts = build_facts(prog)
        doc["candidates"] = facts["candidate_values"]
        doc["baseline"] = {"parameters": facts["baseline_parameters"], "relations": facts["baseline_relations"],
                           "datum_formulas": {d: prog.formulas[d] for d in prog.formulas if any(n in prog.params for n in prog.formulas[d].split())}}
    return doc


SPLIT = {"drawing": ["drawing"], "geometry": ["entities"], "topology": ["topology"], "datums": ["datums"],
         "relationships": ["relationships"], "parameters": ["candidates", "baseline"]}


def write_split(doc: dict, out_dir: str) -> list[str]:
    """drawing.json, geometry.json, topology.json, datums.json, relationships.json, parameters.json"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, keys in SPLIT.items():
        part = {k: doc[k] for k in keys if k in doc}
        if part:
            p = out / f"{name}.json"
            p.write_text(json.dumps(part, indent=1, default=str))
            written.append(str(p))
    return written


def region_items(an: Analysis, region_ids: list[str]) -> set[int]:
    regions = of(an).by_id()
    out: set[int] = set()
    for rid in region_ids:
        r = regions.get(rid)
        if r is not None:
            out |= r.items
    return out


def regions_containing(an: Analysis, p) -> list[str]:
    return [r.id for r in of(an).regions if point_in_ring(p, r.ring)]
