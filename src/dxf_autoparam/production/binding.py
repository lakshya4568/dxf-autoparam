"""Production rules applied to a drawing, through an explicit adapter: the BINDING.

A production rule engine does not understand DXF geometry. What lets it judge a drawing is a binding: each production field the drawing shows
(an input such as `geometry.clear_w`, or a computed output such as `total_w`) is mapped to the drawing's OWN quantity — a value, level or
relation the parametrization named, the distance between two set-out lines, or the level of a horizontal line — in the binding's unit or, for
a view that is a unit of its own, in another (`{"unit": "U02", "lines": [...]}`). Values are read from the drawing (as drawn, or as
regenerated after a change) and converted by the units the knowledge states; a field whose unit the knowledge does not state cannot be bound.
A configuration the geometry cannot measure (a count of cells, an option) or a value the drawing does not show is stated only with its basis,
and every result that depends on it says so.

What the production code would assume is never imported as a fact about the drawing: an output is evaluable only when NOTHING it depends on
was left to the production defaults — measured live (each unbound field the engine reads is perturbed and the engine run again; an output that
moves waits for that field). The engine's own validation is attributed check by check (each message carries the fields it read), so a message
decided by defaults is never taken as a verdict on the drawing. Evaluation always runs the production code (the bridge); without it the answer
is `unavailable`, never a guess.

What the knowledge adds beyond numbers:
  structure   production says which quantities are INPUTS and which are DERIVED; a binding that finds the drawing holding a derived quantity
              as an independent value (or deriving an input) says so — the parametrization is inverted
  proposals   for a derived output bound to a drawing value, the exact relation in the drawing's own names, obtained by running the production
              code (an affine relation's coefficients are its measured slopes), for the model to adopt with set_relation
  guards      outputs that held, and validation the drawing decided, when the binding was accepted: a change that breaks one is refused
"""

from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field

from ..program import Program, names_in
from .bridge import BridgeError, BridgeUnavailable, RuleBridge
from .formulas import get_path, set_path
from .manifest import FamilyKnowledge

LENGTH_TOL_MM = 1.0  # drawn geometry is set out to the millimetre
LEVEL_TOL_M = 0.001
CONFIG_KINDS = ("count", "flag", "text", "ratio", "angle")
_DIGITS = re.compile(r"-?\d+(?:\.\d+)?")


class BindingError(ValueError):
    pass


@dataclass
class Binding:
    family: str
    unit: str
    inputs: dict = field(default_factory=dict)  # production path → drawing reference
    outputs: dict = field(default_factory=dict)  # production output → drawing reference
    config: dict = field(default_factory=dict)  # production path → {"value", "basis"}: what the drawing states but the geometry cannot measure
    assumptions: dict = field(default_factory=dict)  # production path → {"value", "why"}: what the drawing does not show
    guards: list = field(default_factory=list)  # outputs that held when the binding was accepted: they must keep holding under any change
    validation_baseline: list = field(default_factory=list)  # error messages (digits dropped) the drawing already had when accepted
    guard_validation: bool = False  # the engine's validation is part of the guard (it ran, and drawing-decided errors refuse a change)
    id: str = ""
    evidence: list = field(default_factory=list)
    source: str = "agent"  # agent | person
    knowledge_digest: str = ""  # the manifest's sources_digest the binding was accepted against
    note: str = ""

    @classmethod
    def from_json(cls, d: dict) -> Binding:
        if not isinstance(d, dict):
            raise BindingError("a binding is an object: {family, unit, inputs, outputs, config?, assumptions?}")
        known = set(cls.__dataclass_fields__)
        extra = set(d) - known
        if extra:
            raise BindingError(f"unknown field(s) {sorted(extra)}; a binding takes {sorted(known)}")
        if not isinstance(d.get("family"), str) or not isinstance(d.get("unit"), str):
            raise BindingError("family and unit are required (strings)")
        b = cls(**{k: copy.deepcopy(v) for k, v in d.items()})
        for k in ("inputs", "outputs", "config", "assumptions"):
            if not isinstance(getattr(b, k), dict):
                raise BindingError(f"{k} must be an object (path → …)")
        return b

    def to_json(self) -> dict:
        return asdict(self)

    def units(self) -> set[str]:
        """Every unit the binding reads (its own and those its references name)."""
        out = {self.unit}
        for ref in list(self.inputs.values()) + list(self.outputs.values()):
            if isinstance(ref, dict) and isinstance(ref.get("unit"), str):
                out.add(ref["unit"])
        return out


