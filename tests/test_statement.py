"""What the model states about how the views relate — a plan — held to the sheet by the engine.

The engine does not read the statement for meaning (the names are the model's own and nothing here knows a structure): it checks that every
unit, view, part and value named exists, that a binding a link claims is on the sheet, and it counts what the model did across views that the
plan leaves out."""

from __future__ import annotations

import copy

import ezdxf
import pytest
from test_crossview import two_views, view
from test_sheet import FIXTURES, built_sheet, rect, text

from dxf_autoparam.ai.statement import apply_plan, check_link, covered, gap_lines, group_facts, plan_gaps, plan_report
from dxf_autoparam.baseline import reset_drawing
from dxf_autoparam.crossview import EMPTY_ANSWER, SheetModel
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.sheet import segment


def part(name: str, level: str = "assembly") -> dict:
    return {"name": name, "type": "box", "level": level, "parent": None, "regions": [], "entities": [], "existing": False, "parametrize": True,
            "evidence": [], "description": "", "confidence": 0.9}


def size(name: str, candidate: str, value: float) -> dict:
    return {"name": name, "label": name, "component": "", "kind": "length", "candidate": candidate, "value": value}


def link(what: str, places: list[dict], bound_by: str = "noted_only", relation: str = "same_dimension", **kw) -> dict:
    return {"what": what, "kind": "dimension", "relation": relation, "appears_in": places, "bound_by": bound_by, **kw}


@pytest.fixture
def two(tmp_path):
    """Two views NOT drawn in line, each parametrized (a part and the 3000 opening they both state), not yet linked."""
    sm = SheetModel.open(str(two_views(tmp_path / "two.dxf")))
    ua, ub = sm.unit_of_view[view(sm, "SECTION A-A")], sm.unit_of_view[view(sm, "SIDE ELEVATION")]
    for uid, p in ((ua, part("Body")), (ub, part("Shell"))):
        sm.set_answer(uid, {**copy.deepcopy(EMPTY_ANSWER), "components": [p], "parameters": [size("OpeningWidth", "c3", 3000.0)]})
    return sm, ua, ub


def places(ua: str, ub: str, value: str | None = "OpeningWidth") -> list[dict]:
    return [{"unit": ua, "value": value}, {"unit": ub, "value": value}]


# ── a link that holds is kept, and undone with the step ──────────────────────────────────────────


def test_a_link_that_holds_is_kept_checked_and_undone_with_the_step(two):
    sm, ua, ub = two
    sm.share("OpeningWidth", [(ua, "c3"), (ub, "c3")])
    r = apply_plan(sm, "R1", {"summary": "one opening, two views", "links": [link("opening", places(ua, ub), "shared_value", shared_value="OpeningWidth")],
                              "assumptions": [{"text": "equal numbers are taken as different sizes unless a part is shared", "why": "conservative"}]})
    assert r["refused"] == [] and len(r["applied"]) == 3 and r["links"] == 1
    assert sm.stated_plan["run"] == "R1" and sm.stated_plan["links"][0]["appears_in"][0] == {"unit": ua, "view": "V01", "part": "", "value": "OpeningWidth"}
    rep = plan_report(sm, "R1")
    assert rep["stated"] and rep["links"][0]["holds"] and rep["gaps"]["unmentioned_shared"] == []
    assert sm.undo() and sm.stated_plan == {}  # one undoable step, like any other change of the sheet


def test_a_link_is_replaced_by_its_name_and_a_plan_belongs_to_its_run(two):
    sm, ua, ub = two
    apply_plan(sm, "R1", {"links": [link("opening", places(ua, ub), note="first")]})
    apply_plan(sm, "R1", {"links": [link("Opening ", places(ua, ub), note="second")]})  # same words, spacing and case aside: replaced, not doubled
    assert [x["note"] for x in sm.stated_plan["links"]] == ["second"]
    apply_plan(sm, "R2", {"summary": "a new run"})  # the plan of an earlier run is not carried over
    assert sm.stated_plan["run"] == "R2" and sm.stated_plan["links"] == []
    assert plan_report(sm, "R1")["stated"] is False


# ── every reference is checked against the sheet ─────────────────────────────────────────────────


