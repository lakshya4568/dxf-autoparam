"""One parametric model for a whole sheet: views that show the same structure change together.

    sm = SheetModel.open("gad.dxf")              # views found, projection links proposed / taken
    sm.shared_proposals()                          # sizes two units both state (with the evidence)
    sm.share("WidthA", [("U1", "c12"), ("U3", "c40")])
    r = sm.preview({"WidthA": 4000})               # every affected view regenerated, checked — nothing committed
    sm.apply({"WidthA": 4000})                     # committed only if every check passes; undo() / redo()
    sm.export("out.dxf")

The layers:
  DRAWING     the sheet as read (entities, coordinates) — never edited; views are lists of its entity indices
  SEMANTIC    views (sheet.py), PROJECTION LINKS between views that show the same planes (a plan under its elevation
              shares its vertical set-out lines; a section beside an elevation shares its levels), shared parameters
  PARAMETRIC  one program per UNIT (a view, or views linked by projection, analysed together so that a plane they
              share is ONE set-out line: changing it in one view changes it in the other by construction), plus SHARED
              parameters bound by name into several units (a size stated in two views that are not drawn in line)

Nothing here knows a structure type: links come from coinciding set-out lines, shared sizes from what two views both
state; a person (or the AI) accepts, rejects or renames, and every change is checked on the regenerated sheet.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from . import design_intent, generic
from .analyse import analyse
from .cadjson import entity_id
from .display import primitives
from .dxf_read import read_dxf
from .dxf_write import audit, write_dxf
from .graph import affects
from .intent import _drives
from .ir import Analysis, Drawing, Role
from .plan import accept, build_plan, clashes, pairs_of, plan_errors_at, with_plan
from .program import ExprError, Program
from .regen import Regenerated, regenerate_program
from .sheet import Group, SheetLayout, segment, view_drawing
from .validator import GENERIC, PASCAL, Finding, Report, apply, baseline, rescale_values

EMPTY_ANSWER = {"structure_type": "", "family": "other", "views": [], "summary": "", "components": [], "line_roles": [], "levels": [],
                "parameters": [], "datum_formulas": [], "relations": [], "behaviours": [], "constraints": [], "questions": []}
NAME_KEYS = ("name", "parameter", "target")
EXPR_KEYS = ("expr", "value")


class SheetError(ValueError):
    """A request the sheet model refuses, with the reason a person can act on."""


# ── projection links ─────────────────────────────────────────────────────────────


def _planes(dr: Drawing, items: list[int], q: float, box: tuple[float, float, float, float]) -> tuple[set[int], set[int]]:
    """The set-out planes of a view: where its FACES stand — the x of its vertical edges and the y of its horizontal
    ones that are at least 3 % of the view long. Hatch strokes, text strokes and ticks share coordinates across views
    by chance; faces drawn in projection share them by design."""
    xs, ys = set(), set()
    min_v = 0.03 * max(box[3] - box[1], 1e-9)
    min_h = 0.03 * max(box[2] - box[0], 1e-9)
    for i in items:
        it = dr.items[i]
        if it.role != Role.STRUCTURAL:
            continue
        for a, b in it.segments or ([(0, 1)] if it.dxftype == "LINE" and len(it.pts) == 2 else []):
            (x0, y0), (x1, y1) = it.pts[a], it.pts[b]
            if abs(x0 - x1) <= dr.tol and abs(y1 - y0) >= min_v:
                xs.add(round(x0 / q))
            elif abs(y0 - y1) <= dr.tol and abs(x1 - x0) >= min_h:
                ys.add(round(y0 / q))
    return xs, ys


def _shared(a: set[int], b: set[int]) -> set[int]:
    """Planes in both, allowing one grid step either way (a coordinate on the edge of a grid cell)."""
    return {v for v in a if v in b or v - 1 in b or v + 1 in b}


def view_links(dr: Drawing, layout: SheetLayout, min_planes: int = 6, min_frac: float = 0.25) -> list[dict]:
    """Views drawn in projection with each other: one over the other sharing vertical set-out lines (an elevation and
    its plan), or side by side sharing horizontal ones (a section beside an elevation: its levels). Only views at the
    same drawing scale; `strong` when enough planes coincide to be design, not chance."""
    views = layout.views()
    frame = layout.frame or dr.extent
    # faces in projection coincide to the drawing's precision: exact in CAD, to a hair in a PDF conversion — a
    # tolerance relative to the sheet (1/10 000 of it), never finer than the reader's own
    q = max(dr.tol, 1e-4 * max(frame[2] - frame[0], frame[3] - frame[1]), 1e-9)
    planes = {v.id: _planes(dr, v.items, q, v.bbox) for v in views}
    out = []
    for i, a in enumerate(views):
        for b in views[i + 1:]:
            ua, ub = a.units_mm or dr.units_mm, b.units_mm or dr.units_mm
            if abs(ua / ub - 1) > 0.01 or (a.scale and b.scale and a.scale != b.scale):
                continue
            ax0, ay0, ax1, ay1 = a.bbox
            bx0, by0, bx1, by1 = b.bbox
            x_over = max(0.0, min(ax1, bx1) - max(ax0, bx0)) / max(1e-9, min(ax1 - ax0, bx1 - bx0))
            y_over = max(0.0, min(ay1, by1) - max(ay0, by0)) / max(1e-9, min(ay1 - ay0, by1 - by0))
            for axis, over, other in (("x", x_over, y_over), ("y", y_over, x_over)):
                if over < 0.3 or other > 0.2:  # in line along this axis, apart along the other
                    continue
                pa, pb = planes[a.id][0 if axis == "x" else 1], planes[b.id][0 if axis == "x" else 1]
                common = _shared(pa, pb)
                frac = len(common) / max(1, min(len(pa), len(pb)))
                if len(common) >= 3:
                    out.append({"a": a.id, "b": b.id, "axis": axis, "planes": len(common), "fraction": round(frac, 2),
                                "strong": (len(common) >= min_planes and frac >= min_frac) or (len(common) >= 4 and frac >= 0.6),
                                "why": f"{a.id} and {b.id} share {len(common)} {'vertical' if axis == 'x' else 'horizontal'} set-out lines "
                                       f"({frac:.0%} of the smaller view's): drawn in projection"})
    return out


# ── units, bindings, shared parameters ───────────────────────────────────────────


@dataclass
class Binding:
    unit: str
    param: str  # its name in that unit's program (the shared name once bound)
    candidate: str | None = None  # the candidate value (c…) it names there, or
    datums: tuple[str, str] | None = None  # the two set-out lines it is measured between
    status: str = "pending"  # drives | worked_out | refused | pending
    reason: str = ""


@dataclass
class SharedParam:
    id: str
    name: str
    label: str
    value: float
    unit: str
    bindings: list[Binding]
    evidence: list[str] = field(default_factory=list)
    source: str = "person"  # person | ai | proposal


@dataclass
class Unit:
    """Views analysed as one: a view on its own, or views linked by projection (their common planes are one line)."""

    id: str
    views: list[str]
    items: list[int]  # sheet indices
    sub: Drawing
    back: list[int]  # the unit's item k is sheet item back[k]
    answer: dict | None = None  # the parametrization (AI or person), replayable
    an: Analysis | None = None
    snap: dict | None = None
    prog: Program | None = None
    report: Report | None = None
    gap_clusters: dict | None = None
    orig_datums: dict | None = None
    orig_slot_datum: dict | None = None
    dropped: str = ""  # why a parametrization it had was dropped (its views changed)

    @property
    def built(self) -> bool:
        return self.prog is not None


def rename_in_answer(answer: dict, old: str, new: str) -> dict:
    """Every place an answer names a parameter or level — names, behaviour targets, expressions — renamed."""
    word = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])")

    def walk(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: (new if k in NAME_KEYS and v == old else word.sub(new, v) if k in EXPR_KEYS and isinstance(v, str) else walk(v))
                    for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o

    return cast(dict, walk(answer))


@dataclass
class SheetRegen:
    """The sheet regenerated: points per sheet entity (only those of regenerated units), what changed, what is wrong."""

    reg: Regenerated
    changed: list[int]
    by_view: dict[str, int]
    errors: list[str]
    warnings: list[str]
    measured: dict[str, dict[str, float]]  # shared name → unit → the size its lines measure

    @property
    def ok(self) -> bool:
        return not self.errors


class SheetModel:
    def __init__(self, dr: Drawing, layout: SheetLayout | None = None, unlinked: set[tuple[str, str]] | None = None):
        self.dr = dr
        self.path = dr.path
        self.layout = layout or segment(dr)
        self.unlinked: set[tuple[str, str]] = set(unlinked or ())
        self.links = view_links(dr, self.layout)
        self.units: dict[str, Unit] = {}
        self.unit_of_view: dict[str, str] = {}
        self.shared: dict[str, SharedParam] = {}
        self.values: dict[str, dict[str, float]] = {}  # unit → parameter → value (only what differs from its defaults)
        self.history: list[dict] = []
        self.future: list[dict] = []
        self._trial = 0  # > 0 while an answer is only being tried (`_trial_builder`): nothing the person has may change
        self._live: tuple[frozenset[str], int] | None = None  # (values, revision) of the last live step: the next one of them joins it
        self._settle_cache: dict[tuple[int, str, str], dict] = {}  # (revision, unit, size) → the ways to settle it found on that revision (settle_options)
        self.accepted: set[tuple[str, str]] = set()  # projection links a person (or the AI, checked) took although weak
        self.relations: list[dict] = []  # views that show the same structure / a detail of another (semantic, not set-out)
        # The plan an agent run STATED for the sheet: what it took to be the same component or dimension in more than one view, how they
        # relate and how that is bound, and what it assumed (ai.sheet_ai.apply_plan). A statement, checked when made and again at the end.
        self.stated_plan: dict = {}
        self.questions: list[str] = []  # what the AI or the engine asks a person to settle
        # Rules of a production domain bound to units (production.binding): each maps a domain model's fields to a unit's own values and
        # lines; the outputs that held when it was accepted are GUARDS — every regeneration must keep them holding, or nothing is applied.
        self.domain: list[dict] = []
        # The feature operations that made this revision of the drawing out of an earlier one (feature.py): each names the file it came from.
        self.lineage: list[dict] = []
        # Semantic decisions accepted on the sheet, each with who made it, why and on which revision: existing / proposed status
        # (by layer, colour or entities), what an annotation refers to and how it behaves, the names given to values. Undoable,
        # saved with the project; analyses read them (layers.classify_status, annotations), the agent reuses them instead of
        # rediscovering them.
        self.semantics: dict = {"status": [], "annotations": {}, "notes": []}
        # The agent's working notes (ai.understanding_tools): its checklist and the facts it established, each with its evidence and the
        # revision it was established on. Saved with the project; not undo state (a checklist is not undone with a value).
        self.agent_notes: dict = {"checklist": [], "learned": []}
        # Deterministic results reused while their inputs are unchanged (cache.py) — not state: undo does not touch it.
        from .cache import Memo

        self.memo = Memo()
        # Bumped by every change of state (an edit, undo, redo): work started on one revision (a Gemini run, an open
        # panel) is refused when it would land on another — it was decided on a sheet that no longer exists.
        self.revision = 0
        self._group_units()
        # The imported state — what the file alone gives: the views the engine found, no links taken or refused, no values,
        # no plans. A reset goes back to it (baseline.reset_drawing); the geometry itself (self.dr) is never edited.
        self.import_state: dict = {"unlinked": set(), "groups": copy.deepcopy(self.layout.groups)}
        self.prefs: dict = {"baseline": {"on": False, "color": "#4f6bff"}}  # what a person chose to see: saved with the project
        self.runs: list[dict] = []  # finished agent runs (a log, not state: undo does not touch it)

    @classmethod
    def open(cls, path: str) -> SheetModel:
        dr, _ = read_dxf(path)
        return cls(dr)

    # ── units ────────────────────────────────────────────────────────────────

    def is_linked(self, lk: dict) -> bool:
        key = (lk["a"], lk["b"])
        return (lk["strong"] or key in getattr(self, "accepted", set())) and key not in self.unlinked

    def _group_units(self, keep: dict[str, Unit] | None = None) -> None:
        views = self.layout.views()
        parent = {v.id: v.id for v in views}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for lk in self.links:
            if self.is_linked(lk):
                parent[find(lk["b"])] = find(lk["a"])
        groups: dict[str, list[Group]] = {}
        for v in views:
            groups.setdefault(find(v.id), []).append(v)
        old = keep or {}
        self.units, self.unit_of_view = {}, {}
        for members in groups.values():
            ids = sorted(v.id for v in members)
            # stable: named by its views (URL-safe). A group that was not found as a view (V…) but was said to be one keeps its whole id,
            # so that "T01" (UT01) never takes the name of the unit of "V01" (U01).
            uid = "U" + "_".join(v.removeprefix("V") for v in ids)
            items = sorted({i for v in members for i in v.items})
            units_mm = members[0].units_mm
            sub, back = view_drawing(self.dr, items)
            if units_mm:
                sub.units_mm = units_mm
            u = old.get(uid)
            if u is None or u.items != items:
                u = Unit(id=uid, views=ids, items=items, sub=sub, back=back)
                gone = [o for o in old.values() if o.answer and set(o.views) & set(ids)]
                if gone:
                    u.dropped = f"its views changed ({', '.join(o.id for o in gone)} → {uid}): parametrize it again"
            self.units[uid] = u
            for v in ids:
                self.unit_of_view[v] = uid

    def unit(self, uid: str) -> Unit:
        if uid not in self.units:
            raise SheetError(f"no unit {uid}")
        u = self.units[uid]
        if u.prog is None:
            self._build(u)
        assert u.prog is not None
        return u

    def analysis(self, uid: str) -> Analysis:
        """A unit's analysis (set-out lines, candidates, annotations) without building its program — what reading the sheet
        needs; the program is built from the same analysis when the unit is parametrized."""
        if uid not in self.units:
            raise SheetError(f"no unit {uid}")
        u = self.units[uid]
        if u.an is None:
            self._analyse_unit(u)
        assert u.an is not None
        return u.an

    def _analyse_unit(self, u: Unit) -> None:
        u.an = analyse(u.sub)
        assert u.an is not None
        self._drop_layout_gaps(u)
        u.snap = {cid: (c.name, c.accepted, list(c.gaps)) for cid, c in u.an.clusters.items()}
        u.gap_clusters = {gid: g.cluster for gid, g in u.an.gaps.items()}
        u.orig_datums = {did: copy.copy(d) for did, d in u.an.datums.items()}
        u.orig_slot_datum = dict(u.an.slot_datum)

    def _build(self, u: Unit) -> None:
        """The unit's program, from its answer (or the geometry alone): the same validated engine as a single view."""
        if u.an is None:
            self._analyse_unit(u)
        else:  # apply() renames and splits candidates: start from the analysis as found
            assert u.snap is not None
            assert u.gap_clusters is not None
            if u.orig_datums is not None:
                u.an.datums = {did: copy.copy(d) for did, d in u.orig_datums.items()}
            if u.orig_slot_datum is not None:
                u.an.slot_datum = dict(u.orig_slot_datum)
            for cid, (name, acc, gaps) in u.snap.items():
                c = u.an.clusters[cid]
                c.name, c.accepted, c.gaps = name, acc, list(gaps)
            for gid, cl in u.gap_clusters.items():
                u.an.gaps[gid].cluster = cl
        assert u.an is not None
        if u.answer:  # the answer's own selection applies: parts it keeps as drawn are held, sizes it keeps as drawn are not inputs (unlock_part undoes it)
            u.answer, ratio = rescale_values(u.an, u.answer)  # values saved when the unit was read at another scale are measured again (said below)
            if ratio is not None and not self._trial:  # (a candidate being tried changes nothing the person has)
                for name, v in (self.values.get(u.id) or {}).items():  # a size a person had stepped was on the old scale too
                    if name in {p.get("name") for p in u.answer.get("parameters", [])}:
                        self.values[u.id][name] = v / ratio
            u.prog, u.report = apply(u.an, u.answer)
            if ratio is not None:
                u.report.findings.append(Finding("V2", "info", u.id, f"the unit is now read at its own scale: the values named for it before were {ratio:g} times what the drawing "
                                                                     "measures, and are measured again (names, parts and levels are kept)"))
        else:
            u.report = Report()
            u.prog = baseline(u.an, rep=u.report)
        assert u.prog is not None
        for b in (b for p in self.shared.values() for b in p.bindings if b.unit == u.id):
            self._bind_status(u, b)

    def _drop_layout_gaps(self, u: Unit) -> None:
        """Views linked one over the other share their vertical lines; the distance from one view's horizontal lines to
        the other's is only where they sit on the sheet, never a size of the structure — dropped (and the other way
        round for views side by side)."""
        assert u.an is not None
        if len(u.views) < 2:
            return
        cross = set()
        for lk in self.links:
            if {lk["a"], lk["b"]} <= set(u.views) and self.is_linked(lk):
                cross.add("y" if lk["axis"] == "x" else "x")
        if not cross:
            return
        an = u.an
        view_of = {k: self.layout.item_group.get(s) for k, s in enumerate(u.back)}
        views_of = {d.id: {view_of.get(i) for i in d.items} - {None} for d in an.datums.values()}
        drop = [gid for gid, g in an.gaps.items()
                if g.axis in cross and views_of.get(g.a) and views_of.get(g.b) and not (views_of[g.a] & views_of[g.b])]
        for gid in drop:
            g = an.gaps.pop(gid)
            c = an.clusters.get(g.cluster) if g.cluster else None
            if c is not None and gid in c.gaps:
                c.gaps.remove(gid)
                if not c.gaps:
                    del an.clusters[c.id]
        if drop:
            an.notes.append(f"{len(drop)} distance(s) between linked views across their projection are sheet layout, not sizes")

    def _bind_status(self, u: Unit, b: Binding) -> None:
        assert u.prog is not None
        prog = u.prog
        if b.param in prog.params:
            b.status, b.reason = "drives", ""
            return
        rel = next((r for r in prog.relations if r.label == b.param or r.name == b.param), None)
        if rel is not None:
            b.status, b.reason = "worked_out", f"worked out from other inputs in {u.id}: {rel.expr}"
            return
        why = [f.message for f in (u.report.findings if u.report else []) if f.item == b.param]
        b.status, b.reason = "refused", (why[0] if why else f"{b.param} is not a value of {u.id}")

    # ── values ───────────────────────────────────────────────────────────────

    def _values_for(self, u: Unit, changes: dict[str, float]) -> dict[str, float]:
        assert u.prog is not None
        vals = dict(self.values.get(u.id, {}))
        for name, v in changes.items():
            if "." in name:
                unit, local = name.split(".", 1)
                if unit == u.id:
                    vals[local] = v
            elif name in self._shared_by_name():
                for b in self._shared_by_name()[name].bindings:
                    if b.unit == u.id and b.status == "drives":
                        vals[b.param] = v
        return {k: v for k, v in vals.items() if k in u.prog.params}

    def _shared_by_name(self) -> dict[str, SharedParam]:
        return {p.name: p for p in self.shared.values()}

    def _shared_now(self, p: SharedParam) -> float:
        """A shared value as it stands (committed changes included)."""
        return next((self.values[b.unit][b.param] for b in p.bindings if b.param in self.values.get(b.unit, {})), p.value)

    def _touched(self, changes: dict[str, float]) -> set[str]:
        out = set(self.values)
        for name in changes:
            if "." in name:
                out.add(name.split(".", 1)[0])
            elif name in self._shared_by_name():
                out |= {b.unit for b in self._shared_by_name()[name].bindings}
            else:
                raise SheetError(f"no value {name}: a shared name, or unit.name")
        return out

    def regenerate(self, changes: dict[str, float] | None = None, units: set[str] | None = None) -> SheetRegen:
        """The sheet with `changes` (shared names, or "U…" + "." + local names) on top of the current values. Only units
        that are built and have values (or are touched) are regenerated; every other entity stays as drawn."""
        changes = changes or {}
        todo = (units or set()) | self._touched(changes)
        pts, radius, texts, turns = {}, {}, {}, {}
        errors, warnings, changed = [], [], []
        by_view: dict[str, int] = {}
        measured: dict[str, dict[str, float]] = {}
        regenerated: dict[str, tuple] = {}
        for uid in sorted(todo):
            u = self.unit(uid)
            assert u.prog is not None
            vals = self._values_for(u, changes)
            try:
                r = regenerate_program(u.prog, vals)
            except (KeyError, ExprError, ArithmeticError) as exc:
                errors.append(f"{uid}: cannot regenerate: {exc}")
                continue
            errors += [f"{uid}: {i}" for i in r.issues]
            regenerated[uid] = (u, vals, r.datum)
            plans = [p for p in (u.answer or {}).get("plans", []) if p.get("status") == "accepted"]
            if plans:  # what a person accepted for this unit holds at the values asked for, not only at the ones tested
                errors += [f"{uid}: {e}" for e in plan_errors_at(u.prog, plans, vals)]
                if any(not design_intent.derived(p) for p in plans):
                    # the crossing check belongs to a plan a person accepted: the engine's own plans (design intent) say which side of a size stays and
                    # must not make the unit stricter than it was — a size that crosses members was said, when the intent was derived, and is still allowed
                    moved_k = {k for k, p in r.pts.items() if any(abs(a[0] - b[0]) > 1e-9 or abs(a[1] - b[1]) > 1e-9
                                                                  for a, b in zip(p, u.sub.items[k].pts, strict=False))}
                    errors += [f"{uid}: {entity_id(u.sub.items[i])} now crosses {entity_id(u.sub.items[j])} — members run into each other"
                               for i, j in clashes(u.prog, r.pts, moved_k)[:5]]
            for k, p in r.pts.items():
                s = u.back[k]
                pts[s] = p
                orig = self.dr.items[s].pts
                if any(abs(a[0] - b[0]) > 1e-9 or abs(a[1] - b[1]) > 1e-9 for a, b in zip(p, orig, strict=False)):
                    changed.append(s)
                    v = self.layout.item_group.get(s, "")
                    by_view[v] = by_view.get(v, 0) + 1
            moved = set(changed)
            for k, tn in r.turns.items():
                turns[u.back[k]] = tn
            for k, rad in r.radius.items():
                radius[u.back[k]] = rad
                if abs(rad - (self.dr.items[u.back[k]].radius or 0.0)) > 1e-9 and u.back[k] not in moved:
                    changed.append(u.back[k]); moved.add(u.back[k])
            for k, t in r.texts.items():
                texts[u.back[k]] = t
                if t != self.dr.items[u.back[k]].text and u.back[k] not in moved:   # a note whose number changed in place
                    s = u.back[k]
                    changed.append(s); moved.add(s)
                    v = self.layout.item_group.get(s, "")
                    by_view[v] = by_view.get(v, 0) + 1
            # every shared size this unit drives must measure the shared value on its own lines
            um = u.sub.units_mm
            for p in self.shared.values():
                for b in p.bindings:
                    if b.unit != uid or b.status != "drives":
                        continue
                    prm = u.prog.params.get(b.param)
                    if prm is None or not prm.measures:
                        continue
                    a, c = prm.measures
                    got = abs(r.datum[c] - r.datum[a]) * um
                    measured.setdefault(p.name, {})[uid] = got
            for p in self.shared.values():
                want = changes.get(p.name, self._shared_now(p))
                for b in p.bindings:
                    if b.unit == uid and b.status == "worked_out" and abs(want - p.value) > 1e-9:
                        errors.append(f"{p.name} cannot change in {uid}: {b.reason}")
        for name, per in measured.items():
            want = changes.get(name, self._shared_now(self._shared_by_name()[name]))
            for uid, got in per.items():
                if abs(got - want) > max(0.5, 1e-4 * abs(want)):
                    errors.append(f"{name}: {uid} measures {got:.1f} mm, not {want:g} — that view did not follow")
        errors += self._domain_errors(regenerated)
        warnings += self._overlaps(changed, pts)
        reg = Regenerated(values=dict(changes), datum={}, pts=pts, radius=radius, texts=texts, issues=list(errors), turns=turns)
        return SheetRegen(reg=reg, changed=sorted(changed), by_view=by_view, errors=errors, warnings=warnings, measured=measured)

    def _overlaps(self, changed: list[int], pts: dict[int, list]) -> list[str]:
        """Words a change pushed onto other words of the same view (they did not overlap as drawn): said, for a person
        to move — the engine never rewrites a note's place or meaning to dodge it."""
        from dataclasses import replace

        from .sheet import TEXT_TYPES, text_outline

        moved = [i for i in changed if self.dr.items[i].dxftype in TEXT_TYPES and self.dr.items[i].text]
        if not moved:
            return []

        def box(i: int, new: bool) -> tuple[float, float, float, float]:
            it = self.dr.items[i]
            o = text_outline(replace(it, pts=pts.get(i, it.pts)) if new else it)
            return min(p[0] for p in o), min(p[1] for p in o), max(p[0] for p in o), max(p[1] for p in o)

        def hit(a, b) -> bool:
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            if w <= 0 or h <= 0:
                return False
            smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
            return w * h > 0.2 * max(smaller, 1e-12)

        out = []
        group = self.layout.item_group
        for i in moved:
            vid = group.get(i)
            mine_new, mine_old = box(i, True), box(i, False)
            for j in self.layout.group(vid).items if vid else []:
                if j == i or self.dr.items[j].dxftype not in TEXT_TYPES or not self.dr.items[j].text:
                    continue
                other_new, other_old = box(j, True), box(j, False)
                if hit(mine_new, other_new) and not hit(mine_old, other_old):
                    a = (self.dr.items[i].text or "").split("\n")[0][:30]
                    b = (self.dr.items[j].text or "").split("\n")[0][:30]
                    out.append(f"{vid}: the note '{a}' now overlaps '{b}' — move one of them")
            if len(out) >= 20:
                break
        return out

    def _domain_state(self, b: dict, regenerated: dict[str, tuple] | None = None):
        """Every unit a domain binding reads — regenerated where this regeneration touched it, as it stands otherwise."""
        from .production.binding import SheetState, UnitState

        units = {}
        wanted = {b["unit"]} | {r["unit"] for r in list(b.get("inputs", {}).values()) + list(b.get("outputs", {}).values())
                                 if isinstance(r, dict) and isinstance(r.get("unit"), str)}
        for uid in wanted:
            if regenerated and uid in regenerated:
                u, vals, datum = regenerated[uid]
                assert u.prog is not None
                units[uid] = UnitState.of(u.prog, vals, datum)
            elif uid in self.units:
                u = self.unit(uid)
                assert u.prog is not None
                units[uid] = UnitState.of(u.prog, self._values_for(u, {}))
        return SheetState(default=b["unit"], units=units)

    def _domain_errors(self, regenerated: dict[str, tuple]) -> list[str]:
        """The guarded relations of every domain binding that reads a regenerated unit, checked on the regenerated sheet (empty when none)."""
        rows = [b for b in self.domain if (b.get("guards") or b.get("guard_validation")) and (
            b.get("unit") in regenerated or any(isinstance(r, dict) and r.get("unit") in regenerated
                                                for r in list(b.get("inputs", {}).values()) + list(b.get("outputs", {}).values())))]
        if not rows:
            return []
        from .production import service

        return [f"{b['unit']}: {e}" for b in rows for e in service.guard_errors(b, self._domain_state(b, regenerated))]

    def bind_domain(self, binding: dict, guard: bool = True) -> dict:
        """Keep a domain binding (one undoable step): checked and evaluated on the units as they stand; what holds becomes a guard. Refused
        (SheetError, nothing kept) when it does not resolve. A binding with the same id replaces the old one."""
        from .production import service

        uid = binding.get("unit") if isinstance(binding, dict) else None
        if uid not in self.units:
            raise SheetError(f"no unit {uid!r}: a binding names the unit whose values and lines it reads")
        try:
            kept, rep = service.accept(binding, self._domain_state(binding), guard=guard)
        except service.ProductionRefusal as exc:
            raise SheetError(f"binding refused, nothing kept: {exc}") from exc
        self._push()
        self.domain = [b for b in self.domain if b.get("id") != kept["id"]] + [kept]
        return rep

    def unbind_domain(self, bid: str) -> None:
        if not any(b.get("id") == bid for b in self.domain):
            raise SheetError(f"no domain binding {bid!r}")
        self._push()
        self.domain = [b for b in self.domain if b.get("id") != bid]

    def domain_report(self, uid: str | None = None) -> list[dict]:
        """Every domain binding (of one unit, or all) evaluated on the sheet as it stands."""
        from .production import service

        out = []
        for b in self.domain:
            if uid and b.get("unit") != uid:
                continue
            rep = service.report(b, self._domain_state(b))
            out.append({**rep, "guards": list(b.get("guards") or []), "guard_validation": bool(b.get("guard_validation"))})
        return out

    def preview(self, changes: dict[str, float]) -> SheetRegen:
        return self.regenerate(changes)

    def apply(self, changes: dict[str, float], live: bool = False) -> SheetRegen:
        """Commit a change only if the whole sheet regenerates cleanly; otherwise nothing changes.

        `live` is one person stepping a value up and down: every step is committed (the drawing follows), but steps of the same values in a row
        are ONE undoable step, so a single undo goes back to where the stepping began."""
        r = self.regenerate(changes)
        if not r.ok:
            return r
        keys = frozenset(changes)
        if live and self._live == (keys, self.revision):
            self.revision += 1  # same session: the history already holds the state before it
        else:
            self._push()
        self._live = (keys, self.revision) if live else None
        shared = self._shared_by_name()
        for name, v in changes.items():
            if "." in name:
                unit, local = name.split(".", 1)
                self.values.setdefault(unit, {})[local] = float(v)
            else:
                p = shared[name]
                for b in p.bindings:
                    if b.status == "drives":
                        self.values.setdefault(b.unit, {})[b.param] = float(v)
        return r

    def current(self) -> dict[str, float]:
        """Every value a person can set: shared ones by name, the rest as unit.name."""
        out = {}
        bound = {(b.unit, b.param) for p in self.shared.values() for b in p.bindings}
        for p in self.shared.values():
            out[p.name] = self._shared_now(p)
        for uid, u in self.units.items():
            if not u.built and (u.answer or uid in self.values):  # undo / reset leave a unit to be rebuilt: its values are still its values
                self.unit(uid)
            if not u.built:
                continue
            assert u.prog is not None
            for name, prm in u.prog.params.items():
                if (uid, name) not in bound:
                    out[f"{uid}.{name}"] = self.values.get(uid, {}).get(name, prm.value)
        return out

    # ── history ──────────────────────────────────────────────────────────────

    def _state(self) -> dict:
        return {"values": copy.deepcopy(self.values), "shared": copy.deepcopy(self.shared),
                "answers": {uid: copy.deepcopy(u.answer) for uid, u in self.units.items()}, "unlinked": set(self.unlinked),
                "groups": copy.deepcopy(self.layout.groups), "accepted": set(self.accepted), "relations": copy.deepcopy(self.relations),
                "plan": copy.deepcopy(self.stated_plan), "domain": copy.deepcopy(self.domain), "semantics": copy.deepcopy(self.semantics),
                # the drawing this state belongs to: a feature operation makes a new revision of it, and undo goes back to the old one
                "revision_of": (self.dr, self.layout, self.import_state), "lineage": copy.deepcopy(self.lineage)}

    def _push(self) -> None:
        self.history.append(self._state())
        self.future.clear()
        del self.history[:-100]
        self.revision += 1

    def _restore(self, st: dict) -> None:
        swapped = st["revision_of"][0] is not self.dr if st.get("revision_of") else False
        if swapped:  # another revision of the drawing: its entities are not this one's, so nothing of this one's units is kept
            self.dr, self.layout, self.import_state = st["revision_of"]
            self.path = self.dr.path
            self.units, self.unit_of_view = {}, {}
        relayout = swapped or (st["unlinked"] != self.unlinked or st.get("accepted", set()) != self.accepted
                    or [(g.id, g.kind, g.items) for g in st["groups"]] != [(g.id, g.kind, g.items) for g in self.layout.groups])
        self.values, self.shared, self.unlinked = st["values"], st["shared"], st["unlinked"]
        self.accepted, self.relations = st.get("accepted", set()), st.get("relations", [])
        self.stated_plan = st.get("plan", {})
        self.domain = st.get("domain", [])
        self.semantics = st.get("semantics") or {"status": [], "annotations": {}, "notes": []}
        self.lineage = st.get("lineage", [])
        self.layout.groups = st["groups"]
        if relayout:
            self._relayout()
        for uid, ans in st["answers"].items():
            if uid in self.units and self.units[uid].answer != ans:
                self.units[uid].answer = ans
                self.units[uid].prog = None

    def set_plan(self, plan: dict) -> None:
        """Keep the plan an agent run stated (one undoable step)."""
        self._push()
        self.stated_plan = plan

    def undo(self) -> bool:
        if not self.history:
            return False
        self.future.append(self._state())
        self._restore(self.history.pop())
        self.revision += 1
        return True

    def redo(self) -> bool:
        if not self.future:
            return False
        self.history.append(self._state())
        self._restore(self.future.pop())
        self.revision += 1
        return True

    # ── shared parameters ────────────────────────────────────────────────────

    def _names_in_use(self) -> set[str]:
        names = set(self._shared_by_name())
        for u in self.units.values():
            if u.built:
                assert u.prog is not None
                names |= set(u.prog.params) | set(u.prog.formulas) | {r.name for r in u.prog.relations}
        return names

    def share(self, name: str, targets: list[tuple[str, str] | tuple[str, str, str]], label: str = "", evidence: list[str] | None = None,
              source: str = "person") -> SharedParam:
        """One named size driving several units: each target names it in a unit — (unit, candidate c…) or (unit, from
        line, to line). All must measure the same; each unit is rebuilt by the validated engine and must DRIVE it there.
        Refused as a whole (nothing changes) if any target does not hold."""
        if not PASCAL.match(name or "") or GENERIC.match(name):
            raise SheetError(f"{name!r} is not a PascalCase engineering name")
        if name in self._shared_by_name():
            raise SheetError(f"{name} is already shared")
        if len(targets) < 1:
            raise SheetError("name at least one view's size")
        before = self._state()
        measured = []
        bindings = []
        for t in targets:
            uid = t[0]
            u = self.unit(uid)
            assert u.an is not None
            assert u.prog is not None
            an, um = u.an, u.sub.units_mm
            if len(t) == 2 and t[1] not in an.clusters and t[1] in u.prog.params:  # the unit's own value, by its name
                prm = u.prog.params[t[1]]
                measures = prm.measures
                cid = next((c.id for c in an.clusters.values() if c.name == t[1]), None)
                if cid is None and measures is None:
                    raise SheetError(f"{t[1]} in {uid} is not measured between two lines")
                if u.answer and t[1] != name and any(p.get("name") == t[1] for p in u.answer.get("parameters", [])):
                    u.answer = rename_in_answer(u.answer, t[1], name)  # its own name gives way to the shared one
                    u.prog = None
                    u = self.unit(uid)
                    assert u.an is not None
                    assert u.prog is not None
                    cid = cid if cid in u.an.clusters else None
                t = (uid, cid) if cid else (uid, *cast(tuple[str, str], measures))
            if len(t) == 2:
                cid = t[1]
                c = an.clusters.get(cid)
                if c is None:
                    raise SheetError(f"{uid} has no candidate {cid}")
                value, entry, b = c.value * um, {"candidate": cid}, Binding(unit=uid, param=name, candidate=cid)
            else:
                a, d = t[1], t[2]
                if a not in an.datums or d not in an.datums or an.datums[a].axis != an.datums[d].axis:
                    raise SheetError(f"{uid}: {a} and {d} are not two lines on one axis")
                value = abs(an.datums[d].value - an.datums[a].value) * um
                entry, b = {"from_datum": a, "to_datum": d}, Binding(unit=uid, param=name, datums=(a, d))
            adopt = False
            if name in u.prog.params or any(r.name == name for r in u.prog.relations):
                if not self._same_size(u, name, entry):
                    raise SheetError(f"{name} already names something else in {uid}: rename it there first")
                adopt = True  # the unit already calls THIS size by that name (parametrized first, linked after): it is bound as is
            measured.append((uid, value))
            answer = copy.deepcopy(u.answer) if u.answer else copy.deepcopy(EMPTY_ANSWER)
            # the candidate may already carry a name in this unit: the shared name takes its place everywhere
            for p in answer.get("parameters", []):
                if adopt:
                    break
                if entry.get("candidate") and p.get("candidate") == entry["candidate"]:
                    answer = rename_in_answer(answer, p["name"], name)
                    break
            else:
                answer["parameters"].append({"name": name, "label": label or name, "component": "", "value": round(value, 6), **entry,
                                             "evidence": list(evidence or [])[:4], "reason": "shared across views"})
            u.answer = answer
            u.prog = None
            bindings.append(b)
        ref = measured[0][1]
        bad = [(uid, v) for uid, v in measured if abs(v - ref) > max(1.0, 2e-3 * ref)]
        if bad:
            self._restore(before)
            raise SheetError(f"{name}: the views do not state one size ({', '.join(f'{u}: {v:.1f} mm' for u, v in measured)})")
        sid = f"S{len(self.shared) + 1}"
        while sid in self.shared:
            sid = f"S{int(sid[1:]) + 1}"
        p = SharedParam(id=sid, name=name, label=label or name, value=ref, unit="mm", bindings=bindings, evidence=list(evidence or []), source=source)
        self.shared[sid] = p
        for b in bindings:
            self._bind_status(self.unit(b.unit), b)
        refused = [b for b in bindings if b.status != "drives"]
        if refused and all(b.status == "refused" for b in refused) and len(refused) == len(bindings):
            self._restore(before)
            raise SheetError(f"{name} drives none of its views: " + "; ".join(f"{b.unit}: {b.reason}" for b in refused))
        self.history.append(before)
        self.future.clear()
        self.revision += 1
        return p

    @staticmethod
    def _same_size(u: Unit, name: str, entry: dict) -> bool:
        """Whether the unit's own `name` measures the very lines a share target names (the same size, not a namesake)."""
        assert u.an is not None
        assert u.prog is not None
        prm = u.prog.params.get(name)
        if prm is None or not prm.measures:
            return False
        pair = set(prm.measures)
        if entry.get("candidate"):
            c = u.an.clusters.get(entry["candidate"])
            return bool(c) and any({u.an.gaps[g].a, u.an.gaps[g].b} == pair for g in c.gaps if g in u.an.gaps)
        return {entry.get("from_datum"), entry.get("to_datum")} == pair

    def growth(self, name: str) -> list[dict]:
        """How each view takes a value growing: which of its two lines moves (end / start), both about a centre line,
        or the size slides whole — measured, so a person can see it and choose otherwise (`anchor`)."""
        shared = self._shared_by_name().get(name)
        pairs = [(b.unit, b.param) for b in shared.bindings] if shared else [tuple(name.split(".", 1))] if "." in name else []
        if not pairs:
            raise SheetError(f"no parameter {name}")
        out = []
        for uid, local in pairs:
            u = self.unit(uid)
            assert u.prog is not None
            prm = u.prog.params.get(local)
            if prm is None or not prm.measures:
                out.append({"unit": uid, "mode": "none", "why": f"{local} is not measured between two lines in {uid}"})
                continue
            a, b = prm.measures
            v0, v1 = u.prog.datum_values(), u.prog.datum_values({local: prm.value + 1.0})
            if v0[b] < v0[a]:
                a, b = b, a
            um = u.sub.units_mm
            da, db = (v1[a] - v0[a]) * um, (v1[b] - v0[b]) * um
            # the mode names the line that STAYS (as `anchor` takes it): start — it grows at its end, and so on
            mode = ("start" if abs(da) < 1e-6 and abs(db - 1) < 1e-6 else "end" if abs(db) < 1e-6 and abs(da + 1) < 1e-6
                    else "centre" if abs(da + 0.5) < 1e-6 and abs(db - 0.5) < 1e-6 else "slides" if abs(da - db) < 1e-6 else "other")
            out.append({"unit": uid, "from": a, "to": b, "moves": {a: round(da, 6), b: round(db, 6)}, "mode": mode,
                        "why": {"start": f"{a} stays, {b} moves", "end": f"{b} stays, {a} moves", "centre": "both lines move about the centre",
                                "slides": "the size moves whole", "other": "the lines move unevenly"}[mode],
                        "intent": design_intent.explain(u.answer or {}, local), **self._open_direction(u, local)})
        return out

    @staticmethod
    def _open_direction(u: Unit, local: str) -> dict:
        """What the design intent could NOT give this size: its axis ended undecided (`undecided`: why, and the lines in the way), or it was left out of
        its structure's growth (`left_out`: why) — and the choices a person already made about it (`settled`, each can be taken back)."""
        ans = u.answer or {}
        out: dict[str, Any] = {}
        for ax in ans.get("intent_axes", []):
            if ax.get("status") == "undecided" and local in (ax.get("drivers") or []):
                out["undecided"] = {"axis": ax.get("axis"), "assembly": ax.get("assembly"), "evidence": ax.get("evidence") or [],
                                    "blocked": ax.get("blocked") or [], "drivers": ax.get("drivers") or []}
            elif local in [x.get("name") for x in ax.get("dropped") or []]:
                out["left_out"] = {"axis": ax.get("axis"), "status": ax.get("status"),
                                   "why": next(x.get("why") for x in ax["dropped"] if x.get("name") == local)}
        mine = {s["choice"]: {"choice": s["choice"], "title": s["title"], "kind": s["kind"]} for s in ans.get("settled", []) if local in (s.get("drivers") or [])}
        if mine:
            out["settled"] = list(mine.values())
        return out

    def anchor(self, name: str, uid: str, mode: str) -> dict:
        """Choose how a value grows in one unit: `start` — its start line stays and everything beyond grows away from it;
        `end` — the other way; `centre` — the assembly stays about the centre line. Written as an accepted plan for the
        WHOLE assembly the value belongs to (every other size keeps its drawn value: walls, haunches, slabs), committed
        only if it measures right on the sheet; otherwise refused with the reason and nothing changes."""
        policy = {"start": "start_fixed", "end": "end_fixed", "centre": "centered"}.get(mode)
        if policy is None:
            raise SheetError("anchor is start, end or centre")
        shared = self._shared_by_name().get(name)
        local = next((b.param for b in shared.bindings if b.unit == uid), None) if shared else name.split(".", 1)[1] if "." in name else None
        if local is None:
            raise SheetError(f"no local parameter for {name} in {uid}")
        u = self.unit(uid)
        assert u.prog is not None
        prm = u.prog.params.get(local or "")
        if prm is None or not prm.measures and not pairs_of(u.prog, u.answer, local):
            raise SheetError(f"{name} is not measured between two lines in {uid}")
        pairs = pairs_of(u.prog, u.answer, local)
        lines = {x for p in pairs for x in p}
        ans = copy.deepcopy(u.answer) if u.answer else copy.deepcopy(EMPTY_ANSWER)
        # an earlier choice written as formulas on these lines (by the old pair-only anchor) is cleared first
        ans["datum_formulas"] = [f for f in ans.get("datum_formulas", []) if f.get("datum") not in lines]
        if ans != (u.answer or {}):
            self.commit_answer(uid, ans)
            u = self.unit(uid)
            assert u.prog is not None
        prog0, ans0 = self._plain(uid)
        plan = build_plan(prog0, ans0, {"id": f"A_{local}", "driver": {"parameter": local, "pairs": pairs},
                                        "anchor": {"policy": policy, "source": "person"}}, sheet=self._plan_sheet(uid))
        # this is a choice about one value: questions about attached parts are answered by what the set-out does now
        if plan["status"] == "needs_decision" and all(q["about"].startswith("attached:") for q in plan["questions"]):
            decisions = {q["about"]: "follow" for q in plan["questions"]}
            plan = build_plan(prog0, ans0, {"id": f"A_{local}", "driver": {"parameter": local, "pairs": pairs},
                                            "anchor": {"policy": policy, "source": "person"}, "decisions": decisions}, sheet=self._plan_sheet(uid))
        if plan["status"] != "ready":
            raise SheetError(f"{name} cannot grow from its {mode} in {uid}: " + "; ".join(plan["conflicts"][:2] + [q["text"] for q in plan["questions"]][:1]))
        self.commit_answer(uid, with_plan(ans0, accept(plan)))
        g = next(x for x in self.growth(name) if x["unit"] == uid)
        return {**g, "plan": plan["id"], "anchor_line": (plan.get("anchor") or {}).get("line")}

    # ── an axis the design intent could not decide (design_intent.py): the ways to settle it, each tried for real ────────────────────

    SETTLE_BUDGET_S = 60.0  # how long looking for ways to settle one axis may take (each is a whole unit built and checked)

    def _local_name(self, name: str, uid: str) -> str:
        shared = self._shared_by_name().get(name)
        local = next((b.param for b in shared.bindings if b.unit == uid), None) if shared else name.split(".", 1)[1] if "." in name else None
        if local is None:
            raise SheetError(f"no local parameter for {name} in {uid}")
        return local

    def _dry_commit(self, uid: str, answer: dict, discard_values: bool = False) -> str:
        """Whether the whole sheet would accept this answer for the unit, with nothing kept either way: "" when it would, else the reason."""
        state, rev, depth, future, live = self._state(), self.revision, len(self.history), list(self.future), self._live
        try:
            self._commit_answer(uid, answer, None, discard_values)
            return ""
        except SheetError as exc:
            return str(exc)
        finally:
            self._restore(state)
            del self.history[depth:]
            self.future, self.revision, self._live = future, rev, live
            self.units[uid].prog = None  # built again from the answer it has, when something asks

    def _try_settle(self, uid: str, local: str, base: dict, ctx: dict, edits: list[design_intent.Edit]) -> tuple[dict | None, str]:
        """One way of settling the axis, tried for real: the answer written with it, the unit built, the intent derived around it, then the whole sheet
        asked whether it would hold. (the choice with what it would do, "") when it settles the axis and breaks nothing; (None, why not) otherwise."""
        dec, build, sheet = ctx["decision"], ctx["build"], ctx["sheet"]
        title = design_intent.title_of(edits)
        names = design_intent.names_of(dec)
        relaxed = design_intent.apply_edits(base, edits, dec.axis, sorted(names))
        try:
            prog1, rep1 = build(relaxed)
        except (KeyError, ExprError, ArithmeticError, ValueError, AssertionError) as exc:
            return None, f"{title}: the unit does not build with it ({exc})"
        now = {(e["code"], e["item"]): e["message"] for e in rep1.errors()}
        new = [m for k, m in now.items() if k not in ctx["errors"]]
        if new:
            return None, f"{title}: it breaks something that held ({new[0][:160]})"
        other = [p for p in ctx["intent"].plans if (p.get("driver") or {}).get("axis") not in (None, dec.axis)]
        found = design_intent.resolve(prog1, relaxed, build, sheet=sheet, axes=(dec.axis,), seed=other)
        got = design_intent.decisions_of(found, dec.axis, names)
        if not got or any(d.status == "undecided" for d in got):
            return None, f"{title}: it does not settle it ({'still undecided' if got else 'no size would be left to decide it'})"
        for before in ctx["intent"].axes:  # what was decided stays decided
            if before is dec or before.status == "undecided" or before.axis != dec.axis:
                continue
            if any(d.status == "undecided" for d in design_intent.decisions_of(found, before.axis, design_intent.names_of(before))):
                return None, f"{title}: it would leave {', '.join(sorted(design_intent.names_of(before))[:3])} undecided"
        try:
            with_i, found = self._with_intent(uid, relaxed)  # the whole unit, both axes, as a commit will derive it
        except (SheetError, KeyError, ExprError, ArithmeticError, ValueError, AssertionError) as exc:
            return None, f"{title}: the intent cannot be worked out with it ({exc})"
        got = design_intent.decisions_of(found, dec.axis, names)
        if not got or any(d.status == "undecided" for d in got):
            return None, f"{title}: it does not settle it once the whole unit is decided"
        main = next((d for d in got if local in design_intent.names_of(d)), got[0])
        prog2, _rep2 = build(with_i)
        info = design_intent.describe(ctx["program"], prog2, edits, main, local)
        if info["collateral"]:
            return None, f"{title}: it would also stop {', '.join(info['collateral'])} being an input"
        discards = sorted(n for n in self.values.get(uid, {}) if n not in prog2.params)
        problem = self._dry_commit(uid, with_i, discard_values=bool(discards))
        if problem:
            return None, f"{title}: {problem.removeprefix('refused, nothing changed: ')[:240]}"
        return {"id": design_intent.choice_id(edits), "title": title, "kinds": sorted({e.kind for e in edits}),
                "edits": [{"kind": e.kind, "target": e.target, "lines": e.lines} for e in edits], **info,
                "asked_in_growth": local in main.drivers, "discards": discards}, ""

    def settle_options(self, name: str, uid: str) -> dict:
        """The ways to settle a size whose direction of growth the design intent could not decide (no side could stay without breaking something):
        changes only a person may make — leave a pinned level free, release a held part, read a size instead of setting it — each TRIED FOR REAL as
        `design_intent._attempt` tries a side: written into the answer, the unit built, the intent derived around it, the whole sheet asked. Only what
        settles the axis and breaks nothing is offered, with what it does (which side stays, what moves, what stops being an input); what was tried and
        did not hold is said. Nothing is changed. Kept for the revision it was worked out on."""
        import time

        local = self._local_name(name, uid)
        key = (self.revision, uid, local)
        self._settle_cache = {k: v for k, v in self._settle_cache.items() if k[0] == self.revision}  # what was found on another revision is not true of this one
        if key in self._settle_cache:
            return self._settle_cache[key]
        u = self.unit(uid)
        base = design_intent.strip(u.answer or copy.deepcopy(EMPTY_ANSWER))
        build = self._trial_builder(uid)
        prog0, rep0 = build(base)
        sheet = self._plan_sheet(uid)
        intent = design_intent.resolve(prog0, base, build, sheet=sheet)
        mine = [a for a in intent.axes if local in design_intent.names_of(a)]  # one value can belong to two structures (its occurrences lie in both)
        dec = next((a for a in mine if a.status == "undecided"), mine[0] if mine else None)
        out: dict[str, Any] = {"unit": uid, "name": name, "local": local, "revision": self.revision, "axis": dec.axis if dec else None,
                               "assembly": dec.assembly if dec else None, "status": dec.status if dec else "none",
                               "evidence": dec.evidence if dec else [], "blocked": dec.blocked if dec else [], "drivers": sorted(design_intent.names_of(dec)) if dec else [],
                               "choices": [], "rejected": [], "notes": []}
        if dec is None or dec.status != "undecided":
            out["notes"].append(f"{local} is not a size whose direction is undecided" if dec is not None else f"{local} belongs to no structure's growth")
            self._settle_cache[key] = out
            return out
        ctx = {"decision": dec, "build": build, "sheet": sheet, "intent": intent, "program": prog0,
               "errors": {(e["code"], e["item"]) for e in rep0.errors()}}
        sets, notes = design_intent.edits_for(base, dec)
        out["notes"] += notes
        started = time.monotonic()
        for k, edits in enumerate(sets):
            if time.monotonic() - started > self.SETTLE_BUDGET_S:
                out["notes"].append(f"stopped after {int(time.monotonic() - started)} s: {len(sets) - k} more change(s) were not tried")
                break
            choice, why = self._try_settle(uid, local, base, ctx, edits)
            if choice is not None:
                out["choices"].append(choice)
            else:
                out["rejected"].append({"id": design_intent.choice_id(edits), "why": why})
        rank = {"level": 0, "part": 1, "reading": 2}
        out["choices"].sort(key=lambda c: (not c["asked_in_growth"], len(c["left_out"]), c["status"] != "decided", len(c["stops_being_input"]),
                                           min(rank[k] for k in c["kinds"]), c["id"]))
        self._settle_cache[key] = out
        return out

    def settle(self, name: str, uid: str, choice: str, discard_values: bool = False) -> dict:
        """Settle an undecided direction with one of the ways `settle_options` found: written as the person's own decision (the answer changes — a level's
        role, a part released, a size read — and is recorded in `settled`), the intent derived around it, committed only if the whole sheet still holds,
        in ONE step (one undo takes it back). Refused, with nothing changed, if the sheet changed since, or it no longer settles the axis."""
        opts = self.settle_options(name, uid)
        pick = next((c for c in opts["choices"] if c["id"] == choice), None)
        if pick is None:
            raise SheetError(f"{choice} does not settle {name} on this sheet (it changed since, or it never held): ask for the ways again")
        if pick["discards"] and not discard_values:
            raise SheetError(f"it would discard the value you set for {', '.join(pick['discards'])}: confirm that, or reset it first")
        u = self.unit(uid)
        edits = [design_intent.Edit(e["kind"], e["target"], list(e.get("lines") or [])) for e in pick["edits"]]
        relaxed = design_intent.apply_edits(u.answer or {}, edits, opts["axis"], opts["drivers"])
        depth = len(self.history)
        res = self.commit_answer(uid, relaxed, discard_values=discard_values)
        mine = [a for a in (res.get("intent") or {}).get("axes", []) if a["axis"] == opts["axis"]
                and (set(a["drivers"]) | {x["name"] for x in a["dropped"]}) & set(opts["drivers"])]
        if res.get("intent_skipped") or not mine or any(a["status"] == "undecided" for a in mine):
            if len(self.history) > depth:  # committed, but without the direction it was for: put back, not a half-made choice
                self.undo()
                self.future.clear()
            raise SheetError(f"{pick['title']} was not kept: " + (res.get("intent_skipped") or "it no longer settles the direction once the sheet is checked"))
        self._settle_cache = {}
        g = next((x for x in self.growth(name) if x["unit"] == uid), {})
        return {**g, "choice": pick["id"], "title": pick["title"]}

    def unsettle(self, uid: str, choice: str) -> dict:
        """Take a settled choice back: what it changed is written back (the level pinned again, the part held again, the size an input), the intent
        derived again, one undoable step."""
        u = self.unit(uid)
        try:
            answer = design_intent.take_back(u.answer or {}, choice)
        except ValueError as exc:
            raise SheetError(str(exc)) from exc
        self.commit_answer(uid, answer)
        self._settle_cache = {}
        return {"unit": uid, "choice": choice, "revision": self.revision}

    def _plan_sheet(self, uid: str) -> dict:
        """What a plan needs to know of the sheet: its revision, the unit, which views entities are on, shared names."""
        u = self.units[uid]
        group = self.layout.item_group

        def views_of(items):
            return sorted(
                v
                for i in items
                if 0 <= i < len(u.back)
                if (v := group.get(u.back[i])) is not None
            )

        shared = {b.param: p.name for p in self.shared.values() for b in p.bindings if b.unit == uid}

        def other_units(local):
            p = self._shared_by_name().get(shared.get(local, ""))
            return sorted({b.unit for b in p.bindings if b.unit != uid}) if p else []

        kinds = sorted({g.view_type for g in self.layout.groups if g.id in u.views})
        return {"revision": self.revision, "unit": uid, "views_of": views_of, "shared": shared, "other_units": other_units, "view_types": kinds}

    def plan(self, uid: str, request: dict) -> dict:
        """A plan for an instruction (or a structured request) on one unit — read, resolved, predicted; nothing changes."""
        prog0, ans0 = self._plain(uid)
        return build_plan(prog0, ans0, request, sheet=self._plan_sheet(uid))

    def apply_plan(self, uid: str, request: dict, expected_revision: int | None = None, discard_values: bool = False) -> dict:
        """Make a plan binding and the value asked for real — or nothing. The plan is built again from the request and
        the person's decisions (never taken on trust from the page), accepted only when nothing is open, committed only
        if every promise measures right on the whole sheet, and the value it asks for is applied in the same step (one
        undo takes both back). Refused: SheetError with the reasons, the sheet as it was."""
        if expected_revision is not None and expected_revision != self.revision:
            raise SheetError(f"stale: the sheet changed since this plan was made (revision {expected_revision} → {self.revision}); plan again")
        prog0, ans0 = self._plain(uid)
        plan = build_plan(prog0, ans0, request, sheet=self._plan_sheet(uid))
        if plan["status"] != "ready":
            raise SheetError(f"plan {plan['id']} is {plan['status']}: " + "; ".join(plan["conflicts"][:3] + [q["text"] for q in plan["questions"]][:3]))
        state, rev, depth = self._state(), self.revision, len(self.history)
        res = self.commit_answer(uid, with_plan(ans0, accept(plan)), discard_values=discard_values)
        want = (plan.get("driver") or {}).get("requested_value")
        applied = None
        if want is not None:
            key = self._key(uid, plan["driver"]["parameter"])
            r = self.regenerate({key: float(want)})
            if not r.ok:
                self._restore(state)
                del self.history[depth:]
                self.revision = rev
                self.units[uid].prog = None
                self.unit(uid)
                raise SheetError(f"refused, nothing changed: {plan['driver']['parameter']} = {want:g} does not hold: " + "; ".join(r.errors[:3]))
            shared = self._shared_by_name().get(key)
            if shared:
                for b in shared.bindings:
                    if b.status == "drives":
                        self.values.setdefault(b.unit, {})[b.param] = float(want)
            else:
                self.values.setdefault(uid, {})[plan["driver"]["parameter"]] = float(want)
            applied = {"name": key, "value": float(want), "changed": len(r.changed), "by_view": r.by_view}
        final_unit = self.unit(uid)
        assert final_unit.prog is not None
        checks = next(
            (
                x
                for x in final_unit.prog.intent.get("plans", [])
                if x["id"] == plan["id"]
            ),
            None,
        )
        return {**res, "plan": plan, "checks": checks, "applied": applied}

    # ── feature operations: a change the regeneration cannot make, as a new revision of the drawing ─────────

    def plan_feature(self, uid: str, request: dict) -> dict:
        """What a change of COUNT (add / remove instances of a repeated unit) would do on a unit, and whether it can be done faithfully: the whole
        chain is run (the derived drawing, its re-import, the parametrization carried over, the production guards at the new count) and thrown away.
        `status` ready | refused | needs_decision — with the reasons. The sheet is not touched."""
        from . import feature

        return feature.plan_count(self, uid, request)

    def apply_feature(self, uid: str, request: dict, expected_revision: int | None = None, plan_id: str | None = None, out_dir: str | None = None) -> dict:
        """Make a feature operation real — or nothing. The plan is built again from the request (never taken on trust); only a plan that is ready
        is applied; the derived drawing becomes the sheet's next REVISION with every name carried over, and one undo takes it back. Refused:
        SheetError with the reasons, the sheet exactly as it was (and no file left behind)."""
        from . import feature

        if expected_revision is not None and expected_revision != self.revision:
            raise SheetError(f"stale: the sheet changed since this plan was made (revision {expected_revision} → {self.revision}); plan again")
        cand = feature.build_candidate(self, uid, request, Path(out_dir) if out_dir else feature.default_dir(self))
        plan = cand.plan
        if plan_id is not None and plan_id != plan.get("id"):
            feature.discard(cand)
            raise SheetError(f"the plan {plan_id} is not the plan this sheet would make now ({plan.get('id')}): plan again")
        if cand.new is None:
            raise SheetError("refused, nothing changed: " + "; ".join(plan.get("refusals") or [q["text"] for q in plan.get("questions", [])] or [plan.get("status", "")]))
        came_from = self.path
        self._push()
        self._adopt(cast(SheetModel, cand.new))
        self.lineage = [*self.lineage, {"plan": plan["id"], "from": came_from, "to": self.path, "request": plan.get("request"),
                                        "from_count": plan.get("from_count"), "to_count": plan.get("to_count")}]
        return {"plan": plan, "path": self.path, "revision": self.revision, "from": came_from}

    def _adopt(self, new: SheetModel) -> None:
        """Another revision of the drawing becomes this sheet (history and runs are kept; the step was pushed by the caller)."""
        self.dr, self.path, self.layout, self.links = new.dr, new.path, new.layout, new.links
        self.unlinked, self.accepted = new.unlinked, new.accepted
        self.units, self.unit_of_view = new.units, new.unit_of_view
        self.shared, self.values, self.domain = new.shared, new.values, new.domain
        self.relations, self.stated_plan, self.questions = new.relations, new.stated_plan, new.questions
        self.import_state = new.import_state

    def _key(self, uid: str, local: str) -> str:
        """The name a person changes a unit's value by: its shared name, else unit.local."""
        for p in self.shared.values():
            for b in p.bindings:
                if b.unit == uid and b.param == local:
                    return p.name
        return f"{uid}.{local}"

    def unshare(self, name: str) -> None:
        p = self._shared_by_name().get(name)
        if p is None:
            raise SheetError(f"{name} is not shared")
        self._push()
        del self.shared[p.id]

    def _unit_names(self, uid: str) -> set[str]:
        u = self.unit(uid)
        assert u.prog is not None
        return set(u.prog.params) | set(u.prog.formulas) | {r.name for r in u.prog.relations}

    def namesakes(self, name: str, besides: set[str] | None = None) -> list[tuple[str, float | None]]:
        """The other units that have a value (or a measured quantity) of this name, with its number: the same word for the same size seen again
        (to be shared) or for a different size (which stays the unit's own) — the engine cannot tell, and says so."""
        out = []
        for uid, u in self.units.items():
            if not u.built or uid in (besides or set()) or u.prog is None:
                continue
            if name in u.prog.params:
                out.append((uid, round(self.values.get(uid, {}).get(name, u.prog.params[name].value), 3)))
            else:
                rel = next((r for r in u.prog.relations if r.name == name), None)
                if rel is not None:
                    out.append((uid, None))
        return out

    def rename(self, old: str, new: str) -> None:
        """A parameter's name, everywhere it is used (formulas, relations, behaviours, every view it is bound in). Its
        value and what it drives do not change. Refused — and nothing changes, not even the revision — when the NEW name is not an engineering
        name, is a shared size, or is already a value of a unit it would land in; a name another unit uses for ITS value is no obstacle (a
        unit's values are its own: U01.ClearSpan and U02_03.ClearSpan are two values), and `namesakes` says so to whoever asks."""
        if not PASCAL.match(new or "") or GENERIC.match(new):
            raise SheetError(f"the NEW name {new!r} is not a PascalCase engineering name — it must look like ClearHeadroom: words each starting with a capital, "
                             "letters and digits only, no unit prefix, and not one of the analysis' own names (GapX6, ThkY1 …)")
        shared = self._shared_by_name().get(old)
        if "." in old and shared is None:
            uid, local = old.split(".", 1)
            if uid not in self.units:
                raise SheetError(f"the OLD name {old!r} names no unit {uid}: use a shared name, 'U01.name', or the bare name of a value of the open unit")
            targets = [(uid, local)]
        elif shared is not None:
            targets = [(b.unit, b.param) for b in shared.bindings]
        else:
            raise SheetError(f"the OLD name {old!r} is not a shared name or 'unit.name': use a shared name, 'U01.name', or the bare name of a value of the open unit")
        if new in self._shared_by_name():
            raise SheetError(f"the NEW name {new} is already a shared size; use another name, or share_sizes to bring this one under it")
        for uid, local in targets:
            if new == local:
                raise SheetError(f"{old} already has the name {new}")
            if new in self._unit_names(uid):
                raise SheetError(f"the NEW name {new} is already a value of {uid}: one unit cannot have two values of one name")
        state, rev = self._state(), self.revision
        self._push()
        try:
            for uid, local in targets:
                u = self.unit(uid)
                assert u.an is not None
                assert u.prog is not None
                if local not in u.prog.params and not any(r.name == local for r in u.prog.relations):
                    raise SheetError(f"{uid} has no value {local}")
                if not u.answer or not any(p.get("name") == local for p in u.answer.get("parameters", []) + u.answer.get("levels", [])):
                    # a value the geometry found: name it by its candidate (or its lines) so the name survives a rebuild
                    prm = u.prog.params.get(local)
                    if prm is None:
                        raise SheetError(f"{local} in {uid} is not a parameter")
                    cid = next((c.id for c in u.an.clusters.values() if c.name == local), None)
                    ans = copy.deepcopy(u.answer) if u.answer else copy.deepcopy(EMPTY_ANSWER)
                    entry = {"candidate": cid} if cid else {"from_datum": prm.measures[0], "to_datum": prm.measures[1]} if prm and prm.measures else None
                    if entry is None:
                        raise SheetError(f"{local} in {uid} is not measured between two lines: it cannot be named")
                    ans["parameters"].append({"name": new, "label": new, "component": "", "value": round(prm.value, 6), **entry, "reason": "named by a person"})
                    u.answer = ans
                else:
                    u.answer = rename_in_answer(u.answer, local, new)
                if local in self.values.get(uid, {}):
                    self.values[uid][new] = self.values[uid].pop(local)
                u.prog = None
            if shared is not None:
                shared.name = new
                for b in shared.bindings:
                    b.param = new
            for uid, _ in targets:
                self.unit(uid)
        except (SheetError, KeyError, ExprError, ArithmeticError):  # a refused rename leaves nothing behind: not a half-renamed unit, not a revision
            self._restore(state)
            self.history.pop()
            self.revision = rev
            for uid, _l in targets:
                self.units[uid].prog = None
            raise

    def accept_link(self, a: str, b: str) -> None:
        """Take a projection link the geometry shows but too weakly to take alone (a person, or the AI, confirmed it)."""
        lk = next((x for x in self.links if {x["a"], x["b"]} == {a, b}), None)
        if lk is None:
            raise SheetError(f"{a} and {b} share no set-out lines: they cannot be drawn in projection")
        self._push()
        key = (lk["a"], lk["b"])
        self.accepted.add(key)
        self.unlinked.discard(key)
        self._group_units(self.units)

    def set_answer(self, uid: str, answer: dict) -> None:
        """A unit's parametrization replaced (the AI agent's, or a person's), undoable."""
        u = self.unit(uid)
        self._push()
        u.answer, u.prog = answer, None
        self.unit(uid)

    def pristine_analysis(self, uid: str):
        """A copy of the unit's analysis as found — the same candidate, occurrence and line ids the sheet uses (layout
        distances between linked views already dropped) — for work that applies answers to it on its own (the agent)."""
        u = self.unit(uid)
        assert u.an is not None
        assert u.snap is not None
        assert u.gap_clusters is not None
        an = copy.deepcopy(u.an)
        if u.orig_datums is not None:
            an.datums = {did: copy.deepcopy(d) for did, d in u.orig_datums.items()}
        if u.orig_slot_datum is not None:
            an.slot_datum = dict(u.orig_slot_datum)
        for cid, (name, acc, gaps) in u.snap.items():
            if cid in an.clusters:
                c = an.clusters[cid]
                c.name, c.accepted, c.gaps = name, acc, [g for g in gaps if g in an.gaps]
        for gid, cl in u.gap_clusters.items():
            if gid in an.gaps:
                an.gaps[gid].cluster = cl
        an.cache.clear()
        return an

    def _trial_builder(self, uid: str):
        """`build(answer) → (program, report)`: how a candidate answer is tried for real — the unit built from it — with the unit exactly as it was
        afterwards (its answer, program, report and the status of every value it shares)."""
        u = self.units[uid]

        def build(ans: dict):
            keep = (u.answer, u.prog, u.report)
            bound = [(b, b.status, b.reason) for p in self.shared.values() for b in p.bindings if b.unit == uid]
            u.answer, u.prog = ans, None
            self._trial += 1
            try:
                self._build(u)
                assert u.prog is not None
                return u.prog, u.report
            finally:
                self._trial -= 1
                u.answer, u.prog, u.report = keep
                for b, status, reason in bound:
                    b.status, b.reason = status, reason

        return build

    def _with_intent(self, uid: str, answer: dict) -> tuple[dict, design_intent.Intent]:
        """The answer with the design intent of its sizes written in (design_intent.py): which side of each size stays, decided by evidence and
        tried for real. The program the evidence is read from is the answer's own, without any plan the engine derived earlier."""
        self.unit(uid)
        build = self._trial_builder(uid)
        base = design_intent.strip(answer)
        prog, _rep = build(base)
        found = design_intent.resolve(prog, base, build, sheet=self._plan_sheet(uid))
        return design_intent.with_intent(base, found), found

    def _plain(self, uid: str) -> tuple[Program, dict]:
        """The unit's program and answer WITHOUT the plans the engine derived (design intent): what a person's plan is built on. What a person asks
        for is worked out on the drawing as it is, never on the engine's own default — the intent is derived again around their choice."""
        u = self.unit(uid)
        ans = u.answer or copy.deepcopy(EMPTY_ANSWER)
        plain = design_intent.strip(ans)
        if plain == ans:
            assert u.prog is not None
            return u.prog, ans
        prog, _rep = self._trial_builder(uid)(plain)
        return prog, plain

    def commit_answer(self, uid: str, answer: dict, expected_revision: int | None = None, discard_values: bool = False,
                      keep_unnamed_as_drawn: bool = False, intent: bool = True) -> dict:
        """Replace a unit's parametrization only if the WHOLE sheet still holds; otherwise nothing changes.

        With `intent` (the default) the design intent of the unit's sizes — which side of each stays when it changes, what moves with it — is derived
        first and committed with the answer. It is an addition: if the answer does not hold WITH it, the answer is committed without it and the
        result says why (`intent_skipped`); a plan a person made is never replaced by it.

        The rules below are those of the answer itself:

        Refused (SheetError, the state untouched) when: the sheet changed since the work began (`expected_revision`);
        the unit no longer regenerates; a size it shares with other views stops driving here (that view would stop
        following); an accepted plan's promise does not measure right (V16); or a value a person set would be lost
        (unless `discard_values`: the person said so) — a person's edit is never dropped silently.

        `keep_unnamed_as_drawn`: in the same step, the measured sizes nobody named or used are kept as drawn (generic.py) — the unit is
        left with the values somebody chose. Only when the drawing comes out exactly as it was; otherwise they stay inputs, and it is said."""
        if not intent or os.environ.get("AUTOPARAM_DESIGN_INTENT", "").strip().lower() in ("0", "off", "no", "false"):
            return self._commit_answer(uid, answer, expected_revision, discard_values, keep_unnamed_as_drawn)
        base = design_intent.strip(answer)
        skipped = ""
        found = None
        try:
            with_i, found = self._with_intent(uid, answer)
        except (SheetError, KeyError, ExprError, ArithmeticError, ValueError, AssertionError) as exc:  # the intent is an addition, never the reason a commit fails
            with_i, skipped = None, f"the design intent could not be worked out: {type(exc).__name__}: {exc}"
        if with_i is not None and found is not None and (found.plans or found.axes):
            try:
                res = self._commit_answer(uid, with_i, expected_revision, discard_values, keep_unnamed_as_drawn)
                return {**res, "intent": found.as_dict()}
            except SheetError as exc:
                skipped = f"the design intent was not kept: {exc}"
        res = self._commit_answer(uid, base, expected_revision, discard_values, keep_unnamed_as_drawn)
        if skipped:
            res["intent_skipped"] = skipped
        elif found is not None:
            res["intent"] = found.as_dict()
        return res

    def derive_missing_intent(self, progress=None) -> dict:
        """Work saved before the design intent existed (or written without it) gets it when it is opened: at the drawn values nothing moves, only what a
        change of a size does to the drawing. It is not a step of the person's — the undo history is as it was. Units whose intent is derived are not
        looked at again (their answer says so, `intent_axes`)."""
        todo = [uid for uid, u in self.units.items() if u.answer and u.answer.get("parameters") and "intent_axes" not in u.answer]
        if not todo:
            return {}
        depth = len(self.history)
        out: dict[str, Any] = {}
        for n, uid in enumerate(todo, 1):
            if progress is not None:
                progress(f"working out which side of each size stays: {uid} ({n} of {len(todo)})")
            out.update(self.resolve_intent(uid))
        del self.history[depth:]
        return out

    def resolve_intent(self, uid: str | None = None) -> dict:
        """Derive the design intent of every parametrized unit (or one) and commit what changed — ONE undoable step for the lot. For work that was
        parametrized before the intent was derived, or after a person changed what the intent rests on. Returns, per unit, what was decided."""
        uids = [uid] if uid else [k for k, u in self.units.items() if u.answer and u.answer.get("parameters")]
        for k in uids:
            if k not in self.units:
                raise SheetError(f"no unit {k}")
        depth = len(self.history)
        out: dict[str, Any] = {}
        for k in uids:
            u = self.unit(k)
            if not u.answer:
                continue
            try:
                with_i, found = self._with_intent(k, u.answer)
            except (SheetError, KeyError, ExprError, ArithmeticError, ValueError, AssertionError) as exc:
                out[k] = {"skipped": f"{type(exc).__name__}: {exc}"}
                continue
            if with_i == u.answer:
                out[k] = {**found.as_dict(), "changed": False}
                continue
            try:
                self._commit_answer(k, with_i)
                out[k] = {**found.as_dict(), "changed": True}
            except SheetError as exc:
                out[k] = {"skipped": str(exc)}
        if len(self.history) > depth + 1:  # one step for the lot: undo goes back to before any of them
            del self.history[depth + 1:]
        return out

    def _commit_answer(self, uid: str, answer: dict, expected_revision: int | None = None, discard_values: bool = False,
                       keep_unnamed_as_drawn: bool = False) -> dict:
        if expected_revision is not None and expected_revision != self.revision:
            raise SheetError(f"stale: the sheet changed while this was being worked out (revision {expected_revision} → {self.revision}); "
                             "nothing was applied — run it again on the current sheet")
        u = self.unit(uid)
        assert u.an is not None
        assert u.prog is not None
        before_status = {(p.name, b.unit): b.status for p in self.shared.values() for b in p.bindings if b.unit == uid}
        state = self._state()
        rev = self.revision
        self._push()
        u.answer, u.prog = answer, None
        try:
            self.unit(uid)
        except (KeyError, ExprError, ArithmeticError) as exc:
            self._restore(state)
            self.history.pop()
            self.revision = rev
            raise SheetError(f"{uid}: the answer does not build: {exc}") from exc
        assert u.an is not None
        assert u.prog is not None
        problems = []
        for p in self.shared.values():
            for b in p.bindings:
                if b.unit == uid and before_status.get((p.name, uid)) == "drives" and b.status != "drives":
                    problems.append(f"{p.name} is shared with {', '.join(x.unit for x in p.bindings if x.unit != uid)} but would no longer "
                                    f"drive {uid} ({b.status}: {b.reason or 'not a value of the new answer'}) — that view would stop following")
        for p in self.shared.values():  # measured, not only named: the shared size still moves its own lines here
            for b in p.bindings:
                if b.unit != uid or b.status != "drives":
                    continue
                prm = u.prog.params.get(b.param)
                if prm is not None and prm.measures is not None:
                    a, d = cast(tuple[str, str], prm.measures)
                    if not _drives(
                        u.prog,
                        b.param,
                        a,
                        d,
                        {
                            **{datum.id: datum.value for datum in u.an.datums.values()},
                            **u.prog.datum_values(),
                        },
                    ):
                        problems.append(
                            f"{p.name} no longer moves its lines in {uid} ({a}–{d}): the views sharing it would not follow"
                        )
        problems += [f"{e['item']}: {e['message']}" for e in (u.report.errors() if u.report else []) if e["code"] == "V16"]
        lost = sorted(n for n in self.values.get(uid, {}) if n not in u.prog.params)
        if lost and not discard_values:
            problems.append(f"the value(s) you set for {', '.join(lost)} would be lost (the new parametrization has no such value): "
                            "keep them, or confirm discarding them")
        others = {x.unit for p in self.shared.values() if any(b.unit == uid for b in p.bindings) for x in p.bindings}
        r = self.regenerate(units={uid} | others)
        problems += r.errors
        if problems:
            self._restore(state)
            self.history.pop()
            self.revision = rev
            for q in self.shared.values():  # the bindings' statuses as they were
                for b in q.bindings:
                    if b.unit == uid and (q.name, uid) in before_status:
                        b.status = before_status[(q.name, uid)]
            self.units[uid].prog = None
            self.unit(uid)
            raise SheetError("refused, nothing changed: " + "; ".join(problems[:4]))
        if lost:  # the person confirmed: the values fall back to the drawing
            self.values[uid] = {k: v for k, v in self.values[uid].items() if k not in lost}
        kept = self._keep_unnamed_as_drawn(uid)[0] if keep_unnamed_as_drawn else []
        return {"unit": uid, "revision": self.revision, "values_dropped": lost, "kept_as_drawn": kept}

    # ── the measured sizes nobody named (generic.py) ──────────────────────────────

    def unclaimed_generic(self, uid: str) -> list[str]:
        """The generated values of a built unit that nobody named or used: not set by a person, not shared, not in anything the agent wrote."""
        u = self.unit(uid)
        assert u.prog is not None
        shared = {b.param for p in self.shared.values() for b in p.bindings if b.unit == uid}
        return generic.unclaimed(u.prog, u.answer, set(self.values.get(uid, {})), shared)

    def _drawing_of(self, units: set[str]) -> SheetRegen:
        return self.regenerate(units=units)

    def _keep_unnamed_as_drawn(self, uid: str) -> tuple[list[str], str]:
        """Inside a step the caller has begun (`_push`): keep this unit's unclaimed generated values as drawn, recorded in its answer. Applied only
        when the unit and everything it shares comes out EXACTLY as it was — otherwise nothing changes and the reason is returned."""
        u = self.units[uid]
        names = self.unclaimed_generic(uid)
        if not names or not u.answer:
            return [], ""
        assert u.prog is not None
        others = {x.unit for p in self.shared.values() if any(b.unit == uid for b in p.bindings) for x in p.bindings}
        scope = {uid} | others
        before = self._drawing_of(scope).reg
        old_answer, old_prog = u.answer, u.prog
        rows = [generic.frozen_row(u.prog, n) for n in names]
        u.answer = {**u.answer, "frozen": [*u.answer.get("frozen", []), *rows]}
        u.prog = None
        try:
            self.unit(uid)
            after_sr = self._drawing_of(scope)
        except (KeyError, ExprError, ArithmeticError) as exc:
            u.answer, u.prog = old_answer, old_prog
            return [], f"kept as drawn did not build: {exc}"
        a = after_sr.reg
        gone = sorted(n for n in names if u.prog is not None and n in u.prog.params)
        moved = {i for i, pts in a.pts.items() if i not in before.pts or any(abs(x[0] - y[0]) > 1e-9 or abs(x[1] - y[1]) > 1e-9
                                                                         for x, y in zip(pts, before.pts[i], strict=False))}
        moved |= {i for i in set(a.texts) | set(before.texts)  # the note as it reads (an entry that merely says what is drawn is no change)
                  if a.texts.get(i, self.dr.items[i].text) != before.texts.get(i, self.dr.items[i].text)}
        moved |= {i for i, r in a.radius.items() if abs(before.radius.get(i, r) - r) > 1e-9}
        unlinked = sorted(set(old_prog.text_links) - set(u.prog.text_links)) if u.prog is not None else []  # a note that stated a size must still follow it
        if after_sr.errors or moved or gone or unlinked:
            u.answer, u.prog = old_answer, old_prog
            self.unit(uid)
            why = (f"{len(moved)} entities would move" if moved else after_sr.errors[0] if after_sr.errors else
                   f"{len(unlinked)} note(s) would stop following their size" if unlinked else f"{gone[0]} would still be an input")
            return [], f"kept as drawn would change the drawing ({why}): they stay inputs"
        return names, ""

    def purge_unclaimed_generic_values(self, uid: str | None = None, dry_run: bool = False) -> dict:
        """Keep every measured size nobody named or used as drawn, in one undoable step: `uid`'s unit, or every parametrized unit. The drawing
        does not change (checked: a unit whose points, notes or radii would move is left alone and said). Idempotent. `dry_run`: say what
        would be kept, change nothing."""
        todo = [uid] if uid else [k for k, u in self.units.items() if u.answer and u.built]
        for k in todo:
            if k not in self.units:
                raise SheetError(f"no unit {k}")
            if not self.units[k].answer:
                raise SheetError(f"{k} is not parametrized: its measured sizes are all it has — nothing to keep as drawn")
        plan = {k: n for k in todo if (n := self.unclaimed_generic(k))}
        out: dict[str, Any] = {"dry_run": dry_run, "units": {k: len(v) for k, v in plan.items()}, "names": {k: v[:12] for k, v in plan.items()},
                               "kept": 0, "left_as_inputs": {}}
        if dry_run or not plan:
            out["would_keep"] = sum(len(v) for v in plan.values())
            out["revision"] = self.revision
            return out
        rev = self.revision
        self._push()
        for k in plan:
            kept, why = self._keep_unnamed_as_drawn(k)
            out["kept"] += len(kept)
            if why:
                out["left_as_inputs"][k] = why
        if not out["kept"]:  # nothing changed: no step
            self.history.pop()
            self.revision = rev
        out["revision"] = self.revision
        return out

    def unlock_part(self, uid: str, part: str) -> dict:
        """A person asks to edit work that was kept as drawn: the part (and what it is made of) stops being held, the sizes named on it are
        inputs again. One transaction like any other answer: refused, with nothing changed, if the sheet would no longer hold."""
        from .intent import descendants

        u = self.unit(uid)
        assert u.prog is not None
        parts = u.prog.intent.get("parts") or {}
        if part not in parts or not u.answer:
            raise SheetError(f"{uid} has no part {part}")
        names = {part} | descendants(parts, part)
        answer = copy.deepcopy(u.answer)
        was = {r.name for r in u.prog.relations if not r.name.startswith("R_")}
        for c in answer.get("components", []):
            if c.get("name") in names:
                c["parametrize"] = True
        for p in answer.get("parameters", []):
            if p.get("component") in names and p.get("recommended") is False:
                p["recommended"] = True
        self.commit_answer(uid, answer)
        assert self.units[uid].prog is not None
        now = {n for n in was if n in self.units[uid].prog.params}
        return {"unit": uid, "part": part, "unlocked": sorted(names), "inputs_again": sorted(now), "revision": self.revision}

    def release_frozen(self, uid: str, names: list[str] | None = None) -> dict:
        """Give kept-as-drawn sizes back as inputs (all of the unit's, or the ones named), one undoable step. The drawing does not change."""
        u = self.unit(uid)
        rows = list((u.answer or {}).get("frozen", []))
        if not rows:
            raise SheetError(f"{uid} has no sizes kept as drawn")
        want = set(names) if names else {r["name"] for r in rows}
        unknown = sorted(want - {r["name"] for r in rows})
        if unknown:
            raise SheetError(f"{', '.join(unknown)}: not kept as drawn in {uid}")
        self._push()
        u.answer = {**u.answer, "frozen": [r for r in rows if r["name"] not in want]}
        u.prog = None
        self.unit(uid)
        return {"unit": uid, "released": sorted(want), "revision": self.revision}

    def link(self, a: str, b: str, linked: bool) -> None:
        """Take or refuse a projection link between two views (their units are re-formed; a unit whose views changed
        loses its parametrization, said in the result)."""
        lk = next((x for x in self.links if {x["a"], x["b"]} == {a, b}), None)
        if lk is None:
            raise SheetError(f"{a} and {b} have no projection link")
        key = (lk["a"], lk["b"])
        self._push()
        if linked:
            self.unlinked.discard(key)
            if not lk["strong"]:
                self.accepted.add(key)
        else:
            self.accepted.discard(key)
            self.unlinked.add(key)
        self._group_units(self.units)

    # ── the views themselves: a person's corrections ─────────────────────────

    def _relayout(self) -> None:
        self.layout.item_group = {i: g.id for g in self.layout.groups for i in g.items}
        self.links = view_links(self.dr, self.layout)
        self._group_units(self.units)

    def set_view(self, vid: str, name: str | None = None, view_type: str | None = None, kind: str | None = None) -> None:
        """Rename a view, correct its type, or say what a group really is (a view, a table, notes…)."""
        g = next((x for x in self.layout.groups if x.id == vid), None)
        if g is None:
            raise SheetError(f"no view {vid}")
        self._push()
        if name is not None:
            g.name = name.strip()
        if view_type is not None:
            g.view_type = view_type
        if kind is not None and kind != g.kind:
            g.kind = kind
            self._relayout()
        g.evidence.append("corrected by a person")
        g.questions = [q for q in g.questions if not q.startswith("no title")] if name else g.questions

    def merge_views(self, ids: list[str]) -> str:
        """Several groups are one view (a figure the white space split): their entities join the first."""
        gs = [x for x in self.layout.groups if x.id in ids]
        if len(gs) < 2:
            raise SheetError("name two or more views to merge")
        self._push()
        keep = gs[0]
        for g in gs[1:]:
            keep.items = sorted(set(keep.items) | set(g.items))
            keep.titles += [t for t in g.titles if t not in keep.titles]
            if not keep.name and g.name:
                keep.name = g.name
        keep.kind = "view"
        pts = [p for i in keep.items for p in self.dr.items[i].pts]
        keep.bbox = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        keep.evidence.append(f"merged by a person from {', '.join(g.id for g in gs)}")
        self.layout.groups = [g for g in self.layout.groups if g not in gs[1:]]
        self._relayout()
        return keep.id

    def split_view(self, vid: str, box: tuple[float, float, float, float], name: str = "") -> str:
        """The entities of a view inside a box a person drew become a view of their own."""
        g = next((x for x in self.layout.groups if x.id == vid), None)
        if g is None:
            raise SheetError(f"no view {vid}")
        x0, y0, x1, y1 = box
        inside = []
        for i in g.items:
            pts = self.dr.items[i].pts
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                inside.append(i)
        if not inside or len(inside) == len(g.items):
            raise SheetError("the box must hold some, but not all, of the view's entities")
        self._push()
        g.items = sorted(set(g.items) - set(inside))
        n = 1
        while any(x.id == f"V{n:02d}" for x in self.layout.groups):
            n += 1
        new = Group(id=f"V{n:02d}", kind="view", items=sorted(inside), bbox=box, name=name, confidence=1.0,
                    evidence=[f"split from {vid} by a person"])
        self.layout.groups.append(new)
        self._relayout()
        return new.id

    # ── proposals ─────────────────────────────────────────────────────────────

    def shared_proposals(self, units: list[str] | None = None, limit: int = 40) -> list[dict]:
        """Sizes that two units both STATE (a dimension or a note gives the same number in each), most certain first.
        Equal sizes nobody states are not proposed: equal numbers alone are chance."""
        ids = units or sorted(self.units)
        stated: dict[str, list[tuple[float, str, str, list[str]]]] = {}
        for uid in ids:
            u = self.unit(uid)
            assert u.an is not None
            um = u.sub.units_mm
            rows = []
            for c in u.an.clusters.values():
                ev = [e.kind for e in c.evidence]
                if "dimension" not in ev and "text" not in ev:
                    continue
                rows.append((c.value * um, c.id, c.kind.value, [f"{e.kind}: {e.detail}" for e in c.evidence][:3]))
            stated[uid] = rows
        out = []
        for i, ua in enumerate(ids):
            for ub in ids[i + 1:]:
                for va, ca, ka, eva in stated[ua]:
                    if va < 50:
                        continue
                    for vb, cb, kb, evb in stated[ub]:
                        if abs(va - vb) <= max(0.5, 1e-3 * va):
                            out.append({"value": round(va, 1), "a": [ua, ca], "b": [ub, cb], "kinds": [ka, kb],
                                        "evidence": [f"{ua} {ca}: " + "; ".join(eva), f"{ub} {cb}: " + "; ".join(evb)],
                                        "views": [self.units[ua].views, self.units[ub].views]})
        out.sort(key=lambda p: -p["value"])
        return out[:limit]

    # ── impact ────────────────────────────────────────────────────────────────

    def impact(self, name: str, step: float | None = None) -> dict:
        """What a value moves, measured: change it a little, regenerate, compare — per view; and what stays."""
        shared = self._shared_by_name().get(name)
        cur = self.current()
        if name not in cur:
            raise SheetError(f"no value {name}")
        v = cur[name]
        dv = step if step else max(abs(v) * 0.05, 10.0)
        r = self.regenerate({name: v + dv})
        views_all = [g.id for g in self.layout.views()]
        moved_views = sorted(k for k in r.by_view if k)
        units = sorted({b.unit for b in shared.bindings}) if shared else [name.split(".", 1)[0]]
        parts: dict[str, list[str]] = {}
        for uid in units:
            u = self.unit(uid)
            assert u.prog is not None
            local = next((b.param for b in shared.bindings if b.unit == uid), None) if shared else name.split(".", 1)[1]
            reach = affects(u.prog).get(local or "", {})
            parts[uid] = reach.get("parts", [])
        return {"name": name, "value": v, "step": dv, "views": moved_views, "entities": len(r.changed),
                "per_view": r.by_view, "stays": [x for x in views_all if x not in moved_views], "units": units,
                "parts": parts, "errors": r.errors, "bindings": [asdict(b) for b in shared.bindings] if shared else []}

    def valid_range(self, name: str, factor: float = 4.0, steps: int = 12) -> dict:
        """How far a value can go either way before the sheet stops regenerating cleanly (found by halving the
        interval; the first problem met on each side is named) — the honest limits of a slider."""
        cur = self.current()
        if name not in cur:
            raise SheetError(f"no value {name}")
        v = cur[name]
        out = {"name": name, "value": v}
        for side, far in (("max", v * factor), ("min", max(v / factor, 1e-6))):
            r = self.regenerate({name: far})
            if r.ok:
                out[side], out[side + "_reason"] = far, f"still valid at {far:g} (not searched further)"
                continue
            good, bad, why = v, far, r.errors[0]
            for _ in range(steps):
                mid = (good + bad) / 2
                r = self.regenerate({name: mid})
                if r.ok:
                    good = mid
                else:
                    bad, why = mid, r.errors[0]
            out[side], out[side + "_reason"] = good, why
        return out

    # ── the baseline: what the drawing was, and the way back (baseline.py) ───────

    def original(self, name: str) -> list[dict]:
        """A value as the imported drawing has it, per unit it is bound in (value, how it was measured, whether it can be trusted)."""
        from .baseline import current_of, original_of, targets

        return [{"unit": uid, "param": local, "current": current_of(self, uid, local), **original_of(self, uid, local)} for uid, local in targets(self, name)]

    def reset_value(self, name: str) -> dict:
        from .baseline import reset_value

        return reset_value(self, name)

    def reset_drawing(self) -> dict:
        from .baseline import reset_drawing

        return reset_drawing(self)

    def card(self, name: str) -> dict:
        from .baseline import card

        return card(self, name)

    def highlight(self, name: str, step: float | None = None) -> dict:
        from .baseline import highlight

        return highlight(self, name, step)

    def deviation(self, entities: set[int] | None = None) -> dict:
        from .baseline import deviation

        return deviation(self, entities)

    # ── output ────────────────────────────────────────────────────────────────

    def scene(self, sr: SheetRegen | None = None) -> list[dict]:
        """Every entity of the sheet as drawn primitives, from the regenerated points where a unit was regenerated; each
        view's dimensions read at that view's own units."""
        sr = sr or self.regenerate()
        units_of = {}
        for u in self.units.values():
            for s in u.items:
                units_of[s] = u.sub.units_mm
        out = []
        for it in self.dr.items:
            if it.dxftype == "INSERT":
                continue
            pts = sr.reg.pts.get(it.index, it.pts)
            out.extend(primitives(it, pts, sr.reg.radius.get(it.index), sr.reg.texts.get(it.index), units_of.get(it.index, self.dr.units_mm)))
        return out

    def export(self, out_path: str) -> dict:
        """The original DXF with every regenerated entity written back (dimensions re-rendered, notes rewritten); then
        re-opened strictly."""
        sr = self.regenerate(units={uid for uid, u in self.units.items() if u.built})
        units_of = {s: u.sub.units_mm for u in self.units.values() for s in u.items}
        rep = write_dxf(SimpleNamespace(analysis=SimpleNamespace(drawing=self.dr), item_units_mm=units_of), sr.reg, out_path)  # the writer reads .analysis.drawing
        rep["audit"] = audit(out_path)
        rep["errors"] = sr.errors
        return rep

    # ── persistence ───────────────────────────────────────────────────────────

    def fingerprint(self) -> str:
        return hashlib.sha256(Path(self.path).read_bytes()).hexdigest()[:16]

    def to_dict(self) -> dict:
        """The parametric project: what a person or the AI decided, keyed to the DXF it was made on."""
        from .baseline import original_of

        originals: dict[str, dict] = {}  # the imported value of every value a person has changed (a record: it is re-derived from the DXF)
        for uid, vals in self.values.items():
            if uid in self.units:
                unit = self.unit(uid)
                assert unit.prog is not None
                originals[uid] = {
                    n: original_of(self, uid, n)["value"]
                    for n in vals
                    if n in unit.prog.params
                }
        import_groups = {g.key: g for g in self.import_state["groups"]}
        topology_changed = [g.key for g in self.layout.groups] != [g.key for g in self.import_state["groups"]]
        views = []
        for g in self.layout.groups:
            if not topology_changed and g.key in import_groups and (g.name, g.view_type, g.kind) == (import_groups[g.key].name, import_groups[g.key].view_type, import_groups[g.key].kind):
                continue
            row = {"id": g.id, "key": g.key, "name": g.name, "view_type": g.view_type, "kind": g.kind}
            if topology_changed or g.key not in import_groups:
                row.update({"items": g.items, "bbox": list(g.bbox), "titles": g.titles, "scale": g.scale, "units_mm": g.units_mm,
                            "confidence": g.confidence, "evidence": g.evidence, "questions": g.questions, "counts": g.counts})
            views.append(row)
        return {"format": "dxf-autoparam/sheet-1", "dxf": self.path, "fingerprint": self.fingerprint(), "revision": self.revision,
                "unlinked": sorted(list(k) for k in self.unlinked),
                "answers": {uid: u.answer for uid, u in self.units.items() if u.answer},
                "shared": [asdict(p) for p in self.shared.values()], "values": self.values, "originals": originals,
                "accepted": sorted(list(k) for k in self.accepted), "relations": self.relations, "plan": self.stated_plan, "questions": self.questions,
                "domain": self.domain, "lineage": self.lineage, "semantics": self.semantics, "agent_notes": self.agent_notes,
                "views": views, "prefs": self.prefs, "runs": self.runs[-200:]}

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, default=list))

    @classmethod
    def load(cls, project: str, dxf: str | None = None) -> SheetModel:
        d = json.loads(Path(project).read_text())
        dr, _ = read_dxf(dxf or d["dxf"])
        sm = cls(dr, unlinked={tuple(k) for k in d.get("unlinked", [])})
        if sm.fingerprint() != d.get("fingerprint"):
            raise SheetError("the DXF has changed since this project was saved: its views and values may not match")
        if d.get("accepted"):
            sm.accepted = {tuple(k) for k in d["accepted"]}
        views = d.get("views", [])
        if views and all("items" in v and "bbox" in v for v in views):
            sm.layout.groups = [Group(id=v["id"], kind=v["kind"], items=list(v["items"]), bbox=tuple(v["bbox"]), name=v.get("name", ""),
                                      view_type=v.get("view_type", "unknown"), titles=list(v.get("titles", [])), scale=v.get("scale"),
                                      units_mm=v.get("units_mm"), confidence=v.get("confidence", 0.0), evidence=list(v.get("evidence", [])),
                                      questions=list(v.get("questions", [])), counts=dict(v.get("counts", {})), key=v.get("key", ""))
                                for v in views]
            sm._relayout()
        elif views or d.get("accepted"):
            by_key = {g.key: g for g in sm.layout.groups}
            by_id = {g.id: g for g in sm.layout.groups}
            relayout = False
            for v in views:  # corrections a person made to the views (by content key: stable across sessions)
                g = by_key.get(v.get("key")) or by_id.get(v.get("id"))
                if g is not None:
                    if v.get("kind") and v["kind"] != g.kind:
                        relayout = True
                    g.name, g.view_type, g.kind = v.get("name", g.name), v.get("view_type", g.view_type), v.get("kind", g.kind)
            if relayout:
                sm._relayout()
            elif d.get("accepted"):
                sm._group_units(sm.units)
        sm.relations, sm.questions = d.get("relations", []), d.get("questions", [])
        sm.stated_plan = d.get("plan") or {}
        sm.domain = list(d.get("domain") or [])
        sm.lineage = list(d.get("lineage") or [])
        sm.semantics = d.get("semantics") or {"status": [], "annotations": {}, "notes": []}
        sm.agent_notes = d.get("agent_notes") or {"checklist": [], "learned": []}
        for uid, ans in d.get("answers", {}).items():
            if uid in sm.units:
                sm.units[uid].answer = ans
        for p in d.get("shared", []):
            sm.shared[p["id"]] = SharedParam(**{**p, "bindings": [Binding(**{**b, "datums": tuple(b["datums"]) if b.get("datums") else None})
                                                                      for b in p["bindings"]]})
        sm.values = {u: dict(v) for u, v in d.get("values", {}).items()}
        sm.prefs = {**sm.prefs, **(d.get("prefs") or {})}
        sm.runs = list(d.get("runs") or [])
        sm.revision = int(d.get("revision") or 0)  # the page and the pictures stamp what they show with it: a reopened sheet goes on from where it was
        return sm

