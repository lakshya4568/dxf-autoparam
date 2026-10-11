"""The parametrization agent: Gemini works on the drawing with TOOLS, one claim at a time, and the engine checks
every edit the moment it is made.

Why not one big answer: a single JSON holding parts, parameters, formulas, constraints and behaviours must be
consistent with itself and with the drawing all at once. One wrong name ripples into a dozen rejections, every
repair is a full rewrite, and the model spends its thinking on bookkeeping (a repair thought for 62k tokens and
produced nothing). Here the model asks small questions (inspect a region, explain a line, what moves when this
value grows) and makes small edits (define this part, this parameter, this formula); each edit comes back
accepted or rejected with the reason in a line, so a mistake costs one small correction.

    prog, report, info = agent_parametrize("drawing.dxf", instructions="…", on_event=print)

The answer it builds has the same shape as the one-shot answer (ai.schema.AIAnswer), so validation, the app,
re-applying a person's selection and saving / re-opening all work unchanged.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from importlib import resources
from pathlib import Path

from ..cadjson import entity_id
from ..graph import affects
from ..intent import _boxes, _geometry, classify, delta_of, resolve_parts
from ..ir import GapKind, Role
from ..program import names_in
from ..regen import regenerate_program
from ..topology import DatumIndex, of
from ..validator import apply
from .parametrize import images_for, prepare
from .prompt import SYSTEM
from .vertex import Gemini, GeminiStopped

DRAFTSMAN = SYSTEM[SYSTEM.index("DRAFTSMAN'S RULES"): SYSTEM.index("THE PERSON'S INSTRUCTIONS")]
PERSON = SYSTEM[SYSTEM.index("THE PERSON'S INSTRUCTIONS"): SYSTEM.index("CONSISTENCY")]

AGENT_SYSTEM = f"""You are a senior bridge design draftsman turning an existing General Arrangement Drawing into a parametric
model, working inside a CAD engine through TOOLS. You never measure and never write coordinates: the engine has
measured everything; you decide what things ARE, which sizes are design inputs, and what each line is set out from.

What you see: a faithful picture, the set-out lines labelled (x… vertical, y… horizontal), a REGION MAP (every closed
area R1, R2 … = the atomic parts), and an OVERVIEW (regions with size / fill / neighbours / notes inside, texts,
dimensions, stated levels, candidate values c… measured between lines). Ask for detail with the inspect tools.

PLAYBOOK — small steps, each checked at once:
  1. set_structure: what the drawing is.
  2. define_parts for the parts, built from regions (assembly → component → subcomponent; every region in one leaf
     part; existing work existing=true; details a draftsman leaves alone parametrize=false).
  3. For each part to parametrize: inspect_regions → define_parameters for its DESIGN INPUTS, naming a candidate (c…)
     or the two lines it spans; the engine fills the value. Equal sizes that move together = one candidate; two
     members that only happen to be equal = two parameters (from_line / to_line).
  4. set_levels for the stated levels (site_input / check_only / derived).
  5. A named size DRIVES its lines by itself: the engine sets one end out from the other (both ends about the axis
     when the size is centred on one). Use set_formulas only for intent sizes do not give (a line that should follow
     a different line, a slope). Between two fixed levels one size in the chain is the result: the engine keeps it
     as a worked-out quantity and tells you; set_formulas makes it an input instead if that is the design intent.
  6. Verify with what_moves(parameter): the parts that should grow grow, the rest stay. Fix with set_formulas.
  7. state_behaviours and add_constraints for the intent that must hold (fixed levels, symmetry, connections).
  8. finish. Any rejection comes back at once with its reason: fix that one item, never redo the rest.

WORK IN BATCHES: one turn may hold many tool calls. Inspect every region you need in one call, define all the parts
in one turn, all the parameters of a part (or of several parts) in one turn, all the formulas you need in one turn.
Aim to finish in about 10 turns; every status tells you how many are left. The OVERVIEW lists this project's concept
names and structure families with their parts: use them without looking them up. Names are made PascalCase for you.

A parameter name used in a formula, constraint or behaviour must be defined with define_parameters (or set_levels)
FIRST. A formula must reproduce its line as drawn (the engine says so if not) and must not create a cycle.
Use knowledge(query) for this project's concept names (ClearSpan, TopSlab, WingLength …).

