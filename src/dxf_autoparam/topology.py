"""The drawing as a planar graph: nodes, edges, closed REGIONS, how they nest and which ones touch.

A GAD is mostly drawn with loose LINEs, so "the wing wall" exists only as the closed area its
lines bound. This module recovers those areas — the atomic parts of the structure — without
knowing what any of them is:

  1. every structural entity becomes straight segments (arcs and circles as fine chords);
  2. segments are split where they cross and where another segment ends on them (T-junctions);
  3. dangling chains (a ground line, a track rail) are set aside as open features;
  4. the planar faces are traced with half-edges (the face on the left of each half-edge);
  5. bounded faces are regions; a disconnected drawing inside a region is its hole, and the
     regions of that inner drawing are nested in it;
  6. each region gets its area, perimeter, an interior point, its boundary entities, the regions
     it shares an edge with (and how long), and the hatch (material) that fills it.

Pure geometry: no layer names, no structure types.
"""

from __future__ import annotations

import bisect
import itertools
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .display import primitives
from .ir import Analysis, Drawing, Role

Point = tuple[float, float]


@dataclass
class Region:
    id: str
    ring: list[Point]  # outer boundary, counter-clockwise, drawing units
    holes: list[list[Point]] = field(default_factory=list)
    area: float = 0.0  # net of holes, drawing units²
    perimeter: float = 0.0
    centroid: Point = (0.0, 0.0)
    inside: Point = (0.0, 0.0)  # a point surely inside (labels, hatch and text tests)
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    items: set[int] = field(default_factory=set)  # entities on its boundary
    parent: str | None = None  # the region it lies inside
    neighbours: dict[str, float] = field(default_factory=dict)  # region id → shared boundary length
    hatches: list[int] = field(default_factory=list)  # hatch entities that fill it
    pattern: str | None = None
    component: int = 0  # connected piece of linework it belongs to


@dataclass
class Topology:
    nodes: list[Point]
    edges: list[tuple[int, int, frozenset[int]]]  # node a, node b, entities drawing it
    regions: list[Region]
    open_items: list[int]  # structural entities that bound no region (ground lines, rails, level lines)
    connections: dict[int, set[int]]  # entity → entities it meets (shared point, T-junction or crossing)
    node_items: dict[int, set[int]]
    tol: float
    notes: list[str] = field(default_factory=list)
    item_border: dict[int, dict[str, float]] = field(default_factory=dict)  # entity → region → length of it bordering that region
    _grid: dict | None = None
    _cell: float = 1.0

    def by_id(self) -> dict[str, Region]:
        return {r.id: r for r in self.regions}

    def items_at(self, p: Point) -> set[int]:
        """Entities that pass through point p (a dimension's definition point, a leader's tip)."""
        k = self._key(p)
        best: set[int] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for n in (self._grid or {}).get((k[0] + dx, k[1] + dy), ()):
                    if math.dist(self.nodes[n], p) <= self.tol:
                        best |= self.node_items.get(n, set())
        return best

    def region_at(self, p: Point) -> Region | None:
        """The innermost region containing p."""
        hit = [r for r in self.regions if _in_region(p, r)]
        return min(hit, key=lambda r: abs(_signed_area(r.ring))) if hit else None

    def _key(self, p: Point) -> tuple[int, int]:
        return (math.floor(p[0] / self._cell), math.floor(p[1] / self._cell))


# ── small geometry ───────────────────────────────────────────────────────────────


def _signed_area(ring: list[Point]) -> float:
    s = 0.0
    for i, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(i + 1) % len(ring)]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _perimeter(ring: list[Point]) -> float:
    return sum(math.dist(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring)))


def _centroid(ring: list[Point]) -> Point:
    a = _signed_area(ring)
    if abs(a) < 1e-12:
        xs, ys = zip(*ring, strict=True)
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    cx = cy = 0.0
    for i, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(i + 1) % len(ring)]
        f = x0 * y1 - x1 * y0
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    return (cx / (6 * a), cy / (6 * a))


def point_in_ring(p: Point, ring: list[Point]) -> bool:
    x, y = p
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if xc > x:
                inside = not inside
    return inside


def _in_region(p: Point, r: Region) -> bool:
    return point_in_ring(p, r.ring) and not any(point_in_ring(p, h) for h in r.holes)


