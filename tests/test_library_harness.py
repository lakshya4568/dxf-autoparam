"""The engineering library inside the agent harness, driven by a scripted model (no network, no cost) on the real engine.

What is measured: the library's tools and protocol exist only when a domain pack with a library is on; a run that uses them leaves a trace in
the verdict; a cited id the library does not have is refused; a documented definition is checked against values the model defined; the
run's context budget and the loop's own limits hold; and with the library off the model sees exactly what it saw before."""

from __future__ import annotations

import copy
import json
import time

import pytest
from test_agent import XX

from dxf_autoparam.ai import domain
from dxf_autoparam.ai import library as L
from dxf_autoparam.ai.agent import AGENT_SYSTEM, Workbench, agent_system, overview, tools
from dxf_autoparam.ai.parametrize import prepare
from dxf_autoparam.ai.run import ACTIVE, UNIFIED_SYSTEM, unified_system, unified_tools
from dxf_autoparam.ai.scripted import ScriptedModel, call
from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.plan_bench import Box, box_answer, box_gad
from dxf_autoparam.workspace import SheetSession

# these tests measure the engine within ONE unit made of a section and its plan (conftest.joined_units): local systems, each view its own,
# are test_local_systems.py
pytestmark = pytest.mark.usefixtures("joined_units")

LIB_TOOLS = {"list_skills", "load_skill", "search_library", "get_reference", "check_rule", "record_finding"}


def names(t) -> set[str]:
    return {d.name for tool in t for d in tool.function_declarations}


def wait(sheet, rid, timeout=90):
    t = time.time()
    while time.time() - t < timeout:
        p = sheet.run_progress(rid, 0)
        if p["status"] not in ACTIVE:
            return p
        time.sleep(0.03)
    raise AssertionError(f"the run did not settle: {sheet.run_progress(rid, 0)['status']}")


def parametrized_box(tmp_path, levels: bool = True):
    """A single-cell box sheet already parametrized by 'the model's earlier work', with named levels the definitions can be checked against."""
    b = Box(cells=1, span=2500.0, height=2500.0)  # the span equals the height: a definition of the height can hold by arithmetic on the span
    g = box_gad(tmp_path / "box.dxf", b)
    sm = SheetModel.open(g["path"])
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    ans = box_answer(sm, uid, g["box"], g["handles"])
    if levels:
        an, um = sm.unit(uid).an, sm.unit(uid).sub.units_mm

        def line(at):
            return min((d for d in an.datums.values() if d.axis == "y"), key=lambda d: abs(d.value * um - at)).id

        ans["levels"] = [{"datum": line(b.bottom), "name": "FloorLevel", "role": "site_input"},
                         {"datum": line(b.bottom + b.height), "name": "SoffitLevel", "role": "site_input"}]
    sm.commit_answer(uid, ans)
    sheet = SheetSession()
    sheet.sm = sm
    return sheet, uid


def run_script(sheet, script, options=None, instruction="Check this sheet against the library's definitions and change nothing."):
    gem = ScriptedModel(script)
    sheet.gem_factory = lambda: gem
    r = sheet.start_run({"instruction": instruction, "options": {"domain": "bridge", **(options or {})}})
    return gem, wait(sheet, r["run"])


READING = call("account_instruction", items=[
    {"quote": "Check this sheet against the library's definitions", "kind": "process", "meaning": "compare documented definitions with the values", "handled_by": "none",
     "why": "nothing is edited: the check is advisory"},
    {"quote": "change nothing", "kind": "keep", "meaning": "no edits", "handled_by": "none", "why": "a request to leave the drawing as it is"}])


# ── what the model is given ──────────────────────────────────────────────────────


def test_the_library_tools_exist_only_when_a_pack_with_a_library_is_on():
    pack = domain.active("bridge")
    assert not (names(tools()) | names(unified_tools())) & LIB_TOOLS
    assert LIB_TOOLS <= names(tools(pack=pack)) and LIB_TOOLS <= names(unified_tools(pack))
    assert not names(tools(pack={"name": "no-library-for-this-one"})) & LIB_TOOLS


def test_the_protocol_is_in_the_prompt_only_with_the_library_and_says_context_never_value():
    pack = domain.active("bridge")
    on = unified_system(pack)
    assert "ENGINEERING LIBRARY (on for this run" in on and "NEVER a value of this drawing" in on and "the drawing wins" in on
    assert "ENGINEERING LIBRARY" not in unified_system(None) and "ENGINEERING LIBRARY" not in agent_system(None)
    assert agent_system(pack).startswith(AGENT_SYSTEM) and UNIFIED_SYSTEM in on


