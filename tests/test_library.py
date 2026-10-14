"""The engineering library: what it finds, how it ranks, how it loads, what it refuses.

Nothing here calls a model. The data is the migrated agent-context (real records); the small synthetic library at the end is for behaviours the
real data cannot show on demand (a disputed definition, a budget, a malformed record)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from dxf_autoparam.ai import library as L

ROOT = Path(__file__).resolve().parents[1]
# the owner's own GAD, when it is on this machine (never part of the repository): AUTOPARAM_REAL_GAD names another
REAL_GAD = Path(os.environ.get("AUTOPARAM_REAL_GAD") or Path.home() / "Downloads" / "gad_1790232095.dxf")
FAMILIES = {"family:arch", "family:girder", "family:other", "family:pipe", "family:rcc_box", "family:rcc_slab", "family:rob", "family:rub_other"}
RECIPES = {"gad-workflow", "read-the-drawing", "name-and-bind-sizes", "relate-views-and-levels", "handle-uncertainty"}


@pytest.fixture(scope="module")
def lib() -> L.Library:
    lib = L.open_domain("bridge")
    assert lib is not None
    return lib


def session(lib, **kw) -> L.KnowledgeSession:
    return L.KnowledgeSession(lib, **kw)


# ── what is there ─────────────────────────────────────────────────────────────────


def test_the_domain_is_found_and_its_skills_are_the_family_skills_and_the_authored_recipes(lib):
    assert L.domains() == ["bridge"]
    assert set(lib.skills) == FAMILIES | RECIPES
    assert {s.kind for s in lib.skills.values()} == {"workflow", "recipe", "family"}
    assert lib.skills["gad-workflow"].kind == "workflow"


def test_the_sources_general_skills_are_not_offered_as_runnable_they_are_adapted(lib):
    """The source's general skills tell an agent to run a repository command line; here they are the authored recipes' `derived_from`."""
    assert not ({"find-source-evidence", "interpret-components", "propose-dimension-bindings", "propose-geometric-relationships"} & set(lib.skills))
    for sk in lib.skills.values():
        if sk.kind != "family":
            text = (lib.dir / "skills" / f"{sk.id}.md").read_text()
            assert "ctx.py" not in text.split("---", 2)[2] or "Adapted" in text


def test_every_family_skill_resolves_to_its_knowledge_family_and_its_ontology_record(lib):
    for sid in FAMILIES:
        sk = lib.skills[sid]
        assert sk.family["kb"] and lib.record(sk.family["kb"]) is not None, sid
        assert lib._ontology_family(sk.family["ontology"]) is not None, sid
        assert {"recognition", "components", "rules", "failure", "procedure"} <= set(sk.sections), sid
        # the brief's skill anatomy: inputs, prerequisites, dependencies, outputs, validation come from the domain's shared template
        assert {"inputs", "prerequisites", "dependencies", "outputs", "validation"} <= set(sk.sections), sid
        assert "representation" in sk.sections or sk.family["ontology"] == "special"


def test_the_ids_the_family_skills_cite_resolve(lib):
    """The source's own promise ("cites only ids that resolve"), checked against the migrated data. Placeholders in prose are not ids."""
    cited = bad = 0
    for sk in lib.skills.values():
        if not sk.family:
            continue
        text = "\n".join(sk.sections.values())
        for i in set(re.findall(r"`((?:kb|ontology|chunk|proposal|teach|issue|rdso-doc|rdso-extract):[^`\s]+)`", text)):
            if "<" in i or i in ("issue:failed_check", "issue:unresolved_disputes"):  # a pattern or a kind, not an id
                continue
            cited += 1
            if not lib.resolves(i):
                bad += 1
    assert cited > 250 and bad == 0, f"{bad} of {cited} cited ids do not resolve"


def test_trust_is_kept_as_the_source_wrote_it(lib):
    rec = lib.record("kb:kb.rule.irbm_312_3_culvert_exempt")
    v = lib.view(rec)
    assert v["status"] == "NORMATIVE" and v["review"] == "seed_unreviewed"  # a label is not a verification: both are shown
    disputed = lib.search("minimum clear height box", categories={"D"}, limit=5)
    assert disputed and all("not_accepted" in h for h in disputed)
    assert all(r["expression"] is None or r["expression"]["executed"] is False for src in lib.sources for r in src.knowledge.values())


