"""A generated box section that stands between two stated levels, drawn the way a real GAD draws it: the road surface a wearing course above the
bottom slab, the clear height dimensioned from the road to the soffit, an earth cushion between the top of the slab and the formation level, and an
OVERALL height dimension from the bottom of the box to its top — a sum that spans the road level. Nothing here is one drawing's numbers: every size is
a parameter of the generator, and the tests say what each size must move."""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from pathlib import Path

import ezdxf


@dataclass
class LevelBox:
    span: float = 4000.0
    wall: float = 400.0
    bottom: float = 400.0  # bottom slab
    wearing: float = 150.0  # the road surface stands this far above the top of the bottom slab
    clear: float = 2850.0  # clear height, road surface to soffit
    top: float = 400.0  # top slab
    cushion: float = 1000.0  # top of slab to formation level
    pcc: float = 150.0  # base course under the box
    datum_m: float = 100.0  # the level of y = 0, in metres
    overall_dim: bool = True  # the drawing also dimensions the box's overall height
    kerb: float = 300.0  # a kerb on the road beside the box (its top this far above the road surface); 0 = none

    @property
    def width(self) -> float:
        return self.span + 2 * self.wall

    @property
    def y_road(self) -> float:
        return self.bottom + self.wearing

    @property
    def y_soffit(self) -> float:
        return self.y_road + self.clear

    @property
    def y_top(self) -> float:
        return self.y_soffit + self.top

    @property
    def y_formation(self) -> float:
        return self.y_top + self.cushion

    def level(self, y: float) -> float:
        return round(self.datum_m + y / 1000.0, 3)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def members(b: LevelBox) -> dict[str, list[tuple[float, float]]]:
    W = b.width
    return {
        "BottomSlab": _rect(0, 0, W, b.bottom),
        "LeftWall": _rect(0, b.bottom, b.wall, b.y_soffit),
        "RightWall": _rect(W - b.wall, b.bottom, W, b.y_soffit),
        "TopSlab": _rect(0, b.y_soffit, W, b.y_top),
        "WearingCourse": _rect(b.wall, b.bottom, W - b.wall, b.y_road),
        "Cushion": _rect(0, b.y_top, W, b.y_formation),
        "BaseCourse": _rect(-b.pcc, -b.pcc, W + b.pcc, 0),
        **({"Kerb": _rect(-1500, b.y_road, -1200, b.y_road + b.kerb)} if b.kerb else {}),
    }


def level_box_gad(path: str | Path, b: LevelBox | None = None) -> dict:
    b = b or LevelBox()
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.dimstyles.new("GAD50", dxfattribs={"dimtxt": 2.5, "dimscale": 50, "dimgap": 0.6, "dimtad": 1})
    msp = doc.modelspace()
    for name, colour in (("STRUCTURE", 7), ("FILL", 3), ("LEVEL", 1), ("DIM", 2), ("TEXT", 7)):
        doc.layers.add(name, color=colour)
    handles = {}
    for name, pts in members(b).items():
        handles[name] = msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "FILL" if name in ("Cushion", "WearingCourse") else "STRUCTURE"}).dxf.handle
    W = b.width

    def dim(p1, p2, base, angle=0):
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle="GAD50", dxfattribs={"layer": "DIM"}).render()

    def level_line(y, words):
        msp.add_line((-2500, y), (W + 2500, y), dxfattribs={"layer": "LEVEL"})
        msp.add_text(f"{words} {b.level(y):.3f}", height=150, dxfattribs={"layer": "TEXT", "insert": (-2400, y + 40)})

    level_line(b.y_road, "ROAD LEVEL")
    level_line(b.y_formation, "FORMATION LEVEL")
    msp.add_text(f"TOP OF SLAB {b.level(b.y_top):.3f}", height=150, dxfattribs={"layer": "TEXT", "insert": (W + 600, b.y_top + 40)})
    dim((b.wall, b.bottom + 1000), (W - b.wall, b.bottom + 1000), (0, b.y_formation + 600))  # clear span
    dim((0, b.y_formation), (b.wall, b.y_formation), (0, b.y_formation + 1000))  # wall
    dim((W / 2, b.y_road), (W / 2, b.y_soffit), (W / 2 + 500, 0), 90)  # clear height, road to soffit
    dim((W, b.y_soffit), (W, b.y_top), (W + 500, 0), 90)  # top slab
    dim((W, 0), (W, b.bottom), (W + 500, 0), 90)  # bottom slab
    dim((W, b.y_top), (W, b.y_formation), (W + 500, 0), 90)  # cushion
    if b.overall_dim:
        dim((W, 0), (W, b.y_top), (W + 1200, 0), 90)  # overall height: bottom of box to top of slab, across the road level
    msp.add_text("150mm THK. WEARING COURSE", height=150, dxfattribs={"layer": "TEXT", "insert": (-2400, b.bottom - 400)})
    msp.add_text("SECTION A-A", height=175, dxfattribs={"layer": "TEXT", "insert": (W / 2, -b.pcc - 900)})
    doc.saveas(str(path))
    return {"path": str(path), "box": b, "handles": handles}