{DRAFTSMAN}
{PERSON}"""


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


def _batch(props: dict, required: list[str]) -> dict:
    return _schema({"items": {"type": "array", "items": _schema(props, required)}}, ["items"])


S, N, B = {"type": "string"}, {"type": "number"}, {"type": "boolean"}
LIST = {"type": "array", "items": {"type": "string"}}


def _enum(*v: str) -> dict:
    return {"type": "string", "enum": list(v)}


TOOL_SPECS = [
    ("inspect_regions", ("Details of regions: size, fill, holes, neighbours (side, shared length), notes inside, the lines of its edges "
     "(left / right / bottom / top) with what each is set out from, and the measured sizes across it."), _schema({"ids": LIST}, ["ids"])),
    ("inspect_lines", ("Details of set-out lines: position, formula, the chain of lines it is set out from, the parameters that move it, "
     "the parts drawn on it."), _schema({"ids": LIST}, ["ids"])),
    ("find_values", "Candidate values (c…) measured between lines: near a value (mm), and / or spanning a region, and / or on an axis.",
     _schema({"value_mm": N, "region": S, "axis": _enum("x", "y")})),
    ("what_moves", ("Change a parameter (default +10 %) and report what each part does (grows / shrinks / moves / fixed, per axis) and "
     "whether the drawing stays valid."), _schema({"parameter": S, "change_mm": N}, ["parameter"])),
    ("knowledge", "This project's concepts / families / formulas matching the words (several queries at once).",
     _schema({"queries": LIST}, ["queries"])),
    ("set_structure", "What the drawing is.", _schema({"structure_type": S, "family": S, "views": LIST, "summary": S}, ["structure_type", "family"])),
    ("define_parts", "Create or replace parts (component tree nodes) made of regions and / or entities — all of them in one call.",
     _batch({"name": S, "type": S, "level": _enum("assembly", "component", "subcomponent"), "parent": S, "regions": LIST, "entities": LIST,
             "existing": B, "parametrize": B, "evidence": LIST, "description": S}, ["name", "type"])),
    ("remove", "Remove things, as many as you like in one call: parts, parameters, constraints (by description), your formulas (by line).",
     _schema({"parts": LIST, "parameters": LIST, "constraints": LIST, "formulas": LIST})),
    ("define_parameters", ("Create or replace design inputs, as many as you like in one call: each names a candidate value (c…) OR the "
     "two lines it spans (from_line, to_line). The engine fills in the values."),
     _batch({"name": S, "label": S, "part": S, "candidate": S, "from_line": S, "to_line": S,
             "importance": _enum("primary", "secondary", "detail"), "recommended": B, "evidence": LIST}, ["name", "part"])),
    ("set_levels", "Name the horizontal lines stated levels are drawn at (all of them in one call).",
     _batch({"line": S, "name": S, "role": _enum("site_input", "check_only", "derived")}, ["line", "name", "role"])),
    ("set_formulas", ("Set lines out from others: each an expression in mm over line ids and parameter names, e.g. "
     "{line: 'y18', expr: 'y10 + ClearHeight'}. An empty expression removes your formula (the engine's own comes back)."),
     _batch({"line": S, "expr": S}, ["line", "expr"])),
    ("set_relation", "A reported quantity worked out from parameters (OverallWidth, EarthCushion …); empty expr removes it.",
     _schema({"name": S, "label": S, "expr": S, "from_line": S, "to_line": S}, ["name", "expr"])),
    ("add_constraints", ("Things that must stay true under every change: distance (lines [a, b] stay `value` apart), fixed (lines "
     "never move), symmetric (lines [a, b, axis]), centred, equal (lines [a, b, c, d]: b-a = d-c), connected (parts [A, B]), slope "
     "(parts), parallel / perpendicular / collinear (entities)."),
     _batch({"type": _enum("distance", "fixed", "symmetric", "centred", "equal", "connected", "slope", "parallel", "perpendicular", "collinear"),
             "lines": LIST, "parts": LIST, "entities": LIST, "value": S, "description": S}, ["type", "description"])),
    ("state_behaviours", "What parts (or levels / relations) do when a parameter INCREASES; each is checked by measurement.",
     _batch({"parameter": S, "target": S, "behaviour": _enum("grows", "shrinks", "moves", "fixed", "keeps_thickness", "keeps_level",
                                                             "stays_centred", "stays_symmetric", "stays_connected", "keeps_slope"),
             "axis": _enum("x", "y", "both", "any")}, ["parameter", "target", "behaviour"])),
    ("ask_person", "A genuine ambiguity for the person to decide.", _schema({"question": S}, ["question"])),
    ("finish", "Done: the engine runs every check. If problems remain they are listed; call finish again to stop anyway.",
     _schema({"summary": S}, ["summary"])),
]
READ_TOOLS = {"inspect_regions", "inspect_lines", "find_values", "what_moves", "knowledge"}
# a batch tool applies the single edit to each of its items; each item gets its own verdict
BATCH = {"define_parts": "define_part", "define_parameters": "define_parameter", "set_formulas": "set_formula", "set_levels": "set_level",
         "add_constraints": "add_constraint", "state_behaviours": "state_behaviour"}


def tools():
    from google.genai import types

    return [types.Tool(function_declarations=[types.FunctionDeclaration(name=n, description=d, parameters_json_schema=p) for n, d, p in TOOL_SPECS])]


def _r(v: float) -> float:
    return round(float(v), 1)


# ── the workbench: the answer under construction, checked as it changes ─────────


class Workbench:
    def __init__(self, path: str, region=None, hold_existing: bool = False, start: dict | None = None, selection: dict | None = None,
                 drawing=None):
        self.path, self.region, self.hold, self.selection, self.drawing = path, region, hold_existing, selection, drawing
        self.answer = copy.deepcopy(start) if start else {
            "structure_type": "", "family": "other", "views": [], "summary": "", "components": [], "line_roles": [], "levels": [],
            "parameters": [], "datum_formulas": [], "relations": [], "behaviours": [], "constraints": [], "questions": []}
        for k in ("components", "line_roles", "levels", "parameters", "datum_formulas", "relations", "behaviours", "constraints", "questions"):
            self.answer.setdefault(k, [])
        self.finish_calls = 0
        self.validate()

    def validate(self, final: bool = False) -> None:
        """While the agent builds, every value stays editable (the AI's own "keep as drawn" recommendations are applied
        at the end, with the person's selection), so what it defines is what it can use."""
        an, _base, _region, _snap = prepare(self.path, None, self.region, drawing=self.drawing)
        selection = self.selection if (final or self.selection is not None) else {"hold": [], "exclude": [], "drop": []}
        self.prog, self.rep = apply(an, self.answer, hold_existing=self.hold, selection=selection)
        self.an = self.prog.analysis

    # ── reading ───────────────────────────────────────────────────────────────

    def _mm(self, v: float) -> float:
        return _r(v * self.an.drawing.units_mm)

    def _parts_on(self, d: str) -> list[str]:
        return sorted(n for n, p in (self.prog.intent.get("parts") or {}).items() if d in p.datums)[:6]

    def inspect_regions(self, ids: list[str]) -> dict:
        topo = of(self.an)
        regions = topo.by_id()
        dix = DatumIndex(self.an)
        texts = [it for it in self.an.drawing.items if it.dxftype in ("TEXT", "MTEXT") and (it.text or "").strip()]
        out = {}
        for rid in ids[:24]:
            r = regions.get(rid)
            if r is None:
                out[rid] = "no such region"
                continue
            edges = {}
            for side, axis, v in (("left", "x", r.bbox[0]), ("right", "x", r.bbox[2]), ("bottom", "y", r.bbox[1]), ("top", "y", r.bbox[3])):
                d = dix.at(axis, v)
                edges[side] = {"line": d, "formula": self.prog.formulas.get(d, "as drawn") if d else None}
            xs, ys = dix.of_ring(r.ring)
            inside = [f"{entity_id(t)}: {' '.join((t.text or '').split())[:60]}" for t in texts if topo.region_at(t.pts[0]) is r][:4]
            across = []
            lines = set(xs) | set(ys)
            for c in self.an.clusters.values():
                for gid in c.gaps:
                    g = self.an.gaps[gid]
                    if g.a in lines and g.b in lines and g.axis in ("x", "y"):
                        across.append({"candidate": c.id, "value": self._mm(g.value), "kind": c.kind.value, "between": [g.a, g.b],
                                       "occurrences": len(c.gaps), **({"named": c.name} if c.name in self.prog.params else {})})
                        break
            out[rid] = {"width": self._mm(r.bbox[2] - r.bbox[0]), "height": self._mm(r.bbox[3] - r.bbox[1]), "fill": r.pattern or "none",
                        "holes": len(r.holes), "inside_region": r.parent, "edges": edges, "x_lines": xs[:12], "y_lines": ys[:12],
                        "touches": [f"{k} ({_side(r, regions[k], self.an.drawing.tol)}, {self._mm(v)} mm)"
                                    for k, v in sorted(r.neighbours.items(), key=lambda kv: -kv[1])][:8],
                        "notes_inside": inside, "sizes_across": sorted(across, key=lambda a: -a["occurrences"])[:10],
                        "in_part": [c["name"] for c in self.answer["components"] if rid in c.get("regions", [])]}
        return out

    def inspect_lines(self, ids: list[str]) -> dict:
        reach = affects(self.prog)
        moved_by: dict[str, list[str]] = {}
        for p, a in reach.items():
            for d in a["datums"]:
                moved_by.setdefault(d, []).append(p)
        stated = {d: (w, v) for d, _i, w, v in self.an.stated_levels}
        out = {}
        for d in ids[:24]:
            if d not in self.an.datums:
                out[d] = "no such line"
                continue
            chain, x = [], d
            while x and x not in chain and len(chain) < 6:
                chain.append(x)
                f = self.prog.formulas.get(x, "")
                nxt = [n for n in sorted(names_in(f)) if n in self.an.datums and self.an.datums[n].axis == self.an.datums[d].axis and n != x]
                x = nxt[0] if nxt else None
            out[d] = {"axis": self.an.datums[d].axis, "at_mm": self._mm(self.an.datums[d].value), "formula": self.prog.formulas.get(d, "as drawn"),
                      "set_by": self.prog.origin.get(d, "geometry"), "chain": [f"{c} = {self.prog.formulas.get(c, 'as drawn')}" for c in chain],
                      "moved_by": sorted(moved_by.get(d, []))[:10], "parts": self._parts_on(d),
                      **({"stated_level": {"text": stated[d][0], "m": stated[d][1]}} if d in stated else {})}
        return out

    def find_values(self, value_mm: float | None = None, region: str | None = None, axis: str | None = None) -> list[dict]:
        lines = None
        if region:
            r = of(self.an).by_id().get(region)
            if r is not None:
                xs, ys = DatumIndex(self.an).of_ring(r.ring)
                lines = set(xs) | set(ys)
        u = self.an.drawing.units_mm
        rows = []
        for c in sorted(self.an.clusters.values(), key=lambda c: (-c.confidence, -len(c.gaps))):
            if c.kind in (GapKind.DIAMETER, GapKind.RING):
                continue
            if value_mm is not None and abs(c.value * u - value_mm) > max(0.5, 0.002 * value_mm):
                continue
            if axis and axis not in c.axes:
                continue
            pairs = [[self.an.gaps[g].a, self.an.gaps[g].b] for g in c.gaps if self.an.gaps[g].axis in ("x", "y")]
            if lines is not None and not any(a in lines and b in lines for a, b in pairs):
                continue
            rows.append({"candidate": c.id, "value": _r(c.value * u), "kind": c.kind.value, "axes": sorted(c.axes), "occurrences": len(c.gaps),
                         "between": pairs[:4], "confidence": round(c.confidence, 2), **({"named": c.name} if c.name in self.prog.params else {}),
                         **({"drawing_says": c.suggested} if c.suggested else {})})
            if len(rows) >= 20:
                break
        return rows

    def what_moves(self, parameter: str, change_mm: float | None = None) -> dict:
        p = self.prog.params.get(parameter)
        if p is None:
            return {"error": f"no parameter {parameter}: define it first"}
        dv = change_mm if change_mm else delta_of(self.prog, parameter)
        parts = self.prog.intent.get("parts") or resolve_parts(self.an, None)[0]
        thr = max(self.an.drawing.tol * 2, 0.5 / self.an.drawing.units_mm)
        b0 = _boxes(parts, _geometry(self.prog))
        b1 = _boxes(parts, _geometry(self.prog, {parameter: p.value + dv}))
        moves = {}
        for n in parts:
            if b0[n] is None or b1[n] is None:
                continue
            m = classify(b0[n], b1[n], thr)
            words = [f"{m[ax]} {ax} ({m['d' + ax][0] * self.an.drawing.units_mm:+.0f})" for ax in ("x", "y") if m[ax] != "fixed"]
            if not words:
                g0, g1 = _geometry(self.prog)[0], _geometry(self.prog, {parameter: p.value + dv})[0]
                inside = sum(1 for xd, yd in parts[n].nodes if abs(g1[xd] - g0[xd]) > thr or abs(g1[yd] - g0[yd]) > thr)
                if inside:
                    words = [f"reshapes inside ({inside} corners move)"]
            if words:
                moves[n] = ", ".join(words)
        r = regenerate_program(self.prog, {parameter: p.value + dv})
        return {"parameter": parameter, "from": p.value, "to": p.value + dv, "moves": moves,
                "fixed": sorted(set(parts) - set(moves))[:30], "drawing_valid": not r.issues, "problems": r.issues[:3]}

    def knowledge(self, queries: list[str] | None = None, query: str = "") -> list[str]:
        pack = json.loads(resources.files("dxf_autoparam.knowledge").joinpath("bridge.json").read_text())
        if isinstance(queries, str):
            queries = [queries]
        text = " ".join([*(queries or []), query])
        words = [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2]
        hits = []
        for c in pack["concepts"]:
            hay = " ".join([c["name"], c["label"], *c.get("aliases", [])]).lower()
            if any(w in hay for w in words):
                hits.append(f"{c['name']} ({c['unit'] or '-'}): {c['label']}")
        for f in pack["formulas"]:
            if any(w in f["output"].lower() or w in f["expression"].lower() for w in words):
                hits.append(f"formula {f['output']} = {f['expression']}")
        for f in pack["families"]:
            if any(w in (f["id"] + " " + f["label"]).lower() for w in words):
                hits.append(f"family {f['id']}: components {', '.join(x for x in f['components'] if x)}")
        return list(dict.fromkeys(hits))[:30] or ["nothing matches; use a clear PascalCase name"]

    # ── writing ───────────────────────────────────────────────────────────────

    def _upsert(self, key: str, field: str, value, row: dict) -> None:
        rows = self.answer[key]
        for i, r in enumerate(rows):
            if r.get(field) == value:
                rows[i] = row
                return
        rows.append(row)

    def write(self, name: str, a: dict) -> tuple[str, str]:
        """Apply one edit; returns (the item the validator will name in its findings, a note)."""
        A = self.answer
        if name == "set_structure":
            A.update({k: a.get(k, A.get(k)) for k in ("structure_type", "family", "views", "summary")})
            return "structure", ""
        if name == "define_part":
            pname, parent = pascal(a["name"]), pascal(a["parent"]) if a.get("parent") else None
            regions = list(dict.fromkeys(a.get("regions", [])))
            taken = []
            for c in A["components"]:  # every region belongs to one part: a newer claim takes it
                if c.get("name") != pname and set(c.get("regions", [])) & set(regions):
                    taken += [f"{r} from {c['name']}" for r in c["regions"] if r in regions]
                    c["regions"] = [r for r in c["regions"] if r not in regions]
            row = {"name": pname, "type": a.get("type", ""), "level": a.get("level", "component"), "parent": parent,
                   "regions": regions, "entities": a.get("entities", []), "existing": bool(a.get("existing")),
                   "parametrize": a.get("parametrize", True) is not False, "evidence": a.get("evidence", [])[:6],
                   "description": a.get("description", ""), "confidence": 0.9}
            self._upsert("components", "name", pname, row)
            notes = ([f"named {pname}"] if pname != a["name"] else []) + ([f"took {', '.join(taken[:6])}"] if taken else [])
            return pname, "; ".join(notes)
        if name == "remove":
            gone = {k: set(a.get(k) or []) for k in ("parts", "parameters", "constraints", "formulas")}
            gone["parts"] |= {pascal(n) for n in gone["parts"]}
            A["components"] = [c for c in A["components"] if c.get("name") not in gone["parts"]]
            A["parameters"] = [p for p in A["parameters"] if p.get("name") not in gone["parameters"]]
            A["constraints"] = [c for c in A["constraints"] if c.get("description") not in gone["constraints"]]
            A["datum_formulas"] = [f for f in A["datum_formulas"] if f.get("datum") not in gone["formulas"]]
            return "removed", f"removed {sum(len(v) for v in gone.values())} item(s)"
        if name == "define_parameter":
            a = {**a, "name": pascal(a["name"]), "part": pascal(a.get("part", "")) if a.get("part") else ""}
            value, note = self._measure(a)
            row = {"name": a["name"], "label": a.get("label") or a["name"], "component": a.get("part", ""), "kind": "length",
                   "candidate": a.get("candidate") or None, "from_datum": a.get("from_line") or None, "to_datum": a.get("to_line") or None,
                   "value": value, "importance": a.get("importance", "secondary"), "recommended": a.get("recommended", True) is not False,
                   "evidence": a.get("evidence", [])[:6], "confidence": 0.9}
            self._upsert("parameters", "name", a["name"], row)
            return a["name"], note
        if name == "set_level":
            lname = pascal(a["name"])
            self._upsert("levels", "datum", a["line"], {"datum": a["line"], "name": lname, "role": a["role"]})
            return lname, ""
        if name == "set_formula":
            A["datum_formulas"] = [f for f in A["datum_formulas"] if f.get("datum") != a["line"]]
            if (a.get("expr") or "").strip():
                A["datum_formulas"].append({"datum": a["line"], "expr": a["expr"].strip()})
            return a["line"], ""
        if name == "set_relation":
            A["relations"] = [r for r in A["relations"] if r.get("name") != a["name"]]
            if (a.get("expr") or "").strip():
                A["relations"].append({"name": a["name"], "label": a.get("label") or a["name"], "expr": a["expr"].strip(),
                                       "from_datum": a.get("from_line") or None, "to_datum": a.get("to_line") or None})
            return a["name"], ""
        if name == "add_constraint":
            self._upsert("constraints", "description", a["description"],
                         {"type": a["type"], "datums": a.get("lines", []), "components": a.get("parts", []), "entities": a.get("entities", []),
                          "value": a.get("value") or None, "description": a["description"], "confidence": 0.9})
            return a["description"], ""
        if name == "state_behaviour":
            axis = a.get("axis")
            effect = {"target": a["target"], "behaviour": a["behaviour"], "axis": None if axis in (None, "any") else axis}
            for b in A["behaviours"]:
                if b.get("parameter") == a["parameter"]:
                    b["effects"] = [e for e in b["effects"] if e.get("target") != a["target"]] + [effect]
                    break
            else:
                A["behaviours"].append({"parameter": a["parameter"], "effects": [effect]})
            return f"{a['parameter']}→{a['target']}", ""
        if name == "ask_person":
            A["questions"].append(a["question"])
            return "question", ""
        raise KeyError(name)

    def _measure(self, a: dict) -> tuple[float, str]:
        """The value a parameter names, from the drawing (the model never types a number)."""
        u = self.an.drawing.units_mm
        cid = a.get("candidate")
        if cid and cid in self.an.clusters:
            return _r(self.an.clusters[cid].value * u), f"{cid} measures {_r(self.an.clusters[cid].value * u)} mm"
        f, t = a.get("from_line"), a.get("to_line")
        if f in self.an.datums and t in self.an.datums:
            v = abs(self.an.datums[t].value - self.an.datums[f].value) * u
            return _r(v), f"{f}→{t} measures {_r(v)} mm"
        return 0.0, "name a candidate (c…) or two lines on the same axis"

    def verdict(self, item: str, kind: str = "") -> dict:
        errs = [f"{e['code']}: {e['message']}"[:200] for e in self.rep.errors() if e["item"] == item or (item and e["item"].startswith(item + "→"))]
        if kind == "define_parameters" and not errs and item not in self.prog.params:
            why = next((f.message for f in self.rep.findings if f.code == "V9" and f.item == item and "worked-out" in f.message), None)
            if why or any(r.name == item for r in self.prog.relations):
                # not an error: a size other inputs fix at both ends is a result; say so, and how to make it an input
                return {"ok": True, "worked_out": (why or f"{item} is worked out by the set-out")[:300]}
            errs = [f"not kept: {item} measures no two lines — name a candidate (c…) or from_line / to_line"]
        warns = [f"{f.code}: {f.message}"[:200] for f in self.rep.findings if f.severity == "warn" and f.item == item][:2]
        return {"ok": not errs, **({"rejected": errs[:3]} if errs else {}), **({"note": warns} if warns else {})}

    def status(self) -> dict:
        I = self.prog.intent
        named = [n for n, p in self.prog.params.items() if p.source == "ai"]
        errs = self.rep.errors()
        return {"parts": len(self.answer["components"]), "regions_without_part": len(I.get("uncovered_regions", [])),
                "parameters": len(named), "open_problems": len(errs),
                "first_problems": [f"{e['code']} {e['item']}: {e['message']}"[:180] for e in errs[:3]]}


def _side(r, other, tol) -> str:
    a, b = r.bbox, other.bbox
    if abs(b[1] - a[3]) <= 2 * tol:
        return "above"
    if abs(b[3] - a[1]) <= 2 * tol:
        return "below"
    if abs(b[0] - a[2]) <= 2 * tol:
        return "right"
    if abs(b[2] - a[0]) <= 2 * tol:
        return "left"
    return "inside" if r.parent == other.id or other.parent == r.id else "beside"


# ── the overview the agent starts from (cached with the pictures) ────────────────


def overview(an, base) -> dict:
    """Compact on purpose: rows, not objects; details come from the inspect tools. It carries what every edit needs —
    each region's edge lines and every line's current formula — so the agent edits instead of reading for many turns."""
    topo = of(an)
    dix = DatumIndex(an)
    u = an.drawing.units_mm
    dr = an.drawing
    texts = [it for it in dr.items if it.dxftype in ("TEXT", "MTEXT", "ATTRIB") and (it.text or "").strip()]
    in_region: dict[str, list[str]] = {}
    text_rows = []
    for t in texts:
        r = topo.region_at(t.pts[0])
        s = " ".join((t.text or "").split())[:70]
        if r is not None:
            in_region.setdefault(r.id, []).append(s[:30])
        text_rows.append([entity_id(t), s, r.id if r else None])
    regions = []
    for r in topo.regions:
        edges = "/".join(str(dix.at(ax, v) or "?") for ax, v in (("x", r.bbox[0]), ("x", r.bbox[2]), ("y", r.bbox[1]), ("y", r.bbox[3])))
        regions.append([r.id, _r((r.bbox[2] - r.bbox[0]) * u), _r((r.bbox[3] - r.bbox[1]) * u), edges, r.pattern or "", r.parent or "",
                        " ".join(f"{k}:{_side(r, topo.by_id()[k], dr.tol)[0]}" for k in sorted(r.neighbours, key=lambda k: -r.neighbours[k])[:6]),
                        "; ".join(in_region.get(r.id, [])[:2])])
    dims = []
    for it in dr.items:
        if it.dxftype == "DIMENSION":
            cand = next((g.cluster for g in an.gaps.values() if it.index in g.dims and g.cluster), None)
            dims.append([entity_id(it), _r((it.extra.get("measurement") or 0) * u), (it.text or "").strip() or "<>", cand])
    cands = []
    for c in sorted(an.clusters.values(), key=lambda c: (-c.confidence, -len(c.gaps)))[:90]:
        g = an.gaps[c.gaps[0]]
        cands.append([c.id, c.kind.value, _r(c.value * u), "".join(sorted(c.axes)), len(c.gaps), f"{g.a}-{g.b}", c.suggested or ""])
    return {
        "drawing": {"units": "mm (levels m)", "extent_mm": [_r(v * u) for v in dr.extent], "entities": len(dr.items),
                    "structural": sum(1 for i in dr.items if i.role == Role.STRUCTURAL), "symmetry_axes": {k: v for k, v in an.global_axis.items() if v}},
        "regions [id, width, height, edge lines left/right/bottom/top, fill, inside, touches id:side(a/b/l/r), notes inside]": regions,
        "lines [id, at mm, set out as]": [[d.id, _r(d.value * u), base.formulas.get(d.id, "as drawn")]
                                          for d in sorted(an.datums.values(), key=lambda d: (d.axis, d.value))],
        "open_lines (bound no region)": [entity_id(dr.items[i]) for i in topo.open_items][:40],
        "texts [id, text, region]": text_rows[:160],
        "dimensions [id, value, text, candidate]": dims[:120],
        "stated_levels [line, words, m]": [[d, w, v] for d, _i, w, v in an.stated_levels],
        "candidates [id, kind, value, axes, occurrences, first pair, drawing says]": cands,
        "concept names (use for parts and parameters)": _concept_names(),
        "structure families [id, label, parts]": _families(),
    }


def _families() -> list:
    pack = json.loads(resources.files("dxf_autoparam.knowledge").joinpath("bridge.json").read_text())
    return [[f["id"], f["label"], [x for x in f["components"] if x]] for f in pack["families"]]


def pascal(name: str) -> str:
    """'wing_wall' / 'wing wall' / 'wingWall' → 'WingWall' (names a person reads are PascalCase)."""
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\b|[0-9_ -])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", name or "")
    out = "".join(w[:1].upper() + w[1:] for w in words)
    return out if out[:1].isalpha() else "P" + out