# ── discovery ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("words,first", [
    (["RCC BOX CULVERT 1X4.0X4.0 M", "WING WALL", "FORMATION LEVEL"], "family:rcc_box"),
    (["R.C.C. BOX TO BE CAST IN M-35", "TOP SLAB 400 THK"], "family:rcc_box"),
    (["HUME PIPE CULVERT", "HEAD WALL", "PIPE BEDDING"], "family:pipe"),
    (["PSC GIRDER", "BEARING", "PIER CAP", "ABUTMENT"], "family:girder"),
    (["ROAD OVER BRIDGE", "GIRDER", "PIER"], "family:rob"),
    (["MASONRY ARCH", "SPANDREL WALL"], "family:arch"),
])
def test_discovery_ranks_the_skill_whose_structure_the_drawing_prints(lib, words, first):
    found = lib.discover(words)
    assert found and found[0]["skill"] == first and found[0]["strong"]
    assert found[0]["because"], "a match without the words that caused it is not evidence"
    assert all(b["printed"] for b in found[0]["because"])


def test_two_structures_printed_are_both_reported_not_resolved_by_the_engine(lib):
    found = lib.discover(["EXISTING MASONRY ARCH EXTENDED AS RCC BOX"])
    assert {f["skill"] for f in found if f["strong"]} == {"family:arch", "family:rcc_box"}


@pytest.mark.parametrize("words", [[], ["SHAFT DIA 25", "KEYWAY 8x7", "M10 TAP"], ["SECTION A-A", "SCALE 1:100", "ALL DIMENSIONS IN MM"], [""], ["℄", "<>"]])
def test_a_drawing_the_library_knows_nothing_about_matches_nothing(lib, words):
    assert lib.discover(words) == []


def test_parts_alone_never_make_a_strong_match(lib):
    found = lib.discover(["WING WALL", "RETURN WALL", "BED LEVEL", "FOOTING"])
    assert found and not any(f["strong"] for f in found)


def test_printed_words_are_normalised_the_way_a_drafter_writes_them():
    assert L.printed_tokens("R.C.C.  BOX") == ["RCC", "BOX"]
    assert L.printed_tokens(r"{\fArial|b0;WING WALL}\PTOP SLAB") == ["WING", "WALL", "TOP", "SLAB"]
    assert L.printed_tokens("F.L. = 100.000") == ["FL", "100", "000"]


@pytest.mark.skipif(not REAL_GAD.is_file(), reason="the real GAD is not on this machine")
def test_the_real_gad_is_recognised_by_its_own_words_and_the_lookalikes_trail_far_behind(lib):
    from dxf_autoparam.crossview import SheetModel

    texts = L.drawing_texts(SheetModel.open(str(REAL_GAD)).dr.items)
    found = lib.discover(texts)
    assert found[0]["skill"] == "family:rcc_box" and found[0]["strong"]
    assert found[0]["score"] > 5 * found[1]["score"] and not found[1]["strong"]
    assert any(b["printed"] == "RCC BOX" for b in found[0]["because"])


# ── search ────────────────────────────────────────────────────────────────────────


def test_search_finds_a_definition_by_its_words_with_its_roles_and_review_state(lib):
    hits = lib.search("clear height soffit level", topics={"formula"})
    top = hits[0]
    assert top["id"] == "kb:kb.formula.d_clear_height" and top["expression"] == "soffit_level - floor_level"
    assert top["roles"] == ["clear_height", "floor_level", "soffit_level"] and top["review"] == "seed_unreviewed"


def test_search_filters_by_category_topic_and_family(lib):
    assert {h["category"] for h in lib.search("wall", categories={"C"}, limit=25)} == {"C"}
    assert {h["topic"] for h in lib.search("cushion", topics={"rule"}, limit=25)} <= {"rule"}
    pipe = lib.search("scour", families={"pipe"}, limit=25)
    assert pipe and all(not h.get("families") or "pipe" in h["families"] or "*" in h["families"] for h in pipe)


