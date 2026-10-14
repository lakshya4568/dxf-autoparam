---
name: girder-bridge-context
description: Use when a railway drawing shows a girder bridge (long beams on bearings carrying a deck, in PSC I, composite, steel plate, open web or bow string form) and you need the repository context for it before reading, grounding or proposing anything.
---

# Girder bridges (dataset folder `girder`)

Written 2026-10-13 from repository files. Almost everything here is `seed_unreviewed`: a starting entry that no person has checked. Nothing here is verified. Status words such as DERIVED, DISPUTED or UNKNOWN are copied from the records as written; they are not verification. The registry is the index the `ctx.py` commands read. Knowledge, ontology, chunk and sheet ids were checked with `ctx.py evidence`. Issue ids were checked against `agent-context/registry/issues.jsonl`, because `evidence` does not resolve them.

## When to use this skill

Use it for a sheet in `bridges/girder/` or for any drawing whose title or views show longitudinal girders on bearings.

Mapping used (an assumption taken from the brief, not an authority): dataset folder `girder` -> KB family `kb:kb.family.girder` -> ontology family `girder` (`ontology:girder`, entry `girder` in `ontology/bridge-families.json`).

Words that identify the family:
- The KB family entry has no alias list. Its printed name is "girder" and its canonical name is "Girder bridge (PSC I / composite / steel / OWG)" (`kb:kb.family.girder`).
- Drawing labels in `ontology/terminology.json`: "GIRDER" and "BEAM" (-> girder component, `ontology:GIRDER`); "PSC GIRDER" and "PSC I GIRDER" (-> PSC girder bridge); "COMPOSITE GIRDER" and "STEEL COMPOSITE" (-> composite); "PLATE GIRDER", "PG" and "OPEN DECK GIRDER" (-> steel plate girder); "OWG", "OPEN WEB GIRDER" and "TRUSS" (-> open web girder); "RCC GIRDER" and "T-BEAM" (-> RCC girder); "CROSS GIRDER" and "DIAPHRAGM" (-> cross girder).
- Shape on the sheet, per the KB: a long beam on bearings in elevation; parallel girder lines with cross members in plan; the girder profile with the deck on top in section; bearings in a detail (`kb:kb.family.girder`, deep.long_description and view_appearance).

Look-alikes that must not be confused with it:
- Slab bridge (`kb:kb.family.slab`). The girder entry says a slab deck is solid and sits directly on its supports, while a girder bridge has separate girders (`kb:kb.family.girder`, relation `differs_from`).
- Box frame. The KB says monolithic frames do not use bearings, so a box is not a girder bridge (`kb:kb.family.girder`, not_used_with).
- Temporary girder. A restricted height plate girder used during works, shown on an extension or temporary-arrangement sheet, is not the permanent structure. The KB cites RDSO/B-11045 for it (`kb:kb.family.girder`, common_misreadings and sources).
- Substructure drawings. The KB warns against mixing the girder with its abutment and pier drawings (`kb:kb.family.girder`, common_misreadings).

## Scope in this repository

Counts, as the repository files state them:
- `agent-context/reports/coverage.md`: girder has 1 sheet `grounded_needs_review` and 17 `picture_only_ungrounded` (18 in total).
- Folder check: `bridges/girder/` has 18 bridge folders, 18 sheet images and 1 grounding file. This agrees with coverage.
- Vector sheets for girder: none in the registry.
- The generated `bridges/girder/README.md` agrees: 18 bridges, 18 sheets, and training permission unconfirmed for all 18.
- The KB facts agree: 18 bridges and 18 sheets.

Grounded example (`ctx.py status` and `ctx.py pack ... --no-write`, read only):
- `68ec89bd2a5a-p1` (title "532-AB-65.tif", bridge `brg-0a173b3e40`): grounded and marked needs_review. Partly grounded. Two checks are informational (smudged or low-confidence reads). One written-versus-drawn dispute is open. The pack lists 3 conflicts and 15 open questions.
- This is the only grounded girder sheet. Do not draw a conclusion about the whole family from it.
- `human_verified` is `false` for all 18 girder sheets.

## What drawings of this family usually show

