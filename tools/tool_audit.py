"""How good each tool's answer was in a run: per tool, how often it was called, refused or failed, how much the model had to read from it
(characters, pictures), how long it took, and how often the same call was made again (a sign its answer was lost or not understood).

    uv run python -I tools/tool_audit.py out/agent-logs/<run>/events_R1.json            # a saved /api/sheet/ai/progress answer
    uv run python -I tools/tool_audit.py out/agent-logs/<run>/events.jsonl              # what tools/monitor_run.py wrote
    uv run python -I tools/tool_audit.py --url http://127.0.0.1:8765 --run R1           # the live server, read-only
    … [--requests out/agent-logs/<run>/requests_R1.json]                                # with /api/sheet/ai/requests?brief=1: what each turn re-sent

`result_chars` is what the engine recorded for the model (pictures excluded); older runs did not record it — their size is that of the shortened
copy kept for the page, marked `~`. Read-only: nothing is called but the server's GET routes.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import urllib.request


def events_of(args) -> list[dict]:
    if args.url:
        with urllib.request.urlopen(f"{args.url.rstrip('/')}/api/sheet/ai/progress?run={args.run}&since=0", timeout=30) as r:  # a local URL the person gives
            return json.loads(r.read())["events"]
    with open(args.events, encoding="utf-8") as f:
        text = f.read()
    if args.events.endswith(".jsonl"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)["events"]


def audit(events: list[dict]) -> list[dict]:
    rows: dict[str, dict] = {}
    seen: collections.Counter = collections.Counter()
    for e in events:
        if e.get("kind") != "tool":
            continue
        r = rows.setdefault(e["name"], {"tool": e["name"], "calls": 0, "failed": 0, "chars": [], "approx": False, "pictures": 0, "ms": 0, "repeats": 0})
        r["calls"] += 1
        r["failed"] += 0 if e.get("ok") else 1
        if "result_chars" in e:
            r["chars"].append(e["result_chars"])
        else:
            r["chars"].append(len(json.dumps(e.get("result"), default=str)))
            r["approx"] = True
        r["pictures"] += len(e.get("images") or [])
        r["ms"] += int(e.get("ms") or 0)
        key = (e["name"], json.dumps({k: v for k, v in (e.get("args_full") or {}).items() if k != "why"}, sort_keys=True, default=str), e.get("unit"))
        seen[key] += 1
        if seen[key] > 1:
            r["repeats"] += 1
    return sorted(rows.values(), key=lambda r: -sum(r["chars"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("events", nargs="?", help="a saved progress answer (.json) or a monitor's events.jsonl")
    ap.add_argument("--url", help="a running server, read-only")
    ap.add_argument("--run", default="R1")
    ap.add_argument("--requests", help="a saved /api/sheet/ai/requests?brief=1 answer: the turns' sizes")
    args = ap.parse_args()
    if not (args.events or args.url):
        ap.error("give the events file or --url")
    rows = audit(events_of(args))
    print(f"{'tool':26} {'calls':>5} {'failed':>6} {'repeats':>7} {'chars/call':>11} {'max':>8} {'pictures':>8} {'s':>6}")
    for r in rows:
        avg = sum(r["chars"]) // max(1, len(r["chars"]))
        mark = "~" if r["approx"] else " "
        print(f"{r['tool']:26} {r['calls']:5} {r['failed']:6} {r['repeats']:7} {mark}{avg:10} {max(r['chars'], default=0):8} {r['pictures']:8} {r['ms'] / 1000:6.1f}")
    if args.requests:
        with open(args.requests, encoding="utf-8") as f:
            reqs = json.load(f)["requests"]
        big = sorted(reqs, key=lambda q: -q["totals"]["tokens_est"])[:5]
        print("\nthe largest requests (turn, contents, characters, pictures, tokens billed, share cached):")
        for q in big:
            us = q.get("usage") or {}
            print(f"  turn {q['turn']:3}  {q['totals']['contents']:3}  {q['totals']['chars']:9}  {q['totals']['images']:2}  {us.get('input_tokens', 0):8}  {us.get('cached_share', 0):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