def test_search_is_bounded_and_empty_queries_say_so(lib):
    ks = session(lib)
    assert len(ks.call("search_library", {"queries": ["wall"], "limit": 500})["hits"]) <= L.SEARCH_MAX
    assert "error" in ks.call("search_library", {"queries": ["  "]})
    none = ks.call("search_library", {"queries": ["zzzxqv"]})
    assert none["hits"] == [] and "normal answer" in none["note"]


def test_search_results_are_deterministic(lib):
    a = lib.search("haunch size minimum", limit=10)
    b = lib.search("haunch size minimum", limit=10)
    assert [h["id"] for h in a] == [h["id"] for h in b]


# ── loading, progressively ────────────────────────────────────────────────────────


def test_a_skill_loads_in_a_working_set_and_lists_what_it_left_out_with_sizes(lib):
    res = session(lib).call("load_skill", {"id": "family:rcc_box"})
    shown = sum(len(v) for v in res["sections"].values())
    assert shown <= L.DEFAULT_LOAD_CHARS and {"recognition", "representation", "failure"} <= set(res["sections"])
    left = {n["section"]: n["chars"] for n in res["not_included"]}
    assert {"rules", "hazards", "sources"} <= set(left) and left["rules"] > 0
    assert res["trust"].startswith("source knowledge, unreviewed")


def test_a_section_is_loaded_whole_on_request_and_a_long_one_continues_by_offset(lib):
    ks = session(lib)
    whole = lib.skills["family:rcc_box"].sections["sources"]
    assert len(whole) > 5000
    first = ks.call("load_skill", {"id": "family:rcc_box", "sections": ["sources"]})["sections"]["sources"]
    assert first == whole  # under the cap, whole
    big = lib.skills["family:rcc_box"]
    big.sections["_long"] = "x" * 30000
    try:
        a = ks.call("load_skill", {"id": "family:rcc_box", "sections": ["_long"]})["sections"]["_long"]
        assert len(a) < 30000 and "offset=" in a
        rest = ks.call("load_skill", {"id": "family:rcc_box", "sections": ["_long"], "offset": L.MAX_LOAD_CHARS})["sections"]["_long"]
        assert len(rest) == 30000 - L.MAX_LOAD_CHARS
    finally:
        big.sections.pop("_long")


def test_an_unknown_skill_or_section_is_answered_not_raised(lib):
    ks = session(lib)
    r = ks.call("load_skill", {"id": "no-such"})
    assert r["found"] is False and "family:rcc_box" in r["ids"]
    r = ks.call("load_skill", {"id": "gad-workflow", "sections": ["procedure", "nonsense"]})
    assert "procedure" in r["sections"] and r["no_such_section"] == ["nonsense"]
    assert ks.call("load_skill", {"id": "rcc_box"})["id"] == "family:rcc_box"  # the bare dataset name works
    assert ks.call("load_skill", {"id": "skill:family:pipe"})["id"] == "family:pipe"


def test_list_skills_is_compact_and_says_which_match_this_drawing(lib):
    ks = session(lib, texts=lambda: ["RCC BOX CULVERT", "WING WALL"])
    res = ks.call("list_skills", {})
    assert len(json.dumps(res)) < 8000
    first = res["skills"][0]
    assert first["id"] == "family:rcc_box" and first["match"]["strong"] and res["matches"][0]["printed_words"]
    plain = session(lib, texts=lambda: ["SHAFT DIA 25"]).call("list_skills", {})
    assert plain["matches"] == [] and "normal" in plain["matches_note"]
    sizes = {s["id"]: s["sections"] for s in res["skills"]}
    # sizes where the model is likely to load (a match, a recipe), only the section names for a structure skill that did not match
    assert isinstance(sizes["family:rcc_box"], dict) and any(isinstance(v, list) for k, v in sizes.items() if k.startswith("family:"))
    assert isinstance(sizes["gad-workflow"], dict)
    assert {s["kind"] for s in session(lib).call("list_skills", {"kind": "recipe"})["skills"]} == {"recipe"}