def _concept_names() -> str:
    pack = json.loads(resources.files("dxf_autoparam.knowledge").joinpath("bridge.json").read_text())
    return ", ".join(sorted({c["name"] for c in pack["concepts"]}))


# ── the loop ───────────────────────────────────────────────────────────────────


def _trim(history: list, keep: int = 8) -> None:
    """Tool results older than the last `keep` steps are cut to their verdict: every step re-sends the conversation,
    and a long inspect result from ten steps ago is paid for again each time. The model can always ask again."""
    from google.genai import types

    answers = [k for k, c in enumerate(history) if c.role == "user" and c.parts and getattr(c.parts[0], "function_response", None)]
    for k in answers[:-keep]:
        parts = []
        for p in history[k].parts:
            fr = p.function_response
            res = (fr.response or {}).get("result")
            if len(json.dumps(res, default=str)) <= 400:
                parts.append(p)
                continue
            short = {"trimmed": "older result; call the tool again if you need it"}
            if isinstance(res, dict):
                short.update({x: res[x] for x in ("ok", "rejected", "done") if x in res})
            parts.append(types.Part.from_function_response(name=fr.name, response={"result": short}))
        history[k] = types.Content(role="user", parts=parts)


def _args(call) -> dict:
    a = getattr(call, "args", None) or {}
    return dict(a) if not isinstance(a, dict) else a


