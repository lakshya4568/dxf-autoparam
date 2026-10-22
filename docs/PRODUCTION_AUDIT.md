# The production bridge system — a traceable map (aagento-bridge `e6c8f8fbe6`, read 2026-10-22)

What `../aagento-bridge/src/app/features/bridges` does, traced in its code for the family 173A belongs to (the **railway RCC box**), with the
other families' shape noted where it is the same. Every statement cites the file and line it was read from. Three kinds of knowledge are kept apart:

| Mark | Meaning |
|---|---|
| **read** | read in the source (a formula, a constant, a construction) |
| **verified** | read, and confirmed by RUNNING the production code on sampled models (`production extract`: 16 samples per formula, `verified_by_execution`) |
| **measured** | found by experiment: the production code run with one input changed (dependencies by perturbation; views rendered headless) — a relation, not a formula |

The machine-readable form is `src/dxf_autoparam/knowledge/production/<family>.json` (rule engine, outputs, verified formulas, view reads, validation,
findings; refresh with `production build && production extract`) and, for the components the rule engine does not compute,
`src/dxf_autoparam/knowledge/library/bridge/components.json` (parameters, relations, views, behaviour — read, each cited).

## 1. The pipeline

```
person ──► workspace panel (components/bridge-workspace/panels/rcc-box-params.ts) ── patchPath(M.…) ──┐
             • inputs: Clear Span, Box Height, Wearing Course, Side Wall, slabs, P.C.C. projection,       │
               haunch, cells, formation widths, levels, foundation …                                        │
             • DERIVED LINKS written back on every change (syncDependentParams, :419-460)                   ▼
                                                                                              the model M (metres)
mapper (utils/rcc-box-railway/rcc-box-mapper.ts) ── a bridge record → M (boxHeight → geometry.clear_h)      │
                                                                                                             ▼
rule engine RCCBoxRuleEngine.compute (rcc-box-rule-engine.ts) ── D: total_w, total_h, levels, BOQ ─────────────┤
rule engine .validate (rcc-box-rule-engine.ts:106-160) ── the VALIDATION panel's messages                       │
                                                                                                             ▼
views (utils/rcc-box-railway/*-view.ts): each builds its geometry in WORLD units (x metres from its own origin,
y = reduced level) and maps it to the canvas: wx = origin + x·scale, wy = bedY − (z − bedLvl)·scale
(rcc-box-half-section-view.ts:157-158, rcc-box-longitudinal-view.ts:143-144); dimensions print the model's numbers,
levels print "RL …" from the same values ─► scene renderer ─► canvas / DXF export (shared/rcc-box-dxf-export.ts)
```

The registry (`models/bridge-registry.ts:146-158`) wires each family: defaults, rule engine, scene renderer, workspace mapper, version mapper,
computed-levels mapper, initial scale and pan, view buttons, canvas base point. 13 keys today (`cad_preview` and `test_bridge_parametric` have left it).

## 2. Inputs (railway RCC box)

| Panel label | Model path | Default | Unit | Read by |
|---|---|---|---|---|
| Clear Span | `geometry.clear_w` | 5.000 | m | compute (total_w, flow area), half section, L-section, plan |
| Box Height H | `geometry.clear_h` | 3.331 | m | compute (total_h, levels), panel links — **the inside height from the top of the bottom slab to the soffit** |
| Clear Height H | — (derived) | | m | panel: `boxHeight − wearingCourse` |
| Wearing Course | `deck.wearing_course` | 0.150 | m | compute (z_bot), mapper, shear key view |
| Side Wall | `geometry.t_wall_o` (`t_wall_i` between cells) | 0.400 | m | compute (total_w), views |
| Top / Bot Slab Thick | `geometry.t_slab_t` / `t_slab_b` | 0.400 | m | compute, views; filled from an RDSO API (`rcc-box-params.ts:244-246`) |
| P.C.C. Projection | panel field | 0.150 | m | views |
| Haunch Size | `geometry.haunch_size` | 0.300 | m | views; derived from an RDSO table (`:357-373`) |
| No. of Cells | `project.cells` | 2 | – | compute (a count: topology) |
| Formation width Left / Right | `deck.formation_width_left/right` | 3.925 | m | barrel length (`:409-417`) |
| levels | `deck.formation_lvl`, `deck.rail_level`, `hydraulics.bed_lvl`, `hydraulics.hfl`, `hydraulics.soffit_level`, `hydraulics.scour_lvl` | | m RL | compute, levels mapper, views |
| foundation | `foundation.pcc_sub_base` 0.15, `foundation.sand_fill_depth` 0.7, `foundation.found_d` 0.85 | | m | compute (pccBot, granBot); the half section reads `found_d` |
| return wall | `geometry.rw_stem_top_thick`, `rw_stem_thick`, `rw_toe_width`, `rw_heel_width`, `rw_depth`, `rw_depth_sec`, `rw_depth_scour`, `rw_length`; `abutment.return_wall_type` (rcc / pcc / slanting) and `abutment.slanting_*` | `RCC_BOX_RW_PARAMS` | m | `getEffectiveRwParams(M)` (`rcc-box.constants.ts:22-140`) → L-section, retaining-wall (C/S) view, plan |
| toe wall | `geometry.toe_wall_{h, stem_thick, depth, base_thick, form_w_left/right, leveling_course_thick, lc_offset_left/right}` | 0.5 / 0.2 / 0.2 / 0.3 / 0.3 / 0.075 / 0.075 | m | toe-wall view |
| curtain / drop wall | `side.{curtain_d, base_height, left/right_offset, length_below_scour}`, `side.drop_*` | 0.4 / 0.3 / 0.3 / 1.8 | m | curtain-wall and drop-wall views |
| toggles | `options2d.show_return_wall`, `show_wing_wall`, `show_curtain_wall`, `show_drop_wall`, `show_coping`, `show_rmm_wall`, `show_l_shaped_wall`, `hide_left/right_return_wall` … | | – | views (a toggle adds or removes a component and its view) |