# ── references and examples ───────────────────────────────────────────────────────


def test_references_resolve_by_every_id_form_and_unknown_ones_are_said(lib):
    ks = session(lib)
    a = ks.call("get_reference", {"id": "kb:kb.formula.f_box_soffit"})
    b = ks.call("get_reference", {"id": "kb.formula.f_box_soffit"})
    assert a["found"] and a["id"] == b["id"] == "kb:kb.formula.f_box_soffit" and a["expression"] == "floor_level + clear_height"
    assert a["context_only"].startswith("knowledge")
    assert ks.call("get_reference", {"id": "issue:disputed_knowledge:kb:kb.conflict.kc_1"})["kind"] == "issue"
    assert ks.call("get_reference", {"id": "skill:gad-workflow"})["kind"] == "skill"
    gone = ks.call("get_reference", {"id": "kb:kb.nothing.here"})
    assert gone["found"] is False and "search_library" in gone["reason"]


def test_a_conflict_is_shown_with_the_record_so_it_is_not_applied_as_a_rule(lib):
    rec = session(lib).call("get_reference", {"id": "kb:kb.formula.d_cushion"})
    assert rec["status"] == "DERIVED" and rec["conflicts"][0]["id"] == "kb:kb.conflict.kc_5" and rec["conflicts"][0]["status"] == "DISPUTED"
    assert lib.record("kb:kb.conflict.kc_5")["category"] == "D"


def test_a_stored_example_sheet_is_a_compact_labelled_reading_never_a_value(lib):
    ks = session(lib)
    ex = ks.call("search_library", {"queries": ["box"], "scope": "examples"})
    assert ex["examples"] and "unreviewed" in ex["label"]
    sheet = ks.call("get_reference", {"id": ex["examples"][0]["id"]})
    assert sheet["kind"] == "example" and sheet["parts"] and "never a value" in sheet["label"]
    assert len(json.dumps(sheet)) <= L.EXAMPLE_CHARS + 200


def test_a_reference_is_bounded_even_when_the_whole_record_is_asked_for(lib):
    big = max((r for r in lib.sources[0].knowledge.values()), key=lambda r: len(json.dumps(r.get("raw") or {}, default=str)))
    out = session(lib).call("get_reference", {"id": big["id"], "full": True})
    assert len(json.dumps(out, default=str)) < L.MAX_LOAD_CHARS * 2


# ── rule checks ───────────────────────────────────────────────────────────────────


def values(**named):
    return lambda name, unit=None: named.get(name)


def test_a_documented_definition_holds_or_differs_on_values_bound_by_name(lib):
    v = values(Soffit=(2.85, "m"), Floor=(0.35, "m"), Height=(2500.0, "mm"), WrongHeight=(2400.0, "mm"))
    ks = session(lib, values=v)
    ok = ks.call("check_rule", {"rule": "kb:kb.formula.d_clear_height",
                                "bind": {"clear_height": "Height", "soffit_level": "Soffit", "floor_level": "Floor"}})
    assert ok["result"] == "holds" and ok["expected_mm"] == 2500.0 and ok["measured_mm"] == 2500.0 and "advisory" in ok
    bad = ks.call("check_rule", {"rule": "kb:kb.formula.d_clear_height",
                                 "bind": {"clear_height": "WrongHeight", "soffit_level": "Soffit", "floor_level": "Floor"}})
    assert bad["result"] == "differs" and bad["difference_mm"] == -100.0 and "ask_yourself" in bad
    assert [c["result"] for c in ks.checks] == ["holds", "differs"]


def test_a_number_is_never_accepted_as_a_binding_the_library_supplies_no_values(lib):
    ks = session(lib, values=values(Floor=(0.35, "m")))
    r = ks.call("check_rule", {"rule": "kb:kb.formula.d_clear_height", "bind": {"clear_height": 2500, "soffit_level": "2.85", "floor_level": "Floor"}})
    assert r["result"] == "not_evaluable" and sum("NAME" in p for p in r["problems"]) == 2


