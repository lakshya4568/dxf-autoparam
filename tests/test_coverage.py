"""How parametric a unit is, measured on the drawing's own dimensions — and the agent told so, part by part, until each is bound, renamed or kept.

Found on a real sheet: a long section got 13 tool calls and 8 named values while 33 of its 46 dimensions stayed as drawn; 29 of those measured gaps
that no value set at all (a constant offset in the set-out), so renaming could not reach them and the candidate list never showed them. Nothing said
which dimensions were left, and the run finished. Generated drawing, scripted model, real engine."""

from __future__ import annotations

import ezdxf
from test_agent import ScriptedGemini, call

from dxf_autoparam.ai.agent import agent_parametrize
from dxf_autoparam.ai.parametrize import prepare
from dxf_autoparam.coverage import dimension_rows, unit_coverage
from dxf_autoparam.topology import of
from dxf_autoparam.validator import baseline


def footing_and_stem(path) -> str:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (2000, 0), (2000, 400), (0, 400)], close=True)  # a footing
    msp.add_lwpolyline([(800, 400), (1100, 400), (1100, 2400), (800, 2400)], close=True)  # a stem on it
    msp.add_line((-1500, 1200), (3500, 1200))  # a loose level line
    msp.add_text("GROUND LEVEL", height=100, dxfattribs={"insert": (2200, 1250)})
    for base, p1, p2, angle in [((-600, 0), (0, 0), (0, 1200), 90),  # footing bottom to the level line
                                ((0, -500), (0, 0), (800, 0), 0),  # the toe
                                ((2400, 0), (2000, 400), (2000, 0), 90),  # the footing's thickness
                                ((1500, 2800), (800, 2400), (1100, 2400), 0)]:  # the stem's width
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle).render()
    doc.saveas(str(path))
    return str(path)


def regions(path):
    an, *_ = prepare(path)
    rs = of(an).regions
    footing = next(r for r in rs if abs(r.bbox[2] - r.bbox[0] - 2000) < 1e-6 and abs(r.bbox[3] - r.bbox[1] - 400) < 1e-6)
    stem = next(r for r in rs if abs(r.bbox[2] - r.bbox[0] - 300) < 1e-6)
    dims = {round(float(it.extra["measurement"])): f"D{it.index}" for it in an.drawing.items if it.dxftype == "DIMENSION"}
    return footing.id, stem.id, dims


def test_each_dimension_is_driven_unnamed_or_fixed_and_sorted_onto_the_part_it_measures(tmp_path):
    path = footing_and_stem(tmp_path / "stem.dxf")
    an, *_ = prepare(path)
    rows = {r["id"]: r for r in dimension_rows(baseline(an))}
    assert {r["status"] for r in rows.values()} == {"unnamed"}, "the engine measured every dimensioned gap, nobody named one"
    assert all(r["by"] for r in rows.values()), "each says which value moves it (what rename_values would rename)"


def test_the_agent_is_told_part_by_part_and_finish_holds_until_every_dimension_is_accounted_for(tmp_path):
    path = footing_and_stem(tmp_path / "stem.dxf")
    footing, stem, d = regions(path)
    script = [
        [call("define_parts", items=[{"name": "Footing", "type": "footing", "regions": [footing]}, {"name": "Stem", "type": "stem", "regions": [stem]}])],
        [call("define_parameters", items=[{"name": "FootingThickness", "part": "Footing", "dimension": d[400]}])],
        [call("finish", summary="done")],
        [call("coverage")],
        [call("define_parameters", items=[{"name": "ToeWidth", "part": "Footing", "dimension": d[800]},
                                          {"name": "StemThickness", "part": "Stem", "dimension": d[300]}]),
         call("keep_dimensions", items=[{"dimension": d[1200], "why": "the level line is the site's, not a size of the footing"}])],
        [call("finish", summary="done")],
    ]
    gem = ScriptedGemini(script)
    prog, _rep, info = agent_parametrize(path, gem=gem, log=lambda *a: None)
    first = gem.seen[2][0]
    assert first["done"] is False and "dimensions" in first["hint"] and "coverage" in first["hint"], first.get("hint")
    assert "1 of 4 driven" in first["dimensions"], first["dimensions"]
    cov = gem.seen[3][0]
    open_ids = {r["dimension"] for e in cov["parts"].values() for r in e.get("open", [])} | {r["dimension"] for r in cov["unassigned"]}
    assert open_ids == {d[800], d[300], d[1200]}, cov
    assert d[300] in {r["dimension"] for r in cov["parts"]["Stem"]["open"]}, "the stem's width is the stem's"
    kept = gem.seen[4][1]["result"][0]
    assert kept["ok"], kept
    assert info["complete"] and info["stopped"] == "finished", "the second finish is taken: every dimension is accounted for"
    cov = unit_coverage(prog, kept=set(info["answer"]["kept_dimensions"]))
    assert (cov["driven"], cov["kept"], cov["fixed"] + cov["unnamed"]) == (3, 1, 0), {k: cov[k] for k in ("driven", "kept", "fixed", "unnamed")}


