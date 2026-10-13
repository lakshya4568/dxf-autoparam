"""Instruction-guided, assembly-aware parametrization — no model calls (the agent is scripted).

A box culvert drawn as separate members (walls, slabs, haunches), its foundation, a plan view in projection with wing
walls, and an unrelated detail is GENERATED from known sizes, so the intended geometry after any change is known
exactly: the generator itself, run at the new size with the accepted anchor. Every test measures the regenerated
sheet against it (or against the plan's promises), member by member — never a bounding box."""

from __future__ import annotations

import copy
import json
import math

import ezdxf
import pytest
from test_agent import ScriptedGemini, call
from test_crossview import dim_labels, mini_gad

from dxf_autoparam.ai.sheet_ai import parametrize_unit
from dxf_autoparam.crossview import EMPTY_ANSWER, SheetError, SheetModel
from dxf_autoparam.intent import _boxes, _geometry, classify
from dxf_autoparam.plan import build_plan, plan_errors_at, read_instruction, verify_plan, vocabulary
from dxf_autoparam.plan_bench import Box, _expected_points, box_answer, box_gad

FOLLOW_ALL = "Wing walls follow the box. The foundation follows the box. Do not modify the unrelated pitching detail."


def box_sheet(tmp_path, b: Box | None = None, names=None, edit=None):
    g = box_gad(tmp_path / "box.dxf", b or Box())
    sm = SheetModel.open(g["path"])
    uid = next(k for k, u in sm.units.items() if len(u.views) >= 2)
    ans = box_answer(sm, uid, g["box"], g["handles"], names)
    if edit:
        edit(ans, sm.unit(uid))
    sm.commit_answer(uid, ans)
    return sm, uid, g


def points(sm, g, name, sr=None):
    sr = sr or sm.regenerate()
    k = next(it.index for it in sm.dr.items if it.handle == g["handles"][name])
    return sr.reg.pts.get(k, sm.dr.items[k].pts)


def off_intent(sm, g, value, anchor, foundation="follow", wings="follow", tol=0.5) -> list[str]:
    """Members whose regenerated outline is not where the generator draws them at `value` with this anchor."""
    sr = sm.regenerate()
    want = _expected_points(g["box"], value, anchor, foundation, wings)
    bad = []
    for name in g["handles"]:
        got, exp = points(sm, g, name, sr), want[name]
        d = max(min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in exp) for p in got[: len(exp)])
        if d > tol:
            bad.append(f"{name} off by {d:.1f} mm")
    return bad


def width(pts):
    return max(p[0] for p in pts) - min(p[0] for p in pts)


def height(pts):
    return max(p[1] for p in pts) - min(p[1] for p in pts)


# 1 ── the instruction resolves to the drawing's own value and parts ───────────────


