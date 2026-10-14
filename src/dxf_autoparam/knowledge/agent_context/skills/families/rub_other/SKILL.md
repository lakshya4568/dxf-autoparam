---
name: rub_other-bridge-context
description: Use when a road-under-bridge drawing has a slab or girder deck on abutments rather than a box, to find its context records, their review state and their limits.
---

# rub_other: context for road-under-bridge drawings with other decks

Everything here comes from repository files and the command output of ctx.py. Almost all of it is unreviewed. Nothing in this repository is human-verified, and binding of any dimension is blocked.

Terms used below:
- seed_unreviewed: written by a model or a seed process, not reviewed by a person.
- draft: written, not reviewed.
- proposed (category D): a suggestion, never accepted.
- picture_only: only the scan is recorded; no reading.
- binding: turning a written or drawn value into a model parameter.

## When to use this skill

Assumed mapping (a suggestion, as the brief states): dataset folder `rub_other` -> `kb:kb.family.rub` -> ontology family `rub`. The folder README names the same KB entry (bridges/rub_other/README.md).

The KB record says box RUBs are filed in the rcc_box folder and RUBs with other decks are filed here (`kb:kb.family.rub`, raw.facts.note2). Its sub-kinds are box RUB, slab or girder deck RUB, and limited-height subway (raw.facts.sub_kinds).

Recognise a road under bridge (RUB) by:
- The road passes under the railway, and the title names the level crossing it replaces and its chainage, not a bridge number (`kb:kb.family.rub`, raw.deep and raw.qa).
- Words "ROAD UNDER BRIDGE", "RUB", "LHS" or "limited height subway" (`kb:kb.abbreviation.rub`, `kb:kb.abbreviation.lhs`). The family record has no aliases.
- Road levels, approach gradients, side drains and a drainage arrangement (raw.deep.drawing_conventions).
- Notes listing pre-block, block and post-block works, with traffic blocks and speed restrictions (raw.deep.implies).

The repository has no written description of how a slab or girder RUB is drawn. The view labels in the RUB record (for example "HALF SECTION & HALF ELEVATION") describe a box, so do not use them to decide the deck type.

Look-alikes (do not confuse):
- Box RUB, `kb:phys.structure.rcc_box_rub` (draft): a box carrying the track over the road. It is filed in rcc_box. The RUB record lists "calling every RUB a box" as a misreading to avoid (raw.deep.common_misreadings).
- Road over bridge, `kb:phys.structure.rob` (ontology `phys.structure.rob`): the road is over the rail. The ontology gives RUB crossing type rail_over_road and ROB crossing type road_over_rail (ontology/bridge-families.json).
- Slab bridge, `kb:phys.structure.rcc_slab_bridge`, and girder bridge, `kb:phys.structure.psc_girder_bridge`: both are decks on abutments. A RUB is told apart by the road under it, the road works and the drainage, not by its deck.
- Drawing label "LIMITED HEIGHT SUBWAY" (`ontology:LIMITED HEIGHT SUBWAY`) maps to the box RUB structure. A sheet with that label and no box cues needs review.

## Scope in this repository

- bridges/rub_other (bridges/rub_other/README.md): 7 bridges, 7 sheets. Whole 0, extension 0, unknown 7. Permission to train: unconfirmed 7.
- Coverage (agent-context/reports/coverage.md): 7 picture_only_ungrounded. There are no grounded examples in this folder, so none is cited.
- Sheet roles (bridges/_index/sheets.jsonl): gad_main 6, index_or_notes 1. The structure type is recorded as "other" on all seven sheets. Second look is flagged on `116f687ffd1e-p1` (bridge:brg-789cb5fea1).
- Held-out vector-PDF set (vector-pdfs/INDEX.md, not in bridges/): 2 sheets in rub_other, both printed "RCC BOX (RUB)": `v-89157c5cbc6f-p1` and `v-c2a7b0a1c659-p1`. This conflicts with the rule that box RUBs are filed in rcc_box. See hazards.

## What drawings of this family usually show

