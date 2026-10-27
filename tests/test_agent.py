"""The parametrization agent's loop and tools, with Gemini replaced by a script — no network, no cost.
What matters: each edit is checked at once and its verdict goes back to the model; the result is a valid program."""

from __future__ import annotations

import json
from pathlib import Path

from google.genai import types

from dxf_autoparam.ai import domain
from dxf_autoparam.ai.agent import Workbench, agent_parametrize, overview
from dxf_autoparam.ai.parametrize import prepare
from dxf_autoparam.topology import of

ROOT = Path(__file__).resolve().parents[1]
BOX = str(ROOT / "examples" / "two_cell_box_section.dxf")
XX = str(ROOT / "examples" / "sectional_elevation_xx.dxf")


def ids():
    an, *_ = prepare(BOX)
    regions = of(an).regions
    concrete = max(regions, key=lambda r: len(r.holes))
    cells = sorted((r for r in regions if r.parent == concrete.id), key=lambda r: r.bbox[0])
    pcc = next(r for r in regions if r is not concrete and r not in cells)
    span = next(c.id for c in an.clusters.values() if c.kind.value == "void" and round(c.value * an.drawing.units_mm) == 3000 and "x" in c.axes)
    x_line = next(d.id for d in an.datums.values() if d.axis == "x" and not d.virtual)
    y_line = next(d.id for d in an.datums.values() if d.axis == "y" and not d.virtual)
    return concrete.id, cells[0].id, cells[1].id, pcc.id, span, x_line, y_line


def call(tool, **args):
    return types.Part(function_call=types.FunctionCall(name=tool, args=args))


class ScriptedGemini:
    """Plays the model: each step returns the next scripted calls; records what the engine answered."""

    def __init__(self, script):
        self.script = list(script)
        self.cfg = type("C", (), {"model": "scripted", "thinking": "high"})()
        self.seen: list[list[dict]] = []
        self.thinking: list[str] = []

    def step(self, system, tools, prefix_parts, prefix_key, history, label, thinking, max_out=16384, stop=None, on_event=None):
        self.thinking.append(thinking)
        last = history[-1]
        if last.role == "user" and last.parts and getattr(last.parts[0], "function_response", None):
            self.seen.append([p.function_response.response["result"] for p in last.parts])
        parts = [types.Part(text=f"**{label}** planning", thought=True)] + self.script.pop(0)
        if on_event:
            on_event({"kind": "thought", "text": f"{label} planning"})
        return types.Content(role="model", parts=parts), {"label": label, "input_tokens": 10, "output_tokens": 5, "thinking_tokens": 5, "cached": False}

    def close(self):
        return []


def test_the_agent_edits_step_by_step_and_each_edit_is_checked_at_once():
    concrete, cell_l, cell_r, pcc, span, x_line, y_line = ids()
    script = [
        [call("inspect_regions", ids=[cell_l]), call("find_values", value_mm=3000)],
        [call("set_structure", structure_type="RCC box culvert, 2 cells", family="rcc_box", views=["section"], summary=""),
         call("define_parts", items=[{"name": "Box", "type": "box", "level": "assembly", "regions": [concrete]},
                                     {"name": "CellLeft", "type": "cell", "level": "subcomponent", "parent": "Box", "regions": [cell_l]},
                                     {"name": "CellRight", "type": "cell", "level": "subcomponent", "parent": "Box", "regions": [cell_r]},
                                     {"name": "PccCourse", "type": "courses", "regions": [pcc]}]),
         call("define_parameters", items=[{"name": "ClearSpan", "part": "Box", "candidate": span, "occurrences": ["all"]},  # both cells: one input
                                          {"name": "Wrong", "part": "Box", "from_line": x_line, "to_line": y_line}])],  # mixed axes: rejected
        [call("remove", parameters=["Wrong"]), call("what_moves", parameter="ClearSpan"),
         call("state_behaviours", items=[{"parameter": "ClearSpan", "target": "Box", "behaviour": "grows", "axis": "x"}])],
        [call("finish", summary="done")],  # held once: the drawing's other dimensions are still driven by nothing named
        [call("finish", summary="done")],
    ]
    gem = ScriptedGemini(script)
    events = []
    prog, rep, info = agent_parametrize(BOX, gem=gem, on_event=events.append, log=lambda *a: None)
    region_info, values = gem.seen[0]
    assert region_info[cell_l]["edges"]["left"]["line"] and any(v["candidate"] == span for v in values)
    structure, parts, params = gem.seen[1]
    assert structure["ok"] and all(v["ok"] for v in parts) and [v["item"] for v in parts] == ["Box", "CellLeft", "CellRight", "PccCourse"]
    clear, wrong = params["result"]
    assert clear["ok"] and clear["engine"].endswith("3000.0 mm") and "Box" in clear["moves"]  # the engine filled the value
    assert wrong["ok"] is False and "V1" in wrong["rejected"][0]  # the wrong one, with its reason
    assert params["status"]["open_problems"] == 1
    moves = gem.seen[2][1]
    assert moves["drawing_valid"] and "grows x" in moves["moves"]["Box"]
    assert gem.seen[2][2]["result"][0]["ok"]  # the behaviour holds
    assert any(e["kind"] == "tool" and e["name"] == "finish" and e["ok"] for e in events)
    assert rep.errors() == [] and prog.params["ClearSpan"].value == 3000
    held = gem.seen[3][0]
    assert held["done"] is False and "coverage" in held["hint"] and "driven by a named value" in held["dimensions"], held
    assert info["agent"] and info["steps"] == 5
    assert {"tool", "status", "thought"} <= {e["kind"] for e in events}