def _short(a: dict) -> str:
    s = json.dumps(a, separators=(",", ":"))
    return s if len(s) <= 140 else s[:137] + "…"


def agent_parametrize(path: str, region=None, instructions: str = "", start: dict | None = None, request: str = "",
                      hold_existing: bool = False, selection: dict | None = None, gem: Gemini | None = None, on_event=None,
                      stop=None, log=print, max_steps: int | None = None, max_output_tokens: int | None = None, drawing=None):
    """Run the agent. `start`: an answer to continue from (a revision); `request`: what the person asks of it.
    `drawing`: one view or unit of a sheet (already read and cut out) instead of the file's own region."""
    from google.genai import types

    t0 = time.perf_counter()
    emit = on_event or (lambda e: None)
    max_steps = max_steps or int(os.environ.get("VERTEX_AGENT_MAX_STEPS", "30"))
    budget = max_output_tokens or int(os.environ.get("VERTEX_AGENT_MAX_OUTPUT_TOKENS", "150000"))
    an, base, region, _snap = prepare(path, None, region, drawing=drawing)
    images = images_for(an, base, region)
    ov = overview(an, base)
    src = hashlib.sha256(Path(an.drawing.path).read_bytes()).hexdigest()
    image_keys = [f"faithful:{src}:{region}", hashlib.sha256(images[1]).hexdigest(), hashlib.sha256(images[2]).hexdigest()]
    ov_text = "OVERVIEW:\n" + json.dumps(ov, separators=(",", ":"))
    prefix_parts = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images] + [types.Part.from_text(text=ov_text)]
    prefix_key = hashlib.sha256(("agent|" + AGENT_SYSTEM + "|".join(image_keys) + ov_text).encode()).hexdigest()[:24]
    bench = Workbench(path, region, hold_existing, start, selection, drawing=drawing)
    task = ("Parametrize this drawing with the tools, following the playbook." if not request else
            "You parametrized this drawing before; the current state is loaded in the tools (inspect_regions shows the parts, "
            "find_values the named values). The person asks for a change — make it with small edits, keep everything else.\n"
            f"THE PERSON ASKS: {request.strip()}")
    if instructions.strip():
        task += f"\n\nTHE PERSON'S INSTRUCTIONS:\n{instructions.strip()}"
    if start:
        task += "\n\nCURRENT STATE: " + json.dumps(bench.status())
    history = [types.Content(role="user", parts=[types.Part.from_text(text=task)])]
    own = gem is None
    gem = gem or Gemini()
    plan_thinking = gem.cfg.thinking
    step_thinking = os.environ.get("VERTEX_AGENT_STEP_THINKING") or plan_thinking  # every step thinks at the configured level unless the person lowers it
    usages: list[dict] = []
    done, steps, spent, reads_only = False, 0, 0, 0
    log(f"agent on {gem.cfg.model}: plan @{plan_thinking}, steps @{step_thinking}, ≤{max_steps} steps, ≤{budget} output tokens")
    try:
        while not done and steps < max_steps:
            if stop and stop():
                raise GeminiStopped("stopped by the person")
            steps += 1
            content, usage = gem.step(AGENT_SYSTEM, tools(), prefix_parts, prefix_key, history, f"step {steps}",
                                      plan_thinking if steps == 1 else step_thinking, max_out=32768 if steps == 1 else 16384, stop=stop, on_event=emit)
            usage["thoughts"] = [p.text for p in content.parts or [] if getattr(p, "thought", False) and p.text]
            usages.append(usage)
            if not usage.get("cached"):
                spent += usage.get("output_tokens", 0) + usage.get("thinking_tokens", 0)
            history.append(content)
            calls = [p.function_call for p in content.parts or [] if getattr(p, "function_call", None)]
            if not calls:
                history.append(types.Content(role="user", parts=[types.Part.from_text(text="Use the tools (one small edit at a time); call finish when done.")]))
                continue
            results, wrote, pending = [], False, []
            for call in calls:
                a = _args(call)
                try:
                    if call.name in READ_TOOLS and reads_only >= 6:
                        # six turns of looking and nothing defined: looking is refused until an edit is made
                        res = {"refused": "you have looked for six turns without an edit: make your edits now (define_parts / "
                                          "define_parameters / set_formulas, in batches); looking is open again after an edit"}
                        emit({"kind": "tool", "name": call.name, "args": _short(a), "ok": False, "why": "refused: edit first"})
                    elif call.name in READ_TOOLS:
                        res = getattr(bench, call.name)(**a)
                        emit({"kind": "tool", "name": call.name, "args": _short(a), "ok": True})
                    elif call.name == "finish":
                        bench.validate()
                        bench.finish_calls += 1
                        st = bench.status()
                        if st["open_problems"] and bench.finish_calls < 2:
                            res = {"done": False, **st, "hint": "fix these, or call finish again to stop with what is valid"}
                        else:
                            res, done = {"done": True, **st}, True
                        emit({"kind": "tool", "name": "finish", "args": _short(a), "ok": done})
                    elif call.name in BATCH:
                        done_items = [(*bench.write(BATCH[call.name], it), it) for it in (a.get("items") or [])]
                        pending.append((len(results), done_items, call.name))
                        res = None
                        wrote = True
                    else:
                        item, note = bench.write(call.name, a)
                        pending.append((len(results), [(item, note, a)], call.name))
                        res = None
                        wrote = True
                except (KeyError, TypeError, ValueError) as exc:  # a malformed call: the model reads why and corrects it
                    res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                    emit({"kind": "tool", "name": call.name, "args": _short(a), "ok": False, "why": res["error"]})
                results.append([call, res])
            if wrote:
                bench.validate()  # one check for the whole batch of edits; each edit reads its own verdict
                for k, items, name in pending:
                    verdicts = []
                    for item, note, a in items:
                        v = {"item": item, **bench.verdict(item, name)}
                        if note:
                            v["engine"] = note
                        if name == "define_parameters" and v["ok"]:
                            v["moves"] = bench.prog.intent.get("impact", {}).get(item, {})
                        verdicts.append(v)
                        emit({"kind": "tool", "name": BATCH.get(name, name), "args": _short(a), "ok": v["ok"], "why": "; ".join(v.get("rejected", []))[:200]})
                    results[k][1] = verdicts if name in BATCH else verdicts[0]
                st = {**bench.status(), "steps_left": max_steps - steps}
                emit({"kind": "status", **st})
                results[-1][1] = {"result": results[-1][1], "status": st}
                reads_only = 0
            else:
                reads_only += 1
                if reads_only >= 4 and not done:  # looking can go on for ever; the engine checks edits, so edit
                    nudge = ("you have read enough to start: define the parts now (define_parts, all in one call), then the parameters"
                             if not bench.answer["components"] else "make the edits now (define_parameters / set_formulas), in batches")
                    results[-1][1] = {"result": results[-1][1], "nudge": nudge, "steps_left": max_steps - steps}
            history.append(types.Content(role="user", parts=[types.Part.from_function_response(name=c.name, response={"result": r}) for c, r in results]))
            _trim(history, keep=8)
            if spent >= budget:
                emit({"kind": "note", "text": f"output budget reached ({spent} tokens): stopping with what is valid"})
                break
        if not done:
            emit({"kind": "note", "text": f"stopped after {steps} steps with what is valid"})
    finally:
        if own:
            gem.close()
    bench.validate(final=True)
    info = {"answer": bench.answer, "path": path, "usage": usages, "seconds": round(time.perf_counter() - t0, 1),
            "region": region, "steps": steps, "agent": True,
            "tokens_in": sum(u.get("input_tokens", 0) for u in usages if not u.get("cached")),
            "tokens_out": sum(u.get("output_tokens", 0) + u.get("thinking_tokens", 0) for u in usages if not u.get("cached")),
            "tokens_cached": sum(u.get("vertex_cached_tokens", 0) for u in usages if not u.get("cached"))}
    emit({"kind": "round", "round": steps, "accepted": bench.rep.accepted, "rejected": bench.rep.rejected,
          "errors": [f"{e['code']} {e['item']}: {e['message']}"[:220] for e in bench.rep.errors()][:8]})
    return bench.prog, bench.rep, info

