"""The production bridge rule engines, used through an explicit adapter — characterized, bound to drawings, guarding changes, and exercised
through the real agent runtime with a scripted model (no network, no cost).

What is measured: the knowledge describes the code the registry actually runs (and says when it no longer does); formulas read from the source
agree with the production code on fresh samples; a binding judges only what the drawing's values decide; a change that breaks a production
relation held by the drawing — or that the engine's own validation rejects on the drawing's values — is refused and leaves the sheet exactly as it
was; a change of count is a topology change and is never applied; every failure of the boundary (no Node, a crash, a hang, a malformed answer,
stale knowledge) is a status, never a corrupted drawing.

Tests that run the production code need Node and the bundle (`dxf-autoparam production build`); without them they are skipped with the reason."""

from __future__ import annotations

import copy
import json
import random
import shutil
import time
from dataclasses import replace
from pathlib import Path

import pytest

from dxf_autoparam.ai import domain
from dxf_autoparam.ai import production as AP
from dxf_autoparam.ai.run import ACTIVE, unified_system, unified_tools
from dxf_autoparam.ai.scripted import ScriptedModel, call
from dxf_autoparam.crossview import SheetError, SheetModel
from dxf_autoparam.design_intent import strip
from dxf_autoparam.plan_bench import Box
from dxf_autoparam.production import binding as BD
from dxf_autoparam.production import formulas as F
from dxf_autoparam.production import manifest as M
from dxf_autoparam.production import service
from dxf_autoparam.production import source as S
from dxf_autoparam.production.bench import PLAN_DECISIONS, PLAN_INSTRUCTION, _sheet, truth_binding
from dxf_autoparam.production.bridge import BridgeError, BridgeUnavailable, RuleBridge, check_answer, default_bridge, set_default_bridge
from dxf_autoparam.program import evaluate
from dxf_autoparam.workspace import SheetSession

STATUS = default_bridge().status()
needs_bridge = pytest.mark.skipif(not STATUS["available"], reason=f"the production rule bridge cannot run here: {STATUS.get('reason')}")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
SRC = S.locate()
needs_checkout = pytest.mark.skipif(SRC is None, reason="no aagento-bridge checkout (AAGENTO_BRIDGE_DIR or ../aagento-bridge)")
PROD_TOOLS = {"production_families", "production_knowledge", "check_production_model", "bind_production_model", "assess_change", "validate_views"}


def names(t) -> set[str]:
    return {d.name for tool in t for d in tool.function_declarations}


# ── reading formulas out of a rule engine (no Node) ──────────────────────────────

ENGINE = """
import { X } from './x';
export class DemoEngine {
  static compute(model: any): any {
    const g = model.geometry || {};
    const hyd = model.hydraulics || {};
    const n = model.project?.count || model.project?.n || 2;   // the first present
    const w = g.width || 5.0;
    const t = g.thick ?? 0.3;
    const lvl = hyd.level ?? 100;
    let mutable = 3;
    const total = (w * n) + (t * 2);
    const top = lvl - t + Math.max(w, 1);
    const flag = n > 2 ? 1 : 0;
    const other = X.compute(model);
    return {
      total, top, n,
      later: mutable + 1,
      boq: { half: total / 2, fixed: 0.7 },
      cond: flag,
      echo: (model.slab || {}).width ?? 6.85,
    };
  }
}
"""


def test_formulas_are_read_from_straight_line_arithmetic_and_everything_else_is_said_opaque():
    body, root, line0 = F.engine_source(ENGINE, "DemoEngine")
    x = F.extract(body, root, line0)
    assert x.sections == {"g": "geometry", "hyd": "hydraulics"}
    assert x.inputs["n"].chain == ["project.count", "project.n"] and x.inputs["n"].default == 2.0
    assert x.inputs["t"].op == "??" and x.inputs["w"].op == "||"
    assert F.expand(x, x.outputs["total"]["expr"]).replace(" ", "") == "((w*n)+(t*2))"
    assert "max" in F.expand(x, x.outputs["top"]["expr"])
    assert x.outputs["boq.half"]["expr"] and x.outputs["boq.fixed"]["expr"] == "0.7"
    assert x.outputs["echo"]["passthrough"]
    assert "let" in x.opaque["mutable"] and "later" in x.opaque and "cond" in x.opaque and "other" in x.opaque
    lines = ENGINE.split("\n")
    assert "const total" in lines[x.outputs["total"]["line"] - 1], "every formula points at its source line"
    assert "half" in lines[x.outputs["boq.half"]["line"] - 1]