def test_every_step_thinks_at_the_configured_level(monkeypatch):
    monkeypatch.delenv("VERTEX_AGENT_STEP_THINKING", raising=False)
    gem = ScriptedGemini([[call("inspect_regions", ids=[ids()[1]])], [call("find_values", value_mm=3000)], [call("finish", summary="done")]])
    agent_parametrize(BOX, gem=gem, log=lambda *a: None)
    assert gem.thinking == ["high"] * len(gem.thinking) and len(gem.thinking) >= 3
    monkeypatch.setenv("VERTEX_AGENT_STEP_THINKING", "low")  # only a person lowers it, and only the edit steps
    gem = ScriptedGemini([[call("inspect_regions", ids=[ids()[1]])], [call("finish", summary="done")]])
    agent_parametrize(BOX, gem=gem, log=lambda *a: None)
    assert gem.thinking[0] == "high" and gem.thinking[1:] == ["low"] * (len(gem.thinking) - 1)


def test_finish_with_open_problems_is_refused_once_then_ends():
    concrete, *_rest, x_line, y_line = ids()
    script = [
        [call("define_parts", items=[{"name": "Box", "type": "box", "regions": [concrete]}]),
         call("define_parameters", items=[{"name": "Wrong", "part": "Box", "from_line": x_line, "to_line": y_line}])],
        [call("finish", summary="done")],
        [call("finish", summary="stop anyway")],
    ]
    gem = ScriptedGemini(script)
    _prog, rep, info = agent_parametrize(BOX, gem=gem, log=lambda *a: None)
    assert gem.seen[1][0]["done"] is False and "fix these" in gem.seen[1][0]["hint"]
    assert info["steps"] == 3 and len(rep.errors()) == 1


def test_the_overview_is_small_and_the_tools_answer_on_a_real_view():
    an, base, *_ = prepare(XX)
    ov = json.dumps(overview(an, base), separators=(",", ":"))
    assert len(ov) / 4 < 16000  # about a third of the CAD JSON sent to the one-shot
    bench = Workbench(XX)
    lines = bench.inspect_lines(["y10", "x91"])
    assert lines["y10"]["chain"] and "at_mm" in lines["x91"]
    assert "no domain pack" in bench.knowledge("clear span")[0]  # by default the model names things itself
    assert Workbench(XX, pack=domain.active("bridge")).knowledge("clear span")[0].lower().startswith("clear")  # a pack a person switched on answers
    assert bench.what_moves("NoSuch")["error"].startswith("no parameter")


