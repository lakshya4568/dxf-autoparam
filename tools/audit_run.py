"""Audit what an agent run left on a sheet: how parametric is it, really? Read-only, on a COPY of the saved project — never the live server.

    cp ~/.local/state/dxf-autoparam/<drawing>-<hash>.autoparam.json out/agent-logs/<run>/after.autoparam.json     # the copy (the server may keep running)
    uv run python tools/audit_run.py "<drawing>.dxf" out/agent-logs/<run>/after.autoparam.json [--sweep] [--out out/agent-logs/<run>/audit.md]

Everything printed is MEASURED on the engine's model of the saved work (nothing is taken from what the agent said):

  * per unit: parts (existing / kept as drawn), named inputs, levels held, sizes the analysis measured and nobody named, findings;
  * how many of the unit's dimensions a named value drives, and which sizes nothing changes (they stay as drawn whatever the inputs become);
  * which side of each size stays when it changes (design intent): decided by evidence, assumed, or undecided and why;
  * occurrences the agent asked for and the engine could not make follow; names that look generated; parameters the validator refused;
  * with --sweep: every named length changed by ±10 % and the whole sheet checked (interfaces, annotations, held parts, validity …) — the failures a
    change introduces, beyond those the sheet already has with no change at all (minutes on a big sheet; it never writes anything).

It does not start a server, call a model, or write anywhere but --out.
"""

from __future__ import annotations

import argparse
import collections
import sys
import time
from pathlib import Path

from dxf_autoparam import design_intent
from dxf_autoparam.behaviour import behaviour_report
from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.generic import is_generated
from dxf_autoparam.status import dimension_drive


def unit_audit(sm: SheetModel, uid: str) -> dict:
    u = sm.units[uid]
    answer = u.answer or {}
    row: dict = {"unit": uid, "views": u.views, "answered": bool(answer), "dropped": u.dropped}
    if not answer:
        return row
    unit = sm.unit(uid)
    prog, rep = unit.prog, unit.report
    assert prog is not None
    inputs = {n: p for n, p in prog.params.items() if p.source == "ai"}
    asked = [r.get("name") for r in answer.get("parameters", [])]
    parts = answer.get("components", [])
    leaves = [c for c in parts if not any(q.get("parent") == c.get("name") for q in parts)]
    levels = collections.Counter(lv.get("role") for lv in answer.get("levels", []))
    findings = (rep.findings if rep is not None else [])
    errors = [f for f in findings if f.severity == "error"]
    row.update(
        parts=len(leaves), existing=sum(1 for c in leaves if c.get("existing")), kept=sum(1 for c in leaves if c.get("parametrize") is False),
        asked=len(asked), inputs=len([n for n, p in inputs.items() if p.kind != "level"]), refused=sorted(set(asked) - set(prog.params)),
        levels=dict(levels), relations=len(prog.relations),
        measured_unnamed=sum(1 for n, p in prog.params.items() if p.source != "ai" and is_generated(n)),
        generated_names=sorted(n for n in inputs if is_generated(n)),
        errors=[f"{f.code} {f.item}: {f.message}"[:180] for f in errors][:6], warnings=sum(1 for f in findings if f.severity == "warn"),
        dimensions=dimension_drive(prog),
        axes=answer.get("intent_axes"),
        settled=answer.get("settled") or [],
        dropped_occurrences=[f"{r.get('name')}: asked {len(r['occurrences_asked'])}, following {len(r.get('occurrences') or [])}"
                             for r in answer.get("parameters", []) if r.get("occurrences_asked")],
    )
    return row


def sweep(sm: SheetModel, rows: list[dict]) -> list[dict]:
    """±10 % of every named length, the whole sheet checked, minus what fails with the value as it is."""
    out = []
    cur = sm.current()
    seen: set[str] = set()
    for r in rows:
        if not r.get("answered"):
            continue
        prog = sm.unit(r["unit"]).prog
        assert prog is not None
        for name, p in prog.params.items():
            if p.source != "ai" or p.kind != "length" or not p.measures:
                continue
            key = sm._key(r["unit"], name)
            if key in seen or not isinstance(cur.get(key), (int, float)) or not cur[key]:
                continue
            seen.add(key)

            def fails(value: float, key=key) -> collections.Counter:
                c: collections.Counter = collections.Counter()
                rep = behaviour_report(sm, {key: float(value)})
                for cat, cv in rep["categories"].items():
                    c[cat] += sum(1 for i in cv.get("items", []) if i["status"] == "fail")
                return c

            base = fails(cur[key])
            worse: dict[str, int] = {}
            for f in (1.1, 0.9):
                got = fails(cur[key] * f)
                for cat, n in got.items():
                    if n > base[cat]:
                        worse[cat] = max(worse.get(cat, 0), n - base[cat])
            out.append({"key": key, "baseline": sum(base.values()), "worse": worse})
    return out


