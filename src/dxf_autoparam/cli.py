"""Command line.

    dxf-autoparam analyse  drawing.dxf [--domain bridge] [--view N | --region x0,y0,x1,y1] [--json model.json]
    dxf-autoparam regen    drawing.dxf --set OpenX1=4000 [--set ...] -o out.dxf [--domain bridge]
    dxf-autoparam views    drawing.dxf
    dxf-autoparam bench    [fixtures/library] [--domain bridge]
    dxf-autoparam serve    [drawing.dxf] [--domain bridge] [--port 8765]
    dxf-autoparam plan-bench / agent-eval   free benchmarks of the plan engine and (scripted, or --live --yes-spend) of the agent, per category
    dxf-autoparam library  list | search WORDS | show ID [--section S] | discover drawing.dxf   the engineering library (read-only, no model)
    dxf-autoparam production build | extract [--family F] | status | families | show FAMILY [--section S] | discover drawing.dxf | bench
                                       the production bridge rule engines: bundle, knowledge manifests, freshness, a benchmark (no model)

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


def _library(a) -> int:
    """`library list | search | show | discover`: what the agent can retrieve and what it would find for a drawing, printed as the model sees it."""
    from .ai import library as L

    lib = L.open_domain(a.domain)
    if lib is None:
        print(f"no library for domain {a.domain!r}; available: {', '.join(L.domains()) or 'none'}", file=sys.stderr)
        return 2
    ks = L.KnowledgeSession(lib)
    if a.action == "list":
        res = ks.call("list_skills", {"match_drawing": False})
        print(f"{lib.title} — {len(res['skills'])} skills")
        for s in res["skills"]:
            secs = s["sections"].items() if isinstance(s["sections"], dict) else [(k, "") for k in s["sections"]]
            print(f"  {s['id']:<26} {s['kind']:<9} {s['title'][:60]}   [{', '.join(f'{k}:{v}' if v != '' else k for k, v in secs)}]")
        return 0
    if a.arg is None:
        print(f"library {a.action}: give {'words' if a.action == 'search' else 'an id' if a.action == 'show' else 'a DXF file'}", file=sys.stderr)
        return 2
    if a.action == "search":
        res = ks.call("search_library", {"queries": [a.arg], "categories": a.category, "topics": a.topic, "limit": a.limit})
        for h in res.get("hits", []):
            print(f"{h['id']}  [{h['category']}/{h.get('topic')}; {h.get('review')}; {h.get('status')}]  {h['title']}\n    {h['text']}")
        print(f"{res.get('count', 0)} hit(s)")
        return 0
    if a.action == "show":
        if lib.skill(a.arg) is not None:
            res = ks.call("load_skill", {"id": a.arg, **({"sections": a.section} if a.section else {})})
            print(f"# {res['title']}  ({res['kind']}; {res['trust']})")
            for k, text in res["sections"].items():
                print(f"\n## {k}\n{text}")
            if res["not_included"]:
                print("\nnot shown (use --section): " + ", ".join(f"{n['section']} ({n['chars']} chars)" for n in res["not_included"]))
            return 0
        print(json.dumps(ks.call("get_reference", {"id": a.arg}), indent=1, ensure_ascii=False))
        return 0
    from .crossview import SheetModel

    sm = SheetModel.open(a.arg)
    texts = L.drawing_texts(sm.dr.items)
    found = lib.discover(texts, top=5)
    print(f"{len(texts)} printed notes read; {len(lib.match_labels(texts))} vocabulary label match(es)")
    for m in found:
        print(f"  {m['skill']:<22} score {m['score']:>6}  {'STRUCTURE label printed' if m['strong'] else 'parts only'}: "
              + ", ".join(dict.fromkeys(b['printed'] for b in m['because'])))
    if not found:
        print("  no skill's cues match this drawing's printed words: the agent works from the drawing alone (the recipes still apply)")
    return 0


def _production(a) -> int:
    """`production …`: the aagento-bridge rule engines as this project uses them — bundled, extracted into knowledge, checked for freshness."""
    from .production import build as PB
    from .production import manifest as PM
    from .production.bridge import RuleBridge, default_bridge

    if a.action == "build":
        try:
            info = PB.build()
        except PB.BuildError as exc:
            print(f"build failed: {exc}", file=sys.stderr)
            return 2
        print(f"built {PB.cache_dir() / PB.BUNDLE} from aagento-bridge {info['aagento_bridge']['commit'][:10]}"
              f"{' (DIRTY: ' + ', '.join(info['aagento_bridge']['dirty_files'][:3]) + ')' if info['aagento_bridge']['dirty_files'] else ''}; "
              f"{len(info['sources'])} source files fingerprinted, {len(info['families'])} families")
        return 0
    if a.action == "extract":
        from .production import extract as PE

        idx = PE.extract_all(a.family or None, br=RuleBridge(), render=not a.no_render)
        for f in idx["families"]:
            print(f"  {f['family']:<24} {f['parameters']:>4} params {f['outputs']:>5} outputs {f['formulas_verified']:>3} formulas verified "
                  f"{f['views']:>3} views  {'units authored' if f['overlay'] else ''}")
        print(f"wrote {PE.knowledge_dir() / 'index.json'}")
        return 0
    pk = PM.knowledge()
    if a.action == "status":
        st = default_bridge().status()
        print(f"knowledge: {pk.dir} ({len(pk.family_keys())} families, extracted from aagento-bridge {(pk.index['source'].get('commit') or '?')[:10]})")
        print(f"bridge: {'runs here' if st['available'] else 'unavailable — ' + st['reason']}")
        for key in pk.family_keys():
            fam = pk.family(key)
            if not fam.supported:
                print(f"  {key:<24} no rule engine")
                continue
            fr = pk.freshness(key)
            extra = f" changed: {', '.join(fr.get('changed_files', [])[:2])}" if fr.get("changed_files") else ""
            print(f"  {key:<24} knowledge {fr['state']:<12} checkout {fr['checkout']:<7} bundle {fr['bundle']}{extra}")
        return 0
    if a.action == "families":
        for f in pk.index["families"]:
            print(f"  {f['family']:<24} {f['title']:<32} compute {'yes' if f['has_compute'] else 'no ':<3} validate {'yes' if f['has_validate'] else 'no ':<3} "
                  f"{f['formulas_verified']:>3} formulas verified")
        return 0
    if a.action == "show":
        if not a.arg:
            print("production show FAMILY [--section parameters|outputs|views|operations|validation|findings]", file=sys.stderr)
            return 2
        from .ai.production import ProductionSession

        ses = ProductionSession(pk, bench=None)
        print(json.dumps(ses._production_knowledge(a.arg, sections=a.section or None, query=a.query or "", limit=a.limit), indent=1, ensure_ascii=False, default=str))
        return 0
    if a.action == "discover":
        from .ai import library as L
        from .crossview import SheetModel

        sm = SheetModel.open(a.arg)
        for m in pk.discover(L.drawing_texts(sm.dr.items)):
            print(f"  {m['family']:<24} score {m['score']:>6}  {'(close call) ' if m.get('close_call') else ''}words: {', '.join(m['matched_words'])}")
        return 0
    if a.action == "bench":
        from .production import bench as PBn

        rep = PBn.run(out_path=a.out)
        print(PBn.table(rep))
        print(f"wrote {a.out}")
        return 0 if rep["summary"]["false_acceptances"] == 0 else 1
    return 2


def _fidelity(a) -> int:
    reports = {}
    worst = 0
    for path in a.dxf:
        dr, _ = read_dxf(path)
        cov = dr.coverage
        reports[path] = cov
        e = cov["entities"]
        print(f"{Path(path).name}: {e['visible_in_file']} visible entities, {e['read']} read, {e['hidden']} hidden (off / frozen layers), "
              f"{e['not_read']} not read · {e['inserts_expanded']} block references expanded, depth {e['block_depth']} · "
              f"{'FAITHFUL' if cov['faithful'] else 'NOT FAITHFUL'}")
        print(f"  {'type':<14}{'in file':>8}{'read':>7}{'drawn':>7}{'editable':>9}{'hidden':>8}{'not read':>9}  export")
        for r in cov["types"]:
            print(f"  {r['type']:<14}{r['in_file']:>8}{r['read']:>7}{r['drawn']:>7}{r['editable']:>9}{r['hidden']:>8}{r['not_read']:>9}  {r['export']}")
        if cov["compound_parts"]:
            print("  drawn through their parts: " + ", ".join(f"{k} ×{v}" for k, v in sorted(cov["compound_parts"].items())))
        lts = ", ".join(f"{k} ({v['entities']}, {v['drawn_as']})" for k, v in cov["linetypes"].items())
        print(f"  linetypes: {lts}")
        if cov["hatch_patterns"]:
            print("  hatches: " + ", ".join(f"{k} ×{v['count']} → {'/'.join(v['drawn_as'])}" for k, v in cov["hatch_patterns"].items()))
        for prob in cov["problems"]:
            print(f"  ! {prob}")
        worst = max(worst, 0 if cov["faithful"] else 1)
    if a.json:
        Path(a.json).write_text(json.dumps(reports, indent=1, default=str))
        print(f"wrote {a.json}")
    return worst


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
    p = sub.add_parser("fidelity", help="what the DXF holds and what of it is read, drawn, editable and exported — by type, with the handles of "
                                        "anything visible that is not drawn (no model, no cost)")
    p.add_argument("dxf", nargs="+")
    p.add_argument("--json", default=None, help="write the full coverage reports here")
    p = sub.add_parser("rescale", help="redraw one view at another drafting ratio (1:25 → 1:50): its geometry about its own origin, its dimensions "
                                       "showing the same real sizes, text and symbols at their paper size, its title's ratio rewritten; nothing else changes")
    p.add_argument("dxf")
    p.add_argument("--view", required=True, help="the view's id (V01 …, as the page and inspect_sheet list them)")
    p.add_argument("--to", type=float, required=True, help="the new ratio n of 1:n")
    p.add_argument("--from", dest="old", type=float, default=None, help="the ratio it is drawn at now (default: what its own title states)")
    p.add_argument("--out", required=True)
    p = sub.add_parser("bench")
    p.add_argument("fixtures", nargs="?", default="fixtures/library")
    p.add_argument("--domain", choices=["bridge"], default=None)
    p = sub.add_parser("serve")
    p.add_argument("dxf", nargs="?")
    p.add_argument("--domain", choices=["bridge"], default=None)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--answer", default=None, help="open with a saved Gemini answer (validated again, no AI call)")
    p.add_argument("--project", default=None, help="open the workspace with a saved parametric project (.autoparam.json)")
    p.add_argument("--fresh", action="store_true", help="start from the drawing as drawn: the work saved for it is kept aside under a dated name, not opened")
    p.add_argument("--no-autosave", action="store_true", help="do not keep the work on disk while it is made (and do not open saved work)")
    p.add_argument("--state-dir", default=None, help="where the work is kept (default ~/.local/state/dxf-autoparam, or $DXF_AUTOPARAM_STATE)")
    p = sub.add_parser("library", help="the engineering library the agent retrieves from (read-only, no model, no cost)")
    p.add_argument("action", choices=["list", "search", "show", "discover"])
    p.add_argument("arg", nargs="?", default=None, help="search: words · show: a skill id or a record id · discover: a DXF")
    p.add_argument("--domain", default="bridge")
    p.add_argument("--section", action="append", default=[], help="show a skill: this section (repeat); default the working set")
    p.add_argument("--category", action="append", default=[], help="search: B reference, C vocabulary, D proposed or disputed, E operational")
    p.add_argument("--topic", action="append", default=[], help="search: formula, rule, component, level_chain, conflict …")
    p.add_argument("--limit", type=int, default=12)
    p = sub.add_parser("production", help="the production bridge rule engines: bundle, knowledge, freshness, benchmark (no model, no cost)")
    p.add_argument("action", choices=["build", "extract", "status", "families", "show", "discover", "bench"])
    p.add_argument("arg", nargs="?", default=None, help="show: a family · discover: a DXF")
    p.add_argument("--family", action="append", default=[], help="extract: only these families (repeat)")
    p.add_argument("--no-render", action="store_true", help="extract: skip the headless view renders (faster; no view effects)")
    p.add_argument("--section", action="append", default=[], help="show: summary, parameters, outputs, views, operations, validation, findings")
    p.add_argument("--query", default="", help="show: words to filter by")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--out", default="production_bench.json")
    p = sub.add_parser("plan-bench", help="free, no AI: instruction-guided assembly edits on generated drawings with known intent, scored")
    p.add_argument("--out", default="plan_bench.json")
    p = sub.add_parser("agent-eval", help="score the agent per category (reading, parts, values, anchor, plan, geometry …) on a drawing whose intended result is known")
    p.add_argument("--live", action="store_true", help="run the REAL model (billed): needs --yes-spend; without it the limits are printed and nothing starts")
    p.add_argument("--yes-spend", action="store_true", help="the owner's explicit go-ahead for the paid calls of --live")
    p.add_argument("--free", metavar="MODEL", default=None,
                   help="run the case on a FREE Token Harbor model (an id from tools/tokenharbor_check.py): refused unless the catalogue prices both input "
                        "and output at zero, so it never costs anything")
    p.add_argument("--soft-turns", type=int, default=30)
    p.add_argument("--max-turns", type=int, default=60)
    p.add_argument("--max-tokens", type=int, default=250000)
    p.add_argument("--wall-minutes", type=float, default=20.0)
    p.add_argument("--instruction", default=None, help="a file with the instruction (default: the brief's own example)")
    p.add_argument("--out", default="agent_eval.json")
    a = ap.parse_args(argv)

    if a.cmd == "library":
        return _library(a)
    if a.cmd == "production":
        return _production(a)
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
    if a.cmd == "agent-eval":
        from .ai import acceptance as acc
        from .ai.loop import Budget

        budget = Budget.from_env(soft_turns=a.soft_turns, max_turns=a.max_turns, max_tokens=a.max_tokens, wall_s=a.wall_minutes * 60)
        text = Path(a.instruction).read_text() if a.instruction else acc.INSTRUCTION
        report: dict = {"instruction": text}
        if a.free:
            from .ai import gateway, tokenharbor

            gid = a.free.removeprefix(tokenharbor.PREFIX)
            m = next((x for x in tokenharbor.catalog() if x["id"] == gid), None) if tokenharbor.key() else None
            if m is None or not tokenharbor.is_free(m):
                print(f"Not started: {a.free} is not a free Token Harbor model now (no key, not in the catalogue, or priced) — nothing was sent.")
                return 3
            print(f"FREE model acceptance run on {gid} (Token Harbor prices it at zero). Limits:", json.dumps(acc.live_limits(budget)))
            ent = tokenharbor.entry(m)
            gw = gateway.Gateway(gateway.GatewayConfig(model=gid, thinking=ent["thinking"], provider="tokenharbor", price=ent["price"]))
            try:
                case = acc.make_case(instruction=text)
                res = acc.evaluate(gw, case, budget={k: v for k, v in budget.to_dict().items() if k in ("soft_turns", "max_turns", "max_tokens", "wall_s")},
                                   timeout_s=a.wall_minutes * 60)
            finally:
                gw.close()
            report["free"] = {"model": gid, "scores": res["scores"], "usage": res["run"]["usage"], "status": res["run"]["status"], "seconds": res["seconds"]}
            print(acc.table(res["scores"]))
            print("usage:", json.dumps(res["run"]["usage"]))
        elif a.live:
            print("LIVE acceptance run — the real model, billed. Limits:", json.dumps(acc.live_limits(budget)))
            if not a.yes_spend:
                print("Not started: pass --yes-spend to give the go-ahead for these paid calls.")
                return 3
            from .ai.vertex import Gemini

            case = acc.make_case(instruction=text)
            res = acc.evaluate(Gemini(), case, budget={k: v for k, v in budget.to_dict().items() if k in ("soft_turns", "max_turns", "max_tokens", "wall_s")}, timeout_s=a.wall_minutes * 60)
            report["live"] = {"scores": res["scores"], "usage": res["run"]["usage"], "status": res["run"]["status"], "seconds": res["seconds"]}
            print(acc.table(res["scores"]))
            print("usage:", json.dumps(res["run"]["usage"]))
        else:
            print("OFFLINE: scripted models of different care on the generated two-view box (no model, no cost). The live run uses the same scorer.\n")
            for style in ("careful", "careless", "wrong_part"):
                case = acc.make_case(instruction=text)
                res = acc.evaluate(acc.script_for(case, style), case, log=lambda *x: None)
                report[style] = res["scores"]
                print(f"[{style}]\n{acc.table(res['scores'])}\n")
        Path(a.out).write_text(json.dumps(report, indent=1, default=str))
        print(f"wrote {a.out}")
        return 0
    if a.cmd == "fidelity":
        return _fidelity(a)
    if a.cmd == "rescale":
        from .crossview import SheetModel
        from .rescale import rescale_view

        rep = rescale_view(SheetModel.open(a.dxf), a.view, a.to, a.out, a.old)
        print(json.dumps(rep, indent=1))
        return 0 if not rep["not_rescaled"] else 2
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

        serve(a.dxf, a.domain, port=a.port, answer=a.answer, project=a.project, autosave=not a.no_autosave, fresh=a.fresh, state_dir=a.state_dir)
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
