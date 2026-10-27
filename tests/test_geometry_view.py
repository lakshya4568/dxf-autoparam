"""What the agent reads of the geometry (ai.geometry): the view's own numbers, what lies on each line, and each axis as a ruler of its gaps.

A live run (7A, 2026-10-26) was given each line at its sheet coordinate (541 448 mm across) and each region as a width, a height and four line ids:
nothing said where a member is in the view, which level a line stands at, or which size sits between which lines, and the model guessed."""

from __future__ import annotations

from dxf_autoparam.ai.agent import overview
from dxf_autoparam.ai.geometry import geometry
from dxf_autoparam.ai.parametrize import prepare
from dxf_autoparam.plan_bench import Box, box_gad


def test_lines_and_regions_are_in_the_view_frame_and_each_axis_reads_as_a_ruler(tmp_path):
    b = Box(cells=1, span=3000.0, height=2500.0, plan=False, detail=False)
    g = box_gad(tmp_path / "box.dxf", b)
    an, base, *_ = prepare(g["path"])
    geo = geometry(an, base)
    assert geo["frame"]["x"].startswith("mm across from")
    across = [float(r[1].split()[0]) for r in geo["lines"] if r[0].startswith("x")]
    assert min(across) >= -b.width - 1 and max(across) <= b.width + 1, "x is measured within the view, not from the sheet's origin"
    rows = {r[0]: r for r in geo["regions"]}
    assert all(r[3].startswith("x ") and "; y " in r[3] for r in rows.values()), "each region says where it is in the frame"
    ruler = " ".join(geo["rulers"]["y"])
    assert f"—{b.bottom:g}" in ruler and f"—{b.top:g}" in ruler, "the vertical ruler is the section's stack: slab, opening, slab"
    assert "across several steps:" in ruler and f" {b.height:g}" in ruler.split("across several steps:")[1], "the opening, past the haunch lines in it, is said whole"


def test_the_overview_names_a_gap_its_value_where_the_context_has_one(tmp_path):
    g = box_gad(tmp_path / "box.dxf", Box(cells=1, plan=False, detail=False))
    an, base, *_ = prepare(g["path"])
    c = next(c for c in an.clusters.values() if round(c.value * an.drawing.units_mm) == 2500 and "y" in c.axes)
    gap = an.gaps[c.gaps[0]]
    ctx = {"named_values [name, mm, unit, between lines, kind]": [["ClearHeight", 2500.0, "mm", f"{gap.a}-{gap.b}", "length"]]}
    ov = overview(an, base, ctx)
    ruler = " ".join(ov[next(k for k in ov if k.startswith("rulers"))]["y"])
    assert "ClearHeight" in ruler and not any(k.startswith("lines [id, at mm") for k in ov), "the sheet's own coordinates are gone"


def test_zoom_view_takes_a_box_in_the_overview_frame(tmp_path):
    from dxf_autoparam.ai.geometry import Frame
    from dxf_autoparam.ai.run import Run, SheetBench
    from dxf_autoparam.workspace import SheetSession

    g = box_gad(tmp_path / "box.dxf", Box(cells=1, plan=False, detail=False))
    sheet = SheetSession(g["path"])
    sheet.get_pictures()
    uid = next(iter(sheet.sm.units))
    bench = SheetBench(Run(sheet, "R9", "look", {"kind": "drawing"}))
    res = bench.zoom_view(unit=uid, box_local=[-500, 0, 500, 1000])
    fr = Frame(sheet.sm.unit(uid).an)
    x0, y0 = fr.to_sheet(-500, 0)
    um = sheet.sm.unit(uid).sub.units_mm
    assert abs(res["box_mm"][0] - x0 * um) < 1 and abs(res["box_mm"][1] - y0 * um) < 1, (res["box_mm"], x0 * um, y0 * um)
