"""A relation proposed for a drawing — from a generator's knowledge, a standard, the agent's reading — is checked on the drawing before it is bound:
does it hold at the drawn values, does the drawing already carry it when a value changes, and what would binding it take.

A generated box between a road level and a formation level, parametrized the way its answer says (ClearHeight, the slabs, the wearing course)."""

from __future__ import annotations

import pytest
from levels_fixture import LevelBox, level_box_sheet
from test_agent import ScriptedGemini, call

from dxf_autoparam.relations import check


def box(tmp_path):
    b = LevelBox()
    sm, uid, _g = level_box_sheet(tmp_path, b, intent=False)
    u = sm.unit(uid)
    um = u.sub.units_mm
    v = u.prog.datum_values()

    def line(mm: float) -> str:
        return min((d for d in u.an.datums.values() if d.axis == "y"), key=lambda d: abs(v[d.id] * um - mm)).id

    return b, sm, uid, u.prog, line


def test_a_relation_the_drawing_carries_holds_and_follows_every_value(tmp_path):
    b, _sm, _uid, prog, line = box(tmp_path)
    top, bottom = line(b.y_top), line(0.0)
    got = check(prog, f"{top} - {bottom} = BottomSlabThickness + WearingCourseThickness + ClearHeight + TopSlabThickness")
    assert got["holds"] and got["residual_mm"] == pytest.approx(0.0), got
    assert got["terms"][top]["is"] == "line" and got["terms"]["ClearHeight"]["is"] == "value"
    assert all(v is True for v in got["follows"].values()) and set(got["follows"]) >= {"BottomSlabThickness", "WearingCourseThickness", "ClearHeight",
                                                                                       "TopSlabThickness"}
    assert got["binding"].startswith("already carried")
    assert got["gives"]["ClearHeight"][top] == pytest.approx(1.0), "a mm more clear height: the top of the box rises a mm (the road level holds)"


def test_equal_by_coincidence_holds_but_is_not_carried_and_says_what_binding_would_take(tmp_path):
    _b, _sm, _uid, prog, _line = box(tmp_path)
    got = check(prog, "TopSlabThickness = BottomSlabThickness")  # both 400 as drawn: one is not made from the other
    assert got["holds"] and got["follows"] == {"BottomSlabThickness": False, "TopSlabThickness": False}
    assert "set_relation" in got["binding"] and "TopSlabThickness is an input" in got["binding"]


def test_a_relation_that_does_not_hold_says_by_how_much_and_binds_nothing(tmp_path):
    _b, _sm, _uid, prog, _line = box(tmp_path)
    got = check(prog, "ClearSpan = 2 * WallThickness")
    assert not got["holds"] and got["residual_mm"] == pytest.approx(4000 - 800)
    assert got["binding"].startswith("nothing to bind")


def test_a_level_added_to_a_length_is_said_and_a_bad_equation_is_refused_with_why(tmp_path):
    b, _sm, _uid, prog, _line = box(tmp_path)
    assert "units" not in check(prog, "FormationLevel = RoadLevel + ClearHeight"), "a position plus a distance is a position: nothing to say"
    got = check(prog, "ClearHeight = RoadLevel + TopSlabThickness")
    assert "units" in got and "level and a length" in got["units"], "a length made of a level and a length is said"
    assert "error" in check(prog, "ClearSpan + 1")
    assert "not a value" in check(prog, "ClearSpan = NoSuchSize")["error"]
    lvl = check(prog, f"FormationLevel = RoadLevel + {b.clear + b.top + b.cushion} / 1000 * 1000")
    assert lvl["holds"], lvl  # a level is taken in mm: the road level plus the height above it is the formation level


