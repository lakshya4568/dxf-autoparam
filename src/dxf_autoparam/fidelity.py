"""Source fidelity: what every DXF entity LOOKS like and WHERE it came from, kept beside the points the engine moves.

Four things are kept apart and never confused:

  SOURCE        the entity as written — its own handle (inside its block definition when a view is a block), the INSERT
                chain that places it, its raw properties (ACI 0/256 = BYBLOCK/BYLAYER, true colour, linetype, ltscale,
                lineweight, transparency, invisible flag, text / dimension style)
  GEOMETRY      the points the analysis works on (Item.pts) — nothing here changes them
  PRESENTATION  the style CAD resolves for it (colour, dash pattern in drawing units, lineweight, alpha, font) and the
                PARTS a compound annotation is drawn with (a dimension's extension and dimension lines, arrowheads and
                text; a leader's arrowhead; a multileader's lines, arrows and content; a hatch's pattern lines)
  PARAMETRIC    roles, datums, formulas — not here (analyse / program)

Properties are resolved by ezdxf's own CAD rules (the drawing add-on's RenderContext): BYLAYER, BYBLOCK through nested
INSERTs, layer 0 inside blocks taking the INSERT's layer, ACI and true colour, linetype × $LTSCALE × entity ltscale,
DEFAULT lineweight, transparency and layer on / off / frozen. Nothing is guessed from what a colour "usually" means.

A COVERAGE report (coverage_report) says, per entity type, what was in the file, read, drawn, editable and exportable,
and names by handle every visible entity that is NOT drawn — a drawing is never called faithful when it is not.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import ezdxf
from ezdxf import path as ezpath
from ezdxf.addons.drawing.properties import RenderContext

# Errors malformed DXF DATA raises (bad values, broken references). Programming errors on our side are not in it.
DATA_ERRORS = (ezdxf.DXFError, ValueError, ArithmeticError, IndexError, KeyError)

# A pattern hatch is drawn line by line; a pattern far too fine for its boundary (a scale typed wrong) would be millions
# of lines — it is drawn as a tint instead, and the coverage report says so.
MAX_HATCH_SEGMENTS = 40000
TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}
# How each type's edit reaches the exported DXF (dxf_write): reshaped point by point, moved as a whole, or kept as drawn.
EXPORT_RESHAPE = {
    "LINE",
    "LWPOLYLINE",
    "POLYLINE",
    "ARC",
    "CIRCLE",
    "TEXT",
    "ATTRIB",
    "MTEXT",
    "DIMENSION",
    "LEADER",
    "HATCH",
    "SOLID",
    "TRACE",
    "3DFACE",
    "POINT",
    "INSERT",
}
EXPORT_TRANSLATE = {"ELLIPSE", "SPLINE", "MULTILEADER", "MLEADER", "WIPEOUT", "IMAGE", "PDFUNDERLAY", "DWFUNDERLAY", "DGNUNDERLAY", "ACAD_TABLE", "MLINE"}
# MTEXT attachment 1..9 / TEXT halign+valign → how a text hangs from its anchor (as the canvas draws it)
_HA = {0: "l", 1: "c", 2: "r", 3: "c", 4: "c", 5: "c"}
_VA = {0: "b", 1: "bt", 2: "m", 3: "t"}


# ── style ────────────────────────────────────────────────────────────────────────


def _repair_patterns(ctx, doc) -> list[str]:
    """A linetype whose header gives no total length (group 40 = 0) while its elements are dashes and gaps is still a dashed
    linetype: ezdxf compiles it as continuous, so its pattern is compiled from the elements alone. Returns the names repaired."""
    from ezdxf.entities.ltype import compile_line_pattern

    repaired = []
    for lt in doc.linetypes:
        name = lt.dxf.name
        if ctx.line_pattern.get(name) or name.upper() in ("CONTINUOUS", "BYLAYER", "BYBLOCK"):
            continue
        try:
            tags = lt.pattern_tags
            if tags.is_complex_type():
                continue
            elements = [float(t.value) for t in tags.tags if t.code == 49]
        except DATA_ERRORS + (AttributeError,):  # an unreadable linetype record stays as ezdxf resolves it
            continue
        if len(elements) >= 2 and any(e < 0 for e in elements) and sum(abs(e) for e in elements) > 0:
            ctx.line_pattern[name] = compile_line_pattern(None, elements)
            repaired.append(name)
    return repaired


class Styler:
    """CAD property resolution for one layout, with the block-reference stack BYBLOCK resolves against."""

    def __init__(self, doc, layout):
        self.ctx = RenderContext(doc)
        self.ctx.set_current_layout(layout)
        self.repaired_linetypes = _repair_patterns(self.ctx, doc)
        self._interned: dict[tuple, dict] = {}
        self.depth = 0

    def props(self, e):
        try:
            return self.ctx.resolve_all(e)
        except (*DATA_ERRORS, AttributeError, TypeError):  # a broken reference (missing layer / linetype): drawn by default
            return None

    def push(self, p) -> None:
        self.ctx.push_state(p)
        self.depth += 1

    def pop(self) -> None:
        self.ctx.pop_state()
        self.depth -= 1

    def style(self, p) -> dict:
        """The resolved look, as plain data. Identical styles are one shared dict (a 20k-entity sheet has a handful)."""
        if p is None:
            key = ("#ffffff", True, 1.0, 0.25, "CONTINUOUS", (), "")
        else:
            color = (p.color or "#ffffff").lower()
            rgb = color[:7]
            alpha = int(color[7:9], 16) / 255 if len(color) >= 9 else 1.0
            fg = p.pen == 7 and rgb in ("#ffffff", "#000000")  # ACI 7: white on a dark screen, black on paper
            pattern = tuple(float(v) * float(p.linetype_scale or 1.0) for v in (p.linetype_pattern or ()))
            gaps = pattern[1::2]
            dash = tuple(round(v, 4) for v in pattern) if pattern and any(g > 0 for g in gaps) else ()
            font = getattr(getattr(p, "font", None), "family", "") or ""
            key = (rgb, fg, round(alpha, 3), round(float(p.lineweight or 0.25), 3), (p.linetype_name or "CONTINUOUS").upper(), dash, font)
        st = self._interned.get(key)
        if st is None:
            rgb, fg, alpha, lw, lt, dash, font = key
            st = {"color": rgb, "fg": fg, "alpha": alpha, "lw": lw, "lt": lt, "dash": list(dash)}
            if font:
                st["font"] = font
            self._interned[key] = st
        return st


def source_info(e, inserts: list[str], owner: str) -> dict:
    """The entity as the file holds it: its own handle (the definition entity for block content), where it is owned, the
    INSERT chain that places it, and its raw (unresolved) properties."""
    orig = getattr(e, "source_of_copy", None) or e
    d = e.dxf
    info = {
        "handle": orig.dxf.get("handle") or d.get("handle") or "",
        "owner": owner,
        "inserts": list(inserts),
        "layer": orig.dxf.get("layer", "0"),
        "color": d.get("color", 256),
        "linetype": d.get("linetype", "BYLAYER"),
        "ltscale": float(d.get("ltscale", 1.0)),
        "lineweight": int(d.get("lineweight", -1)),
    }
    if d.hasattr("true_color"):
        info["true_color"] = "#%06x" % (int(d.true_color) & 0xFFFFFF)
    if d.hasattr("transparency"):
        info["transparency"] = int(d.transparency)
    if d.get("invisible", 0):
        info["invisible"] = 1
    for key in ("style", "dimstyle"):
        if e.is_supported_dxf_attrib(key) and d.hasattr(key):
            info[key] = d.get(key)
    return info


# ── text ─────────────────────────────────────────────────────────────────────────


def plain_text(e) -> str:
    t = e.dxftype()
    try:
        if t == "MTEXT":
            return e.plain_text(split=False)
        if t in ("TEXT", "ATTRIB", "ATTDEF"):
            return e.plain_text()
    except DATA_ERRORS:  # unparsable formatting codes: the raw string is still the note
        return str(e.dxf.get("text", ""))
    return str(e.dxf.get("text", ""))


def text_spec(e) -> dict:
    """A TEXT / MTEXT / ATTRIB as the canvas draws it: anchor, words, height, rotation and how it hangs from the anchor."""
    t = e.dxftype()
    d = e.dxf
    if t == "MTEXT":
        k = min(max(int(d.get("attachment_point", 1) or 1), 1), 9) - 1
        try:
            rot = float(e.get_rotation())
        except DATA_ERRORS:
            rot = float(d.get("rotation", 0.0))
        spec = {
            "at": (float(d.insert[0]), float(d.insert[1])),
            "text": plain_text(e),
            "h": float(d.get("char_height", 1.0) or 1.0),
            "rot": rot,
            "ha": "lcr"[k % 3],
            "va": ("t", "m", "bt")[k // 3],
            "mtext": True,
        }
        if abs(float(d.get("line_spacing_factor", 1.0) or 1.0) - 1.0) > 1e-6:
            spec["ls"] = float(d.line_spacing_factor)
        if float(d.get("width", 0.0) or 0.0) > 0:
            spec["width"] = float(d.width)
        return spec
    ha, va = int(d.get("halign", 0)), int(d.get("valign", 0))
    at = (float(d.insert[0]), float(d.insert[1]))
    sha, sva = "l", "b"
    if (ha or va) and d.hasattr("align_point"):
        ap = (float(d.align_point[0]), float(d.align_point[1]))
        if ha in (3, 5):
            at, sha, sva = ((at[0] + ap[0]) / 2, (at[1] + ap[1]) / 2), "c", "b"
        else:
            at, sha, sva = ap, _HA.get(ha, "l"), ("m" if ha == 4 else _VA.get(va, "b"))
    spec = {"at": at, "text": plain_text(e), "h": float(d.get("height", 1.0) or 1.0), "rot": float(d.get("rotation", 0.0)), "ha": sha, "va": sva}
    if abs(float(d.get("width", 1.0) or 1.0) - 1.0) > 1e-6:
        spec["wf"] = float(d.width)
    if abs(float(d.get("oblique", 0.0) or 0.0)) > 1e-6:
        spec["oblique"] = float(d.oblique)
    return spec


# ── compound entities as the primitives CAD draws ────────────────────────────────


def flatten(e, tol: float) -> list[list[tuple[float, float]]]:
    """An entity's outline as world polylines (curves flattened to `tol`)."""
    try:
        p = ezpath.make_path(e)
    except TypeError:  # make_path's documented answer for a type with no path (TEXT, INSERT, …)
        return []
    except DATA_ERRORS:
        return []
    try:
        return [pts for sub in p.sub_paths() if len(pts := [(v.x, v.y) for v in sub.flattening(tol)]) >= 2]
    except DATA_ERRORS:  # a curve ezdxf cannot flatten: drawn without its shape (and counted by the caller)
        return []


