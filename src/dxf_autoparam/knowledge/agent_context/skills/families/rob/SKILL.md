---
name: rob-bridge-context
description: Use when a drawing shows a road carried over the railway tracks on spans, piers and abutments (road over bridge, ROB; family rob, dataset folder bridges/rob), before reading its girders, substructure, clearances or open issues.
---

# Road over bridge, ROB (dataset folder `rob`)

Context only. The repository has no grounded ROB sheet and no human-verified record. Binding of any dimension is blocked.

**Assumed mapping (a suggestion, not an authority):** dataset folder `rob` -> `kb:kb.family.rob` -> ontology family `rob`.

## When to use this skill

- The sheet shows a road over the railway, with the road deck above rail level on spans, piers or portal piers, and abutments at both sides. Filed under family `rob`.
- Words that identify the family: the KB family entry lists no aliases. Its printed name is `rob`, and its canonical name is "Road over bridge" (`kb:kb.family.rob`). The abbreviation "ROB" means "road over bridge" (`kb:kb.abbreviation.rob`). The ontology terminology maps "ROAD OVER BRIDGE" to `phys.structure.rob` (`ontology/terminology.json`). Structure: `kb:phys.structure.rob`.
- Look-alikes:
  - A road under the railway (RUB, the `rub_other` folder). The KB says a ROB carries the road "over the railway instead of under it" (`kb:kb.family.rob`, relation to `kb:kb.family.rub`).
  - A railway girder bridge. The KB lists "reading a ROB girder sheet as a railway girder bridge" as a common misreading. The girder family is `kb:kb.family.girder`.
  - A substructure-only sheet. The KB lists "taking a substructure-only sheet as a whole general arrangement" as a misreading.
  - A special or existing work. The engineering text lists ROB among the common variants of special and existing works, a context that changes applicability (`bridge-families/special-and-existing.md`, sections 1 and 23).

## Scope in this repository

- Sheets: 6 (`agent-context/reports/coverage.md`), all at `picture_only_ungrounded`. No grounded ROB sheet exists.
- Dataset (`bridges/rob/README.md`): 6 bridges. Whole 0, extension 0, unknown 6. Sources: zonal 6. Permission to train: unconfirmed 6.
- Picture-only examples (checked with `ctx.py status`; classification `filed_in_catalog+placeholder_reference`; no issues recorded):
  - `33ac3e9e9f6f-p1` (bridge `brg-1e046f8b98`)
  - `e5611a656b3c-p1` (bridge `brg-f7a9055129`, marked "second look")

## What drawings of this family usually show

- Views, as the KB describes them (`kb:kb.family.rob`, `view_appearance`; unreviewed): in plan, a strip of road crossing the tracks with piers and approach walls; in elevation, spans on piers over the track clearance; in longitudinal section, the deck and girder along the road; in cross section, the deck with girders, footpaths and kerbs; in detail, the pier cap, bearing, railing and expansion joint.
- The KB says that in the dataset ROB sheets mostly show the substructure or the girder fabrication, not a whole general arrangement (`kb:kb.family.rob`, long description; from the sample).
- Ontology (`ontology/bridge-families.json`, family `rob`): no views, no primary components and no required facts are listed. The ontology does not say what a complete ROB sheet must show.
- Engineering text: there is no ROB text of its own. The closest is `knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/special-and-existing.md` (sections 1 and 23), where ROB is one variant. Unreviewed research text.
- Standard drawings named by the KB family entry (titles only; files in `knowledge/sources/rdso/raw/rob-substructure/`): substructure and foundation drawings for composite-girder ROB spans. By arrangement type: a portal pier on foundation (RDSO/B-10460 series; the title says the foundation type is not legible); a wall on open foundation for a non-skew arrangement (B-10461 series); a portal pier on open foundation (B-10462 and B-10463 series). The KB's implies note says: if a standard span is named, the substructure drawing set for that span arrangement is the companion sheet.

Component candidates (KB ids; ontology ids with the same names exist):

