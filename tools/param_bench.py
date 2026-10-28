"""How much of a drawing is parametric, measured — and how much the harness lets an agent reach. Read-only on the inputs; no model, no server.

    uv run python -I tools/param_bench.py --cases tools/bench_cases.json [--only 173A,20A] [--ceiling] [--domain bridge] \\
        [--out out/agent-logs/<dir>/bench.jsonl] [--md out/agent-logs/<dir>/bench.md]
    uv run python -I tools/param_bench.py --case 173A=~/Downloads/173A.dxf,<copy of its autosave> [...]

The metrics (docs/PARAM_BENCH.md), all measured by the engine on the drawing's own DIMENSIONS — what its drafter stated:

  driven         a value somebody named (not one the engine generated) moves the dimension's two lines (coverage.py)
  PARAMETRIZED   driven, AND that value can be edited: its ±10 % step (levels ±0.1 m) regenerates a valid sheet both ways. The headline share.
                 Naming a part counts for nothing; a name the engine generated counts for nothing; a value that breaks the sheet when edited
                 counts for nothing, and neither does one whose step the sheet accepts but runs structural members into each other that do
                 not cross with the value as it is (2026-10-28; before, such a step counted as an edit)
  edits          every named value stepped ±10 %: the share whose both steps are accepted, and each refused step's failures by kind (refusal.py:
                 the edit cannot be drawn / the model does not carry it / an accepted plan says otherwise / a rule / the solver)
  views          shared values (one value bound in several views): the share whose steps are accepted — accepted means every view measured the
                 new value (the sheet refuses a view that does not follow)
  annotation     for a sample of editable values: the sheet exported before and after the +10 % step; every DIMENSION the value drives must show
                 a number that changed in proportion to the distance it measures (its own text override, or measurement × DIMLFAC)
  identified     (cases that list the components the drawing labels itself) the components some part's NAME says, with the dimensions on those
                 parts parametrized. Measured by name, not geometry: a part named wrongly still counts as found (see docs)
  cost           (cases with a recorded run) the run's model calls and tokens from the ledger, and per parametrized dimension. The ledger has no
                 price unless VERTEX_PRICES was set: tokens are the cost measure then

  baseline   the saved work as it is (a drawing without saved work: the engine's own reading, which names nothing — 0 by definition)
  ceiling    every dimension the agent's `coverage` tool lists as not driven, bound through the same tool path a model's call takes
             (define_parameters with the dimension's id, validated, taken back if it breaks the drawing), then committed with the whole-sheet
             checks and the design intent derived, as a run commits; repeated while a pass binds something (coverage lists a part's first open
             dimensions). The names are PLACEHOLDERS (Auto<part><n>): the ceiling measures what binding can reach, not naming quality
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

STEP = 0.1  # ±10 % of a length, ±0.1 m of a level


# ── which values somebody named, and whether each can be edited ─────────────────


def named_values(sm) -> dict[str, tuple[str, str, str]]:
    """Every value a person can set that somebody named: sheet key → (unit, local name, kind) of a binding that drives it."""
    from dxf_autoparam.generic import is_generated

    out: dict[str, tuple[str, str, str]] = {}
    shared = sm._shared_by_name()
    for key in sorted(sm.current()):
        if key in shared:
            b = next((b for b in shared[key].bindings if b.status == "drives"), None)
            if b is None:
                continue
            uid, local = b.unit, b.param
        else:
            uid, local = key.split(".", 1)
        prm = sm.unit(uid).prog.params.get(local)
        if prm is None or (is_generated(local) and prm.source != "ai") or prm.kind not in ("length", "level"):
            continue
        out[key] = (uid, local, prm.kind)
    return out


def step_values(sm, keys: dict[str, tuple[str, str, str]]) -> dict[str, dict]:
    """key → {"ok": both steps accepted, "kinds": failures of the refused steps, by kind, "checks": by check}."""
    from dxf_autoparam.behaviour import crossings

    now = sm.current()
    out = {}
    for key, (_uid, _local, kind) in keys.items():
        v = now[key]
        kinds: Counter = Counter()
        checks: Counter = Counter()
        oks = []
        base: set | None = None
        for w in ([v + STEP, v - STEP] if kind == "level" else [v * (1 + STEP), v * (1 - STEP)]):
            r = sm.regenerate({key: w})
            ok = r.ok
            if not r.ok:
                for f in sm.explain(r, {key: w}):
                    kinds[f["kind"] + (" (already failing)" if f.get("existing") else "")] += 1
                    checks[f["check"]] += 1
            else:  # accepted, and still not an edit if it runs members into each other (the sheet refuses that only against a person's plan)
                base = crossings(sm, {key: v}) if base is None else base
                if crossings(sm, {key: w}) - base:
                    ok = False
                    kinds["members cross (accepted by the sheet)"] += 1
                    checks["members cross"] += 1
            oks.append(ok)
        out[key] = {"ok": all(oks), "steps_ok": sum(oks), "kinds": dict(kinds), "checks": dict(checks)}
    return out


def key_of(sm, uid: str, local: str) -> str:
    for p in sm.shared.values():
        if any(b.unit == uid and b.param == local and b.status == "drives" for b in p.bindings):
            return p.name
    return f"{uid}.{local}"


# ── the metrics ──────────────────────────────────────────────────────────────────


def coverage(sm, units: list[str], steps: dict[str, dict]) -> dict:
    """Dimensions per unit: total, driven, PARAMETRIZED (driven by a value whose edits are accepted), kept as drawn, unread."""
    from dxf_autoparam.coverage import unit_coverage

    tot: Counter = Counter()
    per = {}
    rows_of: dict[str, list[dict]] = {}
    for uid in units:
        u = sm.unit(uid)
        if u.prog is None:
            continue
        rows = unit_coverage(u.prog, kept=set((u.answer or {}).get("kept_dimensions", {})))["rows"]
        rows_of[uid] = rows
        c: Counter = Counter(dimensions=len(rows))
        for r in rows:
            c[r["status"]] += 1
            c["writes_another_number"] += r.get("writes") is not None
            if r["status"] == "driven" and any(steps.get(key_of(sm, uid, n), {}).get("ok") for n in r.get("by", [])):
                c["parametrized"] += 1
                r["parametrized"] = True
        per[uid] = f"{c['parametrized']}/{c['dimensions']}"
        tot.update(c)
    d = tot["dimensions"]
    return {"dimensions": d, "driven": tot["driven"], "parametrized": tot["parametrized"], "kept": tot["kept"], "unread": tot["unread"],
            "writes_another_number": tot["writes_another_number"],
            "share_driven": round(tot["driven"] / d, 3) if d else None, "share": round(tot["parametrized"] / d, 3) if d else None,
            "units": per, "_rows": rows_of}


def edits(steps: dict[str, dict]) -> dict:
    kinds: Counter = Counter()
    for s in steps.values():
        kinds.update(s["kinds"])
    ok = sum(1 for s in steps.values() if s["ok"])
    return {"values": len(steps), "editable": ok, "share": round(ok / len(steps), 3) if steps else None, "refused_by": dict(kinds.most_common())}


def views(sm, steps: dict[str, dict]) -> dict:
    shared = [p.name for p in sm.shared.values() if sum(1 for b in p.bindings if b.status == "drives") > 1]
    ok = [n for n in shared if steps.get(n, {}).get("ok")]
    follow = sum(1 for n in shared if steps.get(n, {}).get("checks", {}).get("FOLLOW"))
    return {"shared": len(shared), "editable_in_every_view": len(ok), "a_view_did_not_follow": follow}


def _shown(e) -> tuple[float, int] | None:
    """What a DIMENSION shows: the number its text override writes (with its decimals), or its measurement × DIMLFAC."""
    text = e.dxf.get("text", "") or ""
    toks = re.findall(r"\d+(?:\.\d+)?", text) if text not in ("", "<>") else []
    if toks:
        t = max(toks, key=lambda s: float(s))
        return float(t), len(t.split(".")[1]) if "." in t else 0
    try:
        return float(e.get_measurement()) * float(e.override().get("dimlfac", 1.0) or 1.0), 6
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        return None


def _dims_at(path: str) -> dict[tuple, object]:
    """Every DIMENSION of an exported drawing — in modelspace, or still inside a block reference the writer kept — by where its two measured points
    are (WCS): a dimension the writer exploded out of a reshaped view has a new handle, but it is where the engine put it."""
    import ezdxf

    out: dict[tuple, object] = {}

    def walk(entities, depth: int = 0) -> None:
        for e in entities:
            t = e.dxftype()
            if t == "DIMENSION":
                p2, p3 = e.dxf.get("defpoint2"), e.dxf.get("defpoint3")
                if p2 is not None and p3 is not None:
                    out.setdefault((round(p2.x, 2), round(p2.y, 2), round(p3.x, 2), round(p3.y, 2)), e)
            elif t == "INSERT" and depth < 8:
                try:
                    walk(list(e.virtual_entities()), depth + 1)
                except (ezdxf.DXFError, ValueError, KeyError, ArithmeticError):
                    continue  # a block ezdxf cannot expand: its dimensions are not found, and the row is not counted

    walk(ezdxf.readfile(path).modelspace())
    return out


def _find(dims: dict[tuple, object], pts) -> object | None:
    if not pts or len(pts) < 3:
        return None
    return dims.get((round(pts[1][0], 2), round(pts[1][1], 2), round(pts[2][0], 2), round(pts[2][1], 2)))


def annotation(sm, steps: dict[str, dict], keys: dict[str, tuple[str, str, str]], rows_of: dict[str, list[dict]], limit: int) -> dict:
    """A sample of editable lengths, each stepped +10 % and exported: does every dimension it drives show the new number?"""
    picks = [k for k in sorted(keys) if steps[k]["ok"] and keys[k][2] == "length"][:limit]
    if not picks:
        return {"values": 0, "dimensions": 0, "correct": 0}
    tmp = Path(tempfile.mkdtemp(prefix="bench-"))
    before = str(tmp / "before.dxf")
    sm.export(before)
    dims0 = _dims_at(before)
    pts0 = sm.regenerate().reg.pts
    checked = correct = missing = 0
    wrong: list[str] = []
    for n, key in enumerate(picks):
        uid0, local0, _k = keys[key]
        targets = [(b.unit, b.param) for p in sm.shared.values() if p.name == key for b in p.bindings if b.status == "drives"] or [(uid0, local0)]
        v = sm.current()[key]
        dists0 = {}
        for uid, local in targets:
            u = sm.unit(uid)
            d0 = u.prog.datum_values({**u.prog.defaults(), **sm._values_for(u, {})})
            dists0[uid] = (u, d0, [r for r in rows_of.get(uid, []) if local in r.get("by", []) and r.get("lines")])
        r = sm.apply({key: v * (1 + STEP)})
        if not r.ok:
            continue
        after = str(tmp / f"after{n}.dxf")
        sm.export(after)
        dims1, pts1 = _dims_at(after), sm.regenerate().reg.pts
        for uid, (u, d0, rows) in dists0.items():
            d1 = u.prog.datum_values({**u.prog.defaults(), **sm._values_for(u, {})})
            for row in rows:
                s = u.back[row["index"]]
                it = sm.dr.items[s]
                e0, e1 = _find(dims0, pts0.get(s, it.pts)), _find(dims1, pts1.get(s, it.pts))
                if e0 is None or e1 is None:
                    missing += 1
                    continue
                s0, s1 = _shown(e0), _shown(e1)
                a, b = row["lines"]
                g0, g1 = abs(d0[b] - d0[a]), abs(d1[b] - d1[a])
                if s0 is None or s1 is None or g0 <= 0:
                    missing += 1
                    continue
                checked += 1
                want = s0[0] * g1 / g0
                tol = max(0.51 * 10 ** -s1[1], 1e-6 * abs(want)) if s1[1] < 6 else max(0.5 * s0[0] / max(g0 * u.sub.units_mm, 1e-9), 1e-6)
                if abs(s1[0] - want) <= tol:
                    correct += 1
                elif len(wrong) < 8:
                    wrong.append(f"{uid} {row['id']} ({key} +10 %): shows {s1[0]:g}, expected {want:.3f}"
                                 + (f" — it writes {row['writes']:g} over {row.get('mm')} mm drawn" if row.get("writes") is not None else ""))
        sm.undo()
    return {"values": len(picks), "dimensions": checked, "correct": correct, "share": round(correct / checked, 3) if checked else None,
            **({"not_found_in_export": missing} if missing else {}), **({"wrong": wrong} if wrong else {})}


def _stem(w: str) -> str:
    """One word in its singular: walls → wall, haunches → haunch, pits → pit (a part named for several of a thing is still that thing)."""
    if len(w) > 4 and w.endswith("es") and w[:-2].endswith(("ch", "sh", "x", "ss")):
        return w[:-2]
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _words(name: str) -> set[str]:
    return {_stem(w.lower()) for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name.replace("_", " "))}


def identified(sm, expect: list[dict], rows_of: dict[str, list[dict]]) -> dict:
    """Each component a drafter would name: the parts whose name holds its words, and the dimensions on them parametrized."""
    parts_of = {}
    for uid, u in sm.units.items():
        if u.prog is None:
            continue
        for name in u.prog.intent.get("parts") or {}:
            parts_of[(uid, name)] = _words(name)  # its name, not the type the agent gave it: a boulder layer typed "drainage" is not a drain
    found, out = 0, []
    for c in expect:
        words = {_stem(w.lower()) for w in c["words"]}
        hits = [(uid, name) for (uid, name), ws in parts_of.items() if words <= ws]
        tot = par = 0
        for uid in {h[0] for h in hits}:
            mine = {h[1] for h in hits if h[0] == uid}
            for r in rows_of.get(uid, []):
                if set(r.get("parts") or ()) & mine:  # the parts drawn on the dimension's lines (coverage.py)
                    tot += 1
                    par += bool(r.get("parametrized"))
        found += bool(hits)
        out.append({"component": c["component"], "parts": [f"{u}.{n}" for u, n in hits][:6], "dimensions": tot, "parametrized": par})
    return {"expected": len(expect), "found": found, "share": round(found / len(expect), 3) if expect else None, "components": out}


def cost(window: list[str] | None, parametrized: int, ledger: str = ".cache/ai/usage.jsonl") -> dict | None:
    if not window or not Path(ledger).exists():
        return None
    rows = [json.loads(line) for line in Path(ledger).read_text().splitlines() if line.strip()]
    sel = [r for r in rows if window[0] <= r.get("at", "") <= window[1]]
    usd = sum(float(r.get("cost_usd") or 0.0) for r in sel)
    tokens = sum(int(r.get("input_tokens") or 0) for r in sel)
    out = {"calls": len(sel), "input_tokens": tokens, "cached_tokens": sum(int(r.get("vertex_cached_tokens") or 0) for r in sel),
           "output_tokens": sum(int(r.get("output_tokens") or 0) for r in sel), "models": sorted({r.get("model", "?") for r in sel}),
           "usd": round(usd, 4) if usd else "no price in the ledger"}
    if parametrized:
        out["input_tokens_per_parametrized_dimension"] = round(tokens / parametrized)
        out["calls_per_parametrized_dimension"] = round(len(sel) / parametrized, 2)
    return out


def measure(sm, units: list[str], expect: list[dict] | None, annotation_limit: int) -> dict:
    keys = named_values(sm)
    steps = step_values(sm, keys)
    cov = coverage(sm, units, steps)
    rows_of = cov.pop("_rows")
    out = {"coverage": cov, "edits": edits(steps), "views": views(sm, steps)}
    if annotation_limit:
        out["annotation"] = annotation(sm, steps, keys, rows_of, annotation_limit)
    if expect:
        out["identified"] = identified(sm, expect, rows_of)
    return out


# ── the ceiling: bind every listed dimension through the agent's own tool path ───


def _bind_all(sm, uid: str, pack) -> dict:
    """One unit: open its workbench as a run does, bind every dimension `coverage` lists as not driven, commit to the sheet."""
    from dxf_autoparam import design_intent
    from dxf_autoparam.ai import agent as A
    from dxf_autoparam.ai.agent import pascal
    from dxf_autoparam.ai.context import SheetScope
    from dxf_autoparam.ai.loop import Budget, LoopState, execute_calls
    from dxf_autoparam.crossview import SheetError
    from dxf_autoparam.viewimg import box_around

    u = sm.unit(uid)
    wb = A.Workbench(sm.path, region=box_around([sm.layout.group(v).bbox for v in u.views], 0.0),
                     start=design_intent.strip(u.answer) if u.answer else None, drawing=u.sub, analysis=sm.pristine_analysis(uid),
                     scope=SheetScope(sm, uid), pack=pack)
    cov = wb.coverage()
    todo = [(p, r) for p, e in cov["parts"].items() for r in e.get("open", [])] + [(None, r) for r in cov["unassigned"]]
    seen, items, taken = set(), [], set(wb.prog.params)
    for p, r in todo:
        if r["dimension"] in seen:
            continue
        seen.add(r["dimension"])
        n, stem = 1, f"Auto{pascal(p) if p else 'Sheet'}"
        while f"{stem}{n}" in taken:  # a name of its own, also against the values an earlier pass bound
            n += 1
        taken.add(f"{stem}{n}")
        items.append({"name": f"{stem}{n}", "part": p or "", "dimension": r["dimension"]})
    verdicts: list[dict] = []
    if items:  # what a model reads back: the function response of the call, one verdict per item
        parts, _done = execute_calls(wb, [SimpleNamespace(name="define_parameters", args={"items": items})], lambda e: None, LoopState(), Budget(), {})
        for part in parts:
            res = part.function_response.response.get("result")
            verdicts += [v for v in ((res or {}).get("result") if isinstance(res, dict) else res) or [] if isinstance(v, dict)]
    accepted = sum(1 for v in verdicts if v.get("ok"))
    causes: dict[str, int] = {}
    for v in verdicts:
        if not v.get("ok"):
            code = ((v.get("failure") or {}).get("code")) or (v.get("rejected") or ["?"])[0].split(":")[0]
            causes[code] = causes.get(code, 0) + 1
    committed, why = True, ""
    try:  # as a run commits a unit (sheet_ai.commit_unit): the design intent derived again — which side of each size stays
        sm.commit_answer(uid, wb.answer)
    except SheetError as exc:
        committed, why = False, str(exc)[:300]
    return {"asked": len(items), "accepted": accepted, "refused_by": causes, "committed": committed, **({"why_not": why} if why else {})}


def run_case(case: dict, ceiling: bool, domain: str | None, annotation_limit: int) -> dict:
    from dxf_autoparam.ai import domain as D
    from dxf_autoparam.crossview import SheetModel

    t0 = time.time()
    gen = None
    if case.get("generate"):  # a generated drawing whose members are known (plan_bench's box): written fresh
        from dxf_autoparam.plan_bench import Box, box_gad

        gen = box_gad(Path(tempfile.mkdtemp(prefix="bench-gen-")) / f"{case['name']}.dxf", Box(**case["generate"]))
        case = {**case, "dxf": gen["path"]}
    dxf = str(Path(case["dxf"]).expanduser())
    saved = str(Path(case["saved"]).expanduser()) if case.get("saved") else None
    sm = SheetModel.load(saved, dxf=dxf) if saved else SheetModel.open(dxf)
    if gen is not None and case.get("expert"):  # the generator's own parametrization: the right names on every occurrence, its parts
        from dxf_autoparam.plan_bench import box_answer

        uid = next(k for k, u in sm.units.items() if len(u.views) >= 2)
        sm.commit_answer(uid, box_answer(sm, uid, gen["box"], gen["handles"]))
        saved = "the generator's own answer"
    row: dict = {"case": case["name"], "dxf": Path(dxf).name, "saved_work": bool(saved), "units": len(sm.units), **({"note": case["note"]} if case.get("note") else {})}
    views_ = [uid for uid, u in sm.units.items() if u.views]
    row["baseline"] = measure(sm, views_, case.get("expect"), annotation_limit if saved else 0)
    c = cost(case.get("ledger"), row["baseline"]["coverage"]["parametrized"])
    if c:
        row["baseline"]["cost"] = {**c, **({"run": case["run"]} if case.get("run") else {})}
    if ceiling:
        pack = D.active(domain) if domain else None
        per = {}
        for uid in views_:
            passes: list[dict] = []
            for _ in range(4):  # `coverage` lists a part's first open dimensions; once those are bound, the next ones come up — as an agent asks again
                try:
                    res = _bind_all(sm, uid, pack)
                except Exception as exc:  # noqa: BLE001 — one unit's boundary: a crash is a finding, recorded, and the next unit is measured
                    res = {"crash": f"{type(exc).__name__}: {exc}"[:300]}
                passes.append(res)
                if res.get("crash") or not res.get("accepted") or not res.get("committed"):
                    break
            refused: dict[str, int] = {}
            for x in passes:
                for k, v in (x.get("refused_by") or {}).items():
                    refused[k] = refused.get(k, 0) + v
            per[uid] = {"asked": sum(x.get("asked", 0) for x in passes), "accepted": sum(x.get("accepted", 0) for x in passes), "refused_by": refused,
                        "committed": all(x.get("committed", False) for x in passes if "crash" not in x), "passes": len(passes),
                        **{k: x[k] for x in passes for k in ("crash", "why_not") if k in x}}
        row["ceiling"] = {**measure(sm, views_, None, annotation_limit), "binding": per}
    row["seconds"] = round(time.time() - t0, 1)
    return row


# ── the report ───────────────────────────────────────────────────────────────────


def _pct(s) -> str:
    return f"{100 * s:.0f} %" if s is not None else "—"


def markdown(rows: list[dict]) -> str:
    out = [("| case | saved work | dimensions | baseline: parametrized (driven) | ceiling: parametrized (driven) | editable values (baseline → ceiling) | "
            "shared values editable in every view | annotation correct | s |"), "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        b, c = r["baseline"], r.get("ceiling") or {}
        bc, cc = b["coverage"], c.get("coverage") or {}
        ann = (c or b).get("annotation") or {}
        out.append(f"| {r['case']} | {'yes' if r['saved_work'] else 'no'} | {bc['dimensions']} | {bc['parametrized']} = {_pct(bc['share'])} ({bc['driven']}) | "
                   + (f"{cc['parametrized']} = {_pct(cc['share'])} ({cc['driven']})" if cc else "—") + " | "
                   + f"{b['edits']['editable']}/{b['edits']['values']}" + (f" → {c['edits']['editable']}/{c['edits']['values']}" if c else "") + " | "
                   + f"{(c or b)['views']['editable_in_every_view']}/{(c or b)['views']['shared']} | "
                   + (f"{ann['correct']}/{ann['dimensions']}" if ann.get("dimensions") else "—") + f" | {r['seconds']} |")
    out += ["", "Refused ±10 % steps, failed checks by kind (the ceiling where measured, else the baseline):", ""]
    for r in rows:
        rb = (r.get("ceiling") or r["baseline"])["edits"]["refused_by"]
        out.append(f"- {r['case']}: " + (", ".join(f"{k} {n}" for k, n in rb.items()) or "none"))
    for r in rows:
        ident = r["baseline"].get("identified")
        if ident:
            out += ["", f"{r['case']}: components found by name {ident['found']}/{ident['expected']}", "",
                    "| component | parts | dimensions on them | parametrized |", "|---|---|---|---|"]
            out += [f"| {c['component']} | {', '.join(c['parts']) or '—'} | {c['dimensions']} | {c['parametrized']} |" for c in ident["components"]]
        if r["baseline"].get("cost"):
            co = r["baseline"]["cost"]
            per = (f"{co['input_tokens_per_parametrized_dimension']:,} input tokens and {co['calls_per_parametrized_dimension']} calls per parametrized "
                   "dimension") if "input_tokens_per_parametrized_dimension" in co else "no dimension parametrized"
            out += ["", (f"{r['case']} — the recorded run ({co.get('run', '')}): {co['calls']} model calls, {co['input_tokens']:,} input tokens "
                         f"({co['cached_tokens']:,} cached), {co['output_tokens']:,} output; USD: {co['usd']}; {per}")]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default=None, help="a JSON file: [{name, dxf | generate, saved?, expect?, ledger?, run?, note?}]")
    ap.add_argument("--only", default=None, help="comma-separated case names from --cases")
    ap.add_argument("--case", action="append", default=[], help="NAME=drawing.dxf[,saved-work copy]")
    ap.add_argument("--ceiling", action="store_true", help="also bind every listed dimension and measure again")
    ap.add_argument("--domain", default=None, help="the domain pack for the workbench (bridge): attaches component knowledge; binding is unchanged")
    ap.add_argument("--annotation", type=int, default=10, help="how many editable values the annotation check exports (0: none)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--md", default=None)
    a = ap.parse_args()
    cases = json.loads(Path(a.cases).read_text()) if a.cases else []
    if a.only:
        cases = [c for c in cases if c["name"] in set(a.only.split(","))]
    for spec in a.case:
        name, _, rest = spec.partition("=")
        dxf, _, saved = rest.partition(",")
        cases.append({"name": name, "dxf": dxf, **({"saved": saved} if saved else {})})
    rows = []
    for case in cases:
        if not case.get("generate") and (not Path(case["dxf"]).expanduser().exists() or (case.get("saved") and not Path(case["saved"]).expanduser().exists())):
            print(json.dumps({"case": case["name"], "skipped": "its drawing or saved work is not on this machine"}), flush=True)
            continue
        row = run_case(case, a.ceiling, a.domain, a.annotation)
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items()}, default=str)[:3000], flush=True)
        if a.out:
            with open(a.out, "a") as f:
                f.write(json.dumps(row, default=str) + "\n")
    md = markdown(rows)
    print(md)
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
