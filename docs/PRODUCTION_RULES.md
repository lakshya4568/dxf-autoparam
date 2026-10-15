# The production bridge rule engines — used, not copied

What it is: the aagento-bridge application's own rule engines (`BRIDGE_REGISTRY`, src/app/features/bridges/models/bridge-registry.ts) made
available to this project's agent and sheet as **knowledge it can retrieve** and **code it can run on a drawing's values** — through one
execution boundary, with provenance, freshness and an explicit adapter (the binding). No TypeScript is translated into Python; Python stays the
owner of the parametrization, the sheet and its transactions.

```
aagento-bridge checkout ──(read only)──► tools/production/bridge_rules.ts ──esbuild──► .cache/production/bridge_rules.mjs (+ build.json)
        │                                   (imports BRIDGE_REGISTRY itself)                     │  JSON lines over stdin/stdout
        │ registry imports, sha256                                                                ▼
        ▼                                                                       production/bridge.py  RuleBridge (persistent node, timeouts,
production/extract.py ──► knowledge/production/<family>.json + index.json                          every answer shape-checked)
  (run the code: defaults, outputs, dependencies by perturbation,                                    │
   formulas read from source and VERIFIED by execution, views rendered                               ▼
   headless, validation attributed, duplicates, findings)                        production/binding.py  Binding: production field ↔ the
        │                                                                          drawing's own value / lines / level (units checked)
        ▼                                                                                            │
production/manifest.py  (shape-checked, fresh / stale / unverifiable)            crossview.SheetModel.domain  (undoable, saved, guarded in
        │                                                                          every regenerate(): apply, apply_plan, commit_answer)
        ▼                                                                                            │
ai/production.py  six tools for the agent (only with the domain pack) ───────────────────────────────┘
```

## Commands (no model, no cost)

```bash
uv run dxf-autoparam production build      # bundle the registry from ../aagento-bridge (or AAGENTO_BRIDGE_DIR); records commit + sha256
uv run dxf-autoparam production extract    # regenerate the manifests (≈45 s, 15 registry keys); --family F, --no-render
uv run dxf-autoparam production status     # per family: knowledge fresh / stale / unverifiable, checkout same / changed, bundle matches / differs
uv run dxf-autoparam production show railway_rcc_box --section outputs --query total
uv run dxf-autoparam production discover drawing.dxf
uv run dxf-autoparam production bench      # the integration measured on generated drawings with known truth
uv run python tools/production_demo.py     # one instruction end to end through the real runtime (scripted model)
```

## What was found in the production code (and is recorded as findings, with evidence)

- The registry dispatches 15 keys; 13 have a rule engine (`compute`), 11 a `validate`. `cad_preview` / `test_bridge_parametric` are generic
  template renderers with no rule engine: their manifests say *unsupported*.
- The railway RCC box's `validate()` is inside a block comment (rcc-box-rule-engine.ts:106–160): the production app runs no domain validation for
  it. Its rules are kept as `disabled_rules` (knowledge, never enforced).
- Stale copies: `utils/psc-slab-rule-engine.ts` differs from the registered `utils/psc-slab/…` (375 vs 383 lines); the root highway box copy is
  identical. Found by symbol search over the bridges folder, with who still imports each.
- Railway and highway boxes set levels out differently (`z_bot = bedLvl − wearC − tSB` vs `bedLvl − tSB`) — measured, not assumed.
- Views recompute what the engine computes: the half section draws the granular fill from `foundation.found_d`; the engine's `granBot` uses
  `foundation.sand_fill_depth` — confirmed by rendering the view with each perturbed.
- Some families' own defaults fail their own validation (e.g. the highway box: road level below top of slab).

## Trust, kept apart

| State | Meaning |
|---|---|
| `verified_by_execution` | a formula read from the source that agrees with the production code on every sampled model (16 per formula) |
| `constant_verified` | a fixed number the code returns |
| `opaque` | the source is not plain arithmetic (a conditional, a call): only its measured dependencies are known |
| units `authored` / `inferred_dimensional` / `unknown` | read from the source by a person (cited, citations checked automatically) / forced by a verified sum / not known: such a field cannot be bound |
| knowledge `fresh` / `stale` / `unverifiable` | the checkout's modules hash as recorded / one changed (listed) / no checkout and no matching bundle |
| an output `holds` / `differs` / `not_evaluable` | the production code on the drawing's values agrees with the drawing / does not / depends on a field the binding leaves to the production defaults (measured live, per field) |
| a validation message `decided_by_drawing` | every field the check read is bound; otherwise it names the defaults it used and is never a verdict on the drawing |

The production defaults are never taken as values of the drawing. Config (what the drawing states but its geometry cannot measure, e.g. a count)
needs its basis; an assumption needs why; both are carried into every result that depends on them.

## Guards

An output that **held** when the binding was accepted (on fresh knowledge, by the production code), and the engine's validation where the drawing's
own values decide it, become guards. Every regeneration of a unit the binding reads re-runs them; a change that breaks one is refused with
expected / measured and nothing changes. Measured on the benchmark: a plan applied to a section whose plan view is a unit of its own (it does not
follow) is refused (production total_w 6000 mm vs plan 7000 mm); the same plan with the views in projection is applied and still holds.

Note what a guard can and cannot catch: a production relation between quantities that are all measured on ONE chain of set-out lines is an
identity of the drawing (any closed drawing satisfies it). Guards bite where the drawing's quantities are independent of each other — across
units and views, on named design values, and in the engine's own threshold checks — and the binding's `structure` report says where a drawing
holds a production-derived quantity as independent (inverted dependency), with the exact relation to adopt (`proposals`, slopes measured by
running the production code; adopting it with `set_formulas` makes the drawing follow).

## The agent's tools (on with `--domain bridge`; the library's domain.json declares `production_knowledge`)

| Tool | Does |
|---|---|
| `production_families` | families, whether they run here, freshness, which ones the drawing's printed words point at (a lead; close calls said) |
| `production_knowledge` | one family, section by section (summary, parameters, outputs, views, operations, validation, findings), filtered, bounded |
| `check_production_model` | run the production code on the drawing's values; nothing kept |
| `bind_production_model` | keep it (sheet write, undoable); what held becomes a guard |
| `assess_change` | a change in production terms: parametric (the drawing value that drives it, and the value to plan) or topology change (not applied) |
| `validate_views` | per view: geometry, production relations, engine validation, cross-view, unresolved — from what ran, `unsupported` is not a pass |

## Topology changes

A change of count or option (a third cell, wing walls shown) is recognised from the knowledge (`operations`: `set_count`, `toggle`) and refused
before anything changes: the regeneration engine moves the entities a drawing already has and does not create or delete geometry. The
production model's numbers for the change (e.g. total_w 7000 → 10300 mm) are given so a person can decide how to redraw. Making such changes is
future work: it needs a feature operation that creates entities, which this engine deliberately does not have.

## Limits, said plainly

- Formulas are extracted only where the source is straight-line arithmetic; elsewhere only measured dependencies exist (PSC slab, OWG,
  composite girder and ROB are mostly loops and calls: 0–3 formulas each).
- Units are authored for the two RCC box families; elsewhere they are inferred where formulas force them, otherwise unknown (unbindable).
- Views are characterized only where the production renderer runs headless with the stand-ins the bridge provides.
- How well a *model* chooses families, bindings and plans is not measured here: that needs a live run (`agent-eval --live --yes-spend`).
