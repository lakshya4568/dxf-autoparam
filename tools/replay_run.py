"""Make a sheet again from a recorded agent run — no model, no network, no cost.

    uv run python tools/replay_run.py "/path/to/drawing.dxf" run/events.jsonl --out restored.autoparam.json

The engine is deterministic: the same tool calls, in the same order, on the same DXF, make the same sheet. The model's own answers of a live run
are kept whole in the client's answer cache (.cache/ai/, found through the usage ledger: one line per call, with the key), so the sheet the run
made can be made again without asking the model anything, and saved as a project (.autoparam.json) that `dxf-autoparam serve --project` opens.
The run's event log (the monitor's events.jsonl) is only the yardstick: every replayed call is compared with what the live run recorded for it
(same tool, same success or refusal), and the end revision and verdict with the run's own. The tool says so when anything differs.
(The event log cannot be the source: it bounds long lists and strings for the page, so a big batch of items is not whole in it.)

The replayed run keeps the model's recorded thoughts, marked as replayed: nothing shown from it is new.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from google.genai import types

from dxf_autoparam.ai.run import ACTIVE
from dxf_autoparam.ai.scripted import RecordedModel
from dxf_autoparam.workspace import SheetSession

BUDGET_KEYS = ("soft_turns", "unit_turns", "max_turns", "max_tool_calls", "wall_s", "max_tokens", "call_s")
THOUGHT_CHARS = 1500


def read_events(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a line cut short by a crash is not an event
    return out


def recorded_turns(ledger: Path, cache: Path, n_turns: int) -> list[types.Content]:
    """The model's answers of the run that made `n_turns` calls: the ledger's last block of `turn 1 … turn n`, each read whole from the cache."""
    blocks: list[list[dict]] = []
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        label = str(row.get("label", ""))
        if label == "turn 1":
            blocks.append([])
        if label.startswith("turn ") and blocks:
            blocks[-1].append(row)
    block = next((b for b in reversed(blocks) if len(b) == n_turns), None)
    if block is None:
        raise SystemExit(f"the ledger has no run of {n_turns} turns (blocks of turns found: {[len(b) for b in blocks]})")
    turns = []
    for row in block:
        f = cache / f"{row['key']}.json"
        if row.get("error") or row.get("stopped") or not f.exists():
            raise SystemExit(f"the answer of {row['label']} is not on disk ({f.name}): the run cannot be replayed whole")
        turns.append(types.Content.model_validate(json.loads(f.read_text())["content"]))
    return turns


def thought_of(turn: types.Content) -> str:
    return next((p.text for p in turn.parts or [] if getattr(p, "thought", False) and p.text), "") or ""


def replay(dxf: str, events: list[dict], ledger: Path, cache: Path, quiet: bool = False) -> tuple[SheetSession, dict]:
    start = next((e for e in events if e["kind"] == "run_start"), None)
    if start is None:
        raise SystemExit("no run_start event: this is not a run's event log")
    recorded = [(e["name"], bool(e.get("ok"))) for e in events if e["kind"] == "tool"]
    turns = recorded_turns(ledger, cache, sum(1 for e in events if e["kind"] == "turn"))

    sheet = SheetSession(dxf)

    def model() -> RecordedModel:
        m = RecordedModel(turns)
        m.thoughts = ["[replayed from the recorded run] " + thought_of(t)[:THOUGHT_CHARS] for t in turns]
        return m

    sheet.gem_factory = model
    sheet.gem_per_run = True
    budget = {k: v for k, v in (start.get("budget") or {}).items() if k in BUDGET_KEYS}
    budget.setdefault("unit_turns", 0)  # a run recorded before there was a unit budget was never told one: the replay is not either
    sheet.start_run({"instruction": start["instruction"], "scope": start.get("scope"), "options": {"budget": budget}})
    run = sheet.runs[sheet.current_run]
    t0 = time.time()
    while run.status in ACTIVE or (run.thread is not None and run.thread.is_alive()):
        if not quiet:
            n = len([e for e in run.events if e["kind"] == "tool"])
            print(f"\r  replaying… {n}/{len(recorded)} calls, {time.time() - t0:0.0f}s", end="", file=sys.stderr, flush=True)
        time.sleep(0.5)
    if not quiet:
        print(file=sys.stderr)

    replayed = [(e["name"], bool(e.get("ok"))) for e in run.events if e["kind"] == "tool"]
    differ = [(i, r, p) for i, (r, p) in enumerate(zip(recorded, replayed, strict=False)) if r != p]
    last = next((e for e in reversed(events) if e["kind"] == "status" and e.get("sheet_revision") is not None), None)
    report = {
        "status": run.status, "calls": {"recorded": len(recorded), "replayed": len(replayed)}, "calls_that_differ": differ[:10],
        "revision": {"recorded": last["sheet_revision"] if last else None, "replayed": sheet.sm.revision},
        "recorded_verdict": next((e["state"] for e in reversed(events) if e["kind"] == "verdict"), None),
        "replayed_verdict": (run.verdict or {}).get("state"),
        "error": run.error,
    }
    report["same"] = (not differ and len(recorded) == len(replayed) and report["revision"]["recorded"] == report["revision"]["replayed"]
                      and report["recorded_verdict"] == report["replayed_verdict"])
    return sheet, report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dxf")
    ap.add_argument("events", help="the run's events.jsonl (one JSON event per line): the yardstick, and where the instruction and scope come from")
    ap.add_argument("--ledger", default=".cache/ai/usage.jsonl")
    ap.add_argument("--cache", default=".cache/ai")
    ap.add_argument("--out", help="where to write the project (.autoparam.json)")
    ap.add_argument("--keep", action="store_true", help="also keep it where `dxf-autoparam serve` looks for the work on this drawing (the autosave), so serving the drawing opens it")
    a = ap.parse_args()
    sheet, report = replay(a.dxf, read_events(Path(a.events)), Path(a.ledger), Path(a.cache))
    print(json.dumps(report, indent=1, default=str))
    if (a.out or a.keep) and not report["same"]:
        print("NOT written: the replay differs from the recorded run (see above)")
    elif a.out or a.keep:
        text = json.dumps(sheet.sm.to_dict(), indent=1, default=list)
        if a.out:
            Path(a.out).write_text(text)
            print("project written:", a.out)
        if a.keep:
            from dxf_autoparam import autosave

            target = autosave.project_path(a.dxf)
            autosave.write_atomic(target, text)
            print("kept as the autosave of this drawing:", target)
    sys.exit(0 if report["same"] else 2)


if __name__ == "__main__":
    main()
