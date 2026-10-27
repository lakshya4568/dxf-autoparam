"""Existing work and new work drawn along one set-out line are two structures: a value of one moves that one (intent.split_structures).

The case: an existing box culvert extended by a new one, drawn in one longitudinal section — their slab faces run along the same horizontal lines.
Before, a value named on the new slab moved entities of the old box too (the line was one), and a person saw one value move both structures."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from dxf_autoparam.ai.parametrize import prepare
from dxf_autoparam.intent import held_own_entities
from dxf_autoparam.regen import regenerate_program
from dxf_autoparam.validator import apply

ROOT = Path(__file__).resolve().parents[1]
XX = str(ROOT / "examples" / "sectional_elevation_xx.dxf")
ANSWER = json.loads((ROOT / "tests" / "fixtures" / "sectional_elevation_xx.answer.json").read_text())


def moved_by(prog, name: str) -> tuple[int, int]:
    """Entities of existing work and of new work that move when `name` grows 100 mm."""
    parts = prog.intent["parts"]
    an = prog.analysis
    ex = held_own_entities(an, parts, {n for n, p in parts.items() if p.existing})
    new = held_own_entities(an, parts, {n for n, p in parts.items() if not p.existing})
    a = regenerate_program(prog, None, check=False).pts
    b = regenerate_program(prog, {name: prog.defaults()[name] + 100}, check=False).pts
    moved = {i for i in a if a[i] != b.get(i)}
    return len(moved & ex), len(moved & new)


def test_lines_both_structures_run_along_are_one_each_and_a_value_moves_its_own_structure():
    an, *_ = prepare(XX)
    prog, rep = apply(an, ANSWER)
    lines = prog.intent.get("structure_lines") or {}
    assert lines and all(c == f"{d}e" and c in an.datums for d, c in lines.items())
    assert rep.errors() == []
    assert regenerate_program(prog).issues == [], "as drawn the copies coincide: the drawing is reproduced"
    ex, new = moved_by(prog, "FlooringThickness")  # the new apron's thickness: drawn on a line the old box's bed is drawn on too
    assert new and not ex, (ex, new)


def test_a_split_never_outlives_the_answer_it_was_made_for():
    an, *_ = prepare(XX)
    apply(an, ANSWER)
    plain = copy.deepcopy(ANSWER)
    for c in plain["components"]:
        c["existing"] = False  # nothing existing: nothing to split, and the earlier build's split is put back
    prog, _rep = apply(an, plain)
    assert not prog.intent.get("structure_lines")
    assert not any(g.split_of for g in an.gaps.values()) and not any(g.a.endswith("e") or g.b.endswith("e") for g in an.gaps.values())
