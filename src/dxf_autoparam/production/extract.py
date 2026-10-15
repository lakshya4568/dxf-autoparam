"""Generating the production knowledge manifests — what each bridge family's production code knows, measured by running it.

For every family the registry dispatches, the manifest (`knowledge/production/<family>.json`) records, with provenance:

  parameters   every model field: its default, kind and unit (authored overlay, else inferred from formulas, else unknown), whether the
               rule engine reads it, the code's own fallback when it is absent, which outputs and which views it affects
  outputs      every number compute() returns: its value at the defaults, the inputs it depends on and whether it is affine in each —
               MEASURED by perturbing each input and running the production code — and, where the source is plain arithmetic, its formula,
               verified by evaluating it on sampled models and comparing with what the production code computes for the same models
  views        the view list (and the configuration that changes it), whether each view renders headless, which inputs it reads and which
               change its drawing (perturbed and re-rendered)
  validation   whether the registered engine validates, and what it says on the defaults
  operations   what can be changed (a value, a count, a feature toggle) and what each means for an existing drawing
  findings     what the code itself shows: disabled validation, code-only fallbacks, stale duplicate copies, divergences between views

Nothing is copied from the TypeScript into Python as logic: the formulas are data (expressions of the safe language) kept only with the
verification that ties them to the code, and evaluation always goes back to the production code through the bridge.

    dxf-autoparam production extract [--family railway_rcc_box]       # needs the checkout and a built bundle
"""

from __future__ import annotations

import ast
import copy
import json
import math
import random
import re
import time
from importlib import resources
from pathlib import Path

from ..program import ExprError, evaluate
from . import formulas as F
from . import source as S
from .bridge import BridgeError, RuleBridge
from .build import digest, read_info

FORMAT = "dxf-autoparam/production-knowledge-1"
EXTRACTOR_VERSION = 1
SAMPLES = 16
RENDER_BUDGET_S = 150.0


def knowledge_dir() -> Path:
    return Path(str(resources.files("dxf_autoparam.knowledge").joinpath("production")))


def overlay(family: str) -> dict:
    p = knowledge_dir() / "overlay" / f"{family}.json"
    return json.loads(p.read_text()) if p.is_file() else {}


def flatten(obj, prefix: str = "") -> dict:
    """Leaves of a JSON object by dotted path (list items by index)."""
    out: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}.{i}" if prefix else str(i)))
    else:
        out[prefix] = obj
    return out


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _close(a: float, b: float, rel: float = 1e-9) -> bool:
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


# ── the measurements ─────────────────────────────────────────────────────────────


class _Run:
    def __init__(self, br: RuleBridge, family: str):
        self.br, self.family = br, family

    def compute_many(self, models: list[dict]) -> list[dict | None]:
        out: list[dict | None] = []
        for i in range(0, len(models), 200):
            rows = self.br.request("compute_many", family=self.family, models=models[i:i + 200], timeout_s=120)["derived"]
            out += [flatten(r["derived"]) if r["ok"] else None for r in rows]
        return out


def _step(v: float, count: bool) -> tuple[float, float]:
    if count:
        return v + 1, max(1, v - 1) if v - 1 >= 1 else v + 2
    h = 0.1 * abs(v) + 0.0137
    return v + h, v - 0.5 * h


