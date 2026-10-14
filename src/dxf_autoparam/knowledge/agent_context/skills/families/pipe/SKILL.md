---
name: pipe-bridge-context
description: Use when a drawing shows circular pipe culverts under an embankment (family pipe, dataset folder bridges/pipe), before reading its components, levels, rules or open issues.
---

# Pipe culvert (dataset folder `pipe`)

This file gathers what the repository holds about pipe culverts. Every item is context, not fact. No record in the repository is human-verified, and binding of any dimension is blocked.

**Assumed mapping (a suggestion, not an authority):** dataset folder `pipe` -> `kb:kb.family.pipe` -> ontology family `pipe`.

## When to use this skill

- The sheet is filed under family `pipe`, or it shows one or more circular pipes under fill, with headwalls or wing walls.
- Words that identify the family: the KB family entry lists no aliases (`names.aliases` is empty). Its printed name is `pipe`. Its canonical name is "Pipe culvert (hume / NP3 / NP4)" (`kb:kb.family.pipe`). Related terms: "Hume / spun concrete pipe" (`kb:kb.material.hume`) and "Pipe culvert" (`kb:phys.structure.pipe_culvert`).
- The class letters NP3 and NP4 appear in that canonical name and in the entry's description ("drawings carry class letters such as NP3 or NP4"). The entry flags them as not re-checked against the pipe standard (`kb:kb.family.pipe`, risk flags).
- Look-alikes:
  - A box culvert (`rcc_box`). The KB says a pipe is a "circular precast barrel instead of a rectangular frame" (`kb:kb.family.pipe`, relation to `kb:kb.family.rcc_box`).
  - An extension of an existing pipe. The entry warns against "taking the existing pipe on an extension sheet as the new work". It also says an extension of an existing pipe as a box belongs to the box family. Both are unreviewed KB statements.
  - A box pushed under track. A box carrying track over a road is `kb:phys.structure.rcc_box_rub` (draft). A pipe pushed or micro-tunnelled under track is a separate variant, tied in the KB to RDSO guideline BS-134.

## Scope in this repository

- Sheets: 27 (`agent-context/reports/coverage.md`): 4 at capability `grounded_needs_review`, 23 at `picture_only_ungrounded`.
- Dataset (`bridges/pipe/README.md`): 27 bridges. Whole 0, extension 0, unknown 27. Sources: zonal 24, resdlp 3.
- Grounded examples (from `ctx.py status`; all carry classification `filed_in_catalog+placeholder_reference`):
  - `418834d8e9df-p1` (bridge `brg-89da4faada`)
  - `d66500a59b48-p1` (bridge `brg-fdef3914a7`)
  - `e60a63078d1d-p1` (bridge `brg-c6a308b90c`)
  - A fourth, `e19240b45b96-p1` (bridge `brg-95cf646d2d`), has the same capability.

## What drawings of this family usually show

- Views, as the KB describes them (`kb:kb.family.pipe`, `view_appearance`; unreviewed): in cross section, a circle for each pipe in its bedding; in the longitudinal section, the barrel with bedding, cover and invert levels; in elevation, the headwall with circular openings; in plan, the barrel and wing walls, with the headwall footing at foundation level.
- Ontology (`ontology/bridge-families.json`, family `pipe`): views `section` only. Primary components: `pipe`, `courses`, `earth_fill`, `wing_wall`, `datum`. Of these, `courses`, `earth_fill` and `datum` are plain words, not ids in the component list.
- Required facts (ontology): pipe diameter; pipe thickness; pipe spacing when there is more than one pipe; bed level or floor level (invert).
- Engineering text (`knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/pipe-culvert.md`, section 4 "Structural Components"): pipe barrel, bedding, headwall, wing or return wall, collar joint, protection, fill and track. This is an unreviewed research text.

Component candidates (KB ids; ontology ids with the same name exist for each):