| Class | KB id | Review state |
|---|---|---|
| Structure | `kb:phys.structure.rob` | seed_unreviewed |
| Structure, PSC I-girder (see hazards) | `kb:phys.structure.psc_girder_bridge` | seed_unreviewed |
| Girder | `kb:phys.component.girder` | seed_unreviewed |
| Deck slab | `kb:phys.component.deck_slab` | seed_unreviewed |
| Approach slab | `kb:phys.component.approach_slab` | seed_unreviewed |
| Approach road | `kb:phys.component.approach_road` | seed_unreviewed |
| Road | `kb:phys.component.road` | seed_unreviewed |
| Kerb | `kb:phys.component.kerb` | seed_unreviewed |
| Footpath | `kb:phys.component.footpath` | seed_unreviewed |
| Bearing | `kb:phys.component.bearing` | seed_unreviewed |
| Pedestal | `kb:phys.component.pedestal` | seed_unreviewed |
| Pier | `kb:phys.component.pier` | draft |
| Pier cap | `kb:phys.component.pier_cap` | draft |
| Expansion joint | `kb:phys.component.expansion_joint` | seed_unreviewed |
| Pile | `kb:phys.component.pile` | seed_unreviewed |
| Well foundation | `kb:phys.component.well_foundation` | seed_unreviewed |
| Headroom (space over the rail) | `kb:phys.space.road_headroom` | seed_unreviewed |

## Formulas and rules for this family

Nothing below is executable. The labels are as recorded.

- No KB rule or formula record lists `rob` in its recorded applicability. Nothing in the repository is a ROB rule.
- The family's level chain is "to_define" (`ontology:rob`, level_chain): highest rail level plus minimum vertical clearance is at most the soffit. It is a summary, not a formula.
- Nearby general rules, which are not ROB rules: `kb:kb.rule.irbm_311_3_headroom` (NORMATIVE, seed_unreviewed, relaxable) is recorded for arch only. `kb:kb.rule.irbm_312_1_vertical_clearance` (NORMATIVE, seed_unreviewed) is recorded for slab and girder, and measures clearance above the design water level. Neither is applied to a ROB here.
- A candidate formula text on composite welded ROB girders is in `chunk:KB-BRIDGE-FORMULAS-16-SKEW-BRIDGES-COMPOSITE-GIRDERS:p1:1` (unreviewed book chunk; a formula document, not executable).

## Known hazards for this family