def sensitivity(run: _Run, base: dict, params: dict[str, float], counts: set[str], outputs: list[str]) -> dict[str, dict[str, dict]]:
    """output → input → {"slope": ∂output/∂input at the defaults, "affine": the slope is the same either side and at a second base point}.
    Only pairs that move are kept: what an output does NOT depend on is as much knowledge as what it does."""
    second = copy.deepcopy(base)
    for p, v in params.items():
        if p not in counts:
            F.set_path(second, p, v * 1.13 + 0.011)
    models, index = [base, second], []
    for p, v in params.items():
        for b, bm in (("A", base), ("B", second)):
            v0 = F.get_path(bm, p)
            v0 = v if not is_num(v0) else v0
            up, dn = _step(float(v0), p in counts)
            for tag, val in (("up", up), ("dn", dn)):
                m = copy.deepcopy(bm)
                F.set_path(m, p, val)
                models.append(m)
                index.append((p, b, tag, val - v0))
    got = run.compute_many(models)
    o_a, o_b = got[0], got[1]
    res: dict[str, dict[str, dict]] = {o: {} for o in outputs}
    by = {}
    for (p, b, tag, h), d in zip(index, got[2:], strict=True):
        by[(p, b, tag)] = (h, d)
    for p in params:
        for o in outputs:
            slopes = {}
            moved = False
            for b, ob in (("A", o_a), ("B", o_b)):
                for tag in ("up", "dn"):
                    h, d = by[(p, b, tag)]
                    if d is None or ob is None or not is_num(d.get(o)) or not is_num(ob.get(o)):
                        continue
                    delta = d[o] - ob[o]
                    if abs(delta) > 1e-12 * max(1.0, abs(ob[o])):
                        moved = True
                    slopes[(b, tag)] = delta / h
            if not moved:
                continue
            s = list(slopes.values())
            affine = len(s) == 4 and all(_close(x, s[0], 1e-6) for x in s)
            a_up = slopes.get(("A", "up"))
            res[o][p] = {"slope": round(a_up, 9) if a_up is not None else None, "affine": affine}
    return res


def _sample_value(rng: random.Random, base, count: bool) -> float:
    if count:
        return float(rng.randint(1, 6))
    b = float(base) if is_num(base) else 1.0
    return b * rng.uniform(0.5, 1.7) + rng.uniform(0.001, 0.05)


def verify_formulas(run: _Run, fx: F.Extracted, defaults: dict, derived0: dict, counts: set[str], seed: int = 11) -> dict[str, dict]:
    """Each extracted output formula, evaluated in Python on sampled production models and compared with the production code's own result for
    the same models. The verdict is the code's: `verified_by_execution` only when every sample agrees."""
    rng = random.Random(seed)
    out: dict[str, dict] = {}
    cases = []
    for o, d in fx.outputs.items():
        if o not in derived0 or not is_num(derived0[o]):
            continue
        try:
            expr = F.expand(fx, d["expr"])
        except ExprError as exc:
            out[o] = {"status": "not_evaluable", "why": str(exc)}
            continue
        syms = F.input_symbols(fx, expr)
        rec = {"expr": expr, "line": d["line"], "inputs": {s: i.as_json() for s, i in syms.items()},
               "display": (f"{o} = {fx.locals[d['local']][0]}" if d.get("local") in fx.locals else f"{o} = {d['expr']}")}
        if d.get("passthrough"):
            rec["passthrough"] = True
        models = []
        for _k in range(SAMPLES):
            m = copy.deepcopy(defaults)
            for i in syms.values():
                path = next((p for p in i.chain if F.get_path(defaults, p) is not None), i.chain[0])
                base = F.resolve(i, defaults)
                F.set_path(m, path, _sample_value(rng, base, path in counts))
            models.append(m)
        cases.append((o, rec, syms, [defaults] + models))
    flat_models = [m for _o, _r, _s, ms in cases for m in ms]
    results = run.compute_many(flat_models) if flat_models else []
    k = 0
    for o, rec, syms, ms in cases:
        worst, bad = 0.0, None
        n_ok = 0
        for m in ms:
            node = results[k]
            k += 1
            if node is None or not is_num(node.get(o)):
                bad = bad or {"why": "the production code did not return a number for this sample"}
                continue
            scope = {}
            for s, i in syms.items():
                v = F.resolve(i, m)
                if not is_num(v):
                    scope = None
                    break
                scope[s] = float(v)
            if scope is None:
                bad = bad or {"why": "an input resolves to a non-number"}
                continue
            try:
                py = evaluate(rec["expr"], scope)
            except ExprError as exc:
                bad = bad or {"why": str(exc)}
                continue
            err = abs(py - node[o])
            worst = max(worst, err)
            if _close(py, node[o]):
                n_ok += 1
            elif bad is None:
                bad = {"python": py, "production": node[o]}
        rec["samples"] = len(ms)
        rec["max_abs_error"] = worst
        if not syms:
            rec["status"] = "constant_verified" if n_ok == len(ms) else "differs"
        else:
            rec["status"] = "verified_by_execution" if n_ok == len(ms) else "differs"
        if bad and rec["status"] == "differs":
            rec["counterexample"] = bad
        out[o] = rec
    return out


