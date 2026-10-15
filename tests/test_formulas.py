"""The formula language and component transforms: what a formula may say (angles in named units, vectors, conditions),
what it may never do (run code, mix kinds of quantity, turn a domain error into a coordinate), and a part turned about a
pivot by a measured angle — exact at the drawn value, lengths kept when the angle changes, its leader carried along."""

from __future__ import annotations

import copy
import math

import ezdxf
import pytest

from dxf_autoparam.cadjson import entity_id
from dxf_autoparam.crossview import EMPTY_ANSWER, SheetError, SheetModel
from dxf_autoparam.program import ExprError, check_dims, evaluate, names_in


@pytest.mark.parametrize("expr,scope,want", [
    ("x3 + 2 * sind(30) * L", {"x3": 100, "L": 1000}, 1100.0),
    ("Span / cosd(Skew)", {"Span": 6000, "Skew": 30}, 6000 / math.cos(math.radians(30))),
    ("atan2d(H, W)", {"H": 1, "W": 1}, 45.0),
    ("rotx(1000, 0, 0, 0, 90)", {}, 0.0),
    ("roty(1000, 0, 0, 0, 90)", {}, 1000.0),
    ("hypot(Dx, Dy)", {"Dx": 3, "Dy": 4}, 5.0),
    ("a if a > b else b", {"a": 3, "b": 5}, 5.0),
    ("clamp(x, 0, 10)", {"x": 12}, 10.0),
    ("pi * r ** 2", {"r": 1}, math.pi),
    ("deg(atan2(1, 0))", {}, 90.0),
    ("dot(1, 2, 3, 4) + cross(1, 0, 0, 1)", {}, 12.0),
])
def test_the_language_evaluates_what_it_promises(expr, scope, want):
    assert evaluate(expr, scope) == pytest.approx(want)


def test_constants_and_functions_are_not_names_a_formula_depends_on():
    assert names_in("pi * Span + sind(Skew)") == {"Span", "Skew"}


@pytest.mark.parametrize("expr,scope,why", [
    ("sqrt(-1)", {}, "nonnegative"),
    ("asind(2)", {}, "range"),
    ("1 / (a - a)", {"a": 2}, "division by zero"),
    ("(-8) ** 0.5", {}, "not a real number"),
    ("10.0 ** 400", {}, "too large"),
    ("clamp(1, 5, 0)", {}, "lower bound"),
])
def test_a_domain_error_is_refused_never_turned_into_a_coordinate(expr, scope, why):
    with pytest.raises(ExprError, match=why):
        evaluate(expr, scope)


@pytest.mark.parametrize("expr", ["__import__('os')", "x.real", "[1, 2]", "lambda: 1", "f(1)", "'a'", "sind(1, 2)", "x[0]", "True + 1"])
def test_nothing_but_arithmetic_on_numbers_is_accepted(expr):
    with pytest.raises(ExprError):
        evaluate(expr, {"x": 1.0})


@pytest.mark.parametrize("expr,kind", [("Span / cosd(Skew)", "length"), ("x3 + L * tand(Skew)", "length"), ("atan2d(H, W)", "angle"),
                                       ("sqrt(H * H + W * W)", "length"), ("H / W", "ratio")])
def test_kinds_of_quantity_are_tracked(expr, kind):
    dims = {"Span": "length", "Skew": "angle", "x3": "length", "L": "length", "H": "length", "W": "length"}
    assert check_dims(expr, dims) == kind


@pytest.mark.parametrize("expr,why", [("x3 + Skew", "mixes a length with an angle"), ("sind(Span)", "takes an angle"),
                                      ("sin(Skew)", "takes radians"), ("H * W", "power 2"), ("x3 + atan2d(H, W)", "mixes")])
def test_a_formula_mixing_kinds_is_refused(expr, why):
    dims = {"Span": "length", "Skew": "angle", "x3": "length", "H": "length", "W": "length"}
    with pytest.raises(ExprError, match=why):
        check_dims(expr, dims, want="length")


# ── a part turned about a pivot ───────────────────────────────────────────────────