def test_missing_names_and_unbound_roles_are_said_not_guessed(lib):
    ks = session(lib, values=values(Floor=(0.35, "m")))
    r = ks.call("check_rule", {"rule": "kb:kb.formula.d_clear_height", "bind": {"floor_level": "Floor", "soffit_level": "Nope"}})
    assert r["result"] == "not_evaluable"
    assert any("clear_height: not bound" in p for p in r["problems"]) and any("no value or level named 'Nope'" in p for p in r["problems"])
    assert ks.call("check_rule", {"rule": "kb:kb.nothing", "bind": {}})["ok"] is False
    text_rule = ks.call("check_rule", {"rule": "kb:kb.rule.level_order_cover", "bind": {"a": "Floor"}})
    assert text_rule["result"] == "not_evaluable" and "text" in text_rule["why"]


def test_a_definition_the_library_marks_disputed_carries_the_caution(lib):
    ks = session(lib, values=values(Floor=(0.35, "m"), Top=(3.15, "m"), Form=(5.0, "m"), Cushion=(1850.0, "mm")))
    r = ks.call("check_rule", {"rule": "kb:kb.formula.d_cushion", "bind": {"cushion": "Cushion", "formation_level": "Form", "top_slab_level": "Top"}})
    assert r["result"] == "holds" and r["conflicts"][0]["id"] == "kb:kb.conflict.kc_5" and "dispute" in r["caution"]


# ── findings ──────────────────────────────────────────────────────────────────────


def test_a_finding_must_cite_a_library_id_that_exists_a_drawing_id_is_accepted_as_stated(lib):
    ks = session(lib)
    r = ks.call("record_finding", {"findings": [
        {"kind": "applied", "text": "used the box skill", "evidence": ["skill:family:rcc_box", "kb:kb.formula.d_clear_height", "R12", "c7"]},
        {"kind": "conflict", "text": "the drawing's haunch differs", "evidence": ["kb:kb.rule.know_haunch_minimum"], "about": "Haunch"},
        {"kind": "applied", "text": "x", "evidence": ["kb:kb.invented.rule"]},
        {"kind": "mood", "text": "x"}, {"kind": "gap", "text": "   "}, "not an object",
        {"kind": "applied", "text": "a skill id with no 'skill:' prefix is still a library id", "evidence": ["family:no_such_structure"]}]})
    assert [i["ok"] for i in r["items"]] == [True, True, False, False, False, False, False] and r["ok"] is False
    assert "kb:kb.invented.rule" in r["items"][2]["refused"]
    assert len(ks.findings) == 2 and ks.refused == ["kb:kb.invented.rule", "family:no_such_structure"]
    assert ks.findings[0]["library"] == ["skill:family:rcc_box", "kb:kb.formula.d_clear_height"]  # the drawing ids are kept but not "library"


def test_findings_are_capped_and_a_malformed_call_is_an_error_not_a_crash(lib):
    ks = session(lib)
    assert ks.call("record_finding", {"findings": []})["ok"] is False
    for _ in range(L.MAX_FINDINGS + 5):
        ks.call("record_finding", {"findings": [{"kind": "gap", "text": "t"}]})
    assert len(ks.findings) == L.MAX_FINDINGS
    assert "unknown argument" in ks.call("load_skill", {"id": "x", "colour": "red"})["error"]
    assert "not a library tool" in ks.call("delete_everything", {})["error"]


# ── context limits and the trace ──────────────────────────────────────────────────


def test_a_run_has_a_character_budget_and_then_says_so_while_cheap_tools_stay_open(lib):
    ks = session(lib, budget_chars=3000, values=values())
    first = ks.call("load_skill", {"id": "family:rcc_box"})
    assert first["found"] and ks.used > 3000
    again = ks.call("load_skill", {"id": "family:pipe"})
    assert "refused" in again and "budget" in again["refused"]
    assert "refused" in ks.call("search_library", {"queries": ["wall"]})
    assert "skills" in ks.call("list_skills", {})
    assert ks.call("record_finding", {"findings": [{"kind": "gap", "text": "budget used"}]})["ok"]