def test_a_read_follows_the_fallback_semantics_of_or_and_nullish():
    or_ = F.Input(chain=["a.b", "a.c"], op="||", default=9.0)
    nul = F.Input(chain=["a.b"], op="??", default=9.0)
    assert F.resolve(or_, {"a": {"b": 0, "c": 4}}) == 4  # || skips a zero
    assert F.resolve(nul, {"a": {"b": 0}}) == 0  # ?? keeps it
    assert F.resolve(or_, {}) == 9.0 and F.resolve(nul, {"a": {}}) == 9.0
    m: dict = {"l": [1, 2]}
    with pytest.raises(KeyError):
        F.set_path(m, "l.length", 3)  # an array's length the code read is not a field a model can set


# ── the knowledge: shape, provenance, freshness (no Node) ────────────────────────


def test_every_shipped_manifest_is_well_formed_and_says_where_it_came_from():
    pk = M.ProductionKnowledge()
    assert pk.available() and len(pk.family_keys()) >= 13
    statuses = set()
    for key in pk.family_keys():
        fam = pk.family(key)
        assert M.validate_manifest(fam.data) == [], key
        src = fam.data["source"]
        assert src["repository"] == "aagento-bridge" and src["commit"] and src["sources"] and src["sources_digest"]
        if fam.supported:
            assert (src["modules"].get("ruleEngine") or {}), key
            for o in fam.data["outputs"]:
                statuses.add((o.get("formula") or {}).get("status"))
    assert statuses <= {None, "verified_by_execution", "constant_verified", "opaque", "differs", "not_evaluable"}
    assert "differs" not in statuses, "a formula the production code contradicts is never shipped as knowledge"


def test_the_railway_box_knowledge_says_what_the_production_code_shows():
    fam = M.ProductionKnowledge().family("railway_rcc_box")
    # validate() was commented out when this was first read; aagento-bridge runs it again (rcc-box-rule-engine.ts:106-160): the knowledge follows the
    # code — the authored "disabled" note is dropped and the rules it listed are marked as running
    assert fam.data["capabilities"]["has_validate"] is True
    assert not any(f["kind"] == "disabled_validation" for f in fam.data["findings"])
    assert {r["status"] for r in fam.data["validation"]["disabled_rules"]} == {"source_enabled"}
    assert any("soffit" in m["msg"].lower() and "≠" in m["msg"] for m in fam.data["validation"]["messages_at_defaults"]), \
        "the family's own defaults are inconsistent about the soffit, and its validation says so"
    total = fam.outputs["total_w"]
    assert total["formula"]["status"] == "verified_by_execution" and total["unit"] == "m"
    assert set(total["depends_on"]) == {"geometry.clear_w", "geometry.t_wall_o", "geometry.t_wall_i", "project.cells"}
    assert "geometry.t_slab_t" not in fam.outputs["soffit"]["depends_on"], "the soffit level cancels the top slab: measured, not assumed"
    assert fam.params["hydraulics.berm"]["unit"] == "mm" and fam.params["geometry.clear_w"]["evidence_check"] == "checked"
    sec = next(v for v in fam.views if v["mode"] == "sec")
    assert "foundation.found_d" in sec["affected_by"] and "foundation.sand_fill_depth" not in sec["affected_by"], \
        "the half section draws the fill from found_d, not from the engine's sand_fill_depth (measured by rendering it)"
    curtain = next(v for v in fam.views if v["mode"] == "cw")
    assert any(c.get("when", {}).get("path") == "options2d.show_curtain_wall" for c in curtain["conditions"] if isinstance(c, dict)), \
        "a view a toggle switches off says which toggle"


def test_a_malformed_manifest_is_refused_whole(tmp_path):
    src = M.default_dir()
    dst = tmp_path / "production"
    shutil.copytree(src, dst)
    p = dst / "railway_rcc_box.json"
    d = json.loads(p.read_text())
    del d["outputs"][0]["depends_on"]
    p.write_text(json.dumps(d))
    with pytest.raises(M.KnowledgeError, match="malformed"):
        M.ProductionKnowledge(dst).family("railway_rcc_box")
    d["format"] = "something-else"
    p.write_text(json.dumps(d))
    with pytest.raises(M.KnowledgeError):
        M.ProductionKnowledge(dst).family("railway_rcc_box")


def _fake_checkout(tmp_path: Path, fam: M.FamilyKnowledge) -> S.Source:
    """A checkout holding exactly the files the manifest fingerprints (copied when the real one is here, else written to match)."""
    root = tmp_path / "checkout"
    for f, h in fam.data["source"]["sources"].items():
        dst = root / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        if SRC is not None and (SRC.root / f).is_file() and S.sha256(SRC.root / f) == h:
            shutil.copy(SRC.root / f, dst)
        else:
            dst.write_text("placeholder")
    return S.Source(root)