def wing(path) -> str:
    """A base slab and a wing wall leaving its top right corner at 30°, 2000 long, 300 thick; a leader names the wing."""
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for a, b in [((0, 0), (4000, 0)), ((4000, 0), (4000, 500)), ((4000, 500), (0, 500)), ((0, 500), (0, 0))]:
        msp.add_line(a, b)
    a = math.radians(30)
    p0 = (4000.0, 500.0)
    p1 = (p0[0] + 2000 * math.cos(a), p0[1] + 2000 * math.sin(a))
    n = (-300 * math.sin(a), 300 * math.cos(a))
    p2, p3 = (p1[0] + n[0], p1[1] + n[1]), (p0[0] + n[0], p0[1] + n[1])
    for q, r in [(p0, p1), (p1, p2), (p2, p3), (p3, p0)]:
        msp.add_line(q, r, dxfattribs={"layer": "WING"})
    mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    msp.add_leader([mid, (mid[0] + 400, mid[1] - 600), (mid[0] + 1400, mid[1] - 600)], dxfattribs={"layer": "NOTES"})
    msp.add_text("WING WALL", height=150, dxfattribs={"layer": "NOTES", "insert": (mid[0] + 450, mid[1] - 580)})
    doc.saveas(path)
    return str(path)


def _wing_answer(sm, uid, angle=30.0, extra=None):
    u = sm.unit(uid)
    items = u.sub.items
    wing_lines = [it for it in items if it.layer == "WING"]
    long_edge = next(it for it in wing_lines if abs(math.dist(*it.pts[:2]) - 2000) < 1e-6)
    x4000 = next(d.id for d in u.an.datums.values() if d.axis == "x" and abs(d.value - 4000) < 1e-6)
    y500 = next(d.id for d in u.an.datums.values() if d.axis == "y" and abs(d.value - 500) < 1e-6)
    ans = copy.deepcopy(EMPTY_ANSWER)
    ans["parameters"] = [{"name": "WingAngle", "kind": "angle", "unit": "deg", "angle_of": entity_id(long_edge), "value": angle}]
    ans["transforms"] = [{"name": "WingTurn", "kind": "rotate", "entities": [entity_id(it) for it in wing_lines], "pivot": [x4000, y500],
                          "angle": "WingAngle", "why": "the wing leaves the slab corner at its own angle"}]
    if extra:
        extra(ans)
    return ans, wing_lines


