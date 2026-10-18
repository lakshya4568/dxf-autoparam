"""The deterministic validator: what of a proposed parametrization is TRUE of the drawing.

A proposal (from Gemini, a person, or a template) is applied to the geometric baseline
one claim at a time, and each claim is checked against the geometry:

  V1  ids exist (datums, outlines, candidates)
  V2  a parameter's value IS the measured value it names (candidate value, or datum-to-datum)
  V3  names are PascalCase, unique, not generic placeholders
  V4  a formula parses, uses only known datums and parameters, creates no cycle
  V5  a formula reproduces its datum exactly at the current values (so the drawing is unchanged)
  V6  a level held as an input is a horizontal datum the drawing states a level for
  V7  a relation equals what it says it measures — and whether the model keeps it under every edit
  V8  every parameter regenerates a valid drawing at ±10% (no outline inverts, collapses or crosses itself)
  V9  every parameter drives something

A claim that fails is rejected with the reason; the rest is merged. The result is always
a valid model — at worst the geometric baseline itself.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, field

from .build import Decisions, build
from .cadjson import entity_id, entity_index
from .intent import (
    check_behaviours,
    check_constraints,
    descendants,
    drive_dimensions,
    freeze_params,
    heal_growth_breaks,
    held_only_lines,
    hold_parts,
    impact_summary,
    measure_impact,
    resolve_parts,
)
from .ir import Analysis
from .plan import compile_plans, prepare_plans, verify_plan
from .program import (
    ANGLE,
    LENGTH,
    RATIO,
    Component,
    ExprError,
    Param,
    Program,
    Relation,
    _num,
    check_dims,
    dim_of_unit,
    evaluate,
    from_model,
    names_in,
)
from .regen import check_change, datum_users, regenerate_program
from .topology import of as topo_of

PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
NUM = re.compile(r"\d+(?:\.\d+)?")
GENERIC = re.compile(r"^(Thk|Open|Gap|Step|Pitch|Off|Dim|Leg|Run|Rise|Dia|Ring)[XY]?\d+$")


@dataclass
class Finding:
    code: str
    severity: str  # error (rejected) | warn | info
    item: str
    message: str

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "item": self.item, "message": self.message}


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    accepted: dict[str, int] = field(default_factory=dict)
    rejected: dict[str, int] = field(default_factory=dict)

    def ok(self, kind: str) -> None:
        self.accepted[kind] = self.accepted.get(kind, 0) + 1

    def bad(self, kind: str, code: str, item: str, message: str) -> None:
        self.rejected[kind] = self.rejected.get(kind, 0) + 1
        self.findings.append(Finding(code, "error", item, message))

    def warn(self, code: str, item: str, message: str) -> None:
        self.findings.append(Finding(code, "warn", item, message))

    def errors(self) -> list[dict]:
        return [f.as_dict() for f in self.findings if f.severity == "error"]


REVIEW_BELOW = 0.75  # an AI claim below this confidence is put in front of a person
# Who sets a line, strongest first: a site level, the person's / AI's formula, a named dimension, a constraint, a held or
# existing part. A later rule (a slope, a heal, the generic set-out) never takes a line one of these set.
FIRM = ("ai", "dimension", "constraint", "held", "existing", "kept", "plan")


def _tol_mm(an: Analysis) -> float:
    return max(0.5, 2 * an.drawing.tol * an.drawing.units_mm)


def apply(an: Analysis, answer: dict, base_decisions: Decisions | None = None, hold_existing: bool = False,
          selection: dict | None = None) -> tuple[Program, Report]:
    """Apply a structured proposal (ai.schema.AIAnswer as a dict) to the drawing; return the validated program.

    selection: {"hold": [part names kept as drawn], "exclude": [parameter names kept as drawn]}; None takes the
    AI's own recommendations (parts with parametrize=false held, parameters with recommended=false excluded)."""
    rep = Report()
    u = an.drawing.units_mm
    tol = _tol_mm(an)
    datums = an.datums
    dec = base_decisions or Decisions()

    # ── levels (V1, V6): site inputs pinned, water levels checked only ─────────────
    stated = {d for d, *_ in an.stated_levels}
    used_names: set[str] = set()
    for lv in answer.get("levels", []):
        d, name, role = lv.get("datum"), lv.get("name", ""), lv.get("role")
        if d not in datums or datums[d].axis != "y":
            rep.bad("level", "V1", d or "?", f"{d} is not a horizontal datum of this drawing")
            continue
        if not PASCAL.match(name or ""):
            rep.bad("level", "V3", name, f"level name {name!r} is not PascalCase")
            continue
        if role in ("site_input", "check_only"):
            if d not in stated:
                rep.warn("V6", name, f"{name} is held as an input, but the drawing states no level at {d}")
            if name in used_names:
                rep.bad("level", "V3", name, f"{name} is used twice")
                continue
            dec.pin[d] = name
            used_names.add(name)
            if role == "check_only":
                dec.reference_only.add(d)
        rep.ok("level")

    # The parts, from the regions / entities the answer names; which datums belong only to EXISTING work.
    parts, unknown_ids = resolve_parts(an, answer) if answer.get("components") else ({}, [])
    if unknown_ids:
        rep.warn("V1", "components", f"unknown ids {unknown_ids[:6]} ignored")
    existing_d, proposed_d = set(), set()
    comp_existing = {}
    for part in parts.values():
        comp_existing[part.name] = part.existing
        if part.level != "assembly" or not any(q.parent == part.name for q in parts.values()):
            (existing_d if part.existing else proposed_d).update(part.datums)
    existing_only = existing_d - proposed_d

    # ── parameters naming a candidate (V1, V2, V3) ─────────────────────────────────
    # A candidate is every equal size of one kind; a parameter may name only some of its OCCURRENCES (gap ids): those
    # drive with it, the rest stay their own sizes — equal sizes are not one design input unless someone says so.
    loose: list[dict] = []
    claimed: dict[str, str] = {}  # occurrence → the parameter that drives it
    subset_pairs: dict[str, list[tuple[str, str, str | None]]] = {}
    angle_params: list[dict] = []
    for p in answer.get("parameters", []):
        name = p.get("name", "")
        if not PASCAL.match(name) or GENERIC.match(name):
            rep.bad("parameter", "V3", name, f"{name!r} is not a PascalCase engineering name")
            continue
        if name in used_names:
            rep.bad("parameter", "V3", name, f"{name} is defined twice")
            continue
        if p.get("kind") == "angle" or p.get("unit") in ("deg", "°"):
            angle_params.append(p)  # measured from a line's direction, or stated by a note (below)
            used_names.add(name)
            continue
        cid = p.get("candidate")
        if cid:
            c = an.clusters.get(cid)
            if c is None:
                rep.bad("parameter", "V1", name, f"no candidate {cid}")
                continue
            measured = c.value * u
            if abs(measured - float(p.get("value", 0))) > max(tol, 1e-3 * measured):
                rep.bad("parameter", "V2", name, f"{name} = {p.get('value')} but candidate {cid} measures {measured:.1f} mm")
                continue
            occ = p.get("occurrences")
            occ = None if occ in (None, "all") else list(dict.fromkeys(occ))
            if occ is not None:
                bad = [g for g in occ if g not in c.gaps]
                if not occ or bad:
                    rep.bad("parameter", "V1", name, f"{name}: {', '.join(bad) or 'no occurrence'} not an occurrence of {cid} "
                            f"(its occurrences: {', '.join(c.gaps[:12])})")
                    continue
                if any(an.gaps[g].axis not in ("x", "y") for g in occ):
                    rep.bad("parameter", "V1", name, f"{name}: {cid} is a {c.kind.value} size; only sizes between set-out lines bind by occurrence")
                    continue
            mine = occ if occ is not None else list(c.gaps)
            clash = sorted({claimed[g] for g in mine if g in claimed})
            if clash:
                rep.bad("parameter", "V12", name, f"{name}: occurrence(s) {', '.join(g for g in mine if g in claimed)} of {cid} already "
                        f"driven by {', '.join(clash)} — one occurrence, one input")
                continue
            if occ is not None and set(occ) != set(c.gaps):
                g0 = an.gaps[occ[0]]
                for g in occ:
                    claimed[g] = name
                subset_pairs[name] = [(an.gaps[g].a, an.gaps[g].b, an.gaps[g].sym_axis) for g in occ]
                loose.append({**p, "candidate": None, "from_datum": g0.a, "to_datum": g0.b,
                              "evidence": list(p.get("evidence", []))[:5] + [f"occurrence(s) {', '.join(occ)} of {cid}"]})
                continue
            for g in mine:
                claimed[g] = name
            # A proposed member's value does not drag an existing structure that merely has the same size:
            # occurrences lying wholly on an existing structure are split off (they stay as drawn).
            if existing_only and not comp_existing.get(p.get("component"), False):
                split = [gid for gid in c.gaps if an.gaps[gid].a in existing_only and an.gaps[gid].b in existing_only]
                if split and len(split) < len(c.gaps):
                    for gid in split:
                        an.gaps[gid].cluster = None
                    c.gaps = [g for g in c.gaps if g not in split]
                    rep.findings.append(Finding("V11", "info", name, f"{len(split)} occurrence(s) on existing structures kept separate from {name}"))
            dec.accept.add(cid)
            dec.rename[cid] = name
            used_names.add(name)
            rep.ok("parameter")
        else:
            loose.append(p)

    # ── the baseline, rebuilt with those decisions ─────────────────────────────────
    model = build(an, dec)
    prog = from_model(model)
    labels = {p["name"]: p for p in answer.get("parameters", [])}
    for name, prm in prog.params.items():
        if name in labels:
            prm.label = labels[name].get("label") or prm.label
            prm.component = labels[name].get("component", "")
            prm.source = "ai"
            prm.note = labels[name].get("reason", "")
            if labels[name].get("confidence") is not None:
                prm.confidence = float(labels[name]["confidence"])
            prm.evidence = [str(e) for e in labels[name].get("evidence", [])][:6] + prm.evidence[:3]
    for lv in answer.get("levels", []):
        if lv.get("name") in prog.params:
            prog.params[lv["name"]].component = "Levels"
            prog.params[lv["name"]].label = f"{lv['name']} ({lv.get('role')})"
    # A named candidate the set-out does not use as a driving size (it lies between lines fixed by other inputs — a
    # clear height between two site levels) is kept as a named value measured between its lines, so formulas can use it.
    for p in answer.get("parameters", []):
        name, cid = p.get("name"), p.get("candidate")
        if not cid or name in prog.params or name not in dec.rename.values() or cid not in an.clusters:
            continue
        g = next((an.gaps[gid] for gid in an.clusters[cid].gaps if an.gaps[gid].axis in ("x", "y")), None)
        if g is not None:
            loose.append({**p, "candidate": None, "from_datum": g.a, "to_datum": g.b,
                          "reason": (p.get("reason") or "") + f" (named {cid}; not a driving size of the set-out, kept as a value)"})

    # ── parameters measured between two datums (V1, V2) ────────────────────────────
    for p in loose:
        name = p["name"]
        a, b = p.get("from_datum"), p.get("to_datum")
        if a not in datums or b not in datums or datums[a].axis != datums[b].axis:
            rep.bad("parameter", "V1", name, f"{name}: needs a candidate, or two datums on the same axis (got {a}, {b})")
            continue
        measured = abs(datums[b].value - datums[a].value) * u
        if abs(measured - float(p.get("value", 0))) > max(tol, 1e-3 * measured):
            rep.bad("parameter", "V2", name, f"{name} = {p.get('value')} but {a}→{b} measures {measured:.1f} mm")
            continue
        prog.params[name] = Param(name=name, label=p.get("label", name), value=measured, component=p.get("component", ""), source="ai",
                                  measures=(a, b), confidence=float(p.get("confidence") or 0.9),
                                  evidence=[str(e) for e in p.get("evidence", [])][:6] + [f"measured {a}→{b}"], note=p.get("reason", ""))
        used_names.add(name)
        rep.ok("parameter")

    # ── angle parameters (V1, V2): the direction of a drawn line, or the number a note states ─────────
    for p in angle_params:
        _angle_param(an, prog, p, rep)
    names_t: set[str] = set()
    for t in answer.get("transforms", []):  # what the transforms use is used: an angle that turns a part drives it
        for key in ("angle", "dx", "dy", "sx", "sy"):
            try:
                names_t |= names_in(str(t.get(key) or "0"))
            except ExprError:
                pass
        for e in t.get("pivot") or []:
            try:
                names_t |= names_in(str(e or "0"))
            except ExprError:
                pass
    prog._transform_names = names_t

    # ── datum formulas (V1, V4, V5) ───────────────────────────────────────────────
    defaults_mm = {d: datums[d].value * u for d in datums}
    for f in answer.get("datum_formulas", []):
        d, expr = f.get("datum"), (f.get("expr") or "").strip()
        if d not in prog.formulas:
            rep.bad("formula", "V1", str(d), f"no datum {d}")
            continue
        try:
            names = names_in(expr)
        except ExprError as exc:
            rep.bad("formula", "V4", d, str(exc))
            continue
        unknown = [n for n in names if n not in prog.formulas and n not in prog.params]
        if unknown:
            rep.bad("formula", "V4", d, f"{d} = {expr}: unknown {', '.join(unknown)}")
            continue
        try:  # a set-out line is a length: a formula mixing kinds of quantity is refused before it is evaluated
            check_dims(expr, dims_of(prog), want=LENGTH)
        except ExprError as exc:
            rep.bad("formula", "V4", d, f"{d} = {expr}: {exc}")
            continue
        old = prog.formulas[d]
        prog.formulas[d] = expr
        prog.invalidate()
        try:
            prog.order()
            got = evaluate(expr, {**prog.defaults(), **defaults_mm})
        except ExprError as exc:
            prog.formulas[d] = old
            prog.invalidate()
            # "d = D ± stuff" closing a loop is the same relation as "D = d ∓ stuff": try it that way round.
            rev = _reverse(d, expr, prog)
            # Reversing onto a line another accepted claim already sets would overwrite that claim, not settle the loop.
            if rev is not None and prog.origin.get(rev[0]) != "ai":
                d2, expr2 = rev
                old2 = prog.formulas[d2]
                prog.formulas[d2] = expr2
                prog.invalidate()
                try:
                    prog.order()
                    got2 = evaluate(expr2, {**prog.defaults(), **defaults_mm})
                    if abs(got2 - defaults_mm[d2]) <= tol:
                        if abs(got2 - defaults_mm[d2]) > 1e-6:
                            c = defaults_mm[d2] - got2
                            prog.formulas[d2] = f"{expr2} {'+' if c > 0 else '-'} {abs(c):.6f}"
                            prog.invalidate()
                        prog.origin[d2] = "ai"
                        rep.ok("formula")
                        rep.findings.append(Finding("V4", "info", d, f"{d} = {expr} would close a loop; kept as {d2} = {expr2}"))
                        continue
                except ExprError:
                    pass
                prog.formulas[d2] = old2
                prog.invalidate()
            rep.bad("formula", "V4", d, f"{d} = {expr}: {exc}")
            continue
        if abs(got - defaults_mm[d]) > tol:
            prog.formulas[d] = old
            prog.invalidate()
            rep.bad("formula", "V5", d, f"{d} = {expr} gives {got:.1f} mm but the line is drawn at {defaults_mm[d]:.1f} mm")
            continue
        if abs(got - defaults_mm[d]) > 1e-6:  # keep the drawing exact
            c = defaults_mm[d] - got
            prog.formulas[d] = f"{expr} {'+' if c > 0 else '-'} {abs(c):.6f}"
            prog.invalidate()
        prog.origin[d] = "ai"
        rep.ok("formula")

    # ── a named dimension drives its geometry (on any drawing, by the same rule) ───
    levels_now = {n for n, q in prog.params.items() if q.kind == "level"}
    dims: dict[str, list[tuple[str, str, str | None]]] = {}
    for p in answer.get("parameters", []):
        name, cid = p.get("name"), p.get("candidate")
        if name not in prog.params or prog.params[name].kind == "level":
            continue
        if name in subset_pairs:
            dims[name] = subset_pairs[name]
        elif cid and cid in an.clusters:
            dims[name] = [(an.gaps[g].a, an.gaps[g].b, an.gaps[g].sym_axis) for g in an.clusters[cid].gaps if an.gaps[g].axis in ("x", "y")]
        elif prog.params[name].measures:
            dims[name] = [(*prog.params[name].measures, None)]
    drive_protected = {d for d, o in prog.origin.items() if o in ("ai", "slope", "held", "existing", "constraint")} \
        | {d for d, e in prog.formulas.items() if names_in(e) & levels_now}
    # The lines only held parts use are constants at the end of the build (hold_parts below), so a named size is never set out by moving
    # one: the free end moves, and a size between two held lines is a worked-out quantity — whether or not the hold is applied yet.
    will_hold = {p.name for p in parts.values() if not p.parametrize} | ({p.name for p in parts.values() if p.existing} if hold_existing else set())
    drive_protected |= held_only_lines(parts, will_hold)
    cannot = drive_dimensions(prog, dims, drive_protected)

    # ── parameters must drive something (V9) ──────────────────────────────────────
    _retire_undriven(prog, rep, dims, cannot)

    # ── relations (V7) ─────────────────────────────────────────────────────────────
    for r in answer.get("relations", []):
        name, expr = r.get("name", ""), (r.get("expr") or "").strip()
        try:
            unknown = [n for n in names_in(expr) if n not in prog.params]
        except ExprError as exc:
            rep.bad("relation", "V4", name, str(exc))
            continue
        if unknown:
            rep.bad("relation", "V4", name, f"{name} = {expr}: unknown {', '.join(unknown)}")
            continue
        a, b = r.get("from_datum"), r.get("to_datum")
        check = f"{b} - {a}" if a in datums and b in datums else None
        try:
            value = evaluate(expr, prog.defaults())
        except ExprError as exc:
            rep.bad("relation", "V4", name, str(exc))
            continue
        if check:
            measured = abs(prog.measured(check))
            if abs(abs(value) - measured) > tol:
                rep.bad("relation", "V7", name, f"{name} = {expr} = {value:.1f} but {a}→{b} measures {measured:.1f} mm")
                continue
        rel = Relation(name=name, expr=expr, label=r.get("label", name), check=check)
        if check:
            rel.enforced = all(
                abs(abs(prog.relation_value(rel, {p: prog.params[p].value * k})) - abs(prog.measured(check, {p: prog.params[p].value * k}))) <= tol
                for p in names_in(expr) for k in (0.9, 1.1)
            )
            if not rel.enforced:
                rep.warn("V7", name, f"{name} holds on this drawing but the model does not keep it when its inputs change")
        prog.relations.insert(0, rel)
        rep.ok("relation")

    # ── component transforms (V17): a part rotated / moved / scaled about a pivot, by formulas ──────────
    for t in answer.get("transforms", []):
        row = _transform(an, prog, parts, t, rep)
        if row is not None:
            prog.transforms.append(row)
            rep.ok("transform")

    # ── components (V1): the parts tree ───────────────────────────────────────────
    for c in answer.get("components", []):
        part = parts.get(c.get("name", ""))
        if part is None:
            continue
        if not PASCAL.match(part.name):  # kept (it is only a name), but the person reads names, so it is sent back
            rep.bad("component", "V3", part.name, f"part name {part.name!r} is not PascalCase (e.g. ProposedMainPart, ExistingSupport)")
        if part.parent and part.parent not in parts:
            rep.warn("V1", part.name, f"{part.name}: parent {part.parent!r} is not a component; shown at the top")
            part.parent = None
        prog.components.append(Component(
            name=part.name, type=part.type, description=c.get("description", ""), regions=list(part.regions),
            loops=[e for e in list(c.get("entities", [])) + list(c.get("outlines", [])) if entity_index(e) is not None],
            datums=sorted(part.datums), level=part.level, parent=part.parent, existing=part.existing,
            parametrize=part.parametrize, confidence=c.get("confidence"), evidence=list(c.get("evidence", []))[:6]))
        rep.ok("component")
    prog.structure = {k: answer.get(k) for k in ("structure_type", "family", "views", "summary", "questions")}
    covered = set().union(*(p.regions for p in parts.values())) if parts else set()
    loose = [r.id for r in topo_of(an).regions if r.id not in covered]
    if parts and loose:
        rep.warn("V14", "regions", f"{len(loose)} region(s) belong to no part: {', '.join(loose[:12])}")

    # ── accepted plans, first half: what they hold, what they add, what the anchor must not move ──
    pre_plans = prepare_plans(prog, answer, parts) if answer.get("plans") else None

    # ── what a person chose to keep as drawn ───────────────────────────────────────
    if selection is None:
        selection = {"hold": [p.name for p in parts.values() if not p.parametrize],
                     "exclude": [q.get("name") for q in answer.get("parameters", []) if q.get("recommended") is False]}
    hold = set(selection.get("hold", [])) & set(parts)
    if pre_plans:  # what a plan excludes is held as built (a part it keeps fixed is pinned for its edit instead)
        hold |= pre_plans["hold"] & set(parts)
    if hold_existing:
        hold |= {p.name for p in parts.values() if p.existing}
    held_all = set(hold)
    for n in hold:
        held_all |= descendants(parts, n)
    if hold_existing:
        hold_existing_fixed(prog, answer, rep)
    if hold:
        hold_parts(prog, parts, hold, rep)
    for comp in prog.components:
        comp.held = comp.name in held_all
    frozen = {r.get("name") for r in answer.get("frozen", []) if isinstance(r, dict)}  # measured sizes nobody named, kept as drawn (generic.py)
    freeze_params(prog, (set(selection.get("exclude", [])) | frozen) & set(prog.params), rep)

    # ── the engine's own rules, whatever was proposed ─────────────────────────────
    enforce_slopes(prog, rep)
    # ── accepted plans, second half: the anchor written into the assembly's set-out ──
    compiled = compile_plans(prog, answer, rep, pre_plans) if pre_plans else None
    _retire_undriven(prog, rep, dims, cannot, "the stated slope sets that line from the height")
    relink_texts(prog)
    for p in prog.params.values():
        if p.kind == "length" and p.source == "ai" and abs(p.value - 5 * round(p.value / 5)) > 0.01:
            rep.warn("V10", p.name, f"{p.name} = {p.value:g} mm is not a round design value; it may be a result, not an input")

    # ── design intent, measured: constraints (enforced where possible), then behaviours ──
    roles = [r for r in answer.get("line_roles", []) if r.get("datum") in datums]
    if len(roles) < len(answer.get("line_roles", [])):
        rep.warn("V1", "line_roles", f"{len(answer.get('line_roles', [])) - len(roles)} line role(s) name unknown datums")
    dropped = set(selection.get("drop", []))
    kept = [c for c in answer.get("constraints", []) if (c.get("description") or "") not in dropped] + (pre_plans["constraints"] if pre_plans else [])
    constraint_rows = check_constraints(prog, {**answer, "constraints": kept}, parts, rep)
    # a named value that breaks the drawing when it grows: the engine re-anchors the line that did not follow
    levels = {n for n, q in prog.params.items() if q.kind == "level"}
    protected = {d for d, o in prog.origin.items() if o in (*FIRM, "slope")} \
        | {d for d, e in prog.formulas.items() if names_in(e) & levels}
    may_move: dict[str, set[str]] = {}
    for b in answer.get("behaviours", []):
        for e in b.get("effects", []):
            if e.get("behaviour") in ("grows", "shrinks", "moves"):
                may_move.setdefault(b.get("parameter"), set()).add(e.get("target"))
    for msg in heal_growth_breaks(prog, [n for n, q in prog.params.items() if q.source == "ai"], protected, parts, may_move):
        rep.findings.append(Finding("V8", "info", msg.split(":")[0], "kept valid by the engine — " + msg.split(": ", 1)[1]))
    named = [n for n, p in prog.params.items() if p.source == "ai" or p.kind == "level"]
    wanted = sorted(set(named) | {b.get("parameter") for b in answer.get("behaviours", []) if b.get("parameter") in prog.params})
    impact = measure_impact(prog, parts, wanted) if parts else {"_step": {}, "_base": {}}
    behaviour_rows = check_behaviours(prog, answer, parts, impact, rep, held_all) if parts else []
    # a value of PROPOSED work that also reshapes EXISTING work (they share a set-out line) is put in front of a person
    comp_of = {q.get("name"): q.get("component") for q in answer.get("parameters", [])}
    for pname, row in impact.items():
        if pname.startswith("_") or pname not in prog.params:
            continue
        own = parts.get(comp_of.get(pname) or "")
        if own is None or own.existing:
            continue
        touched = [f"{k} ({', '.join(m[ax] + ' ' + ax for ax in ('x', 'y') if m[ax] != 'fixed')})" for k, m in row.items()
                   if parts[k].existing and k not in held_all and any(m[ax] != "fixed" for ax in ("x", "y"))]
        if touched:
            rep.warn("V15", pname, f"{pname} ({own.name}, proposed) also changes existing work: {'; '.join(touched[:3])} — they share set-out lines. "
                     "Tick 'Hold existing fixed' or hold those parts to keep existing work as built.")
    review = [{"kind": "component", "name": c.name, "confidence": c.confidence, "evidence": c.evidence}
              for c in prog.components if c.confidence is not None and c.confidence < REVIEW_BELOW]
    review += [{"kind": "parameter", "name": q.get("name"), "confidence": q.get("confidence"), "evidence": q.get("evidence", [])}
               for q in answer.get("parameters", []) if (q.get("confidence") or 1) < REVIEW_BELOW and q.get("name") in prog.params]
    review += [{"kind": "constraint", "name": r["label"], "confidence": r["confidence"], "evidence": []}
               for r in constraint_rows if (r.get("confidence") or 1) < REVIEW_BELOW]
    prog.intent = {"parts": parts, "line_roles": roles, "constraints": constraint_rows, "behaviours": behaviour_rows,
                   "impact": impact_summary(impact, parts), "selection": {"hold": sorted(hold), "exclude": sorted(selection.get("exclude", [])), "drop": sorted(dropped), "frozen": len(frozen)},
                   "review": review, "uncovered_regions": loose}

    # ── every value regenerates a valid drawing (V8) ──────────────────────────────
    check_regeneration(prog, rep)
    # ── accepted plans, measured: every promise checked on the regenerated geometry (V16) ──
    if compiled:
        rows = []
        for plan in (p for p in answer.get("plans", []) if p.get("status") == "accepted"):
            res = verify_plan(prog, plan, parts, compiled, answer=answer)
            row = next((r for r in compiled["rows"] if r["id"] == plan.get("id")), {})
            res["compiled"] = {k: row.get(k) for k in ("ok", "problems", "stack")}
            rows.append(res)
            for c in res["checks"]:
                if c["status"] == "fail":
                    rep.bad("plan", "V16", f"{plan.get('id')}:{c['check']}:{c['target']}",
                            f"plan {plan.get('id')}: {c['check']} {c['target']} — expected {c['expected']}, measured {c['measured']}"
                            + (f" at {c.get('failed_at'):g}" if c.get("failed_at") is not None else "") + f". Cause: {c.get('cause')}. {c.get('action')}")
        prog.intent["plans"] = rows
    prog.intent["plans_pending"] = [{"id": p.get("id"), "status": p.get("status"), "questions": [q["text"] for q in p.get("questions", [])][:4]}
                                    for p in answer.get("plans", []) if p.get("status") != "accepted"]
    return prog, rep