# ── units, by the formulas that add them ─────────────────────────────────────────


def _terms(node) -> list:
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        return _terms(node.left) + _terms(node.right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("max", "min"):
        return [t for a in node.args for t in _terms(a)]
    if isinstance(node, ast.UnaryOp):
        return _terms(node.operand)
    return [node]


def _term_symbols(node, count_syms: set[str]) -> list[str]:
    """The symbol whose unit a term carries: a name, a name times a number, or a name times a count."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
        l, r = node.left, node.right
        if isinstance(r, ast.Constant) or (isinstance(r, ast.Name) and r.id in count_syms) or (isinstance(r, ast.BinOp) and _is_count_expr(r, count_syms)):
            return _term_symbols(l, count_syms)
        if isinstance(node.op, ast.Mult) and (isinstance(l, ast.Constant) or (isinstance(l, ast.Name) and l.id in count_syms)):
            return _term_symbols(r, count_syms)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        return [s for t in _terms(node) for s in _term_symbols(t, count_syms)]
    return []


def _is_count_expr(node, count_syms: set[str]) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return node.id in count_syms
    if isinstance(node, ast.BinOp):
        return _is_count_expr(node.left, count_syms) and _is_count_expr(node.right, count_syms)
    return False


def infer_units(params: dict[str, dict], outputs: dict[str, dict], verified: dict[str, dict]) -> None:
    """Terms added together share a unit: from what is known (authored), the rest of each verified formula is inferred, to a fixed point.
    An inferred unit says so (`unit_status: inferred_dimensional`, with the formula it came from)."""
    for _ in range(6):
        changed = False
        for o, rec in verified.items():
            if rec.get("status") != "verified_by_execution":
                continue
            sym_path = {s: (next(iter(i["chain"])) if i["chain"] else None) for s, i in rec["inputs"].items()}
            count_syms = {s for s, p in sym_path.items() if p and params.get(p, {}).get("kind") == "count"}
            terms = _terms(ast.parse(rec["expr"], mode="eval").body)
            groups = [_term_symbols(t, count_syms) for t in terms]
            if any(not g for g in groups):
                continue
            syms = [s for g in groups for s in g]
            known = {params[sym_path[s]]["unit"] for s in syms if sym_path.get(s) in params and params[sym_path[s]].get("unit") not in (None, "unknown")}
            if o in outputs and outputs[o].get("unit") not in (None, "unknown"):
                known.add(outputs[o]["unit"])
            if len(known) != 1:
                continue
            u = known.pop()
            for s in syms:
                p = sym_path.get(s)
                if p in params and params[p].get("unit") in (None, "unknown"):
                    params[p].update(unit=u, unit_status="inferred_dimensional", unit_basis=f"added in {o} (line {rec['line']})")
                    changed = True
            if o in outputs and outputs[o].get("unit") in (None, "unknown"):
                outputs[o].update(unit=u, unit_status="inferred_dimensional", unit_basis=f"sum of terms in {u} (line {rec['line']})")
                changed = True
        if not changed:
            break


# ── views ────────────────────────────────────────────────────────────────────────


def view_variants(br: RuleBridge, family: str, defaults: dict) -> dict:
    base = br.request("views", family=family, model=defaults)
    if not base["available"]:
        return {"available": False, "reason": base.get("reason")}
    seen: dict[str, dict] = {}
    for v in base["views"]:
        seen[v["mode"]] = {"mode": v["mode"], "labels": [v["label"]], "conditions": ["always"]}
    variants = []
    flat = flatten(defaults)
    for path in base.get("reads", []) + base.get("missing", []):
        cur = flat.get(path)
        if not (isinstance(cur, bool) or cur is None):
            continue
        for val in (True, False):
            if cur is val:
                continue
            m = copy.deepcopy(defaults)
            try:
                F.set_path(m, path, val)
            except KeyError:
                continue
            r = br.request("views", family=family, model=m)
            variants.append(({"path": path, "value": val}, r["views"]))
    if base.get("reads_project_line_type"):
        for lt in ("GREENFIELD", "BROWNFIELD"):
            r = br.request("views", family=family, model=defaults, line_type=lt)
            variants.append(({"project_line_type": lt}, r["views"]))
    base_modes = {v["mode"] for v in base["views"]}
    for cond, views in variants:
        modes = {v["mode"] for v in views}
        for v in views:
            row = seen.setdefault(v["mode"], {"mode": v["mode"], "labels": [], "conditions": []})
            if v["label"] not in row["labels"]:
                row["labels"].append(v["label"])
            if v["mode"] not in base_modes:
                row["conditions"].append({"when": cond, "added": True})
        for m in base_modes - modes:
            seen[m]["conditions"].append({"when": cond, "removed": True})
    return {"available": True, "decided_by": sorted(set(base.get("reads", []) + base.get("missing", []))), "views": list(seen.values())}


def view_effects(br: RuleBridge, family: str, defaults: dict, modes: list[str], params: dict[str, float], counts: set[str], budget_s: float) -> dict:
    """Each view rendered headless by the production renderer: whether it draws, whether drawing is deterministic, which inputs it reads and
    which inputs CHANGE what it draws (each perturbed and the view drawn again at the same scale)."""
    out: dict[str, dict] = {}
    t0 = time.monotonic()
    for mode in modes:
        try:
            r0 = br.request("render", family=family, model=defaults, mode=mode, timeout_s=60)
        except BridgeError as exc:
            out[mode] = {"renders": False, "error": str(exc)[:200]}
            continue
        if not r0.get("available"):
            out[mode] = {"renders": False, "error": r0.get("reason")}
            continue
        if not r0.get("ok"):
            out[mode] = {"renders": False, "error": r0.get("error"), "reads": r0.get("reads", [])}
            continue
        r1 = br.request("render", family=family, model=defaults, mode=mode, state=r0["state"], timeout_s=60)
        row = {"renders": True, "draws": r0["draws"], "deterministic": r1.get("signature") == r0["signature"], "reads": r0["reads"],
               "code_fallbacks": r0.get("missing", [])[:80]}
        if row["deterministic"]:
            affected, tried = [], 0
            for p in sorted(set(r0["reads"]) & set(params)):
                if time.monotonic() - t0 > budget_s:
                    row["affected_by_truncated"] = True
                    break
                m = copy.deepcopy(defaults)
                up, _dn = _step(float(params[p]), p in counts)
                try:
                    F.set_path(m, p, up)
                except KeyError:
                    continue
                rp = br.request("render", family=family, model=m, mode=mode, state=r0["state"], timeout_s=60)
                tried += 1
                if rp.get("ok") and rp.get("signature") != r0["signature"]:
                    affected.append(p)
                elif not rp.get("ok"):
                    row.setdefault("fails_when_changed", []).append(p)
            row["affected_by"] = affected
            row["inputs_tried"] = tried
        out[mode] = row
    return out


# ── duplicates and evidence ──────────────────────────────────────────────────────


class _Imports:
    """Which project files import which (relative imports), built once."""

    def __init__(self, src: S.Source):
        self.src = src
        self.by_target: dict[str, list[str]] = {}
        app = src.root / "src" / "app"
        for f in app.rglob("*.ts"):
            if "node_modules" in f.parts:
                continue
            text = f.read_text(errors="replace")
            for a, b in S._ANY_IMPORT.findall(text):
                q = S._resolve(f, a or b)
                if q is not None:
                    self.by_target.setdefault(src.rel(q), []).append(src.rel(f))


def duplicates(src: S.Source, imports: _Imports, authoritative: str, symbol: str) -> list[dict]:
    """Other files in the bridges feature that define the same engine symbol — the stale copies — with whether they are identical and who
    still imports them."""
    pat = re.compile(rf"(?:class|function)\s+{re.escape(symbol)}\b")
    out = []
    auth = src.root / authoritative
    for f in src.bridges.rglob("*.ts"):
        r = src.rel(f)
        if r == authoritative:
            continue
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        if pat.search(text):
            out.append({"path": r, "identical": S.sha256(f) == S.sha256(auth), "lines": text.count("\n") + 1,
                        "authoritative_lines": auth.read_text(errors="replace").count("\n") + 1, "imported_by": sorted(imports.by_target.get(r, []))[:12]})
    return out


def check_evidence(src: S.Source, cites: list[str], words: set[str]) -> str:
    """A citation 'file.ts:LINE …' holds when the file is in the bridges / projects features and that line mentions one of `words`."""
    ok_any = False
    for c in cites:
        m = re.match(r"([\w.-]+\.ts):(\d+)", c)
        if not m:
            return "unparsed"
        name, ln = m.group(1), int(m.group(2))
        files = [f for f in (src.root / "src" / "app").rglob(name) if "node_modules" not in f.parts]
        if not files:
            return f"missing_file:{name}"
        hit = False
        for f in files:
            lines = f.read_text(errors="replace").split("\n")
            if 0 < ln <= len(lines) and (not words or any(w and w in lines[ln - 1] for w in words)):
                hit = True
        if not hit:
            return f"line_mismatch:{c}"
        ok_any = True
    return "checked" if ok_any else "none"


def _text_alternatives(run: _Run, defaults: dict, derived0: dict, params: dict[str, dict], source_text: str) -> dict[str, list]:
    lits = list(dict.fromkeys(a or b for a, b in re.findall(r"'([A-Za-z_][\w -]{0,30})'|\"([A-Za-z_][\w -]{0,30})\"", source_text)))[:30]
    cand = [p for p, r in params.items() if r.get("read_by_compute") and r["type"] in ("str", "bool", "unknown") and not is_num(r.get("default"))][:20]
    models, index = [], []
    for p in cand:
        # a flag is flipped; a text field (or one the defaults lack) is tried with the source's own string literals — never with a truth value
        # it does not hold (a missing length set to `true` is not a configuration)
        vals = [not params[p]["default"]] if params[p]["type"] == "bool" else []
        vals += lits + ([""] if params[p]["type"] == "str" else []) if params[p]["type"] in ("str", "unknown") else []
        for v in vals:
            if v == params[p].get("default"):
                continue
            m = copy.deepcopy(defaults)
            try:
                F.set_path(m, p, v)
            except KeyError:
                continue
            models.append(m)
            index.append((p, v))
    out: dict[str, list] = {}
    for (p, v), d in zip(index, run.compute_many(models) if models else [], strict=True):
        if d is not None and any(is_num(d.get(o)) and is_num(derived0.get(o)) and not _close(d[o], derived0[o]) for o in derived0):
            out.setdefault(p, []).append(v)
    return out


# ── one family ───────────────────────────────────────────────────────────────────


def extract_family(br: RuleBridge, src: S.Source, key: str, row: dict, hello_row: dict, imports: _Imports | None = None,
                   render: bool = True, log=print) -> dict:
    ov = overlay(key)
    fp = S.fingerprint(src, row)
    man: dict = {"format": FORMAT, "extractor_version": EXTRACTOR_VERSION, "knowledge_id": f"aagento-bridge:{key}", "family": key,
                 "title": hello_row.get("title"),
                 "source": {"repository": "aagento-bridge", **S.revision(src), "registry": src.rel(src.registry), "modules": row,
                            "sources": fp, "sources_digest": digest(fp)},
                 "capabilities": {k: hello_row.get(k) for k in ("has_compute", "has_validate", "has_levels", "has_views", "has_renderer", "has_defaults")},
                 "overlay": {"present": bool(ov), "status": ov.get("status"), "basis": ov.get("basis")}}
    if not hello_row.get("has_compute"):
        man["unsupported"] = [{"what": "rule engine", "why": "the registry entry has no rule engine with compute(): the family is drawn by a generic template "
                               "renderer from data the app loads at run time; there is no production model, formula or rule to retrieve"}]
        man["parameters"], man["outputs"], man["views"], man["operations"], man["findings"] = [], [], {"available": False}, [], []
        return man
    defaults = br.request("defaults", family=key)
    derived0_raw = br.request("compute", family=key, model=defaults)["derived"]
    # an engine that hands its input model back inside the result (`model: m`) is not computing those numbers: they are not outputs
    echoed = sorted(k for k, v in derived0_raw.items() if isinstance(v, dict) and v == defaults)
    derived0 = {k: v for k, v in flatten(derived0_raw).items() if k.split(".", 1)[0] not in echoed}
    tr = br.request("trace", family=key, model=defaults)
    flat_d = flatten(defaults)
    # the engine's source: the symbol and module the registry binds
    eng = row.get("ruleEngine") or {}
    sym, path = eng.get("symbol"), eng.get("path")
    if eng.get("inline_object"):
        c = eng["inline_object"].get("compute") or {}
        sym, path = c.get("symbol"), c.get("path")
    fx = None
    if sym and path:
        found = F.engine_source((src.root / path).read_text(errors="replace"), sym, kind="auto")
        if found:
            fx = F.extract(found[0], found[1], found[2])
    # parameters: every leaf of the defaults, plus what the code reads that the defaults lack (its own fallback applies then)
    pov = ov.get("parameters", {})
    params: dict[str, dict] = {}
    for p, v in flat_d.items():
        if v is None:
            continue
        params[p] = {"path": p, "default": v, "type": type(v).__name__ if not is_num(v) else "number", "in_defaults": True}
    code_inputs: dict[str, F.Input] = {}
    if fx:
        for i in fx.inputs.values():
            for p in i.chain:
                code_inputs.setdefault(p, i)
    for p in sorted(set(tr["missing"]) | {p for p in code_inputs if p not in flat_d}):
        if p in params or any(q.startswith(p + ".") for q in flat_d):
            continue
        inp = code_inputs.get(p)
        params[p] = {"path": p, "default": inp.default if inp else None, "type": "number" if inp and inp.default is not None else "unknown",
                     "in_defaults": False, "code_fallback": True}
    for p, rec in params.items():
        rec["read_by_compute"] = p in tr["reads"] or p in tr["missing"]
        if p in code_inputs:
            i = code_inputs[p]
            rec["read_as"] = {"chain": i.chain, "op": i.op, "fallback": i.default, "line": i.line}
        o = pov.get(p, {})
        for k in ("kind", "unit", "label", "component"):
            if k in o:
                rec[k] = o[k]
        if "unit" in o:
            rec["unit_status"] = "authored"
        if o.get("evidence"):
            aliases = {k for k, v in (fx.inputs.items() if fx else []) if p in v.chain}
            rec["evidence"] = o["evidence"]
            rec["evidence_check"] = check_evidence(src, o["evidence"], {p.split(".")[-1], *aliases})
        rec.setdefault("kind", "flag" if isinstance(rec["default"], bool) else "text" if isinstance(rec["default"], str) else "unknown")
        rec.setdefault("unit", "-" if rec["kind"] in ("flag", "text", "count") else "unknown")
        rec.setdefault("unit_status", "authored" if rec["unit"] == "-" and rec["kind"] in ("flag", "text") else ("unknown" if rec["unit"] == "unknown" else "authored"))
    counts = {p for p, r in params.items() if r.get("kind") == "count"}
    numeric = {p: float(r["default"]) for p, r in params.items() if r["type"] == "number" and is_num(r["default"])}
    outputs_num = [o for o, v in derived0.items() if is_num(v)]
    run = _Run(br, key)
    log(f"  {key}: {len(params)} parameters ({len(numeric)} numeric), {len(outputs_num)} numeric outputs")
    sens = sensitivity(run, defaults, {p: v for p, v in numeric.items() if params[p]["read_by_compute"]}, counts, outputs_num)
    verified = verify_formulas(run, fx, defaults, derived0, counts) if fx else {}
    oov = ov.get("outputs", {})
    outputs: dict[str, dict] = {}
    for o in outputs_num:
        rec = {"name": o, "value_at_defaults": derived0[o], "depends_on": sorted(sens[o]), "partials": sens[o]}
        rec.update({k: v for k, v in oov.get(o, {}).items() if k in ("kind", "unit", "label")})
        if "unit" in oov.get(o, {}):
            rec["unit_status"] = "authored"
        if o in verified:
            rec["formula"] = verified[o]
            fpaths = {i["chain"][0] for i in verified[o]["inputs"].values()}
            reads = {p for p in fpaths if p in params}
            if verified[o].get("status") == "verified_by_execution" and set(rec["depends_on"]) - reads:
                rec["formula"]["note"] = f"depends (measured) also on {sorted(set(rec['depends_on']) - reads)[:6]}, read through the fallbacks"
        elif fx and o in fx.opaque:
            rec["formula"] = {"status": "opaque", "why": fx.opaque[o]}
        rec.setdefault("kind", "unknown")
        rec.setdefault("unit", "unknown")
        rec.setdefault("unit_status", "unknown" if rec["unit"] == "unknown" else "authored")
        outputs[o] = rec
    for o, v in derived0.items():  # non-numeric results are configuration echoes (a type name, a flag): listed, not characterized
        if not is_num(v) and v is not None:
            outputs[o] = {"name": o, "value_at_defaults": v, "kind": "flag" if isinstance(v, bool) else "text", "unit": "-", "depends_on": []}
    infer_units(params, outputs, verified)
    for o, rec in outputs.items():
        for p in rec.get("depends_on", []):
            params[p].setdefault("affects_outputs", []).append(o)
    # validation and levels on the defaults
    val = br.request("validate", family=key, model=defaults)
    man["validation"] = {"available": val["available"], **({"reason": val.get("reason")} if not val["available"] else {}),
                         "messages_at_defaults": (val.get("issues") or [])[:40]}
    if ov.get("disabled_rules"):
        man["validation"]["disabled_rules"] = [{**r, "status": "source_disabled"} for r in ov["disabled_rules"]]
    lv = br.request("levels", family=key, model=defaults)
    man["levels_mapper"] = {"available": lv["available"], "levels_at_defaults": lv.get("levels")}
    # views
    vv = view_variants(br, key, defaults)
    if vv.get("available") and render:
        eff = view_effects(br, key, defaults, [v["mode"] for v in vv["views"]], numeric, counts, RENDER_BUDGET_S)
        for v in vv["views"]:
            v.update(eff.get(v["mode"], {}))
            for p in v.get("affected_by", []):
                params[p].setdefault("affects_views", []).append(v["mode"])
    man["views"] = vv
    # operations: what can be changed, and what each means for an EXISTING drawing
    ops = []
    for p, r in params.items():
        if r["type"] == "number" and (r.get("affects_outputs") or r.get("affects_views")):
            ops.append({"op": "set_count" if r.get("kind") == "count" else "set_value", "path": p,
                        "outputs": r.get("affects_outputs", [])[:30], "views": r.get("affects_views", []),
                        "on_existing_drawing": ("topology_change: adds or removes repeated members (and their dimensions) — not a change of value"
                                                if r.get("kind") == "count" else "parametric: a value change, compiled into the set-out and regenerated")})
    for v in vv.get("views", []) if vv.get("available") else []:
        for c in v.get("conditions", []):
            if isinstance(c, dict) and "path" in c.get("when", {}):
                ops.append({"op": "toggle", "path": c["when"]["path"], "value": c["when"]["value"], "view": v["mode"],
                            "effect": "adds the view" if c.get("added") else "removes the view",
                            "on_existing_drawing": "topology_change: a component and its views appear or disappear — needs geometry the drawing may not hold"})
    man["operations"] = ops
    # findings the code itself shows
    findings = list(ov.get("findings", []))
    commented = path and re.search(r"/\*[^*]*?(?:\*(?!/)[^*]*?)*?static\s+validate\s*\(", (src.root / path).read_text(errors="replace"), re.DOTALL)
    if not val["available"] and commented and not any(f.get("kind") == "disabled_validation" for f in findings):
        findings.append({"kind": "disabled_validation", "text": "the registered engine's validate() exists only inside a comment: no domain validation runs",
                         "evidence": [path]})
    bad = [i["msg"] for i in (val.get("issues") or []) if i.get("sev") == "err"]
    if bad:
        findings.append({"kind": "defaults_fail_validation", "text": "the family's own defaults fail its validation: " + "; ".join(m[:120] for m in bad[:4]),
                         "messages": bad[:10]})
    fall = [p for p in tr["missing"] if p in params and params[p].get("code_fallback")]
    if fall:
        findings.append({"kind": "code_fallbacks", "text": "compute() reads fields the family defaults do not hold; the code then uses its own constants: "
                         + ", ".join(f"{p} → {params[p]['default']}" for p in fall[:12]), "paths": fall})
    if imports is not None and sym and path:
        dups = duplicates(src, imports, path, sym)
        if dups:
            man["duplicates"] = dups
            for d in dups:
                findings.append({"kind": "duplicate_copy", "text": f"{d['path']} also defines {sym} ({'identical' if d['identical'] else 'DIFFERENT'}: "
                                 f"{d['lines']} vs {d['authoritative_lines']} lines); the registry uses {path}"
                                 + (f"; still imported by {', '.join(d['imported_by'][:3])}" if d["imported_by"] else ""), "evidence": [d["path"], path]})
    fails = [v["mode"] for v in vv.get("views", []) if v.get("renders") is False]
    if fails:
        findings.append({"kind": "headless_render", "text": f"views that do not render headless (not characterized): {', '.join(fails)}"})
    man["findings"] = findings
    man["parameters"] = list(params.values())
    man["outputs"] = list(outputs.values())
    man["formulas_summary"] = {"extracted": len(verified), "verified": sum(1 for v in verified.values() if v.get("status") == "verified_by_execution"),
                               "constants": sum(1 for v in verified.values() if v.get("status") == "constant_verified"),
                               "differs": sorted(o for o, v in verified.items() if v.get("status") == "differs"),
                               "opaque": sorted(o for o in (fx.opaque if fx else {}) if o in derived0)}
    if echoed:
        man["echoed_input_keys"] = echoed
    man["defaults"] = defaults
    # text and flag fields the engine reads: which values (string literals of its source, the other truth value) change what it computes —
    # a configuration a drawing must state before anything depending on it can be evaluated
    alts = _text_alternatives(run, defaults, derived0, params, (src.root / path).read_text(errors="replace") if path else "")
    for p, vals in alts.items():
        params[p]["values_that_change_outputs"] = vals
    man["characterization"] = {"samples_per_formula": SAMPLES, "defaults_digest": digest({k: json.dumps(v) for k, v in flat_d.items()}),
                               "derived_digest": digest({k: json.dumps(v) for k, v in derived0.items()})}
    return man


def extract_all(families: list[str] | None = None, br: RuleBridge | None = None, src: S.Source | None = None, out_dir: Path | None = None,
                render: bool = True, log=print) -> dict:
    src = src or S.locate()
    if src is None:
        raise RuntimeError("no aagento-bridge checkout (AAGENTO_BRIDGE_DIR or ../aagento-bridge)")
    br = br or RuleBridge()
    hello = br.hello()
    reg = S.registry_modules(src)
    out_dir = out_dir or knowledge_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    info = read_info(br.bundle.parent) or {}
    imports = _Imports(src)
    index = {"format": "dxf-autoparam/production-index-1", "extractor_version": EXTRACTOR_VERSION, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "source": {"repository": "aagento-bridge", **S.revision(src), "registry": src.rel(src.registry)},
             "bundle": {"sources_digest": (hello.get("build") or {}).get("sources_digest"), "built_at": info.get("built_at")}, "families": []}
    for h in hello["families"]:
        key = h["key"]
        if families and key not in families:
            continue
        log(f"extracting {key} …")
        t0 = time.monotonic()
        man = extract_family(br, src, key, reg.get(key, {}), h, imports=imports, render=render, log=log)
        (out_dir / f"{key}.json").write_text(json.dumps(man, indent=1, default=str))
        index["families"].append({"family": key, "title": h["title"], "file": f"{key}.json", "has_compute": h["has_compute"], "has_validate": h["has_validate"],
                                  "parameters": len(man["parameters"]), "outputs": len(man["outputs"]),
                                  "formulas_verified": (man.get("formulas_summary") or {}).get("verified", 0),
                                  "views": len((man.get("views") or {}).get("views", [])), "sources_digest": man["source"]["sources_digest"],
                                  "overlay": man["overlay"]["present"], "seconds": round(time.monotonic() - t0, 1)})
    if families:  # a partial run keeps the other families' rows
        old = out_dir / "index.json"
        if old.is_file():
            prev = json.loads(old.read_text())
            keep = [f for f in prev.get("families", []) if f["family"] not in families]
            index["families"] = sorted(keep + index["families"], key=lambda f: f["family"])
    (out_dir / "index.json").write_text(json.dumps(index, indent=1))
    return index
