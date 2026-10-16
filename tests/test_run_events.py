"""What the Agent panel is built on: every tool event says which stage and phase it belongs to and what it is doing, a person's
answer is an event of its own, and the progress a page polls says the phase the run is in."""

from __future__ import annotations

from test_run import DIRS2, READ2, SAID2, answer_all, parametrized_sheet, wait
from test_web_contract import contract

from dxf_autoparam.ai.narrate import DOING, PHASE_OF, STAGE_OF, STAGES, WORDS, doing, phase_of, stage_of
from dxf_autoparam.ai.run import unified_tools
from dxf_autoparam.ai.scripted import call

LIBRARY_TOOLS = ("list_skills", "load_skill", "search_library", "record_finding")


def tool_names() -> list[str]:
    return [fd.name for t in unified_tools(None) for fd in (t.function_declarations or [])] + list(LIBRARY_TOOLS)


def test_every_agent_tool_has_a_stage_a_phase_and_plain_words():
    for name in tool_names():
        assert name in STAGE_OF and name in WORDS and name in DOING, f"{name} is not narrated"
        assert stage_of(name) in STAGES and phase_of(stage_of(name)), name
        assert doing(name)[:1].isupper()
    assert set(STAGES) <= set(PHASE_OF), "a stage with no phase would show as no phase"


def test_events_carry_their_stage_and_phase_and_an_answer_is_an_event(tmp_path):
    script = [
        [call("account_instruction", items=[{"quote": q, "kind": k, "meaning": m, "handled_by": h} for q, k, m, h in READ2])],
        [call("propose_plan", parameter="ClearSpan", requested_value=2500, directives=DIRS2)],
        [call("finish", summary="the plan waits for you")],
        [call("finish", summary="applied with your answers")],
    ]
    sheet, _uid, _g, _gem = parametrized_sheet(tmp_path, script=script)
    r = sheet.start_run({"instruction": SAID2, "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    assert p["status"] == "awaiting_user" and p["phase"] in PHASE_OF.values()
    starts = [e for e in p["events"] if e["kind"] == "tool_start"]
    done = [e for e in p["events"] if e["kind"] == "tool"]
    assert starts and done
    for e in starts + done:
        assert e["doing"] and e["stage"] == stage_of(e["name"]) and e["phase"] == phase_of(e["stage"]), e
    assert all(e["args_full"] is not None for e in starts), "a running call already shows its arguments"
    assert not [e for e in p["events"] if e["kind"] == "user"], "nothing from the person yet beyond the instruction"
    ans = answer_all(p, lambda q: "centered" if q["about"] == "anchor" else "accept" if "accept" in q["options"] else q["options"][0])
    sheet.continue_run({"run": r["run"], "answers": ans, "note": "centred is what I meant"})
    p = wait(sheet, r["run"])
    users = [e for e in p["events"] if e["kind"] == "user"]
    assert len(users) == 1 and users[0]["text"] == "centred is what I meant" and set(users[0]["answers"]) == set(ans)
    seqs = [e["seq"] for e in p["events"]]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs)), "events are ordered and numbered once"


def test_the_events_a_page_reads_keep_the_keys_the_typescript_contract_lists(tmp_path):
    c = contract()
    script = [
        [call("account_instruction", items=[{"quote": q, "kind": k, "meaning": m, "handled_by": h} for q, k, m, h in READ2])],
        [call("finish", summary="done")],
    ]
    sheet, _uid, _g, _gem = parametrized_sheet(tmp_path, script=script)
    r = sheet.start_run({"instruction": SAID2, "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    assert not [k for k in c["run_progress"] if k not in p], "run_progress"
    start = next(e for e in p["events"] if e["kind"] == "tool_start")
    done = next(e for e in p["events"] if e["kind"] == "tool")
    assert not [k for k in c["tool_start"] if k not in start], start
    assert not [k for k in c["tool_result"] if k not in done], done
