"""Design intent where one named size is drawn in TWO views side by side (a section and its twin): two assemblies, one value.

A paid run on a real sheet (two half sections of one bridge, one ClearSpan) left the span's growth undecided and drawn as "the right end stays": the plan
of each assembly was checked against the whole unit, and the other view — which the same value also drives — moved, so every candidate failed the same way
("unrelated part moves", "fixed part moves", "a binding was lost") whichever side was tried. What one assembly's plan must answer for is its own: the parts
the value moves through its occurrences in the other assembly are that assembly's."""

from __future__ import annotations

import copy
from pathlib import Path

import ezdxf
import pytest

from dxf_autoparam import design_intent as di
from dxf_autoparam.crossview import EMPTY_ANSWER, SheetModel
from dxf_autoparam.plan_bench import Box, faces, members
from dxf_autoparam.topology import of

GAP = 2500.0


def twin_gad(path: Path, b: Box) -> dict[tuple[int, str], str]:
    """Two identical box sections side by side at the same height, each with its drawn centre line and its clear-span dimension."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.dimstyles.new("GAD50", dxfattribs={"dimtxt": 2.5, "dimscale": 50, "dimgap": 0.6, "dimtad": 1})
    for name, colour in (("STRUCTURE", 7), ("CENTRE", 1), ("DIM", 2), ("TEXT", 7)):
        doc.layers.add(name, color=colour)
    msp = doc.modelspace()
    handles: dict[tuple[int, str], str] = {}
    top = b.bottom + b.height + b.top
    for v, x0 in enumerate((0.0, b.width + GAP)):
        for name, pts in members(b, x0=x0).items():
            if name != "Foundation":
                handles[(v, name)] = msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "STRUCTURE"}).dxf.handle
        msp.add_line((x0 + b.width / 2, -200), (x0 + b.width / 2, top + 600), dxfattribs={"layer": "CENTRE"})
        f = faces(b, x0)
        for k in range(b.cells):
            msp.add_linear_dim(base=(0, top + 500), p1=(f[1 + 2 * k], b.bottom + b.height / 2), p2=(f[2 + 2 * k], b.bottom + b.height / 2),
                               dimstyle="GAD50", dxfattribs={"layer": "DIM"}).render()
        msp.add_linear_dim(base=(0, top + 900), p1=(x0, top), p2=(x0 + b.wall, top), dimstyle="GAD50", dxfattribs={"layer": "DIM"}).render()
        title = f"SECTION {'AB'[v]}-{'AB'[v]}"
        msp.add_text(title, height=175, dxfattribs={"layer": "TEXT", "insert": (x0 + b.width / 2, -900), "halign": 1, "align_point": (x0 + b.width / 2, -900)})
    doc.saveas(str(path))
    return handles


def twin_answer(sm: SheetModel, uid: str, b: Box, handles: dict[tuple[int, str], str]) -> dict:
    """Each member a part (by its region), ClearSpan and OuterWall named once for both views (the candidate that holds both occurrences)."""
    u = sm.unit(uid)
    an, um, topo = u.an, u.sub.units_mm, of(u.an)
    item_of = {it.handle: k for k, it in enumerate(an.drawing.items)}
    comps = []
    for (v, name), h in handles.items():
        pts = an.drawing.items[item_of[h]].pts
        box = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        region = min((r for r in topo.regions if sum(abs(a - c) for a, c in zip(r.bbox, box, strict=True)) < 1e-6 * max(1.0, box[2] - box[0])), key=lambda r: r.area)
        typ = "slab" if "Slab" in name else "wall" if "Wall" in name else "haunch"
        comps.append({"name": f"{'AB'[v]}{name}", "type": typ, "level": "component", "regions": [region.id], "confidence": 0.9})

    def line(at: float) -> str:
        return min((d for d in an.datums.values() if d.axis == "x"), key=lambda d: abs(d.value * um - at)).id

    def named(name: str, pairs: list[tuple[float, float]]) -> dict:
        ids = {(line(lo), line(hi)) for lo, hi in pairs}
        cluster = next(c for c in an.clusters.values() if ids <= {(an.gaps[g].a, an.gaps[g].b) for g in c.gaps})
        return {"name": name, "label": name, "component": comps[0]["name"], "kind": "length", "candidate": cluster.id, "value": abs(pairs[0][1] - pairs[0][0]),
                "occurrences": [g for g in cluster.gaps if (an.gaps[g].a, an.gaps[g].b) in ids]}

    f0, f1 = faces(b, 0.0), faces(b, b.width + GAP)
    answer = copy.deepcopy(EMPTY_ANSWER)
    answer.update(structure_type="RCC box culvert", family="rcc_box", components=comps, parameters=[
        named("ClearSpan", [(f0[1], f0[2]), (f1[1], f1[2])]), named("OuterWall", [(0.0, b.wall), (b.width + GAP, b.width + GAP + b.wall)])])
    return answer


def twin_sheet(tmp_path: Path, cells: int) -> tuple[SheetModel, str, Box]:
    b = Box(cells=cells, span=2500.0, plan=False, detail=False)
    handles = twin_gad(tmp_path / f"twin{cells}.dxf", b)
    sm = SheetModel.open(str(tmp_path / f"twin{cells}.dxf"))
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    sm.commit_answer(uid, twin_answer(sm, uid, b, handles))
    return sm, uid, b


def test_a_size_drawn_in_two_views_side_by_side_grows_about_the_centre_of_each(tmp_path):
    sm, uid, _b = twin_sheet(tmp_path, 1)
    axes = [a for a in sm.unit(uid).answer["intent_axes"] if a["axis"] == "x"]
    assert len(axes) == 2, "two views side by side are two assemblies on x: one value drives both"
    for ax in axes:
        assert ax["status"] == "decided" and ax["policy"] == "centered" and ax["dropped"] == [], ax
        assert "mirror" in ax["evidence"][0], "decided by the faces mirroring about the drawn centre line, in each view"
    prog = sm.unit(uid).prog
    v0, v1 = prog.datum_values(), prog.datum_values({"ClearSpan": prog.params["ClearSpan"].value + 1.0})
    span = next(d for d in di.drivers(prog, sm.unit(uid).answer) if d.name == "ClearSpan")
    assert len(span.pairs) == 2
    for lo, hi in span.pairs:  # both views: the two faces move the same distance apart
        assert v1[lo] - v0[lo] == pytest.approx(-0.5) and v1[hi] - v0[hi] == pytest.approx(0.5), (lo, hi)


def test_the_other_view_is_not_held_still_or_dragged_along_by_one_views_plan(tmp_path):
    sm, uid, _b = twin_sheet(tmp_path, 2)
    for ax in sm.unit(uid).answer["intent_axes"]:
        if ax["axis"] == "x":
            assert ax["status"] == "decided", ax["evidence"]
    prog = sm.unit(uid).prog
    rows = {p["id"]: p for p in prog.intent["plans"]}
    assert rows and all(p["ok"] for p in rows.values()), "every promise of every plan is measured on the unit built with all of them"


def test_every_side_failing_the_same_way_is_said_to_be_about_the_structure_not_the_side():
    same = "plan I_Span: clash members — expected no member runs into another, measured A crosses B"
    tried = [{"policy": p, "centre": c, "why": same + " [parts hung on it stay]", "blocked": []}
             for p, c in (("centered", "x3"), ("start_fixed", None), ("end_fixed", None))]
    why, blocked = di._why_undecided(tried, ("left", "right"))
    assert why.startswith("whichever side stays the same thing breaks") and "crosses B" in why and blocked == []
    other = [dict(tried[0]), {**tried[1], "why": "plan I_Span: binding Wall — lost"}, dict(tried[2])]
    why2, _ = di._why_undecided(other, ("left", "right"))
    assert not why2.startswith("whichever") and "for the left to stay" in why2, "different failures are told apart, as before"
