"""The unified agent session end to end — one instruction, the model scripted (no network, no cost), the real engine.

What is measured: the model's reading is checked (quotes, every sentence), it looks at pictures and zooms, plans a change the
engine measures, asks when something is the person's, is paused (not cut) by a budget and continued without doing anything twice,
and the state the page shows is the verdict the engine derived — never a message."""

from __future__ import annotations

import json
import time

import pytest

from dxf_autoparam.ai.run import ACTIVE
from dxf_autoparam.ai.scripted import ScriptedModel, call
from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.plan_bench import Box, box_answer, box_gad
from dxf_autoparam.workspace import SheetSession

INSTRUCTION = ("Reduce the clear span to 2500 mm, centred about the centre line. Keep the foundation fixed. Wing walls follow the box. "
               "Do not modify the unrelated pitching detail.")


Scripted = ScriptedModel


def session(tmp_path, script, **kw):
    g = box_gad(tmp_path / "box.dxf", Box())
    sheet = SheetSession(g["path"])
    uid = next(k for k, u in sheet.sm.units.items() if len(u.views) == 2)
    gem = Scripted(script, **kw)
    sheet.gem_factory = lambda: gem
    return sheet, uid, g, gem


def wait(sheet, rid=None, until=lambda p: p["status"] not in ACTIVE, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        p = sheet.run_progress(rid, 0)
        if until(p):
            return p
        time.sleep(0.03)
    raise AssertionError(f"the run did not settle: {sheet.run_progress(rid, 0)['status']}")


def reading(clauses):
    return call("account_instruction", items=[{"quote": q, "kind": k, "meaning": m, "handled_by": h} for q, k, m, h in clauses])


FULL_READING = [("Reduce the clear span to 2500 mm", "change_value", "ClearSpan becomes 2500", "plan"),
                ("centred about the centre line", "keep", "the box stays about its centre", "plan"),
                ("Keep the foundation fixed", "keep", "the foundation does not move", "plan"),
                ("Wing walls follow the box", "keep", "wing walls follow", "plan"),
                ("Do not modify the unrelated pitching detail", "keep", "excluded", "plan")]
DIRS = [{"target": "Foundation", "mode": "keep_fixed", "clause": "Keep the foundation fixed"},
        {"target": "WingLeft", "mode": "follow", "clause": "Wing walls follow the box"},
        {"target": "WingRight", "mode": "follow", "clause": "Wing walls follow the box"},
        {"target": "PitchingDetail", "mode": "exclude", "clause": "Do not modify the unrelated pitching detail"}]
ANCHOR = {"policy": "centered", "clause": "centred about the centre line"}


def parametrized_sheet(tmp_path, **kw):
    """A sheet whose box is already parametrized (the model's earlier work), so a run can concentrate on the change."""
    g = box_gad(tmp_path / "box.dxf", Box())
    sm = SheetModel.open(g["path"])
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    sm.commit_answer(uid, box_answer(sm, uid, g["box"], g["handles"]))
    sheet = SheetSession()
    sheet.sm = sm
    gem = Scripted(kw.pop("script"), **kw)
    sheet.gem_factory = lambda: gem
    return sheet, uid, g, gem


def test_the_run_is_driven_by_the_model_and_never_by_the_phrase_matcher(tmp_path, monkeypatch):
    """The old reader would have been asked about this instruction; here it must never be called, and the plan holds the model's proposal."""
    from dxf_autoparam import plan as plan_mod

    def boom(*a, **k):
        raise AssertionError("the rule-based reader was used on the run's path")

    monkeypatch.setattr(plan_mod, "read_instruction", boom)
    script = [[reading(FULL_READING)],
              [call("inspect_assembly", parameter="ClearSpan")],
              [call("propose_plan", parameter="ClearSpan", requested_value=2500, anchor=ANCHOR, directives=DIRS)],
              [call("finish", summary="planned and measured")]]
    sheet, uid, _g, gem = parametrized_sheet(tmp_path, script=script)
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    assert p["status"] == "completed", p["verdict"]
    v = p["verdict"]
    assert v["state"] == "completed" and all(c["ok"] for c in v["criteria"])
    assert sheet.sm.current()[f"{uid}.ClearSpan"] == 2500 and v["values_applied"][0]["value"] == 2500
    assert v["plans"][0]["ok"] and v["plans"][0]["checks"]["failed"] == 0
    # the model read it, the engine checked the reading
    first = gem.seen[0][0].response["result"]
    assert all(x["ok"] for x in first["result"]) and first["status"]["instruction"]["unaccounted"] == []


# ── the model looks: pictures in the request, a zoom tool that maps to the geometry ──────────────


def png_of_part(part):
    return part.inline_data.data if getattr(part, "inline_data", None) else None


def test_the_model_receives_the_pictures_of_the_view_it_works_on_and_they_match_the_context(tmp_path):
    from dxf_autoparam.ai.run import UNIFIED_SYSTEM

    sheet, uid, _g, gem = parametrized_sheet(tmp_path, script=[[reading(FULL_READING)], [call("finish", summary="x")], [call("finish", summary="x")]])
    sm = sheet.sm
    sheet.get_pictures()
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}})
    wait(sheet, r["run"])
    first = gem.requests[0]
    images = [p for p in first["prefix"] if png_of_part(p)]
    assert len(images) >= 3 and all(p.inline_data.mime_type == "image/png" for p in images)  # the sheet, the view with its lines, its regions
    pics = sheet.get_pictures()
    ids = [i for i in (f"IMG{n}" for n in range(1, 8)) if pics.meta(i)]
    assert [png_of_part(p) for p in images] == [pics.png_of(i) for i in ids[:len(images)]]  # the very pictures the engine drew, byte for byte
    metas = [pics.meta(i) for i in ids[:len(images)]]
    assert {m["revision"] for m in metas} == {sm.revision}  # one geometry revision
    assert metas[0]["view_ids"] == ["V01", "V02"] or set(metas[0]["view_ids"]) >= {"V01"}
    overview = next(p.text for p in first["prefix"] if getattr(p, "text", None))
    ctx = json.loads(overview.split("OVERVIEW:\n", 1)[1])["CONTEXT"]
    assert ctx["drawing"]["sheet_revision"] == sm.revision and ctx["drawing"]["unit"] == uid  # the numbers describe the same sheet
    assert "zoom_view" in first["tools"] and "inspect_sheet" in first["tools"] and "zoom_view" in UNIFIED_SYSTEM


