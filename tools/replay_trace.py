"""Replay a recorded live run's model turns through the CURRENT engine — free, no network — and say what the engine makes of them.

    uv run python tools/replay_trace.py ../final-output/live-gad-run/run1 [--cache .cache/ai] [--then more_turns.json] [--out DIR]

The run directory is the one `live_run.py` wrote (gad.dxf, instruction.txt, usage_ledger.jsonl, project.json). The model's turns come from the client's
answer cache (the ledger names the key of each), so they are the model's real calls. With the engine of the time the replay reproduces the run (same
parametrization); after an engine change it shows what changed: a call now refused, a promise now checked, a verdict now different.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from dxf_autoparam.ai.scripted import RecordedModel, call
from dxf_autoparam.workspace import SheetSession

ap = argparse.ArgumentParser()
ap.add_argument("run_dir")
ap.add_argument("--cache", default=".cache/ai")
ap.add_argument("--then", default=None, help="a JSON file of scripted turns that follow the recorded ones")
ap.add_argument("--out", default=None, help="write the replayed run's progress and project here")
a = ap.parse_args()
d = Path(a.run_dir)
then = [[call(c["tool"], **c.get("args", {})) for c in turn] for turn in json.loads(Path(a.then).read_text())] if a.then else None
model = RecordedModel.from_ledger(str(d / "usage_ledger.jsonl"), a.cache, then=then)
sheet = SheetSession(str(d / "gad.dxf"))
sheet.gem = model
instruction = (d / "instruction.txt").read_text().strip()
rid = sheet.start_run({"instruction": instruction, "scope": {"kind": "drawing"}, "options": {"budget": {"soft_turns": 10_000, "max_turns": 10_000}}})["run"]
run = sheet.runs[rid]
t0 = time.time()
while run.status in ("queued", "running", "stopping") and time.time() - t0 < 900:
    time.sleep(0.2)
p = run.progress(0)
print(f"replayed {len(model.recorded)} recorded turns -> {p['status']}: {p['reason']}")
v = p["verdict"] or {}
for c in v.get("criteria", []):
    print(f"  {'OK ' if c['ok'] else 'NO '} {c['id']}: {c['detail'][:230]}")
for key in ("notes", "given_up"):
    for n in v.get(key, []) or []:
        print(f"  {key}: {n if isinstance(n, str) else json.dumps(n)[:230]}")
plan = v.get("plan") or {}
if plan.get("stated"):
    print(f"  plan: {len(plan['links'])} link(s), {len(plan['assumptions'])} assumption(s); holds: {sum(1 for x in plan['links'] if x['holds'])}/{len(plan['links'])}")
refused = [e for e in p["events"] if e["kind"] == "tool" and not e.get("ok") and not e.get("waiting")]
print(f"refused calls in the replay: {len(refused)}")
for e in refused:
    print(f"   - {e['name']} @{e.get('unit')}: {str(e.get('why'))[:200]}")
if (d / "project.json").exists():
    old = json.loads((d / "project.json").read_text())
    new = sheet.sm.to_dict()
    same = {uid: (old["answers"].get(uid) == new["answers"].get(uid)) for uid in set(old["answers"]) | set(new["answers"])}
    print("parametrization identical to the recorded run, per unit:", same)
    print("shared values now:", sorted(q["name"] for q in new["shared"]), "| recorded:", sorted(q["name"] for q in old["shared"]))
if a.out:
    o = Path(a.out)
    o.mkdir(parents=True, exist_ok=True)
    (o / "progress.json").write_text(json.dumps(p, indent=1, default=str))
    (o / "project.json").write_text(json.dumps(sheet.sm.to_dict(), indent=1, default=list))
