"""Which side of a size stays, as a person chooses it — on a box between two stated levels (road, formation).

History. On a real sheet 137 of 183 start / centre / end choices were refused: a choice pushed every line beyond the size, so any held level beyond it
refused it. The first answer let the nearest gap nothing holds give (the earth cushion), which kept the level still but limited the change to the
size of that gap — a 50 mm gap under a formation then capped a clear height at +50 mm, and a +500 mm change inverted it. Now the chosen side moves
everything on it: a SITE level there follows the structure (said, with its new level), what lies between keeps its size, and nothing is shrunk to keep
a level still. A level only CHECKED against (a water level) still holds and is never set out from — a gap nothing holds gives for it; a part kept as
drawn, existing work and members running into each other still refuse, saying which side would keep them. A refusal changes nothing; an acceptance is
one undo step."""

from __future__ import annotations

import copy

import pytest
from levels_fixture import LevelBox, level_box_sheet, lines_mm

from dxf_autoparam.crossview import SheetError

# (size, side) → the site levels that follow on the generated box: the road level under the clear height, the formation above the earth cushion
EXPECT = {
    ("ClearHeight", "start"): {"FormationLevel"},  # the road stays, the top rises and the formation with it
    ("ClearHeight", "end"): {"RoadLevel"},  # its own lower line is the road: the road goes down
    ("ClearHeight", "centre"): {"RoadLevel", "FormationLevel"},
    ("TopSlabThickness", "start"): {"FormationLevel"},  # thickens upward, the cushion on it
    ("TopSlabThickness", "end"): {"RoadLevel"},  # the soffit goes down and the clear height under it holds: the road follows
    ("TopSlabThickness", "centre"): {"RoadLevel", "FormationLevel"},
    ("BottomSlabThickness", "end"): set(),  # its top stays: it thickens downward with the base course
    ("BottomSlabThickness", "start"): {"RoadLevel", "FormationLevel"},  # upward: everything above rises
    ("WearingCourseThickness", "end"): set(),
    ("WallThickness", "start"): set(),
    ("WallThickness", "centre"): set(),  # no line is drawn in the middle of a wall: about its own middle
    ("WallThickness", "end"): set(),
    ("ClearSpan", "centre"): set(),
}
RATE = {("ClearHeight", "centre"): 0.5, ("TopSlabThickness", "centre"): 0.5}


def sheet(tmp_path, check=(), held=()):
    """The box with its answer: levels in `check` only checked against, parts in `held` kept as drawn."""
    sm, uid, _g = level_box_sheet(tmp_path, LevelBox(), intent=False)
    if check or held:
        ans = copy.deepcopy(sm.unit(uid).answer)
        for lv in ans["levels"]:
            if lv["name"] in check:
                lv["role"] = "check_only"
        for c in ans["components"]:
            if c["name"] in held:
                c["parametrize"] = False
        sm.commit_answer(uid, ans, intent=False)
    return sm, uid


def chosen(sm, uid, name, side):
    state = (sm.revision, len(sm.history), [(u, x.answer) for u, x in sm.units.items()])
    try:
        res = sm.anchor(f"{uid}.{name}", uid, side)
    except SheetError as exc:
        assert state == (sm.revision, len(sm.history), [(u, x.answer) for u, x in sm.units.items()]), "a refused choice changes nothing"
        return None, str(exc)
    assert sm.revision > state[0] and len(sm.history) == state[1] + 1, "an accepted choice is ONE step"
    return res, None


def named_and_driving(sm, uid) -> dict[str, bool]:
    u = sm.unit(uid)
    out = {}
    for p in u.answer["parameters"]:
        prm = u.prog.params.get(p["name"])
        if prm is None or not prm.measures:
            out[p["name"]] = False
            continue
        a, b = prm.measures
        w0, w1 = lines_mm(sm, uid), lines_mm(sm, uid, {p["name"]: prm.value + 100.0})
        out[p["name"]] = abs(abs(w1[b] - w1[a]) - abs(w0[b] - w0[a]) - 100.0) < 1e-6
    return out


@pytest.mark.parametrize(("name", "side"), sorted(EXPECT))
def test_each_choice_is_taken_the_levels_on_the_moving_side_follow_and_no_named_value_is_lost(tmp_path, name, side):
    sm, uid = sheet(tmp_path)
    res, refused = chosen(sm, uid, name, side)
    assert refused is None, refused
    follow = {x["level"]: x for x in res.get("levels_follow", [])}
    assert set(follow) == EXPECT[(name, side)], follow
    for x in follow.values():
        assert abs(x["mm_per_mm"]) == pytest.approx(RATE.get((name, side), 1.0)), x
        assert "now follows the structure" in x["says"] and "RL" in x["says"]
    roles = {lv["name"]: lv["role"] for lv in sm.unit(uid).answer["levels"]}
    assert all(roles[n] == "derived" for n in follow) and all(roles[n] == "site_input" for n in roles if n not in follow), roles
    # the road it frees was the only level splitting the box's overall height: the wearing course named inside it used to come out worked out
    lost = [n for n, ok in named_and_driving(sm, uid).items() if not ok]
    assert not lost, f"named values that no longer drive their two lines: {lost}"


