"""What a long run costs, and what the person can see and say about it — each held with the model scripted, no network.

A live run on a real ten-unit sheet took 164 model calls and 4.1 M input tokens; only half of them were served from the provider's cache, and that half was always
the same 13,225-token first part: every turn changed something old in the conversation, so nothing after it could be reused. Its chunk never paused, one unit took
a third of the run, every turn thought as long as the hardest one, and the exact request of a call could not be looked at. Here:

  • a run is paused every 30 turns by default, and continuing loses and repeats nothing;
  • a unit that has taken 12 turns is told to wrap up, and the person is told it was;
  • a turn that follows reading and bookkeeping thinks less than one that follows the candidates or a refusal — and never above the model's own level;
  • older results are cut in batches, so between cuts the conversation only grows (what a provider's cache can serve);
  • every call is recorded: what it was made of, how much was the same as the call before, what the provider billed and cached; and the page can ask for it;
  • a saving that turns into a cost (no caching although the request was mostly the same; a change of thinking level that cost the cache) is switched off.
"""

from __future__ import annotations

import itertools
import json

from google.genai import types
from test_run import wait
from test_run_plan import PLAIN, chatty, reading, run, two_unit_session

from dxf_autoparam.ai.loop import Budget, LoopState, adaptive_thinking, keep_pictures, trim
from dxf_autoparam.ai.requestlog import CacheWatch, RequestLog
from dxf_autoparam.ai.run import ACTIVE, THINKING_HEAVY, THINKING_MECHANICAL, THINKING_OPENING
from dxf_autoparam.ai.scripted import call

# ── the chunk ────────────────────────────────────────────────────────────────────


def test_by_default_a_run_is_paused_after_thirty_turns_and_continuing_loses_and_repeats_nothing(tmp_path):
    assert Budget().soft_turns == 30 and Budget.from_env().soft_turns == 30 and Budget().unit_turns == 12 and Budget().max_turns >= 1000
    assert Budget().with_(soft_turns=5, max_turns=3).soft_turns == 3 and Budget().with_(soft_turns=0).soft_turns == 0
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, [[reading(PLAIN)], [call("open_unit", unit="U01")], *chatty(60), [call("finish", summary="x")]])
    rid, p = run(sheet)
    assert p["status"] == "paused" and p["usage"]["turns"] == 30 and p["usage"]["limits"]["soft_turns"] == 30 and p["can"]["continue"]
    first = {e["id"] for e in p["events"] if e["kind"] == "tool"}
    for _ in range(4):
        if p["status"] != "paused":
            break
        sheet.continue_run({"run": rid})
        p = wait(sheet, rid, until=lambda q: q["status"] not in ACTIVE)
    ids = [e["id"] for e in p["events"] if e["kind"] == "tool"]
    assert p["status"] == "completed" and len(ids) == len(set(ids)) and first <= set(ids), "the pauses lost nothing and repeated nothing"
    assert sum(1 for e in p["events"] if e["kind"] == "state" and e["to"] == "paused") == 2


def test_a_run_can_still_be_asked_never_to_pause(tmp_path):
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, [[reading(PLAIN)], [call("open_unit", unit="U01")], *chatty(40), [call("finish", summary="x")]])
    _rid, p = run(sheet, budget={"soft_turns": 0})
    assert p["status"] == "completed" and p["usage"]["turns"] > 40 and p["usage"]["limits"]["soft_turns"] == 0
    assert not any(e["kind"] == "state" and e["to"] == "paused" for e in p["events"])


# ── the unit's share of turns ────────────────────────────────────────────────────


def test_a_unit_that_has_taken_twelve_turns_is_told_to_wrap_up_and_so_is_the_person(tmp_path):
    sheet, _sm, _ua, _ub, gem = two_unit_session(tmp_path, [[reading(PLAIN)], [call("open_unit", unit="U01")], *chatty(16), [call("finish", summary="x")]])
    _rid, p = run(sheet, budget={"soft_turns": 0})
    notes = [e["text"] for e in p["events"] if e["kind"] == "note" and "turns spent on" in e.get("text", "")]
    assert len(notes) == 1 and notes[0].startswith("U01: 12 turns spent on this unit"), notes
    told = [fr for seen in gem.seen for fr in seen if "unit_budget" in json.dumps(fr.response)]
    assert len(told) == 1, "the agent read it once, in the result of that turn"
    said = json.dumps(told[0].response)
    assert "one unit's budget is 12" in said and "open the next unit" in said