@needs_checkout
def test_knowledge_is_stale_the_moment_a_module_it_describes_changes(tmp_path):
    pk = M.ProductionKnowledge()
    fam = pk.family("railway_rcc_box")
    fake = _fake_checkout(tmp_path, fam)
    assert pk.freshness("railway_rcc_box", src=fake, refresh=True)["checkout"] == "same"
    engine = next(f for f in fam.data["source"]["sources"] if f.endswith("rcc-box-rule-engine.ts"))
    (fake.root / engine).write_text((fake.root / engine).read_text() + "\n// changed\n")
    fr = pk.freshness("railway_rcc_box", src=fake, refresh=True)
    assert fr["state"] == "stale" and engine in fr["changed_files"]


@needs_bridge
def test_a_bundle_built_from_other_code_is_never_used_to_evaluate(tmp_path, monkeypatch):
    from dxf_autoparam.production.build import read_info

    info = read_info()
    fam = M.ProductionKnowledge().family("railway_rcc_box")
    f = next(iter(fam.data["source"]["sources"]))
    info["sources"][f] = "0" * 64
    (tmp_path / "build.json").write_text(json.dumps(info))
    monkeypatch.setenv("AUTOPARAM_PRODUCTION_CACHE", str(tmp_path))
    pk = M.ProductionKnowledge()
    fr = pk.freshness("railway_rcc_box", src=False, refresh=True)
    assert fr["bundle"] == "differs" and fr["state"] == "unverifiable"
    sm, us, _up, _g = _sheet(Box(), tmp_path, "s")
    rep = BD.evaluate(fam, BD.Binding.from_json(truth_binding(sm, us, Box())), sm._domain_state({"unit": us}), default_bridge(), freshness=fr)
    assert rep["status"] == "stale" and "nothing was evaluated" in rep["why"]


@needs_checkout
def test_the_registry_not_the_file_name_decides_which_engine_is_authoritative():
    reg = S.registry_modules(SRC)
    assert reg["psc_slab"]["ruleEngine"]["path"].endswith("utils/psc-slab/psc-slab-rule-engine.ts")
    assert reg["hume_pipe"]["ruleEngine"]["inline_object"]["compute"]["symbol"] == "evaluateHumePipeRules"
    psc = M.ProductionKnowledge().family("psc_slab")
    stale = [d for d in psc.data.get("duplicates", []) if d["path"].endswith("utils/psc-slab-rule-engine.ts")]
    assert stale and stale[0]["identical"] is False, "the root copy differs from the registered engine and is reported as a stale copy"


# ── the boundary itself ──────────────────────────────────────────────────────────


def test_answers_that_break_the_protocol_are_refused():
    with pytest.raises(BridgeError, match="malformed"):
        check_answer("compute", 1, {"id": 2, "ok": True, "result": {}})
    with pytest.raises(BridgeError, match="derived"):
        check_answer("compute", 1, {"id": 1, "ok": True, "result": {"derived": 5}})
    with pytest.raises(BridgeError, match="failed in the production code"):
        check_answer("compute", 1, {"id": 1, "ok": False, "error": "boom"})
    with pytest.raises(BridgeError, match="malformed row"):
        check_answer("compute_many", 3, {"id": 3, "ok": True, "result": {"derived": [{"ok": True}]}})
    assert check_answer("validate", 4, {"id": 4, "ok": True, "result": {"available": False}}) == {"available": False}


def test_without_a_bundle_the_rules_are_unavailable_and_say_why(tmp_path):
    br = RuleBridge(bundle=tmp_path / "absent.mjs")
    st = br.status()
    assert st["available"] is False and "production build" in st["reason"]
    with pytest.raises(BridgeUnavailable):
        br.request("hello")


@needs_node
@pytest.mark.parametrize("script,expect", [
    ("process.exit(3);", "exited"),
    ("require('readline').createInterface({input: process.stdin}).on('line', () => {});", "timed out"),
    (("require('readline').createInterface({input: process.stdin}).on('line', l => { const r = JSON.parse(l); "
      "process.stdout.write('not json\\n'); process.stdout.write(JSON.stringify({id: r.id, ok: true, result: {derived: 5}}) + '\\n'); });"), "derived"),
])
def test_a_crashing_hanging_or_lying_bridge_is_an_error_and_the_next_request_starts_afresh(tmp_path, script, expect):
    bundle = tmp_path / "fake.cjs"
    bundle.write_text(script)
    br = RuleBridge(bundle=bundle, timeout_s=1.5)
    with pytest.raises(BridgeError, match=expect):
        br.request("compute", family="x", model={})
    with pytest.raises(BridgeError):  # a fresh process, the same verdict: nothing is ever taken from a broken answer
        br.request("compute", family="x", model={})
    br.close()


# ── characterization through the real production code ───────────────────────────