def test_the_zoom_tool_returns_a_picture_whose_frame_maps_to_the_geometry_it_names(tmp_path):
    from io import BytesIO

    from PIL import Image

    from dxf_autoparam.cadjson import entity_id

    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=[[call("noop")]])
    u = sheet.sm.unit(uid)
    eid = next(entity_id(it) for it in u.sub.items if it.dxftype == "LWPOLYLINE")
    sheet.gem_factory = lambda: Scripted([[reading(FULL_READING)], [call("zoom_view", around=[eid], labels="entities", why="look at one outline")],
                                          [call("finish", summary="x")], [call("finish", summary="x")]])
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}})
    wait(sheet, r["run"])
    gem = sheet.gem
    reply = gem.seen[1][0]  # the engine's answer to the zoom call
    res = reply.response["result"]
    assert res["entities_labelled_count"] >= 1 and any(t["id"] == eid for t in res["entities_labelled"])
    img = Image.open(BytesIO(reply.parts[0].inline_data.data)).convert("RGB")  # the picture is IN the function response
    assert list(img.size) == res["size_px"]
    um = u.sub.units_mm
    tag = next(t for t in res["entities_labelled"] if t["id"] == eid)
    fr = res["frame"]
    px = fr["pad"] + (tag["at_mm"][0] / um - fr["origin"][0]) * fr["scale_px_per_unit"]
    py = fr["size"][1] - fr["pad"] - (tag["at_mm"][1] / um - fr["origin"][1]) * fr["scale_px_per_unit"]
    assert img.getpixel((round(px), round(py))) == (190, 0, 110)  # the tag's dot sits exactly where the coordinates say
    assert res["revision"] == sheet.sm.revision and res["image"] in {i["id"] for i in sheet.run_progress(None, 0)["images"]}
    assert any(e["kind"] == "tool" and e["name"] == "zoom_view" and e["image"]["id"] == res["image"] and e["said"] == "look at one outline"
               for e in sheet.run_progress(None, 0)["events"])
    # a crop that frames nothing the unit has is refused with the reason, not guessed
    sheet2, _uid2, _g, _gem = parametrized_sheet(tmp_path, script=[[call("noop")]])
    sheet2.gem_factory = lambda: Scripted([[call("zoom_view", around=["NOPE99"])], [call("finish", summary="x")], [call("finish", summary="x")]])
    r2 = sheet2.start_run({"instruction": "Look at the view and say what it shows.", "scope": {"views": ["V01"]}})
    wait(sheet2, r2["run"])
    assert "cannot frame NOPE99" in json.dumps(sheet2.gem.seen[0][0].response)


