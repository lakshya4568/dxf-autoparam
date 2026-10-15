"""The production rule engines as the agent's tools — on when the domain pack's library declares production knowledge.

The model decides WHAT: which family a drawing is (if any), which production field each of the drawing's own values plays, what it states and
what it assumes, whether to keep a binding, and what a change means. The engine does the rest deterministically: it reads the knowledge (with
its provenance and freshness), measures the drawing's values, runs the production code through the bridge, attributes every validation message
to the fields that decided it, refuses what does not resolve, and guards what held. Nothing here moves a line.

    production_families      which families exist, whether their rules can run here, which THIS drawing's printed words point at
    production_knowledge     one family's knowledge, section by section (parameters, outputs and formulas, views, operations, validation, findings)
    check_production_model   run the production code on the drawing's values (nothing kept): holds / differs / not_evaluable, validation,
                             inverted dependencies, relations to adopt
    bind_production_model    keep a binding on the sheet (undoable): what held is guarded against any later change
    assess_change            what a change means in the production model, and whether this drawing can take it (a value) or not (a topology change)
    validate_views           every view as checked now: geometry, production rules, cross-view consistency, what is unresolved

Like the library, this is off unless a person switched the domain pack on for the run; nothing the model is told by default names a family.
"""

from __future__ import annotations

import copy
import json
import re

from ..crossview import SheetError
from ..production import manifest as M
from ..production import service
from ..production.binding import Binding, BindingError, SheetState, UnitState, _flat, assemble, from_production
from ..production.bridge import BridgeError, BridgeUnavailable, default_bridge
from ..production.formulas import get_path, set_path
from . import library

_S, _N, _B = {"type": "string"}, {"type": "number"}, {"type": "boolean"}
_LIST = {"type": "array", "items": {"type": "string"}}
_REF = {"anyOf": [{"type": "string"}, {"type": "object"}]}
_MAP = {"type": "object", "additionalProperties": _REF,
        "description": "production field → the drawing's own quantity: a value or level NAME, {lines: [a, b]} (a distance), {line: y…} (a level); "
                       "add unit: U… for a quantity in another unit"}
_STATED = {"type": "object", "additionalProperties": {"type": "object"},
           "description": "production field → {value, basis} (config: what the drawing states that its geometry cannot measure, e.g. a count) or "
                          "{value, why} (assumptions: what the drawing does not show)"}
WHY = {"type": "string", "description": "One short sentence for the person watching: what you are doing with this call and why."}
_BINDING = {"family": _S, "unit": _S, "inputs": _MAP, "outputs": _MAP, "config": _STATED, "assumptions": _STATED, "evidence": _LIST, "why": WHY}