@pytest.mark.parametrize("ref, fragment", [
    ({"unit": "U99", "value": "OpeningWidth"}, "no unit U99"),
    ({"view": "V99", "value": "OpeningWidth"}, "no view V99"),
    ({"unit": "U02", "view": "V01", "value": "OpeningWidth"}, "belongs to U01"),
    ({"unit": "U01"}, "name the part or the value"),
    ({"unit": "U01", "part": "Bodyy"}, "did you mean Body"),
    ({"unit": "U01", "value": "OpeningWidht"}, "did you mean OpeningWidth"),
    ({"part": "Body"}, "name the unit or the view"),
])
def test_a_reference_that_names_nothing_on_the_sheet_is_refused_with_what_exists(two, ref, fragment):
    sm, _ua, ub = two
    r = apply_plan(sm, "R1", {"links": [link("x", [ref, {"unit": ub, "value": "OpeningWidth"}])]})
    assert r["applied"] == [] and fragment in r["refused"][0]
    assert sm.stated_plan == {}  # nothing is kept when nothing holds
    assert r["refused_items"][0]["key"] == "plan:x"


def test_a_unit_nothing_was_parametrized_in_has_nothing_to_point_at(tmp_path):
    sm = SheetModel.open(str(two_views(tmp_path / "two.dxf")))
    r = apply_plan(sm, "R1", {"links": [link("x", [{"unit": "U01", "value": "A"}, {"unit": "U02", "value": "A"}])]})
    assert "not parametrized" in r["refused"][0]


def test_a_link_is_about_at_least_two_places(two):
    sm, ua, _ub = two
    r = apply_plan(sm, "R1", {"links": [link("alone", [{"unit": ua, "value": "OpeningWidth"}, {"unit": ua, "part": "Body"}])]})
    assert "at least two" in r["refused"][0]


def test_a_malformed_statement_is_refused_in_words_and_never_crashes_the_run(two):
    sm, _ua, _ub = two
    r = apply_plan(sm, "R1", {"summary": 7, "assumptions": ["just words", 3, {"text": "kept"}],
                              "links": ["junk", {"what": "x", "appears_in": ["u", 3, None], "bound_by": "noted_only", "shared_value": 5},
                                        {"what": "y", "appears_in": "nope", "bound_by": "noted_only", "evidence": "text"}]})
    assert len(r["refused"]) == 3 and "is an object" in r["refused"][0] and "a place is an object" in r["refused"][1]
    assert [a["text"] for a in sm.stated_plan["assumptions"]] == ["just words", "3", "kept"] and sm.stated_plan["summary"] == "7"


# ── what a refused link said can be stated anyway ────────────────────────────────────────────────


def test_a_refused_link_is_kept_with_the_places_it_named_and_covered_by_a_link_or_by_one_unit(two):
    sm, ua, ub = two
    r = apply_plan(sm, "R1", {"links": [link("claimed", places(ua, ub), "shared_value", shared_value="Nobody")]})  # no such shared value
    item = r["refused_items"][0]
    assert item["places"] == [[ua, ""], [ub, ""]]
    assert not covered(item["places"], sm.stated_plan.get("links", []))  # nothing in the plan relates the two views
    apply_plan(sm, "R1", {"links": [link("the same, in other words", places(ua, ub))]})
    assert covered(item["places"], sm.stated_plan["links"])  # now a kept link names both places
    assert not covered([[ua, ""], ["U99", ""]], sm.stated_plan["links"])  # a place no link names is not covered
    assert not covered([[ua, ""]], sm.stated_plan["links"])  # one place says nothing about how places relate
    assert covered([[ua, "V01"], [ua, "V02"]], [])  # two views of one unit are held together by the sheet itself


# ── a binding a link claims must be on the sheet ─────────────────────────────────────────────────


def test_a_shared_value_that_is_not_there_or_not_in_every_unit_is_not_claimed(two):
    sm, ua, ub = two
    missing = apply_plan(sm, "R1", {"links": [link("opening", places(ua, ub), "shared_value", shared_value="OpeningWidth")]})
    assert "no shared value 'OpeningWidth'" in missing["refused"][0] and "noted_only" in missing["refused"][0]
    sm.share("OnlyHere", [(ua, "c1")])  # shared by one unit only
    partial = apply_plan(sm, "R1", {"links": [link("wall", [{"unit": ua, "value": "OnlyHere"}, {"unit": ub, "value": "OpeningWidth"}], "shared_value", shared_value="OnlyHere")]})
    assert "is shared by" in partial["refused"][0] and ub in partial["refused"][0]
    sm.share("OpeningWidth", [(ua, "c3"), (ub, "c3")])
    by_part = apply_plan(sm, "R1", {"links": [link("opening", [{"unit": ua, "value": "OpeningWidth"}, {"unit": ub, "part": "Shell"}], "shared_value", shared_value="OpeningWidth")]})
    assert by_part["refused"] == []  # a part of the unit is fine: the binding is the unit's
    not_a_value = check_link(sm, {**sm.stated_plan["links"][0], "appears_in": [{"unit": ua, "value": "OpeningWidth", "part": "", "view": "V01"},
                                                                         {"unit": ub, "value": "Shell", "part": "", "view": "V02"}]})
    assert not_a_value and "has no value 'Shell'" in not_a_value[0]


