---
name: other-bridge-context
description: Use when a drawing is a special or unclassified crossing (box syphon, canal box, retaining structure, or no clear family) filed in the other dataset folder, to find its context records, their review state and their limits.
---

# other: context for special and unclassified drawings

Everything here comes from repository files and the command output of ctx.py. Almost all of it is unreviewed. Nothing in this repository is human-verified, and binding of any dimension is blocked.

Terms used below:
- seed_unreviewed: written by a model or a seed process, not reviewed by a person.
- draft: written, not reviewed.
- proposed (category D): a suggestion, never accepted.
- picture_only: only the scan is recorded; no reading.
- binding: turning a written or drawn value into a model parameter.

## When to use this skill

Assumed mapping (a suggestion, as the brief states): dataset folder `other` -> `kb:kb.family.special` -> ontology family `special`. The folder README names the same KB entry (bridges/other/README.md).

This folder is a holding bucket. The KB record and the ontology both give it the name "Special / other (box syphon, canal box, retaining structure, unknown)". The KB record is a stub: it has no deep text, no facts and no view list. The ontology entry for special has no generators, no required facts, no views and no components (ontology/bridge-families.json).

Recognise a special work by:
- A canal or drain crossing. The drawing labels "CANAL BOX" and "SYPHON" map to `kb:phys.structure.box_syphon` (`ontology:CANAL BOX`, `ontology:SYPHON`).
- A stand-alone retaining wall. The label "RETAINING WALL" maps to `kb:phys.structure.retaining_structure` (`ontology:RETAINING WALL`).
- An existing-works context: widening, extension, rehabilitation, staged works, ROB, RUB, FOB, rail flyover. The record says these are "context modifiers, not a license to reuse new-work defaults" (chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:4).
- Anything that fits none of the other families. Six of the seven sheets here have structure type "none" (bridges/_index/sheets.jsonl).

Look-alikes (do not confuse):
- Box culvert and box syphon. The rcc_box record says a culvert box carries water, and a box syphon carries a canal or drain under pressure (`kb:kb.family.rcc_box`, raw.deep.long_description). Three box syphon sheets are filed in the rcc_box folder: `744c47b5ee98-p1`, `86557a0dc538-p1`, `fc266679f828-p1`. A syphon search in this folder misses them.
- Road under bridge: RUB records are in rub_other or rcc_box (`kb:kb.family.rub`).
- Arch on a box, `kb:phys.structure.arch_on_box` (arch family): not a special work.
- Return and wing walls of a box, `kb:phys.component.return_wall` and `kb:phys.component.wing_wall`: parts of other families' structures, not a special work on their own.

## Scope in this repository

- bridges/other (bridges/other/README.md): 7 bridges, 7 sheets. Whole 0, extension 0, unknown 7. Permission to train: unconfirmed 7.
- Coverage (agent-context/reports/coverage.md): 7 picture_only_ungrounded. There are no grounded examples in this folder, so none is cited.
- Sheet roles (bridges/_index/sheets.jsonl): index_or_notes 4, other 2, gad_main 1. Structure type: none 6, other 1. Legibility: good 3, fair 2, poor 2.
- Low confidence and second look: `b4982a7869c5-p1` (bridge:brg-dcd7f0e3f2; poor legibility; low confidence; flagged in bridges/_index/review_queue.jsonl).
- No vector-PDF sheets are recorded for this folder (vector-pdfs/INDEX.md lists rcc_box, rcc_slab and rub_other only).
- Governing documents: the folder README says "Document map not built yet (Phase E)".

## What drawings of this family usually show