# ── the drawing's side: what a reference measures ───────────────────────────────


@dataclass
class UnitState:
    """What a reference is measured on: a unit's program, the values in force, and the set-out lines in mm (as drawn or regenerated)."""

    prog: Program
    values: dict
    datum_mm: dict
    level_offset_mm: float

    @classmethod
    def of(cls, prog: Program, values: dict | None = None, datum: dict | None = None) -> UnitState:
        """`datum`: the regenerated set-out lines in drawing units (a Regenerated.datum); default: the program evaluated at `values`."""
        an = prog.analysis
        um = an.drawing.units_mm
        dv = datum if datum is not None else prog.datum_values(values or {})
        dmm = {d: v * um for d, v in dv.items()}
        for d, x in an.datums.items():
            dmm.setdefault(d, x.value * um)
        return cls(prog=prog, values=dict(values or {}), datum_mm=dmm, level_offset_mm=float(getattr(an, "level_offset_mm", 0.0) or 0.0))

    def role(self, name: str) -> str | None:
        """How the drawing holds a name: `input` (an independent value or a level), `derived` (a relation), or None."""
        if name in self.prog.params:
            return "input"
        return "derived" if any(r.name == name for r in self.prog.relations) else None

    def measure(self, ref) -> tuple[float, str, str]:
        """(value, unit, what it is) of a reference: mm for a length, m for a level. Raises BindingError naming what is wrong."""
        if isinstance(ref, (bool, int, float)) or (isinstance(ref, str) and re.fullmatch(r"\s*-?[0-9.]+\s*", ref)):
            raise BindingError("a number is not a reference: bind the NAME of a value or level, a pair of lines, or a line "
                               "(a value the drawing does not show is an assumption, stated with why)")
        if isinstance(ref, str):
            ref = {"value": ref}
        if not isinstance(ref, dict):
            raise BindingError(f"not a reference: {ref!r}")
        if "value" in ref:
            name = str(ref["value"])
            p = self.prog.params.get(name)
            if p is not None:
                v = float(self.values.get(name, p.value))
                return v, p.unit, ("level " if p.kind == "level" else "value ") + name
            r = next((x for x in self.prog.relations if x.name == name), None)
            if r is not None:
                scope = {**self.prog.defaults(), **self.values}
                v = self.prog.relation_value(r, self.values) if not (names_in(r.expr) - scope.keys()) else _eval_lines(r.expr, self.datum_mm)
                return float(v), "mm", "relation " + name
            raise BindingError(f"no value, level or relation named {name!r} (define it first)")
        an = self.prog.analysis
        if "lines" in ref:
            ab = ref["lines"]
            if not (isinstance(ab, list) and len(ab) == 2 and all(isinstance(x, str) for x in ab)):
                raise BindingError("lines: [line, line] — two set-out line ids")
            a, b = ab
            for d in (a, b):
                if d not in self.datum_mm or d not in an.datums:
                    raise BindingError(f"no set-out line {d!r} in this unit")
            if an.datums[a].axis != an.datums[b].axis:
                raise BindingError(f"{a} and {b} are on different axes: a distance is between two lines of one axis")
            return abs(self.datum_mm[b] - self.datum_mm[a]), "mm", f"distance {a}–{b}"
        if "line" in ref:
            d = str(ref["line"])
            if d not in self.datum_mm or d not in an.datums:
                raise BindingError(f"no set-out line {d!r} in this unit")
            if an.datums[d].axis != "y":
                raise BindingError(f"{d} is a vertical line: a level is read off a horizontal one")
            return (self.datum_mm[d] + self.level_offset_mm) / 1000.0, "m", f"level of line {d}"
        raise BindingError("a reference is a name, {value: name}, {lines: [a, b]} or {line: y…} (optionally with unit: U…)")


