---
name: rcc_slab-bridge-context
description: Use when a railway drawing shows a slab bridge (a solid RCC or PSC deck on abutments and piers) and you need the repository context for it before reading, grounding or proposing anything.
---

# RCC and PSC slab bridges (dataset folder `rcc_slab`)

Written 2026-10-13 from repository files. Almost everything here is `seed_unreviewed`: a starting entry that no person has checked. Nothing here is verified. Status words such as DERIVED, DISPUTED or UNKNOWN are copied from the records as written; they are not verification. The registry is the index the `ctx.py` commands read. Knowledge, ontology, chunk and sheet ids were checked with `ctx.py evidence`. Issue ids were checked against `agent-context/registry/issues.jsonl`, because `evidence` does not resolve them.

## When to use this skill

Use it for a sheet in `bridges/rcc_slab/` or `vector-pdfs/rcc_slab/`, or for any drawing whose title prints a slab word and whose views show a deck resting on supports.

Mapping used (an assumption taken from the brief, not an authority): dataset folder `rcc_slab` -> KB family `kb:kb.family.slab` -> ontology family `slab` (`ontology:slab`, entry `slab` in `ontology/bridge-families.json`).

Words that identify the family:
- The KB family entry has no alias list. Its printed name is "slab" and its canonical name is "Slab bridge (RCC / PSC)" (`kb:kb.family.slab`).
- Drawing labels in `ontology/terminology.json` that map to this family: "RCC SLAB" (`ontology:RCC SLAB`), "PSC SLAB" (`ontology:PSC SLAB`), "PRESTRESSED SLAB", "SLAB BRIDGE" and "SLAB CULVERT". The last two map to the RCC slab class in that file (see hazards).
- KB sub-kinds: RCC slab, PSC slab, rail slab (`kb:kb.family.slab`, facts).
- Shape on the sheet, per the KB: a thin deck on the abutments and piers with bearings and a ballast wall in elevation; plan shows slab units and expansion gaps (`kb:kb.family.slab`, deep.long_description).

Look-alikes that must not be confused with it:
- Box culvert (`kb:kb.family.rcc_box`). The slab entry says a slab bridge is a deck on separate supports, while a box is one frame with walls and a bottom slab (`kb:kb.family.slab`, relation `differs_from`). Recorded misreading: an old RCC slab read as a box when the sheet extends it with a box.
- Girder bridge (`kb:kb.family.girder`). A slab deck is solid and sits directly on its supports; a girder bridge has separate girders.
- Rail slab (rails set in concrete, no ballast). The KB says no structure type exists for it in the vocabulary, and the dataset files these sheets under `rcc_slab` (`kb:kb.family.slab`, trust.risk_flags). Recorded misreading: treating a rail slab as a ballasted deck.

## Scope in this repository

Counts, as the repository files state them:
- `agent-context/reports/coverage.md`: rcc_slab has 6 sheets `grounded_needs_review` and 92 `picture_only_ungrounded` (98 in total).
- Folder check: `bridges/rcc_slab/` has 97 bridge folders and 98 sheet images. This agrees with coverage.
- Two more slab vector sheets sit in `vector-pdfs/rcc_slab/`: `v-18e8d9327c76-p1` and `v-1b2fb7ca5760-p1`. Coverage does not count them. The registry says they are held out as a test set, and the owner splits it. Their training permission is unconfirmed.
- The counts disagree between files. The generated `bridges/rcc_slab/README.md` says 99 sheets and 1 extension sheet. The KB facts say 98 sheets and 0 extension. This file does not choose between them.
- Training permission: the generated README records "yes 3, unconfirmed 96". Most of this folder is unconfirmed.

Grounded examples (`ctx.py status`, read only):
- `426a3ac791e9-p1` (title "RE-SDLP BR.NO.16.jpg"): grounded and marked needs_review. Blocked for binding and fine-tuning. Three issues. Three written-versus-drawn disputes are open.
- `637aaa70625c-p1` (title "217-CTRE-12.tif"): grounded and marked needs_review. Partly grounded. Its folder says rcc_slab but its grounding says rcc_box.
- Nothing in this folder is human-verified: every sheet checked reads `human_verified: false`.

## What drawings of this family usually show

