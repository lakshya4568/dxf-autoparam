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
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(items)), key=lambda i: boxes[i][0])
    active: list[int] = []
    for i in order:
        bx = boxes[i]
        active = [j for j in active if boxes[j][2] + margin >= bx[0]]
        for j in active:
            b = boxes[j]
            if b[1] - margin <= bx[3] and bx[1] - margin <= b[3]:
                parent[find(i)] = find(j)
        active.append(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    # Lines of one structure need not touch (cells inside a box drawn as loose lines):
    # clusters whose extents overlap are one view.
    clusters = [
        [(min(boxes[i][0] for i in m), min(boxes[i][1] for i in m), max(boxes[i][2] for i in m), max(boxes[i][3] for i in m)), m]
        for m in groups.values()
    ]
    merged = True
    while merged:
        merged = False
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                A, B = clusters[a][0], clusters[b][0]
                if A[0] - margin <= B[2] and B[0] - margin <= A[2] and A[1] - margin <= B[3] and B[1] - margin <= A[3]:
                    clusters[a] = [(min(A[0], B[0]), min(A[1], B[1]), max(A[2], B[2]), max(A[3], B[3])), clusters[a][1] + clusters[b][1]]
                    del clusters[b]
                    merged = True
                    break
            if merged:
                break
    views = [{"bbox": bb, "entities": len(members)} for bb, members in clusters]
    views.sort(key=lambda v: -v["entities"])
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
