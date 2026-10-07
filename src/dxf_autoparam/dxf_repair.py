"""Last-resort reader: rebuild a DXF that even ezdxf's recovery refuses.

Typical case: a file that declares a modern version ($ACADVER AC1032) but is written in
R12 style (no subclass markers, no handles/owners) — what older web exporters produce,
including Aagento's previous writer. AutoCAD refuses such files; viewers accept them.

The file is read as raw group-code pairs and every entity the prototype understands is
re-created in a fresh R2018 document (layers, blocks, block references, lines,
polylines with bulges, arcs, circles, ellipses, splines, texts, dimensions, leaders,
solids, points, polyline-boundary hatches). The result is a clean file; what could not
be carried is counted.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing as EzDoc


def _pairs(path: str) -> list[tuple[int, str]]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = text.splitlines()
    out = []
    for i in range(0, len(lines) - 1, 2):
        try:
            out.append((int(lines[i].strip()), lines[i + 1].rstrip("\r")))
        except ValueError:
            continue
    return out


def _f(tags: list[tuple[int, str]], code: int, default: float = 0.0) -> float:
    for c, v in tags:
        if c == code:
            try:
                return float(v)
            except ValueError:
                return default
    return default


def _s(tags: list[tuple[int, str]], code: int, default: str = "") -> str:
    for c, v in tags:
        if c == code:
            return v.strip() if code != 1 else v
    return default


def _entities(pairs: list[tuple[int, str]], start: int, stop_names: set[str]) -> tuple[list[list[tuple[int, str]]], int]:
    """Entities from `start` until a 0-tag in `stop_names`; returns (entities, index of the stop tag)."""
    ents: list[list[tuple[int, str]]] = []
    i = start
    cur: list[tuple[int, str]] | None = None
    while i < len(pairs):
        c, v = pairs[i]
        if c == 0:
            if v in stop_names:
                if cur:
                    ents.append(cur)
                return ents, i
            if cur:
                ents.append(cur)
            cur = [(0, v)]
        elif cur is not None:
            cur.append((c, v))
        i += 1
    if cur:
        ents.append(cur)
    return ents, i


def _group_polylines(ents: list[list[tuple[int, str]]]) -> list[list[tuple[int, str]]]:
    """POLYLINE + VERTEX… + SEQEND → one POLYLINE entity whose vertices ride on code -3 ("x,y,bulge")."""
    out = []
    i = 0
    while i < len(ents):
        e = ents[i]
        i += 1
        if e[0][1] != "POLYLINE":
            out.append(e)
            continue
        merged = list(e)
        while i < len(ents) and ents[i][0][1] == "VERTEX":
            v = ents[i]
            merged.append((-3, f"{_f(v, 10)},{_f(v, 20)},{_f(v, 42)}"))
            i += 1
        if i < len(ents) and ents[i][0][1] == "SEQEND":
            i += 1
        out.append(merged)
    return out


def _add(layout, e: list[tuple[int, str]], counts: Counter, doc: EzDoc) -> None:
    t = e[0][1]
    attribs = {"layer": _s(e, 8, "0") or "0"}
    color = _s(e, 62)
    if color and color.lstrip("-").isdigit() and int(color) not in (256,):
        attribs["color"] = abs(int(color)) if int(color) != 0 else 0
    lt = _s(e, 6)
    if lt and lt.upper() not in ("BYLAYER",) and lt in doc.linetypes:
        attribs["linetype"] = lt
    if attribs["layer"] not in doc.layers:
        doc.layers.add(attribs["layer"])
    try:
        if t == "LINE":
            layout.add_line((_f(e, 10), _f(e, 20)), (_f(e, 11), _f(e, 21)), dxfattribs=attribs)
        elif t == "LWPOLYLINE":
            pts = []
            cur = None
            for c, v in e:
                if c == 10:
                    cur = [float(v), 0.0, 0.0, 0.0, 0.0]
                    pts.append(cur)
                elif c == 20 and cur is not None:
                    cur[1] = float(v)
                elif c == 42 and cur is not None:
                    cur[4] = float(v)
            layout.add_lwpolyline([tuple(p) for p in pts], format="xyseb", close=bool(int(_f(e, 70)) & 1), dxfattribs=attribs)
        elif t == "POLYLINE":
            verts = [tuple(float(n) for n in v.split(",")) for c, v in e if c == -3]
            layout.add_lwpolyline([(x, y, 0, 0, b) for x, y, b in verts], format="xyseb", close=bool(int(_f(e, 70)) & 1), dxfattribs=attribs)
        elif t == "CIRCLE":
            layout.add_circle((_f(e, 10), _f(e, 20)), _f(e, 40), dxfattribs=attribs)
        elif t == "ARC":
            layout.add_arc((_f(e, 10), _f(e, 20)), _f(e, 40), _f(e, 50), _f(e, 51), dxfattribs=attribs)
        elif t == "ELLIPSE":
            layout.add_ellipse((_f(e, 10), _f(e, 20)), major_axis=(_f(e, 11), _f(e, 21)), ratio=_f(e, 40, 1.0) or 1.0,
                               start_param=_f(e, 41), end_param=_f(e, 42, 6.283185307179586), dxfattribs=attribs)
        elif t == "SPLINE":
            cps = []
            cur = None
            for c, v in e:
                if c == 10:
                    cur = [float(v), 0.0]
                    cps.append(cur)
                elif c == 20 and cur is not None:
                    cur[1] = float(v)
            if len(cps) >= 2:
                layout.add_open_spline([tuple(p) for p in cps], degree=int(_f(e, 71, 3)) or 3, dxfattribs=attribs)
        elif t == "TEXT":
            txt = layout.add_text(_s(e, 1), height=_f(e, 40, 2.5) or 2.5, rotation=_f(e, 50), dxfattribs=attribs)
            txt.dxf.insert = (_f(e, 10), _f(e, 20))
            h, va = int(_f(e, 72)), int(_f(e, 73))
            if h or va:
                txt.dxf.halign, txt.dxf.valign = h, va
                txt.dxf.align_point = (_f(e, 11), _f(e, 21))
        elif t == "MTEXT":
            text = "".join(v for c, v in e if c == 3) + _s(e, 1)
            layout.add_mtext(text, dxfattribs={**attribs, "insert": (_f(e, 10), _f(e, 20)), "char_height": _f(e, 40, 2.5) or 2.5,
                                                "rotation": _f(e, 50), "attachment_point": int(_f(e, 71, 1)) or 1})
        elif t == "POINT":
            layout.add_point((_f(e, 10), _f(e, 20)), dxfattribs=attribs)
        elif t in ("SOLID", "TRACE"):
            layout.add_solid([(_f(e, 10 + k), _f(e, 20 + k)) for k in range(4)], dxfattribs=attribs)
        elif t == "INSERT":
            name = _s(e, 2)
            if name in doc.blocks:
                layout.add_blockref(name, (_f(e, 10), _f(e, 20)), dxfattribs={**attribs, "xscale": _f(e, 41, 1.0) or 1.0,
                                                                              "yscale": _f(e, 42, 1.0) or 1.0, "rotation": _f(e, 50)})
            else:
                counts["INSERT (missing block)"] += 1
                return
        elif t == "DIMENSION":
            kind = int(_f(e, 70)) & 7
            p1, p2, base = (_f(e, 13), _f(e, 23)), (_f(e, 14), _f(e, 24)), (_f(e, 10), _f(e, 20))
            text = _s(e, 1) or "<>"
            if kind == 0:
                layout.add_linear_dim(base=base, p1=p1, p2=p2, angle=_f(e, 50), text=text, dxfattribs=attribs).render()
            elif kind == 1:
                d = layout.add_aligned_dim(p1=p1, p2=p2, distance=1.0, text=text, dxfattribs=attribs)
                d.dimension.dxf.defpoint = base
                d.render()
            else:
                counts["DIMENSION (angular/radial, not rebuilt)"] += 1
                return
        elif t == "LEADER":
            pts = []
            cur = None
            for c, v in e:
                if c == 10:
                    cur = [float(v), 0.0]
                    pts.append(cur)
                elif c == 20 and cur is not None:
                    cur[1] = float(v)
            if len(pts) >= 2:
                layout.add_leader([tuple(p) for p in pts], dxfattribs=attribs)
        elif t == "HATCH":
            # polyline boundary paths only: 92 flag bit 2, then 72 has-bulge, 73 closed, 93 count, 10/20 [42]
            hatch = layout.add_hatch(dxfattribs=attribs)
            name = _s(e, 2, "SOLID") or "SOLID"
            if name.upper() == "SOLID":
                hatch.set_solid_fill()
            else:
                try:
                    hatch.set_pattern_fill(name, scale=_f(e, 41, 1.0) or 1.0, angle=_f(e, 52))
                except (ezdxf.DXFError, ValueError, KeyError):  # a pattern this ezdxf does not know: solid
                    hatch.set_solid_fill()
            i = 0
            added = 0
            while i < len(e):
                c, v = e[i]
                if c == 92 and int(v) & 2:
                    n = 0
                    j = i + 1
                    while j < len(e) and e[j][0] != 93:
                        j += 1
                    n = int(e[j][1]) if j < len(e) else 0
                    pts = []
                    k = j + 1
                    while k < len(e) and len(pts) < n:
                        if e[k][0] == 10:
                            pts.append((float(e[k][1]), float(e[k + 1][1]) if k + 1 < len(e) and e[k + 1][0] == 20 else 0.0))
                        k += 1
                    if len(pts) >= 3:
                        hatch.paths.add_polyline_path(pts, is_closed=True)
                        added += 1
                    i = k
                    continue
                i += 1
            if not added:
                layout.delete_entity(hatch)
                counts["HATCH (edge boundaries, not rebuilt)"] += 1
                return
        else:
            counts[t] += 1
            return
        counts["rebuilt"] += 1
    except Exception as exc:  # noqa: BLE001 — the per-entity boundary of the repair: one bad entity must not stop the rest; counted and reported by name
        counts[f"{t} (bad data: {type(exc).__name__})"] += 1


def rebuild(path: str, out_path: str) -> tuple[EzDoc, Counter]:
    pairs = _pairs(path)
    doc = ezdxf.new("R2018", setup=True)
    counts: Counter = Counter()
    sections: dict[str, int] = {}
    for i, (c, v) in enumerate(pairs):
        if c == 0 and v == "SECTION" and i + 1 < len(pairs) and pairs[i + 1][0] == 2:
            sections[pairs[i + 1][1].strip()] = i + 2
    units = None
    if "HEADER" in sections:
        i = sections["HEADER"]
        while i < len(pairs) and not (pairs[i][0] == 0 and pairs[i][1] == "ENDSEC"):
            if pairs[i] == (9, "$INSUNITS") and i + 1 < len(pairs):
                units = int(float(pairs[i + 1][1]))
            i += 1
    if units is not None:
        doc.header["$INSUNITS"] = units
    if "TABLES" in sections:
        ents, _ = _entities(pairs, sections["TABLES"], {"ENDSEC"})
        for e in ents:
            if e[0][1] == "LAYER":
                name = _s(e, 2)
                if name and name not in doc.layers:
                    lt = _s(e, 6, "Continuous")
                    color = int(_f(e, 62, 7))
                    layer = doc.layers.add(name, color=abs(color) or 7, linetype=lt if lt in doc.linetypes else "Continuous")
                    if color < 0:
                        layer.off()
    if "BLOCKS" in sections:
        i = sections["BLOCKS"]
        while i < len(pairs) and not (pairs[i][0] == 0 and pairs[i][1] == "ENDSEC"):
            if pairs[i] == (0, "BLOCK"):
                head, j = _entities(pairs, i, {"ENDSEC"})[0][0], i + 1
                name = _s(head, 2)
                ents, stop = _entities(pairs, j, {"ENDBLK"})
                ents = [x for x in ents if x[0][1] != "BLOCK"]
                if name and not name.startswith("*") and name not in doc.blocks:
                    blk = doc.blocks.new(name, base_point=(_f(head, 10), _f(head, 20)))
                    for e in _group_polylines(ents):
                        _add(blk, e, counts, doc)
                i = stop + 1
                continue
            i += 1
    if "ENTITIES" in sections:
        ents, _ = _entities(pairs, sections["ENTITIES"], {"ENDSEC"})
        msp = doc.modelspace()
        for e in _group_polylines(ents):
            _add(msp, e, counts, doc)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out_path)
    return doc, counts