Components named by the repository (review state in brackets):
- Deck slab (`kb:phys.component.deck_slab`, seed_unreviewed).
- Abutment (`kb:phys.component.abutment`, draft) and pier (`kb:phys.component.pier`, draft).
- Bearing or bed block (`kb:phys.component.bearing`, seed_unreviewed).
- Approach slab at the deck ends (`kb:phys.component.approach_slab`, seed_unreviewed).
- Soffit, the underside of the slab (`kb:phys.feature.soffit`, seed_unreviewed). Top of the slab level (`kb:ref.level.top_of_slab`, seed_unreviewed).
- Structure types: `kb:phys.structure.rcc_slab_bridge` (draft) and `kb:phys.structure.psc_slab_bridge` (seed_unreviewed).

Engineering text, unreviewed research text (`knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/slab-bridge.md`):
- Section "4. Structural Components" lists deck slab, wearing or ballast system, parapet or railing, bearing if applicable, abutment, pier if multispan, foundation and track (`chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SLAB-BRIDGE:p1:5`).
- Section "21. Typical Views" lists plan, elevation or longitudinal section, cross-section, and a detail only when needed.
- Section "23. Common Variants" lists RCC slab, PSC slab, simply supported, multi-span and skew slab (`chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SLAB-BRIDGE:p1:24`).
- KB variants: RCC slab (cast in place), precast PSC slab units placed side by side, and rail slab (`kb:kb.family.slab`, deep.variants).
- Standard drawings: the KB lists RDSO abutment and pier drawings for precast and post-tensioned PSC slab spans (`kb:kb.family.slab`, facts). The KB gives no span limits. Read the standard drawing itself.
- The engineering text says it is not an approved design. A competent engineer must check every executable rule (`knowledge/sources/engineering/bridge-engineering-knowledge/README.md`).
- The engineering coverage table rates this family's parameters "Partial" and its formulas "Insufficient design source" (`knowledge/sources/engineering/bridge-engineering-knowledge/reports/KNOWLEDGE_COVERAGE.md`).

## Formulas and rules for this family

None of these is executable. Each one is a candidate only.
- `kb:kb.formula.f_span_top_slab`: top slab level = soffit + deck slab. DERIVED, seed_unreviewed. Applies to no family in its record. Marked not executable until validated.
- `kb:kb.formula.f_span_soffit_from_top_slab`: soffit = top slab level - deck slab. DERIVED, seed_unreviewed, same status.
- `kb:kb.level_chain.chain_slab`: the level chain for a slab: rail - track depth - deck depth (- bearing) = seat; seat - substructure height = top of footing. COMMON_PRACTICE, seed_unreviewed. The chain is also summarised in `ontology/bridge-families.json` (slab, level_chain).
- `kb:kb.formula.psc_slab_005` and `kb:kb.formula.psc_slab_006`: a slab depth ratio attributed to IRS T-39, and a maximum thickness ratio attributed to an RDSO guideline. The record says both sources are not in hand. UNKNOWN, seed_unreviewed, not for retrieval or training.
- `chunk:KB-BRIDGE-FORMULAS-04-PSC-SLAB-BRIDGE:p1:11`: a thickness-to-span check (PSC-VAL-001) attributed to IRS T-39. Unreviewed book text.
- `kb:kb.formula.psc_val_004`: a clearance formula. DISPUTED. Linked to `kb:kb.conflict.kc_15` (vertical clearance against free board). Do not use.
- Rule SLAB-CON-001 in `slab-bridge.md`, section 8: a construction-sequence rule (falsework, reinforcement, placing, curing records). The file marks it NORMATIVE_CONTEXT and cites IRBM-2024 section 607. It is not a dimension rule. The IRBM document itself was not checked.
- Not for this family: `kb:kb.rule.level_order_slabs` lists its families as rcc_box and pipe, not slab.

## Known hazards for this family