PRODUCTION_TOOL_SPECS = [
    ("production_families", ("The production rule engines this run can consult: each family with its title, whether its rules can run here, whether its "
                             "knowledge still describes the production code, how much of it is verified, and which families THIS drawing's printed words "
                             "point at (with the words). A match is a lead: confirm it on the drawing."),
     {"type": "object", "properties": {"query": _S, "why": WHY}, "required": []}),
    ("production_knowledge", ("One family's production knowledge, section by section: summary, parameters (fields: kind, unit, meaning, default, which "
                              "outputs and views each affects), outputs (what each depends on — measured by running the code — and its formula where "
                              "the code is plain arithmetic, verified by execution), views (the list, what changes it, which fields change each view), "
                              "operations (what can be changed and what that means for an existing drawing), validation (the engine's own checks), "
                              "findings (disabled checks, stale copies, divergences). Filter with `paths` or `query`. Every item carries its status; "
                              "nothing here is a value of this drawing."),
     {"type": "object", "properties": {"family": _S, "sections": _LIST, "paths": _LIST, "query": _S, "limit": _N, "why": WHY}, "required": ["family"]}),
    ("check_production_model", ("Run the production rule engine on THIS drawing's values; nothing is kept. Map production inputs and outputs to the "
                                "drawing's own quantities (a number is refused: config and assumptions take {value, basis|why}). The answer: per output "
                                "holds / differs / not_evaluable (with the field it waits for), the engine's validation message by message with whether "
                                "the drawing's values decided it, `structure` (where your parametrization holds a derived quantity as independent, or "
                                "derives an input), and `proposals` (relations in your own names you can adopt with set_relation)."),
     {"type": "object", "properties": dict(_BINDING), "required": ["family", "inputs"]}),
    ("bind_production_model", ("Keep a binding on the sheet (one undoable step; same arguments as check_production_model, plus `guard`, default true). "
                               "Outputs that hold — and the engine's validation where the drawing's values decide it — become GUARDS: a later change "
                               "that breaks one is refused with the reason and nothing is applied. An output that differs is a conflict: the drawing "
                               "wins; check the binding or record it. Pending edits of the open unit are applied first."),
     {"type": "object", "properties": {**_BINDING, "guard": _B}, "required": ["family", "inputs"]}),
    ("assess_change", ("What a change means in the production model, before you plan it: `changes` = {production field: new value in the field's own "
                       "unit} on top of a kept binding (`binding` id, or family + unit). Returns each bound output before and after in the drawing's "
                       "units, the views the production renderers redraw, and per changed field whether this drawing can take it: parametric (a "
                       "bound value drives it: plan it with propose_plan), a feature operation (a stated count the drawing can take by repeating or "
                       "removing one instance of its repeated unit: plan it with propose_plan(operation)) or a topology change (an option, or a count "
                       "this drawing cannot take faithfully) — with the reason."),
     {"type": "object", "properties": {"binding": _S, "family": _S, "unit": _S, "changes": {"type": "object", "additionalProperties": {}}, "why": WHY},
      "required": ["changes"]}),
    ("validate_views", ("Every view of the sheet as checked now, from what actually ran: geometry (the unit regenerated and checked), production rules "
                        "bound to it (holds / differs / not_evaluable, validation), cross-view consistency (shared values measured in each view, links "
                        "to other units), and what is unresolved. A view no production rule covers says so — it is not a pass."),
     {"type": "object", "properties": {"views": _LIST, "why": WHY}, "required": []}),
]
PRODUCTION_READ = {"production_families", "production_knowledge", "check_production_model", "assess_change", "validate_views"}
PRODUCTION_WRITE = {"bind_production_model"}
PRODUCTION_TOOLS = PRODUCTION_READ | PRODUCTION_WRITE
_ARGS = {n: set(p.get("properties", {})) | {"why"} for n, _d, p in PRODUCTION_TOOL_SPECS}
MAX_RESULT_CHARS = 14000
SECTIONS = ("summary", "parameters", "outputs", "views", "operations", "validation", "findings")


def production_for(pack: dict | None) -> M.ProductionKnowledge | None:
    """The production knowledge the pack's library declares (`production_knowledge` in its domain.json), when it exists and has families."""
    lib = library.for_pack(pack)
    rel = lib.meta.get("production_knowledge") if lib else None
    if not rel:
        return None
    path = (lib.dir / rel).resolve()
    pk = M.knowledge() if path == M.default_dir().resolve() else M.ProductionKnowledge(path)
    return pk if pk.available() else None


def tool_specs(pack: dict | None) -> list:
    return PRODUCTION_TOOL_SPECS if production_for(pack) is not None else []


def protocol(pack: dict | None) -> str:
    if production_for(pack) is None:
        return ""
    return ("PRODUCTION RULE ENGINES (on for this run): the knowledge of the production application's own rule engines — per family, the fields of its "
            "model, what each output depends on (measured by running the code), formulas verified by execution, the views each field changes, its "
            "validation — and the engines themselves, run on THIS drawing's values. Use them to decide what is an input and what is derived, which "
            "views a change reaches, and whether a change is a value change or a topology change. production_families → production_knowledge for "
            "the family you confirm on the drawing → check_production_model with each field mapped to YOUR value / level names (or lines) → "
            "bind_production_model to keep what holds as guards → assess_change before propose_plan → validate_views before finish. The engine "
            "never fills a field the drawing does not bind: an output that depends on one is not_evaluable, and you say what the drawing states "
            "(config, with its basis) or assumes (assumptions, with why). Where production and the drawing differ, the drawing wins: check your "
            "binding, record the conflict, ask the person — never move a line to agree. A change the engine calls a topology change is refused "
            "before anything is changed: say so to the person. A stated count the drawing can take is a feature operation: assess_change returns the "
            "operation to hand to propose_plan.")


def _clip_list(xs: list, limit: int) -> tuple[list, int]:
    return xs[:limit], max(0, len(xs) - limit)


