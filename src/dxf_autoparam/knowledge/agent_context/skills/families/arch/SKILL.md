---
name: arch-bridge-context
description: Use when a drawing shows a curved arch barrel, masonry or concrete, springing from abutments or piers with fill over it (family arch, dataset folder bridges/arch), before reading its levels, rules or open issues.
---

# Arch bridge (dataset folder `arch`)

Context only. No record in the repository is human-verified, and binding of any dimension is blocked.

**Assumed mapping (a suggestion, not an authority):** dataset folder `arch` -> `kb:kb.family.arch` -> ontology family `arch`.

## When to use this skill

- The sheet is filed under family `arch`, or it shows a curved barrel springing from abutments or piers, with spandrel walls and fill over the crown.
- Words that identify the family: the KB family entry lists no aliases. Its printed name is `arch`. Its canonical name is "Arch (masonry arch; arch-soffit box)" (`kb:kb.family.arch`). The teaching card reads: "A bridge whose span is formed by a curved ring in compression, usually masonry or concrete" (`teach:arch-bridge`). Structure types: `kb:phys.structure.arch_bridge` and `kb:phys.structure.arch_on_box`.
- The canonical name says "arch-soffit box", and the ontology reuses box parameters for the arch family (cells, skew, gap between boxes). A box with an arch soffit is a close look-alike.
- Look-alikes:
  - A box culvert or box bridge. The KB says "arch works by thrust, box by frame bending" (`kb:kb.family.arch`, relation to `kb:kb.family.rcc_box`). An arch over a box is recorded as `arch_on_box`.
  - An arch on an extension sheet. The KB warns against "forgetting that the arch is the existing structure on an extension sheet". It also says that when the title reads "existing arch extended as a box", the drawing shows both, and the box is the new work. Both are unreviewed KB statements.
  - An arch soffit read as the top of a box. The KB lists this as a common misreading.

## Scope in this repository

- Sheets: 11 (`agent-context/reports/coverage.md`): 2 at capability `grounded_needs_review`, 9 at `picture_only_ungrounded`.
- Dataset (`bridges/arch/README.md`): 11 bridges. Whole 0, extension 0, unknown 11. Sources: zonal 11. Permission to train: unconfirmed 11.
- Grounded examples (from `ctx.py status`; both carry classification `filed_in_catalog+placeholder_reference`):
  - `9de9340947eb-p1` (bridge `brg-901d51d275`)
  - `a41a23a85b5e-p1` (bridge `brg-9dad58ecd4`)

## What drawings of this family usually show

- Views, as the KB describes them (`kb:kb.family.arch`, `view_appearance`; unreviewed): in elevation, the arch ring with springing and crown levels, spandrel walls and parapet; in cross section, the arch with spandrel walls, cut and hatched; in longitudinal section, the barrel cut with fill over the crown; in plan, barrel width with spandrel and wing walls, and the footings of abutments and wing walls at foundation level.
- Ontology (`ontology/bridge-families.json`, family `arch`): views `elevation` only. Primary components: `arch`, `abutment`, `datum` (plain words, not component ids). Required facts: clear span; rise (the label says "no construction reads it yet"); springing level.
- Engineering text (`knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/arch-bridge.md`, section 4 "Structural Components"): arch barrel, intrados, extrados, spandrel or fill, abutment, wing wall, foundation, protection, track. Unreviewed research text. The book chunk with the same list is `chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-ARCH-BRIDGE:p1:5`. Its machine summary gives the status PARTIAL (`chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-ARCH-BRIDGE:p1:31`).
- The KB says that on the dataset's arch sheets the arch is usually the existing structure, and the new work is a box beside it. It also says most arches in the sample are old masonry (`kb:kb.family.arch`, risk flag: from the sample, not a census).

Component candidates (KB ids; ontology ids with the same names exist):

| Class | KB id | Review state |
|---|---|---|
| Structure | `kb:phys.structure.arch_bridge` | seed_unreviewed |
| Structure, arch on box | `kb:phys.structure.arch_on_box` | seed_unreviewed |
| Barrel | `kb:phys.component.arch_barrel` | draft |
| Spandrel wall | `kb:phys.component.spandrel_wall` | seed_unreviewed |
| Abutment | `kb:phys.component.abutment` | draft |
| Parapet | `kb:phys.component.parapet` | draft |
| Return wall | `kb:phys.component.return_wall` | draft |
| Footing | `kb:phys.component.footing` | draft |
| Weep hole | `kb:phys.component.weep_hole` | draft |
| Haunch | `kb:phys.subcomponent.haunch` | seed_unreviewed |
| Sand filling | `kb:phys.component.sand_filling` | seed_unreviewed |
| Springing (level reference) | `kb:phys.feature.springing` | seed_unreviewed |
| Crown (level reference) | `kb:phys.feature.crown` | seed_unreviewed |

## Formulas and rules for this family

Nothing below is executable. The labels are as recorded. NORMATIVE on a seed_unreviewed record is a label, not verification.