def _retire_undriven(prog: Program, rep: Report, dims: dict, cannot: dict, why: str = "") -> None:
    """A named value no line is set out from: a size other inputs fix at both ends is a RESULT — reported as a
    worked-out quantity measured between its lines (notes follow it), with the reason; it is never silently lost."""
    an = prog.analysis
    referenced = set(getattr(prog, "_transform_names", set()))  # names a component transform uses (an angle) drive it
    for e in [*prog.formulas.values(), *prog.radius.values()]:
        referenced |= names_in(e)
    for name in list(prog.params):
        if name in referenced:
            continue
        p = prog.params.pop(name)
        if p.source != "ai":
            continue  # a geometric candidate folded away by an AI formula or a named dimension
        pair = dims.get(name, [(*p.measures, None)] if p.measures else [])[:1]
        if pair and pair[0][0] in an.datums and pair[0][1] in an.datums:
            a, b = sorted(pair[0][:2], key=lambda d: an.datums[d].value)
            if not any(r.name == name for r in prog.relations):
                prog.relations.append(Relation(name=name, expr=f"{b} - {a}", label=p.label or name, check=f"{b} - {a}", enforced=True))
            if all(prog.origin.get(d) in ("held", "existing") for d in (a, b)):
                reason = f"{name}: both its lines belong to parts kept as drawn, so it cannot drive anything"
            else:
                reason = cannot.get(name) or (f"{name}: {why}" if why else f"{name} is not set out by any line")
            rep.findings.append(Finding("V9", "info", name, reason + f" — kept as a worked-out quantity ({b} - {a}), not an input"))
        else:
            rep.bad("parameter", "V9", name, f"{name} drives nothing and measures no two lines: name a candidate or two lines")