def moved(sm, uid, name, by=100.0):
    u = sm.unit(uid)
    w0, w1 = lines_mm(sm, uid), lines_mm(sm, uid, {name: u.prog.params[name].value + by})
    return {d: round(w1[d] - w0[d], 6) for d in w0 if abs(w1[d] - w0[d]) > 1e-9}


def line_at(sm, uid, axis, at_mm):
    u = sm.unit(uid)
    return min((d for d in u.an.datums.values() if d.axis == axis), key=lambda d: abs(d.value * u.sub.units_mm - at_mm)).id


def test_the_slab_thickens_upward_carrying_the_cushion_and_the_formation(tmp_path):
    box = LevelBox()
    sm, uid = sheet(tmp_path)
    _res, refused = chosen(sm, uid, "TopSlabThickness", "start")
    assert refused is None
    top, formation = line_at(sm, uid, "y", box.y_top), line_at(sm, uid, "y", box.y_formation)
    assert moved(sm, uid, "TopSlabThickness") == {top: 100.0, formation: 100.0}, "the cushion keeps its size; nothing shrinks to keep a level"
    r = sm.apply({f"{uid}.TopSlabThickness": box.top + 600.0})  # far past what the cushion's own size would have allowed
    assert r.ok, [f["message"] for f in r.failures]


def test_a_level_only_checked_against_holds_a_gap_nothing_holds_gives_and_nothing_is_set_out_from_it(tmp_path):
    box = LevelBox()
    sm, uid = sheet(tmp_path, check=("FormationLevel",))
    res, refused = chosen(sm, uid, "ClearHeight", "start")
    assert refused is None and not res.get("levels_follow"), res
    top, formation = line_at(sm, uid, "y", box.y_top), line_at(sm, uid, "y", box.y_formation)
    got = moved(sm, uid, "ClearHeight")
    assert got.get(top) == pytest.approx(100.0) and formation not in got, "the cushion gives under a level that is only checked"
    for side in ("end", "centre"):
        sm, uid = sheet(tmp_path, check=("FormationLevel",))
        _res, refused = chosen(sm, uid, "ClearHeight", side)
        assert refused is None, refused
        u = sm.unit(uid)
        assert all(formation not in names for d, e in u.prog.formulas.items() if d != formation
                   for names in [set(e.replace("-", " ").replace("+", " ").replace("*", " ").split())]), \
            {d: e for d, e in u.prog.formulas.items() if formation in e and d != formation}
        assert set(moved(sm, uid, "FormationLevel", by=0.5)) == {formation}, "a check value changed moves its own line, never the structure"


def test_a_part_kept_as_drawn_in_the_way_refuses_and_says_which_side_keeps_it(tmp_path):
    sm, uid = sheet(tmp_path, held=("Cushion",))
    _res, refused = chosen(sm, uid, "TopSlabThickness", "start")
    assert refused is not None and "held part (Cushion" in refused and "its end (right / top) staying" in refused and "keeps what may not move" in refused, refused
    sm, uid = sheet(tmp_path, held=("BaseCourse",))
    _res, refused = chosen(sm, uid, "BottomSlabThickness", "end")
    assert refused is not None and "its start (left / bottom) staying (its site levels follow)" in refused, refused
    _res, refused = chosen(sm, uid, "ClearHeight", "end")  # the box would go down into the base course kept as drawn
    assert refused is not None and "crosses" in refused and "BaseCourse" in refused, refused


def test_a_level_on_a_line_only_a_part_kept_as_drawn_uses_stays_an_input(tmp_path):
    sm, uid = sheet(tmp_path, held=("Cushion",))
    res, refused = chosen(sm, uid, "ClearHeight", "start")
    assert refused is None and not res.get("levels_follow"), res
    assert {lv["name"]: lv["role"] for lv in sm.unit(uid).answer["levels"]}["FormationLevel"] == "site_input"


def test_a_wall_centred_about_its_own_middle_moves_its_two_faces_apart_equally(tmp_path):
    box = LevelBox()
    sm, uid = sheet(tmp_path)
    _res, refused = chosen(sm, uid, "WallThickness", "centre")
    assert refused is None
    got = moved(sm, uid, "WallThickness")
    outer, inner = line_at(sm, uid, "x", 0.0), line_at(sm, uid, "x", box.wall)
    assert got[outer] == pytest.approx(-50.0) and got[inner] == pytest.approx(50.0), "each face moves half, about the wall's own middle"
    assert sm.growth(f"{uid}.WallThickness")[0]["mode"] == "centre"