@dataclass
class SheetState:
    """The units a binding reads, each as drawn or regenerated; a reference without `unit` is the binding's own."""

    default: str
    units: dict  # uid → UnitState

    def of(self, ref) -> tuple[str, UnitState]:
        uid = ref.get("unit", self.default) if isinstance(ref, dict) else self.default
        st = self.units.get(uid)
        if st is None:
            raise BindingError(f"no unit {uid!r} on this sheet")
        return uid, st

    def measure(self, ref) -> tuple[float, str, str]:
        uid, st = self.of(ref)
        v, u, what = st.measure({k: x for k, x in ref.items() if k != "unit"} if isinstance(ref, dict) else ref)
        return v, u, (what if uid == self.default else f"{what} in {uid}")

    def role(self, ref) -> str | None:
        name = ref if isinstance(ref, str) else (ref.get("value") if isinstance(ref, dict) else None)
        if not isinstance(name, str):
            return None
        _uid, st = self.of(ref)
        return st.role(name)


def _eval_lines(expr: str, datum_mm: dict) -> float:
    from ..program import evaluate

    return evaluate(expr, datum_mm)


def _as_state(st, default: str) -> SheetState:
    return st if isinstance(st, SheetState) else SheetState(default=default, units={default: st})


# ── units ────────────────────────────────────────────────────────────────────────


def to_production(value: float, unit: str, what: str, fam: FamilyKnowledge, path: str, output: bool = False) -> float:
    """A drawing quantity in the production field's unit; refused when the kinds or units do not meet."""
    m_per, kind = fam.length_factor(path, output)
    rec = (fam.outputs if output else fam.params).get(path) or {}
    is_level = what.startswith(("level", "level of line"))
    if kind == "level":
        if unit != "m" or not is_level:
            raise BindingError(f"{path} is a LEVEL in the production model: bind a level (set_levels name) or {{line: y…}}, not {what}")
        if rec.get("unit") != "m":
            raise BindingError(f"{path}: the knowledge does not state its unit as metres ({rec.get('unit')}); it cannot be bound")
        return value
    if kind in CONFIG_KINDS:
        raise BindingError(f"{path} is a {kind}: the geometry does not measure it — state it under config with its basis")
    if kind == "length" or (kind == "unknown" and m_per is not None):
        if m_per is None:
            raise BindingError(f"{path}: the knowledge does not state its unit ({rec.get('unit', 'unknown')}): it cannot be bound until it does")
        if unit != "mm" or is_level:
            raise BindingError(f"{path} is a LENGTH: bind a size (a value, a relation, or {{lines: [a, b]}}), not {what}")
        return value / 1000.0 / m_per
    raise BindingError(f"{path}: the knowledge does not say what kind of quantity it is (kind {kind}, unit {rec.get('unit', 'unknown')}): "
                       "it cannot be bound")


def from_production(value: float, fam: FamilyKnowledge, name: str) -> tuple[float | None, str]:
    """A production output in the drawing's units: (value, 'mm' | 'm'), or (None, why) when its unit is not known."""
    m_per, kind = fam.length_factor(name, output=True)
    if kind == "level" and (fam.outputs.get(name) or {}).get("unit") == "m":
        return value, "m"
    if m_per is not None and kind in ("length", "unknown"):
        return value * m_per * 1000.0, "mm"
    return None, f"the knowledge does not state {name}'s unit and kind as a length or level (unit {(fam.outputs.get(name) or {}).get('unit')}, kind {kind})"


# ── checking a binding's shape (before anything is run) ──────────────────────────


def shape_problems(fam: FamilyKnowledge, b: Binding) -> list[str]:
    probs = []
    if b.family != fam.key:
        probs.append(f"family {b.family!r} is not {fam.key!r}")
    if not fam.supported:
        probs.append(f"{fam.key} has no production rule engine: nothing can be evaluated")
    for path in b.inputs:
        if path not in fam.params:
            probs.append(f"inputs: {path!r} is not a field of {fam.key} (production_knowledge lists them)")
    for name in b.outputs:
        if name not in fam.outputs:
            probs.append(f"outputs: {name!r} is not an output of {fam.key}")
    for key, need in (("config", "basis"), ("assumptions", "why")):
        for path, row in getattr(b, key).items():
            if path not in fam.params:
                probs.append(f"{key}: {path!r} is not a field of {fam.key}")
            elif not isinstance(row, dict) or "value" not in row or not str(row.get(need) or "").strip():
                probs.append(f"{key}: {path} needs {{value, {need}}} — a value without its {need} is not accepted")
            elif key == "config" and fam.params[path].get("kind") not in CONFIG_KINDS:
                probs.append(f"config: {path} is a {fam.params[path].get('kind')} the drawing measures: bind it under inputs")
    both = set(b.inputs) & (set(b.config) | set(b.assumptions))
    if both:
        probs.append(f"bound twice (input and config/assumption): {sorted(both)}")
    return probs