def wide_polygons(e) -> list[list[tuple[float, float]]]:
    """A polyline with width as the filled band CAD draws (TraceBuilder: miters, tapers, arcs)."""
    try:
        from ezdxf.render.trace import TraceBuilder

        return [[(float(v[0]), float(v[1])) for v in poly] for poly in TraceBuilder.from_polyline(e).polygons()]
    except (*DATA_ERRORS, AttributeError, TypeError):
        return []


def has_width(e) -> bool:
    t = e.dxftype()
    try:
        if t == "LWPOLYLINE":
            return float(e.dxf.get("const_width", 0.0) or 0.0) > 0 or any(abs(s) > 0 or abs(w) > 0 for _x, _y, s, w in e.get_points("xyse"))
        if t == "POLYLINE" and not (e.is_poly_face_mesh or e.is_polygon_mesh):
            if float(e.dxf.get("default_start_width", 0.0) or 0.0) > 0 or float(e.dxf.get("default_end_width", 0.0) or 0.0) > 0:
                return True
            return any(float(v.dxf.get("start_width", 0.0) or 0.0) > 0 or float(v.dxf.get("end_width", 0.0) or 0.0) > 0 for v in e.vertices)
    except DATA_ERRORS:
        return False
    return False


def parts_of(e, styler: Styler, tol: float, tag_fills: str = "") -> list[dict]:
    """A compound entity (dimension, leader, multileader, table …) as the primitives CAD draws it with — each in the style
    CAD resolves for it inside the compound. Fills (arrowheads) are tagged with `tag_fills`; texts are tagged "text"."""
    try:
        subs = list(e.virtual_entities())
    except (*DATA_ERRORS, AttributeError, TypeError, NotImplementedError):
        return []
    p = styler.props(e)
    if p is not None:
        styler.push(p)
    out: list[dict] = []
    try:
        for v in subs:
            out.extend(_primitive_parts(v, styler, tol, tag_fills, 0))
    finally:
        if p is not None:
            styler.pop()
    return out


