# agent-context

A derived access layer over the GAD repository. It finds, labels and packages what the repository already holds, so that an agent can ask for the relevant context without reading the whole repository.

It is not a dataset, not a second canonical database, and not a training source. The repository stays as it is: nothing here writes to a source, a grounding, a KB entry, a split, a label or a permission.

## What it does, in one list

- **Registry**: one record per source (drawing sheet, grounding, vector sheet, RDSO document and page, book source, instruction, schema, status note). Each record points to its repository files by path and fingerprint. Nothing is copied.
- **Observations**: each printed text, dimension, level, part, relation, table row (drawings), each RDSO page item (component, parameter, note, table, unclear or not-read marker) and each vector text span, stored with its raw text, the agent's reading kept apart, and its eligibility answers.
- **Knowledge**: knowledge-base entries, proposals, ontology, teaching cards, book chunks and engineering notes, normalised into five categories that are never flattened together (see below).
- **Issues**: every known problem and status conflict, with the purposes it blocks. Reported, never fixed.
- **Packs**: a focused, derived bundle for one record and one task. Every claim cites stored evidence ids. Packs are validated against a schema, the registry, and the current files.

## Layout

```
agent-context/
  README.md            this file
  ctx.py               command-line wrapper (the library is the real interface)
  agentctx/            the library: api.py (the five operations), registry.py (build), store.py (reads),
                       packs.py (packs), validate.py (checks), knowledge.py (index), policy.py (trust rules),
                       adapters/ (one module per corpus), cli.py, demo.py
  schemas/             JSON Schema for source, observation, knowledge and issue records, evidence packs,
                       and the optional runtime CAD snapshot
  registry/            generated: sources.jsonl, observations.jsonl, issues.jsonl, manifest.json
  knowledge/           generated: knowledge.jsonl, search_index.json, GLOBAL_INDEX.md (the compact map)
  packs/               generated: evidence packs and index.json (demonstration packs are here too)
  reports/             generated: build_report.md, issues.md, coverage.md, check_report.md
  skills/              agent skills (SKILL.md): general skills and one skill per bridge family
  tests/               unit tests (synthetic repository, for tests only) and tests on the real repository
  scripts/             one command that rebuilds, checks and tests
```

Everything under `registry/`, `knowledge/`, `packs/` and `reports/` is generated. Do not edit it by hand; rebuild it.

## Use it

Run from the repository root, with the project environment (`.venv`, created by `tools/setup.sh`):

```bash
.venv/bin/python agent-context/ctx.py build                       # rebuild the registry (about 3 seconds)
.venv/bin/python agent-context/ctx.py status 21cc08a32dd8-p1      # one record: completeness, eligibility, issues
.venv/bin/python agent-context/ctx.py search "weep hole" --category B C
.venv/bin/python agent-context/ctx.py search "box barrel" --observations --owner 21cc08a32dd8-p1
.venv/bin/python agent-context/ctx.py evidence 21cc08a32dd8-p1#D1 --live
.venv/bin/python agent-context/ctx.py pack 21cc08a32dd8-p1 --task dimension_binding
.venv/bin/python agent-context/ctx.py validate pack-b73bc37b904408d9
.venv/bin/python agent-context/ctx.py check                       # stale inputs, stale packs, broken paths
.venv/bin/python agent-context/ctx.py demo                        # demonstration packs for real records
.venv/bin/python agent-context/ctx.py tasks
```

From Python (any application or agent skill):

```python
import sys
sys.path.insert(0, "agent-context")            # the folder that holds the agentctx package
from agentctx import Context

ctx = Context()                                # the repository this folder sits in
ctx.search_knowledge("weep hole", categories={"B", "C"})
ctx.get_evidence("21cc08a32dd8-p1#D1")
ctx.get_source_status("21cc08a32dd8-p1")
pack = ctx.build_evidence_pack("21cc08a32dd8-p1", "dimension_binding")
ctx.validate_evidence_pack(pack)
```

The five operations are `search_knowledge`, `get_evidence`, `get_source_status`, `build_evidence_pack` and `validate_evidence_pack`. The CLI and the skills call the same functions.

## Five categories (kept apart on purpose)