def dims_of(prog: Program) -> dict[str, str]:
    """The kind of quantity of every name a formula may use: parameters by their unit (mm / m → length, deg → angle,
    - → ratio); set-out lines are lengths."""
    out = {n: dim_of_unit(p.unit) for n, p in prog.params.items()}
    for d in prog.formulas:
        out.setdefault(d, LENGTH)
    return out


def _angle_param(an: Analysis, prog: Program, p: dict, rep: Report) -> None:
    """An angle measured from the drawing: the direction of a drawn straight line (`angle_of`: its id, degrees from +x,
    the line read either way), or the number a note states (`stated_by`: the note's id). Never a typed-in angle."""
    name = p["name"]
    try:
        value = float(p.get("value"))
    except (TypeError, ValueError):
        rep.bad("parameter", "V2", name, f"{name}: an angle needs its value (degrees)")
        return
    items = an.drawing.items
    ref = p.get("angle_of") or p.get("stated_by")
    k = entity_index(ref or "")
    if k is None or not 0 <= k < len(items):
        rep.bad("parameter", "V1", name, f"{name}: an angle is measured from a line (angle_of) or read from a note (stated_by); {ref!r} is neither")
        return
    it = items[k]
    if p.get("angle_of"):
        if it.dxftype not in ("LINE", "LWPOLYLINE", "POLYLINE") or len(it.pts) < 2:
            rep.bad("parameter", "V1", name, f"{name}: {ref} is a {it.dxftype}, not a straight line")
            return
        (x1, y1), (x2, y2) = it.pts[0], it.pts[1]
        measured = math.degrees(math.atan2(y2 - y1, x2 - x1))
        alts = [measured + k_ * 180.0 for k_ in (-2, -1, 0, 1, 2)]
        best = min(alts, key=lambda a: abs(a - value))
        if abs(best - value) > 0.05:
            rep.bad("parameter", "V2", name, f"{name} = {value:g}° but {ref} is drawn at {measured % 180:.3f}° (or {measured % 180 - 180:.3f}°)")
            return
        evidence = [f"the direction of {ref}: {best:.4f}°"]
        value = best
    else:
        nums = [float(x) for x in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])", it.text or "")]
        if not any(abs(n - value) <= 1e-6 for n in nums):
            rep.bad("parameter", "V2", name, f"{name} = {value:g}° but {ref} says {(it.text or '')[:60]!r}")
            return
        evidence = [f"stated by {ref}: {(it.text or '')[:60]!r}"]
    prog.params[name] = Param(name=name, label=p.get("label", name), value=value, unit="deg", kind="angle", component=p.get("component", ""),
                              source="ai", confidence=float(p.get("confidence") or 0.9),
                              evidence=[str(e) for e in p.get("evidence", [])][:5] + evidence, note=p.get("reason", ""))
    rep.ok("parameter")