def test_views_in_projection_are_one_unit_and_a_relation_between_views_must_be_on_the_sheet(tmp_path):
    from test_crossview import mini_gad

    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    one = next(k for k, u in sm.units.items() if len(u.views) == 2)
    other = next(k for k in sm.units if k != one)
    for uid in (one, other):
        sm.set_answer(uid, {**copy.deepcopy(EMPTY_ANSWER), "components": [part("Wall" if uid == one else "SideWall")], "parameters": [size("WallThickness", "c0", 300.0)]})
    v1, v2 = sm.units[one].views
    inside = apply_plan(sm, "R1", {"links": [link("wall", [{"view": v1, "part": "Wall"}, {"view": v2, "part": "Wall"}], "projection", relation="same_component")]})
    assert inside["refused"] == [], inside  # the two views of one unit are drawn in projection
    across = apply_plan(sm, "R1", {"links": [link("wall in detail", [{"unit": one, "part": "Wall"}, {"unit": other, "part": "SideWall"}], "projection")]})
    assert "are one unit" in across["refused"][0]
    unrelated = apply_plan(sm, "R1", {"links": [link("wall in detail", [{"unit": one, "part": "Wall"}, {"unit": other, "part": "SideWall"}], "view_relation", relation="detail_of")]})
    assert "not related on the sheet" in unrelated["refused"][0]
    sm.relations.append({"a": sm.units[other].views[0], "b": v1, "relation": "detail_of", "evidence": []})
    related = apply_plan(sm, "R1", {"links": [link("wall in detail", [{"unit": one, "part": "Wall"}, {"unit": other, "part": "SideWall"}], "view_relation", relation="detail_of")]})
    assert related["refused"] == [] and related["links"] == 2


def test_a_link_that_held_is_asked_again_and_fails_when_the_sheet_no_longer_holds_it(two):
    sm, ua, ub = two
    sm.share("OpeningWidth", [(ua, "c3"), (ub, "c3")])
    apply_plan(sm, "R1", {"links": [link("opening", places(ua, ub), "shared_value", shared_value="OpeningWidth")]})
    sm.unshare("OpeningWidth")
    rep = plan_report(sm, "R1")
    assert not rep["links"][0]["holds"] and "no shared value" in rep["links"][0]["why"]


# ── what the plan leaves out is counted, not decided ─────────────────────────────────────────────


def test_what_the_model_did_across_views_that_the_plan_leaves_out_is_listed(two):
    sm, ua, ub = two
    sm.share("OpeningWidth", [(ua, "c3"), (ub, "c3")])
    sm.relations.append({"a": "V01", "b": "V02", "relation": "same_structure", "evidence": []})
    sm.set_answer(ua, {**copy.deepcopy(sm.units[ua].answer), "components": [part("Body"), part("Footing")], "parameters": [
        *sm.units[ua].answer["parameters"], size("PierWidth", "c1", 3000.0)]})
    sm.set_answer(ub, {**copy.deepcopy(sm.units[ub].answer), "components": [part("Body"), part("Footing")], "parameters": [
        *sm.units[ub].answer["parameters"], size("PierWidth", "c0", 3000.0)]})
    gaps = plan_gaps(sm, {})
    assert gaps["unmentioned_shared"] == ["OpeningWidth"]
    assert gaps["unmentioned_relations"] == [{"a": "V01", "b": "V02", "relation": "same_structure"}]
    assert {"name": "PierWidth", "units": [ua, ub], "value_mm": 3000.0} in gaps["same_value_name_in_several_units"]
    assert {p["name"] for p in gaps["same_part_name_in_several_units"]} == {"Body", "Footing"}
    lines = gap_lines(gaps)
    assert len(lines) == 4 and "OpeningWidth" in lines[0] and "PierWidth" in lines[2]
    # saying it closes it: the shared value, the relation (by a link between the two units) and the parts
    apply_plan(sm, "R1", {"links": [link("opening", places(ua, ub), "shared_value", shared_value="OpeningWidth"),
                                    link("body", [{"unit": ua, "part": "Body"}, {"unit": ub, "part": "Body"}], "view_relation", relation="same_component"),
                                    link("footing", [{"unit": ua, "part": "Footing"}, {"unit": ub, "part": "Footing"}], "view_relation", relation="same_component"),
                                    link("pier", [{"unit": ua, "value": "PierWidth"}, {"unit": ub, "value": "PierWidth"}], "noted_only")]})
    assert gap_lines(plan_gaps(sm, sm.stated_plan)) == []