Components named by the repository (review state in brackets):
- Girder, the main longitudinal member (`kb:phys.component.girder`, seed_unreviewed).
- Cross girder or diaphragm (`kb:phys.component.cross_girder`, seed_unreviewed).
- Bearing (`kb:phys.component.bearing`, seed_unreviewed).
- Abutment (`kb:phys.component.abutment`, draft) and pier (`kb:phys.component.pier`, draft).
- Structure types: PSC girder (`kb:phys.structure.psc_girder_bridge`), composite steel girder (`kb:phys.structure.composite_girder_bridge`), open web girder or truss (`kb:phys.structure.open_web_girder_bridge`), steel plate girder (`kb:phys.structure.steel_plate_girder_bridge`), RCC T-beam or girder (`kb:phys.structure.rcc_girder_bridge`), PSC box girder (`kb:phys.structure.psc_box_girder_bridge`). All seed_unreviewed.

Engineering text, unreviewed research text (`knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/girder-bridge.md`):
- Section "4. Structural Components" lists primary girder, cross girder or diaphragm, deck slab or floor system, bearing, bed block or pedestal, pier cap, abutment, foundation and track (`chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-GIRDER-BRIDGE:p1:5`).
- Section "21. Typical Views" lists plan, elevation or longitudinal section, cross-section, and a detail only when needed.
- Section "23. Common Variants" lists steel plate girder, steel open-web girder, RCC beam-and-slab, PSC precast girder, PSC segmental or box girder, composite girder and multi-girder deck (`chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-GIRDER-BRIDGE:p1:24`).
- The KB variant list is different: PSC I girder, steel plate girder, composite girder, open web or bow string or truss girder, and temporary restricted height plate girder (`kb:kb.family.girder`, deep.variants). The two lists are not the same. Neither is verified.
- Standard drawings: the KB lists an RDSO abutment drawing for PSC girder spans and RDSO guidelines for composite, plate, open web and bow string girders (`kb:kb.family.girder`, facts). The KB gives no span ranges on purpose. Read the standard drawing itself (its risk flag).
- Unknowns named in the engineering text: family span systems and standard drawings incomplete, bearing selection rules absent, camber, prestress and erection geometry incomplete (`chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-GIRDER-BRIDGE:p1:28`).
- The engineering coverage table gives this family "INSUFFICIENT SOURCE" and its formulas "Not extracted" (`knowledge/sources/engineering/bridge-engineering-knowledge/reports/KNOWLEDGE_COVERAGE.md`).

## Formulas and rules for this family

None of these is executable. Each one is a candidate only.
- `kb:kb.formula.f_span_top_girder`: top slab level = soffit + girder depth. DERIVED, seed_unreviewed. Marked not executable until validated.
- `kb:kb.formula.f_span_soffit_from_top_girder`: soffit = top slab level - girder depth. DERIVED, seed_unreviewed, same status.
- `kb:kb.level_chain.chain_girder`: rail - track depth - deck - girder - bearing stack = bearing seat (the summary is in `ontology/bridge-families.json`, girder, level_chain). COMMON_PRACTICE, seed_unreviewed.
- `kb:kb.rule.know_girder_depth_ratio`: a depth-to-span rule for girders. The record gives L/20 "documented" against L/12 for a plate girder, and says L/20 is a spacing ratio from a secondary source. DISPUTED, seed_unreviewed. It applies to girder. Its conflict record is `kb:kb.conflict.kc_16` ("Girder depth ratio", DISPUTED, status OPEN, resolution "Not checked"). The rule record's own conflict list is empty.
- `kb:kb.formula.cg_val_002`: a second record that states the same depth ratio. Its id uses the CG-VAL label, and the record names no family. DISPUTED, linked to `kb:kb.conflict.kc_16`.
- `kb:kb.formula.cg_val_006`: a clearance value confused with free board. DISPUTED, linked to `kb:kb.conflict.kc_15`. This is a clearance question, not a girder dimension.
- Book chunks (unreviewed): `chunk:KB-BRIDGE-FORMULAS-05-COMPOSITE-GIRDER:p1:2` (parameter list) and `chunk:KB-BRIDGE-FORMULAS-05-COMPOSITE-GIRDER:p1:4` (vertical level formulas). Skew girder formulas are in `chunk:KB-BRIDGE-FORMULAS-16-SKEW-BRIDGES-COMPOSITE-GIRDERS:p1:1`. The coverage table rates skew and curved bridges "INSUFFICIENT SOURCE".
- Rule GIRDER-HIER-001 in `girder-bridge.md`, section 8: bearings and bed blocks are explicit components and must not be flattened into drafting symbols. The file marks it REFERENCE_OBSERVED and cites IRBM-2024 section 1103(6). This is a drawing-practice rule, not a dimension.

## Known hazards for this family

