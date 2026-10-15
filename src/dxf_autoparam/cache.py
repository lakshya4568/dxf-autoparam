"""Deterministic results reused while their inputs are unchanged — keyed by WHAT they depend on, never by time.

    memo = Memo()
    v = memo.get("layers", (drawing_key(sm),), lambda: layer_report(sm.dr, sm.layout))

An entry is recomputed exactly when one of its dependency keys changes:

  drawing_key(sm)     the drawing as read (its entities): a new revision of the drawing (a feature operation) changes it
  layout_key(sm)      the views and how they are grouped into units (merge / split / link / rename change it)
  unit_key(sm, uid)   one unit's parametrization (its answer and program) — not the values it is shown at
  values_key(sm)      the values every unit is regenerated at (an edit, undo, redo change it)
  decisions_key(sm)   the semantic decisions accepted on the sheet (statuses, annotation corrections, names)

So changing one local value re-renders and re-measures, but never re-reads the DXF, re-segments the sheet, re-associates
annotations or re-finds duplicates; changing a shared datum's value invalidates everything that depends on values.
`stats()` tells hits, misses and invalidations — measured, for the agent-efficiency tests.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def drawing_key(sm) -> str:
    return f"{id(sm.dr)}:{len(sm.dr.items)}:{sm.dr.path}"


def layout_key(sm) -> str:
    return _h([[g.id, g.kind, g.name, len(g.items)] for g in sm.layout.groups] + [sorted(sm.unit_of_view.items())])


def unit_key(sm, uid: str) -> str:
    u = sm.units.get(uid)
    if u is None:
        return "-"
    return f"{uid}:{id(u.prog)}:{_h(u.answer) if u.answer else 'baseline'}:{id(u.an)}"


def values_key(sm) -> str:
    return _h(sm.values)


def decisions_key(sm, part: str | None = None) -> str:
    """The accepted semantic decisions — all of them, or one kind ("status", "annotations", "names")."""
    sem = getattr(sm, "semantics", {}) or {}
    return _h(sem.get(part) if part else sem)


class Memo:
    def __init__(self, capacity: int = 256):
        self.store: OrderedDict[str, tuple[tuple, Any]] = OrderedDict()
        self.capacity = capacity
        self.hits = 0
        self.misses = 0
        self.invalidations = 0
        self.log: list[str] = []  # the last few recomputations and why

    def get(self, name: str, deps: tuple, fn: Callable[[], Any]) -> Any:
        e = self.store.get(name)
        if e is not None and e[0] == deps:
            self.hits += 1
            self.store.move_to_end(name)
            return e[1]
        if e is not None:
            self.invalidations += 1
            changed = [k for k, (a, b) in enumerate(zip(e[0], deps, strict=False)) if a != b]
            self.log.append(f"{name}: recomputed, dependency {changed} changed")
            self.log = self.log[-40:]
        self.misses += 1
        v = fn()
        self.store[name] = (deps, v)
        self.store.move_to_end(name)
        while len(self.store) > self.capacity:
            self.store.popitem(last=False)
        return v

    def peek(self, name: str, deps: tuple) -> bool:
        """Whether a current entry exists (nothing is computed)."""
        e = self.store.get(name)
        return e is not None and e[0] == deps

    def stats(self) -> dict:
        return {"entries": len(self.store), "hits": self.hits, "misses": self.misses, "invalidations": self.invalidations,
                "recent": self.log[-8:]}