| Category | Meaning | Where it is |
|---|---|---|
| A | Observation from a drawing or extract (what is printed, and the agent's reading of it) | `registry/observations.jsonl` |
| B | Reference and engineering knowledge (formulas, rules, standard drawings, book chunks, research notes) | `knowledge/knowledge.jsonl` |
| C | Vocabulary and interpretation aids (components, abbreviations, ontology classes, teaching cards) | `knowledge/knowledge.jsonl` |
| D | Proposed or disputed knowledge: proposals, DISPUTED entries, entries marked proposed | `knowledge/knowledge.jsonl` |
| E | Operational instructions for agents (briefs, protocols, procedures) | `registry/sources.jsonl` |

A record keeps its trust labels exactly as the repository wrote them: `evidence_status`, `review_state`, `use` flags, `risk_flags`, `authored`, `reviewed`, citations and conflicts. Nothing is promoted.

## Three answers, not one

Each record has three separate eligibility answers. Each is `eligible:<reason>` or `blocked:<reason>[+<reason>]`.

| Purpose | Question | Current result for all records |
|---|---|---|
| `retrieval` | May an agent read this as context, with its label? | Eligible for most records; blocked where there is no text or no picture |
| `binding` | May this establish a project dimension or a parameter value? | Blocked everywhere: the repository holds no human verification of any value |
| `finetune` | May this enter fine-tuning under the pipeline's own rules? | Blocked everywhere: no record is both human-labelled and permitted for training |

The counts are in `reports/build_report.md`. The fine-tuning pipeline's rules (permission, gold or silver labels, splits) are not changed here.

## Evidence ids

| Form | Example | Points to |
|---|---|---|
| `<record_id>#<local>` | `21cc08a32dd8-p1#D1` | one stored observation of that sheet (D1 = dimension 1) |
| `<record_id>` | `21cc08a32dd8-p1` | a source record (sheet, grounding, vector sheet) |
| `rdso:<doc_id>:p<N>` | `rdso:RDSO-RCC-BOX-10152-R-SERIES:p1` | an RDSO page |
| `rdso:<doc_id>:p<N>#component:<i>` | `...:p1#component:0` | one item on that page |
| `kb:<kb id>` or `kb.<kb id>` | `kb:kb.component.abutment_cap` | an accepted knowledge-base entry |
| `proposal:<file>:<line>` | `proposal:20261009-171725-haunch_rdso:2` | a proposal (category D, not merged) |
| `chunk:<chunk id>` | `chunk:KB-BRIDGE-…:p1:1` | a book chunk |
| `issue:<kind>:<subject>` | `issue:failed_check:426a3ac791e9-p1` | a known problem |

`ctx.py evidence <id> --live` also reads the item from the source file as it is now, so a changed source is visible.

## Packs

A pack is a derived artefact. It is never a source, never a label and never accepted knowledge.

Tasks:

| Task | Use it for |
|---|---|
| `source_evidence` | Finding the sources and stored observations for a record, with their gaps |
| `component_interpretation` | Naming the parts a sheet shows, with knowledge-base definitions as candidate context |
| `dimension_binding` | Listing written dimensions as candidates for a parameter. Binding stays blocked. |
| `geometric_relationships` | Views, levels, parts and relations as recorded. Nothing here edits or measures a CAD entity. |

Every pack has: a pack id (a digest of its whole content), its subject, its completeness status and capabilities, its source references with fingerprints, claims that each cite evidence ids, candidate interpretations (always `blocked` for binding, each with reasons), component definitions, formulas as text (never executed), conflicts, unresolved questions, the live CAD status, permitted and blocked next actions, and an agent summary.

Completeness statuses: `grounded_unverified`, `partially_grounded`, `limited_ungrounded` (identity and picture only; no views, dimensions or parts are reported), `identity_only`, `vector_text_observed`, `page_saved_unverified`, `not_saved`, `pages_saved_partial`, `all_pages_saved_unverified`, `none`.

Live CAD binding: `unavailable` unless a runtime snapshot is supplied with `--cad-snapshot` (see `schemas/cad-snapshot.schema.json`). A snapshot is echoed, never created. Without one, no CAD entity id appears anywhere in a pack.

Validation (`validate`) checks: the schema; that the pack id matches the content; that every claim cites stored evidence and a registered source; that each source is unchanged since the build; that no binding is marked allowed; that no CAD-like id appears without a snapshot; that an ungrounded record has no grounded observations; and that no action is both permitted and blocked.

## Change detection and rebuilds

- The manifest (`registry/manifest.json`) records the hash of every input file the registry reads. `check` lists inputs that changed, were removed or were added since the last build.
- A pack records the fingerprints and file hashes it was built from. `validate` reports a pack as stale when any of them changed.
- The build is deterministic: the same inputs give byte-identical outputs (no timestamps; sorted records). The tests check this.
- The build reads the repository and writes only inside `agent-context/`. The tests check that no input changes.

## Known limits (read before relying on the output)

- Nothing is verified by a person. Every value, reading and label carries `human_verified: false`.
- The RDSO page reads were made by eye, without OCR. Saved is not the same as checked. Only the general arrangement page of most documents was compared with the picture, and only at view level (see `reports/issues.md`).
- Vector PDFs: the text layer is observed text. Their paths are counted, not indexed; geometry is not an observation.
- Grounding readings are a model's reading of the picture. The arithmetic checks in a grounding are checks in code on the written numbers, not checks of the drawing.
- Knowledge: 767 of 874 entries are `seed_unreviewed`; proposals are not merged; formulas and rules are text, not code.
- Citations: many `merged_from` origins and internal source ids (for example `SRC-GEOMETRY`) do not resolve to a file. They are kept as written and reported.
- The search is a token index (words). It has no embeddings, and it does not understand meaning.
- The bridge-family vocabulary differs between the dataset folders, the grounding and the ontology (for example `rcc_slab` and `slab`). The differences are reported, not rewritten.

## Skills

`skills/` holds the agent skills. `skills/README.md` lists them. The general skills (finding evidence, interpreting components, proposing dimension bindings, proposing geometric relationships, handling uncertainty) and one skill per dataset family are written as instructions that call only the commands above, and cite only ids that resolve. `tests/test_skills.py` checks that every id a skill cites exists.

## Tests and checks

```bash
.venv/bin/python -m unittest discover -s agent-context/tests -v      # all tests (about 15 seconds)
.venv/bin/python agent-context/ctx.py check                           # the repository as it is now
bash agent-context/scripts/check_all.sh                               # build, check, tests, demo, in order
```

- `test_synthetic.py`: a tiny synthetic repository (in `tests/fixtures.py`) for behaviour that real data cannot show on demand. Synthetic data is used by these tests only.
- `test_repository.py`: the real repository, built into a temporary folder (the committed outputs are not touched).
- `test_skills.py`: every id cited in `skills/` resolves.

## Adding a source

Each corpus has one adapter in `agentctx/adapters/`. An adapter reads files, creates source records with `make_source`, creates observations and knowledge records through the collector, and reports problems as issues. It never writes to the repository. Add the adapter to `registry.build`, add its input folder to `registry.INPUT_PATTERNS` so changes are detected, and add a test with a synthetic fixture.
