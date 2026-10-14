"""Command-line interface. Every command is a thin call to agentctx.api.Context; output is JSON.

    .venv/bin/python agent-context/ctx.py build
    .venv/bin/python agent-context/ctx.py status 21cc08a32dd8-p1
    .venv/bin/python agent-context/ctx.py search "weep hole" --category B C
    .venv/bin/python agent-context/ctx.py evidence 21cc08a32dd8-p1#D1
    .venv/bin/python agent-context/ctx.py pack 21cc08a32dd8-p1 --task dimension_binding
    .venv/bin/python agent-context/ctx.py validate agent-context/packs/pack-XXXX.json
    .venv/bin/python agent-context/ctx.py check
    .venv/bin/python agent-context/ctx.py demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .api import Context
from .packs import PackError
from .store import RegistryMissing


def _print(value: Any) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _ctx(args: argparse.Namespace) -> Context:
    return Context(root=args.root) if getattr(args, "root", None) else Context()


def cmd_build(args: argparse.Namespace) -> int:
    summary = _ctx(args).build_registry()
    _print({"built": summary["context_dir"], "counts": summary["counts"], "problems": summary["problems"]})
    return 1 if summary["problems"] else 0


def cmd_status(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    result = {rid: ctx.get_source_status(rid) for rid in args.record_ids}
    _print(result if len(result) > 1 else next(iter(result.values())))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    if args.observations:
        hits = ctx.search_observations(" ".join(args.query), owner=args.owner, limit=args.limit)
    else:
        hits = ctx.search_knowledge(" ".join(args.query), categories=set(args.category or []) or None,
                                    topics=set(args.topic or []) or None, include_sources=args.sources,
                                    limit=args.limit)
    _print(hits)
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    result = _ctx(args).get_evidence(args.evidence_id, live=args.live)
    _print(result)
    return 0 if result.get("found") else 1


def cmd_pack(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    scope = json.loads(args.scope) if args.scope else None
    pack = ctx.build_evidence_pack(args.record_id, args.task, scope=scope, cad_snapshot=args.cad_snapshot,
                                   write=not args.no_write, out_dir=args.out)
    if args.print:
        _print(pack)
    else:
        _print({"pack_id": pack["pack_id"], "task": pack["task"]["name"], "record_id": args.record_id,
                "completeness": pack["completeness"]["status"], "claims": len(pack["claims"]),
                "candidates": len(pack.get("candidate_interpretations", [])),
                "live_cad_binding": pack["live_cad_binding"]["status"], "summary": pack["agent_summary"],
                "written_to": None if args.no_write else f"agent-context/packs/{pack['pack_id']}.json"})
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    target = Path(args.target)
    if not target.exists():
        target = ctx.context_dir / "packs" / (args.target if args.target.endswith(".json") else f"{args.target}.json")
    report = ctx.validate_evidence_pack(target)
    _print(report)
    return 0 if report["valid"] else 1


def cmd_check(args: argparse.Namespace) -> int:
    report = _ctx(args).check()
    _print(report)
    return 1 if report["registry_stale"] or report["packs_stale"] else 0


def cmd_tasks(args: argparse.Namespace) -> int:
    _print(_ctx(args).tasks())
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from .demo import run_demo

    _print(run_demo(_ctx(args)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ctx.py", description="agentctx: derived context over the GAD repository.")
    parser.add_argument("--root", help="repository root (default: the repository this package sits in)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build", help="rebuild the registry, knowledge index and reports").set_defaults(func=cmd_build)

    p = sub.add_parser("status", help="source status: completeness, eligibility, issues, staleness")
    p.add_argument("record_ids", nargs="+")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("search", help="search knowledge (or observations with --observations)")
    p.add_argument("query", nargs="+")
    p.add_argument("--category", nargs="*", choices=list("ABCDE"))
    p.add_argument("--topic", nargs="*")
    p.add_argument("--sources", action="store_true", help="also search source records")
    p.add_argument("--observations", action="store_true", help="search stored observations instead")
    p.add_argument("--owner", help="with --observations: only this record")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("evidence", help="resolve one evidence id")
    p.add_argument("evidence_id")
    p.add_argument("--live", action="store_true", help="also read the item from the source file now")
    p.set_defaults(func=cmd_evidence)

    p = sub.add_parser("pack", help="build an evidence pack for one record and task")
    p.add_argument("record_id")
    p.add_argument("--task", required=True, choices=["source_evidence", "component_interpretation",
                                                     "dimension_binding", "geometric_relationships"])
    p.add_argument("--scope", help='JSON, e.g. \'{"dimension_ids": ["D1"]}\'')
    p.add_argument("--cad-snapshot", help="optional runtime CAD snapshot (JSON); never required")
    p.add_argument("--out", help="folder for the pack file (default agent-context/packs)")
    p.add_argument("--no-write", action="store_true", help="do not write a file")
    p.add_argument("--print", action="store_true", help="print the whole pack")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("validate", help="validate a pack file or a pack id in agent-context/packs")
    p.add_argument("target")
    p.set_defaults(func=cmd_validate)

    sub.add_parser("check", help="stale inputs, stale packs, broken paths (reports only)").set_defaults(func=cmd_check)
    sub.add_parser("tasks", help="list the pack tasks").set_defaults(func=cmd_tasks)
    sub.add_parser("demo", help="write demonstration packs for real records").set_defaults(func=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except RegistryMissing as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    except PackError as exc:
        sys.stderr.write(f"pack error: {exc}\n")
        return 2
