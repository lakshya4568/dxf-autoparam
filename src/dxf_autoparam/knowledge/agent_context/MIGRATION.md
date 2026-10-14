# Migrated agent-context (source material)

Copied from `Aagento-GAD-Foundation-Model/agent-context` by `tools/migrate_agent_context.py`. 69 files, 70,257,511 bytes as they were in the source, 5,745,972 bytes stored here. Source tree digest: `ac04f09d104eb7bf5b5736981221eb751ffbc4718013766bdaa14859ebb03582`.

Nothing in this folder is edited by this project. Hashes of every file (as in the source, and as stored) are in `MIGRATION.json`;
`uv run python tools/migrate_agent_context.py --verify-only` and `tests/test_migration.py` check them.

## Transformations

Only one: files larger than 1 MB (generated data) are stored gzip-compressed, losslessly, with a `.gz` suffix:

- `knowledge/knowledge.jsonl` → `knowledge/knowledge.jsonl.gz` (7,433,597 → 965,742 bytes)
- `knowledge/search_index.json` → `knowledge/search_index.json.gz` (6,502,757 → 793,897 bytes)
- `registry/observations.jsonl` → `registry/observations.jsonl.gz` (51,994,973 → 2,461,745 bytes)
- `registry/sources.jsonl` → `registry/sources.jsonl.gz` (3,097,429 → 295,833 bytes)

## Not copied

Directories .git, .pytest_cache, .ruff_cache, __pycache__; suffixes .pyc, .tmp; names .DS_Store.

## What each part is

| Path | What it is | Used at runtime |
|---|---|---|
| `skills/` | the source's agent skills (written for its repository command line) | parsed by section by `ai/library.py` |
| `knowledge/knowledge.jsonl.gz` | 2,914 knowledge records (B reference, C vocabulary, D proposed or disputed, E operational) | yes |
| `registry/sources.jsonl.gz`, `registry/issues.jsonl` | the source register and known problems | yes (references) |
| `registry/observations.jsonl.gz` | printed items read from sheets, RDSO pages and vector sheets | the rows of the 17 drawing sheets a model has read, as worked examples on request; the RDSO-page and vector-text rows are kept, not used |
| `schemas/` | the record schemas | validation in tests |
| `knowledge/GLOBAL_INDEX.md`, `reports/`, `packs/`, `README.md` | the source's map, reports and demonstration packs | reference only |
| `agentctx/`, `ctx.py`, `tests/`, `scripts/` | the source's library, tests and scripts: they need the source repository (not present here) | **no** — provenance only |
