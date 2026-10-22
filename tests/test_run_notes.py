"""The person can speak to an agent that is working — no Stop, no call in flight thrown away.

The composer was disabled while a run was active and the only way to steer was Stop, which abandons the call being made (paid for) and the turn it would
have made. A note is handed to the model at the start of its next turn, as the person's own words."""

from __future__ import annotations

import pytest
from test_crossview import two_views
from test_run import Scripted, wait

from dxf_autoparam.ai.run import RunError
from dxf_autoparam.ai.scripted import call
from dxf_autoparam.workspace import SheetSession

QUESTION = "Which views state the opening width?"


def text_of(content) -> str:
    return "".join(getattr(p, "text", "") or "" for p in content.parts or [])


def test_a_note_made_while_the_agent_works_reaches_its_next_turn(tmp_path):
    sheet = SheetSession(str(two_views(tmp_path / "two.dxf")))
    gem = Scripted([[call("account_instruction", items=[{"quote": QUESTION, "kind": "question", "meaning": "as read", "handled_by": "answer"}])],
                    [call("search_drawing", numbers=[3000])], [call("finish", summary="3000 mm in two views.")]], delay=0.3)
    sheet.gem_factory = lambda: gem
    rid = sheet.start_run({"instruction": QUESTION, "scope": {"kind": "drawing"}})["run"]
    wait(sheet, rid, until=lambda p: p["status"] == "running" and any(e["kind"] == "turn" for e in p["events"]))
    assert sheet.note_run({"run": rid, "note": "Look at the section first."})["ok"]
    p = wait(sheet, rid)
    assert p["status"] == "completed"
    heard = [e for e in p["events"] if e["kind"] == "user" and e.get("while_working")]
    assert [e["text"] for e in heard] == ["Look at the section first."], "the page shows it where it was said"
    seen = [text_of(c) for req in gem.requests for c in req["history"] if c.role == "user"]
    assert any("THE PERSON SAYS, while you work" in t and "Look at the section first." in t for t in seen), "the model was handed it"
    assert not any("THE PERSON SAYS" in text_of(c) for c in gem.requests[0]["history"]), "not before it was said"
    assert "Look at the section first." in sheet.runs[rid].bench.said, "their words from then on: a quote may come from them"


def test_a_note_is_for_a_run_that_is_working(tmp_path):
    sheet = SheetSession(str(two_views(tmp_path / "two.dxf")))
    gem = Scripted([[call("account_instruction", items=[{"quote": QUESTION, "kind": "question", "meaning": "as read", "handled_by": "answer"}])],
                    [call("finish", summary="done")]])
    sheet.gem_factory = lambda: gem
    rid = sheet.start_run({"instruction": QUESTION, "scope": {"kind": "drawing"}})["run"]
    wait(sheet, rid)
    with pytest.raises(RunError, match="takes no note while it works"):
        sheet.note_run({"run": rid, "note": "too late"})
    with pytest.raises(RunError, match="write the note first"):
        sheet.note_run({"run": rid, "note": "  "})
    with pytest.raises(RunError, match="no such run"):
        sheet.note_run({"run": "R99", "note": "x"})


def test_the_page_speaks_to_a_working_run_over_http_and_is_told_when_it_cannot(tmp_path):
    from test_workspace_api import _start_server, j
    from test_workspace_api import call as http

    sheet = SheetSession(str(two_views(tmp_path / "two.dxf")))
    gem = Scripted([[call("account_instruction", items=[{"quote": QUESTION, "kind": "question", "meaning": "as read", "handled_by": "answer"}])],
                    [call("finish", summary="done")]], delay=0.4)
    sheet.gem_factory = lambda: gem
    base, httpd = _start_server(sheet)
    try:
        rid = j(http(base, "/api/sheet/ai/run", {"instruction": QUESTION, "scope": {"kind": "drawing"}}))["run"]
        wait(sheet, rid, until=lambda p: p["status"] == "running")
        assert j(http(base, "/api/sheet/ai/note", {"run": rid, "note": "Take your time."}))["ok"]
        wait(sheet, rid)
        status, body, _ = http(base, "/api/sheet/ai/note", {"run": rid, "note": "too late"})
        assert status == 409 and "takes no note while it works" in j((status, body, None))["error"]
    finally:
        httpd.shutdown()