def _primitive_parts(v, styler: Styler, tol: float, tag_fills: str, depth: int) -> list[dict]:
    t = v.dxftype()
    pv = styler.props(v)
    if pv is not None and not pv.is_visible:
        return []
    st = styler.style(pv)
    layer = (pv.layer if pv is not None else v.dxf.get("layer", "0")) or "0"
    if t == "INSERT":  # an arrowhead or a symbol inside the compound: its own content, in its own context
        if depth > 6:
            return []
        out: list[dict] = []
        if pv is not None:
            styler.push(pv)
        try:
            for w in v.virtual_entities():
                out.extend(_primitive_parts(w, styler, tol, tag_fills or "block", depth + 1))
        except (*DATA_ERRORS, AttributeError, TypeError):
            pass  # an arrow block that cannot be expanded draws nothing; the line it ends still does
        finally:
            if pv is not None:
                styler.pop()
        return out
    if t == "POINT" or layer.upper() == "DEFPOINTS":  # definition points: CAD neither plots nor (in a dimension) shows them
        return []
    if t in ("SOLID", "TRACE"):
        q = [(float(v.dxf.get(f"vtx{i}", (0, 0))[0]), float(v.dxf.get(f"vtx{i}", (0, 0))[1])) for i in range(4)]
        return [{"k": "g", "pts": [q[0], q[1], q[3], q[2]], "s": st, "tag": tag_fills or "fill"}]
    if t in TEXT_TYPES:
        return [{"k": "t", **text_spec(v), "s": st, "tag": "text"}]
    if t == "HATCH" and v.dxf.get("solid_fill", 0):
        rings = [[(float(x), float(y)) for x, y in ring] for ring in hatch_rings(v, tol)]
        return [{"k": "g", "pts": r, "s": st, "tag": tag_fills or "fill"} for r in rings if len(r) >= 3]
    if t in ("LWPOLYLINE", "POLYLINE") and has_width(v):
        return [{"k": "g", "pts": poly, "s": st, "tag": tag_fills or "fill"} for poly in wide_polygons(v) if len(poly) >= 3]
    closed = bool(getattr(v, "closed", False)) if t == "LWPOLYLINE" else t in ("CIRCLE",)
    return [{"k": "p", "pts": poly, "closed": closed, "s": st, "tag": "line"} for poly in flatten(v, tol)]