def test_every_retrieval_is_traced_and_summarised_for_the_verdict(lib):
    ks = session(lib, texts=lambda: ["RCC BOX CULVERT"], values=values())
    ks.call("list_skills", {})
    ks.call("load_skill", {"id": "family:rcc_box", "sections": ["recognition", "failure"]})
    ks.call("search_library", {"queries": ["haunch", "cushion"]})
    ks.call("get_reference", {"id": "kb:kb.family.rcc_box"})
    s = ks.summary()
    assert [t["tool"] for t in ks.trace] == ["list_skills", "load_skill", "search_library", "get_reference"] and s["calls"] == 4
    assert s["skills_loaded"] == {"family:rcc_box": ["recognition", "failure"]}
    assert s["references"] == ["kb:kb.family.rcc_box"] and s["searches"] == ["haunch", "cushion"]
    assert s["matches"][0]["skill"] == "family:rcc_box" and json.dumps(s)  # serialisable


# ── adding knowledge without touching code ────────────────────────────────────────


def make_library(tmp_path: Path, records: list[dict], skills: dict[str, str] | None = None) -> L.Library:
    dom = tmp_path / "toy"
    (dom / "skills").mkdir(parents=True)
    src = tmp_path / "src"
    (src / "knowledge").mkdir(parents=True)
    (src / "registry").mkdir()
    (src / "knowledge" / "knowledge.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    (src / "registry" / "issues.jsonl").write_text("")
    (dom / "domain.json").write_text(json.dumps({"name": "toy", "title": "Toy", "sources": [{"kind": "agent_context", "path": "../src"}], "skills_dir": "skills"}))
    for name, text in (skills or {}).items():
        (dom / "skills" / f"{name}.md").write_text(text)
    return L.open_domain("toy", str(tmp_path))


def rec(rid: str, **kw) -> dict:
    base = {"id": rid, "kb_id": rid.removeprefix("kb:"), "category": "B", "topic": "formula", "kind": "definition", "title": rid, "statement": None,
            "interpretation": None, "expression": None, "applies_families": [], "trust": {"evidence_status": "DERIVED", "review_state": "seed_unreviewed"},
            "conflicts": [], "relations": [], "proposal_status": "none", "citations": [], "raw": {}}
    return {**base, **kw}


def test_a_new_domain_is_a_folder_a_skill_is_a_file_and_a_record_is_a_line(tmp_path):
    lib = make_library(tmp_path, [rec("kb:t.formula.sum", statement="total = a + b", expression={"executed": False, "text": "a + b"}, title="Sum of two")],
                       {"mine": '---\n{"id": "mine", "title": "My recipe", "kind": "recipe", "purpose": "p"}\n---\n## Procedure\n1. do it\n'})
    assert set(lib.skills) == {"mine"} and lib.skill("mine").sections["procedure"].startswith("1. do it")
    ks = L.KnowledgeSession(lib, values=lambda n, u=None: {"A": (2.0, "mm"), "B": (3.0, "mm"), "T": (5.0, "mm")}.get(n))
    assert ks.call("search_library", {"queries": ["sum"]})["hits"][0]["roles"] == ["a", "b", "total"]
    assert ks.call("check_rule", {"rule": "kb:t.formula.sum", "bind": {"a": "A", "b": "B", "total": "T"}})["result"] == "holds"
    assert ks.call("list_skills", {})["matches_note"]  # no family skills: no matches, said


def test_a_malformed_source_does_not_stop_the_library(tmp_path):
    lib = make_library(tmp_path, [rec("kb:t.ok", title="fine")])
    src = lib.sources[0].root
    (src / "knowledge" / "knowledge.jsonl").write_text(json.dumps(rec("kb:t.ok", title="fine")) + "\nnot json at all\n[1, 2]\n")
    lib2 = L.Library(lib.dir)
    assert list(lib2.sources[0].knowledge) == ["kb:t.ok"]