94 parameters in all (`railway_rcc_box.json` → `parameters`, 50 numeric).

## 3. Derived geometry — what follows when an input changes

**Rule engine, verified** (`rcc-box-rule-engine.ts` compute; `railway_rcc_box.json` → `outputs`, `verified_by_execution`):
`total_w = cW·cells + 2·tOW + tIW·(cells−1)` · `total_h = cH + tST + tSB` · `z_bot = bed − wearC − tSB` · `z_top = z_bot + total_h` ·
`soffit = z_top − tST` · `rccBoxTopLvl = bed − wearC + cH + tST` · `pccTop = z_bot` · `pccBot = z_bot − pccB` · `granBot = pccBot − sandFill` ·
`flow_area = cW·cH·cells` · `toeWallL = wingL + 0.082`; BOQ quantities for the shear key, return wall, toe wall, curtain walls, aprons, approach slab are
**constants** (`boq.retWallW = 3.2`, `boq.toeWallW = 0.8`, `boq.shearKeyW = 0.7` …) — the BOQ does not follow the components' drawn sizes.

**Panel links, read** (`components/bridge-workspace/panels/rcc-box-params.ts`) — the "box height moves the clear height" a person sees, hand-coded:

| Quantity | Formula | Line |
|---|---|---|
| Clear Height | `clear_h − wearing_course` | 375-380 |
| Soffit level | `bed_lvl + clear height` | 382-386 |
| Top of slab | `soffit + t_slab_t` | 388-392 |
| Earth cushion | `max(formation_lvl − top of slab, 0)`, written to `deck.earth_cushion` | 400-406, 429-435 |
| Barrel length | `formation_width_left + formation_width_right + 4 × earth cushion` (2H:1V each side), written to `project.span_length`, unless multi-bridge rules clip it | 409-417, 437-444 |
| Haunch size | RDSO band on `max(clear_w, clear_h)`: <3.0 → 0.200 … ≥6.0 → 0.600 | 357-373 |
| Slab / wall thickness | from an RDSO API, `getCulvertByState(cushion, w, h, code)` | 227-250, 446-458 |
| Toe wall stem bottom | `top + left slant + right slant` | 300-315 |

**Measured** (perturbation, `railway_rcc_box.json` → `outputs.*.depends_on`, `views.*.affected_by`): the soffit level does not depend on the top
slab (it cancels: `soffit = bed − wearC + cH`); the half section draws the granular fill from `foundation.found_d` while the engine's `granBot` uses
`foundation.sand_fill_depth` (a cross-view divergence: the two can disagree); fallback defaults differ between the engine and the half section
(`t_slab_b` 0.35 vs 0.400).

## 4. Components — how each is constructed (read; the details with every parameter are in `components.json`)

