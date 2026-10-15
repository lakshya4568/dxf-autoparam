"""End-to-end demonstration of the production rule integration — the real agent runtime with a SCRIPTED model (no network, no cost).

On the generated two-view box (section + plan in projection, wing walls, foundation, an unrelated detail), one engineering instruction:

    "Reduce the clear span to 2500 mm. Keep the middle wall centred, preserve both wall thicknesses …"

The scripted model does what a careful model would: reads the instruction, builds the parts and values, asks which production family the
drawing's words point at, reads that family's knowledge, binds the production model to the drawing's own values (the engine keeps what holds as
guards), assesses the change in the production model (the span: a value this drawing drives; a third cell: a topology change it cannot make),
proposes the plan, checks every view, and finishes. The engine applies the change only if every promise and every production guard holds; the
regenerated sheet is exported.

Then the same plan on the same drawing with the plan view as a unit of its own (it does not follow the section): the production guard refuses it
and the sheet is exactly as before.

    uv run python tools/production_demo.py [--out out/production_demo]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

from dxf_autoparam.ai import acceptance as acc
from dxf_autoparam.ai.scripted import ScriptedModel, call
from dxf_autoparam.crossview import SheetError
from dxf_autoparam.plan_bench import Box, answer_as_calls, box_answer
from dxf_autoparam.production.bench import PLAN_DECISIONS, PLAN_INSTRUCTION, _sheet, truth_binding
from dxf_autoparam.production.bridge import default_bridge


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/production_demo")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    st = default_bridge().status()
    if not st["available"]:
        print(f"the production rule bridge cannot run here: {st['reason']}", file=sys.stderr)
        return 2
    report: dict = {"bridge": {"build": st.get("build")}}

    # ── 1. the agent session ────────────────────────────────────────────────────
    (out / "case").mkdir(exist_ok=True)
    case = acc.make_case(out / "case")
    sm, uid = case.sheet.sm, case.uid
    b = case.g["box"]
    built = [call(n, **x) for n, x in answer_as_calls(box_answer(sm, uid, b, case.g["handles"]))]
    tb = truth_binding(sm, uid, b)
    reading = [{"quote": q, "kind": min(k), "meaning": q, "handled_by": min(h)} for q, k, h in acc.CLAUSES]
    dirs = [{"target": "Foundation", "mode": "keep_fixed", "clause": "do not modify the existing foundation"},
            {"target": "WingLeft", "mode": "follow", "clause": "update the corresponding half-section and half-elevation geometry"},
            {"target": "WingRight", "mode": "follow", "clause": "update the corresponding half-section and half-elevation geometry"},
            {"target": "PitchingDetail", "mode": "exclude", "clause": "Keep the unrelated pitching detail unchanged"},
            {"target": "OuterWall", "mode": "keep_value", "clause": "preserve both wall thicknesses and the slab thicknesses"},
            {"target": "TopSlab", "mode": "keep_value", "clause": "preserve both wall thicknesses and the slab thicknesses"},
            {"target": "BottomSlab", "mode": "keep_value", "clause": "preserve both wall thicknesses and the slab thicknesses"}]
    gem = ScriptedModel([
        [call("account_instruction", items=reading)],
        [call("inspect_sheet"), call("production_families")],
        [call("production_knowledge", family="railway_rcc_box", sections=["summary", "outputs", "views"], query="total")],
        [*built],
        [call("bind_production_model", family="railway_rcc_box", unit=uid, inputs=tb["inputs"], config=tb["config"], outputs=tb["outputs"],
              evidence=["the section shows two cells, outer walls, slabs; the plan shares its wall faces"])],
        [call("assess_change", family="railway_rcc_box", changes={"geometry.clear_w": 2.5}),
         call("assess_change", family="railway_rcc_box", changes={"project.cells": 3})],
        [call("inspect_assembly", parameter="ClearSpan")],
        [call("propose_plan", parameter="ClearSpan", requested_value=2500.0, anchor={"policy": "centered", "clause": "Keep the middle wall centred"},
              directives=dirs)],
        [call("validate_views")],
        *[[call("finish", summary="clear span 2500 mm planned and applied; production relations guarded and holding in both views")]] * 4,
    ])
    case.sheet.gem = gem
    t0 = time.time()
    rid = case.sheet.start_run({"instruction": case.instruction, "scope": {"views": ["V01"]}, "options": {"domain": "bridge"}})["run"]
    for _ in range(8):
        run = case.sheet.runs[rid]
        while run.status in ("queued", "running", "stopping"):
            time.sleep(0.05)
        if run.status != "awaiting_user":
            break
        answers = acc.author_answers(case, run.questions)
        print(f"  the person is asked {len(run.questions)} question(s): " + "; ".join(f"{k.split(':')[-1]}={v}" for k, v in answers.items()))
        case.sheet.continue_run({"run": rid, "answers": answers})
    p = case.sheet.run_progress(rid, 0)
    seen = {fr.name: fr.response for turn in gem.seen for fr in turn}
    v = p["verdict"]
    fams = seen["production_families"]["result"]["match_this_drawing"]
    assess = [fr.response["result"] for turn in gem.seen for fr in turn if fr.name == "assess_change"]
    views = seen["validate_views"]["result"]["views"]
    print(f"run: {p['status']} in {time.time() - t0:.1f}s — {v['headline']}")
    print(f"  families the printed words point at: {[(f['family'], f['score'], f.get('close_call', False)) for f in fams[:2]]}")
    bind = next(fr.response["result"]["result"] for turn in gem.seen for fr in turn if fr.name == "bind_production_model")
    print(f"  binding kept: {bind.get('kept')} — {bind.get('summary')}; guards {bind.get('guards')}")
    for x in assess:
        f = x["fields"][0]
        print(f"  assess {f['field']} → {f.get('status')}" + (f" (drives {f['drives']} → {f['requested_value']:g} mm)" if f.get("drives") else f": {f.get('why', '')[:110]}"))
        if x.get("outputs", {}).get("total_w"):
            print(f"      production total_w {x['outputs']['total_w']['before']:g} → {x['outputs']['total_w']['after']:g} mm")
    for row in views:
        print(f"  view {row['view']} ({row.get('name')}): geometry {row['geometry']['status']}, production relations "
              f"{row['production_rules']['relations']}, engine validation {row['production_rules']['engine_validation']}, "
              f"cross-view {row['cross_view']['status']}, unresolved {row['unresolved']['count']}")
    final = sm.domain_report()
    for r in final:
        print(f"  after the change: {r['binding']} {r['status']} — " + ", ".join(f"{n} expected {o.get('expected')} measured {o.get('measured')}"
                                                                         for n, o in r["outputs"].items()))
    exported = out / "box_clear_span_2500.dxf"
    ex = sm.export(str(exported))
    print(f"  exported {exported} ({ex.get('updated', ex)} )" if isinstance(ex, dict) else f"  exported {exported}")
    report["run"] = {"status": p["status"], "headline": v["headline"], "criteria": v["criteria"], "production": v.get("production"),
                     "views": views, "assess": assess, "after": final}

    # ── 2. the same plan when the plan view does not follow ──────────────────────
    sm2, us, up, _g = _sheet(Box(), out, "unlinked", unlink=True)
    acc2 = sm2.bind_domain(truth_binding(sm2, us, Box(), plan_unit=up))
    before = copy.deepcopy(sm2._state())
    rev = sm2.revision
    try:
        sm2.apply_plan(us, {"instruction": PLAN_INSTRUCTION.format(v="2500"), "decisions": PLAN_DECISIONS})
        outcome = {"refused": False}
    except SheetError as exc:
        after = sm2._state()
        outcome = {"refused": True, "why": str(exc), "state_untouched": after["values"] == before["values"] and after["answers"] == before["answers"]
                   and sm2.revision == rev}
    print(f"unlinked plan view: guards {acc2['guards']}; the same plan → {'REFUSED' if outcome['refused'] else 'applied'}"
          + (f", sheet untouched: {outcome['state_untouched']}\n  {outcome['why'][:260]}" if outcome["refused"] else ""))
    report["unlinked"] = outcome
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str))
    print(f"wrote {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