def test_the_agent_checks_a_relation_then_binds_it_with_where_it_came_from(tmp_path):
    from dxf_autoparam.ai.agent import agent_parametrize

    b = LevelBox()
    sm, uid, g = level_box_sheet(tmp_path, b, intent=False)
    script = [[call("check_relation", equation="TopSlabThickness = BottomSlabThickness", source="the drawing's note: slabs alike")],
              [call("set_relation", name="SlabsAlike", expr="BottomSlabThickness", source="the drawing's note: slabs alike")],
              [call("finish", summary="done")], [call("finish", summary="done")]]
    gem = ScriptedGemini(script)
    _prog, _rep, info = agent_parametrize(g["path"], gem=gem, log=lambda *a: None, start=sm.unit(uid).answer)
    seen = gem.seen[0][0]
    assert seen["holds"] and seen["source"] == "the drawing's note: slabs alike"
    rel = next(r for r in info["answer"]["relations"] if r["name"] == "SlabsAlike")
    assert rel["source"] == "the drawing's note: slabs alike", "the relation keeps where it came from"


def barrel_section(path, formation: float = 7850.0, cushion: float = 1000.0) -> dict:
    """A box's longitudinal section drawn as production builds it: the barrel's length is the formation width plus a 2H:1V embankment slope down to
    the top of the box at each end — formation width + 4 × cushion."""
    import ezdxf

    clear, top, bottom = 2850.0, 400.0, 400.0
    y_top = bottom + clear + top
    y_f = y_top + cushion
    half = formation / 2 + 2 * cushion
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(-half, 0), (half, 0), (half, y_top), (-half, y_top)], close=True)  # the barrel, cut along its length: one outline
    msp.add_line((-half, bottom), (half, bottom))  # the top of the bottom slab
    msp.add_line((-half, bottom + clear), (half, bottom + clear))  # the soffit (the side wall seen behind the cut between the two)
    msp.add_line((-formation / 2, y_f), (formation / 2, y_f))  # the formation
    msp.add_line((-formation / 2, y_f), (-half, y_top))  # the embankment slopes, 2H:1V
    msp.add_line((formation / 2, y_f), (half, y_top))
    msp.add_text(f"FORMATION LEVEL {100 + y_f / 1000:.3f}", height=150, dxfattribs={"insert": (-formation / 2, y_f + 60)})
    msp.add_line((-half - 1500, bottom), (-half, bottom))  # the bed level, stated where the box sits (production's input: soffit = bed + clear)
    msp.add_text(f"BED LEVEL {100 + bottom / 1000:.3f}", height=150, dxfattribs={"insert": (-half - 1500, bottom + 60)})
    for base, p1, p2, ang in [((0, -800), (-half, 0), (half, 0), 0), ((half + 700, 0), (half, bottom), (half, bottom + clear), 90),
                              ((half + 700, 0), (half, bottom + clear), (half, y_top), 90), ((half + 1400, 0), (half, y_top), (formation / 2, y_f), 90)]:
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=ang, dimstyle="Standard").render()
    doc.saveas(str(path))
    return {"path": str(path), "half": half, "y_top": y_top, "y_f": y_f, "formation": formation, "clear": clear, "top": top, "bottom": bottom}