def _transform(an: Analysis, prog: Program, parts: dict, t: dict, rep: Report) -> dict | None:
    """A component transform, checked: what it moves (a part, or entities), its pivot and amount as formulas of the
    drawing's values and set-out lines (kinds of quantity checked), one transform per entity, and the notes it carries
    (those whose leader or place is on what it moves)."""
    from .assembly import part_entities

    name, kind = t.get("name", ""), t.get("kind")
    if not PASCAL.match(name or ""):
        rep.bad("transform", "V3", name or "?", f"transform name {name!r} is not PascalCase")
        return None
    if kind not in ("rotate", "translate", "scale"):
        rep.bad("transform", "V17", name, f"{name}: kind is rotate, translate or scale (got {kind!r})")
        return None
    ents: set[int] = set()
    if t.get("part"):
        if t["part"] not in parts:
            rep.bad("transform", "V17", name, f"{name}: no part {t['part']!r}")
            return None
        ents |= part_entities(prog, parts, t["part"])
    for eid in t.get("entities", []):
        k = entity_index(str(eid))
        if k is None or not 0 <= k < len(an.drawing.items):
            rep.bad("transform", "V17", name, f"{name}: no entity {eid}")
            return None
        ents.add(k)
    if not ents:
        rep.bad("transform", "V17", name, f"{name}: it moves nothing (name a part or entities)")
        return None
    taken = {i: r["name"] for r in prog.transforms for i in r["entities"]}
    clash = sorted({taken[i] for i in ents if i in taken})
    if clash:
        rep.bad("transform", "V17", name, f"{name}: some of its entities are already moved by {', '.join(clash)} — one transform per entity")
        return None
    wants = {"rotate": {"pivot_x": LENGTH, "pivot_y": LENGTH, "angle": ANGLE}, "translate": {"dx": LENGTH, "dy": LENGTH},
             "scale": {"pivot_x": LENGTH, "pivot_y": LENGTH, "sx": RATIO, "sy": RATIO}}[kind]
    exprs = {"pivot_x": (t.get("pivot") or [None, None])[0], "pivot_y": (t.get("pivot") or [None, None])[1],
             "angle": t.get("angle"), "dx": t.get("dx"), "dy": t.get("dy"), "sx": t.get("sx"), "sy": t.get("sy")}
    u = an.drawing.units_mm
    scope = {**prog.defaults(), **{d: v * u for d, v in prog.datum_values().items()}}
    dims = dims_of(prog)
    for key, want in wants.items():
        e = str(exprs[key] if exprs[key] is not None else "").strip()
        if not e:
            rep.bad("transform", "V17", name, f"{name}: {kind} needs {key}")
            return None
        try:
            unknown = [n for n in names_in(e) if n not in prog.params and n not in prog.formulas]
            if unknown:
                raise ExprError(f"unknown {', '.join(unknown)}")
            check_dims(e, dims, want=want if want != RATIO else None)
            evaluate(e, scope)
        except ExprError as exc:
            rep.bad("transform", "V17", name, f"{name}: {key} = {e}: {exc}")
            return None
        exprs[key] = e
    if kind == "scale" and exprs["sx"] != exprs["sy"] and not t.get("nonuniform"):
        rep.bad("transform", "V17", name, f"{name}: a scale with different x and y factors distorts the part; say nonuniform: true if that is meant")
        return None
    row = {"name": name, "kind": kind, "entities": sorted(ents), "why": t.get("why", "")}
    if kind in ("rotate", "scale"):
        row["pivot"] = [exprs["pivot_x"], exprs["pivot_y"]]
    for key in ("angle", "dx", "dy", "sx", "sy"):
        if key in wants:
            row[key] = exprs[key]
    model = an.cache.get("annotations")
    carried: dict[int, tuple[float, float]] = {}
    if model is not None:
        for a in model.annotations:
            if a.attachment in ("geometry", "component") and a.targets and a.targets[0].index in ents and a.anchor is not None:
                for i in a.items:
                    if i not in ents:
                        carried[i] = (float(a.anchor[0]), float(a.anchor[1]))
    row["carried"] = carried
    return row


