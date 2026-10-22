"""Which side of a size stays, as a person chooses it — held on a box between two stated levels (road, formation), where most choices used to be refused.

Found on a real sheet: 137 of 183 start / centre / end choices were refused. A choice pushed every line beyond the size by the change, so any held level
beyond it (the formation above a slab) refused it even where a gap nothing holds (the earth cushion) lay between — the gap that gives when the slab
thickens; "centred" needed a line drawn at the middle of the size; and a refused choice left the formulas it had cleared on the way. Now: a push into a
held line is taken by the nearest gap nothing holds on the way (and refused only when every gap is held, naming them); centred without a drawn middle
is about the size's own middle; a refusal changes nothing and an acceptance is one undo step."""

from __future__ import annotations

import pytest
from levels_fixture import LevelBox, level_box_sheet, lines_mm

from dxf_autoparam.crossview import SheetError

# (size, side) → what must happen on the generated box: the road level is a site input under the clear height, the formation a site input above
# the earth cushion; nothing else is held.
EXPECT = {
    ("ClearHeight", "start"): "ok",  # the road stays, the top rises, the cushion gives
    ("ClearHeight", "end"): "RoadLevel",  # its own lower line is the road: refused, saying so
    ("ClearHeight", "centre"): "RoadLevel",
    ("TopSlabThickness", "start"): "ok",  # thickens upward into the cushion
    ("TopSlabThickness", "end"): "ClearHeight",  # the soffit would go down: the clear height holds it to the road
    ("TopSlabThickness", "centre"): "ClearHeight",
    ("BottomSlabThickness", "end"): "ok",  # its top stays, it thickens downward with the base course
    ("BottomSlabThickness", "start"): "WearingCourseThickness",  # upward it meets the wearing course under the road
    ("WearingCourseThickness", "end"): "ok",
    ("WallThickness", "start"): "ok",
    ("WallThickness", "centre"): "ok",  # no line is drawn in the middle of a wall: about its own middle
    ("WallThickness", "end"): "ok",
    ("ClearSpan", "centre"): "ok",
}


def chosen(tmp_path, name, side):
    sm, uid, _g = level_box_sheet(tmp_path, LevelBox(), intent=False)
    state = (sm.revision, len(sm.history), [(u, x.answer) for u, x in sm.units.items()])
    try:
        sm.anchor(f"{uid}.{name}", uid, side)
    except SheetError as exc:
        assert state == (sm.revision, len(sm.history), [(u, x.answer) for u, x in sm.units.items()]), "a refused choice changes nothing"
        return sm, uid, str(exc)
    assert sm.revision > state[0] and len(sm.history) == state[1] + 1, "an accepted choice is ONE step"
    return sm, uid, None


@pytest.mark.parametrize(("name", "side"), sorted(EXPECT))
def test_each_choice_is_taken_or_refused_for_a_reason_that_names_what_holds(tmp_path, name, side):
    _sm, _uid, refused = chosen(tmp_path, name, side)
    want = EXPECT[(name, side)]
    if want == "ok":
        assert refused is None, refused
    else:
        assert refused is not None and want in refused, f"refused, naming {want}: {refused}"


def test_a_refused_side_says_which_side_would_keep_what_holds(tmp_path):
    _sm, _uid, refused = chosen(tmp_path, "ClearHeight", "end")
    assert refused is not None and "its start (left / bottom) staying keeps what may not move" in refused, refused
    _sm, _uid, refused = chosen(tmp_path, "BottomSlabThickness", "start")
    assert refused is not None and "its end (right / top) staying" in refused, refused


def moved(sm, uid, name, by=100.0):
    u = sm.unit(uid)
    w0, w1 = lines_mm(sm, uid), lines_mm(sm, uid, {name: u.prog.params[name].value + by})
    return {d: round(w1[d] - w0[d], 6) for d in w0 if abs(w1[d] - w0[d]) > 1e-9}


def line_at(sm, uid, axis, at_mm):
    u = sm.unit(uid)
    return min((d for d in u.an.datums.values() if d.axis == axis), key=lambda d: abs(d.value * u.sub.units_mm - at_mm)).id


def test_the_cushion_gives_where_the_slab_thickens_upward(tmp_path):
    box = LevelBox()
    sm, uid, refused = chosen(tmp_path, "TopSlabThickness", "start")
    assert refused is None
    assert moved(sm, uid, "TopSlabThickness") == {line_at(sm, uid, "y", box.y_top): 100.0}, "the top of the slab rises; the formation level stays"
    reg = sm.regenerate({f"{uid}.TopSlabThickness": box.top + 300.0})
    assert reg.ok, reg.errors


def test_a_wall_centred_about_its_own_middle_moves_its_two_faces_apart_equally(tmp_path):
    box = LevelBox()
    sm, uid, refused = chosen(tmp_path, "WallThickness", "centre")
    assert refused is None
    got = moved(sm, uid, "WallThickness")
    outer, inner = line_at(sm, uid, "x", 0.0), line_at(sm, uid, "x", box.wall)
    assert got[outer] == pytest.approx(-50.0) and got[inner] == pytest.approx(50.0), "each face moves half, about the wall's own middle"
    assert sm.growth(f"{uid}.WallThickness")[0]["mode"] == "centre"


def test_a_refusal_says_every_gap_that_holds_on_the_way(tmp_path):
    _sm, _uid, refused = chosen(tmp_path, "TopSlabThickness", "end")
    assert "nothing between it and the size may give" in refused and "ClearHeight holds it" in refused
