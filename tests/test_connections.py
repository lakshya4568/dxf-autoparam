"""How the parts of a unit meet (connections.py), and the contacts a change pulls apart — and, with the library on, what a part of its kind is known
to meet, against what it meets here.

The owner's rule: every joint of the drawing stays joined when a value changes, in every view, and a person can see which part meets which. Parts met
across a set-out line they share stay met whatever moves the line; entities that touched as drawn without one can come apart, and an edit says so.
Generated drawings (a 2-cell box, the level box), no model."""

from __future__ import annotations

import pytest
from levels_fixture import LevelBox, level_box_sheet
from test_intent_plan import box_sheet

from dxf_autoparam.connections import contacts, meets_of, torn
from dxf_autoparam.plan_bench import Box
from dxf_autoparam.regen import regenerate_program


@pytest.fixture(autouse=True)
def bridge_pack(monkeypatch):
    monkeypatch.setenv("AUTOPARAM_DOMAIN", "bridge")


def pairs(rows):
    return {(r["a"], r["how"], r["b"]) for r in rows}


def test_the_parts_of_a_box_meet_across_the_lines_they_share(tmp_path):
    sm, uid, _g = box_sheet(tmp_path, Box(cells=2))
    prog = sm.unit(uid).prog
    parts = prog.intent["parts"]
    got = pairs(contacts(prog, parts))
    walls = [n for n in parts if n.endswith("Wall") or n.startswith("MidWall")]
    assert walls and all((w, "on", "BottomSlab") in got for w in walls), "every wall stands on the bottom slab"
    assert all(("TopSlab", "on", w) in got for w in walls), "the top slab is on every wall"
    assert not {("LeftWall", "beside", "RightWall"), ("RightWall", "beside", "LeftWall")} & got, "parts a cell apart do not meet"
    said = meets_of(contacts(prog, parts), "BottomSlab")
    assert {m["how"] for m in said if m["part"] in walls} == {"under"}, "said from the slab's side: the walls are on it"


@pytest.mark.parametrize("name,factor", [("ClearSpan", 1.1), ("ClearSpan", 0.9), ("OuterWall", 1.1), ("TopSlab", 1.1), ("BottomSlab", 0.9)])
def test_a_change_pulls_nothing_apart(tmp_path, name, factor):
    sm, uid, _g = box_sheet(tmp_path, Box(cells=2))
    u = sm.unit(uid)
    vals = {**u.prog.defaults(), **sm._values_for(u, {})}
    assert name in vals, sorted(vals)
    r = regenerate_program(u.prog, {**vals, name: vals[name] * factor})
    assert torn(u.prog, r.pts) == []
    rep = sm.regenerate({f"{uid}.{name}": vals[name] * factor})
    assert rep.ok and not any("pulled them apart" in w for w in rep.warnings), rep.warnings


def test_a_contact_pulled_apart_is_found_and_named(tmp_path):
    """The check can fail: one wall's entity moved off what it touched (as a change that set it out from elsewhere would) is found, with its part."""
    from dxf_autoparam.coverage import _entity_parts

    sm, uid, _g = box_sheet(tmp_path, Box(cells=2))
    prog = sm.unit(uid).prog
    items = prog.analysis.drawing.items
    wall = next(i for i, ps in _entity_parts(prog).items() if "RightWall" in ps and items[i].role.value == "structural")
    r = regenerate_program(prog, prog.defaults())
    pts = dict(r.pts)
    pts[wall] = [(x + 5000.0 / prog.analysis.drawing.units_mm, y) for x, y in items[wall].pts]
    got = torn(prog, pts)
    assert got and all(wall in t["entities"] for t in got) and any(["RightWall"] in t["parts"] for t in got), got


def test_the_level_box_courses_meet_what_they_lie_on(tmp_path):
    sm, uid, _g = level_box_sheet(tmp_path, LevelBox(), intent=False)
    prog = sm.unit(uid).prog
    got = pairs(contacts(prog, prog.intent["parts"]))
    assert {("BottomSlab", "on", "BaseCourse"), ("Cushion", "on", "TopSlab"), ("WearingCourse", "on", "BottomSlab")} <= got, got
    assert not any("Kerb" in (a, b) for a, _h, b in got), "the kerb beside the road touches nothing of the box"


def test_with_the_library_a_part_says_what_such_a_part_is_known_to_meet(tmp_path):
    from dxf_autoparam import design_intent
    from dxf_autoparam.ai import domain
    from dxf_autoparam.ai.agent import Workbench
    from dxf_autoparam.ai.context import SheetScope
    from dxf_autoparam.viewimg import box_around

    sm, uid, _g = level_box_sheet(tmp_path, LevelBox(), intent=False)
    u = sm.unit(uid)
    wb = Workbench(sm.path, region=box_around([sm.layout.group(v).bbox for v in u.views], 0.0), start=design_intent.strip(u.answer), drawing=u.sub,
                   analysis=sm.pristine_analysis(uid), scope=SheetScope(sm, uid), pack=domain.active("bridge"))
    cov = wb.coverage()
    assert "WearingCourse on BottomSlab (line" in " | ".join(cov["joints"]), cov.get("joints")
    entry = cov["parts"].get("WearingCourse") or next(q for q in cov.get("parts_without_dimensions", []) if q["part"] == "WearingCourse")
    known = entry["knowledge"]["meets_as_known"]
    assert known[0]["how"] == "on" and known[0]["met"] == ["BottomSlab"], known
