"""Measuring the AI and the engine SEPARATELY, on a drawing whose intended result is known exactly.

A parametrization can go wrong in two different places: the model may read the instruction or the drawing wrongly (the wrong part, a
merged size, a guessed anchor), or the engine may fail to carry out what was rightly understood. One number cannot tell them apart, so
this scores a finished run in categories, each against ground truth from the generator that drew the sheet:

  instruction interpretation   every clause of the instruction is read as what it asks (its words quoted, the right kind, the right handler)
  component identification     each part the instruction speaks of is found among the regions the model grouped
  parameter identification     each size it names is a size the drawing has, on its own occurrences
  binding selection            no value takes in occurrences of another size merely because the numbers are equal
  anchor choice                the side that stays is the person's — stated, or asked — never the model's guess
  dependency planning          each part gets the behaviour the instruction states for it
  invariant selection          what must be preserved is preserved (thicknesses, the centre line, the level)
  cross-view correspondence    every view the change reaches changed
  geometry execution           the regenerated sheet equals what the generator draws at the new size (the outcome: the model's reading AND the engine's work)
  engine integrity             whatever was applied passed its own measured promises, and a refused change left the sheet as imported (the ENGINE, whoever erred)
  validation and recovery      refusals were repaired and the run ended complete
  clarification                what the instruction left open was asked; nothing was fabricated (a quote not in the text counts against it)

`evaluate` runs a model (scripted, or the real one) on the case, answers its questions as the instruction's author would, and scores the
run. With a scripted model it proves the scorer tells a careful agent from a careless one; with the real model it is the live acceptance
test, which is only started with an explicit flag (see `cli agent-eval`) because it is billed.
"""

from __future__ import annotations

import math
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..plan_bench import Box, _expected_points, answer_as_calls, box_answer, box_gad
from ..workspace import SheetSession
from .loop import Budget
from .scripted import ScriptedModel, call

INSTRUCTION = ("Reduce the clear span to 2500 mm. Keep the middle wall centred, preserve both wall thicknesses and the slab thicknesses, hold the bed level fixed, "
               "do not modify the existing foundation, and update the corresponding half-section and half-elevation geometry. Keep the unrelated pitching detail "
               "unchanged. Show me anything ambiguous before applying the change.")

# what the instruction's author means, clause by clause (quote, the kinds a faithful reading may give it, what handles it)
CLAUSES = [
    ("Reduce the clear span to 2500 mm", {"change_value"}, {"plan"}),
    ("Keep the middle wall centred", {"keep", "scope"}, {"plan"}),
    ("preserve both wall thicknesses and the slab thicknesses", {"keep"}, {"plan"}),
    ("hold the bed level fixed", {"keep"}, {"plan", "values"}),
    ("do not modify the existing foundation", {"keep"}, {"plan"}),
    ("update the corresponding half-section and half-elevation geometry", {"scope", "link_views", "keep", "process"}, {"plan", "views", "links", "none"}),
    ("Keep the unrelated pitching detail unchanged", {"keep"}, {"plan"}),
    ("Show me anything ambiguous before applying the change", {"process"}, {"question", "none"}),
]
MODES = {"Foundation": {"keep_fixed", "exclude"}, "PitchingDetail": {"exclude", "keep_fixed"}, "OuterWall": {"keep_value", "preserve"},
         "TopSlab": {"keep_value", "preserve"}, "BottomSlab": {"keep_value", "preserve"}, "WingLeft": {"follow", "translate", "resize"},
         "WingRight": {"follow", "translate", "resize"}}
SIZES = ("ClearSpan", "OuterWall", "TopSlab", "BottomSlab")


@dataclass
class Case:
    sheet: SheetSession
    uid: str
    g: dict
    truth_parts: dict[str, str]  # part name → its region
    truth_sizes: dict[str, set[tuple[str, str]]]  # size → its occurrences as (line, line)
    instruction: str = INSTRUCTION
    requested: float = 2500.0
    anchor_expected: str = "centered"
    anchor_stated: bool = True
    notes: list[str] = field(default_factory=list)


