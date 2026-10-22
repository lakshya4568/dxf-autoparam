"""What a person meets in the Values panel, measured on a COPY of saved work: every value stepped, every side choice tried. Read-only.

    cp ~/.local/state/dxf-autoparam/<drawing>-<hash>.autoparam.json out/agent-logs/<run>/copy.autoparam.json     # the copy (the server may keep running)
    uv run python tools/sweep_sides.py "<drawing>.dxf" out/agent-logs/<run>/copy.autoparam.json [--from-drawn] [--only NAME …] [--out FILE.jsonl]

For every value the sheet lists (shared ones once):

  * steps — the value changed as the page's spinner does (±10 % and ±10 mm; a level ±0.1 m, a count ±1) and the whole sheet regenerated: accepted or
    refused, with the engine's reason;
  * sides (lengths only) — each choice under the value (its start stays · centred · its end stays: `SheetModel.anchor`, what the chooser calls), each
    undone afterwards. A refusal must leave the sheet as it was; one that does not is reported (`mutated_on_refusal`).

Then a summary: steps accepted, side choices accepted per unit, and the refusals counted by cause. `--from-drawn` sets the person's values aside first
(every value as drawn). Nothing is written but `--out`; no server is started and no model is called. On a large sheet it takes minutes (each side
choice is a plan built and checked on the whole sheet).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
import traceback

from dxf_autoparam.crossview import SheetError, SheetModel

# the engine's own refusal wording → a cause, for counting (the first that matches)
CAUSES = [("no line at the middle", "centre: no drawn line at the middle"), ("may give", "held line in the push, every gap on the way held"),
          ("is set by a site level", "held line in the push"), ("would no longer drive", "a shared value would stop driving in another view"),
          ("crosses", "members would cross"), ("clash", "members would cross"), ("disagree on the anchor", "one side per axis per assembly"),
          ("would be lost", "a person's value would be dropped"), ("both axes", "the size lies on both axes"),
          ("is worked out there", "the size does not drive (worked out)"), ("not measured between two lines", "not a distance between two lines"),
          ("binding", "another size's binding lost"), ("unrelated", "an unrelated part moves"), ("connection", "a connection torn"),
          ("set by a person's or t", "a person's / the AI's formula line in the push"), ("nothing on this axis stays", "nothing on the axis stays"),
          ("driver", "the size stops measuring what it named"), ("crash", "crash")]


def cause(why: str) -> str:
    return next((label for key, label in CAUSES if key in why), "other: " + why[:90])


def kind_of(sm: SheetModel, name: str) -> tuple[str, str]:
    """(kind, a unit it is set in) of a value as the page names it."""
    shared = sm._shared_by_name().get(name)
    if shared:
        b = next((b for b in shared.bindings if b.status == "drives"), shared.bindings[0])
        prm = sm.unit(b.unit).prog.params.get(b.param)
        return (prm.kind if prm else "?"), b.unit
    uid, local = name.split(".", 1)
    prm = sm.unit(uid).prog.params.get(local)
    return (prm.kind if prm else "?"), uid


def steps(kind: str, v: float) -> list[float]:
    if kind == "level":
        return [v + 0.1, v - 0.1]
    if kind == "count":
        return [v + 1, v - 1]
    return [v * 1.1, v * 0.9, v + 10.0, v - 10.0]


def try_side(sm: SheetModel, name: str, uid: str, mode: str) -> dict:
    """One side choice, measured and undone: the sheet goes back to exactly where it was, accepted or not."""
    st, rev, depth, fut, live = sm._state(), sm.revision, len(sm.history), list(sm.future), sm._live
    before = {u: (x.answer or {}).get("datum_formulas") for u, x in sm.units.items()}
    t = time.time()
    try:
        res = sm.anchor(name, uid, mode)
        return {"ok": True, "mode_now": res.get("mode"), "s": round(time.time() - t, 1)}
    except SheetError as exc:
        after = {u: (x.answer or {}).get("datum_formulas") for u, x in sm.units.items()}
        return {"ok": False, "why": str(exc)[:900], "s": round(time.time() - t, 1),
                "mutated_on_refusal": [u for u in before if before[u] != after.get(u)] or None, "revision_moved": sm.revision != rev}
    except Exception as exc:  # noqa: BLE001 — one choice's boundary: a crash is a finding, recorded with where it happened, and the sweep goes on
        return {"ok": False, "crash": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1200:]}
    finally:
        sm._restore(st)
        del sm.history[depth:]
        sm.future, sm.revision, sm._live = fut, rev, live
        for x in sm.units.values():
            x.prog = None  # built again from the answer it has, when something asks


def summary(rows: list[dict]) -> list[str]:
    n = sum(len(r["steps"]) for r in rows)
    ok = sum(s["ok"] for r in rows for s in r["steps"])
    out = [f"value steps: {ok} of {n} accepted over {len(rows)} values"]
    causes: collections.Counter = collections.Counter()
    per_unit: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    mutated = []
    for r in rows:
        for m, a in (r.get("sides") or {}).items():
            per_unit[r["unit"]][1] += 1
            if a.get("ok"):
                per_unit[r["unit"]][0] += 1
                continue
            causes[cause(a.get("why") or a.get("crash") or "")] += 1
            if a.get("mutated_on_refusal") or a.get("revision_moved"):
                mutated.append(f"{r['name']} {m}")
    tried = sum(t for _a, t in per_unit.values())
    taken = sum(a for a, _t in per_unit.values())
    out.append(f"side choices: {taken} of {tried} accepted, {tried - taken} refused")
    out += [f"  {v:>4}  {k}" for k, v in causes.most_common()]
    out.append("per unit (accepted / tried): " + ", ".join(f"{u} {a}/{t}" for u, (a, t) in sorted(per_unit.items())))
    out.append(f"refusals that changed the sheet: {', '.join(mutated) if mutated else 'none'}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dxf")
    ap.add_argument("project", help="a COPY of the saved work (*.autoparam.json)")
    ap.add_argument("--from-drawn", action="store_true", help="set the person's values aside first: every value as drawn")
    ap.add_argument("--only", nargs="*", default=[], help="these values only (as the page names them: U01.Width, or a shared name)")
    ap.add_argument("--out", help="write one JSON line per value here")
    a = ap.parse_args()
    t0 = time.time()
    sm = SheetModel.load(a.project, dxf=a.dxf)
    if a.from_drawn:
        sm.values = {}
    cur = sm.current()
    print(f"loaded in {time.time() - t0:.1f} s · {len(cur)} values", flush=True)
    rows = []
    for name, v in sorted(cur.items()):
        if a.only and name not in a.only:
            continue
        kind, uid = kind_of(sm, name)
        row: dict = {"name": name, "kind": kind, "unit": uid, "value": v, "steps": []}
        for w in steps(kind, v):
            t = time.time()
            r = sm.regenerate({name: w})
            row["steps"].append({"to": round(w, 4), "ok": r.ok, "errors": r.errors[:6], "n_errors": len(r.errors), "s": round(time.time() - t, 2)})
        if kind == "length":
            row["sides"] = {mode: try_side(sm, name, uid, mode) for mode in ("start", "centre", "end")}
        rows.append(row)
        took = sum(s["ok"] for s in row["steps"])
        sides = " ".join(f"{m}:{'ok' if x.get('ok') else 'NO'}" for m, x in row.get("sides", {}).items())
        print(f"{name:<40} {kind:<7} steps ok {took}/{len(row['steps'])}  {sides}  ({time.time() - t0:.0f} s)", flush=True)
    if a.out:
        with open(a.out, "w") as f:
            f.writelines(json.dumps(r, default=str) + "\n" for r in rows)
    print("\n".join(summary(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
