"""A task that is not "parametrize the drawing" is still a task, and a question to the person is a multiple-choice question.

The session used to treat every run over the whole drawing as an order to parametrize every unit: a question ("which views state the clear span?") ended
`partial` with "no named value was kept" for units nobody was asked to touch, and its first `finish` was refused until the agent had opened them all. The
model's only way to answer was a closing summary the page folded away. And `ask_person` took one string and a flat list of options. Scripted model, real
engine, no network."""

from __future__ import annotations

import pytest
from test_crossview import two_views
from test_run import Scripted, wait

from dxf_autoparam.ai import agent as A
from dxf_autoparam.ai.scripted import call
from dxf_autoparam.workspace import SheetSession


def clause(quote: str, kind: str, handled_by: str, why: str = "") -> dict:
    return {"quote": quote, "kind": kind, "meaning": "as read", "handled_by": handled_by, **({"why": why} if why else {})}


def start(tmp_path, instruction: str, script, **kw):
    sheet = SheetSession(str(two_views(tmp_path / "two.dxf")))  # two views, nothing parametrized
    gem = Scripted(script, **kw)
    sheet.gem_factory = lambda: gem
    r = sheet.start_run({"instruction": instruction, "scope": {"kind": "drawing"}})
    return sheet, r["run"], gem


def criteria(p) -> dict:
    return {c["id"]: c for c in p["verdict"]["criteria"]}


QUESTION = "Which views state the opening width?"
ANSWER = "The opening width is stated in the section and in the side elevation, 3000 mm in each."


def test_a_question_about_the_drawing_is_answered_without_parametrizing_a_single_unit(tmp_path):
    script = [[call("account_instruction", items=[clause(QUESTION, "question", "answer")])], [call("search_drawing", numbers=[3000])],
              [call("finish", summary=ANSWER)]]
    sheet, rid, _gem = start(tmp_path, QUESTION, script)
    p = wait(sheet, rid)
    v = p["verdict"]
    assert p["status"] == "completed", v["remaining"]
    assert "all_units_covered" not in criteria(p) and v["coverage"] == [] and not any("never parametrized" in n for n in v["notes"])
    assert v["finish_summary"] == ANSWER and not v["applied"], "answered, and nothing on the sheet changed"
    assert not [e for e in p["events"] if e["kind"] == "tool" and e["name"] == "finish" and not e["ok"]], "the first finish is not refused for units nobody was asked about"


