"""Annotations as engineering statements: what each dimension, note, label and leader SAYS, what it refers to (ranked
targets, each with its evidence), how it must behave when the geometry changes — and what stays unresolved.

    model = associate(dr, slot_datum, datums, stated)   # one drawing (a unit's): classified, paired, targeted
    bind(dr, slot_datum, datums, model)                  # the behaviours written into the point bindings the program uses

A note and the leader that points from it are ONE annotation. A text is never a driving value because it holds a
number: "150 THK PCC" states a thickness, but which part it describes is decided by what its leader touches, and whether
it drives anything by a person or the agent — never here.

KINDS
  dimension_driving    a native dimension measuring two set-out lines of the structure
  dimension_reference  in parentheses / REF / VARIES, or measuring nothing structural: it reports, never drives
  dimension_derived    an overall dimension equal to the chain of dimensions it spans (worked out from them)
  level                states a level (a number with 2–3 decimals, in metres) — on the line it states
  component_label      names a part, maybe with its size ("TOP SLAB", "HAUNCH 300 x 300")
  material             a material with a thickness or grade ("150mm THK. PCC BASE COURSE")
  construction_note    an instruction ("TO BE PROVIDED AS PER SITE REQUIREMENTS")
  slope                states a slope ("SLOPE 2(H):1(V)", "1:20")
  status               says existing / proposed / to be dismantled
  section_label        a cut or detail marker ("SECTION B-B", "A")
  view_title           a view's title (found by the sheet's segmentation)
  general_note         sheet notes / title block (furniture)
  tolerance, revision  kept apart

ATTACHMENT (behaviour when the geometry changes)
  geometry   the point it touches follows that geometry; the rest of it rides rigidly (a leader keeps its shape and its
             note; a dimension's feet stay on what they measure)
  component  follows the part it names or sits on (the nearest edge it belongs to: across it exactly, along it with the
             nearer corner)
  datum      follows the level line it states (its height), keeps its column on the sheet
  view       stays where it is in its view (a title, a cut label)
  sheet      stays where it is on the sheet (notes, title block)
  fixed      nothing clear tells what it belongs to: it stays where it was written — never dragged by whichever line
             happens to be nearest
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .ir import Drawing, Item, Role

WORDS = json.loads((Path(__file__).parent / "knowledge" / "drafting.json").read_text())["annotation_words"]
TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB"}
LEVEL_RE = re.compile(r"(?<![\d.])([+-]?\d{1,4}\.\d{2,3})(?![\d.])")
NUM_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])")
SLOPE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\(?\s*([VH])\s*\)?\s*[:/]\s*(\d+(?:\.\d+)?)\s*\(?\s*([VH])", re.IGNORECASE)
RATIO_RE = re.compile(r"\b(?:SLOPE|GRADIENT|BATTER|FALL)\b[^0-9]{0,6}(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)|(?<![\d.])1\s*:\s*(\d+(?:\.\d+)?)(?![\d.])", re.IGNORECASE)
GRADE_RE = re.compile(r"\bM\s?-?\s?(\d{2})\b")
THK_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(MM|M)?\s*(?:THK\.?|THICK(?:NESS)?)\b", re.IGNORECASE)
SECTION_RE = re.compile(WORDS["section_label_pattern"], re.IGNORECASE)


def _has(text: str, words: list[str]) -> list[str]:
    up = f" {text.upper()} "
    return [w for w in words if re.search(rf"(?<![A-Z]){re.escape(w.upper())}(?![A-Z])", up)]


def text_states(text: str) -> dict:
    """What a note states, without deciding what it means."""
    s = " ".join((text or "").split())
    out: dict = {}
    m = LEVEL_RE.findall(s)
    if m:
        out["level_m"] = float(m[0])
    nums = [float(x) for x in NUM_RE.findall(s)]
    if nums:
        out["numbers"] = nums[:6]
    m2 = SLOPE_RE.search(s)
    if m2 and {m2.group(2).upper(), m2.group(4).upper()} == {"V", "H"}:
        v, h = (float(m2.group(1)), float(m2.group(3))) if m2.group(2).upper() == "V" else (float(m2.group(3)), float(m2.group(1)))
        out["slope_h_per_v"] = round(h / v, 4) if v else None
    else:
        m3 = RATIO_RE.search(s)
        if m3:
            if m3.group(3):
                out["slope_ratio"] = f"1:{m3.group(3)}"
            elif m3.group(1):
                out["slope_ratio"] = f"{m3.group(1)}:{m3.group(2)}"
    t = THK_RE.search(s)
    if t:
        v = float(t.group(1)) * (1000.0 if (t.group(2) or "").upper() == "M" else 1.0)
        out["thickness_mm"] = v
    g = GRADE_RE.search(s.upper())
    if g:
        out["grade"] = f"M{g.group(1)}"
    mats = _has(s, WORDS["material"])
    if mats:
        out["materials"] = mats[:4]
    for status, key in (("existing", "status_existing"), ("proposed", "status_proposed"), ("removed", "status_removed"),
                        ("construction", "status_construction"), ("alternative", "status_alternative")):
        if _has(s, WORDS[key]):
            out["status"] = status
            break
    return out


def classify_text(text: str, group_kind: str = "", is_title: bool = False) -> tuple[str, list[str]]:
    """(kind, evidence) for a note, from its words and where it sits on the sheet."""
    s = " ".join((text or "").split())
    up = s.upper()
    st = text_states(s)
    if group_kind in ("title_block", "table"):
        return ("revision", ["in the title block, revision words"]) if _has(s, WORDS["revision"]) else ("general_note", [f"in the {group_kind.replace('_', ' ')}"])
    if is_title:
        return "view_title", ["the sheet's segmentation found it as this view's title"]
    if group_kind == "notes":
        return "general_note", ["in a panel of notes"]
    if SECTION_RE.match(up.strip()):
        return "section_label", [f"a cut / detail marker ({s!r})"]
    if _has(s, WORDS["tolerance"]):
        return "tolerance", ["tolerance words"]
    if "level_m" in st and not st.get("thickness_mm"):
        return "level", [f"states a level of {st['level_m']:.3f} m"]
    if "slope_h_per_v" in st or "slope_ratio" in st:
        return "slope", [f"states a slope ({st.get('slope_ratio') or str(st['slope_h_per_v']) + ' H per V'})"]
    instr = _has(s, WORDS["instruction"])
    if st.get("materials") and (st.get("thickness_mm") or st.get("grade") or _has(s, WORDS["thickness"])):
        return "material", [f"a material ({', '.join(st['materials'])}) with a thickness / grade"]
    if instr and len(s.split()) >= 3:
        return "construction_note", [f"instruction words ({', '.join(instr[:3])})"]
    if st.get("status") and len(s.split()) <= 6:
        return "status", [f"says {st['status']}"]
    if st.get("materials"):
        return "material", [f"material words ({', '.join(st['materials'])})"]
    if len(s.split()) <= 6 and re.search(r"[A-Za-z]{3,}", s):
        return "component_label", ["a short name" + (" with its size" if st.get("numbers") else "")]
    if not re.search(r"[A-Za-z]", s):
        return "general_note", ["a number with no words"]
    return "general_note", ["a longer note"]


# ── geometry helpers ─────────────────────────────────────────────────────────────


def _seg_dist(p, a, b) -> tuple[float, float]:
    """(distance from p to segment ab, parameter t of the foot along ab)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy)), t