def make_case(directory: str | Path | None = None, box: Box | None = None, instruction: str = INSTRUCTION) -> Case:
    """The generated two-view box (section + plan with wing walls, a foundation and an unrelated detail), nothing parametrized."""
    directory = Path(directory or tempfile.mkdtemp(prefix="acceptance-"))
    g = box_gad(directory / "box.dxf", box or Box())
    sheet = SheetSession(g["path"])
    uid = next(k for k, u in sheet.sm.units.items() if len(u.views) == 2)
    ans = box_answer(sheet.sm, uid, g["box"], g["handles"])
    an = sheet.sm.unit(uid).an
    parts = {c["name"]: c["regions"][0] for c in ans["components"] if c.get("regions")}
    sizes = {}
    for p in ans["parameters"]:
        if p.get("candidate"):
            sizes[p["name"]] = {(an.gaps[x].a, an.gaps[x].b) for x in p["occurrences"]}
        else:
            sizes[p["name"]] = {(p["from_datum"], p["to_datum"])}
    return Case(sheet, uid, g, parts, sizes, instruction=instruction)


# ── the model the person would hope for, and careless ones (scripted: they prove the scorer) ──


def script_for(case: Case, style: str = "careful") -> ScriptedModel:
    sm, uid = case.sheet.sm, case.uid
    ans = box_answer(sm, uid, case.g["box"], case.g["handles"])
    built = answer_as_calls(ans)
    reading = [{"quote": q, "kind": next(iter(k)), "meaning": q, "handled_by": next(iter(h))} for q, k, h in CLAUSES]
    dirs = [{"target": "Foundation", "mode": "keep_fixed", "clause": "do not modify the existing foundation"},
            {"target": "WingLeft", "mode": "follow", "clause": "update the corresponding half-section and half-elevation geometry"},
            {"target": "WingRight", "mode": "follow", "clause": "update the corresponding half-section and half-elevation geometry"},
            {"target": "PitchingDetail", "mode": "exclude", "clause": "Keep the unrelated pitching detail unchanged"},
            {"target": "OuterWall", "mode": "keep_value", "clause": "preserve both wall thicknesses and the slab thicknesses"},
            {"target": "TopSlab", "mode": "keep_value", "clause": "preserve both wall thicknesses and the slab thicknesses"},
            {"target": "BottomSlab", "mode": "keep_value", "clause": "preserve both wall thicknesses and the slab thicknesses"}]
    anchor = {"policy": "centered", "clause": "Keep the middle wall centred"}
    if style == "wrong_part":  # the engine will faithfully do what it is told with the WRONG part: the geometry fails, the cause is the model's
        parts = built[0][1]["items"]
        a, b = next(p for p in parts if p["name"] == "Foundation"), next(p for p in parts if p["name"] == "WingLeft")
        a["regions"], b["regions"] = b["regions"], a["regions"]
    if style == "careless":
        reading = [{**r, "quote": r["quote"]} for r in reading[:4]] + [{"quote": "Keep the abutments rigid", "kind": "keep", "meaning": "invented", "handled_by": "plan"}]
        dirs = [{"target": "Foundation", "mode": "keep_fixed", "clause": ""}, {"target": "PitchingDetail", "mode": "keep_value", "clause": "Keep the unrelated pitching detail unchanged"}]
        anchor = {"policy": "start_fixed", "clause": ""}  # a guess, with no words of the person behind it
    build = [call(n, **a) for n, a in built]
    return ScriptedModel([
        [call("account_instruction", items=reading)], [call("inspect_sheet")], [*build],
        [call("inspect_assembly", parameter="ClearSpan")],
        [call("propose_plan", parameter="ClearSpan", requested_value=case.requested, anchor=anchor, directives=dirs)],
        [call("finish", summary="x")], [call("finish", summary="x")], [call("finish", summary="x")], [call("finish", summary="x")]])