@needs_bridge
def test_the_bundle_serves_the_registry_the_knowledge_describes():
    pk = M.ProductionKnowledge()
    hello = default_bridge().hello()
    keys = [f["key"] for f in hello["families"]]
    assert sorted(keys) == sorted(pk.family_keys()), "the bundle and the manifests describe the same registry (order is not knowledge)"
    by = {f["key"]: f for f in hello["families"]}
    assert by["rcc_slab_legacy"]["has_validate"] is False and by["railway_rcc_box"]["has_validate"] is True
    assert all(f["has_compute"] for f in hello["families"]), "the template renderers without a rule engine have left the registry"


@needs_bridge
@pytest.mark.parametrize("family", ["railway_rcc_box", "highway_rcc_box", "hume_pipe", "rcc_slab", "railway_arch_bridge"])
def test_the_production_code_still_computes_what_the_knowledge_recorded(family):
    fam = M.ProductionKnowledge().family(family)
    got = BD._flat(default_bridge().request("compute", family=family, model=fam.defaults_model())["derived"])
    for o in fam.data["outputs"]:
        v = o.get("value_at_defaults")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            assert got[o["name"]] == pytest.approx(v, rel=1e-12, abs=1e-12), o["name"]


@needs_bridge
@pytest.mark.parametrize("family", ["railway_rcc_box", "highway_rcc_box", "hume_pipe", "highway_arch_bridge"])
def test_formulas_agree_with_the_production_code_on_samples_never_seen(family):
    fam = M.ProductionKnowledge().family(family)
    rng = random.Random(2026)
    checked = 0
    for o in fam.data["outputs"]:
        f = o.get("formula") or {}
        if f.get("status") != "verified_by_execution":
            continue
        ins = {s: F.Input(chain=i["chain"], op=i["op"], default=i["default"], coerced=i.get("coerced", False)) for s, i in f["inputs"].items()}
        models = []
        for _ in range(6):
            m = fam.defaults_model()
            for i in ins.values():
                path = next((p for p in i.chain if F.get_path(m, p) is not None), i.chain[0])
                base = F.resolve(i, m)
                count = (fam.params.get(path) or {}).get("kind") == "count"
                F.set_path(m, path, float(rng.randint(1, 5)) if count else float(base or 1.0) * rng.uniform(0.4, 2.2) + 0.003)
            models.append(m)
        rows = default_bridge().request("compute_many", family=family, models=models)["derived"]
        for m, row in zip(models, rows, strict=True):
            prod = BD._flat(row["derived"])[o["name"]]
            py = evaluate(f["expr"], {s: float(F.resolve(i, m)) for s, i in ins.items()})
            assert py == pytest.approx(prod, rel=1e-9, abs=1e-9), (o["name"], f["display"])
        checked += 1
    assert checked >= 10, f"{family}: only {checked} formulas"


@needs_bridge
def test_the_two_box_families_set_their_levels_out_differently():
    pk = M.ProductionKnowledge()
    rail, road = pk.family("railway_rcc_box"), pk.family("highway_rcc_box")
    assert "deck.wearing_course" in rail.outputs["z_bot"]["depends_on"]
    assert "deck.wearing_course" not in road.outputs["z_bot"]["depends_on"]


@needs_bridge
def test_each_validation_message_names_the_fields_that_decided_it():
    m = M.ProductionKnowledge().family("highway_rcc_box").defaults_model()
    m["geometry"]["t_wall_o"] = 0.25
    v = default_bridge().request("validate", family="highway_rcc_box", model=m)
    wall = next(a for a in v["attributed"] if "Outer wall" in a["msg"])
    assert wall["sev"] == "err" and wall["reads"] == ["geometry.t_wall_o"]
    hfl = next(a for a in v["attributed"] if "HFL clearance" in a["msg"])
    assert set(hfl["reads"]) == {"hydraulics.hfl", "hydraulics.bed_lvl", "geometry.clear_h"}


# ── bindings on a drawing ────────────────────────────────────────────────────────


@needs_bridge
def test_a_true_binding_holds_and_what_waits_for_an_unbound_field_is_not_judged(tmp_path):
    b = Box()
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    tb = truth_binding(sm, us, b)
    tb["outputs"]["spanLen"] = tb["outputs"]["total_w"]
    rep = service.report(tb, sm._domain_state(tb))
    assert rep["outputs"]["total_w"]["result"] == "holds" and rep["outputs"]["total_w"]["expected"] == pytest.approx(b.width)
    assert rep["outputs"]["total_h"]["result"] == "holds"
    span = rep["outputs"]["spanLen"]
    assert span["result"] == "not_evaluable" and "deck.formation_lvl" in span["waits_for"], "a production default is never taken for the drawing's value"
    val = rep["validation"]
    assert val["ran"] and val["status"] in ("passed", "inconclusive") and val["decided_by_drawing"] < val["checks"], \
        "the engine's own checks ran; those that read a production default are counted apart, never a verdict on the drawing"
    assert rep["status"] == "partial"


