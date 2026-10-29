"""A person's choice of the side that stays is never refused for a site level in its way: the level follows the structure (its line moves with the
side that moves, its RL note says the new level) and the choice says so. What still refuses is what cannot give — two members running into each
other, a part kept as drawn, existing work. A crossing with an entity no part owns is said, not refused: the engine cannot tell a detail that should
follow from something the member must not reach.

Found on a real sheet: ClearHeight's three sides were refused in both its views ("y6 is set by a site level"), a plan's width was "pinned by the
road level" of the elevation drawn above it, and a side chosen for a span froze the wall beside it at its drawn thickness. Generated drawings."""

from __future__ import annotations

import copy

import ezdxf
import pytest
from levels_fixture import LevelBox, level_box_sheet, lines_mm
from test_crossview import mini_gad
from test_intent_plan import FOLLOW_ALL, box_sheet

from dxf_autoparam.crossview import EMPTY_ANSWER, SheetModel
from dxf_autoparam.program import names_in


@pytest.fixture(autouse=True)
def bridge_pack(monkeypatch):
    monkeypatch.setenv("AUTOPARAM_DOMAIN", "bridge")


def level_line(sm, uid: str, name: str) -> str:
    return next(lv["datum"] for lv in sm.unit(uid).answer["levels"] if lv["name"] == name)


def at(sm, uid: str, line: str) -> float:
    u = sm.unit(uid)
    return lines_mm(sm, uid, {**u.prog.defaults(), **sm._values_for(u, {})})[line]


@pytest.mark.parametrize("mode,road,formation", [("start", 0.0, 300.0), ("end", -300.0, 0.0), ("centre", -150.0, 150.0)])
def test_every_side_is_taken_and_the_levels_on_the_side_that_moves_follow(tmp_path, mode, road, formation):
    b = LevelBox()
    sm, uid, _g = level_box_sheet(tmp_path, b)
    yr, yf = level_line(sm, uid, "RoadLevel"), level_line(sm, uid, "FormationLevel")
    r0, f0 = at(sm, uid, yr), at(sm, uid, yf)
    res = sm.anchor("ClearHeight" if "ClearHeight" in {p.name for p in sm.shared.values()} else f"{uid}.ClearHeight", uid, mode)
    follow = {x["level"] for x in res.get("levels_follow", [])}
    assert follow == ({"FormationLevel"} if mode == "start" else {"RoadLevel"} if mode == "end" else {"RoadLevel", "FormationLevel"})
    assert all("now follows the structure" in x["says"] for x in res["levels_follow"])
    r = sm.apply({f"{uid}.ClearHeight": b.clear + 300.0})
    assert r.ok, [f["message"] for f in r.failures]
    assert at(sm, uid, yr) - r0 == pytest.approx(road) and at(sm, uid, yf) - f0 == pytest.approx(formation)


def test_a_plan_under_its_section_is_set_out_on_its_own_never_from_the_section_s_level(tmp_path):
    path = mini_gad(tmp_path / "mini.dxf")
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    msp.add_line((-800, 300), (3800, 300))  # the road level, on the top of the bottom slab of the section
    msp.add_text("ROAD LEVEL 100.300", height=150, dxfattribs={"insert": (-800, 340)})
    doc.saveas(path)
    sm = SheetModel.open(path)
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    u = sm.unit(uid)
    an = u.an
    _section, plan = sorted(u.views, key=lambda v: -sm.layout.group(v).bbox[1])
    y_road = min((d for d in an.datums.values() if d.axis == "y"), key=lambda d: abs(d.value * u.sub.units_mm - 300)).id
    ans = copy.deepcopy(EMPTY_ANSWER)
    ans["levels"] = [{"datum": y_road, "name": "RoadLevel", "role": "site_input"}]
    sm.commit_answer(uid, ans, intent=False)
    prog = sm.unit(uid).prog
    plan_lines = [d for d, vs in an.datum_views.items() if vs == [plan] and d in prog.formulas]
    assert plan_lines, an.datum_views
    assert all("RoadLevel" not in names_in(prog.formulas[d]) for d in plan_lines), {d: prog.formulas[d] for d in plan_lines}


@pytest.mark.parametrize("mode", ["start", "centre", "end"])
def test_a_side_chosen_for_a_span_keeps_the_wall_beside_it_at_its_value_not_its_drawn_size(tmp_path, mode):
    b = LevelBox()
    sm, uid, _g = level_box_sheet(tmp_path, b)
    assert sm.apply({f"{uid}.WallThickness": b.wall + 130.0}).ok
    sm.anchor(f"{uid}.ClearSpan", uid, mode)
    u = sm.unit(uid)
    vals = {**u.prog.defaults(), **sm._values_for(u, {})}
    v = lines_mm(sm, uid, vals)
    for name, want in (("ClearSpan", b.span), ("WallThickness", b.wall + 130.0)):
        a, c = u.prog.params[name].measures
        assert abs(v[c] - v[a]) == pytest.approx(want), f"{name} measures {abs(v[c] - v[a])}, not {want}"


