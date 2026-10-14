---
name: rcc_box-bridge-context
description: Use when a drawing shows a reinforced concrete box (culvert, road under bridge or limited-height subway, or box syphon) filed in the rcc_box dataset folder, to find its context records, their review state and their limits.
---

# rcc_box: context for box drawings

Everything here comes from repository files and the command output of ctx.py. Almost all of it is unreviewed. Nothing in this repository is human-verified, and binding of any dimension is blocked.

Terms used below:
- seed_unreviewed: written by a model or a seed process, not reviewed by a person.
- draft: written, not reviewed.
- proposed (category D): a suggestion, never accepted.
- grounded: a reading of the sheet exists and waits for review.
- picture_only: only the scan is recorded; no reading.
- binding: turning a written or drawn value into a model parameter.

## When to use this skill

Assumed mapping (a suggestion, as the brief states): dataset folder `rcc_box` -> `kb:kb.family.rcc_box` -> ontology family `rcc_box`. The folder README names the same KB entry (bridges/rcc_box/README.md). Box RUBs are filed here too: 37 of the 103 sheets have box_kind `rub`. Their KB family is `kb:kb.family.rub`; non-box RUBs are in the rub_other folder.

Recognise the family by:
- Printed words: "RCC BOX", "R.C.C. BOX", "RCC TWIN CELL BOX", "BOX CULVERT". Vector sheets print "RCC TWIN CELL BOX", "R.C.C BOX", "RCC BOX" and "RCC BOX (RUB)" (vector-pdfs/INDEX.md).
- Titles of RDSO box drawings quoted in the family record: "STANDARD DRAWING OF SINGLE BOX CULVERT", "STANDARD DRAWING OF DOUBLE BOX CULVERT", "TYPICAL DRAWING FOR CONSTRUCTION OF RUB/SUBWAY" (`kb:kb.family.rcc_box`, raw.sources).
- Views: plan at top and at foundation level, half elevation with the cell opening, longitudinal section with rail, formation and bed levels (`kb:kb.family.rcc_box`, raw.deep.drawing_conventions).
- Size notes written as "N x span x height", where N is the number of cells (`kb:kb.family.rcc_box`, raw.deep.drawing_conventions).

The family record has no aliases (its alias list is empty). Its printed name is "rcc_box"; its canonical name is "RCC box (railway / highway)".

Look-alikes (do not confuse):
- Slab bridge, `kb:kb.family.slab`: a slab sits on abutments. The family record says a box is one frame with its own bottom slab, with no abutments, piers or bearings under it.
- Arch on a box, `kb:phys.structure.arch_on_box` (ontology family `arch`). The family record says a box is "not an arch, even when an old arch is drawn beside it on an extension sheet".
- Pipe culvert, ontology family `pipe` (`kb:phys.structure.pipe_culvert`): pipes, not a box.
- Box syphon, `kb:phys.structure.box_syphon`: three syphon sheets are filed here (box_kind `syphon`). The family record says a box syphon is the form that carries a canal or drain under pressure.
- Road under bridge with a slab or girder deck: `kb:kb.family.rub` puts these in another folder.
- Misreadings listed in the record (`kb:kb.family.rcc_box`, raw.deep.common_misreadings): reading a haunch as a wall or outside chamfer; taking "N x span x height" as a span and a height when N is the cell count; taking the dotted outline of an old arch as part of the new box; treating an extension or reinforcement sheet as a complete bridge.

## Scope in this repository

- bridges/rcc_box (bridges/rcc_box/README.md): 97 bridges, 103 sheets. Whole 70, extension 33. Sub-kinds: culvert 63, RUB 37, syphon 3. Cells: single 95, twin 5, unknown 3. Permission to train: yes 53, unconfirmed 50.
- Coverage (agent-context/reports/coverage.md): 4 grounded_needs_review, 99 picture_only_ungrounded. Grounded here means a reading exists and waits for review. It is not verification.
- Held-out vector-PDF set (vector-pdfs/README.md): 49 rcc_box sheets under vector-pdfs/rcc_box. They are not in bridges/ and not in coverage.md, and the README says not to mix them into bridges/.
- Grounded examples (ctx.py status):
  - `2da8cb493f51-p1`: RE-SDLP BR.NO.5B RUB KM 88.4-5. Box RUB. One open dispute.
  - `21cc08a32dd8-p1`: N.W.R. BKN DIVL. PLAN, RUB plan number. Box RUB. Four open disputes.
  - `497aba2d74b7-p1`: N.W.R. BKN DIVL. PLAN, RUB plan number. Box RUB. One open dispute.
  - The fourth grounded sheet is `b37866af6f73-p1`, a culvert extension.

