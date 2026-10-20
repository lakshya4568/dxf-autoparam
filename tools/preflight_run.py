"""Everything to check before a PAID live run of the agent — read-only. It starts no server, calls no model, and changes nothing but the copies it is asked for.

    uv run python tools/preflight_run.py [--url http://127.0.0.1:8765] [--save out/agent-logs/<run>]

Prints PASS / WARN / FAIL / INFO per check and exits 1 when any check FAILS (do not start the run until it does not). With --save DIR it also writes there
`preflight.txt` (this output), `code-state.txt` (the commit and the uncommitted files the run will be judged against) and `before.autoparam.json` (a copy of the
sheet's saved work as it is now). Checked: the server answers and runs the code that is on disk (it was started after the newest source edit), a drawing is open
and no run is going, the autosave is written and owned by this server, the model / thinking / budget the run will use and whether the model has a price,
Google credentials work, nothing heavy (tests, builds) competes for the machine, and where the cost ledger stands. NOT checked here: the test suite — run it first.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LINES: list[tuple[str, str]] = []


def say(level: str, text: str) -> None:
    LINES.append((level, text))
    print(f"{level:5s} {text}", flush=True)


def get(url: str, path: str, timeout: float = 10.0):
    with urllib.request.urlopen(url + path, timeout=timeout) as r:
        return json.loads(r.read())


def newest_source_mtime() -> float:
    return max((p.stat().st_mtime for p in (ROOT / "src" / "dxf_autoparam").rglob("*.py")), default=0.0)


def run(*cmd: str, timeout: float = 20.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, cwd=ROOT)


def server_pid(port: int) -> int | None:
    try:
        out = run("lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t").stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    return int(out[0]) if out else None


def process_started(pid: int) -> float | None:
    try:
        text = run("ps", "-o", "lstart=", "-p", str(pid)).stdout.strip()
        return time.mktime(time.strptime(text, "%a %b %d %H:%M:%S %Y")) if text else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def adc_ok() -> tuple[bool, str]:
    """Whether Google application-default credentials give a token (the token itself is never read into the output)."""
    try:
        r = run("gcloud", "auth", "application-default", "print-access-token", timeout=40)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"gcloud could not be run: {type(exc).__name__}"
    return r.returncode == 0 and bool(r.stdout.strip()), "" if r.returncode == 0 else "run `gcloud auth application-default login`"


def vertex_config():
    from dxf_autoparam.ai import vertex

    return vertex.config()


def check_server(url: str) -> dict | None:
    try:
        summary = get(url, "/api/sheet")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        say("FAIL", f"no server answers at {url} ({exc}): start it from your terminal — `uv run dxf-autoparam serve \"<drawing>.dxf\"` (add --fresh for a raw drawing)")
        return None
    port = urlparse(url).port or 80
    pid = server_pid(port)
    started = process_started(pid) if pid else None
    if started is None:
        say("WARN", "the server answers, but its process could not be found: that it runs the code on disk is NOT VERIFIED")
    else:
        newest = newest_source_mtime()
        when = time.strftime("%a %H:%M:%S", time.localtime(started))
        if newest > started:
            say("FAIL", f"the server (pid {pid}, started {when}) is OLDER than the newest source edit ({time.strftime('%a %H:%M:%S', time.localtime(newest))}): restart it, or the "
                        "run is paid for on old code")
        else:
            say("PASS", f"the server (pid {pid}) was started {when}, after the newest source edit: it runs the code on disk")
    if summary.get("empty"):
        say("FAIL", "no drawing is open in the page: open the drawing first")
        return None
    units = summary.get("units", [])
    done = [u["id"] for u in units if u.get("parametrized")]
    say("PASS", f"open: {summary.get('file')} — revision {summary.get('revision')}, {len(units)} units")
    if done:
        say("INFO", f"{len(done)} unit(s) already carry work ({', '.join(done[:8])}{'…' if len(done) > 8 else ''}): the agent sees it. For a run on the raw drawing restart the "
                    "server with --fresh (the saved work is kept aside under a dated name)")
    else:
        say("PASS", "no unit carries work: this is a run on the drawing as drawn")
    if summary.get("ai_running"):
        say("FAIL", "an agent run is going already")
    return summary


def check_autosave(url: str, save: Path | None) -> None:
    try:
        a = get(url, "/api/sheet/autosave")
    except (urllib.error.URLError, OSError, ValueError):
        say("WARN", "the autosave could not be read")
        return
    if a is None:
        say("FAIL", "autosave is off (--no-autosave): the run's work would not be kept on disk")
        return
    if a.get("owner"):
        say("FAIL", f"another server keeps this drawing's saved work ({a['owner']}): this one writes nothing — stop the other one")
    elif a.get("error"):
        say("FAIL", f"the autosave is failing: {a['error']}")
    elif a.get("saved_revision") is not None and a.get("saved_revision") != a.get("revision"):
        say("WARN", f"unsaved changes (saved revision {a['saved_revision']}, sheet at {a['revision']}): wait a couple of seconds and run this again")
    else:
        say("PASS", f"autosave is written and owned by this server ({a.get('path')})")
    path = a.get("path")
    if save is not None and path and Path(path).exists():
        save.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, save / "before.autoparam.json")
        say("PASS", f"the saved work is copied to {save / 'before.autoparam.json'}")
    elif save is not None:
        say("INFO", "there is no saved file yet (nothing was changed since the drawing was opened): nothing to copy")


def check_model() -> None:
    from dxf_autoparam.ai import usage

    try:
        cfg = vertex_config()
    except RuntimeError as exc:
        say("FAIL", f"no model configuration: {exc}")
        return
    budget = {k: os.environ[k] for k in ("AUTOPARAM_SOFT_TURNS", "AUTOPARAM_UNIT_TURNS", "VERTEX_AGENT_MAX_STEPS", "VERTEX_AGENT_STEP_THINKING") if os.environ.get(k)}
    say("PASS", f"model {cfg.model} @{cfg.thinking} (fallback {cfg.fallback_model} @{cfg.fallback_thinking}), explicit cache {'on' if cfg.explicit_cache else 'off'}")
    say("INFO", "budget from the environment: " + (", ".join(f"{k}={v}" for k, v in budget.items()) or "the defaults (a chunk of 30 turns, 12 per unit; the page can change them per run)"))
    if os.environ.get("AUTOPARAM_AGENT_ADAPTIVE_THINKING"):
        say("WARN", "AUTOPARAM_AGENT_ADAPTIVE_THINKING is set: levels that change between turns cost the provider's cache (a measured run kept about half of its prompt cached)")
    if usage.prices().get(cfg.model):
        say("PASS", f"{cfg.model} has a price: the run's cost can be worked out")
    else:
        say("WARN", f"{cfg.model} has no price (VERTEX_PRICES): the ledger and the monitor will show tokens and no amount — set it from your billing page to see the cost")


def check_machine() -> None:
    ok, why = adc_ok()
    say("PASS" if ok else "FAIL", "Google credentials give a token" if ok else f"Google credentials do not work: {why}")
    ps = run("ps", "-A", "-o", "pid=,command=").stdout.splitlines()
    heavy = [ln.strip()[:90] for ln in ps if any(k in ln for k in ("pytest", "ng test", "vite build", "e2e/workspace.e2e", "e2e/agent.e2e")) and "preflight_run" not in ln]
    if heavy:
        say("WARN", "something heavy is running and competes with the run (and a starved headless browser or test fails): " + " | ".join(heavy[:3]))
    else:
        say("PASS", "no test run or build is competing for the machine")
    monitors = [ln.strip()[:90] for ln in ps if "monitor_run.py" in ln and "grep" not in ln]
    say("INFO", "a monitor is already running: " + monitors[0] if monitors else "no monitor is running yet: start it before the run (tools/monitor_run.py)")


def check_ledger() -> None:
    ledger = ROOT / ".cache" / "ai" / "usage.jsonl"
    n = sum(1 for _ in ledger.open()) if ledger.exists() else 0
    say("INFO", f"the cost ledger has {n} lines now ({ledger}): the run's model calls are the lines after these")


def code_state() -> str:
    head = run("git", "rev-parse", "--short", "HEAD").stdout.strip()
    branch = run("git", "branch", "--show-current").stdout.strip()
    status = run("git", "status", "--short").stdout.strip()
    stat = run("git", "diff", "--stat").stdout.strip().splitlines()[-1:] or [""]
    return f"branch {branch} at {head}\n{len(status.splitlines())} changed or new files ({stat[0].strip()})\n\n{status}\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--save", default=None, help="a folder (out/agent-logs/<run>) for preflight.txt, code-state.txt and a copy of the saved work")
    a = ap.parse_args(argv)
    save = Path(a.save) if a.save else None
    state = code_state()
    say("INFO", state.splitlines()[0] + " — " + state.splitlines()[1])
    if check_server(a.url) is not None:
        check_autosave(a.url, save)
    check_model()
    check_machine()
    check_ledger()
    fails = [t for lv, t in LINES if lv == "FAIL"]
    say("INFO", "NOT checked here: the test suite (run `uv run pytest tests` first) and the person's go-ahead for the cost")
    say("FAIL" if fails else "PASS", f"{len(fails)} check(s) failed: do not start the run" if fails else "ready: every check passed (read the WARN lines)")
    if save is not None:
        save.mkdir(parents=True, exist_ok=True)
        (save / "preflight.txt").write_text("\n".join(f"{lv:5s} {t}" for lv, t in LINES) + "\n")
        (save / "code-state.txt").write_text(state)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
