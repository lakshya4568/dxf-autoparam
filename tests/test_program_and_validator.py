"""The parametric program and the deterministic validator — no AI calls: proposals are written here,
true ones must be accepted and false ones rejected with the right reason."""

from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest

from dxf_autoparam.analyse import analyse
from dxf_autoparam.build import Decisions, build
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.dxf_write import audit, write_dxf
from dxf_autoparam.ir import GapKind
from dxf_autoparam.program import ExprError, evaluate, from_model, names_in
from dxf_autoparam.regen import regenerate_program
from dxf_autoparam.topology import DatumIndex
from dxf_autoparam.topology import of as topo_of
from dxf_autoparam.validator import apply

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT.parent / "aagento-bridge" / "public" / "test-fixtures" / "dxf"
EXAMPLES = sorted((ROOT / "examples").glob("*.dxf"))


def two_cell():
    dr, _ = read_dxf(str(ROOT / "examples" / "two_cell_box_section.dxf"))
    return analyse(dr)


def cluster(an, kind: GapKind, value_mm: float, axis: str | None = None) -> str:
    for c in an.clusters.values():
        if c.kind == kind and abs(c.value * an.drawing.units_mm - value_mm) < 0.5 and (axis is None or axis in c.axes):
            return c.id
    raise AssertionError(f"no {kind} cluster of {value_mm}")


# ── reading ────────────────────────────────────────────────────────────────────


def test_views_stored_as_blocks_are_read():
    f = FIXTURES / "gad_ezdxf_a.dxf"
    if not f.exists():
        pytest.skip("fixture not on this machine")
    dr, _ = read_dxf(str(f))
    assert len(dr.items) > 1000  # 23 block references holding ~2000 entities, not 26 insertion points
    assert sum(1 for it in dr.items if "/" in it.src) > 1000


def test_a_malformed_file_is_rebuilt_not_refused():
    f = FIXTURES / "drawing2.dxf"
    if not f.exists():
        pytest.skip("fixture not on this machine")
    dr, _ = read_dxf(str(f))
    assert any("rebuilt" in n for n in dr.notes)
    assert dr.units_mm == 1.0  # the header claims metres; the dimensions say millimetres
    assert len(dr.items) > 50


# ── the program ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_the_program_reproduces_the_drawing_exactly(path):
    dr, _ = read_dxf(str(path))
    an = analyse(dr)
    prog = from_model(build(an, Decisions()))
    r = regenerate_program(prog)
    err = max(math.dist(r.pts[it.index][k], p) for it in dr.items if it.index in r.pts for k, p in enumerate(it.pts))
    assert err * dr.units_mm < 1e-3


def test_expressions_are_a_safe_small_language():
    assert evaluate("x1 + 2 * ClearSpan - max(1, 2)", {"x1": 10, "ClearSpan": 5}) == 18
    assert names_in("y5 + ClearHeight * 0.5") == {"y5", "ClearHeight"}
    for bad in ("__import__('os')", "x.attr", "[1, 2]", "lambda: 1", "'text'"):
        with pytest.raises(ExprError):
            evaluate(bad, {})


# ── the validator ──────────────────────────────────────────────────────────────


def true_answer(an):
    span = cluster(an, GapKind.VOID, 3000, "x")
    wall = cluster(an, GapKind.SOLID, 350, "x")
    u = an.drawing.units_mm
    # the outer faces of the box, to state a relation between them
    xs = sorted((d for d in an.datums.values() if d.axis == "x" and not d.virtual), key=lambda d: d.value)
    outer_l = next(d for d in xs if abs(d.value * u - 0) < 0.5)
    outer_r = next(d for d in xs if abs(d.value * u - 7000) < 0.5)
    ys = sorted((d for d in an.datums.values() if d.axis == "y" and not d.virtual), key=lambda d: d.value)
    base_top = next(d for d in ys if abs(d.value * u - 400) < 0.5)
    soffit = next(d for d in ys if abs(d.value * u - 3400) < 0.5)
    return {
        "structure_type": "RCC box culvert, 2 cells", "family": "rcc_box", "views": ["section"], "summary": "",
        "components": [{"name": "Box", "type": "box", "outlines": [], "datums": [], "description": ""}],
        "levels": [],
        "parameters": [
            {"name": "ClearSpan", "label": "Clear span", "component": "Box", "kind": "length", "candidate": span, "value": 3000},
            {"name": "OuterWall", "label": "Outer wall", "component": "Box", "kind": "length", "candidate": wall, "value": 350},
            {"name": "ClearHeight", "label": "Clear height", "component": "Box", "kind": "length", "from_datum": base_top.id,
             "to_datum": soffit.id, "value": 3000},
        ],
        "datum_formulas": [{"datum": soffit.id, "expr": f"{base_top.id} + ClearHeight"}],
        "relations": [{"name": "OverallWidth", "label": "Overall width", "expr": "2 * ClearSpan + 2 * OuterWall + 300",
                       "from_datum": outer_l.id, "to_datum": outer_r.id}],
        "questions": [],
    }