| Class | KB id | Review state |
|---|---|---|
| Structure | `kb:phys.structure.pipe_culvert` | seed_unreviewed |
| Barrel | `kb:phys.component.pipe_barrel` | seed_unreviewed |
| Bedding | `kb:phys.component.pipe_bedding` | seed_unreviewed |
| Headwall | `kb:phys.component.headwall` | seed_unreviewed |
| Wing wall | `kb:phys.component.wing_wall` | draft |
| Drop wall | `kb:phys.component.drop_wall` | seed_unreviewed |
| Toe wall | `kb:phys.component.toe_wall` | draft |
| Curtain wall | `kb:phys.component.curtain_wall` | draft |
| Levelling course | `kb:phys.component.levelling_course` | draft |
| Rubble soling | `kb:phys.component.rubble_soling` | seed_unreviewed |
| Embankment | `kb:phys.component.embankment` | seed_unreviewed |
| Earth cushion | `kb:phys.component.earth_cushion` | seed_unreviewed |
| Crown (level reference, pipe or arch) | `kb:phys.feature.crown` | seed_unreviewed |

The KB describes the 27 pipe sheets as a sample of the dataset, not a census (`kb:kb.family.pipe`, facts).

## Formulas and rules for this family

Nothing below is executable. The labels are as recorded. NORMATIVE on a seed_unreviewed record is a label, not verification.