# ── evaluating: the production code on the drawing's values ─────────────────────


def assemble(fam: FamilyKnowledge, b: Binding, st: SheetState) -> tuple[dict, dict[str, dict], list[str]]:
    """(the production model, where each set field came from, problems). Unbound fields keep the production defaults ONLY so the engine
    can run; `evaluate` measures which outputs they would decide and refuses to judge those."""
    model = fam.defaults_model()
    prov: dict[str, dict] = {}
    probs: list[str] = []
    for path, ref in b.inputs.items():
        try:
            v, unit, what = st.measure(ref)
            pv = to_production(v, unit, what, fam, path)
        except BindingError as exc:
            probs.append(f"{path}: {exc}")
            continue
        try:
            set_path(model, path, pv)
        except KeyError:
            probs.append(f"{path}: the production model's shape cannot hold it")
            continue
        prov[path] = {"from": "drawing", "ref": ref, "measured": round(v, 6), "unit": unit, "what": what, "production_value": pv}
    for key, tag in (("config", "configuration stated"), ("assumptions", "assumed")):
        for path, row in getattr(b, key).items():
            try:
                set_path(model, path, row["value"])
            except KeyError:
                probs.append(f"{path}: the production model's shape cannot hold it")
                continue
            prov[path] = {"from": tag, "value": row["value"], "basis": row.get("basis") or row.get("why")}
    return model, prov, probs


def _unbound_probes(fam: FamilyKnowledge, model: dict, bound: set[str]) -> list[tuple[str, object]]:
    """Each field the engine reads that the binding leaves to the defaults, with a changed value to try (numbers moved, configuration
    set to each value that is known to change the result)."""
    out = []
    for p, r in fam.params.items():
        if p in bound or not r.get("read_by_compute"):
            continue
        cur = get_path(model, p)
        if r.get("in_defaults") and isinstance(cur, (int, float)) and not isinstance(cur, bool):
            out.append((p, cur + 1 if r.get("kind") == "count" else cur * 1.1 + 0.0137))
        for v in r.get("values_that_change_outputs") or []:
            out.append((p, v))
    return out


def _flat(d, prefix: str = "") -> dict:
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out.update(_flat(v, f"{prefix}.{i}" if prefix else str(i)))
    else:
        out[prefix] = d
    return out


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def message_key(msg: str) -> str:
    """A validation message without its numbers: the same check failing at another value is the same failure."""
    return _DIGITS.sub("#", " ".join(str(msg).split()))


def _attribute(fam: FamilyKnowledge, val: dict, bound: set[str]) -> list[dict]:
    """Each validation message with the fields that decided it, and whether the drawing decided it (no field left to the defaults)."""
    out = []
    for a in val.get("attributed") or []:
        feeds = set(a.get("reads") or [])
        for o in a.get("derived_reads") or []:
            feeds |= set((fam.outputs.get(o) or {}).get("depends_on") or [])
        defaults = sorted(p for p in feeds if p not in bound and (fam.params.get(p) or {}).get("read_by_compute", True))
        out.append({"sev": a["sev"], "msg": a["msg"], "fields": sorted(feeds)[:12], "decided_by_drawing": not defaults,
                    **({"uses_production_defaults_for": defaults[:8]} if defaults else {})})
    return out