- Girder type. The ontology links the girder count to `phys.structure.psc_girder_bridge` (through the `rob` generator's `igirder.nGirders` key). The family entry's own cited guideline BS-130 R1 is titled "composite I-section steel girders for road over bridges" (`rdso_standard_drawings_and_guidelines`). The two disagree. The repository's rule is that a PSC girder is never represented with RCC assumptions (`CLAUDE.md`, hard rule 1). Ask which girder type the sheet shows.
- No completeness basis. The ontology lists no required facts and no views for `rob`, so a check against the ontology cannot say what is missing.
- Capability limit. The ontology's note says "only planning guidance (BS-112, secondary); no construction" (`ontology:rob`, capability_note). The KB cites BS-112 as planning guidance.
- Some retrieval pointers do not describe ROB design. `chunk:SRC-IRBM-24:p146:2` is a maintenance table. `chunk:SRC-IRBM-24:p273:1` is a list of railway girder types. `chunk:SRC-IRBM-24:p155:2` is about inspection of road over and under bridges (vertical clearance against the schedule, roadway thickness). Read them as maintenance context.
- Titles and text disagree in some research chunks. `chunk:KB-CLAUDE-RESERACH:p1:23` is titled "FILE: bridge-families/rob.md", but its text is from `relationships/level-system.md`. `chunk:KB-CLAUDE-RESERACH:p1:21` and `chunk:KB-CLAUDE-RESERACH:p1:22` show the same mismatch. Check the file before using any of them.
- Road loading governs the deck. This general-practice risk flag says "confirm on a given ROB design basis" (`kb:kb.family.rob`, risk flags).
- Open review items: `bridges/rob/README.md` lists "bridge number / km not fully printed or legible" for six ROB sheets, and a "second look" classification for `e5611a656b3c-p1`.
- The family entry is a draft. `proposal:20261009-143333-E2_family_entries:7` amends `kb:kb.family.rob`, is waiting for owner review, and is never merged automatically (`agent-context/reports/issues.md`, section proposal_not_merged). The entry's citation of that proposal does not resolve.
- `bridges/rob/README.md` lists inspection and non-destructive-testing reports as governing documents, including a report on a footpath slab collapse. They were not read for this file.

## Evidence to request before proposing anything

1. `.venv/bin/python agent-context/ctx.py status <record_id>`. Expect `picture_only_ungrounded`. If so, say so, and stop before any reading of the sheet.
2. `.venv/bin/python agent-context/ctx.py evidence kb:kb.family.rob` and `.venv/bin/python agent-context/ctx.py evidence ontology:rob`.
3. `.venv/bin/python agent-context/ctx.py search "<words>" --observations --owner <record_id>`, if observations exist for the sheet.
4. `.venv/bin/python agent-context/ctx.py pack <record_id> --task source_evidence --no-write --print`. Use `--no-write`.
5. Before stating a substructure or girder type, read the named standard drawing in `knowledge/sources/rdso/raw/rob-substructure/`. Before stating a clearance, read the guideline the question depends on.
6. `ctx.py evidence` does not resolve issue ids. Check an issue in the `status` output of the sheet that carries it, or in `agent-context/reports/issues.md`.

## Permitted output

- The record id, its family, capability and eligibility, as `status` reports them. State plainly that the sheet is ungrounded.
- A reading of the sheet, labelled as a reading, and only where observations exist, with the observation id.
- Component candidates with ids and review state.
- The statement that the repository holds no ROB rule or formula.
- The named standard drawings and their arrangement type, marked as titles from the KB, not checked against the files.

## Blocked output

- Binding any written dimension (span, girder depth, deck thickness, clearance) to a parameter slot. Binding is blocked on the KB records and on the sheets.
- Stating a girder type, a substructure type or a clearance as fact.
- Verification or validation claims. Nothing is verified, and the family's only guidance is planning guidance, secondary.
- Using the KB ROB entry as a design rule.
- Promoting `proposal:20261009-143333-E2_family_entries:7`.
- Geometry edits, or fine-tuning use (permission unconfirmed).

## Abstain or ask for review when

- Any dimension is asked for. This family has no grounded example, so abstain on dimension questions.
- The sheet is a substructure-only or girder-fabrication sheet. Say so, and do not treat it as a general arrangement.
- The girder type is unclear (PSC, composite steel or other), or the sheet is a railway girder bridge.
- The title or a printed word names RUB, RUB subway or GIRDER instead of ROB.
- The sheet is marked "second look" (`e5611a656b3c-p1`).
- The question concerns clearance over the rail, road loading, or foundation type.

## Sources used

Files (repository paths; unreviewed research texts or generated reports unless stated):
- `knowledge/sources/engineering/bridge-engineering-knowledge/bridge-families/special-and-existing.md` (sections 1, 23, 27).
- `knowledge/sources/rdso/raw/rob-substructure/10461 SERIES.pdf` (cited by `kb:kb.family.rob`; not opened; the other series files in the same folder are named only in the KB entry).
- `knowledge/sources/rdso/raw/bs-reports/BS-112.pdf` (planning guidance cited by the KB entry; not read beyond its citation).
- `knowledge/sources/rdso/raw/bs-reports/2026-07-09-BS 130 R1.pdf` (named in the KB entry; not read).
- `ontology/bridge-families.json` (family `rob`); `ontology/terminology.json`.
- `knowledge/sources/books/chunks/KB-CLAUDE-RESERACH.jsonl` (chunks `p1:21`, `p1:22`, `p1:23`).
- `CLAUDE.md` at the repository root (hard rule 1, PSC girder).
- `agent-context/reports/coverage.md`, `agent-context/reports/issues.md`, `bridges/rob/README.md`.

IDs cited (verified with `ctx.py evidence`, except issue ids, which were checked in `status` output or in `issues.md`, and bridge ids, which were checked as folders under `bridges/rob/`):
- Family and ontology: `kb:kb.family.rob`, `kb:kb.family.rub`, `kb:kb.family.girder`, `kb:kb.abbreviation.rob`, `ontology:rob`, `kb:phys.structure.rob`.
- Structure and components: `kb:phys.structure.psc_girder_bridge`, `kb:phys.component.girder`, `kb:phys.component.deck_slab`, `kb:phys.component.approach_slab`, `kb:phys.component.approach_road`, `kb:phys.component.road`, `kb:phys.component.kerb`, `kb:phys.component.footpath`, `kb:phys.component.bearing`, `kb:phys.component.pedestal`, `kb:phys.component.pier`, `kb:phys.component.pier_cap`, `kb:phys.component.expansion_joint`, `kb:phys.component.pile`, `kb:phys.component.well_foundation`, `kb:phys.space.road_headroom`.
- Rules and formulas: `kb:kb.rule.irbm_311_3_headroom`, `kb:kb.rule.irbm_312_1_vertical_clearance`.
- Book chunks: `chunk:KB-BRIDGE-FORMULAS-16-SKEW-BRIDGES-COMPOSITE-GIRDERS:p1:1`, `chunk:SRC-IRBM-24:p146:2`, `chunk:SRC-IRBM-24:p155:2`, `chunk:SRC-IRBM-24:p273:1`, `chunk:KB-CLAUDE-RESERACH:p1:21`, `chunk:KB-CLAUDE-RESERACH:p1:22`, `chunk:KB-CLAUDE-RESERACH:p1:23`.
- Proposal: `proposal:20261009-143333-E2_family_entries:7`.
- Sheets (checked with `ctx.py status`): `33ac3e9e9f6f-p1`, `e5611a656b3c-p1`.
