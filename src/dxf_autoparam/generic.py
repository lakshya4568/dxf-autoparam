"""The values the engine measured itself (ThkY1, GapX6, DimX2 …), and which of them nobody claimed.

After the analysis every gap between set-out lines is an input with a generated name. The agent (or a person) names the few that are design inputs;
all the others stay live inputs, a hundred `GapX…` rows beside the six that matter, and the Values list stops saying which is which. A value nobody
claimed is KEPT AS DRAWN — the engine's own `freeze_params` (a person's "keep these as drawn"): it stops being an input, everything that used it keeps
its number, so the drawing is exactly what it was. The rows are kept in the unit's answer (`frozen`: name, value, what it measured), so nothing is
lost, undo takes it back, and a person can release any of them to be an input again.

What counts as generated is the validator's own pattern (the analysis' naming table), so a prefix added there is covered here.
"""

from __future__ import annotations

import json
import re

from .program import Program, names_in
from .validator import GENERIC

WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def is_generated(name: str) -> bool:
    """A name the analysis gave a measured gap (ThkY1, GapX6, DimX2 …) — not one a person or the agent chose. `U01.GapX6` is GapX6."""
    return bool(GENERIC.match(name.rsplit(".", 1)[-1]))


def natural(name: str) -> tuple[str, int]:
    m = re.match(r"^(\D+)(\d+)$", name)
    return (m.group(1), int(m.group(2))) if m else (name, 0)


def linked_names(prog: Program) -> set[str]:
    """The values a note follows: a note that states a size (or a level in metres) is linked to the value that sets it, and goes stale without it."""
    out = set()
    for links in prog.text_links.values():
        for _tok, ref, _dec in links:
            name = ref.removeprefix("m:")
            if name in prog.params:
                out.add(name)
    return out


def claimed(prog: Program, answer: dict | None, changed: set[str], shared: set[str]) -> set[str]:
    """The values somebody has a use for: set by a person, bound to a size other views follow, a note states it, or named in what the agent
    wrote (a formula, a relation, a constraint, a plan, a behaviour — any of its words). The engine's own sums of sizes (R_g…) do not claim
    their terms: a size kept as drawn is a constant in them, and they hold."""
    out = set(changed) | set(shared) | linked_names(prog)
    body = {k: v for k, v in (answer or {}).items() if k != "frozen"}  # what was kept as drawn does not claim itself
    out |= set(WORD.findall(json.dumps(body, default=str)))
    for d, e in prog.formulas.items():
        if prog.origin.get(d, "geometry") != "geometry":  # a line the agent, a constraint or a slope set out from this value
            out |= names_in(e)
    for r in prog.relations:
        if not r.name.startswith("R_"):
            out |= names_in(r.expr)
    for t in prog.transforms:
        out |= set(WORD.findall(json.dumps({k: v for k, v in t.items() if k != "carried"}, default=str)))
    return out & set(prog.params)


def unclaimed(prog: Program, answer: dict | None, changed: set[str], shared: set[str]) -> list[str]:
    """The generated length values of this program that nobody claimed, in their natural order (GapX2 before GapX10)."""
    taken = claimed(prog, answer, changed, shared)
    return sorted((n for n, p in prog.params.items() if is_generated(n) and p.source != "ai" and p.kind == "length" and n not in taken), key=natural)


def frozen_row(prog: Program, name: str) -> dict:
    p = prog.params[name]
    return {"name": name, "value": p.value, "unit": p.unit, "label": p.label, "kind": p.kind, "occurrences": p.occurrences,
            "measures": list(p.measures) if p.measures else None, "why": "measured by the analysis; nobody named it, so it is kept as drawn"}


def frozen_names(answer: dict | None) -> set[str]:
    return {r["name"] for r in (answer or {}).get("frozen", []) if isinstance(r, dict) and r.get("name")}