def _interior_point(ring: list[Point], holes: list[list[Point]]) -> Point:
    """A point well inside the region: its centroid when that is inside, else the middle of the widest
    inside span on a few horizontal scan lines."""
    c = _centroid(ring)
    if point_in_ring(c, ring) and not any(point_in_ring(c, h) for h in holes):
        return c
    ys = [p[1] for p in ring]
    y0, y1 = min(ys), max(ys)
    best, best_w = c, -1.0
    for f in (0.5, 0.37, 0.63, 0.23, 0.77, 0.11, 0.89):
        y = y0 + (y1 - y0) * f
        xs: list[float] = []
        for poly in [ring, *holes]:
            for i in range(len(poly)):
                (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
                if (ay > y) != (by > y):
                    xs.append(ax + (y - ay) * (bx - ax) / (by - ay))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            if xs[k + 1] - xs[k] > best_w:
                best_w, best = xs[k + 1] - xs[k], ((xs[k] + xs[k + 1]) / 2, y)
    return best


def _cross(p, q, r, s) -> Point | None:
    """Proper crossing of segments pq and rs (interiors only)."""
    d = (q[0] - p[0]) * (s[1] - r[1]) - (q[1] - p[1]) * (s[0] - r[0])
    if abs(d) < 1e-15:
        return None
    t = ((r[0] - p[0]) * (s[1] - r[1]) - (r[1] - p[1]) * (s[0] - r[0])) / d
    u = ((r[0] - p[0]) * (q[1] - p[1]) - (r[1] - p[1]) * (q[0] - p[0])) / d
    eps = 1e-9
    if eps < t < 1 - eps and eps < u < 1 - eps:
        return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
    return None


# ── the graph ────────────────────────────────────────────────────────────────────


def _segments(dr: Drawing) -> list[tuple[Point, Point, int]]:
    out = []
    for it in dr.items:
        if it.role != Role.STRUCTURAL:
            continue
        for prim in primitives(it, it.pts, it.radius, None, dr.units_mm):
            if prim["k"] != "p" or len(prim["pts"]) < 2:
                continue
            pts = [tuple(p) for p in prim["pts"]]
            if prim.get("closed") and math.dist(pts[0], pts[-1]) > 0:
                pts.append(pts[0])
            for a, b in itertools.pairwise(pts):
                out.append((a, b, it.index))
    return out


def _cells_of(a: Point, b: Point, cell: float) -> set[tuple[int, int]]:
    n = max(1, int(math.dist(a, b) / (cell / 2)))
    out = set()
    for k in range(n + 1):
        x = a[0] + (b[0] - a[0]) * k / n
        y = a[1] + (b[1] - a[1]) * k / n
        cx, cy = math.floor(x / cell), math.floor(y / cell)
        out.update({(cx, cy), (cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)})
    return out


def build_topology(dr: Drawing, max_segments: int = 40000) -> Topology:
    tol = dr.tol
    segs = _segments(dr)
    notes: list[str] = []
    if len(segs) > max_segments:
        notes.append(f"{len(segs)} segments: regions not traced (limit {max_segments})")
        return Topology([], [], [], [], {}, {}, tol, notes)
    x0, y0, x1, y1 = dr.extent
    cell = max(max(x1 - x0, y1 - y0, tol) / 120.0, 20 * tol)

    nodes: list[Point] = []
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)

    def node(p: Point) -> int:
        kx, ky = math.floor(p[0] / cell), math.floor(p[1] / cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for n in grid.get((kx + dx, ky + dy), ()):
                    if math.dist(nodes[n], p) <= tol:
                        return n
        nodes.append(p)
        grid[(kx, ky)].append(len(nodes) - 1)
        return len(nodes) - 1

    ends = [(node(a), node(b), i) for a, b, i in segs]
    # crossings: interiors that cross each other become nodes too
    seg_cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    for s, (a, b, _i) in enumerate(segs):
        for c in _cells_of(a, b, cell):
            seg_cells[c].append(s)
    tested: set[tuple[int, int]] = set()
    for members in seg_cells.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                s, t = members[i], members[j]
                if (s, t) in tested:
                    continue
                tested.add((s, t))
                (p, q, _), (r, w, _) = segs[s], segs[t]
                if ends[s][0] in ends[t][:2] or ends[s][1] in ends[t][:2]:
                    continue
                x = _cross(p, q, r, w)
                if x is not None:
                    node(x)

    # split every segment at the nodes on it
    edges: dict[tuple[int, int], set[int]] = defaultdict(set)
    for s, (a, b, item) in enumerate(segs):
        na, nb = ends[s][0], ends[s][1]
        if na == nb:
            continue
        L = math.dist(a, b)
        dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        on: list[tuple[float, int]] = []
        seen: set[int] = set()
        for c in _cells_of(a, b, cell):
            for n in grid.get(c, ()):
                if n in (na, nb) or n in seen:
                    continue
                seen.add(n)
                px, py = nodes[n][0] - a[0], nodes[n][1] - a[1]
                t = px * dx + py * dy
                if tol < t < L - tol and abs(px * dy - py * dx) <= tol:
                    on.append((t, n))
        chain = [na] + [n for _t, n in sorted(on)] + [nb]
        for u, v in itertools.pairwise(chain):
            if u != v:
                edges[(min(u, v), max(u, v))].add(item)

    node_items: dict[int, set[int]] = defaultdict(set)
    adj: dict[int, set[int]] = defaultdict(set)
    for (u, v), its in edges.items():
        node_items[u] |= its
        node_items[v] |= its
        adj[u].add(v)
        adj[v].add(u)
    connections: dict[int, set[int]] = defaultdict(set)
    for its in node_items.values():
        for i in its:
            connections[i] |= its - {i}

    # dangling chains are open features, not boundaries
    live = {k for k in edges}
    deg = {n: len(a) for n, a in adj.items()}
    stack = [n for n, d in deg.items() if d == 1]
    while stack:
        n = stack.pop()
        for m in list(adj[n]):
            e = (min(n, m), max(n, m))
            if e in live:
                live.discard(e)
                deg[n] -= 1
                deg[m] -= 1
                if deg[m] == 1:
                    stack.append(m)

    out: dict[int, list[int]] = defaultdict(list)
    for u, v in live:
        out[u].append(v)
        out[v].append(u)
    for n, ns in out.items():
        ns.sort(key=lambda m: math.atan2(nodes[m][1] - nodes[n][1], nodes[m][0] - nodes[n][0]))
    pos = {(n, m): k for n, ns in out.items() for k, m in enumerate(ns)}

    face_of: dict[tuple[int, int], int] = {}
    faces: list[list[int]] = []
    for start in pos:
        if start in face_of:
            continue
        f = len(faces)
        cyc: list[int] = []
        he = start
        while he not in face_of:
            face_of[he] = f
            cyc.append(he[0])
            u, v = he
            ns = out[v]
            he = (v, ns[(pos[(v, u)] - 1) % len(ns)])
        faces.append(cyc)

    # connected pieces of linework
    parent_uf = {n: n for n in out}

    def find(n: int) -> int:
        while parent_uf[n] != n:
            parent_uf[n] = parent_uf[parent_uf[n]]
            n = parent_uf[n]
        return n

    for u, v in live:
        parent_uf[find(u)] = find(v)

    min_area = (3 * tol) ** 2
    regions: list[Region] = []
    face_region: dict[int, int] = {}
    outers: list[tuple[int, list[Point]]] = []  # (face, ring) of each piece's outer boundary
    for f, cyc in enumerate(faces):
        ring = [nodes[n] for n in cyc]
        a = _signed_area(ring)
        if a > min_area:
            face_region[f] = len(regions)
            xs, ys = [p[0] for p in ring], [p[1] for p in ring]
            regions.append(Region(id="", ring=ring, area=a, perimeter=_perimeter(ring), bbox=(min(xs), min(ys), max(xs), max(ys)),
                                  component=find(cyc[0])))
        elif a < 0:
            outers.append((f, ring))

    # a piece drawn inside a region is a hole in it; that piece's regions are nested in it
    piece_parent: dict[int, int] = {}
    for f, ring in outers:
        piece = find(faces[f][0])
        host = [k for k, r in enumerate(regions) if r.component != piece and point_in_ring(ring[0], r.ring)]
        if host:  # the innermost region around it
            k = min(host, key=lambda k: regions[k].area)
            regions[k].holes.append(ring[::-1])
            piece_parent[piece] = k
            face_region[f] = k  # its outer side borders the host
    for r in regions:
        r.area = _signed_area(r.ring) - sum(abs(_signed_area(h)) for h in r.holes)
        r.perimeter = _perimeter(r.ring) + sum(_perimeter(h) for h in r.holes)
        r.centroid = _centroid(r.ring)
        r.inside = _interior_point(r.ring, r.holes)

    order = sorted(range(len(regions)), key=lambda k: (-regions[k].bbox[3], regions[k].bbox[0]))
    for n, k in enumerate(order, 1):
        regions[k].id = f"R{n}"
    for r in regions:
        if r.component in piece_parent:
            r.parent = regions[piece_parent[r.component]].id

    item_border: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (u, v), its in edges.items():
        if (u, v) not in live:
            continue
        # a face maps to its region; a piece's outer face maps to the region it is a hole in
        ra, rb = face_region.get(face_of.get((u, v))), face_region.get(face_of.get((v, u)))
        L = math.dist(nodes[u], nodes[v])
        for r in {ra, rb} - {None}:
            regions[r].items |= its
            for i in its:
                item_border[i][regions[r].id] += L
        if ra is not None and rb is not None and ra != rb:
            ia, ib = regions[ra].id, regions[rb].id
            regions[ra].neighbours[ib] = regions[ra].neighbours.get(ib, 0.0) + L
            regions[rb].neighbours[ia] = regions[rb].neighbours.get(ia, 0.0) + L

    _hatch(dr, regions)
    bounded = set().union(*(r.items for r in regions)) if regions else set()
    open_items = sorted({i for _a, _b, i in segs} - bounded)
    topo = Topology(nodes=nodes, edges=[(u, v, frozenset(i)) for (u, v), i in edges.items()], regions=sorted(regions, key=lambda r: int(r.id[1:])),
                    open_items=open_items, connections=dict(connections), node_items=dict(node_items), tol=tol, notes=notes,
                    item_border={i: dict(b) for i, b in item_border.items()})
    topo._grid, topo._cell = dict(grid), cell
    return topo


def _hatch(dr: Drawing, regions: list[Region]) -> None:
    """A region whose interior point lies inside a hatch's boundary is filled by it (the material)."""
    for it in dr.items:
        if it.dxftype != "HATCH":
            continue
        rings = [[it.pts[k] for k in ring] for ring in it.extra.get("rings", []) if len(ring) >= 3]
        if not rings:
            continue
        xs = [p[0] for r in rings for p in r]
        ys = [p[1] for r in rings for p in r]
        hb = (min(xs), min(ys), max(xs), max(ys))
        for r in regions:
            x, y = r.inside
            if not (hb[0] <= x <= hb[2] and hb[1] <= y <= hb[3]):
                continue
            if sum(point_in_ring(r.inside, ring) for ring in rings) % 2 == 1:
                r.hatches.append(it.index)
                r.pattern = r.pattern or (it.extra.get("pattern") or "SOLID")


def of(an: Analysis) -> Topology:
    """The topology of an analysed drawing, computed once."""
    topo = an.cache.get("topology")
    if topo is None:
        topo = build_topology(an.drawing)
        an.cache["topology"] = topo
    return topo


# ── datums of a point set ────────────────────────────────────────────────────────


class DatumIndex:
    """Find the set-out line a coordinate lies on."""

    def __init__(self, an: Analysis):
        self.tol = an.drawing.tol
        self.axis: dict[str, tuple[list[float], list[str]]] = {}
        for ax in ("x", "y"):
            ds = sorted((d.value, d.id) for d in an.datums.values() if d.axis == ax and not d.virtual)
            self.axis[ax] = ([v for v, _ in ds], [i for _, i in ds])

    def at(self, axis: str, v: float) -> str | None:
        vals, ids = self.axis[axis]
        k = bisect.bisect_left(vals, v)
        best, bd = None, self.tol
        for j in (k - 1, k):
            if 0 <= j < len(vals) and abs(vals[j] - v) <= bd:
                best, bd = ids[j], abs(vals[j] - v)
        return best

    def of_ring(self, ring: list[Point]) -> tuple[list[str], list[str]]:
        xs = Counter(d for p in ring if (d := self.at("x", p[0])))
        ys = Counter(d for p in ring if (d := self.at("y", p[1])))
        return sorted(xs), sorted(ys)