def test_an_instruction_resolves_to_the_existing_value_and_parts_and_says_what_it_cannot(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    u = sm.unit(uid)
    text = ("Reduce the clear span to 2500 mm. Maintain the outer wall thickness. Keep the foundation fixed. "
            "Keep the bed level fixed. Do not modify the unrelated pitching detail. Keep the drainage pipe fixed.")
    r = read_instruction(text, vocabulary(u.prog), u.prog)
    assert r["driver"]["resolved"]["names"] == ["ClearSpan"] and r["driver"]["requested"]["value"] == 2500
    plan = sm.plan(uid, {"instruction": text})
    modes = {d["target"]: d["mode"] for d in plan["directives"] if d["status"] == "accepted"}
    assert modes["OuterWall"] == "keep_value" and modes["Foundation"] == "keep_fixed"
    assert modes["BedLevel"] == "keep_fixed" and modes["PitchingDetail"] == "exclude"
    # nothing on the drawing is called a drainage pipe: asked, never guessed
    q = next(q for q in plan["questions"] if q["about"].startswith("phrase:"))
    assert "drainage pipe" in q["text"] and "ignore" in q["options"]
    assert plan["status"] == "needs_decision"


# 2 ── one occurrence, not every equal size ────────────────────────────────────────


def test_one_occurrence_is_the_value_and_the_equal_one_stays_its_own_size(tmp_path):
    def left_cell_only(ans, u):
        p = next(p for p in ans["parameters"] if p["name"] == "ClearSpan")
        p["occurrences"] = p["occurrences"][:1]

    sm, uid, g = box_sheet(tmp_path, edit=left_cell_only)
    before = {n: points(sm, g, n) for n in ("LeftWall", "MidWall1", "RightWall")}
    res = sm.apply_plan(uid, {"instruction": "Change the clear span to 2600. The left side stays fixed. " + FOLLOW_ALL})
    assert res["checks"]["ok"], [c for c in res["checks"]["checks"] if c["status"] == "fail"]
    left, mid, right = (points(sm, g, n) for n in ("LeftWall", "MidWall1", "RightWall"))
    assert left == before["LeftWall"]  # the start stays
    assert min(p[0] for p in mid) - max(p[0] for p in left) == pytest.approx(2600)  # the left cell is the value
    assert min(p[0] for p in right) - max(p[0] for p in mid) == pytest.approx(3000)  # the right cell is its own size
    assert all(a[0] - b[0] == pytest.approx(-400) for a, b in zip(right, before["RightWall"], strict=True))


# 3 ── a kept value stays while its geometry moves ─────────────────────────────────


def test_a_kept_value_stays_while_the_geometry_it_sizes_moves(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    w0 = points(sm, g, "LeftWall")
    res = sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred. Maintain the outer wall thickness. " + FOLLOW_ALL})
    keep = [c for c in res["checks"]["checks"] if c["check"] == "keep_value" and c["target"].startswith("OuterWall")]
    assert keep and all(c["status"] == "pass" for c in keep)
    w1 = points(sm, g, "LeftWall")
    assert width(w1) == pytest.approx(350) and min(p[0] for p in w1) - min(p[0] for p in w0) == pytest.approx(500)  # it moved


# 4 ── the meanings of "do not change" are kept apart ──────────────────────────────


def test_keep_fixed_exclude_and_no_parameter_mean_different_things(tmp_path):
    def foundation_value(ans, u):
        an, um = u.an, u.sub.units_mm
        lo = min((d for d in an.datums.values() if d.axis == "y"), key=lambda d: abs(d.value * um + 150))
        hi = min((d for d in an.datums.values() if d.axis == "y"), key=lambda d: abs(d.value * um))
        ans["parameters"].append({"name": "FoundationDepth", "label": "", "component": "Foundation", "kind": "length",
                                  "from_datum": lo.id, "to_datum": hi.id, "value": 150.0})

    sm, uid, g = box_sheet(tmp_path, edit=foundation_value)
    # exclude: no value of its own — refused while the foundation has one
    plan = sm.plan(uid, {"instruction": "Reduce the clear span to 2500, centred. Exclude the foundation. Wing walls follow the box."})
    assert any("FoundationDepth" in c for c in plan["conflicts"]) and plan["status"] == "conflict"
    # keep_fixed: it stays where it is drawn, and keeps its value
    f0 = points(sm, g, "Foundation")
    res = sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred. Keep the foundation fixed. Wing walls follow the box. "
                                             "Do not modify the unrelated pitching detail."})
    assert res["checks"]["ok"] and points(sm, g, "Foundation") == f0
    assert "FoundationDepth" in sm.unit(uid).prog.params
    # no_parameter + follow: the wing walls get no value of their own, yet move with the box
    sm.undo()
    plan = sm.plan(uid, {"instruction": "Reduce the clear span to 2500, centred. Do not parameterize the wing walls. Wing walls follow the box. "
                                        "The foundation follows the box. Do not modify the unrelated pitching detail."})
    modes = {(d["target"], d["mode"]) for d in plan["directives"] if d["status"] == "accepted"}
    assert {("WingLeft", "no_parameter"), ("WingLeft", "follow"), ("WingRight", "no_parameter")} <= modes
    assert plan["status"] == "ready"


# 5 ── "do not touch" is a question ────────────────────────────────────────────────