@needs_bridge
def test_corrupted_bindings_are_caught_and_never_accepted(tmp_path):
    from dxf_autoparam.production.bench import corruptions

    b = Box(cells=3, span=2200.0, wall=375.0, top=275.0, mid=250.0)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    good = truth_binding(sm, us, b)
    fam = M.knowledge().family("railway_rcc_box")
    seen = {}
    for kind, cb in corruptions(sm, us, b, good, fam):
        try:
            rep = service.report(cb, sm._domain_state(cb))
        except service.ProductionRefusal:
            rep = {"status": "refused"}
        seen[kind.split(" (")[0]] = rep["status"]
    assert seen["wrong count stated"] == "differs" and seen["an output bound to the wrong lines"] == "differs"
    assert seen["a size bound to the wrong value"] == "differs"
    assert {seen[k] for k in ("a level bound to a length", "a number in place of a reference", "a field whose unit is unknown",
                             "a field the family does not have")} == {"refused"}


@needs_bridge
def test_an_inverted_dependency_is_reported_and_the_proposed_relation_makes_the_drawing_follow(tmp_path):
    b = Box(cells=1, span=2500.0)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    sm.commit_answer(us, strip(sm.unit(us).answer), intent=False)
    # the overall width made an input of its own: the far face set out from the near one by it, as a person's formula (the engine no longer
    # makes a sum of named sizes an input by itself — it is worked out — so the inversion is written here)
    u = sm.unit(us)
    um = u.sub.units_mm
    lo, hi = sorted(u.prog.params["ClearSpan"].measures, key=lambda d: u.an.datums[d].value)
    xs = [d for d in u.an.datums.values() if d.axis == "x"]
    near0, far0 = next((a.id, c.id) for a in xs for c in xs if abs((c.value - a.value) * um - b.width) < 1e-6
                       and a.value < u.an.datums[lo].value and c.value > u.an.datums[hi].value)
    ans = copy.deepcopy(u.answer)
    ans["parameters"].append({"name": "OverallWidth", "label": "OverallWidth", "kind": "length", "from_datum": near0, "to_datum": far0, "value": b.width})
    ans["datum_formulas"] = [*ans.get("datum_formulas", []), {"datum": far0, "expr": f"{near0} + OverallWidth"}]
    sm.commit_answer(us, ans, intent=False)
    u = sm.unit(us)
    overall = next(n for n, p in u.prog.params.items() if abs(p.value - b.width) < 1e-6)
    bind = {"family": "railway_rcc_box", "unit": us, "inputs": {"geometry.clear_w": "ClearSpan", "geometry.t_wall_o": "OuterWall"},
            "config": {"project.cells": {"value": 1, "basis": "one cell drawn"}}, "outputs": {"total_w": overall}}
    rep = service.report(bind, sm._domain_state(bind))
    assert rep["structure"][0]["kind"] == "output_independent_in_drawing"
    prop = rep["proposals"][0]
    assert prop["relation"] == "ClearSpan + 2 * OuterWall", "obtained by running the production code, in the drawing's own names"
    near, far = prop["lines"]
    ans = copy.deepcopy(u.answer)
    ans["datum_formulas"] = [f for f in ans.get("datum_formulas", []) if f.get("datum") != far] + [{"datum": far, "expr": f"{near} + {prop['relation']}"}]
    sm.commit_answer(us, ans)
    sm.bind_domain({**bind, "outputs": {"total_w": {"lines": [near, far]}}})
    r = sm.apply({f"{us}.ClearSpan": 3000.0})
    assert r.ok, r.errors
    after = sm.domain_report()[0]["outputs"]["total_w"]
    assert after["result"] == "holds" and after["measured"] == pytest.approx(3000.0 + 2 * b.wall)


# ── the newly authored overlays: hume_pipe, rcc_slab, the arch bridges, the RUBs ─


BOX_SHAPED_FAMILIES = ["rcc_slab", "railway_arch_bridge", "highway_arch_bridge", "railway_rub", "highway_rub"]