# ── the plan is saved with the project, and a reset takes it back ────────────────────────────────


def test_the_plan_is_saved_with_the_project_and_a_reset_clears_it(two, tmp_path):
    sm, ua, ub = two
    apply_plan(sm, "R1", {"summary": "s", "links": [link("opening", places(ua, ub))]})
    sm.save(str(tmp_path / "p.json"))
    again = SheetModel.load(str(tmp_path / "p.json"))
    assert again.stated_plan["links"][0]["what"] == "opening" and again.stated_plan["summary"] == "s"
    reset_drawing(sm)
    assert sm.stated_plan == {}
    assert sm.undo() and sm.stated_plan["summary"] == "s"  # a reset is never a point of no return


# ── groups that are not views: what they hold, and a doubt where they hold a view's content ──────


def test_a_table_that_holds_a_views_content_is_doubted_and_a_real_table_is_not(tmp_path):
    sm = SheetModel.open(str(built_sheet(tmp_path / "sheet.dxf")))
    tables = [g for g in sm.layout.groups if g.kind == "table"]
    assert tables and all("doubt" not in f for f in group_facts(sm) if f["kind"] == "table")
    g = tables[0]
    g.counts = {**g.counts, "geometry": 139, "texts": 14, "dimensions": 29, "curves": 8}  # the content of a drawn view
    doubted = next(f for f in group_facts(sm) if f["id"] == g.id)
    assert "taken for a table" in doubted["doubt"] and doubted["drawn"] == 139 and doubted["dimensions"] == 29
    assert all(f["kind"] != "view" for f in group_facts(sm))


def test_a_group_said_to_be_a_view_gets_a_unit_of_its_own_and_takes_no_other_units_name(tmp_path):
    sm = SheetModel.open(str(built_sheet(tmp_path / "sheet.dxf")))
    before = set(sm.units)
    table = next(g for g in sm.layout.groups if g.kind == "table")
    assert table.id.startswith("T")
    sm.set_view(table.id, kind="view", name="A DRAWN THING")
    assert set(sm.units) == before | {"U" + table.id}  # UT01 — never "U01", which is the unit of V01
    assert sm.unit_of_view[table.id] == "U" + table.id and all(sm.unit_of_view[v] in before for v in sm.unit_of_view if v != table.id)


# ── the segmenter: a table has no dimensions, a drawn view does ──────────────────────────────────


def grid(msp, with_dims: bool) -> None:
    for k in range(6):
        msp.add_line((0, 1000 * k), (9000, 1000 * k))
    for x in (0, 3000, 6000, 9000):
        msp.add_line((x, 0), (x, 5000))
    for r in range(5):
        for c in range(3):
            text(msp, f"{r}{c}", 300 + 3000 * c, 300 + 1000 * r, 250)
    if with_dims:
        for k in range(3):
            msp.add_linear_dim(base=(0, 6000 + 800 * k), p1=(0, 5000), p2=(3000 * (k + 1), 5000), dxfattribs={"layer": "DIM"}).render()


@pytest.mark.parametrize("with_dims, kind", [(False, "table"), (True, "view")])
def test_ruled_words_with_dimensions_are_a_view_not_a_table(tmp_path, with_dims, kind):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    rect(msp, -3000, -3000, 40000, 20000, "BORDER")
    grid(msp, with_dims)
    p = tmp_path / "grid.dxf"
    doc.saveas(p)
    dr, _ = read_dxf(str(p))
    lay = segment(dr)
    biggest = max((g for g in lay.groups if g.kind in ("view", "table")), key=lambda g: len(g.items))
    assert biggest.kind == kind, (biggest.kind, biggest.counts)


@pytest.mark.skipif(not (FIXTURES / "gad_ezdxf_a.dxf").exists(), reason="aagento-bridge fixtures not present")
def test_the_real_sheets_keep_their_tables():
    dr, _ = read_dxf(str(FIXTURES / "gad_ezdxf_b.dxf"))
    lay = segment(dr)
    assert {g.name for g in lay.groups if g.kind == "table"} == {"HYDRAULIC TABLE", "TRACK STRUCTURE"}