def evaluate(fam: FamilyKnowledge, b: Binding, st, br: RuleBridge, only: list[str] | None = None, freshness: dict | None = None,
             propose: bool = True) -> dict:
    """The production code run on the drawing's values: per bound output holds / differs / not_evaluable (with expected, measured,
    difference and tolerance, or the field it waits for), the engine's validation check by check, the dependency structure and relation
    proposals, and the provenance of every field. `only`: just these outputs (the guards of a change). Never raises: a failure is `status`."""
    st = _as_state(st, b.unit)
    rep: dict = {"family": fam.key, "unit": b.unit, "binding": b.id or None, "knowledge": freshness or {}}
    probs = shape_problems(fam, b)
    if probs:
        return {**rep, "status": "refused", "problems": probs}
    if freshness and freshness.get("bundle") == "differs":
        return {**rep, "status": "stale", "why": "the bundle that would run the rules was built from other code than this knowledge describes: "
                "rebuild (dxf-autoparam production build) or re-extract; nothing was evaluated"}
    model, prov, probs = assemble(fam, b, st)
    rep["inputs"] = prov
    if probs:
        return {**rep, "status": "refused", "problems": probs}
    bound = set(b.inputs) | set(b.config) | set(b.assumptions)
    probes = _unbound_probes(fam, model, bound)
    names = only if only is not None else list(b.outputs)
    # slopes of each output in each bound input (two steps: an affine dependence has equal slopes) — what a relation proposal is made of
    value_inputs = list(b.inputs.items()) if propose and only is None else []
    try:
        base = br.request("compute", family=fam.key, model=model)["derived"]
        moved = []
        for p, v in probes:
            m = copy.deepcopy(model)
            try:
                set_path(m, p, v)
            except KeyError:
                continue
            moved.append((p, m))
        slope_models = []
        for p, _ref in value_inputs:
            m = copy.deepcopy(model)
            set_path(m, p, get_path(model, p) + 0.1)
            slope_models.append((p, m))
            m2 = copy.deepcopy(model)
            set_path(m2, p, get_path(model, p) + 0.37)
            slope_models.append((p + "#2", m2))
        batch = [m for _p, m in moved] + [m for _p, m in slope_models]
        rows = br.request("compute_many", family=fam.key, models=batch)["derived"] if batch else []
        val = br.request("validate", family=fam.key, model=model) if fam.data["capabilities"].get("has_validate") and (
            only is None or b.guard_validation) else None
    except BridgeUnavailable as exc:
        return {**rep, "status": "unavailable", "why": str(exc)}
    except BridgeError as exc:
        return {**rep, "status": "error", "why": str(exc)}
    flat0 = _flat(base)
    waits: dict[str, list[str]] = {}
    for (p, _m), row in zip(moved, rows[:len(moved)], strict=True):
        f = _flat(row.get("derived") or {}) if row.get("ok") else {}
        for o, v0 in flat0.items():
            v1 = f.get(o)
            if _num(v0) and (not _num(v1) or abs(v1 - v0) > 1e-12 * max(1.0, abs(v0))):
                waits.setdefault(o, []).append(p)
    slopes: dict[str, dict[str, tuple[float, float]]] = {}
    for (p, _m), row in zip(slope_models, rows[len(moved):], strict=True):
        f = _flat(row.get("derived") or {}) if row.get("ok") else {}
        key, step = (p[:-2], 0.37) if p.endswith("#2") else (p, 0.1)
        for o, v0 in flat0.items():
            if _num(v0) and _num(f.get(o)):
                s = (f[o] - v0) / step
                prev = slopes.setdefault(o, {}).get(key)
                slopes[o][key] = (s, prev[0]) if prev else (s, s)
    outs: dict[str, dict] = {}
    for name in names:
        ref = b.outputs.get(name)
        if ref is None:
            outs[name] = {"result": "not_evaluable", "why": "not bound"}
            continue
        if waits.get(name):
            w = sorted(set(waits[name]))
            outs[name] = {"result": "not_evaluable", "waits_for": w[:12],
                          "why": f"depends on {', '.join(w[:6])}, which the binding leaves to the production defaults (bind it, or state it as config / assumption)"}
            continue
        pv = flat0.get(name)
        if not _num(pv):
            outs[name] = {"result": "not_evaluable", "why": f"the production code returned no number for {name}"}
            continue
        expected, unit = from_production(float(pv), fam, name)
        if expected is None:
            outs[name] = {"result": "not_evaluable", "why": unit}
            continue
        try:
            measured, munit, what = st.measure(ref)
        except BindingError as exc:
            outs[name] = {"result": "not_evaluable", "why": str(exc)}
            continue
        if munit != unit:
            outs[name] = {"result": "not_evaluable", "why": f"{name} is in {unit} but {what} is in {munit}: a {('level' if unit == 'm' else 'length')} binds to one"}
            continue
        tol = LEVEL_TOL_M if unit == "m" else max(LENGTH_TOL_MM, 1e-4 * abs(measured))
        diff = measured - expected
        deps = set(fam.outputs.get(name, {}).get("depends_on") or [])
        row = {"result": "holds" if abs(diff) <= tol else "differs", "expected": round(expected, 4), "measured": round(measured, 4),
               "difference": round(diff, 4), "tolerance": tol, "unit": unit, "measured_as": what}
        under = sorted(deps & set(b.assumptions))
        if under:
            row["under_assumption"] = under
        formula = (fam.outputs.get(name) or {}).get("formula") or {}
        if formula.get("status") == "verified_by_execution":
            row["formula"] = formula.get("display")
        outs[name] = row
    rep["outputs"] = outs
    if only is None:
        rep["unbound_read"] = sorted({p for p, _v in probes})
        rep["structure"] = _structure(fam, b, st)
        if propose:
            rep["proposals"] = _proposals(fam, b, st, flat0, slopes, outs)
    if val is not None and val.get("available"):
        att = _attribute(fam, val, bound)
        errs = [a for a in att if a["sev"] == "err"]
        decided = [a for a in errs if a["decided_by_drawing"]]
        rep["validation"] = {"ran": True, "status": "failed" if decided else ("inconclusive" if errs else "passed"),
                             "checks": len(att), "decided_by_drawing": sum(1 for a in att if a["decided_by_drawing"]), "messages": att[:30]}
    elif fam.data["capabilities"].get("has_validate") and only is not None:
        rep["validation"] = {"ran": False, "status": "not_guarded"}
    else:
        rep["validation"] = {"ran": False, "status": "unsupported",
                             "why": (fam.data.get("validation") or {}).get("reason") or "the registered engine has no validate()"}
    res = [o["result"] for o in outs.values()]
    rep["summary"] = {"holds": res.count("holds"), "differs": res.count("differs"), "not_evaluable": res.count("not_evaluable")}
    rep["status"] = "differs" if "differs" in res else ("holds" if res and all(r == "holds" for r in res) else "partial")
    return rep