def test_the_unit_budget_can_be_turned_off_and_a_unit_is_never_cut_off(tmp_path):
    sheet, _sm, _ua, _ub, gem = two_unit_session(tmp_path, [[reading(PLAIN)], [call("open_unit", unit="U01")], *chatty(16), [call("finish", summary="x")]])
    _rid, p = run(sheet, budget={"soft_turns": 0, "unit_turns": 0})
    assert p["status"] == "completed" and not any("turns spent on" in e.get("text", "") for e in p["events"] if e["kind"] == "note")
    assert not any("unit_budget" in json.dumps(fr.response) for seen in gem.seen for fr in seen)


# ── the thinking level ───────────────────────────────────────────────────────────

KINDS = {"mechanical": THINKING_MECHANICAL, "heavy": THINKING_HEAVY, "opening": THINKING_OPENING}


def test_the_thinking_level_follows_what_the_last_turn_did_and_never_exceeds_the_models_own():
    assert adaptive_thinking("high", ["rename_values", "update_checklist"], False, KINDS)[0] == "low"
    assert adaptive_thinking("high", ["inspect_lines", "zoom_view"], False, KINDS)[0] == "low"
    assert adaptive_thinking("high", ["open_unit"], False, KINDS)[0] == "medium"
    assert adaptive_thinking("high", ["inspect_candidates"], False, KINDS)[0] == "high", "after the candidates: the turn that designs the unit's parts"
    assert adaptive_thinking("high", ["propose_plan"], False, KINDS)[0] == "high"
    assert adaptive_thinking("high", ["define_parts", "define_parameters"], False, KINDS)[0] == "medium", "carrying on after edits the engine accepted"
    level, why = adaptive_thinking("high", ["rename_values"], True, KINDS)
    assert level == "high" and "repairing" in why, "a refusal is repaired at full strength, whatever the call was"
    assert adaptive_thinking("high", ["inspect_candidates", "rename_values"], False, KINDS)[0] == "high", "one heavy call makes the turn heavy"
    assert adaptive_thinking("high", ["rename_values", "define_parts"], False, KINDS)[0] == "medium", "a mix is not mechanical"
    level, why = adaptive_thinking("low", ["inspect_candidates"], False, KINDS)
    assert level == "low" and "capped" in why, "a model chosen to think little is not made to think more"
    assert adaptive_thinking("medium", ["open_unit"], False, KINDS)[0] == "medium"
    assert "inspect_candidates" in THINKING_HEAVY and "inspect_candidates" not in THINKING_MECHANICAL
    assert {"account_instruction", "rename_values", "update_checklist", "record_learned", "inspect_sheet", "zoom_view"} <= THINKING_MECHANICAL
    assert not (THINKING_MECHANICAL & THINKING_HEAVY) and not (THINKING_MECHANICAL & THINKING_OPENING)
    assert LoopState().last_calls == [] and LoopState().last_failed is False


def test_a_run_thinks_at_one_level_unless_levels_that_follow_the_last_turn_are_asked_for(tmp_path):
    """A changed level costs the provider's cache more than a lower level saves, so every turn after the first thinks at one level by default."""
    script = [[reading(PLAIN)], [call("open_unit", unit="U01")], [call("find_values", value_mm=3000)], [call("find_values", value_mm=3000)]]
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, script)
    _rid, p = run(sheet, budget={"soft_turns": 0, "max_turns": 4})
    assert [e["thinking"] for e in p["events"] if e["kind"] == "call"] == ["high"] * 4