def render(sm: SheetModel, rows: list[dict], swept: list[dict] | None) -> str:
    L: list[str] = [f"# Audit of {Path(sm.path).name} — project revision {sm.revision}", ""]
    for run in sm.runs[-3:]:
        v = run.get("verdict") or {}
        L.append(f"- run {run.get('id')}: {run.get('status')} — {v.get('headline') or run.get('reason') or ''}")
    L += ["", "## Per unit", "", "| unit | views | parts (existing/kept) | named inputs | levels | measured, unnamed | errors | dimensions driven | intent (decided / assumed / undecided) |",
          "|---|---|---|---|---|---|---|---|---|"]
    tot = collections.Counter()
    for r in rows:
        if not r["answered"]:
            L.append(f"| {r['unit']} | {'+'.join(r['views'])} | — nobody parametrized this unit — | | | | | | |")
            continue
        d = r["dimensions"]
        ax = collections.Counter(a.get("status") for a in (r["axes"] or []))
        tot.update({"total": d["total"] - d["unread"], "driven": d["driven"], "constant": d["constant"], "decided": ax["decided"] + ax["person"], "assumed": ax["provisional"],
                    "undecided": ax["undecided"], "inputs": r["inputs"]})
        lv = ", ".join(f"{n} {k}" for k, n in sorted(r["levels"].items(), key=lambda kv: str(kv[0]))) or "—"
        L.append(f"| {r['unit']} | {'+'.join(r['views'])} | {r['parts']} ({r['existing']}/{r['kept']}) | {r['inputs']} of {r['asked']} asked | {lv} | {r['measured_unnamed']} | "
                 f"{len(r['errors'])} | {d['driven']} of {d['total'] - d['unread']} | {ax['decided'] + ax['person']} / {ax['provisional']} / {ax['undecided']}"
                 f"{'' if r['axes'] is not None else ' (never derived)'} |")
    summary = (f"**Sheet: {tot['driven']} of {tot['total']} dimensions are driven by a named value; {tot['constant']} stay as drawn whatever the inputs become. "
               f"{tot['inputs']} named inputs. Growth direction: {tot['decided']} decided by evidence or a person, {tot['assumed']} assumed, {tot['undecided']} undecided.**")
    L += ["", summary, ""]
    for r in rows:
        if not r["answered"]:
            continue
        notes: list[str] = []
        if r["refused"]:
            notes.append(f"refused by the validator (not inputs now): {', '.join(r['refused'])}")
        if r["generated_names"]:
            notes.append(f"named like a generated placeholder: {', '.join(r['generated_names'])}")
        if r["dropped_occurrences"]:
            notes.append("occurrences asked for and not followed: " + "; ".join(r["dropped_occurrences"]))
        d = r["dimensions"]
        if d["constant"]:
            notes.append(f"{d['constant']} dimensions no named value changes, e.g. " + ", ".join(f"{c['mm']:g}" + (f" ({c['text']})" if c["text"] else "") for c in d["constants"]))
        if d["unsteppable"]:
            notes.append(f"values the program could not step: {', '.join(d['unsteppable'])}")
        for a in r["axes"] or []:
            if a.get("status") in ("undecided", "provisional"):
                notes.append(f"{a['axis']} axis {a['status']}: {design_intent.sentence(a)}"[:330])
        notes += [f"ERROR {e}" for e in r["errors"]]
        if r["settled"]:
            notes.append(f"settled by a person: {len(r['settled'])}")
        if notes:
            L += [f"### {r['unit']}", ""] + [f"- {n}" for n in notes] + [""]
    if swept is not None:
        bad = [s for s in swept if s["worse"]]
        L += ["## Sweep: every named length at ±10 %", "", f"{len(swept)} named lengths checked; {len(bad)} introduce failures the sheet does not already have.", ""]
        L += [f"- {s['key']}: " + ", ".join(f"{cat} +{n}" for cat, n in sorted(s["worse"].items())) + f" (the sheet already had {s['baseline']} with no change)" for s in bad]
        L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dxf")
    ap.add_argument("project", help="a COPY of the saved .autoparam.json")
    ap.add_argument("--sweep", action="store_true", help="change every named length by ±10 %% and check the whole sheet (slow)")
    ap.add_argument("--out", default=None, help="also write the report here")
    a = ap.parse_args(argv)
    sm = SheetModel.load(a.project, dxf=a.dxf)
    t = time.perf_counter()
    rows = [unit_audit(sm, uid) for uid in sm.units]
    swept = sweep(sm, rows) if a.sweep else None
    text = render(sm, rows, swept) + f"\n_(measured in {time.perf_counter() - t:.0f} s)_\n"
    sys.stdout.write(text)
    if a.out:
        Path(a.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
