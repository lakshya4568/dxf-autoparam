"""One parametric model for a whole sheet: views that show the same structure change together.

    sm = SheetModel.open("gad.dxf")              # views found, projection links proposed / taken
    sm.shared_proposals()                          # sizes two units both state (with the evidence)
    sm.share("ClearSpan", [("U1", "c12"), ("U3", "c40")])
    r = sm.preview({"ClearSpan": 4000})            # every affected view regenerated, checked — nothing committed
    sm.apply({"ClearSpan": 4000})                  # committed only if every check passes; undo() / redo()
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
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace

from .analyse import analyse
from .display import primitives
from .dxf_read import read_dxf
from .dxf_write import audit, write_dxf
from .graph import affects
from .ir import Analysis, Drawing, Role
from .program import ExprError, Program
from .regen import Regenerated, regenerate_program
from .sheet import Group, SheetLayout, segment, view_drawing
from .validator import GENERIC, PASCAL, Report, apply, baseline

EMPTY_ANSWER = {"structure_type": "", "family": "other", "views": [], "summary": "", "components": [], "line_roles": [], "levels": [],
                "parameters": [], "datum_formulas": [], "relations": [], "behaviours": [], "constraints": [], "questions": []}
NAME_KEYS = ("name", "parameter", "target")
EXPR_KEYS = ("expr", "value")


class SheetError(ValueError):
    """A request the sheet model refuses, with the reason a person can act on."""


# ── projection links ─────────────────────────────────────────────────────────────


def _planes(dr: Drawing, items: list[int], q: float) -> tuple[set[int], set[int]]:
    """The set-out planes of a view: x and y of its structural vertices, on a grid of the coincidence tolerance."""
    xs, ys = set(), set()
    for i in items:
        it = dr.items[i]
        if it.role != Role.STRUCTURAL:
            continue
        for k in it.vertex_pts:
            xs.add(round(it.pts[k][0] / q))
            ys.add(round(it.pts[k][1] / q))
    return xs, ys


def _shared(a: set[int], b: set[int]) -> set[int]:
    """Planes in both, allowing one grid step either way (a coordinate on the edge of a grid cell)."""
    return {v for v in a if v in b or v - 1 in b or v + 1 in b}


def view_links(dr: Drawing, layout: SheetLayout, min_planes: int = 6, min_frac: float = 0.25) -> list[dict]:
    """Views drawn in projection with each other: one over the other sharing vertical set-out lines (an elevation and
    its plan), or side by side sharing horizontal ones (a section beside an elevation: its levels). Only views at the
    same drawing scale; `strong` when enough planes coincide to be design, not chance."""
    views = layout.views()
    q = max(dr.tol, 1e-9)
    planes = {v.id: _planes(dr, v.items, q) for v in views}
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
    dropped: str = ""  # why a parametrization it had was dropped (its views changed)

    @property
    def built(self) -> bool:
        return self.prog is not None


def rename_in_answer(answer: dict, old: str, new: str) -> dict:
    """Every place an answer names a parameter or level — names, behaviour targets, expressions — renamed."""
    word = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])")

    def walk(o):
        if isinstance(o, dict):
            return {k: (new if k in NAME_KEYS and v == old else word.sub(new, v) if k in EXPR_KEYS and isinstance(v, str) else walk(v))
                    for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o

    return walk(answer)


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
        self._group_units()

    @classmethod
    def open(cls, path: str) -> SheetModel:
        dr, _ = read_dxf(path)
        return cls(dr)

    # ── units ────────────────────────────────────────────────────────────────

    def _group_units(self, keep: dict[str, Unit] | None = None) -> None:
        views = self.layout.views()
        parent = {v.id: v.id for v in views}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for lk in self.links:
            if lk["strong"] and (lk["a"], lk["b"]) not in self.unlinked:
                parent[find(lk["b"])] = find(lk["a"])
        groups: dict[str, list[Group]] = {}
        for v in views:
            groups.setdefault(find(v.id), []).append(v)
        old = keep or {}
        self.units, self.unit_of_view = {}, {}
        for members in groups.values():
            ids = sorted(v.id for v in members)
            uid = "U" + "_".join(v[1:] for v in ids)  # stable: named by its views (URL-safe)
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
        return u

    def _build(self, u: Unit) -> None:
        """The unit's program, from its answer (or the geometry alone): the same validated engine as a single view."""
        if u.an is None:
            u.an = analyse(u.sub)
            self._drop_layout_gaps(u)
            u.snap = {cid: (c.name, c.accepted, list(c.gaps)) for cid, c in u.an.clusters.items()}
            u.gap_clusters = {gid: g.cluster for gid, g in u.an.gaps.items()}
        else:  # apply() renames and splits candidates: start from the analysis as found
            for cid, (name, acc, gaps) in u.snap.items():
                c = u.an.clusters[cid]
                c.name, c.accepted, c.gaps = name, acc, list(gaps)
            for gid, cl in u.gap_clusters.items():
                u.an.gaps[gid].cluster = cl
        if u.answer:
            u.prog, u.report = apply(u.an, u.answer, selection={"hold": [], "exclude": [], "drop": []})
        else:
            u.report = Report()
            u.prog = baseline(u.an, rep=u.report)
        for b in (b for p in self.shared.values() for b in p.bindings if b.unit == u.id):
            self._bind_status(u, b)

    def _drop_layout_gaps(self, u: Unit) -> None:
        """Views linked one over the other share their vertical lines; the distance from one view's horizontal lines to
        the other's is only where they sit on the sheet, never a size of the structure — dropped (and the other way
        round for views side by side)."""
        if len(u.views) < 2:
            return
        cross = set()
        for lk in self.links:
            if {lk["a"], lk["b"]} <= set(u.views) and lk["strong"]:
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
        pts, radius, texts = {}, {}, {}
        errors, warnings, changed = [], [], []
        by_view: dict[str, int] = {}
        measured: dict[str, dict[str, float]] = {}
        for uid in sorted(todo):
            u = self.unit(uid)
            vals = self._values_for(u, changes)
            try:
                r = regenerate_program(u.prog, vals)
            except (KeyError, ExprError, ArithmeticError) as exc:
                errors.append(f"{uid}: cannot regenerate: {exc}")
                continue
            errors += [f"{uid}: {i}" for i in r.issues]
            for k, p in r.pts.items():
                s = u.back[k]
                pts[s] = p
                orig = self.dr.items[s].pts
                if any(abs(a[0] - b[0]) > 1e-9 or abs(a[1] - b[1]) > 1e-9 for a, b in zip(p, orig, strict=False)):
                    changed.append(s)
                    v = self.layout.item_group.get(s, "")
                    by_view[v] = by_view.get(v, 0) + 1
            for k, rad in r.radius.items():
                radius[u.back[k]] = rad
            for k, t in r.texts.items():
                texts[u.back[k]] = t
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
        reg = Regenerated(values=dict(changes), datum={}, pts=pts, radius=radius, texts=texts, issues=list(errors))
        return SheetRegen(reg=reg, changed=sorted(changed), by_view=by_view, errors=errors, warnings=warnings, measured=measured)

    def preview(self, changes: dict[str, float]) -> SheetRegen:
        return self.regenerate(changes)

    def apply(self, changes: dict[str, float]) -> SheetRegen:
        """Commit a change only if the whole sheet regenerates cleanly; otherwise nothing changes."""
        r = self.regenerate(changes)
        if not r.ok:
            return r
        self._push()
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
            if not u.built:
                continue
            for name, prm in u.prog.params.items():
                if (uid, name) not in bound:
                    out[f"{uid}.{name}"] = self.values.get(uid, {}).get(name, prm.value)
        return out

    # ── history ──────────────────────────────────────────────────────────────

    def _state(self) -> dict:
        return {"values": copy.deepcopy(self.values), "shared": copy.deepcopy(self.shared),
                "answers": {uid: copy.deepcopy(u.answer) for uid, u in self.units.items()}, "unlinked": set(self.unlinked),
                "groups": copy.deepcopy(self.layout.groups)}

    def _push(self) -> None:
        self.history.append(self._state())
        self.future.clear()
        del self.history[:-100]

    def _restore(self, st: dict) -> None:
        relayout = st["unlinked"] != self.unlinked or [(g.id, g.kind, g.items) for g in st["groups"]] != [(g.id, g.kind, g.items) for g in self.layout.groups]
        self.values, self.shared, self.unlinked = st["values"], st["shared"], st["unlinked"]
        self.layout.groups = st["groups"]
        if relayout:
            self._relayout()
        for uid, ans in st["answers"].items():
            if uid in self.units and self.units[uid].answer != ans:
                self.units[uid].answer = ans
                self.units[uid].prog = None

    def undo(self) -> bool:
        if not self.history:
            return False
        self.future.append(self._state())
        self._restore(self.history.pop())
        return True

    def redo(self) -> bool:
        if not self.future:
            return False
        self.history.append(self._state())
        self._restore(self.future.pop())
        return True

    # ── shared parameters ────────────────────────────────────────────────────

    def _names_in_use(self) -> set[str]:
        names = set(self._shared_by_name())
        for u in self.units.values():
            if u.built:
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
            an, um = u.an, u.sub.units_mm
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
            if name in u.prog.params or any(r.name == name for r in u.prog.relations):
                raise SheetError(f"{name} already names something else in {uid}: rename it there first")
            measured.append((uid, value))
            answer = copy.deepcopy(u.answer) if u.answer else copy.deepcopy(EMPTY_ANSWER)
            # the candidate may already carry a name in this unit: the shared name takes its place everywhere
            for p in answer.get("parameters", []):
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
        return p

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
                                "slides": "the size moves whole", "other": "the lines move unevenly"}[mode]})
        return out

    def anchor(self, name: str, uid: str, mode: str) -> dict:
        """Choose how a value grows in one unit: `start` — its start line stays and it grows at its end; `end` — the
        other way; `centre` — about the centre line between them. Written as the person's formula (it outranks what the engine chose);
        refused, with nothing changed, when the drawing has no centre line there or the sheet does not hold."""
        if mode not in ("start", "end", "centre"):
            raise SheetError("anchor is start, end or centre")
        shared = self._shared_by_name().get(name)
        local = next((b.param for b in shared.bindings if b.unit == uid), None) if shared else name.split(".", 1)[1] if "." in name else None
        u = self.unit(uid)
        prm = u.prog.params.get(local or "")
        if prm is None or not prm.measures:
            raise SheetError(f"{name} is not measured between two lines in {uid}")
        a, b = prm.measures
        an = u.an
        if an.datums[b].value < an.datums[a].value:
            a, b = b, a
        self._push()
        before = copy.deepcopy(u.answer)
        # from the engine's own set-out: an earlier choice for these lines is cleared first
        ans = copy.deepcopy(u.answer) if u.answer else copy.deepcopy(EMPTY_ANSWER)
        ans["datum_formulas"] = [f for f in ans.get("datum_formulas", []) if f.get("datum") not in (a, b)]
        u.answer, u.prog = ans, None
        u = self.unit(uid)
        if mode == "start":  # the start line stays (on what it was set out from); the end line follows the value
            formulas = [{"datum": a, "expr": self._pinned(u, a, local, b)}, {"datum": b, "expr": f"{a} + {local}"}]
        elif mode == "end":
            formulas = [{"datum": b, "expr": self._pinned(u, b, local, a)}, {"datum": a, "expr": f"{b} - {local}"}]
        else:
            mid = (an.datums[a].value + an.datums[b].value) / 2
            axis = next((d.id for d in an.datums.values() if d.axis == an.datums[a].axis and d.id not in (a, b)
                         and abs(d.value - mid) <= an.drawing.tol), None)
            if axis is None:
                u.answer, u.prog = before, None
                self.history.pop()
                self.unit(uid)
                raise SheetError(f"no centre line between {a} and {b} in {uid}: choose the start or the end")
            formulas = [{"datum": a, "expr": f"{axis} - 0.5 * {local}"}, {"datum": b, "expr": f"{axis} + 0.5 * {local}"}]
        ans = copy.deepcopy(ans)
        ans["datum_formulas"] = ans["datum_formulas"] + formulas
        u.answer, u.prog = ans, None
        self.unit(uid)
        g = next(x for x in self.growth(name) if x["unit"] == uid)
        r = self.regenerate()
        if g["mode"] != mode or not r.ok:
            u.answer, u.prog = before, None
            self.history.pop()
            self.unit(uid)
            why = "; ".join(r.errors[:2]) or f"the engine could not keep it ({g['why']})"
            raise SheetError(f"{name} cannot grow from its {mode} in {uid}: {why}")
        return g

    @staticmethod
    def _pinned(u: Unit, d: str, local: str, avoid: str) -> str:
        """Line d set out as drawn from a line that does not move with the value and does not hang on `avoid` (the
        line about to be set out from d): one its formula names, else the nearest such line on its axis."""
        from .intent import _depends_on

        prog, um, an = u.prog, u.sub.units_mm, u.an
        v0 = prog.datum_values()
        v1 = prog.datum_values({local: prog.params[local].value + 1.0})

        def ok(r: str) -> bool:
            return r in v0 and r not in (d, avoid) and abs(v1[r] - v0[r]) < 1e-12 and avoid not in _depends_on(prog, r)

        refs = [r for r in sorted(re.findall(r"[a-z]+\d+", prog.formulas.get(d, ""))) if ok(r)]
        if not refs:
            axis = an.datums[d].axis
            refs = [r for r in sorted((x.id for x in an.datums.values() if x.axis == axis and x.id in v0), key=lambda r: abs(v0[r] - v0[d]))[:40] if ok(r)][:1]
        if refs:
            off = (v0[d] - v0[refs[0]]) * um
            return f"{refs[0]} {'+' if off >= 0 else '-'} {abs(off):.6f}".rstrip("0").rstrip(".")
        return f"{v0[d] * um:.6f}".rstrip("0").rstrip(".")

    def unshare(self, name: str) -> None:
        p = self._shared_by_name().get(name)
        if p is None:
            raise SheetError(f"{name} is not shared")
        self._push()
        del self.shared[p.id]

    def rename(self, old: str, new: str) -> None:
        """A parameter's name, everywhere it is used (formulas, relations, behaviours, every view it is bound in). Its
        value and what it drives do not change. Refused when the new name is taken or not an engineering name."""
        if not PASCAL.match(new or "") or GENERIC.match(new):
            raise SheetError(f"{new!r} is not a PascalCase engineering name")
        if new in self._names_in_use():
            raise SheetError(f"{new} is already used on this sheet")
        shared = self._shared_by_name().get(old)
        if "." in old and shared is None:
            uid, local = old.split(".", 1)
            targets = [(uid, local)]
        elif shared is not None:
            targets = [(b.unit, b.param) for b in shared.bindings]
        else:
            raise SheetError(f"no parameter {old}: a shared name, or unit.name")
        self._push()
        for uid, local in targets:
            u = self.unit(uid)
            if local not in u.prog.params and not any(r.name == local for r in u.prog.relations):
                raise SheetError(f"{uid} has no parameter {local}")
            if not u.answer or not any(p.get("name") == local for p in u.answer.get("parameters", []) + u.answer.get("levels", [])):
                # a value the geometry found: name it by its candidate (or its lines) so the name survives a rebuild
                prm = u.prog.params.get(local)
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

    def link(self, a: str, b: str, linked: bool) -> None:
        """Take or refuse a projection link between two views (their units are re-formed; a unit whose views changed
        loses its parametrization, said in the result)."""
        key = (a, b) if (a, b) in {(lk["a"], lk["b"]) for lk in self.links} else (b, a)
        self._push()
        if linked:
            self.unlinked.discard(key)
        else:
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
        rep = write_dxf(SimpleNamespace(analysis=SimpleNamespace(drawing=self.dr)), sr.reg, out_path)  # the writer reads .analysis.drawing
        rep["audit"] = audit(out_path)
        rep["errors"] = sr.errors
        return rep

    # ── persistence ───────────────────────────────────────────────────────────

    def fingerprint(self) -> str:
        return hashlib.sha256(Path(self.path).read_bytes()).hexdigest()[:16]

    def to_dict(self) -> dict:
        """The parametric project: what a person or the AI decided, keyed to the DXF it was made on."""
        return {"format": "dxf-autoparam/sheet-1", "dxf": self.path, "fingerprint": self.fingerprint(),
                "unlinked": sorted(list(k) for k in self.unlinked),
                "answers": {uid: u.answer for uid, u in self.units.items() if u.answer},
                "shared": [asdict(p) for p in self.shared.values()], "values": self.values}

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, default=list))

    @classmethod
    def load(cls, project: str, dxf: str | None = None) -> SheetModel:
        d = json.loads(Path(project).read_text())
        dr, _ = read_dxf(dxf or d["dxf"])
        sm = cls(dr, unlinked={tuple(k) for k in d.get("unlinked", [])})
        if sm.fingerprint() != d.get("fingerprint"):
            raise SheetError("the DXF has changed since this project was saved: its views and values may not match")
        for uid, ans in d.get("answers", {}).items():
            if uid in sm.units:
                sm.units[uid].answer = ans
        for p in d.get("shared", []):
            sm.shared[p["id"]] = SharedParam(**{**p, "bindings": [Binding(**{**b, "datums": tuple(b["datums"]) if b.get("datums") else None})
                                                                      for b in p["bindings"]]})
        sm.values = {u: dict(v) for u, v in d.get("values", {}).items()}
        return sm