def _reverse(d: str, expr: str, prog: Program) -> tuple[str, str] | None:
    """'d = D + E' → ('D', 'd - (E)'); 'd = D - E' → ('D', 'd + (E)'), when D is a datum and E holds no datum."""
    import ast

    try:
        tree = ast.parse(expr, mode="eval").body
    except SyntaxError:
        return None
    if not (isinstance(tree, ast.BinOp) and isinstance(tree.op, (ast.Add, ast.Sub)) and isinstance(tree.left, ast.Name)):
        return None
    base = tree.left.id
    rest = ast.unparse(tree.right)
    if base not in prog.formulas or any(n in prog.formulas for n in names_in(rest)):
        return None
    return base, f"{d} {'-' if isinstance(tree.op, ast.Add) else '+'} ({rest})"


def _vertex_datums(an: Analysis, outline_ids: list[str]) -> set[str]:
    out: set[str] = set()
    for o in outline_ids:
        i = entity_index(o)
        if i is None or not 0 <= i < len(an.drawing.items):
            continue
        it = an.drawing.items[i]
        for k in range(len(it.pts)):
            for ax in ("x", "y"):
                b = an.slot_datum.get((it.index, k, ax))
                if b and abs(b[1]) <= an.drawing.tol:
                    out.add(b[0])
    return out