- `issue:title_conflicts_with_content:v-18e8d9327c76-p1` and `issue:open_review_question:v-18e8d9327c76-p1`: a vector sheet filed as rcc_slab whose title prints both PSC SLAB and RCC BOX. Its family is open.
- `issue:title_conflicts_with_content:v-3ee4f1412e6e-p1` and `issue:title_conflicts_with_content:v-5b25c689e115-p1`: titles say RCC SLAB or PSC SLAB, but the sheets are filed as rcc_box and print box words. The issue says the title may be a stale template line.
- `issue:vocabulary_mismatch:637aaa70625c-p1`: folder rcc_slab, grounding rcc_box.
- `issue:failed_check:426a3ac791e9-p1`: four arithmetic checks disagree with the written numbers. Not resolved.
- `issue:unresolved_disputes:426a3ac791e9-p1`: three written-versus-drawn disputes are open (a foundation thickness, the height of stepped courses, and a bridge number).
- `issue:partial_grounding:637aaa70625c-p1`: no grounding entries for repeats, disputes or tables.
- `issue:needs_review:426a3ac791e9-p1` and `issue:needs_review:637aaa70625c-p1`: grounding filed but still marked needs_review.
- `issue:proposal_not_merged:proposal:20261009-143333-E2_family_entries:3`: a proposed amendment to `kb.family.slab` waits for owner review. It is never merged automatically.
- `issue:unresolved_citation_origin:kb-file:family`: some family citation origins do not resolve to files. They are kept as written.
- `issue:not_placed_by_family:bridges/_unsorted`: 430 sheets are not yet in a family folder. A slab sheet could sit there, and its family is known only from `catalog/gad_catalog.jsonl`.
- `issue:placeholder_reference:bridges-index/sheets.classification_ref`: 277 sheets carry a placeholder classification reference.
- Ontology: the slab family lists the generator `rcc-slab-2`, but its parameter slots name the box class `phys.structure.rcc_box_culvert`. The generator `psc-slab` is also listed under girder. Do not infer a family from a generator name.
- Terminology: "SLAB CULVERT" maps to the RCC slab class in `ontology/terminology.json`. That mapping is unreviewed, and a culvert may be a box or a pipe.

## Evidence to request before proposing anything

Run these from the repository root, in this order:
1. `.venv/bin/python agent-context/ctx.py status <record_id>`: completeness, grounding state, issues, eligibility.
2. `.venv/bin/python agent-context/ctx.py evidence <record_id>`: the sheet's own record and its trust labels.
3. `.venv/bin/python agent-context/ctx.py search "<words from the title block or view>" --observations --owner <record_id> --limit 40`: what the sheet reads (text, dimensions, levels, parts, disputes).
4. `.venv/bin/python agent-context/ctx.py pack <record_id> --task source_evidence --no-write`: the summary only. Add `--print` for the full pack. Always use `--no-write`.
5. `.venv/bin/python agent-context/ctx.py search "<family words>" --category C B --limit 25`: vocabulary and component entries.
6. `.venv/bin/python agent-context/ctx.py search "slab formula rule" --category B D --topic formula rule --limit 25`: formula and rule candidates.
7. `.venv/bin/python agent-context/ctx.py evidence <id>` for every id you plan to cite.

Read the engineering text only for the section the question needs.

## Permitted output

- Say what the record reads, with its evidence id. Example: "the record reads 'PSC SLAB' in the title (evidence id ...)". Label it as a reading from a picture, made by a vision model and not checked by a person.
- Describe the family in general terms, citing the KB ids and giving their review state.
- List formula and rule candidates with their trust labels and conflicts. Call them candidates, never rules.
- Report counts from `coverage.md` and the registry, and say when files disagree.
- Name issues by their id and explain what they mean.

## Blocked output

- Binding any dimension to a parameter. Every record reads binding as blocked: the knowledge does not establish project dimensions, and no person has verified any sheet.
- Any claim that a sheet, a value, a formula or the family is verified, correct or complete.
- Treating a DERIVED or NORMATIVE_CONTEXT label as verification. An unreviewed record is not verified.
- Promoting a proposal, changing a review state, or merging `kb.family.slab`.
- Using a span, depth, thickness or ratio that is not in a file you read.
- Any geometry or CAD edit. Live CAD binding is unavailable for these packs.
- Training or fine-tuning use. Those records are blocked.

## Abstain or ask for review when