def test_a_picture_of_an_older_revision_is_stale_and_the_model_is_told(tmp_path):
    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=[[call("noop")]])
    pics = sheet.get_pictures()
    sm = sheet.sm
    a = pics.picture(box=sm.layout.group("V01").bbox, unit=uid, state="drawn", ids="lines")
    assert not pics.is_stale(a["id"]) and pics.meta(a["id"])["revision"] == sm.revision
    sm.apply({f"{uid}.ClearSpan": 2500})  # the sheet changes
    assert pics.is_stale(a["id"]) and pics.meta(a["id"])["stale"] and pics.meta(a["id"])["current_revision"] == sm.revision
    b = pics.picture(box=sm.layout.group("V01").bbox, unit=uid, state="drawn", ids="lines")
    assert b["id"] != a["id"] and not pics.is_stale(b["id"])  # a new picture of the new revision
    cur = pics.picture(box=sm.layout.group("V01").bbox, unit=uid, state="current", ids="none", baseline=True)
    assert cur["meta"]["differs_from_drawn"] and cur["meta"]["fingerprint"] != b["meta"]["fingerprint"]  # the geometry itself differs


# ── budgets pause, they never cut: continue, stop, limits, no duplicate work ─────────────────────


def chatty(n: int):
    """n turns of an edit and a look each: more than 30 tool calls, the way a long task goes."""
    return [[call("set_structure", structure_type="RCC box culvert", family="rcc_box", views=["section", "plan"], summary=f"turn {k}"),
             call("find_values", value_mm=3000)] for k in range(n)]


def test_a_run_goes_past_thirty_tool_calls_when_the_budget_allows_it(tmp_path):
    sheet, _uid, _g, _gem = parametrized_sheet(tmp_path, script=[[reading(FULL_READING)], *chatty(24), [call("finish", summary="x")], [call("finish", summary="x")]])
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}, "options": {"budget": {"soft_turns": 100}}})
    p = wait(sheet, r["run"])
    assert p["usage"]["tool_calls"] > 30 and p["usage"]["turns"] > 25  # the old loop stopped at 30 turns whatever had been done
    assert p["status"] in ("completed", "partial") and p["verdict"]["criteria"][0]["id"] == "finished"


def test_a_chunk_ends_in_a_pause_and_continuing_does_not_do_anything_twice(tmp_path):
    script = [[reading(FULL_READING)], *chatty(6), [call("inspect_assembly", parameter="ClearSpan")],
              [call("propose_plan", parameter="ClearSpan", requested_value=2500, anchor=ANCHOR, directives=DIRS)], [call("finish", summary="x")]]
    sheet, uid, _g, gem = parametrized_sheet(tmp_path, script=script)
    depth = len(sheet.sm.history)
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}, "options": {"budget": {"soft_turns": 4}}})
    p = wait(sheet, r["run"])
    assert p["status"] == "paused" and p["usage"]["turns"] == 4 and p["can"]["continue"] and p["verdict"] is None  # paused: not finished, not failed
    assert len(sheet.sm.history) == depth and sheet.sm.current()[f"{uid}.ClearSpan"] == 3000  # nothing was applied half way
    seen = {(e["name"], e["id"]) for e in p["events"] if e["kind"] == "tool"}
    for _ in range(4):  # chunk after chunk, with the state it had
        if p["status"] != "paused":
            break
        sheet.continue_run({"run": r["run"]})
        p = wait(sheet, r["run"], until=lambda q: q["status"] not in ACTIVE)
    assert p["status"] == "completed", p["verdict"]
    tool_ids = [e["id"] for e in p["events"] if e["kind"] == "tool"]
    assert len(tool_ids) == len(set(tool_ids)) and seen <= {(e["name"], e["id"]) for e in p["events"] if e["kind"] == "tool"}  # no call repeated
    assert sum(1 for e in p["events"] if e["kind"] == "tool" and e["name"] == "propose_plan") == 1 and not gem.script
    assert len(sheet.sm.history) == depth + 2  # the answer and its value, applied once


def test_a_hard_limit_ends_the_run_incomplete_and_says_so(tmp_path):
    sheet, _uid, _g, _gem = parametrized_sheet(tmp_path, script=[[reading(FULL_READING)], *chatty(20)])
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}, "options": {"budget": {"max_turns": 5, "soft_turns": 50}}})
    p = wait(sheet, r["run"])
    assert p["status"] == "exhausted" and "limit" in p["reason"] and p["verdict"] is None  # never "complete"
    assert p["usage"]["turns"] == 5 and p["can"]["apply"]
    done = sheet.apply_run({"run": r["run"]})["verdict"]
    assert done["state"] == "partial" and done["criteria"][0] == {"id": "finished", "ok": False, "detail": done["criteria"][0]["detail"]}
    assert any("without a finish" in x for x in done["remaining"])
    # more room: the same run is continued with more turns, and settles
    sheet2, _uid2, _g2, _gem2 = parametrized_sheet(tmp_path, script=[[reading(FULL_READING)], *chatty(3), [call("finish", summary="x")], [call("finish", summary="x")]])
    r2 = sheet2.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}, "options": {"budget": {"max_turns": 3, "soft_turns": 50}}})
    assert wait(sheet2, r2["run"])["status"] == "exhausted"
    sheet2.continue_run({"run": r2["run"], "more_turns": 20})
    assert wait(sheet2, r2["run"])["status"] in ("completed", "partial")