def test_a_revision_starts_from_the_current_answer():
    answer = json.loads((ROOT / "tests" / "fixtures" / "sectional_elevation_xx.answer.json").read_text())
    gem = ScriptedGemini([[call("remove", parameters=["DropWallThickness"])], [call("finish", summary="removed")],
                          [call("finish", summary="the constraint that used it is the person's call")]])
    prog, _rep, info = agent_parametrize(XX, start=answer, request="drop wall thickness stays as drawn", gem=gem, log=lambda *a: None)
    assert gem.seen[1][0]["done"] is False and any("DropWallThickness" in p for p in gem.seen[1][0]["first_problems"])  # told what it broke
    assert "DropWallThickness" not in prog.params and "ProposedBarrelLength" in prog.params
    assert len(info["answer"]["components"]) == len(answer["components"])


def test_reading_for_ever_is_nudged_towards_editing():
    concrete, *_ = ids()
    gem = ScriptedGemini([[call("inspect_regions", ids=[concrete])]] * 4 + [[call("finish", summary="x")], [call("finish", summary="x")]])
    agent_parametrize(BOX, gem=gem, log=lambda *a: None)
    assert "nudge" not in json.dumps(gem.seen[2]) and "define the parts now" in gem.seen[3][0]["nudge"]


def test_after_six_turns_of_only_looking_looking_is_refused_until_an_edit():
    concrete, *_ = ids()
    look = [call("inspect_regions", ids=[concrete])]
    gem = ScriptedGemini([look] * 7 + [[call("define_parts", items=[{"name": "Box", "type": "box", "regions": [concrete]}])], look,
                                       [call("finish", summary="x")], [call("finish", summary="x")]])
    agent_parametrize(BOX, gem=gem, log=lambda *a: None)
    assert "refused" in json.dumps(gem.seen[6]) and "refused" not in json.dumps(gem.seen[8])  # open again after the edit


def test_a_part_held_against_the_structure_is_said_with_what_it_meets():
    # a live run (7A, 2026-10-26) held the fill beside the proposed box (parametrize=false, "a draftsman leaves it"): the box's clear span could then
    # not grow from its centre, and the agent never knew why. The verdict says what a held part meets and what holding it costs.
    concrete, _l, _r, pcc, _span, _x, _y = ids()
    script = [[call("define_parts", items=[{"name": "Box", "type": "box", "level": "assembly", "regions": [concrete]},
                                           {"name": "PccCourse", "type": "courses", "regions": [pcc], "parametrize": False}])],
              [call("finish", summary="done")], [call("finish", summary="done")]]
    gem = ScriptedGemini(script)
    agent_parametrize(BOX, gem=gem, on_event=lambda e: None, log=lambda *a: None)
    box, course = gem.seen[0][0]["result"]
    assert "held_against" not in box
    assert "PccCourse is kept where it is drawn" in course["held_against"] and "Box" in course["held_against"], course


def test_a_dimension_kept_as_drawn_that_is_another_occurrence_of_a_named_size_is_said():
    # a live run (7A, 2026-10-26) kept a box's left wall "as it equals the right wall" and named only the right one: the left wall was then never
    # parametrized. The verdict says the dimension is one more occurrence of the named size, with the call that binds it.
    an, *_ = prepare(BOX)
    c = next(c for c in an.clusters.values() if len([g for g in c.gaps if an.gaps[g].dims and an.gaps[g].axis in ("x", "y")]) >= 2)
    g1, g2 = [g for g in c.gaps if an.gaps[g].dims and an.gaps[g].axis in ("x", "y")][:2]
    from dxf_autoparam.cadjson import entity_id

    dim2 = entity_id(an.drawing.items[an.gaps[g2].dims[0]])
    concrete, *_ = ids()
    script = [[call("define_parts", items=[{"name": "Box", "type": "box", "level": "assembly", "regions": [concrete]}]),
               call("define_parameters", items=[{"name": "WallThickness", "part": "Box", "candidate": c.id, "occurrences": [g1]}]),
               call("keep_dimensions", items=[{"dimension": dim2, "why": "it equals the other one"}])],
              [call("finish", summary="done")], [call("finish", summary="done")]]
    gem = ScriptedGemini(script)
    agent_parametrize(BOX, gem=gem, on_event=lambda e: None, log=lambda *a: None)
    kept = gem.seen[0][2]["result"][0]
    assert kept["ok"] and "an occurrence of" in kept["same_size_named"] and g2 in kept["same_size_named"] and "WallThickness" in kept["same_size_named"], kept