def test_nothing_the_library_tools_say_to_the_model_names_a_kind_of_structure():
    """The tools are generic: the knowledge arrives as a tool RESULT, when the model asks, never in what it is told it can call."""
    text = json.dumps([(n, d, p) for n, d, p in L.LIBRARY_TOOL_SPECS], default=str)
    for word in ("ClearSpan", "TopSlab", "WingWall", "RailLevel", "rcc_box", "culvert", "bridge", "RCC", "girder", "pipe "):
        assert word not in text, word


def test_the_overview_lists_skills_and_matches_only_when_the_pack_is_on():
    an, base, *_ = prepare(XX)
    pack = domain.active("bridge")
    row = next(v for k, v in overview(an, base, None, pack).items() if k.startswith("engineering library"))
    assert set(row["skills"]) == set(L.open_domain("bridge").skills) and "match this drawing's printed words" in row
    assert not any(k.startswith("engineering library") for k in overview(an, base))
    assert len(json.dumps(row)) < 2500, "the first request carries a catalogue, not content"


def test_without_a_pack_a_library_tool_call_is_an_answer_not_a_crash():
    wb = Workbench(XX)
    assert wb.lib_session is None
    assert "no engineering library" in wb.list_skills()["error"]
    assert "no engineering library" in wb.record_finding(findings=[{"kind": "gap", "text": "x"}])["error"]


def test_a_workbench_with_the_library_reads_the_values_the_model_defined():
    pack = domain.active("bridge")
    wb = Workbench(XX, pack=pack)
    assert wb.lib_session is not None and wb.list_skills()["skills"]
    name = next(n for n, p in wb.prog.params.items() if p.unit == "mm")
    assert wb.value_of(name) == (wb.prog.params[name].value, "mm") and wb.value_of("NoSuchName") is None


# ── a whole run ──────────────────────────────────────────────────────────────────


def test_a_run_retrieves_checks_and_records_and_the_verdict_says_what_the_library_was_used_for(tmp_path):
    sheet, uid = parametrized_box(tmp_path)
    script = [
        [READING],
        [call("list_skills")],
        [call("load_skill", id="family:rcc_box", sections=["recognition", "failure"]), call("load_skill", id="read-the-drawing")],
        [call("search_library", queries=["clear height soffit floor level"], topics=["formula"])],
        [call("get_reference", id="kb:kb.formula.d_clear_height")],
        [call("open_unit", unit=uid)],
        [call("check_rule", rule="kb:kb.formula.d_clear_height", bind={"clear_height": "ClearSpan", "soffit_level": "SoffitLevel", "floor_level": "FloorLevel"}),
         call("check_rule", rule="kb:kb.formula.d_clear_height", bind={"clear_height": "OuterWall", "soffit_level": "SoffitLevel", "floor_level": "FloorLevel"})],
        [call("record_finding", findings=[
            {"kind": "applied", "text": "read the drawing with the box skill's cues", "evidence": ["skill:family:rcc_box", "kb:kb.formula.d_clear_height"]},
            {"kind": "conflict", "text": "the library's clear height differs from the drawing's span: a different size", "evidence": ["kb:kb.formula.d_clear_height"]},
            {"kind": "proposal", "text": "a rule for the haunch minimum is not in the library", "evidence": ["kb:kb.rule.know_haunch_minimum"]},
            {"kind": "applied", "text": "x", "evidence": ["kb:kb.imaginary.rule"]}])],
        [call("finish", summary="compared, nothing edited")],
    ]
    gem, p = run_script(sheet, script)
    assert p["status"] == "completed", p["verdict"]
    first = gem.requests[0]
    assert LIB_TOOLS <= set(first["tools"]) and "ENGINEERING LIBRARY" in first["system"]
    k = p["verdict"]["knowledge"]
    assert k["library"] == "bridge" and k["calls"] == 8 and k["matches"][0]["skill"] == "family:rcc_box" and k["matches"][0]["strong"]
    assert k["skills_loaded"]["family:rcc_box"] == ["recognition", "failure"] and {"recognition", "procedure"} <= set(k["skills_loaded"]["read-the-drawing"])
    assert k["references"] == ["kb:kb.formula.d_clear_height"] and k["searches"] == ["clear height soffit floor level"]
    assert k["rule_checks"]["holds"] == 1 and k["rule_checks"]["differs"] == 1
    held = next(c for c in k["rule_checks"]["items"] if c["result"] == "holds")
    assert held["rule"] == "kb:kb.formula.d_clear_height" and held["bound"] == {"clear_height": "ClearSpan", "soffit_level": "SoffitLevel", "floor_level": "FloorLevel"}
    off = next(c for c in k["rule_checks"]["items"] if c["result"] == "differs")
    assert off["difference_mm"] == -2150.0  # 350 drawn against 2850 − 350 documented
    assert k["findings"]["by_kind"] == {"applied": 1, "conflict": 1, "proposal": 1} and k["refused_ids"] == ["kb:kb.imaginary.rule"]
    notes = " | ".join(p["verdict"]["notes"])
    assert "documented definitions checked against this drawing's values (advisory): 1 hold, 1 differ" in notes
    assert "1 conflict(s) recorded" in notes and "1 proposal(s) recorded for a person to review (none is merged" in notes
    assert "kb:kb.imaginary.rule" in notes
    # nothing the library said changed the sheet: the model edited nothing
    assert not p["verdict"]["values_applied"]
    summary = sheet.run_list()["runs"][0]
    assert summary["verdict"]["knowledge"]["calls"] == 8, "the run's saved summary carries the trace"