def hatch_rings(e, tol: float) -> list[list[tuple[float, float]]]:
    """A hatch's boundary paths as closed world polygons (arcs and splines flattened)."""
    out = []
    try:
        for p in ezpath.from_hatch(e):
            for sub in p.sub_paths():
                pts = [(v.x, v.y) for v in sub.flattening(tol)]
                if len(pts) >= 3:
                    out.append(pts)
    except DATA_ERRORS:
        return []
    return out


def _baselines(e) -> list[list]:
    """The pattern's base lines in world coordinates: [origin x, y, direction x, y, offset x, y, dashes].

    For a hatch inside a block the definition's own pattern is taken and moved by the INSERT's matrix here: ezdxf's
    transform of a virtual hatch scales the (already scaled) pattern by its scale again (ezdxf 1.4: a pattern of scale 50
    comes out 50 times too coarse), which would draw a block's concrete or sand hatch nearly empty."""
    from ezdxf.math import Vec3

    src = getattr(e, "source_of_copy", None)
    ref = getattr(e, "source_block_reference", None)
    owner = src if (src is not None and ref is not None and getattr(src, "pattern", None)) else e
    if not getattr(owner, "pattern", None):
        return []
    m = ref.matrix44() if owner is src else None
    out = []
    for ln in owner.pattern.lines:
        base, off, direction = Vec3(ln.base_point), Vec3(ln.offset), Vec3.from_deg_angle(ln.angle)
        k = 1.0
        if m is not None:
            base, off, direction = m.transform(base), m.transform_direction(off), m.transform_direction(direction)
            k = direction.magnitude or 1.0
            direction = direction / k
        out.append(
            [
                float(base.x),
                float(base.y),
                float(direction.x),
                float(direction.y),
                float(off.x),
                float(off.y),
                [float(d) * k for d in (ln.dash_length_items or [])],
            ]
        )
    return out


