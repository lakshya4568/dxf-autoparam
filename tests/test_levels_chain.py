"""A structure that stands between stated levels is set out FROM them: the box under a road hangs from the road level — the wearing course, the
bottom slab and the courses under it below it, the clear height and the top slab above it — and what lies between the box and the next level up (an
earth cushion) is worked out. An overall dimension that runs across the road level is a sum of the two sides and follows them.

Found on a real sheet: its 3800 overall height (bottom of the box to its top, across the road level) was taken as an inside size, so the bottom slab was
set out from the TOP slab — raising the clear height with the road level held lifted the bottom slab, the base course and the fill with it, left the
3800 dimension reading 3800, and made the agent's WearingCourseThickness "worked out". The same chain is what the production rule engine computes for a
railway box (z_bot = bed level − wearing course − bottom slab). Held here on a generated box whose sizes are all parameters of the generator."""

from __future__ import annotations

import math

import pytest
from levels_fixture import LevelBox, level_box_sheet, lines_mm

from dxf_autoparam.display import _dim_ends


def line_at(sm, uid, axis, at_mm):
    u = sm.unit(uid)
    return min((d for d in u.an.datums.values() if d.axis == axis), key=lambda d: abs(d.value * u.sub.units_mm - at_mm)).id


def moves(sm, uid, name, by):
    u = sm.unit(uid)
    w0, w1 = lines_mm(sm, uid), lines_mm(sm, uid, {name: u.prog.params[name].value + by})
    return {d: round(w1[d] - w0[d], 6) for d in w0 if abs(w1[d] - w0[d]) > 1e-9}


OTHER = LevelBox(span=3000.0, wearing=75.0, clear=2500.0, top=300.0, bottom=350.0, cushion=600.0, kerb=225.0)


# The set-out itself (intent=False): the engine's own growth decisions (design intent) are a layer on top, and on a drawing whose intent cannot be
# decided they are not there to repair a wrong chain — the real sheet's could not.
@pytest.mark.parametrize("intent", [False, True])
@pytest.mark.parametrize("box", [LevelBox(), OTHER])
def test_the_clear_height_moves_only_what_is_above_the_road(tmp_path, box, intent):
    sm, uid, _g = level_box_sheet(tmp_path, box, intent=intent)
    got = moves(sm, uid, "ClearHeight", 500.0)
    soffit, top = line_at(sm, uid, "y", box.y_soffit), line_at(sm, uid, "y", box.y_top)
    assert got == {soffit: 500.0, top: 500.0}, "the soffit and the top of the slab rise; the road, the bottom slab and what is under it stay"


@pytest.mark.parametrize("intent", [False, True])
def test_the_wearing_course_is_an_input_and_the_bottom_slab_hangs_from_the_road(tmp_path, intent):
    box = LevelBox()
    sm, uid, _g = level_box_sheet(tmp_path, box, intent=intent)
    prog = sm.unit(uid).prog
    assert "WearingCourseThickness" in prog.params and prog.params["WearingCourseThickness"].source == "ai"
    floor, base = line_at(sm, uid, "y", box.bottom), line_at(sm, uid, "y", 0.0)
    assert moves(sm, uid, "WearingCourseThickness", 50.0) == {floor: -50.0, base: -50.0, line_at(sm, uid, "y", -box.pcc): -50.0}, \
        "a thicker wearing course lowers the bottom slab and what is under it; the road level holds"
    assert moves(sm, uid, "BottomSlabThickness", 50.0) == {base: -50.0, line_at(sm, uid, "y", -box.pcc): -50.0}, "the bottom slab thickens downward"


def test_the_overall_height_is_worked_out_and_its_dimension_follows(tmp_path):
    box = LevelBox()
    sm, uid, _g = level_box_sheet(tmp_path, box, intent=False)
    u = sm.unit(uid)
    overall = [p for p in u.prog.params.values() if p.kind == "length" and abs(p.value - box.y_top) < 1e-6]
    assert not overall, f"no input measures the overall height across the road level: {[p.name for p in overall]}"
    sr = sm.regenerate({f"{uid}.ClearHeight": box.clear + 500.0})
    assert sr.ok, sr.errors
    um = u.sub.units_mm
    dims = [it for it in u.sub.items if it.dxftype == "DIMENSION"]
    measured = {round(math.dist(*_dim_ends(it, it.pts)) * um): round(math.dist(*_dim_ends(it, sr.reg.pts.get(u.back[it.index], it.pts))) * um)
                for it in dims}
    assert measured[round(box.y_top)] == round(box.y_top) + 500, "the overall dimension reads the new overall height"
    assert measured[round(box.cushion)] == round(box.cushion) - 500, "the cushion to the formation level is what gives"


def test_a_kerb_on_the_road_follows_the_road_not_the_top_of_the_box(tmp_path):
    box = LevelBox()
    sm, uid, _g = level_box_sheet(tmp_path, box, intent=False)
    kerb_top = line_at(sm, uid, "y", box.y_road + box.kerb)
    assert kerb_top not in moves(sm, uid, "ClearHeight", 500.0) and kerb_top not in moves(sm, uid, "TopSlabThickness", 100.0)
    assert moves(sm, uid, "RoadLevel", 0.1).get(kerb_top) == pytest.approx(100.0), "it stands on the road: it goes where the road goes"


def test_without_a_stated_level_nothing_changes_in_how_the_box_is_set_out(tmp_path):
    """The rule speaks only of a level the structure is set out from: with no level the box is sized from inside as before."""
    from levels_fixture import level_box_answer, level_box_gad

    from dxf_autoparam.crossview import SheetModel

    box = LevelBox(kerb=0.0)
    g = level_box_gad(tmp_path / "free.dxf", box)
    sm = SheetModel.open(g["path"])
    uid = next(iter(sm.units))
    ans = level_box_answer(sm, uid, box, g["handles"])
    ans["levels"] = []
    sm.commit_answer(uid, ans)
    prog = sm.unit(uid).prog
    assert {"ClearHeight", "TopSlabThickness", "BottomSlabThickness"} <= set(prog.params)
    v0 = prog.datum_values()
    assert prog.datum_values({"ClearHeight": prog.params["ClearHeight"].value + 1}) != v0
