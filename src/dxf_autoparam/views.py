"""Views on a sheet: clusters of structure separated by white space.

A GAD sheet holds several views (section, elevation, plan, details). Analysed as one,
unrelated views share coordinates by accident and a change in one would drag another.
So a sheet is split into views first, and a person picks the one to parametrize (or
the region is given). Entities outside the chosen region are FIXED: written back
untouched.
"""

from __future__ import annotations

from .ir import Drawing, Role


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def detect_views(dr: Drawing, margin_frac: float = 0.01) -> list[dict]:
    items = [it for it in dr.items if it.role in (Role.STRUCTURAL, Role.REFERENCE) and it.pts]
    if not items:
        return []
    x0, y0, x1, y1 = dr.extent
    margin = margin_frac * max(x1 - x0, y1 - y0, 1.0)
    boxes = [_bbox(it.pts) for it in items]

    def touch(A, B) -> bool:
        return A[0] - margin <= B[2] and B[0] - margin <= A[2] and A[1] - margin <= B[3] and B[1] - margin <= A[3]

    # Lines of one structure need not touch (cells inside a box drawn as loose lines): clusters whose extents
    # overlap are one view. Swept left to right against the open CLUSTERS (few), not the open lines (a sheet-wide
    # line kept every line of a 20k-line sheet open); the pass below merges what grew into each other.
    clusters: list[list] = []  # [extent, member count, first entity] — views with as many entities keep drawing order
    active: list[int] = []
    for i in sorted(range(len(items)), key=lambda i: boxes[i][0]):
        bx = boxes[i]
        active = [c for c in active if clusters[c] is not None and clusters[c][0][2] + margin >= bx[0]]
        hit = [c for c in active if touch(clusters[c][0], bx)]
        if not hit:
            clusters.append([bx, 1, i])
            active.append(len(clusters) - 1)
            continue
        keep, ext, n, first = hit[0], bx, 1, i
        for c in hit:
            E = clusters[c][0]
            ext = (min(ext[0], E[0]), min(ext[1], E[1]), max(ext[2], E[2]), max(ext[3], E[3]))
            n += clusters[c][1]
            first = min(first, clusters[c][2])
            if c != keep:
                clusters[c] = None
        clusters[keep] = [ext, n, first]
    clusters = [c for c in clusters if c is not None]
    merged = True
    while merged:
        merged = False
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                A, B = clusters[a][0], clusters[b][0]
                if touch(A, B):
                    clusters[a] = [(min(A[0], B[0]), min(A[1], B[1]), max(A[2], B[2]), max(A[3], B[3])), clusters[a][1] + clusters[b][1],
                                   min(clusters[a][2], clusters[b][2])]
                    del clusters[b]
                    merged = True
                    break
            if merged:
                break
    clusters.sort(key=lambda c: (-c[1], c[2]))
    views = [{"bbox": bb, "entities": n} for bb, n, _first in clusters]
    for n, v in enumerate(views):
        v["id"] = n
    return views


def restrict(dr: Drawing, bbox: tuple[float, float, float, float], pad_frac: float = 0.05) -> None:
    """Keep entities in `bbox` (annotations a little around it); fix everything else."""
    x0, y0, x1, y1 = bbox
    pad = pad_frac * max(x1 - x0, y1 - y0, 1.0)

    def inside(pts, p: float) -> bool:
        bx = _bbox(pts)
        cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
        return x0 - p <= cx <= x1 + p and y0 - p <= cy <= y1 + p

    for it in dr.items:
        if not it.pts:
            continue
        if it.role in (Role.STRUCTURAL, Role.REFERENCE):
            if not inside(it.pts, dr.tol):
                it.role = Role.FIXED
        elif it.role == Role.ANNOTATION and not inside(it.pts, pad):
            it.role = Role.FIXED
    pts = [it.pts[k] for it in dr.items if it.role == Role.STRUCTURAL for k in it.vertex_pts]
    if pts:
        dr.extent = _bbox(pts)