def test_stop_abandons_the_call_in_flight_and_the_run_can_be_continued(tmp_path):
    sheet, _uid, _g, gem = parametrized_sheet(tmp_path, script=[[reading(FULL_READING)], *chatty(3), [call("finish", summary="x")], [call("finish", summary="x")]], delay=0.4)
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}})
    wait(sheet, r["run"], until=lambda q: q["usage"]["turns"] >= 2)
    sheet.stop_run({"run": r["run"]})
    p = wait(sheet, r["run"])
    assert p["status"] == "stopped" and p["can"]["continue"] and p["verdict"] is None
    turns_then = p["usage"]["turns"]
    gem.delay = 0.0
    sheet.continue_run({"run": r["run"]})
    p = wait(sheet, r["run"])
    assert p["status"] in ("completed", "partial") and p["usage"]["turns"] > turns_then - 1


def test_a_failure_is_failure_and_a_model_that_did_not_answer_can_be_retried(tmp_path):
    from dxf_autoparam.ai.vertex import GeminiUnavailable

    class Down(Scripted):
        def step(self, *a, **k):
            if not getattr(self, "up", False):
                raise GeminiUnavailable("Vertex AI did not answer (scripted)")
            return super().step(*a, **k)

    sheet, _uid, _g, _gem = parametrized_sheet(tmp_path, script=[[call("noop")]])
    gem = Down([[reading(FULL_READING)], [call("finish", summary="x")], [call("finish", summary="x")]])
    sheet.gem = gem
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    assert p["status"] == "failed" and "did not answer" in p["error"] and p["can"]["continue"] and p["verdict"] is None
    gem.up = True
    sheet.continue_run({"run": r["run"]})
    p = wait(sheet, r["run"])
    assert p["status"] in ("completed", "partial") and p["error"] is not None  # the earlier failure stays on record
    assert [e["to"] for e in p["events"] if e["kind"] == "state"][:3] == ["running", "failed", "running"]


def test_events_of_an_older_run_never_describe_a_newer_one(tmp_path):
    sheet, _uid, _g, _gem = parametrized_sheet(tmp_path, script=[[reading(FULL_READING)], [call("finish", summary="x")], [call("finish", summary="x")],
                                                              [reading(FULL_READING)], [call("finish", summary="x")], [call("finish", summary="x")]])
    a = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}})["run"]
    pa = wait(sheet, a)
    b = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}})["run"]
    pb = wait(sheet, b)
    assert a != b and sheet.current_run == b
    assert {e["run"] for e in pa["events"]} == {a} and {e["run"] for e in pb["events"]} == {b}
    assert sheet.run_progress(a, 0)["run"] == a and sheet.run_progress(None, 0)["run"] == b  # a page asks for its run by id
    assert [r["id"] for r in sheet.run_list()["runs"]] == [b, a]
    with pytest.raises(Exception, match="already working"):  # one run at a time on one sheet
        slow = Scripted([[reading(FULL_READING)]] * 3, delay=0.5)
        sheet.gem = slow
        sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}})
        sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}})
    sheet.stop_run({"run": sheet.current_run})
    wait(sheet)


# ── what only the person can decide is asked, never guessed ─────────────────────────────────────

SAID2 = ("Reduce the clear span to 2500 mm. Keep the foundation fixed. The wing walls follow the box. "
         "Leave the unrelated pitching detail alone. Show me anything ambiguous before applying the change.")
READ2 = [("Reduce the clear span to 2500 mm", "change_value", "ClearSpan becomes 2500", "plan"),
         ("Keep the foundation fixed", "keep", "the foundation does not move", "plan"),
         ("The wing walls follow the box", "keep", "wings follow", "plan"),
         ("Leave the unrelated pitching detail alone", "keep", "excluded", "plan"),
         ("Show me anything ambiguous before applying the change", "process", "ask before deciding", "question")]
DIRS2 = [{"target": "Foundation", "mode": "keep_fixed", "clause": "Keep the foundation fixed"},
         {"target": "WingLeft", "mode": "follow", "clause": "The wing walls follow the box"},
         {"target": "WingRight", "mode": "follow", "clause": "The wing walls follow the box"},
         {"target": "PitchingDetail", "mode": "exclude", "clause": "Leave the unrelated pitching detail alone"},
         {"target": "OuterWall", "mode": "keep_value", "clause": "", "why": "walls usually keep their thickness"}]  # the model's own inference


def answer_all(p, pick=lambda q: q.get("recommended") or (q["options"][0] if q["options"] else "ok")):
    return {q["id"]: pick(q) for q in p["questions"]}