def test_a_measured_angle_turns_its_part_about_the_pivot_exactly(tmp_path):
    sm = SheetModel.open(wing(tmp_path / "wing.dxf"))
    uid = next(iter(sm.units))
    ans, wing_lines = _wing_answer(sm, uid)
    sm.commit_answer(uid, ans)
    u = sm.unit(uid)
    assert u.prog.params["WingAngle"].value == pytest.approx(30.0) and u.prog.params["WingAngle"].unit == "deg"
    assert u.prog.transforms and u.prog.transforms[0]["kind"] == "rotate"
    # at the drawn angle: the drawing, exactly
    sr = sm.regenerate()
    for it in wing_lines:
        s = u.back[it.index]
        assert sr.reg.pts.get(s, sm.dr.items[s].pts) == pytest.approx(sm.dr.items[s].pts)
    # 40°: every wing point turned 10° about (4000, 500); lengths kept; the slab untouched
    sr = sm.preview({f"{uid}.WingAngle": 40.0})
    assert sr.ok, sr.errors
    far = max((p for it in wing_lines for p in sr.reg.pts[u.back[it.index]]), key=lambda p: math.dist(p, (4000, 500)))
    r = math.hypot(2000, 300)
    want_angle = 40 + math.degrees(math.atan2(300, 2000))
    assert far == pytest.approx((4000 + r * math.cos(math.radians(want_angle)), 500 + r * math.sin(math.radians(want_angle))), abs=1e-6)
    for it in wing_lines:
        p = sr.reg.pts[u.back[it.index]]
        assert math.dist(p[0], p[1]) == pytest.approx(math.dist(*it.pts[:2]), abs=1e-6)
    slab = [i for i in u.items if sm.dr.items[i].layer == "0" and sm.dr.items[i].dxftype == "LINE"]
    assert all(sr.reg.pts.get(i, sm.dr.items[i].pts) == pytest.approx(sm.dr.items[i].pts) for i in slab)
    # the leader that names the wing is carried with it (its tip stays on the wing's edge)
    leader = next(i for i in u.items if sm.dr.items[i].dxftype == "LEADER")
    tip = sr.reg.pts[leader][0]
    edge = next(sr.reg.pts[u.back[it.index]] for it in wing_lines if abs(math.dist(*it.pts[:2]) - 2000) < 1e-6)
    ax, ay = edge[0]
    bx, by = edge[1]
    t = ((tip[0] - ax) * (bx - ax) + (tip[1] - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)
    assert math.dist(tip, (ax + t * (bx - ax), ay + t * (by - ay))) < 1e-6
    # the behaviour report calls it a rotation
    from dxf_autoparam.behaviour import behaviour_report

    rep = behaviour_report(sm, {f"{uid}.WingAngle": 40.0})
    assert rep["categories"]["validity"]["status"] == "pass"


def test_an_angle_the_drawing_does_not_show_is_refused(tmp_path):
    sm = SheetModel.open(wing(tmp_path / "wing.dxf"))
    uid = next(iter(sm.units))
    ans, _ = _wing_answer(sm, uid, angle=33.0)
    sm.commit_answer(uid, ans)  # the answer builds, but the angle and its transform are refused with the reason
    u = sm.unit(uid)
    assert "WingAngle" not in u.prog.params and not u.prog.transforms
    msgs = " ".join(f["message"] for f in u.report.errors())
    assert "drawn at 30" in msgs


def test_bad_transforms_are_refused_with_the_reason(tmp_path):
    sm = SheetModel.open(wing(tmp_path / "wing.dxf"))
    uid = next(iter(sm.units))

    def two(ans):
        ans["transforms"].append({**ans["transforms"][0], "name": "WingTurnAgain"})
        ans["transforms"].append({"name": "Squash", "kind": "scale", "entities": ["L0"], "pivot": ["0", "0"], "sx": "2", "sy": "1"})
        ans["transforms"].append({"name": "Mixed", "kind": "translate", "entities": ["L1"], "dx": "WingAngle", "dy": "0"})

    ans, _ = _wing_answer(sm, uid, extra=two)
    sm.commit_answer(uid, ans)
    msgs = " ".join(f["message"] for f in sm.unit(uid).report.errors())
    assert "one transform per entity" in msgs
    assert "distorts the part" in msgs
    assert "is an angle, not a length" in msgs
    assert [t["name"] for t in sm.unit(uid).prog.transforms] == ["WingTurn"]


def test_a_rotated_part_exports_turned_and_comes_back_on_undo(tmp_path):
    sm = SheetModel.open(wing(tmp_path / "wing.dxf"))
    uid = next(iter(sm.units))
    ans, wing_lines = _wing_answer(sm, uid)
    sm.commit_answer(uid, ans)
    sr = sm.apply({f"{uid}.WingAngle": 45.0})
    assert sr.ok, sr.errors
    out = tmp_path / "turned.dxf"
    rep = sm.export(str(out))
    assert rep["audit"]["errors"] == 0
    doc = ezdxf.readfile(out)
    angles = sorted(round(math.degrees(math.atan2(e.dxf.end.y - e.dxf.start.y, e.dxf.end.x - e.dxf.start.x)) % 180, 6)
                    for e in doc.modelspace() if e.dxftype() == "LINE" and e.dxf.layer == "WING")
    assert 45.0 in angles and 135.0 in angles
    assert sm.undo()
    sr = sm.regenerate()
    u = sm.unit(uid)
    assert all(sr.reg.pts.get(u.back[it.index], it.pts) == pytest.approx(it.pts) for it in wing_lines)


def test_a_formula_mixing_kinds_never_reaches_a_set_out_line(tmp_path):
    sm = SheetModel.open(wing(tmp_path / "wing.dxf"))
    uid = next(iter(sm.units))
    u = sm.unit(uid)
    x4000 = next(d.id for d in u.an.datums.values() if d.axis == "x" and abs(d.value - 4000) < 1e-6)
    x0 = next(d.id for d in u.an.datums.values() if d.axis == "x" and abs(d.value) < 1e-6)

    def bad(ans):
        ans["datum_formulas"] = [{"datum": x4000, "expr": f"{x0} + 3970 + WingAngle"}]

    ans, _ = _wing_answer(sm, uid, extra=bad)
    try:
        sm.commit_answer(uid, ans)
    except SheetError:
        pass
    msgs = " ".join(f["message"] for f in sm.unit(uid).report.errors())
    assert "mixes a length with an angle" in msgs