def test_true_claims_are_accepted_and_drive_the_drawing(tmp_path):
    an = two_cell()
    ans = true_answer(an)
    prog, rep = apply(an, ans)
    assert not rep.errors(), rep.errors()
    assert {"ClearSpan", "OuterWall", "ClearHeight"} <= set(prog.params)
    assert prog.params["ClearSpan"].occurrences == 2  # both cells, one value
    rel = next(r for r in prog.relations if r.name == "OverallWidth")
    r = regenerate_program(prog, {"ClearSpan": 4000, "ClearHeight": 3500})
    assert not r.issues
    assert abs(prog.relation_value(rel, {"ClearSpan": 4000}) - 9000) < 1e-6
    out = tmp_path / "box.dxf"
    write_dxf(prog, r, str(out))
    assert audit(str(out))["errors"] == 0


@pytest.mark.parametrize(
    "mutate, code",
    [
        (lambda a, an: a["parameters"][0].update(value=3100), "V2"),  # value not what the geometry measures
        (lambda a, an: a["parameters"][0].update(candidate="c999"), "V1"),  # no such candidate
        (lambda a, an: a["parameters"][1].update(name="outer wall"), "V3"),  # not a PascalCase name
        (lambda a, an: a["parameters"][1].update(name="GapX3"), "V3"),  # a generic placeholder, not a name
        (lambda a, an: a["datum_formulas"][0].update(expr=a["datum_formulas"][0]["expr"] + " + 50"), "V5"),  # moves the line
        (lambda a, an: a["datum_formulas"][0].update(expr="Nonsense + 1"), "V4"),  # unknown name
        (lambda a, an: a["datum_formulas"].append({"datum": a["datum_formulas"][0]["expr"].split()[0],
                                                    "expr": a["datum_formulas"][0]["datum"] + " - ClearHeight"}), "V4"),  # a cycle
        (lambda a, an: a["relations"][0].update(expr="2 * ClearSpan + 2 * OuterWall"), "V7"),  # does not equal what it measures
        (lambda a, an: a["parameters"][2].update(to_datum="x0"), "V1"),  # datums on different axes
    ],
    ids=["wrong-value", "unknown-candidate", "not-pascal", "generic-name", "formula-moves-line", "unknown-name", "cycle",
         "relation-mismatch", "mixed-axes"],
)
def test_false_claims_are_rejected_with_the_reason(mutate, code):
    an = two_cell()
    ans = true_answer(an)
    mutate(ans, an)
    prog, rep = apply(an, ans)
    assert code in {f["code"] for f in rep.errors()}, rep.errors()
    # and the drawing still regenerates exactly — a rejected claim never reaches the model
    r = regenerate_program(prog)
    err = max(math.dist(r.pts[it.index][k], p) for it in an.drawing.items if it.index in r.pts for k, p in enumerate(it.pts))
    assert err < 1e-6