| Component | Construction | Anchored to | Views |
|---|---|---|---|
| box barrel | cells × clear span, walls, slabs, 45° haunches | bed level (z_bot = bed − wearC − tSB), the centre line | half section, L-section, plan |
| wearing course / PCC / granular fill | layers of constant thickness above / under the bottom slab | the bottom slab | half section, L-section, shear key |
| earth retainer | trapezium on the top slab at each barrel end: height 0.225, top 0.450, base 0.675 | top of slab, barrel end | L-section (`:1232-1246`), earth-retainer detail |
| return wall (rcc) | stem: outer face vertical (solid), inner face battered by `rw_stem_thick − rw_stem_top_thick` (dashed: hidden); footing: toe, heel, depth at the stem, a sloped top down to the edges; lean concrete 0.120 projecting 0.150; coping | footing bottom = scour level − `rw_depth_scour`; stem up to the top of the box; the barrel end (`x_para_out`) | L-section (`:1497-1700`), C/S of return wall (`rcc-box-retaining-wall-view.ts:96-260`), plan |
| toe wall | stem on a footing on a levelling course | ground / road level | toe-wall view, L-section, plan |
| shear key | a downward key under the bottom slab at a barrel end: total depth 1.200 from the slab top (`sk_depth = 1.200 − t_slab_b`), flat toe 0.225, slope run 0.450, PCC 0.150 | bottom of the box, the barrel end | shear-key view (`:173-260`), L-section (`:1145-1177` draws dowel walls) |
| curtain / drop wall | a cut-off wall below the scour level with a base block | scour level | curtain / drop views |

The SAME parameters appear in several views: the return wall's toe, heel, footing depths and stem in the L-section and in its own C/S; the earth
retainer in the L-section and its detail; the shear key in the L-section and its detail. In production one value drives every view (they read one M);
on a DXF they are separate drawings of one value — what `share_sizes` joins.

## 5. Views and their coordinate frames

Each view is a function of M drawing in its own world frame (x metres from the view's own origin — the centre line in a half section, the barrel's
start in the L-section; y = RL), mapped to the canvas by a scale and an origin. The UI shows one tab per view: HALF SECTION · LONGITUDINAL ELEVATION ·
PLAN TOP · RETAINING WALL · CURTAIN WALL · DROP WALL · TOE WALL · SHEAR KEY · EARTH RETAINER · BORE LOG · REINFORCEMENT · BBS · KEY PLAN. The view
modes in the knowledge: sec, elv, plan, rw, cw, drop, tw, sk, er, lfw, borelog, reinf, bbs, trough (`railway_rcc_box.json` → `views`; four of them are
switched by toggles). This is why a DXF view should open in its OWN local frame (real mm, levels as y): that is the frame its numbers were made in.

## 6. Validation coverage

`RCCBoxRuleEngine.validate` (`rcc-box-rule-engine.ts:106-160`) runs again (it was inside a block comment when the knowledge was first extracted; an
authored note said so — the extractor now drops a note the code contradicts and marks those rules as running): outer wall ≥ 0.3 m · top slab ≥ 0.3 m ·
clear height ≥ 1.0 m · HFL clearance · HFL below soffit · computed soffit = input soffit · earth cushion ≥ 75 mm (IRS) · haunch ≥ 300 mm · slab not
narrower than the box. At its own defaults it warns: `Computed soffit (99.498m) ≠ input (99.648m)`.

**Not validated anywhere:** every component outside the box: the return wall, toe wall, shear key, earth retainer, curtain / drop walls have no check
(their BOQ quantities are constants). A drawing can state a return wall footing narrower than its stem and production would not say so.

## 7. What dxf-autoparam takes from it, and what it did not (gap)

| Production knowledge | In dxf-autoparam | How the agent gets it |
|---|---|---|
| rule engine outputs and their formulas | `knowledge/production/<family>.json` (verified by execution) | `production_knowledge`, `check_production_model`, `bind_production_model` (domain pack on) |
| the engine's validation | the same, run on the drawing's own bound values (a message reading a production default is never a verdict) | `validate_views`, guards on bound outputs |
| view reads and their perturbation effects | the same (`views.*.affected_by`) | `production_knowledge(section: views)` |
| **component parameters read through helpers and constants** (`rw_*`, `toe_wall_*`, `side.curtain_*`, `RCC_BOX_RW_PARAMS`) | **missing until now** — no view record listed one | `components.json` (read, cited) → `coverage` attaches a part's card; `get_reference("component:…")` |
| **the panel's derived links** (clear height, cushion, barrel length, haunch table) | **missing until now** | `components.json` relations: hypotheses the agent checks on the drawing (`calculate`) and binds (`set_relation`, `set_formulas`) |
| which component a DXF part is | nothing in production (it never reads a drawing) | the part's name / type / labels matched to a card's names (`library.component_cards`) |

What production does that a DXF cannot carry: a change of COUNT (cells) or a toggle (a component appearing) rebuilds geometry; on an existing drawing
that is a topology change, said and not applied (`docs/PRODUCTION_RULES.md`).