- `kb:kb.rule.irbm_312_2_arch_clearance`: NORMATIVE, seed_unreviewed. Clearance to the crown of the intrados, banded by span. No conflict link recorded. The engineering text gives the same rule as ARCH-CLR-001, status NORMATIVE, citing IRBM-2024 section 312(2), with the note "verify later ACS before issue" (`bridge-families/arch-bridge.md`, section 8).
- `kb:kb.rule.bs118_4_3_arch_seismic`: DISPUTED, seed_unreviewed. Masonry and plain concrete arches over a stated span are not built in seismic zones IV and V. The record notes that the 2020 code is not in hand and may differ. Conflict: `kb:kb.conflict.kc_17` (DISPUTED, "Seismic exemption and arch limits wording"). Do not present it as accepted.
- `kb:kb.rule.irbm_311_3_clear_span`: NORMATIVE, seed_unreviewed. Minimum clear span. No conflict link.
- `kb:kb.rule.irbm_311_3_headroom`: NORMATIVE, seed_unreviewed, relaxable. Minimum headroom. Recorded applicability: arch only. No conflict link.
- `kb:kb.rule.irbm_313_free_board`: NORMATIVE, seed_unreviewed, relaxable. Free board from the design water level. Conflict: `kb:kb.conflict.kc_6` (DISPUTED).
- `kb:kb.rule.irbm_403_2_open_foundation_depth`: NORMATIVE, seed_unreviewed. Open foundation depth below the scoured bed, for ordinary soil. No conflict link.
- `kb:kb.rule.irbm_301_3_skew`: NORMATIVE, seed_unreviewed. An advisory skew limit. No conflict link.
- `kb:kb.rule.track_rail_over_formation`: ASSUMPTION, seed_unreviewed. Rail over formation; the record calls its common value an assumption, not a rule. Conflict: `kb:kb.conflict.kc_1` (DISPUTED).
- `kb:kb.formula.d_clearance`: COMMON_PRACTICE, seed_unreviewed. Clearance is soffit level minus HFL where drawings write the clearance against the HFL. The record notes that IRBM 312 measures clearance from the design-discharge water level, including afflux. Conflict: `kb:kb.conflict.kc_6`.
- The arch level chain is "to_define" in both the KB and the ontology (`ontology:arch`, level_chain): springing plus rise gives the crown (intrados); crown plus ring plus fill gives formation. It is a summary, not a computed chain.

## Known hazards for this family

- `kb:kb.rule.bs118_4_3_arch_seismic` is DISPUTED: `issue:disputed_knowledge:kb:kb.rule.bs118_4_3_arch_seismic` (the sources disagree; see the conflict).
- Both grounded arch sheets still need review: `issue:needs_review:9de9340947eb-p1` and `issue:needs_review:a41a23a85b5e-p1`. Both have partial grounding: `issue:partial_grounding:9de9340947eb-p1` (no entries for repeats, disputes, tables) and `issue:partial_grounding:a41a23a85b5e-p1` (no entries for repeats, relations, parameters, disputes, absent, tables).
- Classification review: three arch sheets are marked "second look", which asks whether the family and structure type are right. They are `71faa23ab6a2-p1` (bridge `brg-3291cb8add`), `9de9340947eb-p1` (grounded example) and `a41a23a85b5e-p1` (grounded example) (`bridges/arch/README.md`, open review items).
- Three arch sheets have a bridge number or km that is not fully legible: `a41a23a85b5e-p1`, `4b17c610275f-p1` and `272180db4517-p1` (`bridges/arch/README.md`).
- The ontology's capability note says there is "no construction mechanism for an arch barrel" and that the family is "never reported as validated" (`ontology:arch`, capability_note). The research note on arches gives its status as "INSUFFICIENT SOURCE for geometry" (`chunk:KB-CLAUDE-RESERACH:p1:18`).
- The engineering text lists its own gaps: permitted curve construction not extracted; barrel sizing absent; skew arch geometric rules absent (`bridge-families/arch-bridge.md`, section 27).
- The ontology's arch parameter slots for cells and skew use the box classes `phys.structure.rcc_box_culvert`. Read them as box slots on an arch-on-box record, not as arch values.
- The family entry is a draft. `proposal:20261009-143333-E2_family_entries:6` amends `kb:kb.family.arch`, is waiting for owner review, and is never merged automatically (`agent-context/reports/issues.md`, section proposal_not_merged). The entry's citation of that proposal does not resolve.
- `bridges/arch/README.md` lists load-test reports and a load-testing circular as governing documents. They were not read for this file, so this file gives no basis for any capacity or loading statement.

## Evidence to request before proposing anything

1. `.venv/bin/python agent-context/ctx.py status <record_id>`: capability, eligibility, issues and classification.
2. `.venv/bin/python agent-context/ctx.py evidence kb:kb.family.arch` and `.venv/bin/python agent-context/ctx.py evidence ontology:arch`.
3. `.venv/bin/python agent-context/ctx.py search "<words>" --observations --owner <record_id>`: what the sheet itself shows (springing, crown, rise, clear span, levels).
4. `.venv/bin/python agent-context/ctx.py pack <record_id> --task source_evidence --no-write --print`. Use `--no-write`.
5. For rules: `.venv/bin/python agent-context/ctx.py search "arch clearance rule formula" --category B D --topic formula rule`.
6. Before any statement about dimensions of a standard arch, read the standard drawing `knowledge/sources/rdso/raw/arch-bridge/10298.pdf`. Before any statement about strength or loading, read the load-test reports listed in `bridges/arch/README.md`.
7. `ctx.py evidence` does not resolve issue ids. Check an issue in the `status` output of the sheet that carries it, or in `agent-context/reports/issues.md`.