def test_a_run_thinks_at_the_level_the_last_turn_calls_for(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPARAM_AGENT_ADAPTIVE_THINKING", "1")  # opt-in
    script = [[reading(PLAIN)], [call("open_unit", unit="U01")], [call("find_values", value_mm=3000)], [call("open_unit", unit="NOPE")], [call("find_values", value_mm=3000)],
              [call("find_values", value_mm=3000)]]
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, script)
    _rid, p = run(sheet, budget={"soft_turns": 0, "max_turns": 6})
    levels = [e["thinking"] for e in p["events"] if e["kind"] == "call"]
    # 1 the first turn · 2 after bookkeeping · 3 after open_unit · 4 after a read · 5 after a refusal (NOPE is no unit) · 6 after a read
    assert levels == ["high", "low", "medium", "low", "high", "low"], levels
    turns = [e for e in p["events"] if e["kind"] == "turn"]
    assert all(t["thinking"] and t["thinking_why"] for t in turns) and "repairing" in turns[4]["thinking_why"]


def test_a_level_fixed_by_the_environment_or_the_caller_is_not_second_guessed(tmp_path, monkeypatch):
    monkeypatch.setenv("VERTEX_AGENT_STEP_THINKING", "medium")
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, [[reading(PLAIN)], [call("open_unit", unit="U01")], [call("find_values", value_mm=3000)], [call("find_values", value_mm=3000)]])
    _rid, p = run(sheet, budget={"soft_turns": 0, "max_turns": 4})
    assert [e["thinking"] for e in p["events"] if e["kind"] == "call"] == ["high", "medium", "medium", "medium"]


# ── older results are cut together ───────────────────────────────────────────────


_SEQ = itertools.count(1)


def _exchange(name: str = "find_values", chars: int = 900, images: int = 0):
    """One model call and its result; no two are the same (as no two turns of a run are)."""
    n = next(_SEQ)
    ask = types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args={"v": n}))])
    parts = [types.FunctionResponsePart(inline_data=types.FunctionResponseBlob(mime_type="image/png", data=b"\x89PNG" + bytes(200))) for _ in range(images)]
    got = types.Part.from_function_response(name=name, response={"result": {"text": f"{n}:" + "x" * chars}}, **({"parts": parts} if parts else {}))
    return [ask, types.Content(role="user", parts=[got])]


def _conversation(n: int, images: int = 0) -> list:
    out: list = []
    for _ in range(n):
        out += _exchange(images=images)
    return out


def _frozen(history: list) -> list[str]:
    return [json.dumps(c.model_dump(mode="json", exclude_none=True), sort_keys=True) for c in history]


def test_old_results_are_cut_together_so_between_cuts_the_conversation_only_grows():
    h = _conversation(10)
    assert trim(h, keep=6, batch=4) == 4, "ten results, six kept: four are due, and four is the batch"
    for _ in range(3):  # the next turns add one result each: one is due, then two, then three — none is cut yet
        h += _exchange()
        before = _frozen(h)
        assert trim(h, keep=6, batch=4) == 0 and _frozen(h) == before, "nothing old changes: a provider's cache can serve all of the request before the new turn"
    h += _exchange()
    assert trim(h, keep=6, batch=4) == 4, "the fourth is due: all four are cut at once"
    one = _conversation(10)
    assert trim(one, keep=6) == 4 and (one.append(_exchange()[0]), one.append(_exchange()[1]), trim(one, keep=6))[2] == 1, "batch 1 is the old behaviour"


def test_old_pictures_are_dropped_together_too():
    h = _conversation(5, images=2)
    assert keep_pictures(h, keep=3, batch=3) == 0, "two results are due, three are the batch"
    h += _exchange(images=2)
    assert keep_pictures(h, keep=3, batch=3) == 3, "the third is due: the three oldest lose their pictures together"
    assert sum(1 for c in h if c.role == "user" and any(getattr(p.function_response, "parts", None) for p in c.parts)) == 3
    assert keep_pictures(h, keep=3, batch=3) == 0


# ── the record of the requests ───────────────────────────────────────────────────

SYSTEM = "You turn a drawing into a parametric model. " * 20