The repository describes RUBs mainly through box examples. Each record is seed_unreviewed unless marked otherwise.
- Structure: the RUB family is described as a box with road works. Other deck types are named in the record ("some RUBs have slab or girder decks on abutments"), but no component list, geometry or view list is recorded for them. The ontology gives rub no primary components, no views and no required facts (ontology/bridge-families.json).
- Road and approaches: `kb:phys.component.approach_road` (seed_unreviewed, road approach with gradient); `kb:phys.component.road` (seed_unreviewed, road surface); `kb:ref.level.road` (seed_unreviewed, road carriageway level); `kb:phys.space.road_headroom` (seed_unreviewed, clear height over the road).
- Retaining walls on the approaches: `kb:phys.component.return_wall` (draft).
- Drainage: `kb:phys.component.weep_hole` (draft). The record names drainage chambers, sumps and pumps where the road dips (kb:kb.family.rub, raw.deep.made_of).
- Parameter slots in the ontology for rub: all of them are box or wall parameters (cells, box gap, top and bottom slab, outer wall, haunch, wing and curtain walls, weep holes, cushion, cell clear span and height). None describes a slab or girder deck (ontology/bridge-families.json, rub).
- Views named in the RUB record (raw.view_appearance): plan with land boundary and key plan; half bottom and half top plan; half section and half elevation; section along the road with proposed road level and formation; cross sections of the approach walls; detail sheets for drainage chamber, height gauge and bore log. The elevation and section rows describe a box.
- Standards named in the record (all permission unconfirmed): `rdso-doc:RDSO-BS-REPORTS-BS-137` (guideline, air-pulling method); `rdso-doc:RDSO-BS-REPORTS-2026-07-09-BS-138-R1` (guideline on inspection, maintenance and construction); standard drawings `rdso-doc:RDSO-RCC-BOX-10159-SERIES`, `rdso-doc:RDSO-RCC-BOX-10160` and `rdso-doc:RDSO-RCC-BOX-M-00008`. The record's capability note says it holds "only secondary procedural knowledge ... no construction" (payload.capability_note).
- Construction methods (proposed, category D): `kb:kb.method.rub_subway_construction_methods_open_line` lists cut and cover with segmental boxes, box pushing, air pushing, box pushing with a protection plate, and box pulling. These are not accepted.
- Water ingress (proposed, category D): `kb:kb.inspection_defect.water_ingress_in_rubs_and_subways`.

## Formulas and rules for this family

No formula is recorded for the RUB family. Its ontology level chain is marked to_define, and its summary reads "road level + headroom = soffit; soffit + top slab + cushion = formation". The summary uses box terms, and no definition source is recorded (ontology/bridge-families.json, rub). Candidates only; none is executable.
- Weep holes in RUB walls (category B, evidence_status NORMATIVE, in dispute): `kb:kb.rule.irbm_207_3_weep_holes` places weep holes in abutments, wing walls and return walls. A proposal says BS-138 R1 advises no weep holes in new RUBs and subways, and that any provided should be sealed after checking structural capacity (`proposal:20261009-181438-learn-test-weep-hole:2`, category D). The dispute record is `kb:kb.conflict.kc_12` (DISPUTED). Report both; do not choose.
- Box cushion and headroom values (for a box RUB only): `kb:kb.conflict.kc_22` (minimum clear height of a box, DISPUTED) and `kb:kb.conflict.kc_5` (earth cushion minimum and datum, DISPUTED). Use them only if the sheet is a box, and see the rcc_box skill.
- Standard drawing values: none is accepted. `kb:kb.standard_drawing.rdso_b_10159` and `kb:kb.standard_drawing.rdso_b_10160` are category D, proposed.

## Known hazards for this family

- `issue:title_conflicts_with_content:v-89157c5cbc6f-p1`: the title prints two types ("RCC BOX" and "RCC BOX (RUB)"), and the bridge number printed 822/30-823/2 differs from the file name 822/2. The vector set files it under rub_other; bridges/ files box RUBs under rcc_box. The two filing rules disagree, and neither is resolved.
- The vector row for file 822-RUB (`v-c2a7b0a1c659-p1`, printed "RCC BOX (RUB)", high confidence in vector-pdfs/INDEX.md) is in the same position. Treat the box-or-deck question as open for both.
- The README's governing-document list for this folder is the box RUB list (it includes RCC box standard drawings). It does not describe the seven sheets.
- The README's open review items repeat `02b5df283486-p1`, `04a44b96ca41-p1` and `087150456848-p1`. Those sheets are filed under _unsorted and rcc_slab (bridges/_index/sheets.jsonl), not here.
- Identity: `bridge:brg-15ed7bbf52` (sheet `3477fff49910-p1`) has no printed bridge number (partial identity, bridges/_index/review_queue.jsonl).
- Duplicate printed identity: `bridge:brg-d4eb60d3b7` in this folder and `bridge:brg-77c60447c9` in the other folder both print bridge 528 at km 177/6-7. The file names share the prefix 528-PCKM-21. Check before merging the two records.
- Ontology gives rub no components, views or required facts, and its parameter slots are box parameters. A sheet cannot be checked against a family list here.
- Dispute on weep holes (see above): the rule record and the BS-138 proposal disagree.
- No sheet in this folder is grounded (capability picture_only_ungrounded; checked_against_picture none). Statements about a sheet are limited to its file name, sheet role, legibility and identity fields in bridges/_index/sheets.jsonl.

## Evidence to request before proposing anything

Run these first, from the repository root:
1. `.venv/bin/python agent-context/ctx.py evidence kb:kb.family.rub` (the family record: raw.deep, raw.facts, raw.qa, capability note).
2. `.venv/bin/python agent-context/ctx.py status <record_id>` (capability, issues, source state). Issue ids are listed here; `evidence` does not resolve them.
3. `.venv/bin/python agent-context/ctx.py search "<words the sheet prints>" --observations --owner <record_id>`. An empty query returns nothing. Then run `evidence <record_id>#<local id>` on each observation you rely on.
4. `.venv/bin/python agent-context/ctx.py search "road under bridge subway" --category B C D --limit 25`, then `evidence` on every candidate id you cite.
5. `.venv/bin/python agent-context/ctx.py pack <record_id> --task source_evidence --no-write --print`. Use `--no-write`; do not write packs.
6. For a box-or-deck question, also follow the evidence steps in the rcc_box skill.