def test_levels_held_as_site_inputs_stay_put_when_the_structure_changes():
    dr, _ = read_dxf(str(ROOT / "examples" / "rcc_box_half_section_half_elevation.dxf"))
    an = analyse(dr)
    stated = {words: d for d, _i, words, _v in an.stated_levels}
    bed = next(d for w, d in stated.items() if "BED" in w)
    formation = next(d for w, d in stated.items() if "FORMATION" in w)
    hfl = next(d for w, d in stated.items() if "HFL" in w)
    span = cluster(an, GapKind.SOLID, 10700) if any(abs(c.value - 10700) < 0.5 for c in an.clusters.values()) else None
    ans = {"structure_type": "", "family": "rcc_box", "views": [], "summary": "", "components": [], "datum_formulas": [], "relations": [],
           "questions": [], "parameters": [{"name": "ClearSpan", "label": "", "component": "Box", "kind": "length", "candidate": span, "value": 10700}] if span else [],
           "levels": [{"datum": bed, "name": "BedLevel", "role": "site_input"}, {"datum": formation, "name": "FormationLevel", "role": "site_input"},
                      {"datum": hfl, "name": "Hfl", "role": "check_only"}]}
    prog, rep = apply(an, ans)
    assert not rep.errors(), rep.errors()
    assert prog.params["FormationLevel"].value == pytest.approx(105.0)
    before = prog.datum_values()
    biggest = max((p for p in prog.params.values() if p.kind == "length"), key=lambda p: p.value)
    after = prog.datum_values({biggest.name: biggest.value * 1.1})
    assert after[formation] == pytest.approx(before[formation])
    assert after[bed] == pytest.approx(before[bed])
    lifted = prog.datum_values({"FormationLevel": 106.0})
    assert lifted[formation] * dr.units_mm == pytest.approx(106000)


def test_a_check_only_level_that_is_the_end_of_a_size_is_left_free():
    """check_only holds a line fixed and never sets out from it; a size the answer defines to that line could then never move it."""
    an = two_cell()
    u = an.drawing.units_mm
    ans = true_answer(an)
    soffit = next(d for d in an.datums.values() if d.axis == "y" and not d.virtual and abs(d.value * u - 3400) < 0.5)
    ans["levels"] = [{"datum": soffit.id, "name": "SoffitLevel", "role": "check_only"}]
    prog, rep = apply(an, ans)
    assert not rep.errors(), rep.errors()
    said = [f for f in rep.findings if f.code == "V6" and f.item == "SoffitLevel"]
    assert said and "ClearHeight" in said[0].message and "derived" in said[0].message
    assert "SoffitLevel" not in prog.params  # not held
    assert (prog.datum_values({"ClearHeight": 3500})[soffit.id] - prog.datum_values()[soffit.id]) * u == pytest.approx(500)


def test_a_check_only_level_on_a_face_of_a_proposed_part_is_kept_with_a_word_and_existing_work_and_water_levels_are_not_touched():
    """A line that is only a face keeps what was said (a level input); the answer is told that a check-only level is held fixed."""
    an = two_cell()
    dix = DatumIndex(an)
    region = next(r for r in topo_of(an).regions if dix.of_ring(r.ring)[1])
    face = dix.of_ring(region.ring)[1][0]
    aside = next(d.id for d in an.datums.values() if d.axis == "y" and not d.virtual and d.id not in dix.of_ring(region.ring)[1])  # not on the part
    base = {"structure_type": "", "family": "other", "views": [], "summary": "", "parameters": [], "datum_formulas": [], "relations": [],
            "questions": [], "components": [{"name": "Box", "type": "box", "regions": [region.id]}]}
    prog, rep = apply(an, {**base, "levels": [{"datum": face, "name": "FaceLevel", "role": "check_only"}]})
    said = [f for f in rep.findings if f.code == "V6" and f.item == "FaceLevel" and "a face of Box" in f.message and "derived" in f.message]
    assert said and "FaceLevel" in prog.params, "told, and kept: the level stays an input"
    existing = {**base, "components": [{**base["components"][0], "existing": True}]}  # existing work is held as drawn anyway
    prog, rep = apply(an, {**existing, "levels": [{"datum": face, "name": "FaceLevel", "role": "check_only"}]})
    assert "FaceLevel" in prog.params and not any(f.code == "V6" and "check-only" in f.message for f in rep.findings)
    prog, rep = apply(an, {**base, "levels": [{"datum": aside, "name": "WaterLevel", "role": "check_only"}]})  # a line the part is not drawn on
    assert "WaterLevel" in prog.params and not any(f.code == "V6" and "check-only" in f.message for f in rep.findings)