## What drawings of this family usually show

Component terms, with review state. Each record is seed_unreviewed unless marked draft.
- Whole box: `kb:phys.structure.rcc_box_culvert` (draft). One or more cells carrying track over a waterway. Ontology: `ontology:phys.structure.rcc_box_culvert`.
- Barrel: `kb:phys.component.box_barrel`. All cells, walls, slabs and haunches as one component.
- Cell: `kb:phys.space.cell_opening`. The clear opening of one cell; repeated per cell.
- Walls: `kb:phys.component.outer_wall`. `kb:phys.component.intermediate_wall` exists only when there is more than one cell.
- Slabs: `kb:phys.component.top_slab`, `kb:phys.component.bottom_slab`.
- Haunch: `kb:phys.subcomponent.haunch`. A triangular thickening at the slab-to-wall corner inside a cell. The legacy glossary names it "Haunch Chamfer Size" (knowledge/sources/engineering/bridge-formulas/08-glossary.txt, line 78). The two descriptions differ; see hazards.
- Ends and protection (all draft): `kb:phys.component.wing_wall`, `kb:phys.component.return_wall`, `kb:phys.component.curtain_wall`, `kb:phys.component.floor_apron`, `kb:phys.component.filter_media`.
- Box RUB parts: `kb:phys.structure.rcc_box_rub` (draft), `kb:phys.component.approach_road`, `kb:phys.space.road_headroom`, `kb:phys.component.weep_hole` (draft). The drawing label "LIMITED HEIGHT SUBWAY" maps to `rcc_box_rub` (`ontology:LIMITED HEIGHT SUBWAY`).
- Levels named by the family record: rail, formation, bed, soffit, top of slab, floor (`kb:kb.family.rcc_box`, raw.deep). The ontology lists required facts: cells, clear span, clear height, outer wall, top slab, bottom slab, mid wall when cells > 1, haunch, and one of bed, floor or soffit level (ontology/bridge-families.json).
- Parameter names seen on grounded sheets (`kb:kb.family.rcc_box`, raw.facts): clear width or box clear span, clear height, top and bottom slab thickness, outer wall thickness, haunch size, barrel length, segment length and count (precast), rail, formation and bed levels.
- Variants (`kb:kb.family.rcc_box`, raw.deep.variants): single cell; twin or multi cell; skew box; precast segmental box; culvert, road under bridge, limited-height subway, box syphon; extension as RCC box.
- Standard drawings (proposed, category D; not accepted): `kb:kb.standard_drawing.rdso_b_10151_r`, `kb:kb.standard_drawing.rdso_b_10153`, `kb:kb.standard_drawing.rdso_b_10154_r`, `kb:kb.standard_drawing.rdso_b_10168`, `kb:kb.standard_drawing.rdso_b_10171`. Several have an unmerged duplicate (proposal_status `unmerged:amends_existing_entry`).
- Not written in the repository, on purpose: standard clear spans, heights and fill depths. The family record's risk flags say to take them from the RDSO drawings, not from the entry.

## Formulas and rules for this family

