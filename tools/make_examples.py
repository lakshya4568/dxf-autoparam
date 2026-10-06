"""Example drawings for the demo and the tests (inputs, not engine code).

  examples/*.dxf from the library fixtures (each a different structure family), plus
  three_cell_box_lines.dxf: a triple-cell box drawn the untidy way — separate LINE
  entities only, no closed outlines, no hatching — with chain + overall dimensions and
  a haunch note, the way many hand-drafted GADs arrive.

    uv run python tools/make_examples.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "fixtures" / "library" / "dxf"
OUT = ROOT / "examples"

COPY = {
    "ir_box_culvert_section.dxf": "two_cell_box_section.dxf",
    "ir_rcc_box_half_section.dxf": "rcc_box_half_section_half_elevation.dxf",
    "ir_girder_deck_section.dxf": "girder_deck_section.dxf",
    "ir_deck_slab_section.dxf": "deck_slab_section.dxf",
    "ir_pier_elevation.dxf": "pier_elevation.dxf",
    "ir_retaining_wall_section.dxf": "retaining_wall_section.dxf",
    "ir_well_foundation_section.dxf": "well_foundation_section.dxf",
}


def three_cell_box(path: Path, cells: int = 3, span: float = 2500, height: float = 2000, wall: float = 300,
                   mid: float = 250, top: float = 300, base: float = 350, haunch: float = 150, pcc: float = 150, proj: float = 150) -> None:
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    for name, lt in (("STRUCTURE", "Continuous"), ("CENTRE", "CENTER"), ("DIM", "Continuous"), ("TEXT", "Continuous")):
        doc.layers.add(name, linetype=lt)
    msp = doc.modelspace()
    L = lambda a, b: msp.add_line(a, b, dxfattribs={"layer": "STRUCTURE"})
    W = 2 * wall + cells * span + (cells - 1) * mid
    H = base + height + top
    # outer outline, line by line
    for a, b in (((0, 0), (W, 0)), ((W, 0), (W, H)), ((W, H), (0, H)), ((0, H), (0, 0))):
        L(a, b)
    # each cell, with four haunches, as separate lines
    x = wall
    for _ in range(cells):
        x0, x1, y0, y1, h = x, x + span, base, base + height, haunch
        pts = [(x0 + h, y0), (x1 - h, y0), (x1, y0 + h), (x1, y1 - h), (x1 - h, y1), (x0 + h, y1), (x0, y1 - h), (x0, y0 + h)]
        for i in range(len(pts)):
            L(pts[i], pts[(i + 1) % len(pts)])
        x = x1 + mid
    # PCC course below, projecting both sides
    for a, b in (((-proj, 0), (-proj, -pcc)), ((-proj, -pcc), (W + proj, -pcc)), ((W + proj, -pcc), (W + proj, 0)), ((W + proj, 0), (W, 0)), ((0, 0), (-proj, 0))):
        L(a, b)
    msp.add_line((W / 2, -pcc - 400), (W / 2, H + 400), dxfattribs={"layer": "CENTRE"})
    # chain dimensions + overall, and a note
    dims = [(0, wall)]
    x = wall
    for k in range(cells):
        dims.append((x, x + span))
        x += span
        if k < cells - 1:
            dims.append((x, x + mid))
            x += mid
    dims.append((x, x + wall))
    for a, b in dims:
        msp.add_linear_dim(base=(a, H + 600), p1=(a, H), p2=(b, H), dxfattribs={"layer": "DIM"}).render()
    msp.add_linear_dim(base=(0, H + 1100), p1=(0, H), p2=(W, H), dxfattribs={"layer": "DIM"}).render()
    for a, b in ((0, base), (base, base + height), (base + height, H)):
        msp.add_linear_dim(base=(W + 700, a), p1=(W, a), p2=(W, b), angle=90, dxfattribs={"layer": "DIM"}).render()
    msp.add_text(f"HAUNCH {haunch:.0f} X {haunch:.0f}", height=100, dxfattribs={"layer": "TEXT"}).set_placement((wall + 300, base + 250), align=TextEntityAlignment.BOTTOM_LEFT)
    msp.add_text(f"{cells} CELL BOX {span / 1000:.3f} X {height / 1000:.3f} m", height=150, dxfattribs={"layer": "TEXT"}).set_placement((W / 2, -pcc - 700), align=TextEntityAlignment.MIDDLE_CENTER)
    doc.saveas(path)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for src, dst in COPY.items():
        if (LIB / src).exists():
            shutil.copy(LIB / src, OUT / dst)
    three_cell_box(OUT / "three_cell_box_lines.dxf")
    print("\n".join(sorted(p.name for p in OUT.glob("*.dxf"))))


if __name__ == "__main__":
    main()