# ── answering as the instruction's author would ──


def author_answers(case: Case, questions: list[dict]) -> dict[str, str]:
    out = {}
    for q in questions:
        opts = q.get("options") or []
        if q["about"] == "anchor":
            out[q["id"]] = next((o for o in opts if o.startswith(case.anchor_expected)), q.get("recommended") or (opts[0] if opts else "ok"))
        elif q["about"].startswith("D") or "AI proposes" in q["text"]:
            m = re.search(r"proposes: (\S+) — (\w+)", q["text"])
            ok = bool(m) and m.group(2) in MODES.get(m.group(1), set())
            out[q["id"]] = "accept" if ok and "accept" in opts else "reject" if "reject" in opts else (opts[0] if opts else "ok")
        elif q["about"].startswith("attached:"):
            name = q["about"].split(":", 1)[1]
            out[q["id"]] = "follow" if "follow" in opts and MODES.get(name, {"follow"}) & {"follow", "translate", "resize"} else "keep_fixed" if "keep_fixed" in opts else (opts[0] if opts else "ok")
        else:
            out[q["id"]] = q.get("recommended") or (opts[0] if opts else "ok")
    return out


# ── the run, then its score ──


def evaluate(gem, case: Case | None = None, budget: dict | None = None, timeout_s: float = 600.0, log=print) -> dict:
    """Run `gem` on the case (answering its questions as the author would) and score the run. Returns {"scores", "run", "geometry", "cost"}."""
    case = case or make_case()
    sheet = case.sheet
    sheet.gem = gem
    t0 = time.time()
    rid = sheet.start_run({"instruction": case.instruction, "scope": {"views": ["V01"]}, "options": {"budget": budget or {}}})["run"]
    asked = 0
    while True:
        run = sheet.runs[rid]
        end = time.time() + max(1.0, timeout_s - (time.time() - t0))
        while time.time() < end and run.status in ("queued", "running", "stopping"):
            time.sleep(0.05)
        if run.status == "awaiting_user" and asked < 6:
            asked += 1
            answers = author_answers(case, run.questions)
            log(f"  the person is asked {len(run.questions)} question(s): " + "; ".join(f"{k.split(':')[-1]}={v}" for k, v in answers.items()))
            sheet.continue_run({"run": rid, "answers": answers})
        elif run.status == "paused" and asked < 12:
            asked += 1
            sheet.continue_run({"run": rid})
        else:
            break
    run = sheet.runs[rid]
    return {"run": run.progress(0), "scores": score(case, run), "seconds": round(time.time() - t0, 1)}


def _aka(a: str, b: str) -> bool:
    """Do two names mean the same thing? The same words, or one concept of this project's knowledge (every word of one of its aliases in
    both) — 'Foundation' and 'Footing' do; 'Foundation' and 'WingLeft' do not."""
    from ..plan import _concepts, words

    wa, wb = words(a), words(b)
    if wa and wa == wb:
        return True

    def concepts(w: set[str]) -> set[str]:
        return {c for c, als in _concepts().items() if any(al and al <= w for al in als)}

    return bool(concepts(wa) & concepts(wb))


def _pairs_of(wb, row: dict) -> set[tuple[str, str]]:
    return {(a, b) for _g, a, b in wb._row_pairs(row)}


def _geometry(case: Case, anchor: str = "centered") -> tuple[float, dict]:
    sm = case.sheet.sm
    sr = sm.regenerate()
    want = _expected_points(case.g["box"], case.requested, anchor, "keep_fixed", "follow")
    worst, per = 0.0, {}
    for name, h in case.g["handles"].items():
        k = next(it.index for it in sm.dr.items if it.handle == h)
        got = sr.reg.pts.get(k, sm.dr.items[k].pts)
        exp = want[name]
        d = max(min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in exp) for p in got[: len(exp)])
        per[name] = round(d, 3)
        worst = max(worst, d)
    return worst, per


