"""Command line.

    dxf-autoparam analyse  drawing.dxf [--domain bridge] [--view N | --region x0,y0,x1,y1] [--json model.json]
    dxf-autoparam regen    drawing.dxf --set OpenX1=4000 [--set ...] -o out.dxf [--domain bridge]
    dxf-autoparam views    drawing.dxf
    dxf-autoparam bench    [fixtures/library] [--domain bridge]
    dxf-autoparam serve    [drawing.dxf] [--domain bridge] [--port 8765]

Sizes on the command line are millimetres; levels are metres.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import describe
from .dxf_read import read_dxf
from .dxf_write import audit, write_dxf
from .pipeline import autoparametrize, save_model, validate
from .regen import regenerate
from .views import detect_views


def _region(s: str | None):
    return tuple(float(v) for v in s.split(",")) if s else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dxf-autoparam", description="Existing DXF → parametric model → regenerated DXF")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("analyse", "regen"):
        p = sub.add_parser(name)
        p.add_argument("dxf")
        p.add_argument("--domain", choices=["bridge"], default=None)
        p.add_argument("--view", type=int, default=None)
        p.add_argument("--region", default=None)
        if name == "analyse":
            p.add_argument("--json", default=None, help="write the parametric IR here")
            p.add_argument("--validate", action="store_true")
        else:
            p.add_argument("--set", action="append", default=[], help="NAME=VALUE (mm, levels in m)")
            p.add_argument("-o", "--out", required=True)
    p = sub.add_parser("ai", help="Gemini proposes, the validator decides → a validated parametric program")
    p.add_argument("dxf")
    p.add_argument("--view", type=int, default=None)
    p.add_argument("--region", default=None)
    p.add_argument("--rounds", type=int, default=2, help="(--oneshot) 1 proposal + up to rounds-1 repair rounds")
    p.add_argument("--oneshot", action="store_true", help="one big answer + repair rounds instead of the tool-using agent")
    p.add_argument("--instructions", default="", help="what to parametrize / keep / expect to change, in words")
    p.add_argument("--json", default=None, help="write the validated program here")
    p.add_argument("--set", action="append", default=[], help="NAME=VALUE to regenerate with (mm, levels in m)")
    p.add_argument("-o", "--out", default=None, help="regenerated DXF")
    p.add_argument("--answer-out", default=None, help="save Gemini's answer (re-open it with serve --answer)")
    p = sub.add_parser("json", help="DXF → CAD JSON: entities, regions, relationships, datums, candidates (what the AI reads)")
    p.add_argument("dxf")
    p.add_argument("--view", type=int, default=None)
    p.add_argument("--region", default=None)
    p.add_argument("--ai", action="store_true", help="the trimmed form sent to the AI")
    p.add_argument("--split", default=None, help="also write drawing/geometry/topology/datums/relationships/parameters .json into this folder")
    p.add_argument("-o", "--out", default=None, help="write here (default: print a summary)")
    p = sub.add_parser("learn", help="original + edited DXF → what the edit changed, what grew, moved or stayed, and what the program cannot explain")
    p.add_argument("original")
    p.add_argument("edited")
    p.add_argument("--json", default=None)
    p = sub.add_parser("check", help="free, no AI: does the engine hold on these drawings? (every named size drives or is explained, "
                                     "values change validly, the DXF exports)")
    p.add_argument("dxf", nargs="+")
    p.add_argument("--out", default="out/check")
    p = sub.add_parser("views")
    p.add_argument("dxf")
    p = sub.add_parser("bench")
    p.add_argument("fixtures", nargs="?", default="fixtures/library")
    p.add_argument("--domain", choices=["bridge"], default=None)
    p = sub.add_parser("serve")
    p.add_argument("dxf", nargs="?")
    p.add_argument("--domain", choices=["bridge"], default=None)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--answer", default=None, help="open with a saved Gemini answer (validated again, no AI call)")
    p.add_argument("--project", default=None, help="open the workspace with a saved parametric project (.autoparam.json)")
    p = sub.add_parser("plan-bench", help="free, no AI: instruction-guided assembly edits on generated drawings with known intent, scored")
    p.add_argument("--out", default="plan_bench.json")
    a = ap.parse_args(argv)

    if a.cmd == "check":
        from .robustness import check_all

        rows = check_all(a.dxf, a.out)
        for r in rows:
            if "crash" in r:
                print(f"{r['drawing']:<34} CRASH {r['crash']}")
                continue
            print(f"{r['drawing']:<34} {r['entities']:>5} entities {r['regions']:>4} regions | named {r['named']}: {len(r['driving'])} drive, "
                  f"{len(r['worked_out'])} worked out, {len(r['lost'])} lost | breaks {len(r['breaks'])} | export {r.get('export')} | "
                  f"{'PASS' if r['passed'] else 'FAIL'}")
        return 0 if all(r.get("passed") for r in rows) else 1
    if a.cmd == "views":
        dr, _ = read_dxf(a.dxf)
        for v in detect_views(dr):
            print(f"view {v['id']}: {v['entities']} entities, bbox {', '.join(f'{c:.0f}' for c in v['bbox'])}")
        return 0
    if a.cmd == "json":
        from .ai.parametrize import prepare
        from .cadjson import cad_json, write_split
        from .validator import baseline

        an, _base, _used, _snap = prepare(a.dxf, a.view, _region(a.region))
        doc = cad_json(an, baseline(an), for_ai=a.ai)
        if a.split:
            print("\n".join(write_split(doc, a.split)))
        if a.out:
            Path(a.out).write_text(json.dumps(doc, indent=1, default=str))
            print(f"wrote {a.out}")
        topo = doc["topology"]
        print(f"{doc['drawing']['entities']} entities · {len(topo['regions'])} regions · {len(topo['open_features'])} open features · "
              f"{len(doc['datums'])} set-out lines · {len(doc['relationships'])} relationship candidates · {len(doc.get('candidates', []))} candidate values")
        return 0
    if a.cmd == "learn":
        from .analyse import analyse
        from .learn import learn
        from .validator import baseline

        dr, _ = read_dxf(a.original)
        lesson = learn(a.original, a.edited, baseline(analyse(dr)))
        print("\n".join(lesson["rules"]))
        if a.json:
            Path(a.json).write_text(json.dumps(lesson, indent=1, default=str))
            print(f"wrote {a.json}")
        return 0
    if a.cmd == "bench":
        from .bench import run

        run(Path(a.fixtures), domain=a.domain)
        return 0
    if a.cmd == "serve":
        from .server import serve

        serve(a.dxf, a.domain, port=a.port, answer=a.answer, project=a.project)
        return 0
    if a.cmd == "plan-bench":
        from .plan_bench import run as plan_run

        res = plan_run(a.out)
        for r in res["cases"]:
            bad = [k for k, ok in r["scores"].items() if not ok]
            print(f"{r['id']:<5} {r['category']:<12} {r.get('plan_status', ''):<15} {'ok' if not bad else 'FAILED: ' + ', '.join(bad)}")
        print()
        for c, v in res["by_category"].items():
            print(f"{c:<40} {v['passed']:>3}/{v['of']:<3} {v['rate'] * 100:5.1f}%")
        for k, v in res["by_kind"].items():
            print(f"{k:<12} cases {v['cases']}, fully right {v['cases_fully_right']}, checks {v['checks_passed']}/{v['of']}")
        print(f"→ {a.out}")
        return 0
    if a.cmd == "ai":
        from .ai.parametrize import ai_parametrize
        from .regen import regenerate_program

        if a.oneshot:
            prog, rep, info = ai_parametrize(a.dxf, view=a.view, region=_region(a.region), rounds=a.rounds, instructions=a.instructions)
        else:
            from .ai.agent import agent_parametrize
            from .ai.parametrize import prepare

            region = _region(a.region)
            if a.view is not None and region is None:
                _an, _b, region, _s = prepare(a.dxf, a.view, None)
            prog, rep, info = agent_parametrize(a.dxf, region=region, instructions=a.instructions,
                                                on_event=lambda e: e["kind"] in ("tool", "status", "note") and print("  ", e))
        st = prog.structure
        print(f"\n{st.get('structure_type')}  [{st.get('family')}]  — {'; '.join(st.get('views') or [])}")
        for c in prog.components:
            depth = 0 if c.level == "assembly" or not c.parent else 1 if c.level == "component" else 2
            print(f"{'  ' * depth}- {c.name} [{c.type}] {' '.join(c.regions)}{' (existing)' if c.existing else ''}{' — held as drawn' if c.held else ''}")
        I = prog.intent
        if I.get("behaviours"):
            ok = sum(1 for b in I["behaviours"] if b["status"] == "confirmed")
            print(f"behaviours: {ok}/{len(I['behaviours'])} confirmed by measurement")
        if I.get("constraints"):
            print(f"constraints: {sum(1 for c in I['constraints'] if c['status'] == 'always')}/{len(I['constraints'])} kept under every change")
        for p in sorted(prog.params.values(), key=lambda p: (p.source != 'ai' and p.kind != 'level', p.component, p.name)):
            print(f"  {p.name:<22} {p.value:>11.3f} {p.unit:<3} {p.component:<16} {p.label}")
        for r in prog.relations:
            if not r.name.startswith("R_"):
                print(f"  {r.name} = {r.expr}   ({'kept by the model' if r.enforced else 'holds now only'})")
        for f in rep.findings:
            print(f"  [{f.severity}] {f.code} {f.item}: {f.message}")
        print(f"validator: accepted {rep.accepted}, rejected {rep.rejected}; Gemini {info['tokens_in']} in / {info['tokens_out']} out tokens, {info['seconds']} s")
        if a.json:
            prog.save(a.json)
            print(f"wrote {a.json}")
        if a.answer_out:
            Path(a.answer_out).write_text(json.dumps(info["answer"], indent=1))
            print(f"wrote {a.answer_out}")
        if a.out:
            values = {}
            for s in a.set:
                name, _, raw = s.partition("=")
                if name not in prog.params:
                    print(f"no value called {name}", file=sys.stderr)
                    return 2
                values[name] = float(raw)
            reg = regenerate_program(prog, values)
            if reg.issues:
                print("REFUSED — the drawing would break:", *reg.issues, sep="\n  ", file=sys.stderr)
                return 1
            print(json.dumps({"written": a.out, **write_dxf(prog, reg, a.out), "audit": audit(a.out)}))
        return 0

    model = autoparametrize(a.dxf, domain=a.domain, view=a.view, region=_region(a.region))
    if a.cmd == "analyse":
        print(describe(model))
        if a.validate:
            v = validate(model)
            print(f"VALIDATION: identity {v['identity_max_error']:.1e}; {v['regenerate_ok']}/{v['parameters']} values regenerate validly at ±10%")
            for r in v["per_parameter"]:
                if not r["ok"]:
                    print(f"  {r['name']}: {r['issues'][0]}")
        if a.json:
            save_model(model, a.json)
            print(f"wrote {a.json}")
        return 0
    # regen
    u = model.analysis.drawing.units_mm
    values: dict[str, float] = {}
    for s in a.set:
        name, _, raw = s.partition("=")
        if name not in model.parameters:
            print(f"no value called {name}; values: {', '.join(model.parameters)}", file=sys.stderr)
            return 2
        p = model.parameters[name]
        values[name] = float(raw) if p.kind in ("level", "position") else float(raw) / u
    reg = regenerate(model, values)
    if reg.issues:
        print("REFUSED — the drawing would break:", *reg.issues, sep="\n  ", file=sys.stderr)
        return 1
    rep = write_dxf(model, reg, a.out)
    print(json.dumps({"written": a.out, **rep, "audit": audit(a.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