Rules (each record's applicability includes `pipe`):
- `kb:kb.rule.irbm_402_culvert_scour`: NORMATIVE, seed_unreviewed. Pipe and box culverts should not normally be provided where the bed is likely to scour. No conflict link.
- `kb:kb.rule.irbm_312_3_culvert_exempt`: NORMATIVE, seed_unreviewed. Pipe and box culverts are pressure conduits; no vertical clearance. No conflict link.
- `kb:kb.rule.bs118_4_4_culvert_seismic`: NORMATIVE, seed_unreviewed. Box and pipe culverts need not be analysed for seismic forces. No conflict link.
- `kb:kb.rule.irbm_313_free_board`: NORMATIVE, seed_unreviewed, relaxable. Free board from the design water level. Conflict: `kb:kb.conflict.kc_6` (DISPUTED).
- `kb:kb.rule.know_cushion_minimum`: UNKNOWN, seed_unreviewed. Minimum earth cushion; the record gives no value. Conflict: `kb:kb.conflict.kc_5` (DISPUTED).
- `kb:kb.rule.level_order_cover`: DERIVED, seed_unreviewed. Formation not below the top of a buried structure. No conflict link.
- `kb:kb.rule.level_order_slabs`: DERIVED, seed_unreviewed. Level order of top, soffit, floor and underside. No conflict link.
- `kb:kb.rule.track_rail_over_formation`: ASSUMPTION, seed_unreviewed. Rail over formation depends on rail, sleeper and ballast; the record calls its common value an assumption, not a rule. Conflict: `kb:kb.conflict.kc_1` (DISPUTED).
- `kb:kb.rule.irbm_207_3_weep_holes`: NORMATIVE, seed_unreviewed. Weep hole spacing and placement. No conflict link.
- `kb:kb.rule.irbm_301_3_skew`: NORMATIVE, seed_unreviewed. An advisory skew limit. No conflict link.
- `kb:kb.rule.irbm_605_3_boulder_backing`: NORMATIVE, seed_unreviewed. Boulder filling behind abutments and wing walls. No conflict link.

Formulas (each record is marked as not executed):
- `kb:kb.formula.f_pipe_top`: DERIVED. Top level = soffit level plus pipe thickness.
- `kb:kb.formula.f_pipe_soffit`: DERIVED. Soffit level = floor level plus pipe diameter.
- `kb:kb.formula.f_pipe_outside_invert`: DERIVED. Slab bottom level = floor level minus pipe thickness.
- `kb:kb.formula.f_floor_at_bed`: DERIVED. Floor level = bed level, where the bed level marks the floor of the cells or a pipe's invert.
- `kb:kb.formula.d_cushion`: DERIVED. Cushion = formation level minus top of structure, when the fill datum is not settled. Conflict: `kb:kb.conflict.kc_5`.
- `kb:kb.formula.hpc_geo_003`: UNKNOWN. The record says an added constant in the culvert width is unexplained.
- Ontology level chain (`ontology:pipe`, `level_chain`): "invert + diameter + 2×wall + cushion = formation", status `from_knowledge_layer`. Its definition source is `aagento-bridge/knowledge/formulas.json#chains`, which is not a file in this repository.

## Known hazards for this family

- Arithmetic disagreement on `d66500a59b48-p1`: `issue:failed_check:d66500a59b48-p1`. The grounding recorded it; it is not resolved.
- Open written-versus-drawn disputes: `issue:unresolved_disputes:d66500a59b48-p1` and `issue:unresolved_disputes:e60a63078d1d-p1`. Keep both values and leave the dispute open.
- All four grounded pipe sheets still need review: `issue:needs_review:418834d8e9df-p1`, `issue:needs_review:e19240b45b96-p1`, `issue:needs_review:e60a63078d1d-p1`, `issue:needs_review:d66500a59b48-p1`. The grounding also has gaps, for example `issue:partial_grounding:418834d8e9df-p1`.
- Classification pointer is a placeholder: `issue:placeholder_reference:bridges-index/sheets.classification_ref` (277 sheets repository-wide). The classification itself is in `catalog/gad_catalog.jsonl`.
- The sources name the pipe standard differently, and none is settled here. The KB name uses NP3 and NP4 (flagged, not re-checked). A research note says "IRS-class RCC pipes only" and gives its own status as INSUFFICIENT SOURCE (`chunk:KB-CLAUDE-RESERACH:p1:17`). The formula index names "IRS, IS:458" (`chunk:KB-BRIDGE-FORMULAS-INDEX:p1:6`). The hume formula source it names, `hume-pipe-rule-engine.ts`, is not in this repository.
- Existing or new, and whole or extension, cannot be read from the dataset: all 27 pipe sheets are "unknown" (`bridges/pipe/README.md`).
- Capability limit: the generator is tested on synthetic cases only. Headwalls, collars and splayed wings are not constructed (`ontology:pipe`, capability_note).
- The text lists its own gaps: minimum cushion not extracted; pipe class and joint schedule absent; spacing and headwall dimensions absent (`bridge-families/pipe-culvert.md`, section 27).
- The family entry is a draft. `proposal:20261009-143333-E2_family_entries:4` amends `kb:kb.family.pipe`, is waiting for owner review, and is never merged automatically (`agent-context/reports/issues.md`, section proposal_not_merged). The entry's citation of that proposal does not resolve.
- Eight pipe sheets have a bridge number or km that is not fully legible (`bridges/pipe/README.md`, open review items).

## Evidence to request before proposing anything

1. `.venv/bin/python agent-context/ctx.py status <record_id>`: capability, eligibility, issues and classification.
2. `.venv/bin/python agent-context/ctx.py evidence kb:kb.family.pipe` and `.venv/bin/python agent-context/ctx.py evidence ontology:pipe`.
3. `.venv/bin/python agent-context/ctx.py search "<words>" --observations --owner <record_id>`: what the sheet itself shows (text, dimensions, levels).
4. `.venv/bin/python agent-context/ctx.py pack <record_id> --task source_evidence --no-write --print`. Use `--no-write`; do not write packs in this task.
5. For rules and formulas: `.venv/bin/python agent-context/ctx.py search "pipe culvert rule formula" --category B D --topic formula rule`.
6. `ctx.py evidence` does not resolve issue ids. Check an issue in the `status` output of the sheet that carries it, or in `agent-context/reports/issues.md`.

## Permitted output

- The record id, its family, capability and eligibility, as `status` reports them.
- A reading of the sheet, labelled as a reading ("the record reads a circular pipe in the section"), with its observation id.
- KB component candidates, with ids and review state.
- Rule and formula candidates with their trust labels, any `kb.conflict.*` link, and the words "candidate, not executable".
- Open issues and disputes by id, and the evidence that is missing.

## Blocked output

- Binding any written dimension to a parameter slot. Binding is blocked: `blocked:knowledge_does_not_establish_project_dimensions` on the KB records, and `blocked:not_a_value_observation` on the sheets.
- Claims of verification. No record here is verified, and no sheet has `human_verified` set. Do not write "verified", "validated", "checked", "passes" or "correct".
- Treating a NORMATIVE label on a seed_unreviewed record as settled. Treating a DISPUTED, UNKNOWN or ASSUMPTION item as accepted.
- Promoting a proposal (for example `proposal:20261009-143333-E2_family_entries:4`) or a draft entry into the KB.
- Executing a formula, or presenting the ontology level chain as a computed result.
- Editing geometry, or using a sheet for fine-tuning (`finetune` is blocked: permission unconfirmed).
- Choosing between a written value and a drawn value. Keep both.

## Abstain or ask for review when

- The title or a printed word names another family, for example RCC BOX, RUB, PSC SLAB or GIRDER.
- The sheet shows an extension of an existing structure, or it cannot be read whether the pipe is existing or new.
- `issue:failed_check` or `issue:unresolved_disputes` is open for the record.
- The record is `picture_only_ungrounded` (23 of the 27 pipe sheets).
- The question concerns minimum cushion, scour, seismic action or free board. Those rules are unknown, disputed, or not yet checked against the source.
- The sheet names a pipe class or standard (NP3, NP4, IRS, IS:458). The sources disagree on it.

## Sources used

Files (repository paths; all unreviewed research texts or generated reports unless stated):
- `knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/pipe-culvert.md`: sections 1, 4, 21, 27, 30.
- `knowledge/sources/rdso/raw/bs-reports/BS-134.pdf` (cited by `kb:kb.family.pipe`; not opened).
- `knowledge/sources/books/chunks/KB-CLAUDE-RESERACH.jsonl` (chunk `p1:17`).
- `knowledge/sources/books/chunks/KB-BRIDGE-FORMULAS-INDEX.jsonl` (chunk `p1:6`).
- `ontology/bridge-families.json` (family `pipe`); the family, formula, rule, conflict and component records under `knowledge/kb/entries/` (read through `ctx.py`).
- `agent-context/reports/coverage.md`, `agent-context/reports/issues.md`, `bridges/pipe/README.md`.

IDs cited (verified with `ctx.py evidence`, except issue ids, which were checked in `status` output or in `issues.md`):
- Family and ontology: `kb:kb.family.pipe`, `kb:kb.family.rcc_box`, `kb:kb.material.hume`, `ontology:pipe`.
- Structure and components: `kb:phys.structure.pipe_culvert`, `kb:phys.structure.rcc_box_rub`, `kb:phys.component.pipe_barrel`, `kb:phys.component.pipe_bedding`, `kb:phys.component.headwall`, `kb:phys.component.wing_wall`, `kb:phys.component.drop_wall`, `kb:phys.component.toe_wall`, `kb:phys.component.curtain_wall`, `kb:phys.component.levelling_course`, `kb:phys.component.rubble_soling`, `kb:phys.component.embankment`, `kb:phys.component.earth_cushion`, `kb:phys.feature.crown`.
- Rules: `kb:kb.rule.irbm_402_culvert_scour`, `kb:kb.rule.irbm_312_3_culvert_exempt`, `kb:kb.rule.bs118_4_4_culvert_seismic`, `kb:kb.rule.irbm_313_free_board`, `kb:kb.rule.know_cushion_minimum`, `kb:kb.rule.level_order_cover`, `kb:kb.rule.level_order_slabs`, `kb:kb.rule.track_rail_over_formation`, `kb:kb.rule.irbm_207_3_weep_holes`, `kb:kb.rule.irbm_301_3_skew`, `kb:kb.rule.irbm_605_3_boulder_backing`.
- Formulas: `kb:kb.formula.f_pipe_top`, `kb:kb.formula.f_pipe_soffit`, `kb:kb.formula.f_pipe_outside_invert`, `kb:kb.formula.f_floor_at_bed`, `kb:kb.formula.d_cushion`, `kb:kb.formula.hpc_geo_003`.
- Conflicts: `kb:kb.conflict.kc_1`, `kb:kb.conflict.kc_5`, `kb:kb.conflict.kc_6`.
- Book chunks: `chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-PIPE-CULVERT:p1:5`, `chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-PIPE-CULVERT:p1:29`, `chunk:KB-CLAUDE-RESERACH:p1:17`, `chunk:KB-BRIDGE-FORMULAS-INDEX:p1:6`.
- Proposal: `proposal:20261009-143333-E2_family_entries:4`.
- Issues (`issue:<kind>:<subject>`): `issue:failed_check:d66500a59b48-p1`, `issue:unresolved_disputes:d66500a59b48-p1`, `issue:unresolved_disputes:e60a63078d1d-p1`, `issue:needs_review:418834d8e9df-p1`, `issue:needs_review:e19240b45b96-p1`, `issue:needs_review:e60a63078d1d-p1`, `issue:needs_review:d66500a59b48-p1`, `issue:partial_grounding:418834d8e9df-p1`, `issue:placeholder_reference:bridges-index/sheets.classification_ref`.
- Sheets (grounded examples, checked with `ctx.py status`): `418834d8e9df-p1`, `e19240b45b96-p1`, `d66500a59b48-p1`, `e60a63078d1d-p1`.