These are candidates only. None is executable. A NORMATIVE label in a record is a label, not a check, because every record here is unreviewed.
- Derived geometry (category B, DERIVED): `kb:kb.formula.f_box_outside_width` (orthogonal box, equal cells, not skew); `kb:kb.formula.f_box_outside_width_1` (one cell); `kb:kb.formula.f_box_soffit`; `kb:kb.formula.f_box_soffit_from_bed`; `kb:kb.formula.f_box_top`; `kb:kb.formula.f_box_slab_bottom`.
- Definitions (category B, DERIVED): `kb:kb.formula.d_clear_height` and `kb:kb.formula.d_clear_height_from_bed`. Their datum is disputed in `kb:kb.conflict.kc_4`. `kb:kb.formula.d_cushion` depends on `kb:kb.conflict.kc_5` (earth cushion datum, disputed). `kb:kb.formula.d_top_slab` and `kb:kb.formula.d_bottom_slab` have no conflict record.
- Level order (category B, check): `kb:kb.rule.level_order_cover` (formation at or above the top of a buried box); `kb:kb.rule.level_order_slabs` (top of slab above soffit, above floor, above underside of the base slab).
- Culverts as pressure conduits (category B, evidence_status NORMATIVE): `kb:kb.rule.irbm_312_3_culvert_exempt` says syphons, pipe and box culverts need no vertical clearance. The family record says the opposite for a culvert box: "a culvert box does not hold a water head; only a syphon is designed to run under pressure" (`kb:kb.family.rcc_box`, raw.deep.what_it_does_not). Related dispute: `kb:kb.conflict.kc_15`. No conflict record links the two statements.
- Scour (category B, evidence_status NORMATIVE): `kb:kb.rule.irbm_402_culvert_scour` (not where the bed is likely to scour). The open-foundation depth is disputed in `kb:kb.conflict.kc_10`.
- Span and multi-cell approval (category B, REFERENCE_OBSERVED, quoted from a secondary source): `kb:kb.rule.ircm_box_span`; `kb:kb.rule.ircm_box_multi_cell`.
- Seismic (category B, evidence_status NORMATIVE): `kb:kb.rule.bs118_4_4_culvert_seismic`.
- Weep holes in wing and return walls (category B, evidence_status NORMATIVE, in dispute): `kb:kb.rule.irbm_207_3_weep_holes`. A proposal says no weep holes in new RUBs (`proposal:20261009-181438-learn-test-weep-hole:2`, category D). The dispute is `kb:kb.conflict.kc_12`.
- Other disputed box values (all DISPUTED): `kb:kb.conflict.kc_22` (minimum clear height of a box); `kb:kb.conflict.kc_3` (minimum haunch); `kb:kb.conflict.kc_2` (barrel length); `kb:kb.conflict.kc_1` (rail level minus formation level).
- Legacy software notes (not RDSO or IRBM text): `chunk:KB-BRIDGE-FORMULAS-01-RCC-BOX-RAILWAY:p1:4` (flow area) and `chunk:KB-BRIDGE-FORMULAS-01-RCC-BOX-RAILWAY:p1:6` (soffit level). They describe a rule-engine module and are unreviewed.
- Ontology level chain (ontology/bridge-families.json, chain.rcc_box): "invert + clear_height + top_slab + cushion = formation (railway)". Its definition file lies outside this repository and was not read.

## Known hazards for this family