## Permitted output

- Cite the record id for each claim. Say "the record reads ..." for printed text, and label every reading as a reading.
- Name the candidate family with its reason and its conflict: "candidate rub_other; the printed type reads RCC BOX (RUB), which the box filing rule puts under rcc_box".
- List candidate RUB terms and rules by id, with review state and any conflict id.
- Report issues by id and say what each one blocks.
- Say "no deck type is recorded for this sheet" when that is the case.

## Blocked output

- Binding any dimension to a parameter. Binding is blocked for knowledge records and for these picture-only sheets.
- Stating that the deck is a slab or a girder without a reading of the sheet and a human check.
- Stating that a RUB, a level, or a standard drawing value is verified, approved, correct or complete.
- Choosing between the weep-hole rule and the BS-138 proposal. Report the dispute instead.
- Any geometry edit, CAD command or coordinate output.
- Use for training. Fine-tune eligibility is blocked: permission is unconfirmed for all seven sheets and no human labels exist.

## Abstain or ask for review when

- The printed type is a box RUB ("RCC BOX (RUB)") or the sheet carries "LIMITED HEIGHT SUBWAY" with box cues. Route it to the rcc_box folder and its skill.
- The title names two types or two bridge numbers (`v-89157c5cbc6f-p1`).
- The sheet has no printed bridge number (`3477fff49910-p1`), or is marked second look (`116f687ffd1e-p1`).
- The sheet is an index or notes sheet (1 of the 7 sheets).
- Any answer depends on the weep-hole rule, the box cushion rule or the box headroom rule.
- Any question on construction method. The only method record is proposed.
- The sheet's bridge identity matches another folder's bridge (the 528 case).

## Sources used

Repository files read:
- ontology/bridge-families.json (entries rub and special)
- agent-context/reports/coverage.md; agent-context/reports/issues.md
- agent-context/registry/issues.jsonl; agent-context/knowledge/knowledge.jsonl (read to list conflict and family records)
- bridges/rub_other/README.md; bridges/other/README.md (checked for the duplicate printed identity); bridges/_index/sheets.jsonl; bridges/_index/review_queue.jsonl
- vector-pdfs/INDEX.md
- knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/special-and-existing.md (identity, applicability, common variants, unknowns)
- knowledge/sources/books/chunks/KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI.jsonl

Ids cited (each checked, see the report):
- Family and ontology: kb:kb.family.rub; kb:kb.family.rcc_box; ontology:rub; ontology:LIMITED HEIGHT SUBWAY; kb:kb.abbreviation.rub; kb:kb.abbreviation.lhs
- Components and structures: kb:phys.structure.rcc_box_rub; kb:phys.component.approach_road; kb:phys.component.road; kb:ref.level.road; kb:phys.space.road_headroom; kb:phys.component.return_wall; kb:phys.component.weep_hole; kb:phys.structure.rob; ontology:phys.structure.rob; kb:phys.structure.rcc_slab_bridge; kb:phys.structure.psc_girder_bridge; kb:phys.component.box_barrel
- Methods and inspection (proposed): kb:kb.method.rub_subway_construction_methods_open_line; kb:kb.inspection_defect.water_ingress_in_rubs_and_subways
- Standard drawings (proposed): kb:kb.standard_drawing.rdso_b_10159; kb:kb.standard_drawing.rdso_b_10160
- Rules and conflicts: kb:kb.rule.irbm_207_3_weep_holes; proposal:20261009-181438-learn-test-weep-hole:2; kb:kb.conflict.kc_12; kb:kb.conflict.kc_22; kb:kb.conflict.kc_5
- RDSO documents: rdso-doc:RDSO-BS-REPORTS-BS-137; rdso-doc:RDSO-BS-REPORTS-2026-07-09-BS-138-R1; rdso-doc:RDSO-RCC-BOX-10159-SERIES; rdso-doc:RDSO-RCC-BOX-10160; rdso-doc:RDSO-RCC-BOX-M-00008
- Engineering chunks: chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:2; chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:24; chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:28
- Sheets: 116f687ffd1e-p1; 3477fff49910-p1; v-89157c5cbc6f-p1; v-c2a7b0a1c659-p1; 02b5df283486-p1; 04a44b96ca41-p1; 087150456848-p1
- Bridges: bridge:brg-789cb5fea1; bridge:brg-15ed7bbf52; bridge:brg-d4eb60d3b7; bridge:brg-77c60447c9
- Issues (checked against agent-context/registry/issues.jsonl): issue:title_conflicts_with_content:v-89157c5cbc6f-p1; issue:proposed_knowledge:kb:kb.method.rub_subway_construction_methods_open_line; issue:proposed_knowledge:kb:kb.inspection_defect.water_ingress_in_rubs_and_subways; issue:disputed_knowledge:kb:kb.conflict.kc_12