def test_values_saved_at_another_scale_are_measured_again_only_when_every_one_is_off_by_the_same_drafting_ratio():
    """A value is the engine's own measurement of what the parameter names. When a unit used to be read at another scale (a detail drawn at 1:25 on a
    1:100 sheet), every value saved then is the same measurement times one ratio: they are measured again. Anything else is the validator's to refuse."""
    from dxf_autoparam.validator import rescale_values

    an = two_cell()
    ans = true_answer(an)
    base = {p["name"]: p["value"] for p in ans["parameters"]}

    def scaled(factor) -> dict:
        out = copy.deepcopy(ans)
        for p in out["parameters"]:
            p["value"] = p["value"] * factor(p["name"])
        return out

    fixed, ratio = rescale_values(an, scaled(lambda n: 4.0))
    assert ratio == pytest.approx(4.0) and {p["name"]: p["value"] for p in fixed["parameters"]} == pytest.approx(base)
    assert not apply(an, fixed)[1].errors(), "and the answer is accepted again"
    assert rescale_values(an, ans) == (ans, None), "values that agree with the drawing are left alone"
    assert rescale_values(an, scaled(lambda n: 4.0 if n == "ClearSpan" else 1.0))[1] is None, "one value off: that is a wrong value, the validator says so"
    assert rescale_values(an, scaled(lambda n: 2.0 if n == "OuterWall" else 4.0))[1] is None, "two ratios are not one scale"
    assert rescale_values(an, scaled(lambda n: 40.0))[1] is None, "and 40 is not a drafting scale"
    assert rescale_values(an, {**ans, "parameters": []}) == ({**ans, "parameters": []}, None)


def test_the_work_saved_for_a_detail_before_it_was_read_at_its_own_scale_is_kept_not_dropped(tmp_path):
    """A detail at 1:25 was read at the sheet's scale, so the agent's names for it carried values four times the drawing's and the engine now refuses them
    (V2). The names, parts and levels are the work: the values are measured again, a stepped value goes with them, and the unit says so."""
    from test_sheet import built_sheet

    from dxf_autoparam.crossview import EMPTY_ANSWER, SheetModel

    sm = SheetModel.open(str(built_sheet(tmp_path / "s.dxf", automatic_detail_dims=True)))
    uid = sm.unit_of_view[next(g.id for g in sm.layout.views() if g.name == "DETAIL OF WALL")]
    an = sm.pristine_analysis(uid)
    um = an.drawing.units_mm
    sized = [c for c in an.clusters.values() if c.kind in (GapKind.SOLID, GapKind.VOID) and any(an.gaps[g].axis in ("x", "y") for g in c.gaps)][:2]
    assert len(sized) == 2 and um == pytest.approx(0.25)
    rows = [{"name": name, "label": "", "component": "", "kind": "length", "candidate": c.id, "value": round(c.value * um * 4, 6)} for name, c in zip(("WallTop", "FootingStep"), sized, strict=True)]
    u = sm.units[uid]
    u.answer, u.prog = {**copy.deepcopy(EMPTY_ANSWER), "parameters": rows}, None  # as saved by the old reading
    sm.values[uid] = {"WallTop": rows[0]["value"] * 1.1}  # a person had stepped it
    prog = sm.unit(uid).prog
    assert {"WallTop", "FootingStep"} <= set(prog.params) and not u.report.errors()
    assert prog.params["WallTop"].value == pytest.approx(sized[0].value * um)
    assert sm.values[uid]["WallTop"] == pytest.approx(sized[0].value * um * 1.1), "the stepped value is on the new scale too"
    assert any("read at its own scale" in f.message for f in u.report.findings)
    assert [p["value"] for p in u.answer["parameters"]] == pytest.approx([c.value * um for c in sized]), "and the saved answer says what the drawing measures"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_the_fast_change_checks_equal_a_full_regeneration(path):
    """The ±10 % checks recompute only the lines downstream of the changed value and check only the entities that
    move (big sheets: 12k lines × 600 values). They must report exactly what a full regeneration reports."""
    from dxf_autoparam.regen import check_change, datum_users
    from dxf_autoparam.validator import baseline

    dr, _ = read_dxf(str(path))
    prog = baseline(analyse(dr))
    plan, users, base = prog.change_plan(), datum_users(prog.analysis), regenerate_program(prog, check=False).datum
    for p in prog.params.values():
        for dv in (max(p.value * 0.1, 10.0), -max(p.value * 0.1, 10.0), -2 * p.value):
            vals = {p.name: p.value + dv}
            full, fast = prog.datum_values(vals), prog.datum_values_changed(vals, plan)
            assert full.keys() == fast.keys() and all(math.isclose(full[d], fast[d], abs_tol=1e-9) for d in full), (p.name, dv)
            assert check_change(prog, vals, base, users, plan) == regenerate_program(prog, vals).issues, (p.name, dv)