- `issue:informational_check_failed:68ec89bd2a5a-p1`: two checks are informational (smudged or low-confidence reads).
- `issue:unresolved_disputes:68ec89bd2a5a-p1`: one open dispute on girder length. The plan note and the section print different values. Do not choose one.
- `issue:partial_grounding:68ec89bd2a5a-p1`: no grounding entries for absent parts.
- `issue:needs_review:68ec89bd2a5a-p1`: grounding filed but still marked needs_review.
- Observation `68ec89bd2a5a-p1#P10`: the girder part was classed as "other". The elevation shows girder lines, but the girder section is not drawn. The record says this doubt in its own words.
- `issue:disputed_knowledge:kb:kb.rule.know_girder_depth_ratio`, `issue:disputed_knowledge:kb:kb.formula.cg_val_002`, `issue:disputed_knowledge:kb:kb.conflict.kc_16`, `issue:disputed_knowledge:kb:kb.formula.cg_val_006`: the depth and clearance candidates are disputed. Each one blocks binding and fine-tuning.
- `issue:proposal_not_merged:proposal:20261009-143333-E2_family_entries:5`: a proposed amendment to `kb.family.girder` waits for owner review. It is never merged automatically.
- `issue:unresolved_citation_origin:kb-file:family`: some family citation origins, including `kb:kb.family.girder`, do not resolve to files. They are kept as written.
- `issue:not_placed_by_family:bridges/_unsorted`: 430 sheets are not yet in a family folder. A girder sheet could sit there.
- `issue:placeholder_reference:bridges-index/sheets.classification_ref`: 277 sheets carry a placeholder classification reference.
- Ontology: the girder entry's parameter slot `structure.spans` names the class `phys.structure.psc_slab_bridge`. The generator `psc-slab` is also listed under the slab family. Do not infer the family from a generator name.
- Terminology: "T-BEAM" maps to RCC girder, and "TRUSS" maps to open web girder. These mappings are unreviewed.
- Temporary works: a restricted height plate girder on a temporary sheet is not the permanent structure (see the look-alikes above).

## Evidence to request before proposing anything

Run these from the repository root, in this order:
1. `.venv/bin/python agent-context/ctx.py status <record_id>`: completeness, grounding state, issues, eligibility.
2. `.venv/bin/python agent-context/ctx.py evidence <record_id>`: the sheet's own record and its trust labels.
3. `.venv/bin/python agent-context/ctx.py search "<words from the title block or view>" --observations --owner <record_id> --limit 40`: what the sheet reads (text, dimensions, levels, parts, disputes).
4. `.venv/bin/python agent-context/ctx.py pack <record_id> --task source_evidence --no-write`: the summary only. Add `--print` for the full pack. Always use `--no-write`.
5. `.venv/bin/python agent-context/ctx.py search "girder bearing" --category C B --limit 25`: vocabulary and component entries. Keep only those about this family's parts.
6. `.venv/bin/python agent-context/ctx.py search "girder formula rule" --category B D --topic formula rule --limit 25`: formula and rule candidates.
7. `.venv/bin/python agent-context/ctx.py evidence <id>` for every id you plan to cite.

Read the engineering text only for the section the question needs.

## Permitted output

- Say what the record reads, with its evidence id. Example: "the record reads 'old girder bridge' in an observation (evidence id ...)". Label it as a reading from a picture, made by a vision model and not checked by a person.
- Describe the family in general terms, citing the KB ids and giving their review state.
- List formula and rule candidates with their trust labels and conflicts. Call them candidates, never rules.
- Report counts from `coverage.md` and the registry, and say when files disagree.
- Name issues by their id and explain what they mean.

## Blocked output

- Binding any dimension to a parameter. Every record reads binding as blocked: the knowledge does not establish project dimensions, and no person has verified any sheet.
- Any claim that a sheet, a value, a formula or the family is verified, correct or complete.
- Treating a DERIVED label, or a rule marked REFERENCE_OBSERVED, as verification. An unreviewed record is not verified.
- Choosing between the two printed values of the disputed girder length, or between the two depth ratios.
- Promoting a proposal, changing a review state, or merging `kb.family.girder`.
- Using a span, depth, girder spacing or ratio that is not in a file you read.
- Any geometry or CAD edit. Live CAD binding is unavailable for these packs.
- Training or fine-tuning use. Those records are blocked.

## Abstain or ask for review when