def score(case: Case, run) -> dict:
    """Score a finished (or stopped) run, category by category. Each category: {score 0..1, detail}; `unsafe` counts what must never happen."""
    b = run.bench
    sm = case.sheet.sm
    wb = b.units.get(case.uid) if b else None
    out: dict[str, dict] = {}

    def put(cat: str, value: float, detail: str, **extra) -> None:
        out[cat] = {"score": round(float(value), 3), "detail": detail, **extra}

    ledger = b.ledger if b else []
    hits = []
    for quote, kinds, handlers in CLAUSES:
        want = re.sub(r"[^a-z0-9]+", " ", quote.lower()).strip()
        hit = next((i for i in ledger if want in re.sub(r"[^a-z0-9]+", " ", i["quote"].lower()) or re.sub(r"[^a-z0-9]+", " ", i["quote"].lower()) in want), None)
        hits.append(bool(hit and hit["kind"] in kinds and hit["handled_by"] in handlers))
    put("instruction_interpretation", sum(hits) / len(CLAUSES), f"{sum(hits)}/{len(CLAUSES)} clauses read as asked")
    region_parts = {}
    if wb is not None:
        for c in wb.answer["components"]:
            for r in c.get("regions", []):
                region_parts[r] = (c["name"], c.get("type", ""))
    wanted = [n for n in case.truth_parts if n in ("Foundation", "PitchingDetail", "WingLeft", "WingRight", "LeftWall", "RightWall", "TopSlab", "BottomSlab")]
    got = [n for n in wanted if case.truth_parts[n] in region_parts and any(_aka(n, h) for h in region_parts[case.truth_parts[n]])]
    put("component_identification", len(got) / max(1, len(wanted)), f"{len(got)}/{len(wanted)} parts are the regions they should be" + (
        f" (wrong: {', '.join(n for n in wanted if n not in got)})" if len(got) < len(wanted) else ""))
    rows = (wb.answer["parameters"] if wb else [])
    mine = {r["name"]: _pairs_of(wb, r) for r in rows} if wb else {}
    ids = {size: next((n for n, p in mine.items() if p and p >= pairs), None) for size, pairs in case.truth_sizes.items() if size in SIZES}
    put("parameter_identification", sum(1 for v in ids.values() if v) / max(1, len(ids)), f"sizes found on their occurrences: {ids}")
    merged = [n for n, p in mine.items() if sum(1 for pairs in case.truth_sizes.values() if p & pairs) > 1]
    put("binding_selection", 0.0 if merged else 1.0, "no value takes in two sizes" if not merged else f"{', '.join(merged)} takes in occurrences of more than one size")
    plans = wb.answer.get("plans", []) if wb else []
    plan = next((p for p in plans if (p.get("driver") or {}).get("parameter") in (ids.get("ClearSpan"), "ClearSpan")), plans[0] if plans else None)
    anchor = (plan or {}).get("anchor") or {}
    asked_anchor = any(e["kind"] == "question" and e.get("about") == "anchor" for e in run.events)
    ok_anchor = anchor.get("policy") == case.anchor_expected and anchor.get("source") in ("instruction", "person", "accepted before", "only feasible")
    guessed = bool(plan) and anchor.get("policy") and anchor.get("source") not in ("instruction", "person", "accepted before", "only feasible")
    put("anchor_choice", 1.0 if ok_anchor else 0.0, f"anchor {anchor.get('policy')} from {anchor.get('source')}" + ("; asked" if asked_anchor else ""), unsafe=int(bool(guessed)))
    dirs = {d["target"]: d for d in (plan or {}).get("directives", []) if d.get("status") == "accepted"}
    right = [t for t, modes in MODES.items() if t in dirs and dirs[t]["mode"] in modes]
    put("dependency_planning", len(right) / len(MODES), f"{len(right)}/{len(MODES)} parts behave as the instruction says")
    inv = [dirs.get(t, {}).get("mode") in ("keep_value", "preserve") for t in ("OuterWall", "TopSlab", "BottomSlab")] + [ok_anchor]
    put("invariant_selection", sum(inv) / len(inv), f"{sum(inv)}/{len(inv)} invariants kept (thicknesses, the centre line)")
    value = sm.current().get(f"{case.uid}.ClearSpan")
    changed_views = {v for v, n in sm.regenerate().by_view.items() if v and n}
    put("cross_view_correspondence", 1.0 if {"V01", "V02"} <= changed_views and value == case.requested else 0.0, f"views changed: {sorted(changed_views)}; ClearSpan = {value}")
    worst, per = _geometry(case)
    done = value == case.requested
    put("geometry_execution", 1.0 if done and worst <= 0.5 else 0.0, (f"worst member off by {worst:.2f} mm" if done else "the value was not applied: nothing to measure"), members=per)
    refusals = [e for e in run.events if e["kind"] == "tool" and not e.get("ok") and not e.get("waiting")]
    verdict = run.verdict or {}
    # the engine is judged on what it did with what it was told: it never applies a change that fails its own measured promises, and a change it
    # refuses leaves the sheet as it was — whoever's fault the refusal is
    plan_rows = verdict.get("plans") or []
    unchanged = not sm.regenerate().changed
    held = bool(done and plan_rows and all(r["ok"] for r in plan_rows)) or (not done and unchanged)
    put("engine_integrity", 1.0 if held else 0.0, "every applied change passed its measured promises" if done and held else
        "nothing was applied, and the sheet is as imported" if (not done and unchanged) else "a change was applied that its own checks do not support")
    put("validation_recovery", 1.0 if verdict.get("state") == "completed" else 0.0, f"{len(refusals)} refused call(s); run {run.status}; {len(verdict.get('remaining', []))} thing(s) remain")
    fabricated = sum(1 for e in run.events if e["kind"] == "tool" and e["name"] == "account_instruction" and "QUOTE" in json_text(e.get("result")))
    questions = [e for e in run.events if e["kind"] == "question"]
    expected_q = 0 if case.anchor_stated else 1
    put("clarification", 0.0 if fabricated else 1.0 if len(questions) >= expected_q else 0.0, f"{len(questions)} question(s) asked; {fabricated} quote(s) not in the person's words", fabricated=fabricated,
        unsafe=fabricated)
    cats = list(out)
    ai = ["instruction_interpretation", "component_identification", "parameter_identification", "binding_selection", "anchor_choice", "dependency_planning", "invariant_selection", "clarification"]
    intent = ["cross_view_correspondence", "geometry_execution"]
    out["_summary"] = {"ai": round(sum(out[c]["score"] for c in ai) / len(ai), 3), "engine": out["engine_integrity"]["score"],
                       "intent": round(sum(out[c]["score"] for c in intent) / len(intent), 3), "outcome": 1.0 if verdict.get("state") == "completed" else 0.0,
                       "unsafe": sum(out[c].get("unsafe", 0) for c in cats), "categories": len(cats)}
    return out


def json_text(x) -> str:
    import json

    try:
        return json.dumps(x, default=str)
    except (TypeError, ValueError):
        return str(x)


def table(scores: dict) -> str:
    rows = [f"  {c:<28} {v['score']:>4.2f}  {v['detail']}" + ("  UNSAFE" if v.get("unsafe") else "") for c, v in scores.items() if not c.startswith("_")]
    s = scores["_summary"]
    return "\n".join(rows + [f"  AI {s['ai']:.2f} · engine {s['engine']:.2f} · result matches the author's intent {s['intent']:.2f} · run complete {s['outcome']:.0f} · unsafe {s['unsafe']}"])


def live_limits(budget: Budget | None = None) -> dict:
    """What a live acceptance run is limited to — printed before anything is started."""
    b = budget or Budget.from_env(soft_turns=30, max_turns=60, max_tokens=250_000, wall_s=1200)
    return {**b.to_dict(), "note": "tokens = output + thinking tokens; input tokens (the pictures and the overview, cached after the first turn) are billed on top"}