def test_a_crossing_with_an_entity_no_part_owns_is_said_and_one_between_two_parts_refuses(tmp_path, monkeypatch):
    import dxf_autoparam.coverage as C

    sm, uid, g = box_sheet(tmp_path)
    sm.apply_plan(uid, {"instruction": "Change the clear span to 3600, the left side stays fixed. " + FOLLOW_ALL})
    r = sm.apply({f"{uid}.OuterWall": 900.0})  # the bottom slab grows into the pitching detail the instruction keeps
    clash = [f for f in r.failures if f["check"] == "CLASH"]
    assert not r.ok and clash and all(f["kind"] == "invalid_edit" for f in clash), "two parts running into each other: refused"
    real = C._entity_parts
    pitching = {i for it in sm.unit(uid).sub.items if it.handle == g["handles"]["PitchingDetail"] for i in [it.index]}

    def without_the_detail(prog):  # the same drawing with the detail owned by no part
        return {i: ps for i, ps in real(prog).items() if i not in pitching}

    monkeypatch.setattr(C, "_entity_parts", without_the_detail)
    r = sm.apply({f"{uid}.OuterWall": 900.0})
    assert r.ok, [f["message"] for f in r.failures]
    assert any("belongs to no part" in w for w in r.warnings), r.warnings


def test_a_refused_side_is_a_question_tried_for_real_and_asking_changes_nothing(tmp_path):
    # a person chose "centred" for a span on a real sheet, was refused with a page of checks, and had no way on: the refusal is now a question —
    # what stood in the way, and the ways out the engine tried on the whole sheet (only what holds can be chosen)
    import json

    sm, uid, _g = box_sheet(tmp_path)
    holds = sm.anchor_options(f"{uid}.ClearSpan", uid, "start")
    assert holds["refused"] == "" and holds["notes"] == ["it holds as asked: nothing stands in the way"]
    before = (sm.revision, len(sm.history), json.dumps(sm.unit(uid).answer, sort_keys=True))
    o = sm.anchor_options(f"{uid}.ThkY1", uid, "centre")  # a size the side cannot be chosen for (it is worked out from other inputs there)
    assert o["refused"] and isinstance(o["blocked"], list)
    assert all({"id", "title", "mode", "decisions", "keep_as_drawn"} <= set(c) for c in o["choices"])
    assert all(r["why"] for r in o["rejected"]), "what did not hold says why"
    assert (sm.revision, len(sm.history), json.dumps(sm.unit(uid).answer, sort_keys=True)) == before, "asking changes nothing"


def test_entities_kept_where_they_are_drawn_stay_when_the_value_moves_and_one_undo_takes_it_back(tmp_path):
    from dxf_autoparam.cadjson import entity_id
    from dxf_autoparam.crossview import KEPT_AS_DRAWN

    sm, uid, g = box_sheet(tmp_path)
    items = sm.unit(uid).sub.items
    pit = next(it for it in items if it.handle == g["handles"]["PitchingDetail"])
    drawn = list(pit.pts)
    depth = len(sm.history)
    sm.anchor(f"{uid}.ClearSpan", uid, "end", keep_as_drawn=[entity_id(pit)])
    assert any(c["name"] == KEPT_AS_DRAWN and entity_id(pit) in c["entities"] for c in sm.unit(uid).answer["components"])
    assert not sm.preview({f"{uid}.ClearSpan": 3400.0}).errors
    from dxf_autoparam.regen import regenerate_program

    now = regenerate_program(sm.unit(uid).prog, {"ClearSpan": 3400.0}).pts[pit.index]
    assert [tuple(p) for p in now] == pytest.approx([tuple(p) for p in drawn]), "kept where it is drawn while the span grows"
    assert len(sm.history) == depth + 1, "one step"
    sm.undo()
    assert not any(c["name"] == KEPT_AS_DRAWN for c in sm.unit(uid).answer.get("components", []))


def test_members_of_two_parts_in_each_other_s_way_come_back_to_the_agent_as_a_question_for_the_person(tmp_path):
    from dxf_autoparam.refusal import person_question

    sm, uid, _g = box_sheet(tmp_path)
    sm.apply_plan(uid, {"instruction": "Change the clear span to 3600, the left side stays fixed. " + FOLLOW_ALL})
    r = sm.apply({f"{uid}.OuterWall": 900.0})  # the bottom slab grows into the pitching detail
    q = person_question(r.failures)
    assert q and "PitchingDetail" in q["text"] and len(q["options"]) == 4
    assert any(o.endswith("follows the change") for o in q["options"]) and any(o.endswith("stays where it is drawn") for o in q["options"])
    assert person_question([]) is None


def test_existing_work_dismantled_where_the_new_work_crosses_it_no_longer_stands_in_the_way(tmp_path):
    from dxf_autoparam.cadjson import entity_id
    from dxf_autoparam.crossview import DISMANTLED_BY_PERSON

    sm, uid, g = box_sheet(tmp_path)
    sm.apply_plan(uid, {"instruction": "Change the clear span to 3600, the left side stays fixed. " + FOLLOW_ALL})
    assert not sm.apply({f"{uid}.OuterWall": 900.0}).ok, "the bottom slab runs into the pitching detail"
    pit = next(it for it in sm.unit(uid).sub.items if it.handle == g["handles"]["PitchingDetail"])
    drawn = list(pit.pts)
    sm.anchor(f"{uid}.ClearSpan", uid, "start", dismantle=[entity_id(pit)])
    assert any(c["name"] == DISMANTLED_BY_PERSON and c["type"] == "dismantled" for c in sm.unit(uid).answer["components"])
    r = sm.apply({f"{uid}.OuterWall": 900.0})
    assert r.ok, [f["message"] for f in r.failures]
    from dxf_autoparam.regen import regenerate_program

    assert regenerate_program(sm.unit(uid).prog, {"OuterWall": 900.0}).pts[pit.index] == pytest.approx(drawn), "dismantled work stays as drawn"