## Permitted output

- The record id, its family, capability and eligibility, as `status` reports them.
- A reading of the sheet, labelled as a reading, with its observation id.
- KB component and rule candidates with ids, review state and any conflict link, marked "candidate, not executable".
- Open issues and disputes by id, and the evidence that is missing.

## Blocked output

- Binding any written dimension (clear span, rise, springing level, thickness) to a parameter slot. Binding is blocked on the KB records (`blocked:knowledge_does_not_establish_project_dimensions`) and on the sheets (`blocked:not_a_value_observation`).
- Verification or validation claims. The arch family is never reported as validated.
- Presenting `kb:kb.rule.bs118_4_3_arch_seismic` as accepted, or reading its wording as settled.
- Any capacity, loading or seismic result drawn from this file.
- Promoting `proposal:20261009-143333-E2_family_entries:6`.
- Computing the clearance or the level chain. Both are candidates only.
- Geometry edits, or fine-tuning use (permission unconfirmed).

## Abstain or ask for review when

- The sheet is marked "second look", or the title names another family (for example RCC BOX, PSC SLAB or RUB) while the sheet shows an arch.
- The sheet shows an existing arch extended as a box, or it cannot be read whether the arch is existing or new.
- A span or rise is disputed, or the sheet has open tables or repeats. Both grounded examples have partial grounding.
- The question concerns seismic zones, arch clearance against HFL, or foundation depth. Those rules are disputed or not yet checked against the source.
- The record is `picture_only_ungrounded` (9 of the 11 arch sheets).

## Sources used

Files (repository paths; unreviewed research texts or generated reports unless stated):
- `knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/arch-bridge.md` (sections 1, 4, 8 rule ARCH-CLR-001, 27, 30).
- `knowledge/sources/rdso/raw/arch-bridge/10298.pdf` (cited by `kb:kb.family.arch`; not opened).
- `knowledge/sources/books/chunks/KB-CLAUDE-RESERACH.jsonl` (chunk `p1:18`).
- `knowledge/sources/books/chunks/KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-ARCH-BRIDGE.jsonl`.
- `ontology/bridge-families.json` (family `arch`).
- `agent-context/reports/coverage.md`, `agent-context/reports/issues.md`, `bridges/arch/README.md`.

IDs cited (verified with `ctx.py evidence`, except issue ids, which were checked in `status` output or in `issues.md`, and bridge ids, which were checked as folders under `bridges/arch/`):
- Family and ontology: `kb:kb.family.arch`, `kb:kb.family.rcc_box`, `ontology:arch`, `teach:arch-bridge`.
- Structure and components: `kb:phys.structure.arch_bridge`, `kb:phys.structure.arch_on_box`, `kb:phys.component.arch_barrel`, `kb:phys.component.spandrel_wall`, `kb:phys.component.abutment`, `kb:phys.component.parapet`, `kb:phys.component.return_wall`, `kb:phys.component.footing`, `kb:phys.component.weep_hole`, `kb:phys.subcomponent.haunch`, `kb:phys.component.sand_filling`, `kb:phys.feature.springing`, `kb:phys.feature.crown`.
- Rules and formulas: `kb:kb.rule.irbm_312_2_arch_clearance`, `kb:kb.rule.bs118_4_3_arch_seismic`, `kb:kb.rule.irbm_311_3_clear_span`, `kb:kb.rule.irbm_311_3_headroom`, `kb:kb.rule.irbm_313_free_board`, `kb:kb.rule.irbm_403_2_open_foundation_depth`, `kb:kb.rule.irbm_301_3_skew`, `kb:kb.rule.track_rail_over_formation`, `kb:kb.formula.d_clearance`.
- Conflicts: `kb:kb.conflict.kc_1`, `kb:kb.conflict.kc_6`, `kb:kb.conflict.kc_17`.
- Book chunks: `chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-ARCH-BRIDGE:p1:5`, `chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-ARCH-BRIDGE:p1:31`, `chunk:KB-CLAUDE-RESERACH:p1:18`.
- Proposal: `proposal:20261009-143333-E2_family_entries:6`.
- Issues (`issue:<kind>:<subject>`): `issue:disputed_knowledge:kb:kb.rule.bs118_4_3_arch_seismic`, `issue:needs_review:9de9340947eb-p1`, `issue:needs_review:a41a23a85b5e-p1`, `issue:partial_grounding:9de9340947eb-p1`, `issue:partial_grounding:a41a23a85b5e-p1`.
- Sheets (checked with `ctx.py status`): `9de9340947eb-p1`, `a41a23a85b5e-p1`, `71faa23ab6a2-p1`, `4b17c610275f-p1`, `272180db4517-p1`.