def test_the_first_look_at_the_sheet_carries_the_matches_when_the_library_is_on(tmp_path):
    sheet, _uid = parametrized_box(tmp_path)
    gem, _p = run_script(sheet, [[READING], [call("inspect_sheet")], [call("finish", summary="nothing")]])
    first = next(fr.response for seen in gem.seen for fr in seen if fr.name == "inspect_sheet")["result"]
    hint = first["engineering_library"]
    assert hint["on"] == "bridge" and hint["skills"] == 13 and hint["match_this_drawing"][0]["skill"] == "family:rcc_box"
    assert hint["match_this_drawing"][0]["strong"] and "RCC BOX" in hint["match_this_drawing"][0]["printed_words"]
    (tmp_path / "second").mkdir()
    sheet2, _ = parametrized_box(tmp_path / "second")
    gem2 = ScriptedModel([[READING], [call("inspect_sheet")], [call("finish", summary="nothing")]])
    sheet2.gem_factory = lambda: gem2
    wait(sheet2, sheet2.start_run({"instruction": "Check this sheet. Change nothing."})["run"])
    assert "engineering_library" not in gem2.seen[1][0].response["result"]


def test_a_library_that_was_on_and_never_consulted_is_said_not_hidden(tmp_path):
    sheet, _uid = parametrized_box(tmp_path)
    _gem, p = run_script(sheet, [[READING], [call("finish", summary="nothing")]])
    assert p["verdict"]["knowledge"]["calls"] == 0
    assert any("never consulted" in n and "family:rcc_box" in n for n in p["verdict"]["notes"])


def test_with_the_library_off_the_run_is_what_it_was(tmp_path):
    sheet, _uid = parametrized_box(tmp_path)
    gem = ScriptedModel([[READING], [call("list_skills")], [call("finish", summary="nothing")]])
    sheet.gem_factory = lambda: gem
    r = sheet.start_run({"instruction": "Check this sheet. Change nothing."})
    p = wait(sheet, r["run"])
    assert not LIB_TOOLS & set(gem.requests[0]["tools"]) and "ENGINEERING LIBRARY" not in gem.requests[0]["system"]
    assert p["verdict"]["knowledge"] is None and not any("library" in n for n in p["verdict"]["notes"])
    answer = gem.seen[1][0].response
    assert "no engineering library" in json.dumps(answer)  # a model that calls it anyway is told, and the run goes on


def test_the_run_budget_for_library_text_holds_and_the_loops_own_limits_still_apply(tmp_path):
    sheet, _uid = parametrized_box(tmp_path)
    script = [[READING]] + [[call("load_skill", id="family:rcc_box", sections=["sources"])] for _ in range(14)] + [[call("finish", summary="x")]]
    gem, p = run_script(sheet, script, options={"library_budget_chars": 4000})
    k = p["verdict"]["knowledge"]
    assert k["budget_chars"] == 4000 and k["chars_read"] < 4000 + 7000  # one load may cross it; the next is refused
    refused = [fr.response for seen in gem.seen for fr in seen if "budget" in json.dumps(fr.response)]
    assert refused, "after the budget the model is told, not silently cut"
    looked = [fr.response for seen in gem.seen for fr in seen if "turns without an edit" in json.dumps(fr.response)]
    assert looked, "reading the library counts as looking: twelve turns without an edit and the loop says make your edits or finish"