def test_an_unstated_anchor_and_an_inference_are_put_to_the_person_and_their_answers_apply_without_the_model(tmp_path):
    script = [[reading(READ2)], [call("propose_plan", parameter="ClearSpan", requested_value=2500, directives=DIRS2)], [call("finish", summary="the plan waits for you")],
              [call("finish", summary="applied with your answers")]]
    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=script)
    r = sheet.start_run({"instruction": SAID2, "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    assert p["status"] == "awaiting_user" and p["verdict"] is None and p["can"]["answer"] and not p["can"]["continue"]
    abouts = {q["about"] for q in p["questions"]}
    assert "anchor" in abouts and any("AI proposes" in q["text"] for q in p["questions"])  # the unstated anchor; the model's own guess
    assert sheet.sm.current()[f"{uid}.ClearSpan"] == 3000  # nothing applied while a question is open
    with pytest.raises(Exception, match="answer the questions"):
        sheet.continue_run({"run": r["run"]})
    ans = answer_all(p, lambda q: "centered" if q["about"] == "anchor" else "accept" if "accept" in q["options"] else q["options"][0])
    sheet.continue_run({"run": r["run"], "answers": ans})
    p = wait(sheet, r["run"])
    assert p["status"] == "completed", p["verdict"]["remaining"]
    plan = sheet.sm.unit(uid).answer["plans"][0]
    assert plan["status"] == "accepted" and plan["anchor"]["policy"] == "centered" and plan["anchor"]["source"] == "person"
    by_source = {d["target"]: d["source"] for d in plan["directives"]}
    assert by_source["Foundation"] == "instruction" and by_source["OuterWall"].startswith("person (accepted")  # told apart: theirs, and the AI's they accepted
    assert sheet.sm.current()[f"{uid}.ClearSpan"] == 2500


def test_a_word_that_names_nothing_is_a_question_and_declining_a_proposal_leaves_the_drawing_alone(tmp_path):
    script = [[reading(READ2[:1])], [call("ask_person", question="What do you mean by 'the pitching detail': the stone pitching in the plan, or the detail at the right?",
                                         options=["the stone pitching", "the detail at the right"])],
              [call("finish", summary="x")]]
    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=script)
    r = sheet.start_run({"instruction": SAID2, "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    assert p["status"] == "awaiting_user" and p["questions"][0]["options"] == ["the stone pitching", "the detail at the right"]
    assert sheet.sm.current()[f"{uid}.ClearSpan"] == 3000  # a guess would have moved something
    sheet.continue_run({"run": r["run"], "answers": {p["questions"][0]["id"]: "the stone pitching"}})
    p = wait(sheet, r["run"])
    assert p["status"] == "partial"  # the instruction's other sentences were never accounted for: said, not hidden
    assert any("not accounted for" in x for x in p["verdict"]["remaining"])
    assert any("answers recorded" in e.get("text", "") for e in p["events"])


def test_the_person_can_ask_to_confirm_the_plan_before_it_is_applied(tmp_path):
    script = [[reading(FULL_READING)], [call("propose_plan", parameter="ClearSpan", requested_value=2500, anchor=ANCHOR, directives=DIRS)],
              [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=script)
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}, "options": {"confirm_plan": True}})
    p = wait(sheet, r["run"])
    assert p["status"] == "awaiting_user" and [q["about"] for q in p["questions"]] == ["approve:P_ClearSpan"]
    assert "not changed until you say so" in p["questions"][0]["text"] and sheet.sm.current()[f"{uid}.ClearSpan"] == 3000
    sheet.continue_run({"run": r["run"], "answers": {p["questions"][0]["id"]: "apply"}})
    p = wait(sheet, r["run"])
    assert p["status"] == "completed" and sheet.sm.current()[f"{uid}.ClearSpan"] == 2500
    # declined: nothing applied, and the run says it is not complete
    sheet2, uid2, _g2, _gem2 = parametrized_sheet(tmp_path, script=[[reading(FULL_READING)], [call("propose_plan", parameter="ClearSpan", requested_value=2500, anchor=ANCHOR, directives=DIRS)],
                                                                   [call("finish", summary="x")], [call("finish", summary="x")], [call("finish", summary="x")]])
    r2 = sheet2.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}, "options": {"confirm_plan": True}})
    q = wait(sheet2, r2["run"])["questions"][0]["id"]
    sheet2.continue_run({"run": r2["run"], "answers": {q: "do not apply"}})
    p2 = wait(sheet2, r2["run"])
    assert p2["status"] == "partial" and sheet2.sm.current()[f"{uid2}.ClearSpan"] == 3000
    assert any("declined" in x or "waits" in x or "plan" in x for x in p2["verdict"]["remaining"])


# ── no success for an incomplete, refused or unmeasured change ──────────────────────────────────


