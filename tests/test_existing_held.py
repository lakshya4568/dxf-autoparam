"""Existing work and new work on one set-out chain.

A drawing of an extension draws the existing structure and the new one on the same set-out lines, so a size of the new work moves lines the existing
work stands on — through the chain of sizes that sets them out. The agent used to be REFUSED every size of the new work ("would move the existing
structure"), because the check moved every line of a held part; the sheet itself never applied the hold at all. Now the hold is real on the sheet, the check
asks what the hold leaves moving, and a size of existing work is a named, measured value that an explicit unlock makes an input.
"""

from __future__ import annotations

import pytest

from dxf_autoparam.ai.agent import Workbench
from dxf_autoparam.ai.context import SheetScope, fixed_lines, held_part_names
from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.intent import held_own_entities
from dxf_autoparam.plan_bench import Box, box_answer, box_gad
from dxf_autoparam.workspace import SheetSession

HELD = ("Foundation", "PitchingDetail")  # the existing work: kept as built


def extension(tmp_path):
    g = box_gad(tmp_path / "box.dxf", Box())
    sm = SheetModel.open(g["path"])
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    ans = box_answer(sm, uid, g["box"], g["handles"])
    for c in ans["components"]:
        if c["name"] in HELD:
            c["existing"], c["parametrize"] = True, False
    return sm, uid, ans, g


def held_entities(sm, uid) -> set[int]:
    u = sm.unit(uid)
    parts = u.prog.intent["parts"]
    held = {n for n, p in parts.items() if not p.parametrize}
    return {u.back[i] for i in held_own_entities(u.an, parts, held) if i < len(u.back)}


def line_at(an, axis: str, mm: float) -> str:
    u = an.drawing.units_mm
    return min((d for d in an.datums.values() if d.axis == axis), key=lambda d: abs(d.value * u - mm)).id


def test_a_size_of_the_new_work_is_accepted_although_the_chain_runs_through_existing_work(tmp_path):
    sm, uid, ans, _g = extension(tmp_path)
    bench = Workbench(sm.path, analysis=sm.pristine_analysis(uid), scope=SheetScope(sm, uid), start=ans)
    bench.validate()
    names = [p["name"] for p in ans["parameters"]]
    moved_held = 0
    for name in names:
        _info, failure = bench.binding_check(name)
        assert failure is None, (name, failure)
        # the scenario is not vacuous: moving this size DOES move lines of a part kept as drawn (the old check refused on exactly that)
        v0, v1 = bench.prog.datum_values(), bench.prog.datum_values({name: bench.prog.params[name].value + 1.0})
        old_fixed = fixed_lines(bench.prog, held_part_names(bench.answer))
        moved_held += any(d in old_fixed and abs(v1[d] - v0[d]) > 1e-12 for d in v1)
    assert moved_held, "at least one size of the new work moves a held line through the chain: that is what used to be refused"


def test_editing_the_new_work_leaves_the_existing_work_exactly_where_it_is(tmp_path):
    sm, uid, ans, g = extension(tmp_path)
    sm.commit_answer(uid, ans)
    u = sm.unit(uid)
    assert {c.name for c in u.prog.components if c.held} >= set(HELD), "the sheet holds what the answer keeps as drawn"
    held = held_entities(sm, uid)
    assert held, "there is existing work to protect"
    base = sm.regenerate(units={uid})
    foundation = next(i for i, it in enumerate(sm.dr.items) if it.handle == g["handles"]["Foundation"])
    assert foundation in held
    named = [n for n, p in u.prog.params.items() if p.source == "ai" and p.kind == "length"]
    assert {"ClearSpan", "OuterWall", "TopSlab"} <= set(named)
    edits = 0
    for name in named:
        for factor in (1.1, 0.9):
            r = sm.regenerate({f"{uid}.{name}": u.prog.params[name].value * factor}, units={uid})
            if r.errors:  # a value the drawing cannot take is said, not drawn
                continue
            moved = [i for i in held if any(abs(a[0] - b[0]) > 1e-6 or abs(a[1] - b[1]) > 1e-6 for a, b in zip(r.reg.pts[i], base.reg.pts[i], strict=True))]
            assert not moved, f"{name} x{factor} moved existing work: {moved[:3]}"
            assert any(i not in held for i in r.changed), f"{name} x{factor} changed nothing of the new work"
            edits += 1
    assert edits >= 4


def test_the_sheet_shows_no_held_entity_as_changed_before_any_edit(tmp_path):
    """The hold writes constants into the program; written with too few decimals they differ from the drawing by a hair and every held entity would
    show as modified (and orange in the page) with nothing touched."""
    sm, uid, ans, _g = extension(tmp_path)
    sm.commit_answer(uid, ans)
    r = sm.regenerate(units={uid})
    assert not set(r.changed) & held_entities(sm, uid), "a held entity differs from the drawing with no edit made"


