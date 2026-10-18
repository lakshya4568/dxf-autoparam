"""Watch an agent run on a RUNNING workspace server and write down everything, read-only (it never starts, stops or changes anything).

    uv run python tools/monitor_run.py [--url http://127.0.0.1:8790] [--out out/agent-logs] [--every 1.0]

Run it from the project folder (the model-call ledger path is relative). Leave it running while you use the page; Ctrl+C ends it.
Each session writes a folder `out/agent-logs/<time>/`:

  run.log          the readable story, one line per fact: the instruction and scope, every turn, the model's own thinking summary,
                   every tool call with its arguments and the engine's answer, what the engine applied to the sheet, questions to
                   you, errors, state changes, a status line every 30 s, and each paid model call (tokens, cache, seconds, cost)
  events.jsonl     the engine's events exactly as it emitted them (for later analysis)
  sheet.log        the sheet as it changes: revision, parametrized units, named values (added / changed / removed)
  system_prompt.txt  the agent's standing instructions and its tool names, as this checkout would send them to the model
  images/          every picture the model was given (whole-sheet view, unit pictures, zooms)
  summary-R*.md    written at the end of each run: outcome, criteria, values applied, cost, how parametric the sheet is now

What it cannot show: the full text of the request body sent to the model (the engine does not expose it over HTTP). What the model
was given is visible through its parts: the instruction + scope below, the system prompt snapshot, and every tool result it read.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ACTIVE = {"queued", "running", "stopping"}


def get(url: str, path: str, timeout: float = 15.0):
    with urllib.request.urlopen(url + path, timeout=timeout) as r:
        return json.loads(r.read())


def clip(v, n: int = 700) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + f"… (+{len(s) - n} chars)"


class Log:
    def __init__(self, folder: Path):
        self.folder = folder
        self.run = open(folder / "run.log", "a", buffering=1)  # noqa: SIM115 — held for the whole session
        self.events = open(folder / "events.jsonl", "a", buffering=1)  # noqa: SIM115
        self.sheet = open(folder / "sheet.log", "a", buffering=1)  # noqa: SIM115
        self.t0 = time.time()

    def line(self, text: str, tag: str = "", file=None, echo: bool = True) -> None:
        now = time.strftime("%H:%M:%S")
        rows = str(text).splitlines() or [""]
        out = f"{now} {tag:<9}{rows[0]}" + "".join(f"\n{'':<18}{r}" for r in rows[1:])
        (file or self.run).write(out + "\n")
        if echo:
            print(out, flush=True)


def snapshot_sheet(url: str) -> dict:
    s = get(url, "/api/sheet")
    return {
        "file": s.get("file"), "revision": s.get("revision"), "entities": s.get("entities"), "values": dict(s.get("values") or {}),
        "units": {u["id"]: {"parametrized": u["parametrized"], "params": u["params"], "views": u["views"]} for u in s.get("units", [])},
        "can_undo": s.get("can_undo"),
    }


def sheet_table(snap: dict) -> str:
    rows = [f"  {uid:<8} {('parametrized, ' + str(u['params']) + ' values') if u['parametrized'] else 'not parametrized':<34} views {', '.join(u['views'])}" for uid, u in snap["units"].items()]
    done = sum(1 for u in snap["units"].values() if u["parametrized"])
    return f"{snap['file']} · revision {snap['revision']} · {snap['entities']} entities · {done}/{len(snap['units'])} units parametrized · {len(snap['values'])} named values\n" + "\n".join(rows)


def diff_sheet(a: dict, b: dict) -> list[str]:
    out = []
    if a["revision"] != b["revision"]:
        out.append(f"revision {a['revision']} → {b['revision']}")
    for k in sorted(set(a["values"]) | set(b["values"])):
        if k not in a["values"]:
            out.append(f"+ value {k} = {b['values'][k]}")
        elif k not in b["values"]:
            out.append(f"- value {k} (was {a['values'][k]})")
        elif a["values"][k] != b["values"][k]:
            out.append(f"~ value {k}: {a['values'][k]} → {b['values'][k]}")
    for uid in sorted(set(a["units"]) | set(b["units"])):
        ua, ub = a["units"].get(uid), b["units"].get(uid)
        if ua != ub:
            out.append(f"unit {uid}: {('parametrized ' + str(ua['params']) if ua and ua['parametrized'] else 'not parametrized')} → "
                       f"{('parametrized ' + str(ub['params']) if ub and ub['parametrized'] else 'not parametrized' if ub else 'gone')}")
    return out


def event_lines(e: dict, log: Log, verbose_results: int) -> None:
    k = e.get("kind")
    tag = f"[{e.get('run', '?')} +{e.get('t', 0):>6.1f}s]"
    if k == "run_start":
        log.line(f"RUN START — instruction:\n{e.get('instruction')}\nscope: {json.dumps(e.get('scope'), default=str)}\nbudget: {json.dumps(e.get('budget'), default=str)}", tag)
    elif k == "user":
        log.line(f"YOU (follow-up): {e.get('text') or '(answers only)'}  answers={json.dumps(e.get('answers') or {}, ensure_ascii=False)}", tag)
    elif k == "stage":
        log.line(f"stage: {e.get('text')}", tag)
    elif k == "turn":
        log.line(f"TURN {e.get('turn')} begins ({e.get('turns_left', {}).get('in_chunk', '?')} turns left in this chunk)", tag)
    elif k == "call":
        log.line(f"model call · {e.get('model', '?')} · thinking {e.get('thinking', '?')} · prompt cache {e.get('prompt_cache', '?')}{' · replayed from cache' if e.get('cached') else ''}", tag)
    elif k == "thought":
        log.line(f"THINKING SUMMARY (the model's own, shortened by the API): {clip(e.get('text', ''), 1200)}", tag)
    elif k == "retry":
        log.line(f"RETRY — {e.get('why')}", tag)
    elif k == "tool_start":
        log.line(f"→ {e.get('name')}  [{e.get('doing')}] {('unit ' + e['unit']) if e.get('unit') else ''}\n  args: {clip(e.get('args_full', e.get('args')), 900)}", tag)
    elif k == "tool":
        mark = "✓" if e.get("ok") else "✗ FAILED"
        said = f"\n  model said: “{e['said']}”" if e.get("said") else ""
        why = f"\n  refused because: {e['why']}" if not e.get("ok") and e.get("why") else ""
        log.line(f"{mark} {e.get('name')}  {e.get('ms', 0)} ms{said}\n  engine: {e.get('summary') or '(no summary)'}{why}\n  result: {clip(e.get('result'), verbose_results)}", tag)
    elif k == "applied":
        log.line(f"APPLIED TO THE SHEET — {json.dumps({x: e[x] for x in e if x not in ('kind', 'seq', 'run', 't')}, ensure_ascii=False, default=str)}", tag)
    elif k == "image":
        log.line(f"picture {e.get('id')} given to the model ({e.get('state')}, revision {e.get('revision')}, views {e.get('views')})", tag)
    elif k == "state":
        log.line(f"STATE {e.get('from')} → {e.get('to')} — {e.get('reason') or e.get('label')}", tag)
    elif k == "question":
        log.line(f"QUESTION FOR YOU: {clip(e.get('text'), 600)}  options={e.get('options')}  suggested={e.get('recommended')}", tag)
    elif k == "error":
        log.line(f"ERROR: {e.get('text')}", tag)
    elif k == "note":
        log.line(f"note: {e.get('text')}", tag)
    elif k == "budget":
        log.line(f"budget: {e.get('turns')} turns · {e.get('tool_calls')} tool calls · {e.get('tokens')} tokens · {e.get('seconds')} s — {e.get('reason')}", tag)
    elif k == "status":
        log.line(f"status: {clip({x: e[x] for x in e if x not in ('kind', 'seq', 'run', 't')}, 300)}", tag, echo=False)
    elif k == "verdict":
        log.line(f"VERDICT: {e.get('state')} (ended by {e.get('ended_by')})", tag)
    else:
        log.line(f"{k}: {clip(e, 300)}", tag, echo=False)


def write_summary(folder: Path, rid: str, p: dict, before: dict, after: dict, usage_rows: list[dict], t_start: float) -> None:
    v = p.get("verdict") or {}
    u = p.get("usage") or {}
    cost = [r.get("cost_usd") for r in usage_rows if r.get("cost_usd") is not None]
    lines = [
        f"# Run {rid}", "", f"- **Instruction:** {p.get('instruction')}", f"- **Scope:** {json.dumps(p.get('scope'), default=str)}",
        f"- **Outcome:** {p.get('status')} — {v.get('headline') or p.get('reason') or ''}",
        f"- **Effort:** {u.get('turns', 0)} turns · {u.get('tool_calls', 0)} tool calls · {u.get('tokens', 0):,} output+thinking tokens · {p.get('elapsed', 0):.0f} s",
        f"- **Model calls this run:** {len(usage_rows)} · input {sum(r.get('input_tokens', 0) for r in usage_rows):,} (cached {sum(r.get('vertex_cached_tokens', 0) for r in usage_rows):,}) · "
        f"output {sum(r.get('output_tokens', 0) for r in usage_rows):,} · thinking {sum(r.get('thinking_tokens', 0) for r in usage_rows):,}"
        + (f" · reported cost ${sum(cost):.4f}" if cost else " · cost not reported by the provider (see the price table in the page's Cost tab)"),
        "", "## What the engine's gate checked", "",
    ]
    for c in v.get("criteria") or []:
        lines.append(f"- {'✓' if c.get('ok') else '✗'} {c.get('id')}: {c.get('detail')}")
    if v.get("values_applied"):
        lines += ["", "## Values applied", ""] + [f"- {x.get('name')} = {x.get('value')}" for x in v["values_applied"]]
    if v.get("finish_summary"):
        lines += ["", "## What the model says it did", "", str(v["finish_summary"])]
    lines += ["", "## The sheet", "", "Before:", "```", sheet_table(before), "```", "After:", "```", sheet_table(after), "```", "Changes:", ""]
    lines += [f"- {d}" for d in diff_sheet(before, after)] or ["- none"]
    (folder / f"summary-{rid}.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8790")
    ap.add_argument("--out", default="out/agent-logs")
    ap.add_argument("--every", type=float, default=1.0)
    ap.add_argument("--result-chars", type=int, default=900, help="how much of each tool result to write in run.log (events.jsonl has it whole)")
    a = ap.parse_args()
    url = a.url.rstrip("/")
    folder = Path(a.out) / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    log = Log(folder)

    try:
        sheet0 = snapshot_sheet(url)
    except (urllib.error.URLError, OSError) as exc:
        print(f"cannot reach {url}: {exc}", file=sys.stderr)
        return 1
    log.line(f"monitoring {url} → {folder}\n{sheet_table(sheet0)}", "START")
    log.line(sheet_table(sheet0), "SHEET", file=log.sheet, echo=False)

    try:  # the agent's standing instructions, as this checkout sends them (read from the code, not from the server)
        from dxf_autoparam.ai.run import unified_system, unified_tools

        names = [fd.name for t in unified_tools(None) for fd in (t.function_declarations or [])]
        (folder / "system_prompt.txt").write_text(unified_system(None) + "\n\n=== TOOLS ===\n" + "\n".join(names) + "\n")
        log.line(f"system prompt + {len(names)} tool names saved to system_prompt.txt", "START")
    except Exception as exc:  # noqa: BLE001 — a snapshot is a convenience, never a reason to stop watching
        log.line(f"system prompt snapshot skipped: {exc}", "START")

    from dxf_autoparam.ai import vertex

    ledger = vertex.CACHE / "usage.jsonl"
    ledger_pos = ledger.stat().st_size if ledger.exists() else 0
    cursors: dict[str, int] = {}
    seen_status: dict[str, str] = {}
    run_usage: dict[str, list[dict]] = {}
    run_before: dict[str, dict] = {}
    last_sheet = sheet0
    last_beat = 0.0
    current_run = None
    done_runs: set[str] = set()
    try:
        while True:
            try:
                runs = get(url, "/api/sheet/ai/runs").get("runs", [])
                for r in reversed(runs):
                    rid = r["id"]
                    if rid in done_runs and r["status"] not in ACTIVE:
                        continue
                    if rid not in cursors:
                        cursors[rid] = 0
                        run_before[rid] = last_sheet
                        run_usage[rid] = []
                    try:
                        p = get(url, f"/api/sheet/ai/progress?run={rid}&since={cursors[rid]}")
                    except urllib.error.HTTPError:
                        done_runs.add(rid)  # a run saved with the project, not live in this session
                        continue
                    for e in p.get("events", []):
                        log.events.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
                        event_lines(e, log, a.result_chars)
                    cursors[rid] = p.get("next", cursors[rid])
                    for im in p.get("images", []):  # every picture the model was given, saved so you can see what it saw
                        dest = folder / "images" / f"{rid}-{im['id']}.png"
                        if not dest.exists():
                            try:
                                dest.parent.mkdir(exist_ok=True)
                                with urllib.request.urlopen(f"{url}/api/sheet/ai/image?run={rid}&id={im['id']}", timeout=15) as resp:
                                    dest.write_bytes(resp.read())
                                log.line(f"picture {im['id']} saved → {dest} ({im.get('size')}, views {im.get('views')}, revision {im.get('revision')})", "IMAGE")
                            except (urllib.error.URLError, OSError):
                                pass
                    if p["status"] != seen_status.get(rid):
                        seen_status[rid] = p["status"]
                    if p["status"] in ACTIVE:
                        current_run = rid
                    elif rid not in done_runs and p["status"] in ("completed", "partial", "failed", "stopped", "exhausted", "paused", "awaiting_user"):
                        # a stretch of work ended (it may be continued later): write what is true now
                        after = snapshot_sheet(url)
                        write_summary(folder, rid, p, run_before[rid], after, run_usage[rid], log.t0)
                        log.line(f"run {rid} is {p['status']} — {(p.get('verdict') or {}).get('headline') or p.get('reason') or ''}\n{sheet_table(after)}\n(written: summary-{rid}.md)", "END")
                        if p["status"] in ("completed", "partial", "failed", "stopped"):
                            done_runs.add(rid)
                        else:  # paused / awaiting / exhausted: it can go on, so keep following it
                            seen_status[rid] = p["status"]
                            run_before[rid] = after
                # the sheet, as it changes
                now_sheet = snapshot_sheet(url)
                changes = diff_sheet(last_sheet, now_sheet)
                if changes:
                    log.line("\n".join(changes), "SHEET", file=log.sheet)
                    log.line("sheet changed: " + "; ".join(changes[:6]) + (f" (+{len(changes) - 6} more, see sheet.log)" if len(changes) > 6 else ""), "SHEET", echo=True)
                    last_sheet = now_sheet
                # every paid model call, from the usage ledger
                if ledger.exists() and ledger.stat().st_size > ledger_pos:
                    with open(ledger) as fh:
                        fh.seek(ledger_pos)
                        chunk = fh.read()
                        ledger_pos = fh.tell()
                    for ln in chunk.splitlines():
                        try:
                            row = json.loads(ln)
                        except ValueError:
                            continue
                        if current_run:
                            run_usage.setdefault(current_run, []).append(row)
                        log.line(f"MODEL CALL {row.get('label')} · {row.get('model')} · in {row.get('input_tokens')} (cached {row.get('vertex_cached_tokens')}) · out {row.get('output_tokens')} · "
                                 f"thinking {row.get('thinking_tokens')} · {row.get('seconds')} s · cost {row.get('cost_usd')} · finish {row.get('finish')}", "$")
                # a heartbeat every 30 s while something runs
                if current_run and time.time() - last_beat > 30:
                    last_beat = time.time()
                    p = get(url, f"/api/sheet/ai/progress?run={current_run}&since=999999")
                    if p["status"] in ACTIVE:
                        u = p.get("usage") or {}
                        calls = run_usage.get(current_run, [])
                        done = sum(1 for x in last_sheet["units"].values() if x["parametrized"])
                        log.line(f"{current_run} {p['status']} · stage {p.get('stage')} · turn {u.get('turns')} · {u.get('tool_calls')} tool calls · {len(calls)} model calls · "
                                 f"in {sum(c.get('input_tokens', 0) for c in calls):,} out {sum(c.get('output_tokens', 0) for c in calls):,} tokens · "
                                 f"{done}/{len(last_sheet['units'])} units parametrized", "STATUS")
            except (urllib.error.URLError, OSError, ValueError) as exc:
                log.line(f"server not answering ({exc}); retrying", "WARN")
                time.sleep(3)
            time.sleep(a.every)
    except KeyboardInterrupt:
        log.line("monitor stopped", "END")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