- `issue:unresolved_disputes:2da8cb493f51-p1` (one dispute), `issue:unresolved_disputes:21cc08a32dd8-p1` (four), `issue:unresolved_disputes:497aba2d74b7-p1` (one). Example: `2da8cb493f51-p1#dispute0` sets a note "SIZE 4X4.5M" (a reinforcement drawing reference) against a title "1X4X4.00M R.C.C. BOX" and V1 dimensions 4.00 and 4.00. Binding stays blocked while disputes are open.
- `issue:audit_difference:21cc08a32dd8-p1`: the year part of the drawing number is read as 101 instead of 2011.
- `issue:needs_review:21cc08a32dd8-p1`, `issue:needs_review:2da8cb493f51-p1`, `issue:needs_review:497aba2d74b7-p1`, `issue:needs_review:b37866af6f73-p1`: filed but not reviewed.
- `issue:partial_grounding:2da8cb493f51-p1`, `issue:partial_grounding:497aba2d74b7-p1`, `issue:partial_grounding:b37866af6f73-p1`: the grounding has no entries for some kinds (absent parts, repeats, tables, disputes).
- Title conflicts in the vector set (filed as rcc_box, but the title names slab): `issue:title_conflicts_with_content:v-3ee4f1412e6e-p1` and `issue:title_conflicts_with_content:v-993a513ea007-p1` (RCC SLAB); `issue:title_conflicts_with_content:v-5b25c689e115-p1`, `issue:title_conflicts_with_content:v-62a9c04bc34e-p1`, `issue:title_conflicts_with_content:v-781273206fcb-p1` (PSC SLAB). The sheets print box words and no slab words; the issue says the title may be a stale template line.
- `issue:vocabulary_mismatch:637aaa70625c-p1`: a sheet filed under rcc_slab has a grounding that says rcc_box. This is the look-alike in the other direction.
- `issue:open_point:rdso-extract:RDSO-RCC-BOX-RDSO-B-10153-SERIES`: span height differs between two pages and one table row is unresolved.
- `issue:unverified_claim:rdso-extract:RDSO-RCC-BOX-10157-6TO-10157-10` (error): page 1 values were never read from a displayed image. Do not use them.
- `issue:component_index_missing:rdso-extract/component-index` and `issue:reinforcement_marks_in_component_index:agent/out/rdso-extract/_qa/COMPONENT_INDEX.md`: some RDSO index rows are reinforcement bar marks, not components.
- Dispute on pressure: the rule record and the GAD drafting checklist say box culverts are pressure conduits (knowledge/sources/engineering/bridge-formulas/17-gad-drafting-composition-checklists.txt, citing IRBM para 312(3)). The family record says a culvert box does not hold a water head. Report both; choose neither.
- Haunch: the glossary says "Haunch Chamfer Size"; the record says a triangular thickening inside a cell. The family record warns against reading a haunch as an outside chamfer.
- NORMATIVE labels cite the source id SRC-IRBM-2024 (for example `kb:kb.rule.irbm_312_3_culvert_exempt`). That source id does not resolve to a file in this repository. The book chunks use the id SRC-IRBM-24 (for example `chunk:SRC-IRBM-24:p63:3`); the repository does not say whether the two ids name the same manual.
- The family entry's proposal citation is one of seven family citations that do not resolve (`issue:unresolved_citation_origin:kb-file:family`). Its internal sheet link uses a "sheet:" prefix that the resolver does not accept; the bare record id does resolve.
- The README's open review items list `02b5df283486-p1`, `04a44b96ca41-p1` and `087150456848-p1`. Those sheets are filed under _unsorted and rcc_slab (bridges/_index/sheets.jsonl), not here. Do not read them as open items for this folder.
- The ontology crossing types for rcc_box are rail_over_water and road_over_water only. Box RUBs (rail over road) are not listed, so their route is `ontology:rub`.
- The vector set files sheets printed "RCC BOX (RUB)" under rub_other, while bridges/ files box RUBs under rcc_box. The two filing rules disagree. See the rub_other skill.

## Evidence to request before proposing anything

Run these first, from the repository root:
1. `.venv/bin/python agent-context/ctx.py evidence kb:kb.family.rcc_box` (the family record, its risk flags and raw fields).
2. `.venv/bin/python agent-context/ctx.py status <record_id>` (capability, issues, observation counts). Issue ids are listed here; `evidence` does not resolve them.
3. `.venv/bin/python agent-context/ctx.py search "<words the sheet prints>" --observations --owner <record_id>`. An empty query returns nothing. Then run `evidence <record_id>#<local id>` on each observation you rely on.
4. `.venv/bin/python agent-context/ctx.py search "<family words>" --category B C D --limit 25`, then `evidence` on every candidate id you cite.
5. `.venv/bin/python agent-context/ctx.py pack <record_id> --task source_evidence --no-write --print`. Other tasks: component_interpretation, dimension_binding, geometric_relationships. Use `--no-write`; do not write packs.
6. For RDSO documents: `evidence rdso-doc:<doc id>` (register entry, category B) and `evidence rdso-extract:<doc id>` (page readings, category A, read by eye).

## Permitted output

- Cite the record id for each claim. Say "the record reads ..." for printed text, and label every reading as a reading.
- Name a candidate family, with the reason: "candidate rcc_box, filed here; the title reads ...".
- List candidate components, rules and formulas by id, with review state, trust label and any conflict id. Mark each one as a candidate.
- Report issues by id and say what each one blocks.
- State gaps plainly, for example "no grounding entry for absent parts on 2da8cb493f51-p1".

## Blocked output

- Binding any dimension to a parameter. Binding is blocked for knowledge records, for picture-only sheets, and for any sheet with open disputes.
- Saying that anything is verified, correct, complete, approved or accepted. Nothing here is human-verified.
- Promoting a proposal (category D) to a rule or a value, or using a standard-drawing value as a fact.
- Giving standard spans, heights, cushions or fill depths from memory or from this file.
- Any geometry edit, CAD command or coordinate output.
- Use for training. Fine-tune eligibility is blocked: permission is unconfirmed for 50 sheets and no human labels exist.