def test_production_s_barrel_relation_is_carried_by_the_drawing_and_choosing_production_s_side_makes_the_barrel_follow_the_cushion(tmp_path):
    """aagento-bridge's panel computes barrel length = formation left + right + 4 × cushion (rcc-box-params.ts). On a drawing built that way — the box
    between the bed level and the formation level, both stated — the relation already holds under every change: the engine reads the 2H:1V slopes
    from the geometry. What differs is which side GIVES: as read, the barrel is kept and the formation widens when the cushion thins; production
    keeps the formation and shortens the barrel. `check_relation` says both; the agent sets the formation's edges out from where they stand and the
    barrel's ends from them, and a taller box then shortens the barrel by four times what the cushion loses — the slopes keep their 2H:1V."""
    from dxf_autoparam.ai.sheet_ai import parametrize_unit
    from dxf_autoparam.crossview import EMPTY_ANSWER, SheetModel

    g = barrel_section(tmp_path / "barrel.dxf")
    sm = SheetModel.open(g["path"])
    uid = next(iter(sm.units))
    u = sm.unit(uid)
    an, um = u.an, u.sub.units_mm

    def line(axis, at):
        return min((d for d in an.datums.values() if d.axis == axis), key=lambda d: abs(d.value * um - at)).id

    xl, xr, xfl, xfr = line("x", -g["half"]), line("x", g["half"]), line("x", -g["formation"] / 2), line("x", g["formation"] / 2)
    y_bs, y_soffit, y_top, y_f = line("y", g["bottom"]), line("y", g["bottom"] + g["clear"]), line("y", g["y_top"]), line("y", g["y_f"])
    root = min((d for d in an.datums.values() if d.axis == "x"), key=lambda d: d.value).id  # the drawing's first line: where the set-out starts
    ans = EMPTY_ANSWER | {"parameters": [
        {"name": "ClearHeight", "label": "ClearHeight", "component": "", "kind": "length", "from_datum": y_bs, "to_datum": y_soffit, "value": g["clear"]},
        {"name": "TopSlabThickness", "label": "TopSlabThickness", "component": "", "kind": "length", "from_datum": y_soffit, "to_datum": y_top,
         "value": g["top"]},
        {"name": "BarrelLength", "label": "BarrelLength", "component": "", "kind": "length", "from_datum": xl, "to_datum": xr, "value": 2 * g["half"]}],
        "levels": [{"datum": y_bs, "name": "BedLevel", "role": "site_input"}, {"datum": y_f, "name": "FormationLevel", "role": "site_input"}]}
    sm.commit_answer(uid, ans, intent=False)
    rhs = f"({xfr} - {xfl}) + 4 * ({y_f} - {y_top})"
    got = check(sm.unit(uid).prog, f"BarrelLength = {rhs}")
    assert got["holds"] and got["residual_mm"] == pytest.approx(0.0), got
    assert got["binding"].startswith("already carried"), "the slopes are read from the geometry: the relation is an identity of the set-out"
    assert got["gives"]["ClearHeight"].get(xfr, 0.0) == pytest.approx(2.0) and xr not in got["gives"]["ClearHeight"], \
        "as read, a mm less cushion moves the formation's edge 2 mm out and keeps the barrel"

    def at(d: str) -> float:
        w = sm.unit(uid)
        return w.prog.datum_values()[d] * um - w.prog.datum_values()[root] * um

    cushion = f"({y_f} - {y_top})"
    items = [{"line": xfl, "expr": f"{root} + {at(xfl):g}"}, {"line": xfr, "expr": f"{root} + {at(xfr):g}"},  # the formation stays where it is drawn
             {"line": xl, "expr": f"{xfl} - 2 * {cushion}"}, {"line": xr, "expr": f"{xfr} + 2 * {cushion}"}]  # the barrel's ends come down its slopes
    script = [[call("check_relation", equation=f"BarrelLength = {rhs}", source="aagento-bridge rcc-box-params.ts: formation L + R + 4 x cushion")],
              [call("set_formulas", items=items)], [call("finish", summary="done")], [call("finish", summary="done")]]
    gem = ScriptedGemini(script)
    parametrize_unit(sm, uid, gem, log=lambda *a: None)  # the run's own path: the unit's analysis, committed through the sheet's checks
    assert gem.seen[0][0]["holds"] and gem.seen[0][0]["source"].startswith("aagento-bridge")
    assert all(v["ok"] for v in gem.seen[1][0]["result"]), gem.seen[1][0]["result"]

    def lines_now() -> dict[str, float]:
        w = sm.unit(uid)
        d = w.prog.datum_values({**w.prog.defaults(), **sm._values_for(w, {})})
        return {k: v * um for k, v in d.items()}

    before = lines_now()
    assert before[xr] - before[xl] == pytest.approx(2 * g["half"])
    assert sm.apply({f"{uid}.ClearHeight": g["clear"] + 500.0}).ok
    after = lines_now()
    assert after[xr] - after[xl] == pytest.approx(2 * g["half"] - 2000.0), "the cushion lost 500 mm: the barrel is 4 × 500 shorter"
    assert after[xfr] - after[xfl] == pytest.approx(g["formation"]), "the formation keeps its width"
    assert (after[xr] - after[xfr]) / (after[y_f] - after[y_top]) == pytest.approx(2.0), "the embankment keeps its 2H:1V"
    assert check(sm.unit(uid).prog, f"BarrelLength = {rhs}")["holds"], "and the relation still holds"