def hold_existing_fixed(prog: Program, answer: dict, rep: Report) -> None:
    """Datums only an EXISTING structure uses are written as constants: it does not move or resize."""
    an = prog.analysis
    u = an.drawing.units_mm
    existing, proposed = set(), set()
    for c in answer.get("components", []):
        ds = set(c.get("datums", [])) | _vertex_datums(an, c.get("outlines", []))
        (existing if c.get("existing") else proposed).update(ds)
    held = 0
    for d in existing - proposed:
        if d in prog.formulas and not any(n in prog.params for n in names_in(prog.formulas[d]) if prog.params.get(n) and prog.params[n].kind == "level"):
            prog.formulas[d] = _num(an.datums[d].value * u)
            prog.origin[d] = "existing"
            held += 1
    if held:
        prog.invalidate()
        rep.findings.append(Finding("V11", "info", "existing", f"{held} set-out lines of existing structures are held fixed"))
    for p in list(prog.params.values()):
        if p.measures and set(p.measures) <= (existing - proposed):
            prog.params.pop(p.name)
            rep.warn("V11", p.name, f"{p.name} measures an existing structure — existing work is not a design input; dropped")


SLOPE_TEXT = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*\(?\s*V\s*\)?\s*[:/]\s*(\d+(?:\.\d+)?)\s*\(?\s*H", re.IGNORECASE), "VH"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*\(?\s*H\s*\)?\s*[:/]\s*(\d+(?:\.\d+)?)\s*\(?\s*V", re.IGNORECASE), "HV"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:IN|:)\s*(\d+(?:\.\d+)?)", re.IGNORECASE), "?"),
]


def stated_slopes(an: Analysis) -> list[tuple[tuple[float, float], float]]:
    """Slopes the drawing writes: (where, run/rise). '1(V):1.5(H)' → 1.5; '2(H):1(V)' → 2; '1:1.5' → 1.5 or 1/1.5."""
    out = []
    for it in an.drawing.items:
        if it.dxftype not in ("TEXT", "MTEXT") or not it.text or ":" not in it.text and " IN " not in it.text.upper():
            continue
        for rx, kind in SLOPE_TEXT:
            m = rx.search(it.text)
            if not m:
                continue
            a, b = float(m.group(1)), float(m.group(2))
            if a <= 0 or b <= 0:
                continue
            if kind == "VH":
                out.append((it.pts[0], b / a))
            elif kind == "HV":
                out.append((it.pts[0], a / b))
            else:
                out += [(it.pts[0], b / a), (it.pts[0], a / b)]
            break
    return out


def enforce_slopes(prog: Program, rep: Report) -> None:
    """A sloped edge keeps its slope: its far end is set out by ratio × height from its near end.

    Applies to inclined edges whose ratio the drawing states nearby ('1(V):1.5(H)', 'SLOPE 2:1') or that
    is a clean drafting ratio (1:1, 1:1.5, 1:2, 1:12 …) and spans a real height — not small chamfers,
    which keep their equal legs. Deterministic; it overrides whatever was proposed for that end.
    """
    from .analyse import _nice_ratio

    an = prog.analysis
    dr = an.drawing
    u = dr.units_mm
    ext_h = max(dr.extent[3] - dr.extent[1], 1e-9)
    texts = stated_slopes(an)
    count = 0
    done: set[str] = set()
    ax = an.global_axis.get("x") or next((a for a in sorted(an.axes, key=lambda a: -an.sym_counts.get(a, 0))
                                          if an.datums[a].axis == "x" and an.datums[a].source == "drawn-axis"), None)
    centre = an.datums[ax].value if ax else (dr.extent[0] + dr.extent[2]) / 2
    for it in dr.items:
        if it.role.value != "structural":
            continue
        for i, j in it.segments:
            (x1, y1), (x2, y2) = it.pts[i], it.pts[j]
            dx, dy = x2 - x1, y2 - y1
            if abs(dx) <= dr.tol or abs(dy) <= dr.tol or abs(dy) < 0.08 * ext_h:
                continue
            r = abs(dx / dy)
            mid = ((x1 + x2) / 2, (y1 + y2) / 2)
            reach = 0.25 * max(dr.extent[2] - dr.extent[0], ext_h)
            stated = any(math.dist(p, mid) <= reach and abs(t - r) <= 0.03 * r for p, t in texts)
            if not (stated or _nice_ratio(r)):
                continue
            ends = [(an.slot_datum.get((it.index, i, "x")), an.slot_datum.get((it.index, i, "y"))),
                    (an.slot_datum.get((it.index, j, "x")), an.slot_datum.get((it.index, j, "y")))]
            if any(b is None or abs(b[1]) > dr.tol for e in ends for b in e):
                continue
            (xa, ya), (xb, yb) = [(e[0][0], e[1][0]) for e in ends]
            # The toe is the end farther from the structure's centre; the other end is held by the structure.
            ends2 = sorted([(xa, ya), (xb, yb)], key=lambda e: abs(an.datums[e[0]].value - centre))
            if any(slope_kept(prog, xe, {ya, yb}) for xe in (xa, xb)):
                count += 1
                continue
            for k, (near, far) in enumerate(((ends2[0], ends2[1]), (ends2[1], ends2[0]))):
                # a slope the drawing STATES outranks a named length at its toe (the run follows the height); never the
                # other end, which belongs to the structure
                if _set_slope(prog, near, far, done, u, over_dimension=stated and k == 0):
                    count += 1
                    break
    if count:
        prog.invalidate()
        rep.findings.append(Finding("S1", "info", "slopes", f"{count} sloped edge(s) keep their slope: the far end follows ratio × height"))