def test_a_size_of_existing_work_is_a_named_measured_value_and_unlocking_makes_it_an_input(tmp_path):
    sm, uid, ans, g = extension(tmp_path)
    an = sm.unit(uid).an
    pts = next(it.pts for it in sm.dr.items if it.handle == g["handles"]["Foundation"])
    um = sm.unit(uid).sub.units_mm
    x0, x1 = min(p[0] for p in pts) * um, max(p[0] for p in pts) * um
    a, b = line_at(an, "x", x0), line_at(an, "x", x1)
    ans["parameters"].append({"name": "FoundationWidth", "label": "Foundation width", "component": "Foundation", "kind": "length", "from_datum": a, "to_datum": b,
                              "value": abs(x1 - x0), "recommended": False})
    sm.commit_answer(uid, ans)
    sheet = SheetSession()
    sheet.sm = sm
    info = sheet.unit(uid)
    row = next((m for m in info["measured"] if m["name"] == "FoundationWidth"), None)
    assert row is not None, "the size is kept: named, with the value the geometry measures"
    assert abs(row["value"] - abs(x1 - x0)) < 1e-6 and row["held"] and row["part"] == "Foundation" and row["existing"]
    assert "FoundationWidth" not in {p["name"] for p in info["params"]}, "and it is not an input while the part is held"
    shot = sm.regenerate(units={uid})
    sheet.edit("unlock_part", {"unit": uid, "part": "Foundation"})
    after = sheet.unit(uid)
    assert "FoundationWidth" in {p["name"] for p in after["params"]} and not any(m["name"] == "FoundationWidth" for m in after["measured"])
    now = sm.regenerate(units={uid})
    assert all(abs(p[0] - q[0]) < 1e-9 and abs(p[1] - q[1]) < 1e-9 for i in shot.reg.pts for p, q in zip(shot.reg.pts[i], now.reg.pts[i], strict=True)), \
        "unlocking moves no line: it makes the size an input"
    width = sm.unit(uid).prog.params["FoundationWidth"].value
    assert sm.apply({f"{uid}.FoundationWidth": width + 100}).ok, "and now the existing foundation can be edited, because a person asked"
    with pytest.raises(Exception, match="no part"):
        sm.unlock_part(uid, "NoSuchPart")


def test_a_size_that_follows_at_some_occurrences_is_bound_to_those_and_the_rest_are_said_to_stay(tmp_path):
    """Equal sizes are not one design input, and not every occurrence can follow a size: the cell on the right has both its lines set out by the
    agent's own formulas, so ClearSpan can drive the left one only. It used to be refused whole ('1 do, 1 do not'); now it is bound to the one that
    follows and says which stays its own size."""
    sm, uid, ans, _g = extension(tmp_path)
    row0 = next(p for p in ans["parameters"] if p["name"] == "ClearSpan")
    ans["parameters"] = [p for p in ans["parameters"] if p["name"] != "ClearSpan"]
    bench = Workbench(sm.path, analysis=sm.pristine_analysis(uid), scope=SheetScope(sm, uid), start=ans)
    an = bench.an
    cluster = an.clusters[row0["candidate"]]
    left, right = sorted(cluster.gaps, key=lambda gid: an.datums[an.gaps[gid].a].value)
    um = an.drawing.units_mm
    anchor, a, b = an.gaps[left].a, an.gaps[right].a, an.gaps[right].b
    for d in (a, b):
        bench.write("set_formula", {"line": d, "expr": f"{anchor} + {round((an.datums[d].value - an.datums[anchor].value) * um, 6)}"})
    bench.write("define_parameter", {"name": "ClearSpan", "part": "", "candidate": cluster.id, "occurrences": ["all"]})
    bench.validate()
    info, failure = bench.binding_check("ClearSpan")
    assert failure is None, failure
    assert info["drives"] == [left]
    assert len(info["left_as_drawn"]) == 1 and info["left_as_drawn"][0].startswith(f"{right} stays its own size")
    assert "your formula" in info["left_as_drawn"][0], "and says what holds it"
    row = next(q for q in bench.answer["parameters"] if q["name"] == "ClearSpan")
    assert row["occurrences"] == [left], "the binding is the occurrence that follows"
    # and when NOTHING follows it is still refused, with the lines and what sets them named
    bench2 = Workbench(sm.path, analysis=sm.pristine_analysis(uid), scope=SheetScope(sm, uid), start=ans)
    for d in (an.gaps[left].a, an.gaps[left].b, a, b):
        bench2.write("set_formula", {"line": d, "expr": f"{anchor} + {round((an.datums[d].value - an.datums[anchor].value) * um, 6)}"})
    bench2.write("define_parameter", {"name": "ClearSpan", "part": "", "candidate": cluster.id, "occurrences": ["all"]})
    bench2.validate()
    _info, failure = bench2.binding_check("ClearSpan")
    assert failure is None or failure["code"] == "DRIVE" and "your formula" in failure["cause"]
