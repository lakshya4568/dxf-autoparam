"""Which units of the sheet a run really covered — read off the sheet, never off what the model said.

A model's closing words once said "U05–U09 were accounted for and left as drawn" while the sheet showed U05, U06 and U07 parametrized and only U08 and U09
never opened; and a gate that reported "1 thing remains" hid that two of ten units had not been touched. A unit is, at the end of a run:

  parametrized  the sheet holds an answer for it (parts, named values or levels)
  skipped       the model's checklist says so, in words, for that unit — a reason on the record, which the person can read
  looked_at     the run opened it and nothing was kept: not covered, and not the same as skipped
  untouched     the run never opened it

Only `parametrized` and `skipped` count as covered. The table is the engine's own: per unit what it holds, and what it refused.
"""

from __future__ import annotations

import re

from ..generic import is_generated

SKIPPED = ("skipped", "skip", "n/a", "not_applicable", "not applicable", "cancelled", "canceled", "dropped", "out_of_scope", "out of scope")


def _skip_reason(uid: str, checklist: list[dict]) -> str | None:
    word = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(uid)}(?![A-Za-z0-9_])")
    for c in checklist:
        if str(c.get("status", "")).lower() in SKIPPED and word.search(f"{c.get('text', '')} {c.get('evidence', '')}"):
            return (str(c.get("evidence") or c.get("text") or "")).strip()[:200] or "skipped"
    return None


def unit_rows(sm, scope_units: list[str], opened: dict[str, dict], checklist: list[dict], refusals: list[dict]) -> list[dict]:
    """One row per unit in scope: its state and what the sheet holds for it. `opened`: the units the run opened → what it holds for each (a unit
    worked on and not yet applied counts: the gate asks before it applies)."""
    rows = []
    for uid in scope_units:
        u = sm.units.get(uid)
        if u is None:
            continue
        answer = u.answer or opened.get(uid) or {}
        parametrized = bool(answer.get("components") or answer.get("parameters") or answer.get("levels"))
        reason = _skip_reason(uid, checklist)
        state = "parametrized" if parametrized else "skipped" if reason else "looked_at" if uid in opened else "untouched"
        row = {"unit": uid, "views": list(u.views), "state": state, "covered": state in ("parametrized", "skipped")}
        if parametrized:
            prog = sm.unit(uid).prog
            named = [n for n, p in prog.params.items() if p.source == "ai" or not is_generated(n)] if prog is not None else []
            row.update(parts=len(answer.get("components", [])), inputs=len(named),
                       measured=len([r for r in (prog.relations if prog is not None else []) if not r.name.startswith("R_")]),
                       kept_as_drawn=len(answer.get("frozen", [])))
        if state == "skipped":
            row["reason"] = reason
        mine = [r["item"] for r in refusals if r.get("unit") == uid]
        if mine:
            row["refused"] = mine[:12]
        rows.append(row)
    return rows


def sentence(rows: list[dict]) -> str:
    """'8 of 10 units parametrized (U08, U09 untouched; U05 looked at, nothing kept; U06 skipped: why)' — the first thing a person should read."""
    if not rows:
        return ""
    done = [r for r in rows if r["state"] == "parametrized"]
    out = f"{len(done)} of {len(rows)} units parametrized"
    said = {"skipped": "skipped on the record", "looked_at": "looked at, nothing kept", "untouched": "untouched"}
    parts = []
    for state, words in said.items():
        ids = [r["unit"] for r in rows if r["state"] == state]
        if ids:
            parts.append(f"{', '.join(ids)} {words}")
    return out + (f" ({'; '.join(parts)})" if parts else "")


def table_md(rows: list[dict]) -> str:
    """The same rows as a markdown table the person can read (and paste): what the engine holds per unit, whatever the model's own prose says."""
    lines = ["| unit | views | state | parts | named inputs | measured | kept as drawn | refused |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['unit']} | {' + '.join(r['views'])} | {r['state'].replace('_', ' ')}{(': ' + r['reason']) if r.get('reason') else ''} | "
                     f"{r.get('parts', '')} | {r.get('inputs', '')} | {r.get('measured', '')} | {r.get('kept_as_drawn', '')} | {', '.join(r.get('refused', []))} |")
    return "\n".join(lines)