Each record is seed_unreviewed unless marked. None of them describes a complete special drawing.
- Box syphon: `kb:phys.structure.box_syphon` (seed_unreviewed; evidence_status ENGINEERING_INFERENCE). A box structure that conveys a canal under or over the line. Free-form route. Ontology: `ontology:phys.structure.box_syphon`.
- Retaining structure: `kb:phys.structure.retaining_structure` (seed_unreviewed). A stand-alone retaining wall drawn as its own structure.
- Canal level: `kb:ref.level.fsl` (seed_unreviewed). The full supply level of a canal. The record says weep holes stay above it.
- Retaining-wall parts: `kb:phys.component.return_wall` (draft), `kb:phys.component.wing_wall` (draft), `kb:phys.subcomponent.back_wall` (seed_unreviewed; the wall at the top rear of an abutment, retaining the fill).
- Drawing labels (ontology): "CANAL BOX", "SYPHON", "RETAINING WALL".
- Special-works terms (text, unreviewed, no values): existing structure, proposed structure, temporary works, interface joint, staging, utilities, track protection (chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:5).
- Common variants (chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:24): doubling extension, gauge conversion, rehabilitation, reconstruction, box pushing, ROB, RUB or subway, FOB, rail flyover.
- Crossing types (ontology/bridge-families.json, special): canal over rail, rail over canal, other.

## Formulas and rules for this family

No formula is recorded for special works. The ontology level chain is marked to_define and has no summary. Candidates only; none is executable.
- Pressure conduits: `kb:kb.rule.irbm_312_3_culvert_exempt` (category B; evidence_status NORMATIVE) names syphons: "Syphons, pipe and box culverts are designed as pressure conduits; no clearance is required for them." Related dispute: `kb:kb.conflict.kc_15` (vertical clearance vs free board, DISPUTED). The GAD drafting checklist says the same (knowledge/sources/engineering/bridge-formulas/17-gad-drafting-composition-checklists.txt, citing IRBM para 312(3)). Use it only with the design basis of the given crossing.
- Weep holes above canal level: `kb:kb.rule.irbm_207_3_weep_holes` (category B; evidence_status NORMATIVE) places weep holes above the full supply level in canals. Their placement is disputed in `kb:kb.conflict.kc_12`.
- Open-line approval: chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:9 gives rule EXIST-GAD-001. Open-line railway-bridge GADs need approval by the Chief Bridge Engineer of the zonal railway. The text labels it NORMATIVE; the registry shows this chunk as UNKNOWN; no KB record exists for it.
- Not recorded: any clearance, span, height or level rule for canal boxes, syphons or retaining structures. Do not fill this gap from memory.

## Known hazards for this family

- The folder has no governing document map ("Document map not built yet (Phase E)", bridges/other/README.md).
- The KB record is a stub. Its retrieval pointers match the word "special" rather than the family content: `chunk:SRC-IRBM-24:p161:1` is about plant and machinery charges, and `chunk:SRC-BS-118:p45:1` is about ductile detailing for seismic design. Do not cite them as support for special works. `chunk:SRC-BS-118:p15:1` (special studies for specific bridge cases) is the closest.
- Six of seven sheets have no structure type recorded. This folder is a holding bucket, not a finding about the sheets.
- Duplicate printed identity: `bridge:brg-77c60447c9` (this folder) and `bridge:brg-d4eb60d3b7` (rub_other) both print bridge 528 at km 177/6-7. The sheets `560a2e4ebe5b-p1` and `79ad4bb9c06c-p1` share the file prefix 528-PCKM-21. Check before merging the two records.
- Box syphon sheets are filed in rcc_box, not here: `744c47b5ee98-p1`, `86557a0dc538-p1`, `fc266679f828-p1`.
- Four sheets are index or notes sheets, so they may show no structure.
- Sheets not placed in a family folder: `issue:not_placed_by_family:bridges/_unsorted` (430 sheets; their family is only in catalog/gad_catalog.jsonl). A special work may sit there.
- The rule EXIST-GAD-001 is labelled NORMATIVE in its text but UNKNOWN in the registry, and it has no KB record.

## Evidence to request before proposing anything

Run these first, from the repository root:
1. `.venv/bin/python agent-context/ctx.py evidence kb:kb.family.special` (the family record; it is thin, so also read the ontology entry special).
2. `.venv/bin/python agent-context/ctx.py status <record_id>` (capability, issues). Issue ids are listed here; `evidence` does not resolve them.
3. `.venv/bin/python agent-context/ctx.py search "<words the sheet prints>" --observations --owner <record_id>`. An empty query returns nothing. Then run `evidence <record_id>#<local id>` on each observation you rely on.
4. `.venv/bin/python agent-context/ctx.py search "syphon canal retaining wall" --category B C D --limit 25`, then `evidence` on every candidate id you cite.
5. `.venv/bin/python agent-context/ctx.py pack <record_id> --task source_evidence --no-write --print`. Use `--no-write`; do not write packs.