def _render_baselines(baselines: list, paths) -> tuple[list[list[float]], bool]:
    """Pattern lines (dashes and dots rendered; a dot is a zero-length segment) of these base lines inside `paths`."""
    from ezdxf.math import Vec2
    from ezdxf.render import hatching

    out: list[list[float]] = []
    for ox, oy, dx, dy, fx, fy, pattern in baselines:
        if math.hypot(fx, fy) < hatching.MIN_HATCH_LINE_DISTANCE:
            continue
        try:
            bl = hatching.HatchBaseLine(Vec2(ox, oy), Vec2(dx, dy), Vec2(fx, fy), list(pattern) or None)
            for line in hatching.hatch_paths(bl, paths):
                for a, b in bl.pattern_renderer(line.distance).render(line.start, line.end):
                    out.append([float(a.x), float(a.y), float(b.x), float(b.y)])
                if len(out) > MAX_HATCH_SEGMENTS:
                    return [], True
        except (*DATA_ERRORS, hatching.HatchingError, TypeError):
            continue  # one base line ezdxf cannot hatch: the others still draw
    return out, False


def hatch_info(e, tol: float) -> dict:
    """What a hatch draws: a solid fill, a gradient, or pattern lines clipped to its boundary (dashes and dots rendered,
    capped, deterministic) — with the pattern's base lines so a regenerated boundary is hatched the same way again."""
    from ezdxf.render import hatching

    if e.dxf.get("solid_fill", 0):
        gradient = getattr(e, "gradient", None)
        if gradient is not None and getattr(gradient, "kind", 0):
            return {"fill": "gradient", "name": getattr(gradient, "name", "")}
        return {"fill": "solid"}
    info: dict = {"fill": "pattern", "name": e.dxf.get("pattern_name", ""), "baselines": [], "segments": []}
    try:
        info["baselines"] = _baselines(e)
        paths = hatching.hatch_boundary_paths(e, True)
    except (*DATA_ERRORS, hatching.HatchingError, AttributeError, TypeError) as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"[:120]
        return info
    segs, dense = _render_baselines(info["baselines"], paths)
    if dense:
        info["too_dense"] = True
    info["segments"] = segs
    return info


def pattern_segments(baselines: list, rings: list[list[tuple[float, float]]]) -> tuple[list[list[float]], bool]:
    """Pattern lines for a (regenerated) boundary, from the hatch's own base lines. (segments, too_dense)."""
    from ezdxf import path as _path
    from ezdxf.math import Vec2

    paths = [_path.from_vertices([Vec2(p) for p in r], close=True) for r in rings if len(r) >= 3]
    if not paths:
        return [], False
    return _render_baselines(baselines, paths)


# ── coverage ─────────────────────────────────────────────────────────────────────


@dataclass
class Coverage:
    """Counters the reader fills while it walks the file (top level and block content, recursively)."""

    seen: Counter = field(default_factory=Counter)  # visible entities met, by type
    hidden: Counter = field(default_factory=Counter)  # on an off / frozen layer, or invisible
    dropped: Counter = field(default_factory=Counter)  # met, visible, and NOT read (with why)
    dropped_handles: dict = field(default_factory=lambda: defaultdict(list))
    hidden_handles: dict = field(default_factory=lambda: defaultdict(list))
    compound_parts: Counter = field(default_factory=Counter)  # primitives compound entities are drawn with, by kind
    max_depth: int = 0
    inserts: int = 0
    repaired_linetypes: list = field(default_factory=list)  # dashed linetypes compiled from their elements (no total length)

    def see(self, t: str) -> None:
        self.seen[t] += 1

    def hide(self, t: str, handle: str) -> None:
        self.hidden[t] += 1
        if len(self.hidden_handles[t]) < 25:
            self.hidden_handles[t].append(handle)

    def drop(self, t: str, handle: str, why: str) -> None:
        self.dropped[f"{t}: {why}"] += 1
        if len(self.dropped_handles[t]) < 25:
            self.dropped_handles[t].append(handle)