def test_a_kept_dimension_needs_a_dimension_of_the_unit_and_a_reason(tmp_path):
    path = footing_and_stem(tmp_path / "stem.dxf")
    _footing, _stem, d = regions(path)
    script = [[call("keep_dimensions", items=[{"dimension": "D9999", "why": "x"}, {"dimension": d[1200], "why": " "}, {"dimension": d[400], "why": "fixed by the site"}])],
              [call("finish", summary="done")]]
    gem = ScriptedGemini(script)
    agent_parametrize(path, gem=gem, log=lambda *a: None)
    got = {v["item"]: v for v in gem.seen[0][0]["result"]}
    assert not got["D9999"]["ok"] and not got[d[1200]]["ok"] and got[d[400]]["ok"], got


def test_the_coverage_of_a_parametrized_unit_counts_what_its_answer_left_as_drawn(tmp_path):
    path = footing_and_stem(tmp_path / "stem.dxf")
    footing, _stem, d = regions(path)
    script = [[call("define_parts", items=[{"name": "Footing", "type": "footing", "regions": [footing]}]),
               call("define_parameters", items=[{"name": "FootingThickness", "part": "Footing", "dimension": d[400]}])],
              [call("finish", summary="done")], [call("finish", summary="done")]]
    gem = ScriptedGemini(script)
    prog, _rep, _info = agent_parametrize(path, gem=gem, log=lambda *a: None)
    cov = unit_coverage(prog)
    assert cov["driven"] == 1 and cov["driven"] + cov["unnamed"] + cov["fixed"] == 4, {k: cov[k] for k in ("driven", "unnamed", "fixed")}


def test_a_part_of_a_known_kind_gets_what_such_a_part_has_from_the_library_and_only_with_the_library(tmp_path):
    from dxf_autoparam.ai import library

    lib = library.open_domain("bridge")
    assert [c["id"] for c in lib.component_cards({"return", "wall"})][:1] == ["return_wall"]
    assert lib.component_cards({"wall"}) == [], "every word of a name: a wall is not a return wall"
    assert lib.reference("component:return_wall")["found"] and not lib.reference("component:nothing")["found"]
    path = footing_and_stem(tmp_path / "stem.dxf")
    footing, stem, _d = regions(path)
    for pack in ("bridge", None):
        script = [[call("define_parts", items=[{"name": "ReturnWall", "type": "return_wall", "regions": [stem]},
                                               {"name": "Footing", "type": "footing", "regions": [footing]}])],
                  [call("coverage")], [call("finish", summary="done")], [call("finish", summary="done")]]
        gem = ScriptedGemini(script)
        agent_parametrize(path, gem=gem, log=lambda *a: None, domain_name=pack)
        cov = gem.seen[1][0]
        rows = {p: e for p, e in cov["parts"].items()} | {q["part"]: q for q in cov.get("parts_without_dimensions", [])}
        if pack:
            know = rows["ReturnWall"]["knowledge"]
            assert know["component"] == "component:return_wall" and any(t.startswith("ToeWidth") for t in know["parameters"]), know
            assert any("FootingWidth" in r for r in know["relations"]) and "cross_view" in know
            assert "knowledge" not in rows.get("Footing", {}), "no card names a plain footing"
        else:
            assert not any("knowledge" in e for e in rows.values()), "without the library the model names things itself"