## Permitted output

- Cite the record id for each claim. Say "the record reads ..." for printed text, and label every reading as a reading.
- Name a candidate structure type with its reason, marked as a candidate: "candidate box_syphon, from the label CANAL BOX".
- Report sheet roles, legibility and identity fields from bridges/_index/sheets.jsonl.
- State the gap plainly: "no governing document and no rule for canal boxes in the repository".

## Blocked output

- Binding any dimension to a parameter. Binding is blocked for knowledge records and for these picture-only sheets.
- Assigning the special bucket, or any structure type, as accepted.
- Presenting the pressure-conduit, weep-hole or open-line approval rule as settled for a given canal or retaining structure.
- Giving clearances, spans, heights or levels for canal boxes or retaining walls from memory.
- Any geometry edit, CAD command or coordinate output.
- Use for training: blocked. Permission is unconfirmed for all seven sheets and no human labels exist.

## Abstain or ask for review when

- The sheet's structure type is none (six of seven sheets). Report that and stop.
- Confidence is low or legibility is poor (`b4982a7869c5-p1`).
- A sheet names a canal, syphon or retaining wall and also a box or culvert. Check the rcc_box folder first.
- The sheet is an index or notes sheet (`1310dc740a7b-p1`, `4f517f4ce123-p1`, `b3d9214ff46e-p1`, `fef0a9283770-p1`).
- The bridge number is shared with another folder (the 528 case).
- Any question on pressure, clearance, weep holes or approval for a canal structure.

## Sources used

Repository files read:
- ontology/bridge-families.json (entries special, rub and rob)
- agent-context/reports/coverage.md; agent-context/reports/issues.md
- agent-context/registry/issues.jsonl; agent-context/knowledge/knowledge.jsonl (read to list the family and conflict records)
- bridges/other/README.md; bridges/rub_other/README.md; bridges/_index/sheets.jsonl; bridges/_index/review_queue.jsonl
- vector-pdfs/INDEX.md
- knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/special-and-existing.md (identity, applicability, components, rule EXIST-GAD-001, common variants, unknowns)
- knowledge/sources/books/chunks/KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI.jsonl
- knowledge/sources/engineering/bridge-engineering-knowledge/bridge-formulas/17-gad-drafting-composition-checklists.txt (lines 105 to 121)

Ids cited (each checked, see the report):
- Family and ontology: kb:kb.family.special; kb:kb.family.rub; kb:kb.family.rcc_box; ontology:special; ontology:rub; ontology:rob
- Structures and labels: kb:phys.structure.box_syphon; ontology:phys.structure.box_syphon; kb:phys.structure.retaining_structure; ontology:CANAL BOX; ontology:SYPHON; ontology:RETAINING WALL; kb:phys.structure.arch_on_box; kb:phys.component.return_wall; kb:phys.component.wing_wall; kb:phys.subcomponent.back_wall; kb:ref.level.fsl
- Rules and conflicts: kb:kb.rule.irbm_312_3_culvert_exempt; kb:kb.rule.irbm_207_3_weep_holes; kb:kb.conflict.kc_12; kb:kb.conflict.kc_15
- Engineering chunks: chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:4; chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:5; chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:9; chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SPECIAL-AND-EXI:p1:24; chunk:SRC-IRBM-24:p161:1; chunk:SRC-BS-118:p45:1; chunk:SRC-BS-118:p15:1
- Sheets: 744c47b5ee98-p1; 86557a0dc538-p1; fc266679f828-p1; b4982a7869c5-p1; 560a2e4ebe5b-p1; 79ad4bb9c06c-p1; 1310dc740a7b-p1; 4f517f4ce123-p1; b3d9214ff46e-p1; fef0a9283770-p1
- Bridges: bridge:brg-dcd7f0e3f2; bridge:brg-77c60447c9; bridge:brg-d4eb60d3b7
- Issues (checked against agent-context/registry/issues.jsonl): issue:not_placed_by_family:bridges/_unsorted
