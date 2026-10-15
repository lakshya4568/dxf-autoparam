"""Entities drawn twice — never merged, always reported with what differs.

    find_duplicates(dr, items=None)

  exact       the same type and geometry (within the drawing's tolerance) and the same layer, colour and linetype
  restyled    the same geometry in another style — layer, colour or linetype differ (an existing outline under a
              proposed one, a revision drawn over the original): the difference is kept, it may be the meaning
  near        the same type, every defining point within a small distance (a line redrawn slightly off)
  overlap     straight lines on one line whose extents overlap without being the same (a shared boundary drawn by two
              parts, a face drawn in pieces)

A duplicate can carry meaning (existing / proposed, a revision): nothing here deletes or merges anything.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .ir import Drawing, Item

GEOMETRIC = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "TEXT", "MTEXT", "HATCH", "DIMENSION", "SOLID", "POINT"}


def _q(v: float, q: float) -> int:
    return round(v / q)


def _key(it: Item, q: float) -> tuple | None:
    t = it.dxftype
    P = [(_q(x, q), _q(y, q)) for x, y in it.pts]
    if t == "LINE":
        return (t, tuple(sorted(P)))
    if t in ("LWPOLYLINE", "POLYLINE"):
        b = tuple(sorted(round(abs(v), 4) for v in it.bulges)) if it.bulges else ()
        if it.closed and P:
            n = len(P)
            starts = [k for k in range(n) if P[k] == min(P)]
            cands = []
            for k in starts:
                fw = tuple(P[(k + j) % n] for j in range(n))
                bw = tuple(P[(k - j) % n] for j in range(n))
                cands += [fw, bw]
            return ("PL", min(cands), True, b)
        return ("PL", min(tuple(P), tuple(reversed(P))), False, b)
    if t == "ARC":
        sa, ea = (round(float(it.extra.get("start_angle", 0)) % 360, 2), round(float(it.extra.get("end_angle", 0)) % 360, 2))
        return (t, P[0], _q(it.radius or 0.0, q), sa, ea)
    if t == "CIRCLE":
        return (t, P[0], _q(it.radius or 0.0, q))
    if t in ("TEXT", "MTEXT"):
        return ("TEXT", P[0], " ".join((it.text or "").split()))
    if t in ("ELLIPSE", "SPLINE"):
        disp = it.display[0] if it.display else []
        samp = [disp[0], disp[len(disp) // 2], disp[-1]] if disp else []
        return (t, P[0], tuple((_q(x, q), _q(y, q)) for x, y in samp))
    if t == "HATCH":
        return (t, tuple(sorted(P)), it.extra.get("pattern", ""))
    if t == "DIMENSION":
        return (t, tuple(sorted(P[1:3])), round((it.extra.get("measurement") or 0.0) / q))
    if t in ("SOLID", "POINT"):
        return (t, tuple(sorted(P)))
    return None


def _style(it: Item) -> tuple[str, str, str]:
    st = it.extra.get("style") or {}
    colour = "ACI 7" if st.get("fg") else st.get("color", "?")
    return (it.layer, colour, st.get("lt", "?"))


def _member(it: Item, group_of: dict[int, str] | None, u: float) -> dict:
    from .cadjson import entity_id

    layer, colour, lt = _style(it)
    m = {"index": it.index, "id": entity_id(it), "type": it.dxftype, "layer": layer, "colour": colour, "linetype": lt,
         "handle": (it.extra.get("source") or {}).get("handle", it.handle)}
    if group_of:
        m["view"] = group_of.get(it.index, "")
    if it.dxftype == "LINE":
        m["length_mm"] = round(math.dist(*it.pts[:2]) * u, 1)
    return m


def find_duplicates(dr: Drawing, items: list[int] | None = None, group_of: dict[int, str] | None = None, limit: int = 200) -> dict:
    tol = max(dr.tol, 1e-9)
    u = dr.units_mm
    pool = [dr.items[i] for i in (items if items is not None else range(len(dr.items)))]
    pool = [it for it in pool if it.dxftype in GEOMETRIC and it.pts and it.anchor is None]
    groups: list[dict] = []
    seen_pair: set[frozenset] = set()

    # exact / restyled: same canonical key at the drawing's tolerance
    by_key: dict[tuple, list[Item]] = defaultdict(list)
    for it in pool:
        k = _key(it, tol * 2)
        if k is not None:
            by_key[k].append(it)
    for members in by_key.values():
        if len(members) < 2:
            continue
        styles = {_style(it) for it in members}
        differs = [name for name, idx in (("layer", 0), ("colour", 1), ("linetype", 2)) if len({s[idx] for s in styles}) > 1]
        groups.append({"relation": "restyled" if differs else "exact", "members": [_member(it, group_of, u) for it in members],
                       "differs": differs, "deviation_mm": 0.0})
        for a in members:
            for b in members:
                if a.index < b.index:
                    seen_pair.add(frozenset((a.index, b.index)))

    # near duplicates: lines whose two ends are each close to the other's (a grid on end points)
    lines = [it for it in pool if it.dxftype == "LINE" and math.dist(*it.pts[:2]) > tol]
    span = max(dr.extent[2] - dr.extent[0], dr.extent[3] - dr.extent[1], 1.0)
    cell = max(span / 512, 20 * tol)
    grid: dict[tuple[int, int], list[Item]] = defaultdict(list)
    for it in lines:
        for x, y in it.pts[:2]:
            grid[(int(x // cell), int(y // cell))].append(it)

    def direction(it):
        (x1, y1), (x2, y2) = it.pts[:2]
        L = math.hypot(x2 - x1, y2 - y1)
        d = ((x2 - x1) / L, (y2 - y1) / L)
        return d if (d[0] > 1e-12 or (abs(d[0]) <= 1e-12 and d[1] > 0)) else (-d[0], -d[1])

    def differs_of(a, b) -> list[str]:
        styles = {_style(a), _style(b)}
        return [name for name, idx in (("layer", 0), ("colour", 1), ("linetype", 2)) if len({s_[idx] for s_ in styles}) > 1]

    for a in lines:
        x, y = a.pts[0]
        La = math.dist(*a.pts[:2])
        near_tol = max(5 * tol, 0.01 * La)
        r = int(near_tol // cell) + 1
        cx, cy = int(x // cell), int(y // cell)
        cand = {b.index: b for gx in range(cx - r, cx + r + 1) for gy in range(cy - r, cy + r + 1) for b in grid.get((gx, gy), ())}
        for b in cand.values():
            if b.index <= a.index or frozenset((a.index, b.index)) in seen_pair:
                continue
            ends = min(math.dist(a.pts[0], b.pts[0]) + math.dist(a.pts[1], b.pts[1]), math.dist(a.pts[0], b.pts[1]) + math.dist(a.pts[1], b.pts[0])) / 2
            if ends <= near_tol:
                groups.append({"relation": "near", "members": [_member(a, group_of, u), _member(b, group_of, u)], "differs": differs_of(a, b),
                               "deviation_mm": round(ends * u, 2)})
                seen_pair.add(frozenset((a.index, b.index)))

    # overlaps: lines on one infinite line (direction and offset alike) whose extents overlap without being the same
    by_line: dict[tuple[int, int], list[tuple[float, float, Item]]] = defaultdict(list)
    for it in lines:
        d = direction(it)
        (ax, ay) = it.pts[0]
        off = ax * d[1] - ay * d[0]  # signed distance of the infinite line from the origin
        key = (round(math.degrees(math.atan2(d[1], d[0])) * 100), round(off / (2 * tol)))
        t = sorted((p[0] * d[0] + p[1] * d[1]) for p in it.pts[:2])
        by_line[key].append((t[0], t[1], it))
    for rows in by_line.values():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: (r[0], r[1]))
        for k, (lo, hi, a) in enumerate(rows):
            for lo2, hi2, b in rows[k + 1:]:
                if lo2 >= hi - tol:
                    break
                if frozenset((a.index, b.index)) in seen_pair:
                    continue
                ov = min(hi, hi2) - lo2
                if ov > tol:
                    groups.append({"relation": "overlap", "members": [_member(a, group_of, u), _member(b, group_of, u)], "differs": differs_of(a, b),
                                   "overlap_mm": round(ov * u, 1)})
                    seen_pair.add(frozenset((a.index, b.index)))
    summary: dict[str, int] = defaultdict(int)
    pairs: dict[str, int] = defaultdict(int)
    for g in groups:
        summary[g["relation"]] += 1
        if g["differs"]:
            styles = sorted({f"{m['layer']}/{m['colour']}/{m['linetype']}" for m in g["members"]})
            pairs[" ↔ ".join(styles[:2])] += 1
    order = {"restyled": 0, "exact": 1, "near": 2, "overlap": 3}
    groups.sort(key=lambda g: (order[g["relation"]], -len(g["members"])))
    return {"summary": dict(summary), "style_pairs": dict(sorted(pairs.items(), key=lambda kv: -kv[1])[:12]), "groups": groups[:limit],
            "truncated": max(0, len(groups) - limit)}