def _structure(fam: FamilyKnowledge, b: Binding, st: SheetState) -> list[dict]:
    """Where the drawing's parametrization inverts the production model's dependencies: a production INPUT the drawing derives, or a production
    output (derived from inputs) the drawing holds as an independent value."""
    out = []
    for path, ref in b.inputs.items():
        try:
            if st.role(ref) == "derived":
                out.append({"kind": "input_derived_in_drawing", "field": path, "drawing": ref,
                            "text": f"production treats {path} as an INPUT, but the drawing derives {ref} from other values: in a change it will "
                                    "follow them instead of staying what the design says — make it a value of its own"})
        except BindingError:
            continue
    for name, ref in b.outputs.items():
        try:
            role = st.role(ref)
        except BindingError:
            continue
        rec = fam.outputs.get(name) or {}
        if role == "input" and rec.get("depends_on") and (rec.get("kind") != "level"):
            out.append({"kind": "output_independent_in_drawing", "field": name, "drawing": ref,
                        "text": f"production DERIVES {name} from {', '.join(rec['depends_on'][:5])}, but the drawing holds {ref} as an independent "
                                "value: in a change it will stay put while its parts change — make it a relation (see proposals)"})
    return out


def _proposals(fam: FamilyKnowledge, b: Binding, st: SheetState, flat0: dict, slopes: dict, outs: dict) -> list[dict]:
    """For each bound output, the relation that reproduces it in the drawing's own names: every bound input that moves it (slope measured by
    running the production code at this configuration) must be bound to an independent drawing value and act affinely (two steps agree); the
    coefficient is the slope (in the drawing's units), the constant what is left. Nothing is written by hand; what blocks a proposal is said."""
    out = []
    for name, ref in b.outputs.items():
        rec = fam.outputs.get(name) or {}
        if rec.get("kind") not in ("length", "level") or outs.get(name, {}).get("result") not in ("holds", "differs") or not _num(flat0.get(name)):
            continue
        expected, unit = from_production(float(flat0[name]), fam, name)
        if expected is None:
            continue
        terms, blocked, const = [], [], expected
        for p, r in b.inputs.items():
            s1, s2 = slopes.get(name, {}).get(p, (0.0, 0.0))
            if abs(s1) < 1e-9 and abs(s2) < 1e-9:
                continue  # this input does not move the output here
            try:
                role = st.role(r)
                v, vunit, _what = st.measure(r)
            except BindingError as exc:
                blocked.append(f"{p}: {exc}")
                continue
            if role != "input":
                blocked.append(f"{p} is bound to {r} ({'a derived value' if role == 'derived' else 'measured lines'}): bind it to an independent named value")
                continue
            if abs(s1 - s2) > 1e-6 * max(1.0, abs(s1)):
                blocked.append(f"{name} is not affine in {p}: no linear relation")
                continue
            in_m, _k = fam.length_factor(p)
            out_m, _k2 = fam.length_factor(name, output=True)
            # the slope is d(out)/d(in) in production units; the drawing writes lengths in mm and levels in m
            coef = s1 * ((out_m or 1.0) * (1000.0 if unit == "mm" else 1.0)) / ((in_m or 1.0) * (1000.0 if vunit == "mm" else 1.0))
            nm = r if isinstance(r, str) else r.get("value")
            terms.append((round(coef, 6), nm))
            const -= coef * v
        if blocked:
            out.append({"output": name, "drawing": ref, "relation": None, "blocked_by": blocked[:4]})
            continue
        if not terms:
            continue
        expr = " + ".join((f"{c:g} * {n}" if c != 1 else n) for c, n in terms)
        if abs(const) > 1e-6:
            expr += f" + {round(const, 6):g}" if const > 0 else f" - {round(-const, 6):g}"
        expr = expr.replace("+ -", "- ")
        formula = rec.get("formula") or {}
        row = {"output": name, "drawing": ref, "relation": expr, "unit": unit,
               "basis": f"the production engine's {name} at this configuration (slopes measured by running it"
                        + (f"; formula {formula['display']}" if formula.get("status") == "verified_by_execution" else "") + ")"}
        lines = _lines_of(st, ref)
        if lines and unit == "mm":
            near, far = lines
            row["lines"] = [near, far]
            row["adopt_with"] = (f"set_relation(name, expr='{expr}', from_line='{near}', to_line='{far}') names it, and the engine says whether the "
                                 f"set-out keeps it; to make the drawing keep it in every change, set_formulas {{line: '{far}', expr: '{near} + {expr}'}} "
                                 "(or a plan that preserves its parts)")
        else:
            row["adopt_with"] = "set_relation(name, expr) names it; the engine says whether the set-out keeps it"
        out.append(row)
    return out


