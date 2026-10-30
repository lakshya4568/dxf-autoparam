"""Serve the workspace with the model replaced by a SCRIPT — to look at the agent's page (and to drive it from a browser test) without any
AI call or cost.

    uv run python tools/serve_scripted.py --port 8799

The sheet is a generated two-view RCC box (known sizes, so the result of the change can be checked exactly). Each run plays what a model
could do with the instruction below: read it, look at the sheet and zoom, name the parts and values from the drawing (one wrong claim the
engine refuses, then repaired), inspect the assembly, propose the plan — leaving the one thing the instruction does not say (which side
stays) to the person — and finish. The SECOND run of a server is another task: a question, which the model answers by asking two multiple-choice
questions (one with a recommendation, one where several choices may apply) before it finishes — to look at that card. Every thought is marked
[scripted]: nothing shown here is a model's own.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from dxf_autoparam.ai.scripted import ScriptedModel, call
from dxf_autoparam.cadjson import entity_id
from dxf_autoparam.plan_bench import Box, answer_as_calls, box_answer, box_gad
from dxf_autoparam.server import Session, make_handler
from dxf_autoparam.workspace import SheetSession

INSTRUCTION = ("Reduce the clear span to 2500 mm. Keep the middle wall centered, preserve the wall and slab thicknesses, keep the existing foundation fixed. "
               "The wing walls follow the box. Keep the unrelated pitching detail unchanged. Show me anything ambiguous before applying the change.")
ASK_INSTRUCTION = "Ask me which view holds the shared value."
READING = [("Reduce the clear span to 2500 mm", "change_value", "ClearSpan becomes 2500", "plan"),
           ("Keep the middle wall centered", "keep", "the middle wall stays on the centre line", "plan"),
           ("preserve the wall and slab thicknesses", "keep", "wall and slab thicknesses keep their values", "plan"),
           ("keep the existing foundation fixed", "keep", "the foundation does not move", "plan"),
           ("The wing walls follow the box", "keep", "the wing walls move with the box", "plan"),
           ("Keep the unrelated pitching detail unchanged", "keep", "the detail is outside the edit", "plan"),
           ("Show me anything ambiguous before applying the change", "process", "ask before deciding", "question")]
DIRS = [{"target": "Foundation", "mode": "keep_fixed", "clause": "keep the existing foundation fixed"},
        {"target": "WingLeft", "mode": "follow", "clause": "The wing walls follow the box"},
        {"target": "WingRight", "mode": "follow", "clause": "The wing walls follow the box"},
        {"target": "PitchingDetail", "mode": "exclude", "clause": "Keep the unrelated pitching detail unchanged"},
        {"target": "OuterWall", "mode": "keep_value", "clause": "preserve the wall and slab thicknesses"},
        {"target": "TopSlab", "mode": "keep_value", "clause": "preserve the wall and slab thicknesses"},
        {"target": "BottomSlab", "mode": "keep_value", "clause": "preserve the wall and slab thicknesses"}]


class DemoModel(ScriptedModel):
    """The scripted model, plus — only when the run has the engineering library on (its protocol is in the system prompt) — one turn that
    uses it the way a model might: look at which skills match, read the matching skill's recognition and failure sections, search a
    definition, and say what it applied. Everything is the engine's real answer; the choices are scripted."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._library_turn_added = False

    def step(self, system, tools, prefix_parts, prefix_key, history, label, thinking, **kw):
        if "ENGINEERING LIBRARY" in system and not self._library_turn_added and self.script:
            self._library_turn_added = True
            self.script.insert(1, [call("list_skills", why="which skills match this drawing's own printed words"),
                                   call("load_skill", why="read how a drawing of this kind is recognised, and when not to use the skill",
                                        id="family:rcc_box", sections=["recognition", "failure"]),
                                   call("search_library", why="the documented definition of the clear height", queries=["clear height soffit level"], topics=["formula"]),
                                   call("record_finding", why="say what was used", findings=[
                                       {"kind": "applied", "text": "the box skill's cues were confirmed on the sheet: it prints RCC BOX and the views are section and plan",
                                        "evidence": ["skill:family:rcc_box", "kb:kb.formula.d_clear_height"]}])])
        return super().step(system, tools, prefix_parts, prefix_key, history, label, thinking, **kw)