def slope_kept(prog: Program, xd: str, ys: set[str]) -> bool:
    """True when this x datum is already set out along the slope (its formula reads both heights)."""
    f = prog.formulas.get(xd, "")
    return ys <= names_in(f) if f else False


def _set_slope(prog: Program, near, far, done: set[str], u: float, over_dimension: bool = False) -> bool:
    an = prog.analysis
    (xn, yn), (xf, yf) = near, far
    firm = prog.origin.get(xf) in FIRM and not (over_dimension and prog.origin.get(xf) == "dimension")
    if xf in done or xf not in prog.formulas or firm:
        return False  # the line is set by a stronger rule: the slope is kept from its other end, if that one is free
    if any(prog.params.get(n) and prog.params[n].kind == "level" for n in names_in(prog.formulas[xf])):
        return False
    dy = an.datums[yf].value - an.datums[yn].value
    if abs(dy) <= an.drawing.tol:
        return False
    ratio = (an.datums[xf].value - an.datums[xn].value) / dy
    nice = round(ratio * 4) / 4 if abs(ratio * 4 - round(ratio * 4)) < 0.02 else ratio
    expr = f"{xn} + {nice:g} * ({yf} - {yn})"
    old = prog.formulas[xf]
    prog.formulas[xf] = expr
    prog.invalidate()
    try:
        prog.order()
        got = evaluate(expr, {**prog.defaults(), **{d: an.datums[d].value * u for d in an.datums}})
    except ExprError:
        prog.formulas[xf] = old
        prog.invalidate()
        return False
    c = an.datums[xf].value * u - got
    if abs(c) > _tol_mm(an):
        prog.formulas[xf] = old
        prog.invalidate()
        return False
    if abs(c) > 1e-6:
        prog.formulas[xf] = f"{expr} {'+' if c > 0 else '-'} {abs(c):.6f}"
    prog.origin[xf] = "slope"
    done.add(xf)
    return True


def relink_texts(prog: Program) -> None:
    """Notes that state a value follow it: sizes (mm or m), worked-out relations, and levels (by their line).

    A number is linked only when exactly one value matches it, or when one of the matching values is
    measured right beside the note. A level note keeps its link to the line it labels.
    """
    an = prog.analysis
    dr = an.drawing
    u = dr.units_mm
    by_mm: dict[int, list[str]] = {}
    where: dict[str, tuple[float, float]] = {}
    for p in prog.params.values():
        if p.kind == "length":
            by_mm.setdefault(round(p.value), []).append(p.name)
            if p.measures:
                a, b = (an.datums[d] for d in p.measures)
                where[p.name] = ((a.value + b.value) / 2, (a.value + b.value) / 2)
    rels: dict[int, list[str]] = {}
    for r in prog.relations:
        try:
            rels.setdefault(round(prog.relation_value(r)), []).append(r.name)
        except ExprError:
            pass
    links: dict[int, list[tuple[str, str, int]]] = {}
    level_links = {i: [k for k in ls if k[1].startswith("datum:")] for i, ls in prog.text_links.items()}
    rules = _straight_runs(dr)
    for it in dr.items:
        if it.dxftype not in ("TEXT", "MTEXT", "ATTRIB") or not it.text:
            continue
        found = list(level_links.get(it.index, []))
        taken = {t for t, _r, _d in found}
        x, y = it.pts[0]
        h = it.text_height or 1.0
        for m in NUM.finditer(it.text):
            tok = m.group()
            around = it.text[max(0, m.start() - 1): m.end() + 1]
            if tok in taken or ":" in around or "/" in around or "SCALE" in it.text.upper():
                continue  # a ratio (1:100, 1(V):1.5(H)) or a scale is not a size
            v = float(tok)
            dec = len(tok.split(".")[1]) if "." in tok else 0
            if dec == 0 and v >= 5:
                cands = by_mm.get(round(v), [])
                ref = None
                # Best evidence first: the dimension line it is written on. The note states THAT distance — through
                # the size that sets it when one does, else as the lines stand (a size of the same value elsewhere,
                # or across, is not it).
                on_line = _measured_between(an, it, v, u, rules)
                if on_line:
                    pair = set(on_line.split(":")[1:])
                    same = [n for n in cands if prog.params[n].measures and set(prog.params[n].measures) == pair]
                    ref = same[0] if same else on_line
                elif len(cands) == 1:
                    ref = cands[0]
                elif cands:
                    def dist(n, x=x, y=y):
                        if n not in where:
                            return 1e30
                        p = prog.params[n].measures
                        ax = an.datums[p[0]].axis
                        c = where[n][0]
                        return abs((x if ax == "x" else y) - c)
                    best = min(cands, key=dist)
                    if dist(best) <= 30 * h:
                        ref = best
                elif len(rels.get(round(v), [])) == 1:
                    ref = "rel:" + rels[round(v)][0]
                if ref and not ref.startswith("rel:") and not _drives(prog, ref):
                    # A size measured here but set by other lines (a splay, a sum): the note states the DISTANCE,
                    # so it follows the distance as regenerated, not the size's own (unchanging) value.
                    a, b = prog.params[ref].measures
                    ref = f"len:{a}:{b}"
                if ref:
                    found.append((tok, ref, 0))
                    taken.add(tok)
            elif dec >= 2 and not any(f[0] == tok for f in found):
                cands = by_mm.get(round(v * 1000), [])
                if len(cands) == 1:
                    found.append((tok, "m:" + cands[0], dec))
        for m in NUM.finditer(it.text):  # a size nobody named: the distance it is written between, as drawn now
            tok = m.group()
            around = it.text[max(0, m.start() - 1): m.end() + 1]
            if tok in taken or "." in tok or ":" in around or "/" in around or "SCALE" in it.text.upper() or float(tok) < 5:
                continue
            ref = _measured_between(an, it, float(tok), u, rules)
            if ref:
                found.append((tok, ref, 0))
                taken.add(tok)
        if found:
            links[it.index] = found
    prog.text_links = links


def _drives(prog: Program, name: str) -> bool:
    """Whether a named size sets the lines it measures (one of them is written from it)."""
    p = prog.params.get(name)
    if not p or not p.measures:
        return True
    return any(name in names_in(prog.formulas.get(d, "")) for d in p.measures)