def _lines_of(st: SheetState, ref) -> tuple[str, str] | None:
    """The two set-out lines a length reference measures, near (smaller coordinate) first — or None."""
    try:
        _uid, us = st.of(ref)
    except BindingError:
        return None
    pair = None
    if isinstance(ref, dict) and isinstance(ref.get("lines"), list) and len(ref["lines"]) == 2:
        pair = tuple(ref["lines"])
    else:
        name = ref if isinstance(ref, str) else (ref.get("value") if isinstance(ref, dict) else None)
        p = us.prog.params.get(name) if name else None
        if p is not None and p.measures:
            pair = tuple(p.measures)
    if not pair or any(d not in us.datum_mm for d in pair):
        return None
    a, b = pair
    return (a, b) if us.datum_mm[a] <= us.datum_mm[b] else (b, a)


def guard_errors(fam: FamilyKnowledge, b: Binding, st, br: RuleBridge, freshness: dict | None = None) -> list[str]:
    """What stops a change: a guarded output that held when the binding was accepted and no longer holds on the regenerated drawing, a new
    validation error the drawing's own values decide, or a guard that can no longer be verified. Empty: every guard holds."""
    if not b.guards and not b.guard_validation:
        return []
    rep = evaluate(fam, b, st, br, only=list(b.guards), freshness=freshness, propose=False)
    tag = f"production rule ({fam.key}{', ' + b.id if b.id else ''})"
    if rep["status"] in ("unavailable", "error", "stale", "refused"):
        why = rep.get("why") or "; ".join(rep.get("problems", [])[:2])
        return [f"{tag}: the guarded relations cannot be verified — {why}"]
    out = []
    for name, r in rep["outputs"].items():
        if r["result"] == "differs":
            out.append(f"{tag}: {name} — the production engine computes {r['expected']:g} {r['unit']} from the drawing's values but the "
                       f"regenerated drawing measures {r['measured']:g} {r['unit']} ({r['measured_as']}); it held before the change")
        elif r["result"] == "not_evaluable":
            out.append(f"{tag}: {name} can no longer be checked ({r['why']})")
    v = rep.get("validation") or {}
    if b.guard_validation and v.get("ran"):
        known = set(b.validation_baseline)
        for m in v["messages"]:
            if m["sev"] == "err" and m["decided_by_drawing"] and message_key(m["msg"]) not in known:
                out.append(f"{tag}: the production engine's validation now fails — {m['msg']} (decided by {', '.join(m['fields'][:4])})")
    return out