## Abstain or ask for review when

- The title or printed type names another family (RCC SLAB, PSC SLAB, or RCC BOX (RUB) with a second type). See the five vector title conflicts above.
- The sheet has an open dispute (any sheet listed under unresolved_disputes).
- The sheet is picture_only (99 of 103 here). Then say only what the identity and print show, with no parts and no values.
- The classification is a placeholder: `issue:placeholder_reference:bridges-index/sheets.classification_ref` (277 sheets, all families). The real classification sits in catalog/gad_catalog.jsonl.
- The sheet is an extension (33 sheets), a reinforcement sheet, or a multi-drawing sheet. It shows part of a structure, not the whole bridge.
- The bridge number or km is not legible, or the classification is marked second look: `744c47b5ee98-p1`, `86557a0dc538-p1`, `854c078ea136-p1`, `3c0aec72ce94-p1`, `6bedb299e346-p1` (bridges/_index/review_queue.jsonl).
- Two sheets were merged into one bridge (`bridge:brg-5c2a050e78`, bridges/rcc_box/README.md). Confirm before using both.
- A written value conflicts with the linework, or the record and the ontology disagree (for example, the pressure-conduit rule).
- A value would come from an RDSO page that carries an open point.

## Sources used

Repository files read:
- ontology/bridge-families.json
- agent-context/reports/coverage.md; agent-context/reports/issues.md
- agent-context/registry/issues.jsonl; agent-context/registry/sources.jsonl; agent-context/registry/observations.jsonl; agent-context/knowledge/knowledge.jsonl (read to list the conflict records)
- bridges/rcc_box/README.md; bridges/_index/sheets.jsonl; bridges/_index/review_queue.jsonl
- vector-pdfs/README.md; vector-pdfs/INDEX.md
- knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/rcc-box.md (all sections)
- knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/special-and-existing.md (sections 1 to 10 and 20 to 30)
- knowledge/sources/engineering/bridge-formulas/01-rcc-box-railway.txt (header lines only)
- knowledge/sources/engineering/bridge-formulas/08-glossary.txt (box, cell and haunch lines; line 78)
- knowledge/sources/engineering/bridge-formulas/17-gad-drafting-composition-checklists.txt (lines 105 to 121)
- knowledge/sources/books/chunks/KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-RCC-BOX.jsonl