def _record(log: RequestLog, history: list, **kw):
    prefix = [types.Part.from_text(text="the whole drawing " * 400), types.Part.from_bytes(data=b"\x89PNG" + bytes(300), mime_type="image/png")]
    return log.record(turn=kw.pop("turn", len(history) // 2 + 1), label="turn", model="m", thinking="high", why="", system=kw.pop("system", SYSTEM), tools=[], prefix_parts=prefix,
                      history=history, explicit=False, **kw)


def test_a_conversation_that_only_grows_is_the_same_request_as_before_plus_the_new_turn():
    log, h = RequestLog(), _conversation(6)
    first = _record(log, h)
    assert first["prefix_reuse"] == {"with": None} and first["totals"]["images"] == 1
    h += _exchange()
    second = _record(log, h)
    r = second["prefix_reuse"]
    assert r["with"] == 1 and r["contents_same"] == len(first["contents"]) and r["share"] > 0.95 and "broke_because" not in r


def test_a_cut_in_the_older_conversation_is_said_with_where_and_why():
    log, h = RequestLog(), _conversation(10)
    _record(log, h)
    cut = trim(h, keep=6, batch=1)
    rec = _record(log, h, pruned={"trimmed": cut, "pictures": 0})
    r = rec["prefix_reuse"]
    assert cut == 4 and r["contents_same"] < len(rec["contents"]) - 1 and r["share"] < 1
    assert r["broke_because"] == "4 older tool result(s) were cut to their verdicts" and rec["pruned"] == {"trimmed": 4}
    folded = _record(log, h[-4:], pruned={"compacted": 3})
    assert folded["prefix_reuse"]["broke_at"] == 1 and "folded into the working state" in folded["prefix_reuse"]["broke_because"]
    changed = _record(log, h[-4:], system=SYSTEM + " (changed)")
    assert changed["prefix_reuse"]["share"] == 0 and "system prompt" in changed["prefix_reuse"]["broke_because"]


def test_the_billed_tokens_and_what_was_cached_are_kept_with_each_request():
    log, h = RequestLog(), _conversation(4)
    rec = _record(log, h)
    log.finish(rec, {"model": "m", "input_tokens": 20000, "vertex_cached_tokens": 13225, "output_tokens": 70, "thinking_tokens": 40, "seconds": 6.5, "finish": "STOP", "prompt_cache": "implicit"})
    u = rec["usage"]
    assert u["uncached_tokens"] == 6775 and u["cached_share"] == 0.661 and u["output_tokens"] == 70 and not u["replayed"]
    rep = _record(log, h + _exchange())
    log.finish(rep, {"input_tokens": 99999, "vertex_cached_tokens": 0, "cached": True})
    t = log.totals()
    assert t["calls"] == 2 and t["billed_calls"] == 1 and t["input_tokens"] == 20000 and t["cached_tokens"] == 13225, "a call replayed from disk costs nothing and is not counted"
    assert log.listing(since=1)["requests"][0]["n"] == 2 and log.listing()["next"] == 2


def test_a_request_can_be_read_whole_without_its_pictures_for_the_last_few_calls():
    log, h = RequestLog(), _conversation(3, images=1)
    for k in range(5):
        _record(log, h + _conversation(k))
    assert log.payload(1) is None and log.payload(2) is None and log.payload(5) is not None, "only the last three are kept whole"
    body = json.loads(log.payload(5))
    assert body["system"] == SYSTEM and body["model"] == "m" and "contents" in body and "prefix" in body
    text = log.payload(5)
    assert "iVBOR" not in text and '"elided": true' in text, "a picture is a size and a digest, not its bytes"


# ── the watch on the saving ──────────────────────────────────────────────────────


def _call(thinking: str, input_tokens: int, cached: int, share: float = 0.95, replayed: bool = False) -> dict:
    return {"thinking": thinking, "prefix_reuse": {"with": 1, "share": share},
            "usage": {"input_tokens": input_tokens, "cached_tokens": cached, "cached_share": round(cached / input_tokens, 3), "replayed": replayed}}


def test_a_provider_that_caches_nothing_of_a_mostly_unchanged_request_is_noticed_after_three_calls():
    w = CacheWatch()
    for _ in range(2):
        w.observe(_call("high", 30000, 0))
    assert not w.silent()
    w.observe(_call("high", 31000, 0))
    assert w.silent()
    ok = CacheWatch()
    for _ in range(5):
        ok.observe(_call("high", 30000, 27000))
    assert not ok.silent()


def test_what_says_nothing_about_caching_is_not_counted_against_it():
    w = CacheWatch()
    for rec in (_call("high", 30000, 0, share=0.3), _call("high", 4000, 0), _call("high", 30000, 0, replayed=True), _call("high", 30000, 0, share=0.5)):
        w.observe(rec)
    assert w.bad == 0, "a request that changed much, a small one and a replayed one tell nothing"
    w.observe(_call("high", 30000, 0))
    w.observe(_call("high", 30000, 20000))
    assert w.bad == 0, "one good call starts the count again"


def test_a_change_of_thinking_level_that_cost_the_cache_is_noticed_only_when_it_happens_again_and_again():
    w = CacheWatch()
    w.observe(_call("high", 30000, 25000))
    w.observe(_call("low", 31000, 4500))  # the cache went with the level
    assert not w.level_broke()
    w.observe(_call("low", 32000, 28000))
    w.observe(_call("high", 33000, 6000))  # and again
    assert w.level_broke()
    fine = CacheWatch()
    for k, lv in enumerate(["high", "low", "high", "low", "high"]):
        fine.observe(_call(lv, 30000 + 1000 * k, 25000 + 1000 * k))
    assert not fine.level_broke() and fine.level_ok == 4, "levels changed and the cache held: nothing to switch off"


def test_the_level_changes_of_a_live_run_are_noticed_although_each_one_started_from_an_already_collapsed_cache():
    """The first paid run on the raw sheet (calls 4-8 of R1): the cache followed the level, and the first version of this watch compared each call
    with the call before's own cached tokens, so after the first collapse it counted the next changes as harmless and never switched anything off."""
    w = CacheWatch()
    for rec in (_call("medium", 45655, 41207, share=0.976), _call("low", 47181, 15872, share=0.957), _call("high", 48310, 19037, share=0.971),
                _call("medium", 51265, 44339, share=0.926)):
        w.observe(rec)
    assert w.level_breaks == 2 and w.level_ok == 1 and w.level_broke()


# ── the run and the page ─────────────────────────────────────────────────────────


def test_every_model_call_of_a_run_is_recorded_and_the_page_can_ask_for_any_of_them(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPARAM_AGENT_ADAPTIVE_THINKING", "1")  # the record shows the level of each call: here they differ
    sheet, _sm, _ua, _ub, _gem = two_unit_session(tmp_path, [[reading(PLAIN)], [call("open_unit", unit="U01")], [call("find_values", value_mm=3000)], [call("finish", summary="x")]])
    rid, p = run(sheet, budget={"soft_turns": 0})
    got = sheet.run_requests(rid)
    assert got["run"] == rid and [r["n"] for r in got["requests"]] == list(range(1, p["usage"]["turns"] + 1))
    first, second, third = got["requests"][:3]
    assert first["thinking"] == "high" and second["thinking"] == "low" and third["thinking"] == "medium" and first["prefix_reuse"] == {"with": None}
    assert second["prefix_reuse"]["with"] == 1 and second["prefix_reuse"]["contents_same"] >= 2 and second["thinking_why"]
    assert first["totals"]["images"] >= 1, "the pictures the run began with are in the prefix"
    assert got["totals"]["calls"] == len(got["requests"]) and got["next"] == got["requests"][-1]["n"]
    assert sheet.run_requests(rid, since=got["next"])["requests"] == []
    body = json.loads(sheet.run_request_payload(rid, got["next"]))
    assert body["system"] and body["contents"] and "iVBOR" not in json.dumps(body)
    assert sheet.run_request_payload(rid, 1) is None, "an old request is no longer kept whole"
    latest = sheet.run_requests(rid, limit=2, brief=True)
    assert [r["n"] for r in latest["requests"]] == [got["next"] - 1, got["next"]], "with no `since`: the latest calls"
    assert all("contents" not in r and r["totals"]["tokens_est"] for r in latest["requests"]) and "contents" in got["requests"][0]
