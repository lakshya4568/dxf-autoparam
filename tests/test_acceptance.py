"""The scorer that keeps the AI's mistakes and the engine's apart — proven with scripted models of different care. The live acceptance run (the real
model) uses the same scorer; this file never calls a model that costs anything."""

from __future__ import annotations

from dxf_autoparam.ai import acceptance as acc
from dxf_autoparam.ai.scripted import ScriptedModel, call


def test_a_careful_agent_scores_full_in_every_category_and_nothing_is_unsafe(tmp_path):
    case = acc.make_case(tmp_path)
    res = acc.evaluate(acc.script_for(case, "careful"), case, log=lambda *a: None)
    s = res["scores"]
    assert s["_summary"] == {"ai": 1.0, "engine": 1.0, "intent": 1.0, "outcome": 1.0, "unsafe": 0, "categories": 12}, acc.table(s)
    assert s["geometry_execution"]["score"] == 1.0 and max(s["geometry_execution"]["members"].values()) <= 0.5  # measured against the generator's own drawing


def test_a_careless_agent_loses_interpretation_and_is_flagged_for_a_fabricated_quote_while_the_engine_stays_exact(tmp_path):
    case = acc.make_case(tmp_path)
    res = acc.evaluate(acc.script_for(case, "careless"), case, log=lambda *a: None)
    s = res["scores"]
    assert s["instruction_interpretation"]["score"] < 0.6 and s["dependency_planning"]["score"] < 0.8
    assert s["clarification"]["unsafe"] == 1 and s["clarification"]["fabricated"] == 1  # "Keep the abutments rigid" is not in the person's words
    assert s["_summary"]["unsafe"] >= 1
    # the model's guess at the anchor ("start fixed", no words of the person's) was asked about, never applied: the engine's gate held
    assert s["anchor_choice"]["unsafe"] == 0 and "person" in s["anchor_choice"]["detail"]
    assert s["geometry_execution"]["score"] == 1.0 and s["_summary"]["engine"] == 1.0  # and what was applied is executed exactly


def test_a_misidentified_part_fails_the_geometry_and_the_scores_say_whose_fault_it_is(tmp_path):
    case = acc.make_case(tmp_path)
    res = acc.evaluate(acc.script_for(case, "wrong_part"), case, log=lambda *a: None)
    s = res["scores"]
    assert s["component_identification"]["score"] < 1.0  # the cause: the model grouped the wrong regions
    assert s["geometry_execution"]["score"] == 0.0 and s["_summary"]["outcome"] == 0.0  # the effect: the sheet is not what the author meant
    # ... and the ENGINE did its part: it measured the plan, refused what did not hold, and left the sheet exactly as imported
    assert s["engine_integrity"]["score"] == 1.0 and s["_summary"]["engine"] == 1.0 and s["_summary"]["ai"] < 1.0


def test_a_model_that_only_asks_never_guesses_and_the_run_waits(tmp_path):
    case = acc.make_case(tmp_path)
    gem = ScriptedModel([[call("ask_person", question="Which foundation do you mean: the PCC course under the box, or the wing wall footings?",
                               options=["the PCC course", "the wing wall footings"])]])
    sheet = case.sheet
    sheet.gem = gem
    rid = sheet.start_run({"instruction": case.instruction, "scope": {"views": ["V01"]}})["run"]
    import time

    for _ in range(300):
        if sheet.runs[rid].status != "running" and sheet.runs[rid].status != "queued":
            break
        time.sleep(0.05)
    run = sheet.runs[rid]
    s = acc.score(case, run)
    assert run.status == "awaiting_user" and s["clarification"]["score"] == 1.0 and s["_summary"]["unsafe"] == 0
    assert s["geometry_execution"]["score"] == 0.0 and sheet.sm.current().get(f"{case.uid}.ClearSpan") is None  # nothing was changed on a guess
    sheet.stop_run({"run": rid})


def test_the_live_limits_are_named_before_anything_is_started():
    lim = acc.live_limits()
    assert lim["max_turns"] == 60 and lim["soft_turns"] == 30 and lim["max_tokens"] == 250000 and lim["wall_s"] == 1200 and "billed" in lim["note"]