- The title names another family, such as slab or box, while the views show girder lines.
- The sheet shows a temporary restricted height plate girder or extension works. It may not be the permanent structure.
- The sheet mixes girder drawings with abutment or pier drawings.
- A girder length or depth is disputed on the sheet (`68ec89bd2a5a-p1`).
- A question depends on the depth-ratio candidates, which are DISPUTED (`kb:kb.rule.know_girder_depth_ratio`, `kb:kb.conflict.kc_16`).
- The sheet is skew, curved or a bow string girder. The coverage table rates skew and curved bridges "INSUFFICIENT SOURCE".
- The sheet has no grounding file. Seventeen of the 18 sheets in this folder are in that state.
- The label is "TRUSS", "T-BEAM" or "PG". The mapping is unreviewed.
- The sheet sits in `bridges/_unsorted` or carries a placeholder classification reference.

## Sources used

Repository files (read only):
- `agent-context/reports/coverage.md`, `agent-context/reports/issues.md`, `agent-context/registry/issues.jsonl`, `agent-context/registry/sources.jsonl`, `agent-context/registry/observations.jsonl`
- `ontology/bridge-families.json` (entry `girder`), `ontology/terminology.json`
- `knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/girder-bridge.md` (sections 1, 4, 8, 21, 23, 27), `README.md`, `knowledge/sources/engineering/bridge-engineering-knowledge/reports/KNOWLEDGE_COVERAGE.md`
- `knowledge/kb/proposals/reorg-agent/_merged/20261009-143333-E2_family_entries.jsonl` (row 5)
- `knowledge/sources/books/chunks/KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-GIRDER-BRIDGE.jsonl`, `knowledge/sources/books/chunks/KB-BRIDGE-FORMULAS-05-COMPOSITE-GIRDER.jsonl`, `knowledge/sources/books/chunks/KB-BRIDGE-FORMULAS-16-SKEW-BRIDGES-COMPOSITE-GIRDERS.jsonl`
- `bridges/girder/README.md` (generated)

Ids cited (checked as described in the file header):
- KB: `kb:kb.family.girder`, `kb:kb.family.slab`, `kb:phys.component.girder`, `kb:phys.component.cross_girder`, `kb:phys.component.bearing`, `kb:phys.component.abutment`, `kb:phys.component.pier`, `kb:phys.structure.psc_girder_bridge`, `kb:phys.structure.composite_girder_bridge`, `kb:phys.structure.open_web_girder_bridge`, `kb:phys.structure.steel_plate_girder_bridge`, `kb:phys.structure.rcc_girder_bridge`, `kb:phys.structure.psc_box_girder_bridge`, `kb:kb.level_chain.chain_girder`, `kb:kb.formula.f_span_top_girder`, `kb:kb.formula.f_span_soffit_from_top_girder`, `kb:kb.rule.know_girder_depth_ratio`, `kb:kb.formula.cg_val_002`, `kb:kb.formula.cg_val_006`, `kb:kb.conflict.kc_15`, `kb:kb.conflict.kc_16`
- Ontology: `ontology:girder`, `ontology:GIRDER`
- Chunks: `chunk:KB-BRIDGE-ENGINEERING-KNOWLEDGE-BRIDGE-FAMILIES-GIRDER-BRIDGE:p1:5`, `...:p1:24`, `...:p1:28`, `chunk:KB-BRIDGE-FORMULAS-05-COMPOSITE-GIRDER:p1:2`, `chunk:KB-BRIDGE-FORMULAS-05-COMPOSITE-GIRDER:p1:4`, `chunk:KB-BRIDGE-FORMULAS-16-SKEW-BRIDGES-COMPOSITE-GIRDERS:p1:1`
- Sheets and observations: `68ec89bd2a5a-p1`, `68ec89bd2a5a-p1#P10`
- Issues (checked against `agent-context/registry/issues.jsonl`, not `evidence`): `issue:informational_check_failed:68ec89bd2a5a-p1`, `issue:unresolved_disputes:68ec89bd2a5a-p1`, `issue:partial_grounding:68ec89bd2a5a-p1`, `issue:needs_review:68ec89bd2a5a-p1`, `issue:disputed_knowledge:kb:kb.rule.know_girder_depth_ratio`, `issue:disputed_knowledge:kb:kb.formula.cg_val_002`, `issue:disputed_knowledge:kb:kb.conflict.kc_16`, `issue:disputed_knowledge:kb:kb.formula.cg_val_006`, `issue:proposal_not_merged:proposal:20261009-143333-E2_family_entries:5`, `issue:unresolved_citation_origin:kb-file:family`, `issue:not_placed_by_family:bridges/_unsorted`, `issue:placeholder_reference:bridges-index/sheets.classification_ref`
- Rule ids in the engineering text (not registry ids): GIRDER-HIER-001 (`girder-bridge.md`, section 8).