@pytest.mark.parametrize("family,params,outputs", [
    ("hume_pipe", ["spanSize", "numPipes", "bedLevel", "wallThickness"], ["span", "total_w", "total_h", "flowArea"]),
    ("rcc_slab", ["geometry.clear_w", "hydraulics.bed_lvl", "project.cells"], ["total_w", "total_h", "archThick", "z_bot"]),
    ("railway_arch_bridge", ["geometry.clear_w", "hydraulics.bed_lvl", "project.cells"], ["total_w", "total_h", "archThick", "z_bot"]),
    ("highway_arch_bridge", ["geometry.clear_w", "hydraulics.bed_lvl", "project.cells"], ["total_w", "total_h", "archThick", "z_bot"]),
    ("railway_rub", ["geometry.clear_w", "hydraulics.bed_lvl", "project.cells"], ["total_w", "total_h", "z_bot", "boq.shearKeyW"]),
    ("highway_rub", ["geometry.clear_w", "hydraulics.bed_lvl", "project.cells"], ["total_w", "total_h", "z_bot", "boq.shearKeyW"]),
])
def test_the_newly_authored_overlays_give_their_key_fields_a_known_kind_and_unit(family, params, outputs):
    fam = M.ProductionKnowledge().family(family)
    for path in params:
        rec = fam.params[path]
        assert rec["kind"] != "unknown" and rec["unit"] != "unknown", (family, path, rec)
        assert rec["evidence_check"] == "checked", (family, path, rec.get("evidence"))
    for name in outputs:
        rec = fam.outputs[name]
        assert rec["kind"] != "unknown" and rec["unit"] != "unknown", (family, name, rec)


@needs_bridge
@pytest.mark.parametrize("family", BOX_SHAPED_FAMILIES)
def test_a_box_shaped_overlay_holds_the_box_s_own_total_width_and_height_on_a_generated_drawing(tmp_path, family):
    """rcc_slab / the arch bridges / the RUBs register the SAME box rule engine (byte-identical apart from the class name) as the RCC box
    families, so the generated box fixture's own truth binding (total_w, total_h) is a genuine relation for them too."""
    b = Box()
    sm, us, _up, _g = _sheet(b, tmp_path, family)
    tb = truth_binding(sm, us, b, family=family)
    rep = service.report(tb, sm._domain_state(tb))
    assert rep["outputs"]["total_w"]["result"] == "holds" and rep["outputs"]["total_w"]["expected"] == pytest.approx(b.width)
    assert rep["outputs"]["total_h"]["result"] == "holds"


@needs_bridge
def test_a_hume_pipe_binding_on_a_generated_drawing_judges_a_real_relation(tmp_path):
    """hume_pipe has no fixture generator of its own; its span input/output is a clean round trip through the overlay's units
    (spanSize in metres in, span in millimetres out) and is bound to the box fixture's own clear-span value."""
    b = Box()
    sm, us, _up, _g = _sheet(b, tmp_path, "hume")
    binding = {"family": "hume_pipe", "unit": us, "inputs": {"spanSize": "ClearSpan"}, "outputs": {"span": "ClearSpan"}}
    rep = service.report(binding, sm._domain_state(binding))
    assert rep["outputs"]["span"]["result"] == "holds" and rep["outputs"]["span"]["expected"] == pytest.approx(b.span)


# ── the sheet: guards, undo, persistence ─────────────────────────────────────────


@needs_bridge
def test_a_change_the_other_view_follows_is_applied_and_one_it_does_not_is_refused_with_nothing_changed(tmp_path):
    for unlink in (False, True):
        b = Box()
        (tmp_path / str(unlink)).mkdir()
        sm, us, up, _g = _sheet(b, tmp_path / str(unlink), "s", unlink=unlink)
        acc = sm.bind_domain(truth_binding(sm, us, b, plan_unit=up))
        assert acc["guards"] == ["total_w", "total_h"]
        before = copy.deepcopy(sm._state())
        rev = sm.revision
        req = {"instruction": PLAN_INSTRUCTION.format(v="2500"), "decisions": PLAN_DECISIONS}
        if not unlink:
            res = sm.apply_plan(us, req)
            assert res["applied"]["value"] == 2500.0 and len([v for v, c in res["applied"]["by_view"].items() if c]) == 2
            assert sm.domain_report()[0]["outputs"]["total_w"]["measured"] == pytest.approx(6000.0)
        else:
            with pytest.raises(SheetError, match=r"production rule .* total_w .* 6000 mm .* 7000 mm"):
                sm.apply_plan(us, req)
            after = sm._state()
            assert after["values"] == before["values"] and after["answers"] == before["answers"] and after["domain"] == before["domain"]
            assert sm.revision == rev