Ids cited (each checked, see the report):
- Family: kb:kb.family.rcc_box; kb:kb.family.rub; kb:kb.family.slab; ontology:rcc_box; ontology:rub
- Components: kb:phys.structure.rcc_box_culvert; ontology:phys.structure.rcc_box_culvert; kb:phys.component.box_barrel; kb:phys.space.cell_opening; kb:phys.component.outer_wall; kb:phys.component.intermediate_wall; kb:phys.component.top_slab; kb:phys.component.bottom_slab; kb:phys.subcomponent.haunch; kb:phys.component.wing_wall; kb:phys.component.return_wall; kb:phys.component.curtain_wall; kb:phys.component.floor_apron; kb:phys.component.filter_media; kb:phys.structure.rcc_box_rub; kb:phys.component.approach_road; kb:phys.space.road_headroom; kb:phys.component.weep_hole; ontology:LIMITED HEIGHT SUBWAY; kb:phys.structure.arch_on_box; kb:phys.structure.pipe_culvert; kb:phys.structure.box_syphon
- Standard drawings (proposed): kb:kb.standard_drawing.rdso_b_10151_r; kb:kb.standard_drawing.rdso_b_10153; kb:kb.standard_drawing.rdso_b_10154_r; kb:kb.standard_drawing.rdso_b_10168; kb:kb.standard_drawing.rdso_b_10171
- Formulas and rules: kb:kb.formula.f_box_outside_width; kb:kb.formula.f_box_outside_width_1; kb:kb.formula.f_box_soffit; kb:kb.formula.f_box_soffit_from_bed; kb:kb.formula.f_box_top; kb:kb.formula.f_box_slab_bottom; kb:kb.formula.d_clear_height; kb:kb.formula.d_clear_height_from_bed; kb:kb.formula.d_cushion; kb:kb.formula.d_top_slab; kb:kb.formula.d_bottom_slab; kb:kb.rule.level_order_cover; kb:kb.rule.level_order_slabs; kb:kb.rule.irbm_312_3_culvert_exempt; kb:kb.rule.irbm_402_culvert_scour; kb:kb.rule.ircm_box_span; kb:kb.rule.ircm_box_multi_cell; kb:kb.rule.bs118_4_4_culvert_seismic; kb:kb.rule.irbm_207_3_weep_holes; proposal:20261009-181438-learn-test-weep-hole:2
- Conflicts: kb:kb.conflict.kc_1; kb:kb.conflict.kc_2; kb:kb.conflict.kc_3; kb:kb.conflict.kc_4; kb:kb.conflict.kc_5; kb:kb.conflict.kc_10; kb:kb.conflict.kc_12; kb:kb.conflict.kc_15; kb:kb.conflict.kc_22
- Legacy notes: chunk:KB-BRIDGE-FORMULAS-01-RCC-BOX-RAILWAY:p1:4; chunk:KB-BRIDGE-FORMULAS-01-RCC-BOX-RAILWAY:p1:6
- IRBM book chunk (id naming only): chunk:SRC-IRBM-24:p63:3
- Engineering chunks: chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-RCC-BOX:p1:2; chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-RCC-BOX:p1:4; chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-RCC-BOX:p1:9; chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-RCC-BOX:p1:19; chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-RCC-BOX:p1:25; chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-RCC-BOX:p1:29
- Sheets: 2da8cb493f51-p1; 2da8cb493f51-p1#dispute0; 21cc08a32dd8-p1; 497aba2d74b7-p1; b37866af6f73-p1; 744c47b5ee98-p1; 86557a0dc538-p1; fc266679f828-p1; 854c078ea136-p1; 3c0aec72ce94-p1; 6bedb299e346-p1; 637aaa70625c-p1; v-3ee4f1412e6e-p1; v-993a513ea007-p1; v-5b25c689e115-p1; v-62a9c04bc34e-p1; v-781273206fcb-p1; 02b5df283486-p1; 04a44b96ca41-p1; 087150456848-p1
- Bridges: bridge:brg-5c2a050e78
- RDSO: rdso-doc:RDSO-RCC-BOX-10151R-SERIES; rdso-extract:RDSO-RCC-BOX-RDSO-B-10153-SERIES; rdso-extract:RDSO-RCC-BOX-10157-6TO-10157-10
- Issues (checked against agent-context/registry/issues.jsonl, since `evidence` does not resolve issue ids): issue:unresolved_disputes:2da8cb493f51-p1; issue:unresolved_disputes:21cc08a32dd8-p1; issue:unresolved_disputes:497aba2d74b7-p1; issue:audit_difference:21cc08a32dd8-p1; issue:needs_review:21cc08a32dd8-p1; issue:needs_review:2da8cb493f51-p1; issue:needs_review:497aba2d74b7-p1; issue:needs_review:b37866af6f73-p1; issue:partial_grounding:2da8cb493f51-p1; issue:partial_grounding:497aba2d74b7-p1; issue:partial_grounding:b37866af6f73-p1; issue:title_conflicts_with_content:v-3ee4f1412e6e-p1; issue:title_conflicts_with_content:v-993a513ea007-p1; issue:title_conflicts_with_content:v-5b25c689e115-p1; issue:title_conflicts_with_content:v-62a9c04bc34e-p1; issue:title_conflicts_with_content:v-781273206fcb-p1; issue:vocabulary_mismatch:637aaa70625c-p1; issue:open_point:rdso-extract:RDSO-RCC-BOX-RDSO-B-10153-SERIES; issue:unverified_claim:rdso-extract:RDSO-RCC-BOX-10157-6TO-10157-10; issue:component_index_missing:rdso-extract/component-index; issue:reinforcement_marks_in_component_index:agent/out/rdso-extract/_qa/COMPONENT_INDEX.md; issue:unresolved_citation_origin:kb-file:family; issue:placeholder_reference:bridges-index/sheets.classification_ref