def test_an_instruction_to_parametrize_still_owes_every_unit_whatever_else_it_asks(tmp_path):
    both = "Which views state the opening width? Make the whole drawing parametric."
    script = [[call("account_instruction", items=[clause("Which views state the opening width", "question", "answer"),
                                                  clause("Make the whole drawing parametric", "parametrize", "parts")])],
              [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, rid, _gem = start(tmp_path, both, script)
    p = wait(sheet, rid)
    assert p["status"] == "partial" and not criteria(p)["all_units_covered"]["ok"]
    assert "units parametrized" in next(e for e in p["events"] if e["kind"] == "tool" and e["name"] == "finish")["why"], "the first finish is told which units are owed"


def test_a_clause_mislabelled_is_not_a_way_out_of_the_work(tmp_path):
    script = [[call("account_instruction", items=[clause("Make the whole drawing parametric", "context", "none", why="background")])],
              [call("finish", summary="x")], [call("finish", summary="x")]]
    sheet, rid, _gem = start(tmp_path, "Make the whole drawing parametric.", script)
    p = wait(sheet, rid)
    assert p["status"] == "partial" and "all_units_covered" in criteria(p), "only a question or a check, and nothing that asks for the work, waives it"


def test_an_answer_clause_needs_an_answer_in_the_summary(tmp_path):
    script = [[call("account_instruction", items=[clause(QUESTION, "question", "answer")])], [call("finish", summary="")], [call("finish", summary="")]]
    sheet, rid, _gem = start(tmp_path, QUESTION, script)
    p = wait(sheet, rid)
    assert not criteria(p)["commitments_kept"]["ok"] and "finish's summary" in criteria(p)["commitments_kept"]["detail"] and p["status"] == "partial"


# ── multiple-choice questions ──────────────────────────────────────────────────────────────────────


def test_a_question_is_normalised_into_choices_a_recommendation_and_what_was_cut():
    asked, said = A.mcq({"questions": [
        {"question": "Which side stays?", "header": "Side", "recommended": "Left", "options": [{"label": "Left", "description": "the left face stays"}, "Right", "Left", {"label": ""}]},
        {"question": "Which of these apply?", "multi_select": True, "options": ["A", "B", "C", "D", "E", "F", "G"], "recommended": "not an option"},
        {"question": "A free one", "options": ["only one"]}, {"question": ""}, {"question": "fourth"}, {"question": "fifth"}]})
    assert [q["text"] for q in asked] == ["Which side stays?", "Which of these apply?", "A free one", "fourth"] and "first 4 questions" in said
    first, second, free, _ = asked
    assert first["options"] == ["Left", "Right"] and first["descriptions"] == {"Left": "the left face stays"} and first["header"] == "Side" and first["recommended"] == "Left"
    assert second["multi"] and second["options"] == ["A", "B", "C", "D", "E"] and second["recommended"] is None and "only 5 options" in said
    assert free["options"] == [] and not free["multi"], "one option is no choice: it is asked in words"
    old, _ = A.mcq({"question": "Which?", "options": ["x", "y"]})
    assert old[0]["options"] == ["x", "y"], "the one-question form still works"


def test_only_words_of_the_persons_own_become_text_a_quote_may_come_from():
    q = {"options": ["Left", "Right"], "multi": True}
    assert A.chosen(q, "Left") and A.chosen(q, "Left | Right") and not A.chosen(q, "Left | the middle one") and not A.chosen({"options": []}, "anything")
    assert not A.chosen({"options": ["Left", "Right"], "multi": False}, "Left | Right"), "several choices where one was asked are not a choice"


def test_the_page_gets_the_question_whole_and_the_answers_go_back_to_the_run(tmp_path):
    ask = call("ask_person", questions=[
        {"question": "Which view holds the shared value?", "header": "View", "recommended": "Section",
         "options": [{"label": "Section", "description": "the section A-A"}, {"label": "Side", "description": "the side elevation"}]},
        {"question": "Which sizes may change?", "header": "Sizes", "multi_select": True, "options": ["Opening", "Wall", "Slab"]}])
    script = [[call("account_instruction", items=[clause("Ask me which view holds the shared value", "question", "question")])], [ask],
              [call("finish", summary="Used the section.")]]
    sheet, rid, _gem = start(tmp_path, "Ask me which view holds the shared value.", script)
    p = wait(sheet, rid)
    assert p["status"] == "awaiting_user" and len(p["questions"]) == 2
    one, many = p["questions"]
    assert one["header"] == "View" and one["recommended"] == "Section" and one["descriptions"]["Side"] == "the side elevation" and not one.get("multi")
    assert many["multi"] and many["options"] == ["Opening", "Wall", "Slab"]
    sheet.continue_run({"run": rid, "answers": {one["id"]: "Side", many["id"]: "Opening | Slab"}})
    p = wait(sheet, rid)
    said = sheet.runs[rid].bench.said
    assert "answering" not in said, "choices among the options are not the person's words"
    assert any("Opening | Slab" in e.get("text", "") for e in p["events"] if e["kind"] == "note")
    assert p["status"] == "completed", p["verdict"]["remaining"]
    sheet2, rid2, _ = start(tmp_path / "again", "Ask me which view holds the shared value.", script) if (tmp_path / "again").mkdir() is None else (None, None, None)
    q = wait(sheet2, rid2)["questions"][0]
    sheet2.continue_run({"run": rid2, "answers": {q["id"]: "the one with the opening, whichever that is"}})
    wait(sheet2, rid2)
    assert "the one with the opening" in sheet2.runs[rid2].bench.said, "their own words are kept: a quote may come from them"


@pytest.mark.parametrize("bad", [None, [], "x"])
def test_a_call_with_no_usable_question_asks_nothing_and_does_not_stall(bad):
    asked, _ = A.mcq({"questions": bad, "question": ""})
    assert asked == []


# ── "if you are unsure, ask me": a question commitment is kept only by asking ────────────────────────────────────────────────────────────────

ASK = "Which views state the opening width? If you are unsure, ask me."


def test_a_clause_handled_by_a_question_is_not_kept_until_one_is_asked(tmp_path):
    """A real run read "if you are unsure, ask me", accounted for it as handled by a question, asked nothing, recorded an assumption, and was told every
    commitment was kept. The first finish now says no question was asked; the run cannot claim the commitment by finishing again."""
    script = [[call("account_instruction", items=[clause("Which views state the opening width?", "question", "answer"),
                                                  clause("If you are unsure, ask me.", "process", "question")])],
              [call("finish", summary=ANSWER)], [call("finish", summary=ANSWER)]]
    sheet, rid, _gem = start(tmp_path, ASK, script)
    p = wait(sheet, rid)
    first = next(e for e in p["events"] if e["kind"] == "tool" and e["name"] == "finish")
    assert not first["ok"] and "no question was asked" in first["why"], "the first finish says so"
    assert not criteria(p)["commitments_kept"]["ok"] and p["status"] != "completed"


def test_asking_keeps_the_question_commitment(tmp_path):
    script = [[call("account_instruction", items=[clause("Which views state the opening width?", "question", "answer"),
                                                  clause("If you are unsure, ask me.", "process", "question")])],
              [call("ask_person", questions=[{"question": "Is the opening width the clear span of the box?", "header": "Opening",
                                              "options": [{"label": "yes"}, {"label": "no"}]}])]]
    sheet, rid, _gem = start(tmp_path, ASK, script)
    p = wait(sheet, rid)
    assert p["status"] == "awaiting_user" and p["questions"], "the question reaches the person"
    b = sheet.runs[rid].bench
    assert all(c["ok"] for c in b.commitments() if c["handled_by"] == "question")


def test_saying_why_no_question_was_needed_keeps_it_too(tmp_path):
    script = [[call("account_instruction", items=[clause("Which views state the opening width?", "question", "answer"),
                                                  clause("If you are unsure, ask me.", "process", "question")])],
              [call("account_instruction", items=[clause("If you are unsure, ask me.", "process", "none", why="every value I name is dimensioned")])],
              [call("finish", summary=ANSWER)]]
    sheet, rid, _gem = start(tmp_path, ASK, script)
    p = wait(sheet, rid)
    assert criteria(p)["commitments_kept"]["ok"], criteria(p)["commitments_kept"]


def test_checking_what_was_edited_is_not_idle_looking(tmp_path):
    """A real run was refused `what_moves` twelve turns after its last edit, while it checked an anomaly: measuring and checking what the run has
    edited gets twice the look budget; plain looking keeps the old limit."""
    check = "Check this drawing. Change nothing."
    script = ([[call("account_instruction", items=[clause("Check this drawing.", "check", "answer"), clause("Change nothing.", "keep", "none", why="a check")])],
               [call("update_checklist", items=[{"id": "check", "text": "check the drawing", "status": "doing"}])]]
              + [[call("calculate", expression="2 * 1500")] for _ in range(13)]
              + [[call("search_drawing", words=["slab"])], [call("finish", summary="checked")]])
    sheet, rid, _gem = start(tmp_path, check, script)
    p = wait(sheet, rid)
    tools = [e for e in p["events"] if e["kind"] == "tool"]
    calcs = [e for e in tools if e["name"] == "calculate"]
    assert len(calcs) == 13 and all(e["ok"] for e in calcs), [e.get("why") for e in calcs if not e["ok"]]
    search = next(e for e in tools if e["name"] == "search_drawing")
    assert not search["ok"] and "edit first" in search["why"], "plain looking still has its limit"