@needs_bridge
def test_a_change_the_engines_own_validation_rejects_on_the_drawings_values_is_refused(tmp_path):
    b = replace(Box(), detail=False)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    acc = sm.bind_domain(truth_binding(sm, us, b, family="highway_rcc_box"))
    assert acc["guard_validation"] is True
    hfl = next(m for m in acc["validation"]["messages"] if "HFL clearance" in m["msg"])
    assert hfl["decided_by_drawing"] is False and "hydraulics.hfl" in hfl["uses_production_defaults_for"], \
        "a check the production defaults decide (no flood level is bound) is never held for or against the drawing"
    wall = next(m for m in acc["validation"]["messages"] if "Outer wall" in m["msg"])
    assert wall["decided_by_drawing"] is True and wall["fields"] == ["geometry.t_wall_o"]
    bad = sm.apply({f"{us}.OuterWall": 250.0})
    assert not bad.ok and any("Outer wall thickness < 0.3m" in e for e in bad.errors)
    assert sm.values.get(us, {}).get("OuterWall") is None
    assert sm.apply({f"{us}.OuterWall": 400.0}).ok


@needs_bridge
def test_a_binding_is_one_undoable_step_saved_with_the_project_and_cleared_by_reset(tmp_path):
    from dxf_autoparam.baseline import reset_drawing

    b = Box()
    sm, us, _up, g = _sheet(b, tmp_path, "s")
    sm.bind_domain(truth_binding(sm, us, b))
    assert [x["id"] for x in sm.domain] == [f"railway_rcc_box@{us}"]
    proj = tmp_path / "p.autoparam.json"
    sm.save(str(proj))
    sm2 = SheetModel.load(str(proj), g["path"])
    assert sm2.domain == sm.domain and sm2.domain_report()[0]["status"] == "holds"
    assert sm.undo() and sm.domain == []
    assert sm.redo() and len(sm.domain) == 1
    reset_drawing(sm)
    assert sm.domain == []


@needs_bridge
def test_a_parametrization_that_drops_a_bound_value_is_refused(tmp_path):
    b = Box()
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    sm.bind_domain(truth_binding(sm, us, b))
    ans = copy.deepcopy(sm.unit(us).answer)
    ans["parameters"] = [p for p in ans["parameters"] if p["name"] != "OuterWall"]
    with pytest.raises(SheetError, match="OuterWall.*define it first"):
        sm.commit_answer(us, ans)
    assert any(p["name"] == "OuterWall" for p in sm.unit(us).answer["parameters"])


@needs_bridge
def test_stale_knowledge_guards_nothing_and_a_guarded_sheet_without_the_bridge_refuses_what_it_cannot_verify(tmp_path, monkeypatch):
    b = Box()
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    pk = M.knowledge()
    real = pk.freshness
    monkeypatch.setattr(pk, "freshness", lambda key, **kw: {**real(key, **kw), "state": "stale", "checkout": "changed"})
    acc = sm.bind_domain(truth_binding(sm, us, b))
    assert acc["guards"] == [] and "stale" in acc["guards_note"]
    monkeypatch.setattr(pk, "freshness", real)
    sm.bind_domain(truth_binding(sm, us, b))
    assert sm.domain[0]["guards"]
    saved = default_bridge()
    try:
        set_default_bridge(RuleBridge(bundle=tmp_path / "absent.mjs"))
        r = sm.apply({f"{us}.ClearSpan": 2800.0})
        assert not r.ok and any("cannot be verified" in e for e in r.errors)
    finally:
        set_default_bridge(saved)


# ── the agent's tools, through the real runtime ──────────────────────────────────


def test_the_production_tools_exist_only_with_the_pack_and_name_no_kind_of_structure():
    pack = domain.active("bridge")
    assert not names(unified_tools()) & PROD_TOOLS and PROD_TOOLS <= names(unified_tools(pack))
    assert "PRODUCTION RULE ENGINES" in unified_system(pack) and "PRODUCTION RULE ENGINES" not in unified_system(None)
    text = json.dumps([(n, d, p) for n, d, p in AP.PRODUCTION_TOOL_SPECS], default=str)
    for word in ("ClearSpan", "rcc", "RCC", "culvert", "bridge", "girder", "pipe ", "slab", "cells"):
        assert word not in text, word