def test_a_malformed_library_call_is_an_answer_and_the_run_goes_on(tmp_path):
    sheet, _uid = parametrized_box(tmp_path)
    script = [[READING],
              [call("load_skill", id="family:pipe", sections="recognition"), call("search_library", queries="wall", topics="component"),
               call("check_rule", rule="kb:kb.formula.d_clear_height", bind="not an object"), call("record_finding", findings="a string"),
               call("list_skills", colour="red")],
              [call("finish", summary="done")]]
    gem, p = run_script(sheet, script)
    assert p["status"] in ("completed", "partial") and not p["error"]
    out = {fr.name: json.dumps(fr.response) for fr in gem.seen[1]}
    assert '"recognition"' in out["load_skill"] and '"hits"' in out["search_library"]  # a string where a list is meant is read as that list
    assert "not_evaluable" in out["check_rule"] and "findings" in out["record_finding"] and "unknown argument" in out["list_skills"]


def test_a_check_with_a_number_instead_of_a_name_is_refused_in_a_run(tmp_path):
    sheet, uid = parametrized_box(tmp_path)
    script = [[READING], [call("open_unit", unit=uid)],
              [call("check_rule", rule="kb:kb.formula.d_clear_height", bind={"clear_height": "ClearSpan", "floor_level": 0.35, "soffit_level": "SoffitLevel"})],
              [call("finish", summary="done")]]
    gem, p = run_script(sheet, script)
    res = json.dumps([fr.response for seen in gem.seen for fr in seen if fr.name == "check_rule"])
    assert "NAME of a value or level" in res
    assert p["verdict"]["knowledge"]["rule_checks"]["holds"] == 0


def test_a_run_whose_model_changes_a_value_is_unaffected_by_what_it_read(tmp_path):
    """Retrieval is context: the engine's verdict on an edit is the same with or without it (the same refusal, the same measurement)."""
    sheet, _uid = parametrized_box(tmp_path)
    before = copy.deepcopy(sheet.sm.current())
    script = [[READING], [call("load_skill", id="family:rcc_box", sections=["rules"])], [call("finish", summary="nothing")]]
    _gem, p = run_script(sheet, script)
    assert p["verdict"]["state"] in ("completed", "partial")
    assert sheet.sm.current() == before


def test_a_part_left_new_in_a_view_titled_existing_is_said(tmp_path):
    # a live run (7A, 2026-10-26) left every part of "HALF SECTION OF EXIST. BRIDGE" as new work (existing=false): said now, from the library's own
    # status words and the view's title — a view whose title also says new work ("PROPOSED EXTENSION OF EXISTING …") is not
    from dxf_autoparam.topology import of

    g = box_gad(tmp_path / "box.dxf", Box(cells=1))
    sm = SheetModel.open(g["path"])
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    sm.set_view(sm.units[uid].views[0], name="HALF SECTION OF EXISTING BOX")
    region = max(of(sm.unit(uid).an).regions, key=lambda r: len(r.holes)).id
    sheet = SheetSession()
    sheet.sm = sm
    gem, _p = run_script(sheet, [[call("open_unit", unit=uid)], [call("define_parts", items=[{"name": "Box", "type": "box", "regions": [region]}])],
                                 [call("finish", summary="x")], [call("finish", summary="x")]], instruction="Make the drawing parametric.")
    verdict = next(r.response for turn in gem.seen for r in turn if r.name == "define_parts")
    row = verdict["result"]["result"][0] if "result" in verdict["result"] else verdict["result"][0]
    assert "existing=true" in row.get("existing_doubt", ""), row


def test_the_overview_says_what_the_matching_family_is_made_of_and_where_the_standard_tables_are():
    # seven recorded runs never asked the library for anything: what the family the drawing's words match is known to be made of — its components,
    # what must be known, how each level follows — is in the first overview, as a lead, with where the standard drawings' tables are
    rows = L.overview_rows(domain.active("bridge"), ["RCC BOX CULVERT 1 x 4.9 x 4.5", "WING WALL", "TOP OF SLAB"])
    lib = next(iter(rows.values()))
    fam = next(v for k, v in lib.items() if k.startswith("the family the words match"))
    assert fam["family"] == "rcc_box" and fam["components"] and any("soffit_level" in w for w in fam["level_chain (how each level follows; graded, DERIVED holds by definition)"])
    assert any(k.startswith("standard drawings") and "rdso-sheet:" in v for k, v in lib.items())
