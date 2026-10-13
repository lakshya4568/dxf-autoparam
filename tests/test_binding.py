"""Exact binding through the agent's real tools and validation path — no model call (Gemini is a script).

The agent receives the context of its view / unit, resolves the labels it sees, inspects candidate OCCURRENCES and
annotations, binds sizes to the occurrences it means (equal values stay separate sizes until it says so), and gets a
deterministic verdict for every edit — with the binding, its references, expected vs measured, the cause, and whether
it can repair it or a person must decide. Accepted bindings are measured (they drive what they name, nothing fixed
moves, the drawing is reproduced); a sheet unit's result lands only through the sheet's commit-or-refuse path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_agent import BOX, ScriptedGemini, call
from test_crossview import mini_gad
from test_sheet import FIXTURES

from dxf_autoparam.ai.agent import Workbench, agent_parametrize
from dxf_autoparam.ai.context import SheetScope, unit_context
from dxf_autoparam.ai.parametrize import prepare
from dxf_autoparam.ai.sheet_ai import parametrize_unit
from dxf_autoparam.crossview import SheetError, SheetModel
from dxf_autoparam.topology import of

GAD_A = FIXTURES / "gad_ezdxf_a.dxf"


def box_ids():
    """The two-cell box section: the concrete, its two cells, and the candidate 'clear span' (equal in both cells)."""
    an, *_ = prepare(BOX)
    regions = of(an).regions
    concrete = max(regions, key=lambda r: len(r.holes))
    cells = sorted((r for r in regions if r.parent == concrete.id), key=lambda r: r.bbox[0])
    span = next(c for c in an.clusters.values() if c.kind.value == "void" and round(c.value * an.drawing.units_mm) == 3000 and "x" in c.axes)
    left, right = sorted(span.gaps, key=lambda g: an.datums[an.gaps[g].a].value)
    return concrete.id, cells[0].id, cells[1].id, span.id, left, right, an


def by_item(verdicts):
    return {v["item"]: v for v in verdicts}


def batch(seen_step, k):
    r = seen_step[k]
    return r["result"] if isinstance(r, dict) and "result" in r else r


# ── 1. context and reference resolution ────────────────────────────────────────


@pytest.mark.skipif(not GAD_A.exists(), reason="aagento-bridge fixtures not present")
def test_the_agent_starts_from_the_context_of_its_view_and_unit_and_resolves_its_labels():
    sm = SheetModel.open(str(GAD_A))
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    scope = SheetScope(sm, uid)
    bench = Workbench(sm.path, analysis=sm.pristine_analysis(uid), scope=scope)
    ctx = unit_context(sm, uid, bench.an, bench.prog, {}, bench.rep)
    assert ctx["drawing"]["unit"] == uid and ctx["drawing"]["sheet_revision"] == sm.revision and len(ctx["drawing"]["sha256_16"]) == 16
    assert [v["id"] for v in ctx["views"]] == sm.units[uid].views
    assert any(p["one_unit"] and set(p["views"]) == set(sm.units[uid].views) for p in ctx["projection"])
    eq = ctx["equal_sizes [candidate, mm, kind, occurrences g:from-to] (bind only the occurrences you mean)"]
    assert eq and all(len(row[3]) > 1 and all(o.startswith("g") for o in row[3]) for row in eq)
    # every label resolves to what the tools and the validator use — or is refused
    line, cand = next(iter(bench.an.datums)), eq[0][0]
    occ = eq[0][3][0].split(":")[0]
    got = bench.resolve_labels([line, cand, occ, sm.units[uid].views[0], uid, "R1", "zz9"])
    assert got[line]["is"] == "set-out line" and got[cand]["is"] == "candidate" and got[occ]["candidate"] == cand
    assert got[sm.units[uid].views[0]]["in_this_unit"] and got[uid]["this_unit"] and got["R1"]["is"] == "region"
    assert got["zz9"] == "no such reference in this drawing"


def test_the_overview_the_agent_reads_opens_with_its_context():
    gem = ScriptedGemini([[call("finish", summary="look")], [call("finish", summary="stop")]])
    seen = {}
    real = gem.step

    def step(system, tools, prefix_parts, *a, **k):
        seen.setdefault("overview", prefix_parts[-1].text)
        return real(system, tools, prefix_parts, *a, **k)

    gem.step = step
    _prog, _rep, info = agent_parametrize(BOX, gem=gem, log=lambda *a: None)
    ov = json.loads(seen["overview"].split("OVERVIEW:\n", 1)[1])
    assert next(iter(ov)) == "CONTEXT" and ov["CONTEXT"]["drawing"]["file"] == Path(BOX).name
    assert info["context"]["references"]["labelled_on_set_out_picture"]  # the picture's labels are listed by the same ids
    assert info["baseline_error_mm"] < 1e-6


# ── 2. candidate occurrences ───────────────────────────────────────────────────


def test_a_candidates_occurrences_are_inspected_one_by_one():
    _c, cell_l, cell_r, span, left, right, _an = box_ids()
    bench = Workbench(BOX)
    got = bench.inspect_candidates([span, "c999"])[span]
    assert got["value_mm"] == 3000 and len(got["occurrences"]) == 2 and got["evidence"]
    occ = {o["occurrence"]: o for o in got["occurrences"]}
    assert set(occ) == {left, right}
    for g in (left, right):
        o = occ[g]
        assert set(o["ends"]) == set(o["between"]) and all("formula" in e and "set_by" in e for e in o["ends"].values())
        assert o["driven_by"] == []  # nothing named yet
    assert occ[left]["regions"] == [cell_l] and occ[right]["regions"] == [cell_r]  # each occurrence is its own cell
    assert bench.inspect_candidates(["c999"])["c999"] == "no such candidate"


# ── 3, 4, 5, 7. binding, invalid references, equal values, cycles / ownership, measured behaviour ──


def test_bindings_name_exact_occurrences_and_bad_ones_are_refused_with_actionable_reasons():
    concrete, cell_l, cell_r, span, left, right, an = box_ids()
    script = [
        [call("define_parts", items=[{"name": "Box", "type": "box", "level": "assembly", "regions": [concrete]},
                                     {"name": "CellLeft", "type": "cell", "level": "subcomponent", "parent": "Box", "regions": [cell_l]},
                                     {"name": "CellRight", "type": "cell", "level": "subcomponent", "parent": "Box", "regions": [cell_r]}]),
         call("define_parameters", items=[
             {"name": "Span", "part": "Box", "candidate": span},                                   # which of the two? refused
             {"name": "LeftSpan", "part": "CellLeft", "candidate": span, "occurrences": [left]},   # this one only
             {"name": "RightSpan", "part": "CellRight", "candidate": span, "occurrences": [right]},  # an equal size, its own
             {"name": "Ghost", "part": "Box", "candidate": span, "occurrences": ["g999"]},         # no such occurrence
             {"name": "Nowhere", "part": "Box", "candidate": "c999"},                               # no such candidate
             {"name": "Twice", "part": "Box", "candidate": span, "occurrences": [left]},           # already LeftSpan's
             {"name": "BadDim", "part": "Box", "dimension": "D99999"}])],                            # no such annotation
        [call("set_formulas", items=[{"line": an.gaps[left].a, "expr": f"{an.gaps[left].a} + LeftSpan"}]),  # a loop on itself
         call("what_moves", parameter="LeftSpan")],
        [call("finish", summary="done")], [call("finish", summary="stop")],
    ]
    gem = ScriptedGemini(script)
    prog, _rep, info = agent_parametrize(BOX, gem=gem, log=lambda *a: None)
    v = by_item(batch(gem.seen[0], 1))
    # the multi-occurrence candidate without a choice: refused before anything is written, with where it is
    assert not v["Span"]["ok"] and v["Span"]["failure"]["code"] == "OCCURRENCES" and v["Span"]["failure"]["repair"] == "agent"
    assert {left, right} <= set(v["Span"]["failure"]["refs"]) and "Span" not in [p["name"] for p in info["answer"]["parameters"]]
    # the exact ones: accepted, each driving its own occurrence only, and saying which end grows
    for name, g in (("LeftSpan", left), ("RightSpan", right)):
        assert v[name]["ok"] and v[name]["drives"] == [g] and " moves, " in v[name]["grows"] and "Box" in v[name]["moves"]
    # invalid references and an ownership conflict: deterministic, structured, repairable by the agent
    assert v["Ghost"]["failure"]["code"] == "V1" and "g999" in v["Ghost"]["failure"]["cause"]
    assert v["Nowhere"]["failure"]["code"] == "V1"
    assert v["Twice"]["failure"]["code"] == "V12" and "LeftSpan" in v["Twice"]["failure"]["cause"]
    assert v["BadDim"]["failure"]["code"] == "V1" and v["BadDim"]["failure"]["refs"] == ["D99999"]
    assert all({"code", "binding", "refs", "expected", "measured", "cause", "repair", "hint"} <= set(x["failure"]) for x in v.values() if not x["ok"])
    # a formula loop is refused (V4), never applied
    loop = batch(gem.seen[1], 0)[0]
    assert not loop["ok"] and loop["failure"]["code"] == "V4"
    # the behaviour is MEASURED after the edit: the left cell grows, the right one does not move
    moves = batch(gem.seen[1], 1)
    assert moves["drawing_valid"] and "CellLeft" in moves["moves"] and "CellRight" in moves["fixed"]
    u = an.drawing.units_mm
    v0, v1 = prog.datum_values(), prog.datum_values({"LeftSpan": 3500.0})
    g_l, g_r = an.gaps[left], an.gaps[right]
    assert abs(abs(v1[g_l.b] - v1[g_l.a]) * u - 3500) < 1e-6 and abs(abs(v1[g_r.b] - v1[g_r.a]) * u - 3000) < 1e-6
    assert all(abs(v1[d] - v0[d]) < 1e-12 for d in (g_r.a, g_r.b))  # equal value, separate size: it stays
    assert info["baseline_error_mm"] < 1e-6  # the drawing at its current values is still exactly the drawing


def test_a_dimension_binds_the_one_occurrence_it_is_tied_to_and_an_untied_note_is_refused(tmp_path):
    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    bench = Workbench(sm.path, analysis=sm.pristine_analysis(uid), scope=SheetScope(sm, uid))
    dims = {d["id"]: d for d in (bench.inspect_dimensions([x["id"] for x in bench.inspect_dimensions() if x["kind"] == "dimension"])).values()}
    wall = next(d for d in dims.values() if d["states_mm"] == 300 and d["bindable"])
    _item, _note = bench.write("define_parameter", {"name": "LeftWall", "part": "", "dimension": wall["id"]})
    row = next(p for p in bench.answer["parameters"] if p["name"] == "LeftWall")
    occ = wall["tied_to"][0].split(" ")[0]
    assert row["occurrences"] == [occ] and row["candidate"] == bench.an.gaps[occ].cluster  # its own occurrence, not every 300
    bench.validate()
    info, failure = bench.binding_check("LeftWall")
    assert failure is None and info["drives"] == [occ]


# ── 6. held / fixed geometry ───────────────────────────────────────────────────


def test_a_part_kept_as_drawn_never_moves_and_binding_its_size_needs_the_person():
    concrete, cell_l, cell_r, span, left, right, _an = box_ids()
    script = [
        [call("define_parts", items=[{"name": "Box", "type": "box", "level": "assembly", "regions": [concrete]},
                                     {"name": "CellLeft", "type": "cell", "level": "subcomponent", "parent": "Box", "regions": [cell_l]},
                                     {"name": "CellRight", "type": "cell", "level": "subcomponent", "parent": "Box", "regions": [cell_r],
                                      "parametrize": False}]),  # the person keeps the right cell as drawn
         call("define_parameters", items=[{"name": "RightSpan", "part": "CellRight", "candidate": span, "occurrences": [right]},
                                          {"name": "LeftSpan", "part": "CellLeft", "candidate": span, "occurrences": [left]}])],
        [call("finish", summary="done")], [call("finish", summary="stop")],
    ]
    gem = ScriptedGemini(script)
    prog, _rep, info = agent_parametrize(BOX, gem=gem, log=lambda *a: None)
    v = by_item(batch(gem.seen[0], 1))
    assert not v["RightSpan"]["ok"] and v["RightSpan"]["failure"]["code"] == "FIXED" and v["RightSpan"]["failure"]["repair"] == "person"
    assert v["RightSpan"]["taken_back"] and "RightSpan" not in [p["name"] for p in info["answer"]["parameters"]]
    assert v["LeftSpan"]["ok"]
    # with the person's hold applied, changing the left span leaves every line of the held cell where it is drawn
    cell = prog.intent["parts"]["CellRight"]
    v0, v1 = prog.datum_values(), prog.datum_values({"LeftSpan": 4000.0})
    assert cell.datums and all(abs(v1[d] - v0[d]) < 1e-12 for d in cell.datums if d in v0)


# ── 8, 10. the sheet path: scripted agent on a unit, cross-view propagation, transactional refusal ──


def test_a_unit_parametrized_by_the_agent_lands_through_the_sheet_and_shared_sizes_follow(tmp_path):
    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    other = next(k for k in sm.units if k != uid)
    sm.share("OuterWall", [(uid, "c0"), (other, "c0")])
    rev = sm.revision
    an = sm.pristine_analysis(uid)
    u = an.drawing.units_mm
    span = next(c.id for c in an.clusters.values() if round(c.value * u) == 2400 and "x" in c.axes)
    script = [
        [call("resolve_labels", labels=["c0", uid]), call("inspect_candidates", ids=[span]), call("inspect_dimensions", ids=[])],
        [call("define_parameters", items=[{"name": "ClearSpan", "part": "", "candidate": span, "occurrences": ["all"]}]),
         call("remove", parameters=["OuterWall"])],   # a size another view follows: not the agent's to drop
        [call("finish", summary="done")], [call("finish", summary="stop")],
    ]
    gem = ScriptedGemini(script)
    res = parametrize_unit(sm, uid, gem, log=lambda *a: None)
    labels, cand, dims = gem.seen[0]
    assert labels["c0"]["is"] == "candidate" and labels[uid]["this_unit"] and cand[span]["occurrences"] and dims
    defined, removed = gem.seen[1][0], gem.seen[1][1]
    assert defined[0]["ok"]
    removed = removed.get("result", removed)
    assert not removed["ok"] and removed["failure"]["code"] == "SHARED" and removed["failure"]["repair"] == "person"
    assert res["revision"] == rev + 1 and sm.revision == rev + 1  # committed, once
    assert "ClearSpan" in sm.units[uid].prog.params and "OuterWall" in sm.units[uid].prog.params
    # a size of the unit moves its two linked views and nothing else
    r = sm.preview({f"{uid}.ClearSpan": 3000.0})
    assert r.ok and set(r.by_view) == {"V01", "V03"}
    # the shared size still drives both units: a change goes through the sheet transaction and every view follows
    r = sm.apply({"OuterWall": 400.0})
    assert r.ok and {"V01", "V02", "V03"} <= set(r.by_view) and set(r.measured["OuterWall"].values()) == {400.0}


def test_a_unit_answer_that_would_break_a_shared_size_is_refused_whole(tmp_path):
    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    other = next(k for k in sm.units if k != uid)
    sm.share("OuterWall", [(uid, "c0"), (other, "c0")])
    an = sm.pristine_analysis(uid)
    u = an.drawing.units_mm
    other_size = next(c for c in an.clusters.values() if round(c.value * u) == 2700)
    before_answer, rev, hist = json.dumps(sm.units[uid].answer, sort_keys=True), sm.revision, len(sm.history)
    gem = ScriptedGemini([
        # the agent rebinds the shared name to another size of its own unit (2700 mm, not the 300 the other view has)
        [call("define_parameters", items=[{"name": "OuterWall", "part": "", "candidate": other_size.id, "occurrences": [other_size.gaps[0]]}])],
        [call("finish", summary="done")], [call("finish", summary="stop")],
    ])
    with pytest.raises(SheetError, match="refused, nothing changed"):
        parametrize_unit(sm, uid, gem, log=lambda *a: None)
    status = gem.seen[0][0]["status"]
    assert any("NOT THE SHARED VALUE" in s for s in status["shared_here"])  # said to the agent while it worked
    assert json.dumps(sm.units[uid].answer, sort_keys=True) == before_answer and sm.revision == rev and len(sm.history) == hist
    assert sm.apply({"OuterWall": 350.0}).ok  # the sheet is as it was, and still works
    assert sm.undo() and sm.current()["OuterWall"] == 300


# ── 9. stale context ───────────────────────────────────────────────────────────


def test_a_result_worked_out_on_an_older_sheet_is_refused(tmp_path):
    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    an = sm.pristine_analysis(uid)
    span = next(c.id for c in an.clusters.values() if round(c.value * an.drawing.units_mm) == 2400 and "x" in c.axes)

    class EditsMeanwhile(ScriptedGemini):
        def step(self, *a, **k):
            if len(self.seen) == 0 and not getattr(self, "edited", False):
                sm.set_view("V02", name="SIDE WALL DETAIL")  # a person edits the sheet while Gemini works
                self.edited = True
            return super().step(*a, **k)

    gem = EditsMeanwhile([[call("define_parameters", items=[{"name": "ClearSpan", "part": "", "candidate": span, "occurrences": ["all"]}])],
                          [call("finish", summary="done")], [call("finish", summary="stop")]])
    before = sm.units[uid].answer
    with pytest.raises(SheetError, match="stale"):
        parametrize_unit(sm, uid, gem, log=lambda *a: None)
    assert "changed since you started" in gem.seen[0][0]["status"]["sheet"]  # the agent was told
    assert sm.units[uid].answer == before and sm.layout.group("V02").name == "SIDE WALL DETAIL"  # the person's edit stands


def test_the_workspace_runs_the_agent_in_the_background_and_commits_or_refuses_it(tmp_path):
    """What the agent defines reaches the sheet only through the sheet's transaction: a size another view follows that would stop driving is
    REFUSED with nothing changed — and the run says it did not apply anything, instead of reporting success."""
    import time

    from dxf_autoparam.ai.scripted import ScriptedModel
    from dxf_autoparam.workspace import SheetSession

    sheet = SheetSession(mini_gad(tmp_path / "mini.dxf"))
    sm = sheet.sm
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    other = next(k for k in sm.units if k != uid)
    sm.share("OuterWall", [(uid, "c0"), (other, "c0")])
    an = sm.pristine_analysis(uid)
    u = an.drawing.units_mm
    span = next(c.id for c in an.clusters.values() if round(c.value * u) == 2400 and "x" in c.axes)
    big = next(c for c in an.clusters.values() if round(c.value * u) == 2700)
    view = sm.units[uid].views[0]

    def run(script):
        sheet.gem = ScriptedModel(script)
        sheet.start_run({"instruction": "Parametrize it.", "scope": {"views": [view]}})
        for _ in range(400):
            p = sheet.run_progress(None, 0)
            if p["status"] not in ("queued", "running", "stopping"):
                return p
            time.sleep(0.05)
        raise AssertionError("the run did not end")

    rev = sm.revision
    p = run([[call("define_parameters", items=[{"name": "OuterWall", "part": "", "candidate": big.id, "occurrences": [big.gaps[0]]}])],
             [call("finish", summary="x")], [call("finish", summary="x")], [call("finish", summary="x")]])
    assert p["status"] == "failed" and sm.revision == rev  # the sheet untouched, and the run says so
    committed = next(c for c in p["verdict"]["criteria"] if c["id"] == "committed")
    assert not committed["ok"] and "refused" in committed["detail"] and any("refused" in x for x in p["verdict"]["remaining"])
    p = run([[call("define_parameters", items=[{"name": "ClearSpan", "part": "", "candidate": span, "occurrences": ["all"]}])],
             [call("finish", summary="x")], [call("finish", summary="x")]])
    assert p["status"] == "completed" and sm.revision == rev + 1 and "ClearSpan" in sm.units[uid].prog.params