def make_script(sheet: SheetSession, uid: str, g: dict, delay: float = 0.0):
    sm = sheet.sm
    ans = box_answer(sm, uid, g["box"], g["handles"])
    build = [call(n, why="name the parts and the sizes the drawing shows" if n == "define_parts" else "bind each size to the lines it spans", **a) for n, a in answer_as_calls(ans)]
    u = sm.unit(uid)
    ents = [entity_id(it) for it in u.sub.items if it.dxftype == "LWPOLYLINE"][:2]
    an = u.an
    xl = next(d.id for d in an.datums.values() if d.axis == "x" and not d.virtual)
    yl = next(d.id for d in an.datums.values() if d.axis == "y" and not d.virtual)
    thoughts = [f"[scripted] {t}" for t in (
        "Read the instruction clause by clause; each quote is checked against the person's text.",
        "Look at the sheet before touching anything.", "Zoom into the section to tag its entities with the ids the tools use.",
        "Name the parts from the regions, bind the clear span on both cells, and try one wrong claim the engine must refuse.",
        "Repair: remove the wrong value and measure what the clear span moves.", "Inspect the assembly the clear span belongs to.",
        "Propose the plan with the person's own words as clauses; the anchor was not said.", "Finish: the engine asks the person first.",
        "State how the two views relate, then finish.")]
    return DemoModel([
        [call("account_instruction", why="read the instruction first", items=[{"quote": q, "kind": k, "meaning": m, "handled_by": h} for q, k, m, h in READING])],
        [call("inspect_sheet", why="see the views and what is parametrized")],
        [call("zoom_view", why="the whole sheet, to see how the views relate", sheet=True), call("zoom_view", why="a closer look at two outlines of the section", around=ents, labels="entities")],
        [*build, call("define_parameters", why="a claim across two axes: the engine should refuse it",
                      items=[{"name": "Wrong", "part": "Box", "from_line": xl, "to_line": yl}])],
        [call("remove", why="take back the wrong claim", parameters=["Wrong"]), call("what_moves", why="what does the clear span move?", parameter="ClearSpan")],
        [call("inspect_assembly", why="which parts the clear span belongs to and what each anchor would do", parameter="ClearSpan")],
        [call("propose_plan", why="the plan, with the person's words behind each directive", parameter="ClearSpan", requested_value=2500, directives=DIRS)],
        [call("finish", summary="the plan waits for the person's choice of anchor")],
        [call("state_plan", why="say how the two views of the box relate", summary="The half section and the half elevation show one box: they are drawn in projection, so a size changed in one is changed in the other.",
              links=[{"what": "box walls", "kind": "component", "relation": "same_component", "appears_in": [{"view": "V01", "part": "LeftWall"}, {"view": "V02", "part": "LeftWall"}],
                      "bound_by": "projection", "evidence": ["the two views share their vertical set-out lines"]}],
              assumptions=[{"text": "the pitching detail is outside the edit", "why": "the person said to leave it unchanged"}]),
         call("finish", summary="applied with the person's answers; the plan across the views is stated")]], thoughts=thoughts, delay=delay)


def make_questions_script(delay: float = 0.0) -> DemoModel:
    """A question-only task: the model reads it, asks two multiple-choice questions, and answers with what the person chose."""
    return DemoModel([
        [call("account_instruction", why="read the instruction first",
              items=[{"quote": ASK_INSTRUCTION.rstrip("."), "kind": "question", "meaning": "the person wants to choose where the shared value lives", "handled_by": "question"}])],
        [call("ask_person", why="two things only you can decide", questions=[
            {"question": "Which view should hold the shared value?", "header": "View", "recommended": "Section",
             "options": [{"label": "Section", "description": "the half section, where the clear span is dimensioned"}, {"label": "Plan", "description": "the plan, where the barrel length is"}]},
            {"question": "Which sizes may I name?", "header": "Sizes", "multi_select": True,
             "options": [{"label": "Clear span"}, {"label": "Wall thickness"}, {"label": "Slab thickness"}]}])],
        [call("finish", summary="I used your choices: the shared value lives where you said, and only the sizes you ticked are named.")]],
        thoughts=[f"[scripted] {t}" for t in ("Read the instruction: it asks for a choice only the person can make.", "Ask both questions at once, with the options the drawing offers.",
                                              "Finish with what was chosen.")], delay=delay)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--delay", type=float, default=0.0, help="seconds each scripted model turn takes (to try Stop)")
    a = ap.parse_args()
    # the scripted run is written for ONE unit made of the box's section and its plan (its plan has the wings follow the box): the demo and the
    # agent e2e measure the page, on a sheet of joined units — local systems are measured by tests/test_local_systems.py
    os.environ.setdefault("AUTOPARAM_SYSTEMS", "joined")
    tmp = Path(tempfile.mkdtemp(prefix="scripted-"))
    g = box_gad(tmp / "box.dxf", Box())
    sheet = SheetSession(g["path"])
    uid = next(k for k, u in sheet.sm.units.items() if len(u.views) == 2)
    sheet.gem_per_run = True
    runs = {"n": 0}

    def factory() -> DemoModel:
        runs["n"] += 1
        return make_questions_script(a.delay) if runs["n"] == 2 else make_script(sheet, uid, g, a.delay)

    sheet.gem_factory = factory
    httpd = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(Session(None), sheet))
    print(f"scripted demo on http://127.0.0.1:{httpd.server_address[1]}/  (the instruction to type:)\n{INSTRUCTION}\n", flush=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