def text_box(it: Item) -> list[tuple[float, float]]:
    from .sheet import text_outline

    try:
        return text_outline(it)
    except (IndexError, ValueError, ZeroDivisionError):
        return [it.pts[0]] * 4


def _box_dist(p, box) -> float:
    from .analyse import point_in_poly

    if len(box) >= 3 and point_in_poly(p, box):
        return 0.0
    return min(_seg_dist(p, box[k], box[(k + 1) % len(box)])[0] for k in range(len(box)))


def _centre(box) -> tuple[float, float]:
    return (sum(p[0] for p in box) / len(box), sum(p[1] for p in box) / len(box))


class _Edges:
    """Straight segments of the structure (and reference lines) on a grid, for nearest-edge queries."""

    def __init__(self, dr: Drawing, roles=(Role.STRUCTURAL, Role.REFERENCE)):
        self.segs: list[tuple[tuple[float, float], tuple[float, float], int, int, int]] = []  # a, b, item, pt a, pt b
        for it in dr.items:
            if it.role not in roles or it.anchor is not None:
                continue
            if it.dxftype in ("LINE", "LWPOLYLINE", "POLYLINE"):
                n = len(it.pts)
                pairs = list(it.segments) or [(k, k + 1) for k in range(n - 1)]
                if it.closed and n > 2 and not it.segments:
                    pairs.append((n - 1, 0))
                for i, j in pairs:
                    if i < n and j < n:
                        self.segs.append((it.pts[i], it.pts[j], it.index, i, j))
        x0, y0, x1, y1 = dr.extent if dr.extent[2] > dr.extent[0] else (0.0, 0.0, 1.0, 1.0)
        self.cell = max(x1 - x0, y1 - y0, 1e-9) / 128
        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for s, (a, b, *_rest) in enumerate(self.segs):
            n = max(1, int(math.dist(a, b) / self.cell) + 1)
            seen = set()
            for k in range(n + 1):
                x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
                key = (int(x // self.cell), int(y // self.cell))
                if key not in seen:
                    seen.add(key)
                    self.grid[key].append(s)

    def near(self, p, reach: float) -> list[tuple[float, int, float]]:
        """(distance, segment index, foot parameter) of every segment within `reach` of p, nearest first."""
        r = int(reach // self.cell) + 1
        cx, cy = int(p[0] // self.cell), int(p[1] // self.cell)
        cand: set[int] = set()
        for gx in range(cx - r, cx + r + 1):
            for gy in range(cy - r, cy + r + 1):
                cand.update(self.grid.get((gx, gy), ()))
        out = []
        for s in cand:
            a, b = self.segs[s][0], self.segs[s][1]
            d, t = _seg_dist(p, a, b)
            if d <= reach:
                out.append((d, s, t))
        out.sort()
        return out


# ── the model ────────────────────────────────────────────────────────────────────


@dataclass
class Target:
    kind: str  # entity | line | region | view | sheet
    ref: str
    index: int | None = None
    score: float = 0.0
    evidence: list[str] = field(default_factory=list)
    seg: int | None = None  # the structural segment touched (internal)
    foot: float = 0.0
    pt: tuple[int, int] | None = None  # or: the (entity, point) whose set-out lines it follows (a hatch's boundary corner)

    def to_dict(self) -> dict:
        d = {"kind": self.kind, "ref": self.ref, "score": round(self.score, 3), "evidence": self.evidence}
        if self.index is not None:
            d["index"] = self.index
        return d


@dataclass
class Annotation:
    id: str
    items: list[int]
    kind: str
    text: str
    attachment: str
    status: str  # resolved | ambiguous | unassociated
    targets: list[Target] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    states: dict = field(default_factory=dict)
    anchor: tuple[float, float] | None = None
    quantity: dict | None = None

    def to_dict(self, back: list[int] | None = None) -> dict:
        def sheet(i):
            return back[i] if back is not None and i is not None and 0 <= i < len(back) else i

        d = {"id": self.id, "kind": self.kind, "text": self.text[:160], "attachment": self.attachment, "status": self.status,
             "items": [sheet(i) for i in self.items], "evidence": self.evidence}
        if self.states:
            d["states"] = self.states
        if self.targets:
            d["targets"] = [{**t.to_dict(), **({"index": sheet(t.index)} if t.index is not None else {})} for t in self.targets[:4]]
        if self.quantity:
            d["quantity"] = self.quantity
        if self.anchor is not None:
            d["anchor"] = [round(self.anchor[0], 3), round(self.anchor[1], 3)]
        return d


@dataclass
class AnnotationModel:
    annotations: list[Annotation]
    of_item: dict[int, str]  # item index → annotation id
    notes: list[str] = field(default_factory=list)

    def by_id(self) -> dict[str, Annotation]:
        return {a.id: a for a in self.annotations}

    def summary(self) -> dict:
        kinds: dict[str, int] = defaultdict(int)
        att: dict[str, int] = defaultdict(int)
        st: dict[str, int] = defaultdict(int)
        for a in self.annotations:
            kinds[a.kind] += 1
            att[a.attachment] += 1
            st[a.status] += 1
        return {"annotations": len(self.annotations), "kinds": dict(kinds), "attachment": dict(att), "status": dict(st)}


def _eid(it: Item) -> str:
    from .cadjson import entity_id

    return entity_id(it)


def _text_groups(texts: list[Item], boxes: dict[int, list], pointed: set[int] | None = None) -> list[list[int]]:
    """Single-line texts (TEXT, or MTEXT holding one line) stacked into one note (same rotation and height, aligned, a line
    apart) — read as one annotation, top line first. A multi-line MTEXT is already one note."""
    pointed = pointed or set()
    singles = [t for t in texts if "\n" not in (t.text or "")]

    def one_statement(t: Item) -> bool:  # a level is written on one line: two level lines are two notes
        return bool(LEVEL_RE.search(t.text or ""))
    parent = {t.index: t.index for t in texts}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_rot: dict[int, list[Item]] = defaultdict(list)
    for t in singles:
        by_rot[round(float(t.extra.get("rotation", 0.0)) % 360)].append(t)
    for group in by_rot.values():
        for a in group:
            ha = a.text_height or 1.0
            ang = math.radians(float(a.extra.get("rotation", 0.0)))
            ux, uy = math.cos(ang), math.sin(ang)
            ca = _centre(boxes[a.index])
            for b in group:
                if b.index <= a.index:
                    continue
                hb = b.text_height or 1.0
                if abs(ha - hb) > 0.1 * max(ha, hb) or a.layer != b.layer:
                    continue
                if one_statement(a) or one_statement(b) or (a.index in pointed and b.index in pointed):
                    continue  # each states its own level, or each has its own leader: two notes
                cb = _centre(boxes[b.index])
                dx, dy = cb[0] - ca[0], cb[1] - ca[1]
                along, across = dx * ux + dy * uy, -dx * uy + dy * ux
                # stacked: about one line apart across the reading direction, starting (or centred) together along it
                la, lb = a.pts[0], b.pts[0]
                start_gap = abs((lb[0] - la[0]) * ux + (lb[1] - la[1]) * uy)
                if 0.6 * ha <= abs(across) <= 2.0 * ha and (start_gap <= 0.8 * ha or abs(along) <= 0.8 * ha):
                    parent[find(b.index)] = find(a.index)
    out: dict[int, list[int]] = defaultdict(list)
    for t in texts:
        out[find(t.index)].append(t.index)
    groups = []
    for members in out.values():
        if len(members) > 1:
            t0 = next(t for t in texts if t.index == members[0])
            ang = math.radians(float(t0.extra.get("rotation", 0.0)))
            nx, ny = -math.sin(ang), math.cos(ang)
            members.sort(key=lambda i: -(_centre(boxes[i])[0] * nx + _centre(boxes[i])[1] * ny))
        groups.append(members)
    return groups


def _box_seg(box, a, b) -> tuple[float, float]:
    """(distance between a text's box and segment ab, foot parameter of the box centre on ab)."""
    from .analyse import point_in_poly

    c = _centre(box)
    t = _seg_dist(c, a, b)[1]
    if point_in_poly(a, box) or point_in_poly(b, box):
        return 0.0, t
    for k in range(len(box)):
        p, q = box[k], box[(k + 1) % len(box)]
        if _crosses(p, q, a, b):
            return 0.0, t
    d = min(min(_seg_dist(v, a, b)[0] for v in box), _box_dist(a, box), _box_dist(b, box))
    return d, t


def _crosses(p1, p2, p3, p4) -> bool:
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2, d3, d4 = orient(p3, p4, p1), orient(p3, p4, p2), orient(p1, p2, p3), orient(p1, p2, p4)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def associate(dr: Drawing, slot_datum: dict | None = None, datums: dict | None = None, stated: list | None = None,
              titles: set[int] | None = None, group_kind: dict[int, str] | None = None) -> AnnotationModel:
    """Every annotation of `dr` classified, paired (note ↔ leader, stacked lines ↔ one note), targeted with ranked
    evidence, and given a behaviour. `slot_datum` / `datums` / `stated` (an analysis' bindings, set-out lines and stated
    levels) tie dimensions and levels to set-out lines; `titles` / `group_kind` (the sheet's segmentation) tell titles
    and notes panels apart."""
    titles = titles or set()
    group_kind = group_kind or {}
    items = dr.items
    edges = _Edges(dr)
    tol = max(dr.tol, 1e-9)
    texts = [it for it in items if it.dxftype in TEXT_TYPES and (it.text or "").strip() and it.role != Role.FIXED]
    boxes = {it.index: text_box(it) for it in texts}
    level_of = {ti: (d, v, w) for d, ti, w, v in (stated or [])}
    hatches = [it for it in items if it.dxftype == "HATCH" and it.extra.get("polys")]
    anns: list[Annotation] = []
    of_item: dict[int, str] = {}

    # ── leaders and the note each points from ─────────────────────────────────────
    # A note sits on (above / beside) the leader's last segment — its shoulder — which may run past the note's end; a level
    # note under the shoulder belongs to its own line, so a note that states no level is preferred when both are as near.
    leader_text: dict[int, int] = {}
    for ld in (it for it in items if it.dxftype == "LEADER" and len(it.pts) >= 2):
        a_pt, b_pt = ld.pts[-2], ld.pts[-1]
        horizontal = abs(a_pt[1] - b_pt[1]) <= 1e-6 * max(1.0, abs(a_pt[0] - b_pt[0]))
        best = None
        for t in texts:
            h = t.text_height or 1.0
            d = _box_seg(boxes[t.index], a_pt, b_pt)[0]
            if d > 1.6 * h + 2 * tol:
                continue
            score = d
            if LEVEL_RE.search(t.text or ""):
                score += h  # a level note is its line's, not the leader's, unless nothing else is there
            if horizontal and _centre(boxes[t.index])[1] > b_pt[1]:
                score -= 0.3 * h  # written on the shoulder (above it): the drafting convention
            if best is None or score < best[0]:
                best = (score, t.index)
        if best is not None:
            leader_text[ld.index] = best[1]
    leaders_of_text: dict[int, list[int]] = defaultdict(list)
    for li, ti in leader_text.items():
        leaders_of_text[ti].append(li)

    def band(c1: Target, c2: Target, p) -> bool:
        """The point lies between two parallel faces (both horizontal, or both vertical): it names the band they bound."""
        if c1.seg is None or c2.seg is None:
            return False
        (a1, b1), (a2, b2) = edges.segs[c1.seg][:2], edges.segs[c2.seg][:2]
        if abs(a1[1] - b1[1]) <= tol and abs(a2[1] - b2[1]) <= tol:
            return min(a1[1], a2[1]) - tol <= p[1] <= max(a1[1], a2[1]) + tol
        if abs(a1[0] - b1[0]) <= tol and abs(a2[0] - b2[0]) <= tol:
            return min(a1[0], a2[0]) - tol <= p[0] <= max(a1[0], a2[0]) + tol
        return False

    def foot(c: Target):
        if c.seg is None:
            return None
        a_, b_ = edges.segs[c.seg][0], edges.segs[c.seg][1]
        return (a_[0] + (b_[0] - a_[0]) * c.foot, a_[1] + (b_[1] - a_[1]) * c.foot)

    def decide(cands: list[Target], p, what: str) -> tuple[list[Target], str, list[str]]:
        if not cands:
            return [], "unassociated", []
        cands.sort(key=lambda t: -t.score)
        if len(cands) == 1 or cands[1].score <= 0.8 * cands[0].score or _same_line(cands[0], cands[1], edges, tol):
            return cands, "resolved", []
        if band(cands[0], cands[1], p):
            return cands, "resolved", [f"{what} lies between the parallel faces {cands[0].ref} and {cands[1].ref}: it names the band they bound"]
        f1, f2 = foot(cands[0]), foot(cands[1])
        if f1 is not None and f2 is not None and math.dist(f1, f2) <= 3 * tol:
            return cands, "resolved", [f"{what} is at the corner where {cands[0].ref} and {cands[1].ref} meet"]
        return cands, "ambiguous", [f"{what} is as near to {cands[0].ref} as to {cands[1].ref}: which part is meant is not clear"]

    def in_hatch(p) -> Target | None:
        from .analyse import point_in_poly

        for h in hatches:
            for poly in h.extra["polys"]:
                if len(poly) >= 3 and point_in_poly(p, poly):
                    k = min(range(len(h.pts)), key=lambda j: math.dist(h.pts[j], p))
                    return Target("entity", _eid(h), h.index, 0.6, [f"points into hatch {_eid(h)} ({h.extra.get('pattern') or 'fill'})"], pt=(h.index, k))
        return None

    def tip_target(tip, h) -> tuple[list[Target], str, list[str]]:
        cands: list[Target] = []
        seen_items: set[int] = set()
        reach = max(1.5 * h, 25 * tol)
        for d, sgi, t in edges.near(tip, reach)[:8]:
            item = edges.segs[sgi][2]
            if item in seen_items:
                continue
            seen_items.add(item)
            cands.append(Target("entity", _eid(items[item]), item, 1.0 / (1.0 + d / max(reach * 0.15, tol)),
                                [f"the arrow tip is {d * dr.units_mm:.1f} mm from {_eid(items[item])}"], sgi, t))
        if cands:
            return decide(cands, tip, "the arrow tip")
        hit = in_hatch(tip)
        if hit is not None:
            return [hit], "resolved", []
        return [], "unassociated", ["the leader's tip touches nothing of the structure"]

    # ── notes (stacked lines are one note; with their leaders) ───────────────────
    for grp in _text_groups(texts, boxes, set(leaders_of_text)):
        main = items[grp[0]]
        text = " ".join(" ".join((items[i].text or "").split()) for i in grp)
        kind, why = classify_text(text, group_kind.get(main.index, ""), any(i in titles for i in grp))
        h = main.text_height or 1.0
        lds = [li for i in grp for li in leaders_of_text.get(i, [])]
        ann = Annotation(id=_eid(main), items=[*grp, *lds], kind=kind, text=text, attachment="fixed", status="unassociated",
                         evidence=list(why) + ([f"{len(grp)} stacked text lines read as one note"] if len(grp) > 1 else []), states=text_states(text))
        gboxes = [boxes[i] for i in grp]
        if kind in ("view_title", "section_label"):
            ann.attachment, ann.status = "view", "resolved"
            ann.targets = [Target("view", "", None, 1.0, ["a title / marker stays with its view"])]
        elif kind in ("general_note", "revision") and not lds:
            ann.attachment, ann.status = "sheet", "resolved"
            ann.targets = [Target("sheet", "", None, 1.0, ["sheet furniture"])]
        elif lds:  # pointed: the arrow tip says what it describes
            ld = items[lds[0]]
            ann.anchor = ld.pts[0]
            ann.targets, ann.status, more = tip_target(ld.pts[0], h)
            ann.evidence.append(f"its leader {_eid(ld)} points at it" + (f" (+{len(lds) - 1} more leader(s))" if len(lds) > 1 else ""))
            ann.evidence += more
            ann.attachment = "geometry" if ann.status == "resolved" else "fixed"
        elif kind == "level" and any(i in level_of for i in grp):
            d, v, _w = level_of[next(i for i in grp if i in level_of)]
            ann.anchor = main.pts[0]
            ann.targets = [Target("line", d, None, 1.0, [f"states {v:.3f} m; set-out line {d} is at that level (the view's level datum)"])]
            ann.attachment, ann.status = "datum", "resolved"
        else:  # beside or on a part: the edge it is written on, when one is clearly nearest (measured from its box)
            c = _centre([v for b in gboxes for v in b])
            ann.anchor = c
            reach = 3.0 * h
            half = max(math.dist(c, v) for b in gboxes for v in b)
            cands: list[Target] = []
            seen: set[int] = set()
            for _d, sgi, _t in edges.near(c, half + reach)[:24]:
                item = edges.segs[sgi][2]
                if item in seen:
                    continue
                a_pt, b_pt = edges.segs[sgi][0], edges.segs[sgi][1]
                d, t = min(_box_seg(b, a_pt, b_pt) for b in gboxes)
                if d > reach:
                    continue
                seen.add(item)
                cands.append(Target("entity", _eid(items[item]), item, 1.0 / (1.0 + d / max(h, tol)),
                                    [f"written {d * dr.units_mm:.0f} mm from {_eid(items[item])} (text height {h * dr.units_mm:.0f} mm)"], sgi, t))
            ann.targets, ann.status, more = decide(cands, c, "the note")
            ann.evidence += more
            if ann.status == "unassociated":
                hit = in_hatch(c)
                if hit is not None:
                    ann.targets, ann.status = [hit], "resolved"
                    ann.evidence.append("written inside a hatched area")
            if ann.status == "resolved":
                ann.attachment = "component"
            elif ann.status == "ambiguous":
                ann.attachment = "fixed"
                ann.evidence.append("it stays where it was written until a person (or the agent, with evidence) says what it names")
            else:
                ann.attachment = "view" if kind in ("construction_note", "general_note", "material", "level") else "fixed"
                ann.evidence.append(f"no structure within {reach * dr.units_mm:.0f} mm (3 text heights): stays where it was written")
        anns.append(ann)
        for i in ann.items:
            of_item[i] = ann.id

    # leaders with no note (an arrow to a symbol): geometry at the tip
    for ld in (it for it in items if it.dxftype == "LEADER" and it.index not in leader_text and len(it.pts) >= 2):
        tg, status, more = tip_target(ld.pts[0], 25 * tol)
        a = Annotation(id=_eid(ld), items=[ld.index], kind="leader", text="", attachment="geometry" if status == "resolved" else "fixed",
                       status=status, targets=tg, evidence=["a leader with no note at its end", *more], anchor=ld.pts[0])
        anns.append(a)
        of_item[ld.index] = a.id

    # multileaders: their own content and tip(s)
    for ml in (it for it in items if it.dxftype in ("MULTILEADER", "MLEADER") and it.pts):
        content = " ".join(q.get("text", "") for q in it_parts(ml) if q["k"] == "t")
        kind, why = classify_text(content)
        h = next((q.get("h", 1.0) for q in it_parts(ml) if q["k"] == "t"), 1.0)
        tg, status, more = tip_target(ml.pts[0], h)
        a = Annotation(id=_eid(ml), items=[ml.index], kind=kind, text=content, attachment="geometry" if status == "resolved" else "fixed",
                       status=status, targets=tg, evidence=[*why, "a multileader: its arrow tip says what it describes", *more],
                       states=text_states(content), anchor=ml.pts[0])
        anns.append(a)
        of_item[ml.index] = a.id

    # dimensions
    dims = [it for it in items if it.dxftype == "DIMENSION" and len(it.pts) >= 3]
    for it in dims:
        anns.append(_dimension(dr, it, slot_datum, datums, edges, tol))
        of_item[it.index] = anns[-1].id
    _derived(dr, [a for a in anns if a.kind == "dimension_driving"])
    return AnnotationModel(anns, of_item)


def it_parts(it: Item) -> list[dict]:
    return it.extra.get("parts") or []


def _same_line(t1: Target, t2: Target, edges: _Edges, tol: float) -> bool:
    """Two touched segments that lie on one straight set-out line (a wall face drawn as two lines) are one target."""
    if t1.seg is None or t2.seg is None:
        return False
    a1, b1 = edges.segs[t1.seg][0], edges.segs[t1.seg][1]
    a2, b2 = edges.segs[t2.seg][0], edges.segs[t2.seg][1]
    hor = abs(a1[1] - b1[1]) <= tol and abs(a2[1] - b2[1]) <= tol and abs(a1[1] - a2[1]) <= tol
    ver = abs(a1[0] - b1[0]) <= tol and abs(a2[0] - b2[0]) <= tol and abs(a1[0] - a2[0]) <= tol
    return hor or ver


def _dimension(dr: Drawing, it: Item, slot_datum, datums, edges: _Edges, tol: float) -> Annotation:
    u = dr.units_mm
    text = (it.text or "").strip()
    meas = (it.extra.get("measurement") or 0.0) * u
    p1, p2 = it.pts[1], it.pts[2]
    q: dict = {"measured_mm": round(meas, 3), "override": text or "<>"}
    dx, dy = abs(p2[0] - p1[0]), abs(p2[1] - p1[1])
    ang = it.extra.get("angle", 0.0)
    axis = "x" if dy < tol < dx else "y" if dx < tol < dy else ("x" if abs(math.sin(math.radians(ang))) < 0.5 else "y")
    q["axis"] = axis
    lines = []
    if slot_datum is not None:
        for k in (1, 2):
            b = slot_datum.get((it.index, k, axis))
            if b is not None and abs(b[1]) <= tol:
                lines.append(b[0])
    targets: list[Target] = []
    for p in (p1, p2):
        near = edges.near(p, 3 * tol)
        if near:
            s = near[0][1]
            item = edges.segs[s][2]
            targets.append(Target("entity", _eid(dr.items[item]), item, 1.0, [f"a measured point lies on {_eid(dr.items[item])}"], s, near[0][2]))
    for d in lines:
        targets.append(Target("line", d, None, 1.0, [f"a measured point sits on set-out line {d}"]))
    if len(lines) == 2:
        q["between"] = lines
    evidence = []
    if text and "<>" not in text:
        nums = [float(x) for x in NUM_RE.findall(text)]
        q["stated"] = nums[:3]
        if nums and not any(abs(n - meas) <= max(0.5, 1e-3 * meas) or abs(n * 1000 - meas) <= 0.5 for n in nums):
            evidence.append(f"its text {text!r} does not state its measured {meas:.0f} mm")
    reference = bool(re.search(r"^\s*\(.*\)\s*$|\bREF\b|\bVAR(IES|IABLE)?\b|\bTYP\b", text, re.IGNORECASE))
    structural_feet = sum(1 for t in targets if t.kind == "entity")
    if reference:
        kind = "dimension_reference"
        evidence.append("its text marks it as a reference (in brackets / REF / VARIES / TYP)")
    elif structural_feet == 0 and not lines:
        kind = "dimension_reference"
        evidence.append("neither measured point lies on the structure: it reports, it cannot drive")
    else:
        kind = "dimension_driving"
        evidence.append("measures between points of the structure" + (f" (set-out lines {lines[0]} → {lines[1]})" if len(lines) == 2 else ""))
    status = "resolved" if (structural_feet >= 1 or lines) else "unassociated"
    shown = text.replace("<>", f"{meas:.0f}") if text else f"{meas:.0f}"  # what the sheet shows; the raw override stays in quantity
    return Annotation(id=_eid(it), items=[it.index], kind=kind, text=shown, attachment="geometry" if status == "resolved" else "fixed",
                      status=status, targets=targets, evidence=evidence, states={}, anchor=it.pts[0], quantity=q)


def _derived(dr: Drawing, dims: list[Annotation]) -> None:
    """An overall dimension equal to the chain it spans (on the same axis, between its feet) is worked out from that chain."""
    tol = max(dr.tol, 1e-9)
    by_axis: dict[str, list[tuple[float, float, Annotation]]] = defaultdict(list)
    for a in dims:
        it = dr.items[a.items[0]]
        k = 0 if a.quantity["axis"] == "x" else 1
        lo, hi = sorted((it.pts[1][k], it.pts[2][k]))
        by_axis[a.quantity["axis"]].append((lo, hi, a))
    for rows in by_axis.values():
        for lo, hi, a in rows:
            inside = sorted(((l2, h2, b) for l2, h2, b in rows if b is not a and l2 >= lo - tol and h2 <= hi + tol and (h2 - l2) < (hi - lo) - tol),
                            key=lambda r: (r[0], r[1]))
            if len(inside) < 2:
                continue
            # a chain from lo to hi made of consecutive inner dimensions
            pos, used = lo, []
            for l2, h2, b in inside:
                if abs(l2 - pos) <= tol:
                    pos, used = h2, [*used, b]
            if used and abs(pos - hi) <= tol and len(used) >= 2:
                a.kind = "dimension_derived"
                a.evidence.append(f"equals the chain of {len(used)} dimensions it spans ({' + '.join(b.text for b in used)})")
                a.quantity["chain"] = [b.id for b in used]


# ── behaviours → bindings ────────────────────────────────────────────────────────


def bind(dr: Drawing, slot_datum: dict, datums: dict, model: AnnotationModel) -> dict[str, int]:
    """Write each annotation's behaviour into the point bindings the program regenerates from. Returns counts by behaviour.

    geometry   every point of the note and its leader is set out from the touched edge: across the edge by the edge's own
               line, along it by the nearer corner's line — so the tip stays on the edge and the note keeps its shape
    component  the same, from the edge the note is written on
    datum      the height from the stated level line; the column stays where it was written
    view / sheet / fixed   no binding: the note stays exactly where it was written
    Dimensions keep the bindings the analysis gave them (their measured points sit on the lines they measure)."""
    edges = _Edges(dr)
    counts: dict[str, int] = defaultdict(int)
    for a in model.annotations:
        if a.kind.startswith("dimension"):
            counts["dimension"] += 1
            continue
        pts_of = [(i, k) for i in a.items for k in range(len(dr.items[i].pts))]
        if a.attachment in ("view", "sheet", "fixed") or not a.targets:
            for i, k in pts_of:
                slot_datum.pop((i, k, "x"), None)
                slot_datum.pop((i, k, "y"), None)
            counts[a.attachment] += 1
            continue
        if a.attachment == "datum":
            d = a.targets[0].ref
            if d in datums:
                for i, k in pts_of:
                    slot_datum.pop((i, k, "x"), None)
                    slot_datum[(i, k, "y")] = (d, dr.items[i].pts[k][1] - datums[d].value)
                counts["datum"] += 1
            continue
        t = a.targets[0]
        if t.pt is not None:  # follows a corner of what it points into (a hatch's boundary)
            bx, by = slot_datum.get((t.pt[0], t.pt[1], "x")), slot_datum.get((t.pt[0], t.pt[1], "y"))
            if bx is None or by is None:
                continue
            for i, k in pts_of:
                x, y = dr.items[i].pts[k]
                slot_datum[(i, k, "x")] = (bx[0], x - datums[bx[0]].value)
                slot_datum[(i, k, "y")] = (by[0], y - datums[by[0]].value)
            counts[a.attachment] += 1
            continue
        if t.seg is None:
            continue
        seg = edges.segs[t.seg]
        a_pt, b_pt, item, pi, pj = seg
        near_k = pi if t.foot <= 0.5 else pj
        bx = slot_datum.get((item, near_k, "x"))
        by = slot_datum.get((item, near_k, "y"))
        horizontal = abs(a_pt[1] - b_pt[1]) <= dr.tol
        vertical = abs(a_pt[0] - b_pt[0]) <= dr.tol
        # across a horizontal edge: its own y line (both ends share it); across a vertical one: its own x line
        if horizontal:
            by = slot_datum.get((item, pi, "y")) or by
        if vertical:
            bx = slot_datum.get((item, pi, "x")) or bx
        if bx is None or by is None:
            continue
        for i, k in pts_of:
            x, y = dr.items[i].pts[k]
            slot_datum[(i, k, "x")] = (bx[0], x - datums[bx[0]].value)
            slot_datum[(i, k, "y")] = (by[0], y - datums[by[0]].value)
        counts[a.attachment] += 1
    return dict(counts)