def test_a_refused_edit_a_failed_check_and_an_open_problem_never_become_complete(tmp_path):

    u0 = parametrized_sheet(tmp_path, script=[[call("noop")]])[0].sm
    # a parameter naming two lines on different axes is refused by the engine; the model never repairs it
    an = u0.unit(next(iter(u0.units))).an
    x_line = next(d.id for d in an.datums.values() if d.axis == "x" and not d.virtual)
    y_line = next(d.id for d in an.datums.values() if d.axis == "y" and not d.virtual)
    script = [[reading(FULL_READING[:1])], [call("define_parameters", items=[{"name": "Wrong", "part": "Box", "from_line": x_line, "to_line": y_line}])],
              [call("finish", summary="done")], [call("finish", summary="done anyway")]]
    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=script)
    r = sheet.start_run({"instruction": "Reduce the clear span to 2500 mm.", "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    refused = [e for e in p["events"] if e["kind"] == "tool" and e["name"] == "define_parameters"]
    assert refused and refused[0]["ok"] is False and "V1" in refused[0]["why"]  # the timeline shows the refusal as one
    v = p["verdict"]
    crit = {c["id"]: c for c in v["criteria"]}
    assert p["status"] in ("partial", "failed") and v["state"] != "completed"
    assert not crit["refusals_repaired"]["ok"] and not crit["plans_measured"]["ok"]  # asked for a change; no plan; a refusal left
    assert any("refused" in x or "no plan" in x for x in v["remaining"])
    assert sheet.sm.current()[f"{uid}.ClearSpan"] == 3000  # and nothing moved
    # the status the page shows is derived from the same engine state: no unit is "validated" or "complete" here
    st = sheet.status()
    assert st["units"][uid]["state"] not in ("complete",) and st["overall"] != "complete"


def test_a_refused_requested_value_is_reported_as_refused_not_applied(tmp_path):
    script = [[reading(FULL_READING)], [call("propose_plan", parameter="ClearSpan", requested_value=100, anchor=ANCHOR, directives=DIRS)],
              [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=script)
    r = sheet.start_run({"instruction": INSTRUCTION.replace("2500", "100"), "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    assert p["status"] in ("partial", "failed") and sheet.sm.current()[f"{uid}.ClearSpan"] == 3000
    assert any("ClearSpan" in x for x in p["verdict"]["remaining"]) or any(c["id"] == "plans_measured" and not c["ok"] for c in p["verdict"]["criteria"])


# ── the whole job, from a drawing nobody has parametrized: the scripted agent workflow ──────────


def test_a_scripted_agent_parametrizes_and_changes_the_two_view_box_from_one_instruction(tmp_path):
    """The brief's definition of done, end to end on the generated two-view box (its intended geometry is known exactly): the model reads the
    instruction, looks, names the parts and the value from the drawing, plans the change, is asked the one thing it cannot settle, the
    engine applies and measures it — and both views and the sheet's status say the same thing."""
    from test_intent_plan import off_intent

    from dxf_autoparam.plan_bench import answer_as_calls

    g = box_gad(tmp_path / "box.dxf", Box())
    sheet = SheetSession(g["path"])
    uid = next(k for k, u in sheet.sm.units.items() if len(u.views) == 2)
    ans = box_answer(sheet.sm, uid, g["box"], g["handles"])
    build = [call(name, **args) for name, args in answer_as_calls(ans)]
    said = ("Reduce the clear span to 2500 mm. Keep the middle wall centered, preserve the wall and slab thicknesses, keep the existing foundation fixed. "
            "The wing walls follow the box. Keep the unrelated pitching detail unchanged.")
    reading_ = [("Reduce the clear span to 2500 mm", "change_value", "ClearSpan = 2500", "plan"),
                ("Keep the middle wall centered", "keep", "the middle wall stays on the centre line", "plan"),
                ("preserve the wall and slab thicknesses", "keep", "thicknesses keep their values", "plan"),
                ("keep the existing foundation fixed", "keep", "foundation does not move", "plan"),
                ("The wing walls follow the box", "keep", "wings follow", "plan"),
                ("Keep the unrelated pitching detail unchanged", "keep", "excluded", "plan")]
    dirs = [{"target": "Foundation", "mode": "keep_fixed", "clause": "keep the existing foundation fixed"},
            {"target": "WingLeft", "mode": "follow", "clause": "The wing walls follow the box"},
            {"target": "WingRight", "mode": "follow", "clause": "The wing walls follow the box"},
            {"target": "PitchingDetail", "mode": "exclude", "clause": "Keep the unrelated pitching detail unchanged"},
            {"target": "OuterWall", "mode": "keep_value", "clause": "preserve the wall and slab thicknesses"},
            {"target": "TopSlab", "mode": "keep_value", "clause": "preserve the wall and slab thicknesses"},
            {"target": "BottomSlab", "mode": "keep_value", "clause": "preserve the wall and slab thicknesses"}]
    from dxf_autoparam.cadjson import entity_id

    eid = entity_id(next(it for it in sheet.sm.unit(uid).sub.items if it.dxftype == "LWPOLYLINE"))
    script = [[reading(reading_)], [call("inspect_sheet")], [call("zoom_view", around=[eid])], build,
              [call("inspect_assembly", parameter="ClearSpan")],
              [call("propose_plan", parameter="ClearSpan", requested_value=2500, directives=dirs)],  # "centered": the person said where; the model did not quote it
              [call("finish", summary="the plan waits for the anchor")], [call("finish", summary="done")]]
    gem = Scripted(script)
    sheet.gem_factory = lambda: gem
    r = sheet.start_run({"instruction": said, "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    assert p["status"] == "awaiting_user", (p["status"], p["verdict"])
    q = next(x for x in p["questions"] if x["about"] == "anchor")
    assert any(o.startswith("centered") for o in q["options"])
    sheet.continue_run({"run": r["run"], "answers": {q["id"]: next(o for o in q["options"] if o.startswith("centered"))}})
    p = wait(sheet, r["run"])
    assert p["status"] == "completed", p["verdict"]["remaining"]
    sm = sheet.sm
    assert sm.current()[f"{uid}.ClearSpan"] == 2500
    assert off_intent(sm, g, 2500, "centered", foundation="keep_fixed") == []  # every member where the generator draws it at 2500, centred
    st = sheet.status()
    assert {v["state"] for v in st["views"]} == {"complete"} and st["overall"] == "complete" and "Everything is validated" in st["sentence"]
    # the run is in the project's history, and survives save and reload
    assert sm.runs and sm.runs[-1]["status"] == "completed" and sm.runs[-1]["verdict"]["state"] == "completed"
    path = tmp_path / "p.json"
    sm.save(str(path))
    sm2 = SheetModel.load(str(path), dxf=sm.path)
    assert sm2.runs[-1]["id"] == r["run"] and sm2.current()[f"{uid}.ClearSpan"] == 2500 and sm2.unit(uid).answer["plans"][0]["status"] == "accepted"
    # the edited drawing exports and re-opens strictly, with the dimensions and the note re-rendered at the new size
    out = tmp_path / "out.dxf"
    rep = sm.export(str(out))
    assert rep["audit"]["errors"] == 0 and not rep["errors"] and out.exists()
    import ezdxf

    texts = [e.dxf.text for e in ezdxf.readfile(str(out)).modelspace() if e.dxftype() in ("TEXT", "MTEXT")]
    assert any("2.500" in t for t in texts) and not any("3.000 X 2.500" in t for t in texts)  # the note that stated the size follows it
    # undo takes the whole change back; reset takes the value back to the imported drawing's
    assert sm.undo()
    sm.reset_drawing()
    assert not sm.regenerate().changed


# ── conflicting instructions are not guessed away; the timeline is the real calls; the baseline is the file's own ──


def test_a_conflicting_instruction_is_a_conflict_in_the_plan_and_nothing_moves(tmp_path):
    said = "Reduce the clear span to 2500 mm, centred. Keep the foundation fixed. The foundation follows the box."
    reading_ = [("Reduce the clear span to 2500 mm", "change_value", "x", "plan"), ("centred", "keep", "centred", "plan"),
                ("Keep the foundation fixed", "keep", "fixed", "plan"), ("The foundation follows the box", "keep", "follows", "plan")]
    dirs = [{"target": "Foundation", "mode": "keep_fixed", "clause": "Keep the foundation fixed"},
            {"target": "Foundation", "mode": "follow", "clause": "The foundation follows the box"}]  # the same part, both ways
    script = [[reading(reading_)], [call("propose_plan", parameter="ClearSpan", requested_value=2500, anchor={"policy": "centered", "clause": "centred"}, directives=dirs)],
              [call("finish", summary="x")], [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=script)
    r = sheet.start_run({"instruction": said, "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    plan = sheet.sm.unit(uid).answer["plans"][0] if sheet.sm.unit(uid).answer.get("plans") else None
    assert plan is None or plan["status"] != "accepted"
    assert p["status"] in ("awaiting_user", "partial", "failed") and p["verdict"] is None or p["verdict"]["state"] != "completed"
    assert sheet.sm.current()[f"{uid}.ClearSpan"] == 3000  # a conflict is not resolved by a guess
    assert any("cannot both hold" in json.dumps(e.get("result")) for e in p["events"] if e["kind"] == "tool" and e["name"] == "propose_plan")


def test_every_call_and_its_result_is_in_the_timeline_as_data_not_as_text_of_objects(tmp_path):
    from dxf_autoparam.ai.narrate import shrink

    script = [[reading(FULL_READING)], [call("inspect_sheet")], [call("zoom_view", sheet=True)], [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, _uid, _g, _gem = parametrized_sheet(tmp_path, script=script)
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}})
    p = wait(sheet, r["run"])
    tools = [e for e in p["events"] if e["kind"] == "tool"]
    assert [e["name"] for e in tools][:3] == ["account_instruction", "inspect_sheet", "zoom_view"]
    for e in tools:
        assert isinstance(e["result"], (dict, list, str, int, float, bool, type(None))) and e["id"] and e["ms"] >= 0
        json.dumps(e)  # the page receives it as JSON: nothing that only prints as <object …>
    starts = {e["id"] for e in p["events"] if e["kind"] == "tool_start"}
    assert starts == {e["id"] for e in tools}  # every call that began has its result
    nested = shrink({"a": {"b": {"c": [1, {"d": set(range(30))}, b"\x00" * 9000]}}, "long": "x" * 5000})
    assert nested["a"]["b"]["c"][2] == "<9000 bytes>" and len(nested["long"]) < 600 and "more" in json.dumps(nested["a"]["b"]["c"][1])
    assert "[object" not in json.dumps(nested) and "<" not in json.dumps(shrink({"x": [1, 2]}))


def test_the_dotted_original_is_the_imported_geometry_at_its_imported_coordinates(tmp_path):
    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=[[call("noop")]])
    sm = sheet.sm
    assert sheet.baseline()["prims"] == [] and sheet.baseline()["changed"] == 0  # nothing differs yet
    sm.apply({f"{uid}.ClearSpan": 2500})
    b = sheet.baseline()
    assert b["changed"] > 0
    now = {p["i"]: p for p in sheet._prims(sm.regenerate().changed, sm.regenerate())}
    for q in b["prims"]:
        if "p" in q and q["k"] == "p":
            it = sm.dr.items[q["i"]]
            xs = [c for pt in it.pts for c in pt]
            assert min(q["p"][0::2]) >= min(xs[0::2]) - 1e-6 and max(q["p"][0::2]) <= max(xs[0::2]) + 1e-6  # drawn from the file's own points
    assert any(abs(q["p"][0] - now[q["i"]]["p"][0]) > 1 for q in b["prims"] if q["i"] in now and "p" in q and "p" in now[q["i"]])  # and they are NOT where it is now
    sm.reset_value(f"{uid}.ClearSpan")
    assert sheet.baseline()["prims"] == []  # back where it was: nothing to show


def test_undo_and_redo_stay_right_around_edits_and_resets(tmp_path):
    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=[[call("noop")]])
    sm, key = sheet.sm, f"{uid}.ClearSpan"
    sm.apply({key: 2500})
    sm.apply({key: 2700})
    sm.reset_value(key)
    assert sm.current()[key] == 3000
    assert sm.undo() and sm.current()[key] == 2700 and sm.undo() and sm.current()[key] == 2500
    assert sm.redo() and sm.current()[key] == 2700 and sm.redo() and sm.current()[key] == 3000
    sm.reset_drawing()
    assert not sm.units[uid].answer and sm.undo() and sm.current()[key] == 3000 and sm.units[uid].answer  # the parametrization came back too
    assert sm.undo() and sm.current()[key] == 2700


def test_a_change_made_while_the_agent_worked_is_never_overwritten_silently(tmp_path):
    script = [[reading(FULL_READING)], *chatty(1), [call("inspect_assembly", parameter="ClearSpan")],
              [call("propose_plan", parameter="ClearSpan", requested_value=2500, anchor=ANCHOR, directives=DIRS)], [call("finish", summary="x")],
              [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, uid, _g, _gem = parametrized_sheet(tmp_path, script=script)
    other = next(n for n in sheet.sm.current() if n.startswith(uid) and not n.endswith("ClearSpan") and n.endswith("TopSlab"))
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"views": ["V01"]}, "options": {"budget": {"soft_turns": 3}}})
    assert wait(sheet, r["run"])["status"] == "paused"
    sheet.sm.apply({other: sheet.sm.current()[other] + 20})  # the person nudges a value while the run is paused
    sheet.continue_run({"run": r["run"]})
    p = wait(sheet, r["run"], until=lambda q: q["status"] not in ACTIVE and q["status"] != "paused" or q["status"] == "awaiting_user")
    for _ in range(3):
        if p["status"] != "paused":
            break
        sheet.continue_run({"run": r["run"]})
        p = wait(sheet, r["run"])
    assert p["status"] == "awaiting_user" and p["questions"][0]["about"] == "rebase" and "changed while the agent worked" in p["questions"][0]["text"]
    assert sheet.sm.current()[f"{uid}.ClearSpan"] == 3000 and sheet.sm.current()[other] == 320  # nothing was applied over their change
    sheet.continue_run({"run": r["run"], "answers": {p["questions"][0]["id"]: "apply on the current sheet"}})
    p = wait(sheet, r["run"])
    assert p["status"] == "completed", p["verdict"]["remaining"]
    assert sheet.sm.current()[f"{uid}.ClearSpan"] == 2500 and sheet.sm.current()[other] == 320  # both stand