def test_do_not_touch_is_ambiguous_and_is_asked_not_guessed(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    plan = sm.plan(uid, {"instruction": "Reduce the clear span to 2500, centred. Do not touch the foundation. Wing walls follow the box."})
    q = next(q for q in plan["questions"] if "Foundation" in q["text"])
    assert set(q["options"]) == {"no_parameter", "keep_fixed", "exclude"}
    assert plan["status"] == "needs_decision"
    rev = sm.revision
    with pytest.raises(SheetError, match="needs_decision"):
        sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred. Do not touch the foundation. Wing walls follow the box."})
    assert sm.revision == rev and not sm.values


# 6 ── anchors: centered, start fixed, end fixed ───────────────────────────────────


@pytest.mark.parametrize("words,policy", [("centred", "centered"), ("the left side stays fixed", "start_fixed"),
                                          ("the right side stays fixed", "end_fixed")])
def test_each_anchor_policy_moves_the_whole_box_as_drawn_by_the_generator(tmp_path, words, policy):
    sm, uid, g = box_sheet(tmp_path)
    res = sm.apply_plan(uid, {"instruction": f"Change the clear span to 3600, {words}. " + FOLLOW_ALL})
    assert res["plan"]["anchor"]["policy"] == policy and res["checks"]["ok"]
    assert off_intent(sm, g, 3600, policy) == []


# 7 ── growth and shrinkage of the whole assembly, and back ────────────────────────


def test_the_clear_span_grows_and_shrinks_with_the_whole_assembly_and_comes_back_exactly(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    drawn = {n: points(sm, g, n) for n in g["handles"]}
    sm.apply_plan(uid, {"instruction": "Change the clear span to 3600, centred. " + FOLLOW_ALL})
    assert off_intent(sm, g, 3600, "centered") == []
    for v in (2400.0, 3300.0):  # ordinary edits after the plan: deterministic, no new reading
        assert sm.apply({f"{uid}.ClearSpan": v}).ok
        assert off_intent(sm, g, v, "centered") == []
    assert sm.apply({f"{uid}.ClearSpan": 3000.0}).ok
    sr = sm.regenerate()
    assert all(points(sm, g, n, sr) == pytest.approx(drawn[n]) for n in drawn)


# 8, 9 ── slab ends follow the walls; slab thickness stays ─────────────────────────


def test_the_slab_ends_follow_the_wall_faces_they_sit_on(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred. " + FOLLOW_ALL})
    for slab in ("TopSlab", "BottomSlab"):
        s = points(sm, g, slab)
        assert min(p[0] for p in s) == pytest.approx(min(p[0] for p in points(sm, g, "LeftWall")))
        assert max(p[0] for p in s) == pytest.approx(max(p[0] for p in points(sm, g, "RightWall")))


def test_slab_thickness_stays_while_the_slab_resizes(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    t0 = {s: height(points(sm, g, s)) for s in ("TopSlab", "BottomSlab")}
    res = sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred. Maintain the slab thicknesses. " + FOLLOW_ALL})
    for s in ("TopSlab", "BottomSlab"):
        assert height(points(sm, g, s)) == pytest.approx(t0[s])
        assert width(points(sm, g, s)) == pytest.approx(6000)
    assert all(c["status"] == "pass" for c in res["checks"]["checks"] if c["check"] == "keep_value")


# 10 ── haunches stay on their corners, the same size ──────────────────────────────


def test_haunches_follow_their_corners_and_keep_their_legs(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, the right side stays fixed. " + FOLLOW_ALL})
    wall_face = max(p[0] for p in points(sm, g, "LeftWall"))
    slab_top = max(p[1] for p in points(sm, g, "BottomSlab"))
    h = points(sm, g, "Haunch1BL")
    assert h[0] == pytest.approx((wall_face, slab_top))  # the corner it fills
    assert width(h) == pytest.approx(150) and height(h) == pytest.approx(150)
    for name in ("Haunch1BR", "Haunch1TL", "Haunch1TR", "Haunch2BL", "Haunch2BR", "Haunch2TL", "Haunch2TR"):
        hp = points(sm, g, name)
        assert width(hp) == pytest.approx(150) and height(hp) == pytest.approx(150)


# 11 ── attached parts move without resizing ───────────────────────────────────────


def test_wing_walls_move_with_the_box_without_changing_size(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    w0 = points(sm, g, "WingLeft")
    res = sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred. Wing walls stay attached to the box. "
                                             "The foundation follows the box. Do not modify the unrelated pitching detail."})
    assert res["checks"]["ok"]
    w1 = points(sm, g, "WingLeft")
    assert (width(w1), height(w1)) == pytest.approx((width(w0), height(w0)))
    assert max(p[0] for p in w1) == pytest.approx(min(p[0] for p in points(sm, g, "PlanBox")))  # still on the box's face


# 12 ── a fixed bed level and held geometry ────────────────────────────────────────


def test_the_bed_level_and_a_held_foundation_stay_where_they_are(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    f0 = points(sm, g, "Foundation")
    res = sm.apply_plan(uid, {"instruction": "Increase the clear span to 3400, centred. Keep the bed level fixed. Keep the foundation fixed. "
                                             "Wing walls follow the box. Do not modify the unrelated pitching detail."})
    checks = {(c["check"], c["target"].split(" ")[0]): c["status"] for c in res["checks"]["checks"]}
    assert checks[("keep_fixed", "BedLevel")] == "pass" and checks[("fixed", "Foundation")] == "pass"
    assert points(sm, g, "Foundation") == f0
    assert max(p[1] for p in points(sm, g, "BottomSlab")) == pytest.approx(350)  # the bed (top of the bottom slab)
    u = sm.unit(uid)
    plans = u.answer["plans"]
    assert plan_errors_at(u.prog, plans, {"ClearSpan": 2800.0}) == []  # a slider edit keeps the promise
    assert plan_errors_at(u.prog, plans, {"BedLevel": 0.5}) == []  # the person may still move the level itself


# 13 ── a tied part with no accepted behaviour stops the edit ──────────────────────


def test_a_part_tied_to_the_box_without_an_accepted_behaviour_stops_the_edit(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    plan = sm.plan(uid, {"instruction": "Reduce the clear span to 2500, centred."})
    asked = {q["about"] for q in plan["questions"]}
    assert {"attached:Foundation", "attached:WingLeft", "attached:WingRight"} <= asked
    detail = next(q for q in plan["questions"] if q["about"] == "attached:PitchingDetail")
    assert detail["recommended"] == "keep_fixed"  # it does not touch the box: it only hangs on its lines
    before = (sm.revision, copy.deepcopy(sm.unit(uid).answer))
    with pytest.raises(SheetError):
        sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred."})
    assert (sm.revision, sm.unit(uid).answer) == before


# 14 ── a tear is caught although the size measures right ─────────────────────────


def wall_under_slab(path) -> str:
    """A wall standing under a slab that overhangs it on both sides: the wall's top corners lie on the slab's
    underside (a T-junction), not on its ends."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(-500, 2000), (1000, 2000), (1000, 2300), (-500, 2300)], close=True)
    msp.add_lwpolyline([(0, 0), (300, 0), (300, 2000), (0, 2000)], close=True)
    msp.add_text("SECTION", height=175, dxfattribs={"insert": (250, -600), "halign": 1, "align_point": (250, -600)})
    doc.saveas(path)
    return str(path)


def test_a_wall_torn_off_its_slab_is_caught_although_its_offset_measures_right(tmp_path):
    from dxf_autoparam.analyse import analyse
    from dxf_autoparam.dxf_read import read_dxf
    from dxf_autoparam.plan import accept, with_plan
    from dxf_autoparam.topology import of
    from dxf_autoparam.validator import apply

    def fresh():
        return analyse(read_dxf(wall_under_slab(tmp_path / "ws.dxf"))[0])

    an = fresh()  # one drawing on its own: the same plan, compiled and measured by validator.apply
    u = an.drawing.units_mm
    x = {round(d.value * u): d.id for d in an.datums.values() if d.axis == "x"}
    regs = sorted(of(an).regions, key=lambda r: r.bbox[1])
    ans = {**copy.deepcopy(EMPTY_ANSWER), "components": [{"name": "Wall", "type": "wall", "regions": [regs[0].id]},
                                                           {"name": "Slab", "type": "slab", "regions": [regs[1].id]}],
           "parameters": [{"name": "WallOffset", "label": "", "component": "Wall", "kind": "length", "from_datum": x[-500], "to_datum": x[0], "value": 500.0}]}
    prog, _rep = apply(an, ans)
    plan = build_plan(prog, ans, {"instruction": "Increase the wall offset to 1500, the left side stays fixed."})
    assert plan["status"] == "ready", plan["questions"] + plan["conflicts"]
    ans = with_plan(ans, accept(plan))
    prog, rep = apply(fresh(), ans)
    assert prog.intent["plans"][0]["ok"] and not rep.errors()  # done right, the slab's far end follows: the wall still stands under it
    # now break it: the slab's far end held where it is drawn, as a stray formula would
    prog.formulas[x[1000]] = "1000"
    prog.invalidate()
    row = prog.intent["plans"][0]["compiled"]
    out = verify_plan(prog, ans["plans"][0], prog.intent["parts"], {"rows": [{"id": plan["id"], **row}]}, values=[2500.0], answer=ans)
    checks = {c["check"]: c for c in out["checks"]}
    assert checks["driver"]["status"] == "pass"  # the offset itself measures 2500
    assert checks["connection"]["status"] == "fail" and "no longer meets" in checks["connection"]["measured"]
    assert not out["ok"]


# 15 ── wrong geometry inside an unchanged bounding box ────────────────────────────


def test_wrong_geometry_inside_a_bounding_box_that_did_not_change_is_caught(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred. " + FOLLOW_ALL})
    u = sm.unit(uid)
    prog, plan, parts = u.prog, u.answer["plans"][0], u.prog.intent["parts"]
    row = prog.intent["plans"][0]["compiled"]
    step = {"ClearSpan": 3300.0}
    right = _boxes({"Box": parts["Box"]}, _geometry(prog, step))["Box"]
    # the haunch's leg is pinned where it is drawn: the haunch stretches with the wall, inside the box
    leg = min((d for d in u.an.datums.values() if d.axis == "x"), key=lambda d: abs(d.value * u.sub.units_mm - 500)).id
    prog.formulas[leg] = "500"
    prog.invalidate()
    wrong = _boxes({"Box": parts["Box"]}, _geometry(prog, step))["Box"]
    b0 = _boxes({"Box": parts["Box"]}, _geometry(prog))["Box"]
    thr = 0.5
    assert classify(b0, wrong, thr) == classify(b0, right, thr)  # the bounding box says nothing changed
    out = verify_plan(prog, plan, parts, {"rows": [{"id": plan["id"], **row}]}, answer=u.answer)
    failed = {c["check"] for c in out["checks"] if c["status"] == "fail"}
    assert "assembly" in failed  # the measurement does


# 16 ── views in projection and sizes shared with other units ──────────────────────


def test_both_views_follow_and_a_shared_size_holds_in_every_unit(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    res = sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred. " + FOLLOW_ALL})
    assert set(res["applied"]["by_view"]) == {"V01", "V02"}
    assert width(points(sm, g, "PlanBox")) == pytest.approx(width(points(sm, g, "TopSlab")))  # plan = section
    # a size shared with a separate detail view: the plan's value reaches it
    sm2 = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    u2 = next(k for k, u in sm2.units.items() if len(u.views) == 2)
    other = next(k for k in sm2.units if k != u2)
    sm2.set_answer(u2, {**copy.deepcopy(EMPTY_ANSWER), "parameters": [
        {"name": "OuterWall", "label": "Outer wall", "component": "", "kind": "length", "candidate": "c0", "value": 300.0}]})
    sm2.share("OuterWall", [(u2, "c0"), (other, "c0")])
    out = sm2.apply_plan(u2, {"instruction": "Change the outer wall to 400, the left side stays fixed."})
    assert out["checks"]["ok"]
    sr = sm2.regenerate()
    assert sr.ok and sr.measured["OuterWall"][u2] == pytest.approx(400) and sr.measured["OuterWall"][other] == pytest.approx(400)
    assert dim_labels(sm2, sr).count("400") >= 3  # both walls under the section and the detail's own


# 17 ── dimensions recalculate; annotations keep their associations ────────────────


def test_dimensions_read_the_new_sizes_and_stay_on_their_lines(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    an = sm.unit(uid).an
    tied = {k: v for k, v in an.slot_datum.items() if an.drawing.items[k[0]].dxftype == "DIMENSION"}
    sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred. " + FOLLOW_ALL})
    sr = sm.regenerate()
    labels = dim_labels(sm, sr)
    assert labels.count("2500") == 2 and "6000" in labels and labels.count("350") >= 2  # spans, overall, walls
    note = next(t for k, t in sr.reg.texts.items() if "CELL RCC BOX" in t)
    assert note.startswith("2 CELL RCC BOX 2.500 X 2.500")
    an = sm.unit(uid).an
    assert {k: v for k, v in an.slot_datum.items() if an.drawing.items[k[0]].dxftype == "DIMENSION"} == tied


# 18 ── a person's values survive a refused edit ───────────────────────────────────


def test_a_refused_edit_keeps_every_value_the_person_set(tmp_path):
    sm, uid, _g = box_sheet(tmp_path)
    assert sm.apply({f"{uid}.OuterWall": 400.0}).ok
    rev, values = sm.revision, copy.deepcopy(sm.values)
    with pytest.raises(SheetError):  # contradictory: refused as a conflict
        sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, centred. Keep the foundation fixed. The foundation follows the box."})
    with pytest.raises(SheetError, match="clash"):  # a value where the members run into each other: refused when measured
        sm.apply_plan(uid, {"instruction": "Change the clear span to 100. The left side stays fixed. " + FOLLOW_ALL})
    assert (sm.revision, sm.values) == (rev, values)
    # a new parametrization that would drop the person's value is refused unless they say so
    ans = copy.deepcopy(sm.unit(uid).answer)
    ans["parameters"] = [p for p in ans["parameters"] if p["name"] != "OuterWall"]
    with pytest.raises(SheetError, match="would be lost"):
        sm.commit_answer(uid, ans)
    assert sm.values == values
    assert sm.commit_answer(uid, ans, discard_values=True)["values_dropped"] == ["OuterWall"]


# 19 ── undo, redo and saving keep the accepted intent ─────────────────────────────


def test_an_accepted_plan_is_undone_redone_saved_and_reopened(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    sm.apply_plan(uid, {"instruction": "Reduce the clear span to 2500, the left side stays fixed. " + FOLLOW_ALL})
    assert sm.undo() and not sm.unit(uid).answer.get("plans") and not sm.values
    assert sm.redo() and sm.unit(uid).answer["plans"][0]["status"] == "accepted"
    assert off_intent(sm, g, 2500, "start_fixed") == []
    project = tmp_path / "box.autoparam.json"
    sm.save(str(project))
    again = SheetModel.load(str(project), dxf=g["path"])
    u = again.unit(uid)
    assert u.answer["plans"][0]["anchor"]["policy"] == "start_fixed"
    assert u.prog.intent["plans"][0]["ok"]  # compiled and measured again on opening, no model involved
    assert off_intent(again, g, 2500, "start_fixed") == []
    assert again.apply({f"{uid}.ClearSpan": 3200.0}).ok and off_intent(again, g, 3200, "start_fixed") == []


# 20 ── the agent, scripted: it plans before it writes behaviour ───────────────────


def test_the_agent_plans_the_change_before_writing_behaviour_and_the_sheet_commits_it(tmp_path):
    sm, uid, g = box_sheet(tmp_path)
    said = ("Reduce the clear span to 2500 mm, centred about the centre line. Keep the foundation fixed. Wing walls follow the box. "
            "Do not modify the unrelated pitching detail.")
    dirs = [{"target": "Foundation", "mode": "keep_fixed", "clause": "Keep the foundation fixed"},
            {"target": "WingLeft", "mode": "follow", "clause": "Wing walls follow the box"},
            {"target": "WingRight", "mode": "follow", "clause": "Wing walls follow the box"},
            {"target": "PitchingDetail", "mode": "exclude", "clause": "Do not modify the unrelated pitching detail"}]
    anchor = {"policy": "centered", "clause": "centred about the centre line"}
    script = [
        [call("set_formulas", items=[{"line": "x3", "expr": "x6 - ClearSpan"}])],  # behaviour before a plan: refused
        [call("inspect_assembly", parameter="ClearSpan")],
        # the agent's own inference (no words of the person behind it) is a proposal, not a decision
        [call("propose_plan", parameter="ClearSpan", requested_value=2500, anchor=anchor,
              directives=[*dirs, {"target": "OuterWall", "mode": "keep_value", "clause": "", "why": "walls keep their thickness"}])],
        [call("propose_plan", parameter="ClearSpan", requested_value=2500, anchor=anchor, directives=dirs)],
        [call("finish", summary="planned and measured")],
    ]
    gem = ScriptedGemini(script)
    res = parametrize_unit(sm, uid, gem, instructions=said, log=lambda *a: None)
    first = gem.seen[0][0]["result"][0]
    assert first["ok"] is False and first["failure"]["code"] == "PLAN_FIRST"
    look = gem.seen[1][0]
    assert any(a["policy"] == "centered" and a["possible"] for a in look["anchors"]) and "Foundation" in look["tied_to_it"]
    pending = gem.seen[2][0]["result"]
    assert pending["plan"] == "needs_decision" and any("The AI proposes" in q for q in pending["questions"])
    done = gem.seen[3][0]["result"]
    assert done["ok"] and done["plan"] == "accepted and measured" and done["checks"]["failed"] == 0
    assert res["values_applied"] == [{"name": f"{uid}.ClearSpan", "value": 2500}]
    assert off_intent(sm, g, 2500, "centered", foundation="keep_fixed") == []
    assert json.dumps(sm.to_dict())  # the plan is part of the saved project