def _fit(out: dict, limit: int = MAX_RESULT_CHARS) -> dict:
    """A result within the character budget: the longest lists are cut (and say how much was cut) until it fits."""
    s = json.dumps(out, default=str)
    while len(s) > limit:
        key, longest = None, 0
        for sec in out.values() if isinstance(out, dict) else []:
            if isinstance(sec, dict):
                for k, v in sec.items():
                    if isinstance(v, list) and len(v) > longest:
                        key, longest = (sec, k), len(v)
        for k, v in out.items():
            if isinstance(v, list) and len(v) > longest:
                key, longest = (out, k), len(v)
        if key is None or longest <= 3:
            break
        d, k = key
        d[k] = d[k][: max(3, longest // 2)]
        d.setdefault("cut", {})[k] = f"{longest - len(d[k])} more: narrow with paths / query"
        s = json.dumps(out, default=str)
    return out


class ProductionSession:
    """The tools' implementation for ONE run: the knowledge, the sheet (bindings live on it), the run's units, and the trace."""

    def __init__(self, pk: M.ProductionKnowledge, bench):
        self.pk = pk
        self.bench = bench
        self.trace: list[dict] = []
        self.checks: list[dict] = []
        self.bound: list[dict] = []
        self.refused: list[str] = []
        self.assessments: list[dict] = []
        self.view_reports = 0

    @property
    def sm(self):
        return self.bench.sm

    def call(self, name: str, args: dict) -> dict:
        if name not in PRODUCTION_READ:
            return {"error": f"{name} is not a production read tool"}
        extra = set(args) - _ARGS[name]
        if extra:
            return {"error": f"unknown argument(s) for {name}: {sorted(extra)}; it takes {sorted(_ARGS[name] - {'why'})}"}
        a = {k: v for k, v in args.items() if k != "why"}
        try:
            res = getattr(self, "_" + name)(**a)
        except (M.KnowledgeError, BindingError, service.ProductionRefusal) as exc:
            res = {"ok": False, "error": str(exc)[:600]}
        except TypeError as exc:
            res = {"ok": False, "error": f"bad arguments for {name}: {exc}"[:300]}
        self.trace.append({"n": len(self.trace) + 1, "tool": name, "args": {k: (v if len(json.dumps(v, default=str)) < 120 else "…") for k, v in a.items()},
                           "ok": not res.get("error")})
        return _fit(res)

    # ── reading ──────────────────────────────────────────────────────────────────

    def _texts(self) -> list[str]:
        return library.drawing_texts(self.sm.dr.items)

    def _production_families(self, query: str = "") -> dict:
        st = default_bridge().status()
        words = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
        rows = []
        for f in self.pk.index["families"]:
            if words and not words & set(re.findall(r"[a-z0-9]+", (f["family"] + " " + f["title"]).lower())):
                continue
            fresh = self.pk.freshness(f["family"]) if f["has_compute"] else {"state": "n/a"}
            rows.append({"family": f["family"], "title": f["title"], "rule_engine": f["has_compute"], "validation": f["has_validate"],
                         "outputs": f["outputs"], "formulas_verified": f["formulas_verified"], "views": f["views"],
                         "units_authored": f.get("overlay", False), "knowledge": fresh.get("state")})
        return {"families": rows, "runs_here": st["available"], **({"why_not": st.get("reason")} if not st["available"] else {}),
                "source": {k: self.pk.index["source"].get(k) for k in ("repository", "commit", "branch")},
                "match_this_drawing": self.pk.discover(self._texts()) or "none: the drawing prints none of the families' words",
                "note": "a match is a lead: confirm on the drawing (zoom_view) before binding; look-alike families share most words"}

    def _production_knowledge(self, family: str, sections: list[str] | None = None, paths: list[str] | None = None, query: str = "",
                              limit: float = 40) -> dict:
        fam = self.pk.family(family)
        secs = [s for s in (sections or ["summary", "parameters", "outputs"]) if s in SECTIONS]
        unknown = [s for s in (sections or []) if s not in SECTIONS]
        lim = max(5, min(int(limit or 40), 120))
        terms = [t for t in re.findall(r"[a-z0-9_]+", (query or "").lower()) if len(t) > 1]
        want = [p for p in (paths or []) if p]

        def keep(path: str, *texts: str) -> bool:
            if want and not any(path == p or path.startswith(p.rstrip(".") + ".") for p in want):
                return False
            hay = " ".join([path, *[t or "" for t in texts]]).lower()
            return all(t in hay for t in terms) if terms else True

        d = fam.data
        out: dict = {"family": fam.key, "title": fam.title,
                     "provenance": {"repository": "aagento-bridge", "commit": d["source"].get("commit"), "registry": d["source"].get("registry"),
                                    "rule_engine": (d["source"]["modules"].get("ruleEngine") or {}), "sources_digest": d["source"]["sources_digest"][:16],
                                    "knowledge": self.pk.freshness(fam.key).get("state")},
                     "trust": ("extracted from the production code and measured by running it; formulas only where verified by execution; units "
                               "'authored' were read from the source by a person (cited), 'inferred_dimensional' follow from formulas, 'unknown' cannot be bound")}
        if not fam.supported:
            out["unsupported"] = d.get("unsupported")
            return out
        if "summary" in secs:
            out["summary"] = {"capabilities": d["capabilities"], "formulas": d.get("formulas_summary"), "validation": (d.get("validation") or {}).get("available"),
                              "views": [v["mode"] + ": " + " / ".join(v.get("labels", [])) for v in fam.views],
                              "findings": [f["kind"] for f in d.get("findings", [])], "parameters": len(fam.params), "outputs": len(fam.outputs)}
        if "parameters" in secs:
            rows = []
            for p in d["parameters"]:
                if not keep(p["path"], p.get("label"), p.get("component"), p.get("kind")):
                    continue
                row = {"path": p["path"], "kind": p.get("kind"), "unit": p.get("unit"), "unit_status": p.get("unit_status")}
                for k in ("label", "component", "default", "read_by_compute"):
                    if p.get(k) not in (None, ""):
                        row[k] = p[k]
                if p.get("affects_outputs"):
                    row["affects_outputs"] = p["affects_outputs"][:10]
                if p.get("affects_views"):
                    row["affects_views"] = p["affects_views"]
                if p.get("code_fallback"):
                    row["absent_from_defaults"] = "the code falls back to its own constant when absent"
                if p.get("values_that_change_outputs"):
                    row["values_that_change_outputs"] = p["values_that_change_outputs"][:6]
                if p.get("evidence"):
                    row["evidence"] = p["evidence"][:3]
                    row["evidence_check"] = p.get("evidence_check")
                rows.append(row)
            rows.sort(key=lambda r: (not r.get("label"), not r.get("affects_outputs"), r["path"]))
            out["parameters"], more = _clip_list(rows, lim)
            if more:
                out["parameters_more"] = more
        if "outputs" in secs:
            rows = []
            for o in d["outputs"]:
                if not keep(o["name"], o.get("label"), o.get("kind")):
                    continue
                row = {"name": o["name"], "kind": o.get("kind"), "unit": o.get("unit"), "depends_on": o.get("depends_on", [])[:12]}
                if o.get("label"):
                    row["label"] = o["label"]
                aff = [p for p, x in (o.get("partials") or {}).items() if x.get("affine")]
                if aff and len(aff) != len(o.get("depends_on", [])):
                    row["affine_in"] = aff[:12]
                f = o.get("formula") or {}
                if f.get("status") in ("verified_by_execution", "constant_verified"):
                    row["formula"] = {"text": f.get("display"), "status": f["status"], "samples": f.get("samples"), "line": f.get("line"),
                                      **({"note": f["note"]} if f.get("note") else {})}
                elif f:
                    row["formula"] = {"status": f.get("status"), "why": (f.get("why") or "")[:140]}
                rows.append(row)
            rows.sort(key=lambda r: (not r.get("label"), r.get("formula", {}).get("status") != "verified_by_execution", r["name"]))
            out["outputs"], more = _clip_list(rows, lim)
            if more:
                out["outputs_more"] = more
        if "views" in secs:
            vv = d.get("views") or {}
            out["views"] = {"decided_by": vv.get("decided_by", []),
                            "list": [{"mode": v["mode"], "labels": v.get("labels"), "when": v.get("conditions"), "renders_headless": v.get("renders"),
                                      "changed_by": [p for p in v.get("affected_by", []) if keep(p)][:20],
                                      **({"error": v["error"][:120]} if v.get("error") else {})} for v in vv.get("views", [])]}
        if "operations" in secs:
            ops = [o for o in d.get("operations", []) if keep(o["path"])]
            out["operations"], more = _clip_list([{k: v for k, v in o.items() if k != "outputs"} | {"outputs": o.get("outputs", [])[:6]} for o in ops], lim)
            if more:
                out["operations_more"] = more
        if "validation" in secs:
            v = d.get("validation") or {}
            out["validation"] = {"available": v.get("available"), **({"reason": v.get("reason")} if v.get("reason") else {}),
                                 "messages_at_defaults": v.get("messages_at_defaults", [])[:12], "disabled_rules": v.get("disabled_rules", [])}
        if "findings" in secs:
            out["findings"] = d.get("findings", [])
            if d.get("duplicates"):
                out["duplicates"] = d["duplicates"]
        if unknown:
            out["no_such_section"] = unknown
            out["sections"] = list(SECTIONS)
        return out

    # ── running the production code on the drawing ───────────────────────────────

    def _unit_of(self, unit: str | None) -> str:
        uid = unit or self.bench.active or (self.bench.run.scope.get("units") or [None])[0]
        if uid not in self.sm.units:
            raise BindingError(f"no unit {uid!r}: name the unit whose values you bind (inspect_sheet lists them), or open it")
        return uid

    def _state(self, binding: dict) -> SheetState:
        """The units a binding reads: an open unit as the run's workbench has it now (names it just defined included), others as the sheet holds them."""
        b = {"unit": binding["unit"], "inputs": binding.get("inputs") or {}, "outputs": binding.get("outputs") or {}}
        st = self.sm._domain_state(b)
        for uid in list(st.units):
            wb = self.bench.units.get(uid)
            if wb is not None:
                st.units[uid] = UnitState.of(wb.prog, {})
        return st

    def _binding(self, a: dict) -> dict:
        b = {k: a.get(k) for k in ("family", "inputs", "outputs", "config", "assumptions", "evidence") if a.get(k) is not None}
        b["unit"] = self._unit_of(a.get("unit"))
        b.setdefault("inputs", {})
        b.setdefault("outputs", {})
        return b

    def _check_production_model(self, family: str, inputs: dict, unit: str | None = None, outputs: dict | None = None, config: dict | None = None,
                                assumptions: dict | None = None, evidence: list | None = None) -> dict:
        b = self._binding({"family": family, "unit": unit, "inputs": inputs, "outputs": outputs, "config": config, "assumptions": assumptions})
        rep = service.report(b, self._state(b))
        self.checks.append({"family": family, "unit": b["unit"], "status": rep.get("status"), "summary": rep.get("summary")})
        return _brief(rep)

    def _assess_change(self, changes: dict, binding: str | None = None, family: str | None = None, unit: str | None = None) -> dict:
        kept = next((b for b in self.sm.domain if b.get("id") == binding or (family and b.get("family") == family and (not unit or b.get("unit") == unit))), None)
        if kept is None:
            return {"ok": False, "error": "no kept binding to assess against: bind_production_model first (assess_change compares the bound outputs)",
                    "kept": [b.get("id") for b in self.sm.domain]}
        if not isinstance(changes, dict) or not changes:
            return {"ok": False, "error": "changes: {production field: new value in the field's own unit}"}
        fam = self.pk.family(kept["family"])
        b = Binding.from_json(kept)
        st = self._state(kept)
        model, _prov, probs = assemble(fam, b, st)
        if probs:
            return {"ok": False, "error": "the kept binding no longer resolves: " + "; ".join(probs[:3])}
        after = copy.deepcopy(model)
        fields = []
        for p, v in changes.items():
            rec = fam.params.get(p)
            if rec is None:
                fields.append({"field": p, "status": "unknown", "why": f"not a field of {fam.key}"})
                continue
            try:
                set_path(after, p, v)
            except KeyError:
                fields.append({"field": p, "status": "unknown", "why": "the production model's shape cannot hold it"})
                continue
            kind = rec.get("kind")
            row = {"field": p, "kind": kind, "from": get_path(model, p), "to": v, "views": rec.get("affects_views", [])}
            if kind == "count" or kind in ("flag", "text"):
                row.update(status="topology_change", can_apply=False,
                           why=("a change of count or option adds or removes members of the structure (their outlines, hatches, dimensions, notes); "
                                "the regeneration engine moves the entities a drawing already has and never creates or deletes geometry — refused before "
                                "anything changes. The production model's numbers for it are shown so the person can decide how to redraw."))
                if kind == "count" and p in b.config:
                    row.update(self._count_change(fam, kept, b, p, v, rec))
                    if row.get("can_apply"):
                        row.pop("why", None)
            elif p in b.inputs:
                ref = b.inputs[p]
                name = ref if isinstance(ref, str) else (ref.get("value") if isinstance(ref, dict) else None)
                m_per, _k = fam.length_factor(p)
                drawing_value = (v * (m_per or 1.0) * 1000.0) if kind == "length" else v
                if name:
                    row.update(status="parametric", can_apply=True, drives=name, requested_value=round(drawing_value, 4),
                               how=f"propose_plan(parameter='{name}', requested_value={round(drawing_value, 4)}) — the plan decides what moves and what stays")
                else:
                    row.update(status="parametric_unnamed", can_apply=False,
                               why=f"bound to {ref}, which is measured, not a named value: name it (define_parameters) so a plan can change it")
            elif p in b.config or p in b.assumptions:
                row.update(status="stated_not_drawn", can_apply=False, why="the drawing does not measure this field (config / assumption): nothing on it moves")
            else:
                row.update(status="unbound", can_apply=False, why="the binding does not map this field to the drawing: bind it before planning a change of it")
            fields.append(row)
        try:
            d0 = _flat(default_bridge().request("compute", family=fam.key, model=model)["derived"])
            d1 = _flat(default_bridge().request("compute", family=fam.key, model=after)["derived"])
        except (BridgeUnavailable, BridgeError) as exc:
            return {"ok": False, "fields": fields, "error": f"the production rules cannot run: {exc}"}
        outs = {}
        for name in b.outputs:
            if isinstance(d0.get(name), (int, float)) and isinstance(d1.get(name), (int, float)):
                e0, u0 = from_production(float(d0[name]), fam, name)
                e1, _u1 = from_production(float(d1[name]), fam, name)
                if e0 is not None:
                    outs[name] = {"before": round(e0, 4), "after": round(e1, 4), "change": round(e1 - e0, 4), "unit": u0}
        views = sorted({v for f in fields for v in f.get("views", [])})
        labels = {v["mode"]: " / ".join(v.get("labels", [])) for v in fam.views}
        res = {"ok": True, "binding": kept["id"], "fields": fields, "outputs": outs, "views_production_redraws": [f"{v}: {labels.get(v, '')}" for v in views],
               "verdict": ("every changed field can be applied to this drawing: plan it (a value with propose_plan(parameter, requested_value), a count "
                           "with propose_plan(operation))" if fields and all(f.get("can_apply") for f in fields) else
                           "not everything can be applied to this drawing: see each field's status")}
        self.assessments.append({"binding": kept["id"], "fields": [(f["field"], f.get("status")) for f in fields]})
        return res

    def _count_change(self, fam, kept: dict, b: Binding, path: str, value, rec: dict) -> dict:
        """A change of a COUNT the binding states, as a feature operation on the unit's repeated lattice (feature.py): planned through the whole chain
        — the derived drawing, the parametrization carried over, the guards at the new count — and said to be possible only when all of it holds."""
        stated = b.config.get(path)
        current = stated.get("value") if isinstance(stated, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or value < 1:
            return {"feature_operation": {"status": "refused", "refusals": [f"{path}: a count is a whole number of at least 1 (got {value!r})"]}}
        seg = path.rsplit(".", 1)[-1].lower()
        nouns = sorted({seg, seg.removesuffix("s")} - {""})  # the field's own word for the thing counted
        op = {"kind": "set_count", "count": int(value), "unit": kept["unit"], "binding": kept["id"], "field": path, "nouns": nouns,
              **({"current": int(current)} if isinstance(current, (int, float)) and not isinstance(current, bool) else {})}
        try:
            plan = self.sm.plan_feature(kept["unit"], op)
        except (SheetError, KeyError, ValueError) as exc:
            return {"feature_operation": {"status": "refused", "refusals": [str(exc)[:300]]}}
        brief = {k: plan[k] for k in ("id", "status", "from_count", "to_count", "grows_mm", "pitch_mm", "effects", "notes_rewritten") if k in plan}
        brief["warnings"] = plan.get("warnings", [])[:4]
        if plan["status"] == "ready":
            return {"status": "feature_operation", "can_apply": True, "feature_operation": brief, "operation": op,
                    "how": f"propose_plan(operation={json.dumps(op)}) — the engine derives the drawing at the new count, carries the parametrization over "
                           "by name and applies it only if the production guards hold at the new count; one undo takes it back"}
        brief["refusals"] = plan.get("refusals", [])[:4]
        if plan.get("questions"):
            brief["questions"] = [{"text": q["text"], "options": q.get("options", []), "about": q.get("about")} for q in plan["questions"]][:2]
            return {"feature_operation": brief, "operation": op,
                    "why": ("a change of count needs a decision first — " + " | ".join(q["text"] for q in plan["questions"][:2])
                            + " Ask the person; the answer goes into the operation (`detached`, `repeat`, `drop_plans`).")[:700]}
        return {"feature_operation": brief,
                "why": ("a change of count adds or removes members of the structure; this drawing cannot take it faithfully — "
                        + ("; ".join(plan.get("refusals", [])[:3]) or plan["status"]))[:700]}

    def _validate_views(self, views: list[str] | None = None) -> dict:
        sm = self.sm
        want = set(views or [])
        rows = []
        domain_by_unit: dict[str, list[dict]] = {}
        with self.bench._lock():
            reports = sm.domain_report()
            for rep, b in zip(reports, sm.domain, strict=True):
                for uid in Binding.from_json(b).units():
                    domain_by_unit.setdefault(uid, []).append(rep)
            for g in sm.layout.views():
                if want and g.id not in want:
                    continue
                uid = sm.unit_of_view.get(g.id)
                row = {"view": g.id, "name": g.name, "type": g.view_type, "unit": uid}
                if uid is None:
                    row["geometry"] = {"status": "not_run", "why": "this view belongs to no unit"}
                    rows.append(row)
                    continue
                u = sm.unit(uid)
                sr = sm.regenerate(units={uid})
                errs = [e for e in sr.errors if e.startswith(uid + ":")]
                warns = [w for w in sr.warnings if w.startswith(g.id)]
                row["geometry"] = {"status": "failed" if errs else "passed", "parametrized": bool(u.answer), "errors": errs[:4], "warnings": warns[:3]}
                reps = domain_by_unit.get(uid, [])
                if not reps:
                    row["production_rules"] = {"relations": "unsupported", "engine_validation": "unsupported",
                                               "why": "no production binding covers this unit (bind_production_model) — not a pass"}
                else:
                    sts = [r.get("status") for r in reps]
                    vals = [((r.get("validation") or {}).get("status")) for r in reps]
                    rel = ("unavailable" if any(s in ("unavailable", "error", "stale") for s in sts) else "failed" if "differs" in sts else
                           "partial" if "partial" in sts else "passed")
                    val = ("failed" if "failed" in vals else "inconclusive" if "inconclusive" in vals else "passed" if "passed" in vals else "unsupported")
                    row["production_rules"] = {"relations": rel, "engine_validation": val,
                                               "bindings": [{"id": r.get("binding"), "family": r.get("family"), "status": r.get("status"),
                                                             "summary": r.get("summary"), "validation": (r.get("validation") or {}).get("status"),
                                                             "guards": r.get("guards"), **({"why": r.get("why")} if r.get("why") else {})} for r in reps]}
                shared = [(p, bd) for p in sm.shared.values() for bd in p.bindings if bd.unit == uid]
                bad = [f"{p.name}: {bd.status}" for p, bd in shared if bd.status != "drives"]
                bad += [e for e in errs if "did not follow" in e or "measures" in e]
                links = [r for r in reps if r.get("unit") != uid]
                if not shared and len(u.views) < 2 and not links:
                    row["cross_view"] = {"status": "not_applicable", "why": "no shared value, no projection partner, no binding to another unit"}
                else:
                    row["cross_view"] = {"status": "failed" if bad else "passed", "shared_values": [p.name for p, _bd in shared][:10],
                                         "projection_partners": [v for v in u.views if v != g.id], "problems": bad[:4]}
                unresolved = []
                for r in reps:
                    unresolved += [f"{r.get('family')}.{n}: {o.get('why', '')[:90]}" for n, o in (r.get("outputs") or {}).items() if o.get("result") == "not_evaluable"]
                unresolved += [f"refused: {x['item']}" for x in self.bench.open_refusals() if x.get("unit") == uid]
                unresolved += [f"question: {q.get('text', '')[:90]}" for q in self.bench.person_questions() if q.get("unit") == uid]
                row["unresolved"] = {"count": len(unresolved), "items": unresolved[:8]}
                rows.append(row)
        self.view_reports += 1
        return {"views": rows, "note": "statuses come from what ran now; 'unsupported' and 'not_applicable' are not passes"}

    # ── writing ──────────────────────────────────────────────────────────────────

    def bind(self, a: dict) -> dict:
        """bind_production_model: the open units' edits are applied first (the binding refers to what the sheet holds), then the sheet keeps it."""
        extra = set(a) - _ARGS["bind_production_model"]
        if extra:
            return {"ok": False, "rejected": [f"unknown argument(s) {sorted(extra)}"]}
        committed = {u: self.bench.commit(u) for u in list(self.bench.units)}
        bad = {u: r for u, r in committed.items() if not r["ok"]}
        if bad:
            return {"ok": False, "rejected": [f"{u}: its edits could not be applied first — {r['error'][:200]}" for u, r in bad.items()]}
        try:
            b = self._binding(a)
        except BindingError as exc:
            return {"ok": False, "rejected": [str(exc)]}
        guard = a.get("guard", True) is not False
        try:
            with self.bench._lock():
                rep = self.sm.bind_domain(b, guard=guard)
                self.bench.sync_revision()
        except Exception as exc:  # noqa: BLE001 — a SheetError (refusal) or a binding error: said to the model, nothing kept
            self.refused.append(f"{a.get('family')}@{b.get('unit')}: {str(exc)[:160]}")
            return {"ok": False, "rejected": [str(exc)[:600]]}
        self.bound.append({"id": rep.get("binding"), "status": rep.get("status"), "guards": rep.get("guards"), "conflicts": rep.get("conflicts", [])})
        self.bench.run.emit({"kind": "applied", "unit": b["unit"], "revision": self.sm.revision, "production_binding": rep.get("binding")})
        out = _brief(rep)
        out["ok"] = True
        out["kept"] = rep.get("binding")
        for k in ("guards", "guard_validation", "guards_note", "conflicts", "conflicts_note"):
            if k in rep:
                out[k] = rep[k]
        return out

    # ── the run's verdict ─────────────────────────────────────────────────────────

    def summary(self) -> dict:
        with self.bench._lock():
            final = self.sm.domain_report() if self.sm.domain else []
        return {"calls": len(self.trace), "checks": self.checks[-20:], "bindings_kept": self.bound, "refused": self.refused[-10:],
                "assessments": self.assessments[-10:], "view_reports": self.view_reports,
                "at_the_end": [{"id": r.get("binding"), "status": r.get("status"), "summary": r.get("summary"), "guards": r.get("guards"),
                                "validation": (r.get("validation") or {}).get("status")} for r in final]}

    def notes(self) -> list[str]:
        s = self.summary()
        if not s["calls"] and not s["bindings_kept"]:
            return ["production rule engines were on and never consulted"]
        out = []
        for r in s["at_the_end"]:
            sm = r.get("summary") or {}
            out.append(f"production rules {r['id']}: {r['status']} — {sm.get('holds', 0)} hold, {sm.get('differs', 0)} differ, "
                       f"{sm.get('not_evaluable', 0)} not evaluable; {len(r.get('guards') or [])} guarded; validation {r.get('validation')}")
            if sm.get("differs"):
                out.append(f"production rules {r['id']}: {sm['differs']} relation(s) differ between the production engine and the drawing — the drawing was kept")
        if s["refused"]:
            out.append("production bindings refused: " + "; ".join(s["refused"][:3]))
        topo = [f for a in s["assessments"] for f in a["fields"] if f[1] == "topology_change"]
        if topo:
            out.append("topology changes assessed and not applicable to this drawing: " + ", ".join(f[0] for f in topo[:4]))
        return out


def _brief(rep: dict) -> dict:
    """A report as the model reads it: inputs without their full provenance, outputs and validation compact."""
    out = {k: rep.get(k) for k in ("status", "family", "unit", "summary", "structure", "proposals", "unbound_read") if rep.get(k) is not None}
    if rep.get("problems"):
        out["problems"] = rep["problems"][:8]
    if rep.get("why"):
        out["why"] = rep["why"]
    if rep.get("inputs"):
        out["inputs"] = {p: (f"{v['what']} = {v['measured']:g} {v['unit']} → {v['production_value']:g}" if v.get("from") == "drawing"
                             else f"{v['from']}: {v.get('value')} ({v.get('basis')})") for p, v in rep["inputs"].items()}
    if rep.get("outputs"):
        out["outputs"] = rep["outputs"]
    v = rep.get("validation")
    if v:
        out["validation"] = ({**{k: v[k] for k in ("status", "checks", "decided_by_drawing") if k in v},
                              "messages": [m for m in v.get("messages", []) if m["sev"] != "ok"][:12] or "every check passed"} if v.get("ran") else v)
    k = rep.get("knowledge") or {}
    if k:
        out["knowledge"] = k.get("state")
    return out