def _straight_runs(dr) -> dict[str, list[tuple[float, float, float]]]:
    """Every straight horizontal and vertical run on the drawing (structure and annotation): x — (y, x0, x1) of the
    horizontal ones, y — (x, y0, y1) of the vertical ones. A dimension line is one of them."""
    out: dict[str, list[tuple[float, float, float]]] = {"x": [], "y": []}
    for it in dr.items:
        if it.dxftype not in ("LINE", "LWPOLYLINE", "POLYLINE") or len(it.pts) < 2:
            continue
        pts = it.pts
        for p, q in itertools.pairwise(pts):
            if abs(p[1] - q[1]) <= dr.tol and abs(p[0] - q[0]) > dr.tol:
                out["x"].append((p[1], min(p[0], q[0]), max(p[0], q[0])))
            elif abs(p[0] - q[0]) <= dr.tol and abs(p[1] - q[1]) > dr.tol:
                out["y"].append((p[0], min(p[1], q[1]), max(p[1], q[1])))
    return out


def _measured_between(an: Analysis, it, v_mm: float, u: float, rules: dict | None = None) -> str | None:
    """The one pair of set-out lines a number is written between, whose distance is that number. Best evidence: a
    DIMENSION LINE — a straight run whose ends sit on the two lines — with the number just beside it (an exploded
    dimension). Else: the number between the two lines along their axis, near where their gap was seen. Reading the
    same way counts (a vertical text measures a height). None when no pair, or two pairs equally near, fit."""
    from .sheet import text_outline

    o = text_outline(it)
    cx, cy = sum(p[0] for p in o) / 4, sum(p[1] for p in o) / 4
    h = it.text_height or 1.0
    rot = (it.extra.get("rotation", 0.0) or 0.0) % 180
    want = "y" if 45 < rot < 135 else "x"
    tol = max(0.5, 5e-4 * v_mm)
    tol_d = max(an.drawing.tol * 4, 0.5 / max(u, 1e-9))
    scored = []
    for g in an.gaps.values():
        if g.axis not in ("x", "y") or abs(g.value * u - v_mm) > tol or g.a not in an.datums or g.b not in an.datums:
            continue
        a, b = sorted((an.datums[g.a].value, an.datums[g.b].value))
        along, across = (cx, cy) if g.axis == "x" else (cy, cx)
        if not (a - 0.5 * h <= along <= b + 0.5 * h):
            continue
        dim_line = min((abs(across - c) for c, s0, s1 in (rules or {}).get(g.axis, ())
                        if abs(s0 - a) <= tol_d and abs(s1 - b) <= tol_d), default=None)
        if dim_line is not None and dim_line <= 3 * h:
            off = dim_line - 100 * h  # a dimension line beside the number outranks any face
        else:
            seen = g.sample[1] if g.axis == "x" and g.sample else g.sample[0] if g.sample else across
            off = abs(across - seen)
            if off > 12 * h:
                continue
        scored.append((off + 0.05 * abs(along - (a + b) / 2) + (0 if g.axis == want else 4 * h), f"len:{g.a}:{g.b}", {g.a, g.b}))
    if not scored:
        return None
    scored.sort(key=lambda s: s[0])
    best = scored[0]
    rival = next((s for s in scored[1:] if s[2] != best[2]), None)
    if rival is not None and rival[0] < (1.25 * best[0] if best[0] > 0 else best[0]) + 0.5 * h:
        return None  # two different pairs of lines fit about as well: the number is left as written
    return best[1]



def check_regeneration(prog: Program, rep: Report, step: float = 0.1) -> None:
    """V5 the model reproduces the drawing; V8 every value can change ±10% without breaking it. A named value
    that breaks the drawing when it GROWS is an error (sent back to the AI with the lines that did not follow);
    a shrink that breaks it, or a generic value, is a warning (a real design limit is possible)."""
    base = regenerate_program(prog, check=False)
    an = prog.analysis
    ident = max((math.dist(base.pts[i][k], p) for it in an.drawing.items if (i := it.index) in base.pts for k, p in enumerate(it.pts)), default=0.0)
    if ident * an.drawing.units_mm > _tol_mm(an):
        rep.findings.append(Finding("V5", "error", "drawing", f"the model does not reproduce the drawing (off by {ident * an.drawing.units_mm:.2f} mm)"))
    users, base_datum, plan = datum_users(an), base.datum, prog.change_plan()
    for p in list(prog.params.values()):
        delta = 1.0 if p.kind == "level" else max(p.value * step, 10.0)
        for dv in (delta, -delta):
            issues = check_change(prog, {p.name: p.value + dv}, base_datum, users, plan)
            if issues:
                why = _explain_break(prog, issues[0], {p.name: p.value + dv}, plan)
                msg = f"changing {p.name} by {dv:+g} {p.unit}: {issues[0]}{why}"
                if dv > 0 and p.source == "ai":
                    rep.bad("regeneration", "V8", p.name, msg + " Set the lines that should follow out from the line that moves.")
                else:
                    rep.warn("V8", p.name, msg)
                break


def _explain_break(prog: Program, issue: str, values: dict[str, float], plan=None) -> str:
    """Which set-out lines of the broken entity moved and which stayed — the lines that should have followed."""
    an = prog.analysis
    m = re.match(r"\S+ (\S+) \(", issue)
    it = next((i for i in an.drawing.items if m and (i.src or i.handle) == m.group(1)), None)
    if it is None:
        return ""
    u = an.drawing.units_mm
    if plan is not None:
        u0 = an.drawing.units_mm
        v0, v1 = {d: v / u0 for d, v in plan[2].items()}, prog.datum_values_changed(values, plan)
    else:
        v0, v1 = prog.datum_values(), prog.datum_values(values)
    moved, stayed = [], []
    for d in sorted({an.slot_datum[(it.index, k, ax)][0] for k in it.vertex_pts for ax in ("x", "y") if (it.index, k, ax) in an.slot_datum}):
        if d not in v0:
            continue
        shift = (v1[d] - v0[d]) * u
        (moved if abs(shift) > 0.01 else stayed).append(f"{d} = {prog.formulas[d]}" + (f" ({shift:+.0f} mm)" if abs(shift) > 0.01 else ""))
    return f" — on {entity_id(it)}: moved {'; '.join(moved[:4]) or 'nothing'}; stayed {'; '.join(stayed[:4]) or 'nothing'}."


def baseline(an: Analysis, decisions: Decisions | None = None, rep: Report | None = None, selection: dict | None = None) -> Program:
    """The geometry-only program, with the engine's own rules applied (slopes kept, notes linked). Its parts are
    the regions of the drawing; a selection may hold some of them as drawn and keep some values as drawn."""
    prog = from_model(build(an, decisions or Decisions()))
    rep = rep if rep is not None else Report()
    parts, _ = resolve_parts(an, None)
    if selection:
        hold = set(selection.get("hold", [])) & set(parts)
        if hold:
            hold_parts(prog, parts, hold, rep)
        freeze_params(prog, set(selection.get("exclude", [])) & set(prog.params), rep)
    enforce_slopes(prog, rep)
    relink_texts(prog)
    prog.intent = {"parts": parts, "selection": {"hold": sorted((selection or {}).get("hold", [])), "exclude": sorted((selection or {}).get("exclude", []))}}
    return prog