def _wait(sheet, rid, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        p = sheet.run_progress(rid, 0)
        if p["status"] not in ACTIVE:
            return p
        time.sleep(0.03)
    raise AssertionError(sheet.run_progress(rid, 0)["status"])


def _sheet_session(tmp_path, b: Box):
    sm, us, up, _g = _sheet(b, tmp_path, "s")
    sheet = SheetSession()
    sheet.sm = sm
    return sheet, sm, us, up


READ = call("account_instruction", items=[
    {"quote": "Check the drawing against the production rules", "kind": "process", "meaning": "bind the production model and keep what holds",
     "handled_by": "none", "why": "a check, no value changes"},
    {"quote": "tell me whether a third cell can be added", "kind": "context", "meaning": "assess the change of count", "handled_by": "none",
     "why": "an assessment for the person"}])


@needs_bridge
def test_a_run_consults_binds_assesses_and_validates_every_view(tmp_path):
    b = Box()
    sheet, sm, us, _up = _sheet_session(tmp_path, b)
    tb = truth_binding(sm, us, b)
    script = [
        [READ],
        [call("production_families")],
        [call("production_knowledge", family="railway_rcc_box", sections=["summary", "outputs", "operations"], query="total")],
        [call("check_production_model", family="railway_rcc_box", unit=us, inputs=tb["inputs"], config=tb["config"],
              outputs={**tb["outputs"], "spanLen": tb["outputs"]["total_w"]})],
        [call("bind_production_model", family="railway_rcc_box", unit=us, inputs=tb["inputs"], config=tb["config"], outputs=tb["outputs"])],
        [call("bind_production_model", family="railway_rcc_box", unit=us, inputs={"geometry.clear_w": 3000}, outputs={})],
        [call("assess_change", family="railway_rcc_box", changes={"project.cells": 3}),
         call("assess_change", family="railway_rcc_box", changes={"geometry.clear_w": 2.5})],
        [call("validate_views")],
        [call("finish", summary="bound, guarded, assessed: a third cell is a topology change this engine cannot make")],
    ]
    gem = ScriptedModel(script)
    sheet.gem_factory = lambda: gem
    instruction = "Check the drawing against the production rules, and tell me whether a third cell can be added."
    p = _wait(sheet, sheet.start_run({"instruction": instruction, "options": {"domain": "bridge"}})["run"])
    seen = {fr.name: fr.response for turn in gem.seen for fr in turn}
    assert PROD_TOOLS <= set(gem.requests[0]["tools"]) and "PRODUCTION RULE ENGINES" in gem.requests[0]["system"]
    fams = seen["production_families"]["result"]
    assert fams["runs_here"] and fams["match_this_drawing"][0]["family"] in ("railway_rcc_box", "highway_rcc_box")
    know = seen["production_knowledge"]["result"]
    total = next(o for o in know["outputs"] if o["name"] == "total_w")
    assert total["formula"]["status"] == "verified_by_execution" and know["provenance"]["knowledge"] == "fresh"
    chk = seen["check_production_model"]["result"]
    assert chk["outputs"]["total_w"]["result"] == "holds" and chk["outputs"]["spanLen"]["result"] == "not_evaluable"
    kept = sm.domain
    assert [x["id"] for x in kept] == [f"railway_rcc_box@{us}"] and kept[0]["guards"] == ["total_w", "total_h"]
    binds = [fr.response["result"]["result"] for turn in gem.seen for fr in turn if fr.name == "bind_production_model"]  # a write's verdict
    assert binds[0]["ok"] and binds[0]["guards"] == ["total_w", "total_h"]
    assert not binds[1]["ok"] and "number is not a reference" in json.dumps(binds[1])
    topo, value = [fr.response["result"] for turn in gem.seen for fr in turn if fr.name == "assess_change"]
    assert topo["fields"][0]["status"] == "topology_change" and topo["fields"][0]["can_apply"] is False
    assert topo["outputs"]["total_w"]["after"] - topo["outputs"]["total_w"]["before"] == pytest.approx(b.span + b.mid)
    assert value["fields"][0]["drives"] == "ClearSpan" and value["fields"][0]["requested_value"] == pytest.approx(2500.0)
    views = seen["validate_views"]["result"]["views"]
    sec = next(v for v in views if v["unit"] == us)
    assert sec["geometry"]["status"] == "passed" and sec["production_rules"]["relations"] == "passed"
    assert sec["production_rules"]["engine_validation"] == "passed", "the railway box's engine validates again: its checks ran on the drawing's values"
    v = p["verdict"]
    assert v["production"]["bindings_kept"][0]["guards"] == ["total_w", "total_h"]
    crit = {c["id"]: c for c in v["criteria"]}
    assert crit["production_guards_hold"]["ok"]
    assert any("topology changes assessed" in n for n in v["notes"]) and any("production rules railway_rcc_box@" in n for n in v["notes"])
    assert not v["values_applied"], "nothing changed the drawing's values: binding and assessing never move a line"


@needs_bridge
def test_with_the_pack_off_no_production_tool_is_reachable(tmp_path):
    sheet, _sm, _us, _up = _sheet_session(tmp_path, Box())
    gem = ScriptedModel([[READ], [call("production_families")], [call("finish", summary="nothing")]])
    sheet.gem_factory = lambda: gem
    p = _wait(sheet, sheet.start_run({"instruction": "Check the drawing against the production rules, and tell me whether a third cell can be added."})["run"])
    assert not PROD_TOOLS & set(gem.requests[0]["tools"])
    answer = next(fr.response for turn in gem.seen for fr in turn if fr.name == "production_families")
    assert "no production rule engines" in json.dumps(answer)
    assert p["verdict"]["production"] is None
