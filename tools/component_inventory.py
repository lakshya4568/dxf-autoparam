"""Every part of every unit of a saved sheet, classified by what its own dimensions measure — read-only, on a COPY of the saved work.

    uv run python tools/component_inventory.py "<drawing>.dxf" <copy of the autosave> [--domain bridge] [--out FILE.md]

Per part: what the drawing's labels call it, the library component it matches (with --domain), its dimensions (coverage.py: driven by a named value /
unnamed / fixed / kept / unread) and a status:

  parametrized     every dimension on it is driven by a value somebody named
  partial          some are
  unparametrized   it has dimensions and none is driven
  no dimension     no dimension of the drawing measures it (what it has, if anything, comes from named sizes the agent bound to its lines)

and, per unit, the dimensions on no part. Measured on the engine's model of the saved work; nothing is taken from what an agent said. No model, no server,
nothing written but --out."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dxf_autoparam.ai import labels as L
from dxf_autoparam.coverage import unit_coverage
from dxf_autoparam.crossview import SheetModel


def classify(entry: dict | None) -> str:
    if not entry or not entry.get("total"):
        return "no dimension"
    if entry.get("driven", 0) == entry["total"] - entry.get("unread", 0) - entry.get("kept", 0):
        return "parametrized"
    return "partial" if entry.get("driven") else "unparametrized"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dxf")
    ap.add_argument("project")
    ap.add_argument("--domain", default=None, help="match parts to the domain library's components (e.g. bridge)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    sm = SheetModel.load(a.project, dxf=a.dxf)
    lib = None
    if a.domain:
        from dxf_autoparam.ai import library

        lib = library.open_domain(a.domain)
    lines = [f"# Component inventory — {Path(a.dxf).name} (revision {sm.revision})", "",
             "| unit | part | type | the drawing labels it | library component | dimensions (driven / total) | status | named values on it |",
             "|---|---|---|---|---|---|---|---|"]
    totals = {"parametrized": 0, "partial": 0, "unparametrized": 0, "no dimension": 0}
    loose_lines = []
    for uid, u in sm.units.items():
        if not u.answer:
            continue
        unit = sm.unit(uid)
        prog = unit.prog
        if prog is None:
            continue
        cov = unit_coverage(prog, kept=set((unit.answer or {}).get("kept_dimensions") or {}))
        parts = prog.intent.get("parts") or {}
        parents = {p.parent for p in parts.values() if p.parent}
        pointed = L.pointed_labels(unit.an)
        driven_by: dict[str, set[str]] = {}
        for r in cov["rows"]:
            for p in r.get("parts") or []:
                if r["status"] == "driven":
                    driven_by.setdefault(p, set()).update(r.get("by") or [])
        for c in (unit.answer or {}).get("components", []):
            name = c.get("name")
            if not name or name in parents or name not in parts:
                continue
            said = [x["text"] for x in L.part_labels(prog, parts, name, pointed)][:2]
            card = ""
            if lib is not None:
                words = L.words(name) | L.words(c.get("type", ""))
                for t in said:
                    words |= L.words(t)
                cards = lib.component_cards(words)
                card = cards[0]["id"] if cards else ""
            entry = cov["parts"].get(name)
            status = classify(entry)
            totals[status] += 1
            dims = f"{entry.get('driven', 0)} / {entry['total']}" if entry else "0 / 0"
            lines.append(f"| {uid} | {name} | {c.get('type', '')} | {'; '.join(said)[:60]} | {card} | {dims} | {status} | "
                         f"{', '.join(sorted(driven_by.get(name, set())))[:90]} |")
        if cov["unassigned"]:
            loose_lines.append(f"- {uid}: {len(cov['unassigned'])} dimension(s) nothing named drives on no part — "
                               + ", ".join(f"{r['dimension']} {r['mm']:g}" for r in cov["unassigned"][:12]))
    lines += ["", "Parts: " + ", ".join(f"{k} {v}" for k, v in totals.items()), "", "Dimensions on no part:", *loose_lines]
    text = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