def test_a_dimension_that_writes_another_number_than_it_measures_is_said_to_disagree(tmp_path):
    """A drafter's number over geometry not drawn to it (a real sheet: a dimension measuring 3425 that says 3600): the number cannot follow any change
    of the geometry, so the agent and the page are told — never silently counted as following."""
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (3425, 0), (3425, 400), (0, 400)], close=True)
    msp.add_linear_dim(base=(0, -500), p1=(0, 0), p2=(3425, 0), text="3600").render()  # the drafter's number
    msp.add_linear_dim(base=(3900, 0), p1=(3425, 0), p2=(3425, 400), angle=90, text="<>").render()  # the measurement
    msp.add_linear_dim(base=(0, 900), p1=(0, 400), p2=(3425, 400), text="3.425 M").render()  # the measurement, in metres
    path = str(tmp_path / "written.dxf")
    doc.saveas(path)
    an, *_ = prepare(path)
    rows = sorted(dimension_rows(baseline(an)), key=lambda r: r["mm"])
    assert [(r["mm"], r.get("writes")) for r in rows] == [(400.0, None), (3425.0, 3600.0), (3425.0, None)] or \
        [(r["mm"], r.get("writes")) for r in rows] == [(400.0, None), (3425.0, None), (3425.0, 3600.0)]
    cov = unit_coverage(baseline(an))
    briefs = [b for e in cov["parts"].values() for b in e.get("open", [])] + cov["unassigned"]
    assert any("writes 3600 but measures 3425 mm" in (b.get("disagrees") or "") for b in briefs)


def test_a_sum_the_sheet_already_works_out_is_driven_and_binding_it_as_an_input_is_refused(tmp_path, monkeypatch):
    """The agent's workbench works on its answer without what the engine derived (which side of each size stays). There the box's overall width
    looked free: listed as a dimension to bind, it was bound as an input, held the outer faces, and a wider clear span could then only run into the
    wall between the cells — the 2- and 4-cell boxes fell from 88 % to 50 % and 40 % of their dimensions editable. As the sheet stands the overall
    width is a result of the clear span and the walls: driven, never listed, and refused as an input with what it is made of."""
    from types import SimpleNamespace

    from test_intent_plan import box_sheet

    from dxf_autoparam import design_intent
    from dxf_autoparam.ai.agent import Workbench
    from dxf_autoparam.ai.context import SheetScope
    from dxf_autoparam.ai.loop import Budget, LoopState, execute_calls
    from dxf_autoparam.plan_bench import Box
    from dxf_autoparam.viewimg import box_around

    monkeypatch.setenv("AUTOPARAM_DOMAIN", "bridge")
    sm, uid, _g = box_sheet(tmp_path, Box(cells=2))
    u = sm.unit(uid)
    wb = Workbench(sm.path, region=box_around([sm.layout.group(v).bbox for v in u.views], 0.0), start=design_intent.strip(u.answer), drawing=u.sub,
                   analysis=sm.pristine_analysis(uid), scope=SheetScope(sm, uid))
    rows = wb._coverage()["rows"]
    summed = [r for r in rows if r.get("as_the_sheet_stands")]
    assert summed and all(r["status"] == "driven" for r in summed)
    overall = max(summed, key=lambda r: r["mm"])
    assert "ClearSpan" in overall["by"], overall
    assert overall["id"] not in {b["dimension"] for e in wb.coverage()["parts"].values() for b in e.get("open", [])}, "never listed as open"
    parts, _ = execute_calls(wb, [SimpleNamespace(name="define_parameters", args={"items": [{"name": "OverallWidth", "dimension": overall["id"]}]})],
                             lambda e: None, LoopState(), Budget(), {})
    (v,) = parts[0].function_response.response["result"]["result"]
    assert not v["ok"] and v["failure"]["code"] == "SUM" and "ClearSpan" in v["failure"]["measured"] and "set_relation" in v["failure"]["hint"]
    assert "OverallWidth" not in wb.prog.params, "nothing written"