- The title names another family or prints more than one type (`v-18e8d9327c76-p1`).
- The title says slab but the sheet prints box words, or the folder and the grounding disagree (`v-3ee4f1412e6e-p1`, `637aaa70625c-p1`).
- A written dimension is disputed on the sheet (`426a3ac791e9-p1`).
- An arithmetic check fails (`426a3ac791e9-p1`).
- The sheet has no grounding file. Ninety-two of the 98 sheets in this folder are in that state.
- The sheet sits in `bridges/_unsorted` or carries a placeholder classification reference.
- The drawing shows rails set in concrete (rail slab). No structure type exists for it.
- The question touches a DISPUTED record (`kb:kb.formula.psc_val_004`, `kb:kb.conflict.kc_15`).
- The title says "SLAB CULVERT", or the drawing is a culvert of any kind. Ask before you classify it.

## Sources used

Repository files (read only):
- `agent-context/reports/coverage.md`, `agent-context/reports/issues.md`, `agent-context/registry/issues.jsonl`, `agent-context/registry/sources.jsonl`, `agent-context/registry/observations.jsonl`
- `ontology/bridge-families.json` (entry `slab`), `ontology/terminology.json`
- `knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/slab-bridge.md` (sections 1, 4, 8, 21, 23, 27), `README.md`, `knowledge/sources/engineering/bridge-engineering-knowledge/reports/KNOWLEDGE_COVERAGE.md`
- `knowledge/kb/proposals/reorg-agent/_merged/20261009-143333-E2_family_entries.jsonl` (row 3)
- `knowledge/sources/books/chunks/KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SLAB-BRIDGE.jsonl`, `knowledge/sources/books/chunks/KB-BRIDGE-FORMULAS-04-PSC-SLAB-BRIDGE.jsonl`
- `bridges/rcc_slab/README.md` (generated)

Ids cited (checked as described in the file header):
- KB: `kb:kb.family.slab`, `kb:kb.family.rcc_box`, `kb:kb.family.girder`, `kb:phys.structure.rcc_slab_bridge`, `kb:phys.structure.psc_slab_bridge`, `kb:phys.component.deck_slab`, `kb:phys.component.abutment`, `kb:phys.component.pier`, `kb:phys.component.bearing`, `kb:phys.component.approach_slab`, `kb:phys.feature.soffit`, `kb:ref.level.top_of_slab`, `kb:kb.level_chain.chain_slab`, `kb:kb.formula.f_span_top_slab`, `kb:kb.formula.f_span_soffit_from_top_slab`, `kb:kb.formula.psc_slab_005`, `kb:kb.formula.psc_slab_006`, `kb:kb.formula.psc_val_004`, `kb:kb.conflict.kc_15`, `kb:kb.rule.level_order_slabs`
- Ontology: `ontology:slab`, `ontology:RCC SLAB`, `ontology:PSC SLAB`
- Chunks: `chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-SLAB-BRIDGE:p1:5`, `...:p1:24`, `chunk:KB-BRIDGE-FORMULAS-04-PSC-SLAB-BRIDGE:p1:11`
- Sheets and observations: `426a3ac791e9-p1`, `637aaa70625c-p1`, `v-18e8d9327c76-p1`, `v-1b2fb7ca5760-p1`, `v-3ee4f1412e6e-p1`, `v-5b25c689e115-p1`, `426a3ac791e9-p1#D132`
- Issues (checked against `agent-context/registry/issues.jsonl`, not `evidence`): `issue:title_conflicts_with_content:v-18e8d9327c76-p1`, `issue:open_review_question:v-18e8d9327c76-p1`, `issue:title_conflicts_with_content:v-3ee4f1412e6e-p1`, `issue:title_conflicts_with_content:v-5b25c689e115-p1`, `issue:vocabulary_mismatch:637aaa70625c-p1`, `issue:failed_check:426a3ac791e9-p1`, `issue:unresolved_disputes:426a3ac791e9-p1`, `issue:needs_review:426a3ac791e9-p1`, `issue:needs_review:637aaa70625c-p1`, `issue:partial_grounding:637aaa70625c-p1`, `issue:proposal_not_merged:proposal:20261009-143333-E2_family_entries:3`, `issue:unresolved_citation_origin:kb-file:family`, `issue:not_placed_by_family:bridges/_unsorted`, `issue:placeholder_reference:bridges-index/sheets.classification_ref`
- Rule ids in the engineering text (not registry ids): SLAB-CON-001 (`slab-bridge.md`, section 8).