def coverage_report(dr, doc, cov: Coverage, layout) -> dict:
    """Per entity type: in the file (visible), read, drawn, editable, how an edit is exported — and every visible entity
    that is not drawn, by handle. Plus the properties the drawing uses and whether each is reproduced."""
    from .display import primitives

    read = Counter(it.dxftype for it in dr.items)
    drawn: Counter = Counter()
    editable: Counter = Counter()
    undrawn: dict[str, list[str]] = defaultdict(list)
    for it in dr.items:
        prims = primitives(it, it.pts, None, None, dr.units_mm) if it.dxftype != "INSERT" else [{"k": "anchor"}]
        if prims:
            drawn[it.dxftype] += 1
        elif len(undrawn[it.dxftype]) < 25:
            undrawn[it.dxftype].append((it.extra.get("source") or {}).get("handle") or it.src)
        if it.role.value in ("structural", "reference") and it.vertex_pts:
            editable[it.dxftype] += 1
    types = sorted(set(cov.seen) | set(read) | {k.split(":")[0] for k in cov.dropped})
    rows = []
    for t in types:
        n_drop = sum(v for k, v in cov.dropped.items() if k.split(":")[0] == t)
        export = "reshape" if t in EXPORT_RESHAPE else "translate" if t in EXPORT_TRANSLATE else "as drawn"
        row = {
            "type": t,
            "in_file": cov.seen.get(t, 0),
            "read": read.get(t, 0),
            "drawn": drawn.get(t, 0),
            "editable": editable.get(t, 0),
            "hidden": cov.hidden.get(t, 0),
            "not_read": n_drop,
            "export": export,
        }
        if t == "INSERT":  # a block reference is read by expanding it: its content is drawn entity by entity
            row.update(read=cov.inserts, drawn=cov.inserts, editable=read.get(t, 0), note="expanded; small blocks move as one symbol")
        if cov.dropped_handles.get(t):
            row["not_read_handles"] = cov.dropped_handles[t]
        if undrawn.get(t):
            row["not_drawn_handles"] = undrawn[t]
        rows.append(row)
    problems = []
    for k, v in sorted(cov.dropped.items()):
        problems.append(f"{v} {k} — handles {', '.join(cov.dropped_handles.get(k.split(':')[0], [])[:6])}")
    for t, hs in undrawn.items():
        if t != "INSERT":
            problems.append(f"{read[t] - drawn[t]} {t} read but not drawn — handles {', '.join(hs[:6])}")

    # properties in use, each with how it is reproduced
    linetypes: dict[str, dict] = {}
    colors: Counter = Counter()
    lineweights: Counter = Counter()
    fonts: Counter = Counter()
    hatches: dict[str, dict] = {}
    dimstyles: Counter = Counter()
    for it in dr.items:
        st = it.extra.get("style") or {}
        if st:
            name = st.get("lt", "CONTINUOUS")
            drawn_as = ("dashed" if st.get("dash") else "continuous") + (
                " (compiled from its dashes: the file gives no total length)" if name in {n.upper() for n in cov.repaired_linetypes} else ""
            )
            lt = linetypes.setdefault(name, {"entities": 0, "dash": st.get("dash", []), "drawn_as": drawn_as})
            lt["entities"] += 1
            colors["ACI 7 (foreground)" if st.get("fg") else st.get("color", "?")] += 1
            lineweights[st.get("lw")] += 1
            if st.get("font"):
                fonts[st["font"]] += 1
        h = it.extra.get("hatch")
        if h:
            row = hatches.setdefault(h.get("name") or h.get("fill"), {"count": 0, "drawn_as": set()})
            row["count"] += 1
            row["drawn_as"].add(
                "tint (pattern too dense)" if h.get("too_dense") else "pattern lines" if h.get("segments") or h.get("baselines") else h.get("fill", "?")
            )
        src = it.extra.get("source") or {}
        if src.get("dimstyle"):
            dimstyles[src["dimstyle"]] += 1
    for row in hatches.values():
        row["drawn_as"] = sorted(row["drawn_as"])
    layers = []
    for layer in doc.layers:
        try:
            layers.append(
                {
                    "name": layer.dxf.name,
                    "on": layer.is_on(),
                    "frozen": layer.is_frozen(),
                    "locked": layer.is_locked(),
                    "color": layer.dxf.get("color", 7),
                    "linetype": layer.dxf.get("linetype", "Continuous"),
                    "lineweight": layer.dxf.get("lineweight", -3),
                    "plot": bool(layer.dxf.get("plot", 1)),
                }
            )
        except DATA_ERRORS:  # an unreadable layer record: named, not hidden
            layers.append({"name": str(layer.dxf.get("name", "?")), "unreadable": True})
    layouts = []
    for lo in doc.layouts:
        vps = []
        if not lo.is_modelspace:
            for vp in lo.query("VIEWPORT"):
                try:
                    vps.append(
                        {
                            "handle": vp.dxf.handle,
                            "center": [round(vp.dxf.center[0], 3), round(vp.dxf.center[1], 3)],
                            "width": round(vp.dxf.width, 3),
                            "height": round(vp.dxf.height, 3),
                            "view_center": [round(vp.dxf.view_center_point[0], 3), round(vp.dxf.view_center_point[1], 3)],
                            "view_height": round(vp.dxf.view_height, 3),
                        }
                    )
                except DATA_ERRORS:
                    vps.append({"handle": vp.dxf.get("handle", "?"), "unreadable": True})
        layouts.append({"name": lo.name, "entities": len(lo), "read": lo.name == getattr(layout, "name", "Model"), "viewports": vps})
    seen_total = sum(cov.seen.values())
    read_total = sum(1 for it in dr.items if it.dxftype != "INSERT")
    return {
        "faithful": not problems,
        "problems": problems,
        "entities": {
            "visible_in_file": seen_total,
            "read": read_total,
            "hidden": sum(cov.hidden.values()),
            "not_read": sum(cov.dropped.values()),
            "inserts_expanded": cov.inserts,
            "block_depth": cov.max_depth,
        },
        "types": rows,
        "compound_parts": dict(cov.compound_parts),
        "linetypes": linetypes,
        "colors": dict(colors.most_common(24)),
        "lineweights": {str(k): v for k, v in sorted(lineweights.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))},
        "fonts": dict(fonts),
        "hatch_patterns": hatches,
        "dimension_styles": dict(dimstyles),
        "header": {
            "$LTSCALE": float(doc.header.get("$LTSCALE", 1.0)),
            "$INSUNITS": int(doc.header.get("$INSUNITS", 0) or 0),
            "$DIMSCALE": float(doc.header.get("$DIMSCALE", 1.0) or 1.0),
            "$LWDEFAULT": int(doc.header.get("$LWDEFAULT", 25) or 25),
            "version": doc.dxfversion,
        },
        "layers": layers,
        "layouts": layouts,
        "hidden_handles": {k: v for k, v in cov.hidden_handles.items()},
    }


def transform_part(part: dict, fn) -> dict:
    """A part with every point mapped by fn((x, y)) -> (x, y). Texts move their anchor only."""
    q = dict(part)
    if "pts" in q:
        q["pts"] = [fn(p) for p in q["pts"]]
    if "at" in q:
        q["at"] = fn(q["at"])
    return q


def rigid(dx: float, dy: float, angle: float = 0.0, pivot: tuple[float, float] = (0.0, 0.0)):
    """A rigid motion: rotate by `angle` (radians) about `pivot`, then translate by (dx, dy)."""
    c, s = math.cos(angle), math.sin(angle)
    px, py = pivot

    def fn(p):
        x, y = p[0] - px, p[1] - py
        return (px + c * x - s * y + dx, py + s * x + c * y + dy)

    return fn