def level_box_answer(sm, uid: str, b: LevelBox, handles: dict, wearing_named: bool = True) -> dict:
    """The parts by region and the sizes an agent names, each between its two lines, with the road and formation levels as site inputs."""
    from dxf_autoparam.crossview import EMPTY_ANSWER
    from dxf_autoparam.topology import of

    u = sm.unit(uid)
    an, um = u.an, u.sub.units_mm
    topo = of(an)
    item_of = {it.handle: k for k, it in enumerate(an.drawing.items)}
    comps = [{"name": "Box", "type": "box", "level": "assembly", "regions": [], "confidence": 0.95}]
    for name, h in handles.items():
        k = item_of.get(h)
        if k is None:
            continue
        pts = an.drawing.items[k].pts
        box = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        best = min((r for r in topo.regions if sum(abs(a - c) for a, c in zip(r.bbox, box, strict=True)) < 1e-6 * max(1.0, box[2] - box[0])),
                   key=lambda r: (r.area, len(r.holes)), default=None)
        if best is not None:
            typ = {"BottomSlab": "slab", "TopSlab": "slab", "LeftWall": "wall", "RightWall": "wall", "WearingCourse": "wearing_course",
                   "Cushion": "fill", "BaseCourse": "footing", "Kerb": "kerb"}[name]
            comps.append({"name": name, "type": typ, "level": "component", "parent": "Box" if typ in ("slab", "wall") else None,
                          "regions": [best.id], "confidence": 0.9})

    def line(axis, at):
        return min((d for d in an.datums.values() if d.axis == axis), key=lambda d: abs(d.value * um - at)).id

    def size(name, axis, lo, hi):
        return {"name": name, "label": name, "component": "Box", "kind": "length", "from_datum": line(axis, lo), "to_datum": line(axis, hi),
                "value": abs(hi - lo)}

    params = [size("ClearSpan", "x", b.wall, b.width - b.wall), size("WallThickness", "x", 0, b.wall),
              size("ClearHeight", "y", b.y_road, b.y_soffit), size("TopSlabThickness", "y", b.y_soffit, b.y_top),
              size("BottomSlabThickness", "y", 0, b.bottom)]
    if wearing_named:
        params.append(size("WearingCourseThickness", "y", b.bottom, b.y_road))
    ans = copy.deepcopy(EMPTY_ANSWER)
    ans.update(structure_type="RCC box", components=comps, parameters=params,
               levels=[{"datum": line("y", b.y_road), "name": "RoadLevel", "role": "site_input"},
                       {"datum": line("y", b.y_formation), "name": "FormationLevel", "role": "site_input"}])
    return ans


def level_box_sheet(tmp_path: Path, b: LevelBox | None = None, wearing_named: bool = True, intent: bool = True):
    """(sheet, unit id, generator output) with the answer committed."""
    from dxf_autoparam.crossview import SheetModel

    b = b or LevelBox()
    g = level_box_gad(tmp_path / "level_box.dxf", b)
    sm = SheetModel.open(g["path"])
    uid = next(iter(sm.units))
    sm.commit_answer(uid, level_box_answer(sm, uid, b, g["handles"], wearing_named=wearing_named), intent=intent)
    return sm, uid, g


def lines_mm(sm, uid: str, values: dict | None = None) -> dict[str, float]:
    """Where each set-out line is (mm) at these values of the unit's own parameters."""
    u = sm.unit(uid)
    return {d: v * u.sub.units_mm for d, v in u.prog.datum_values(values or {}).items()}


__all__ = ["LevelBox", "level_box_answer", "level_box_gad", "level_box_sheet", "lines_mm", "members", "replace"]
