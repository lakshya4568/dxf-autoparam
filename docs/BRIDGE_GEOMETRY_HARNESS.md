# Real bridge geometry: what the harness now knows, measured (2026-10-22)

The brief: the agent left the return wall in 173A's longitudinal section — and many small components tied to the main structure — unparametrized;
make it understand components, bind the right relations, validate them on the geometry and engineering knowledge, handle scale and annotation, open
each view in its own coordinates, and reach 70–80 % of a representative new GAD with minimal intervention, measured — generically, not for one
drawing. Everything below is generic engine and harness code; the drawings' names appear only in tests, the bench's case file and this document.

## What was built, task by task

| # | Task | What exists now | Where | Verified by |
|---|---|---|---|---|
| 1 | Production audit | A traceable map of aagento-bridge's inputs, derived geometry, components, views, validation — formulas read from the code vs relationships measured | `docs/PRODUCTION_AUDIT.md`, CLAUDE.md §8 | read from the code at `e6c8f8fbe6`; `knowledge/production/*.json` refreshed by the extractor (13 families) |
| 2 | The GAD's inventory | Every part of 173A classified parametrized / partial / unparametrized / no dimension, with the drawing's own label and evidence; findings F1–F10 (why the return walls and toe walls were missed) | `docs/INVENTORY_173A.md`, `tools/component_inventory.py` | measured on a copy of the saved work |
| 3 | Semantic geometry model | Each DIMENSION tied to its two set-out lines, stepped, and sorted onto the parts drawn on those lines (sizes / sets out from / unassigned); a written number that disagrees with what it measures is said; parts carry the drawing's own labels and, by name, a production component card; unknown components are parts like any other; a SUM the sheet already works out (through the design intent) is driven, never a size to bind | `coverage.py`, `ai/labels.py`, `ai/context.SheetScope.drivers`, `knowledge/library/bridge/components.json` | `tests/test_coverage.py` (7) |
| 4 | Formula binding | `check_relation`: a proposed LEFT = RIGHT measured on the drawing — holds (residual), carried (every value that takes part stepped), which side gives (`gives`), units, what binding it takes; `set_relation` with `source`; `set_formulas` binds lines; a cycle is refused (V4), a loop of two lines kept one way round and said | `relations.py`, `ai/agent.py` | `tests/test_relations.py` (6): production's barrel = formation + 4 × cushion on a generated section — carried, the engine's side gives, rebound to production's: −2000 mm for +500 mm, the slopes keep 2H:1V; the same on 173A's own section |
| 5 | Validation and refusal | Every refusal (a change, a preview, the assembly check, a commit) names its check, its entities (id and DXF handle) and its KIND — the edit cannot be drawn / the model does not carry it / an accepted plan / a rule / the solver — with the measured basis, and whether the sheet already failed it | `refusal.py`, `crossview.py` (`failures`, `explain`, `SheetError.failures`), page `ValidationPanel` | `tests/test_refusals.py` (valid, invalid, incomplete, existing, promise, rule, solver, commit, agent, ambiguous) |
| 6 | Scale and annotation | Each view read at its own scale; a geometry edit moves each by its real size with every number right; a view redrawn at another ratio changes size on the sheet, not what it measures | `rescale.py`, `cli rescale` | `tests/test_scale.py` (1:100 + 1:25) |
| 7 | Views as workspaces | A tab per view, each in its own frame (x from its axis or centre line, y from a stated level, real mm, RL readout); the mapping to the sheet is exact both ways; edits stay on the sheet's entities so every view of the same geometry follows | `frames.py`, `web/src/canvas/ViewTabs.tsx`, `frames.ts` | `tests/test_frames.py`, `web/test/frames.test.ts`, `web/e2e/workspace.e2e.mjs` |
| 8 | Agent context and orchestration | `coverage` (what is open, per part, with the component card), `keep_dimensions`, `check_relation`, the status line's dimension count and a finish gate that refuses once while dimensions are open, refusal kinds in what the agent reads, each view's frame in `inspect_view`, a loop the engine closed the other way said in the verdict | `ai/agent.py`, `ai/run.py`, `ai/understanding_tools.py` | `tests/test_agent.py`, `test_sheet_ai.py`, `test_refusals.py`, `test_frames.py` |
| 9 | Evaluation suite | PARAMETRIZED = driven by a named value that can be edited ±10 % with the sheet valid; edits by refusal kind; views; annotation numbers after an edit; components found; cost per parametrized dimension | `tools/param_bench.py`, `tools/bench_cases.json`, `docs/PARAM_BENCH.md` | the numbers below |
| 10 | Integration | the suite, lint, the page's typecheck / unit tests / build, both e2e, the benchmark; docs (ARCHITECTURE Part 7, this file, PARAM_BENCH), CLAUDE.md map and rules | — | see "Tests run" |

## Before / after

| drawing | before: saved work of the last paid run (old harness) | after: reachable through the harness (ceiling) |
|---|---|---|
| 173A (the GAD of the brief) | 58 of 95 = 61 %; L-section 15/50 | 83 = 87 %; L-section 39/50 |
| 20A | 67 of 136 = 49 % | 96 = 71 % (one pass: 2 dimensions listed but not yet bound) |
| Bridge No.7A (new) | not parametrized | 106 of 122 = 87 % |
| mib173 (new) | not parametrized | at least 144 of 200 = 72 % (one pass: 42 listed but not yet bound) |
| generated box, 1–4 cells | the generator's answer: 86–90 % | 100 %, every edit accepted (before the SUM fix: 50 % and 40 % on 2 and 4 cells) |

PARAMETRIZED = a named value drives the dimension's two lines and its ±10 % edit keeps the whole sheet valid. The full table, the method and
what it does not measure: `docs/PARAM_BENCH.md`. Every annotation the sampled edits drove showed its new number after export (one drawn
disagreement excepted, said).

## Found by measuring, fixed in the engine

- **A dimension from a centre line kept its old number** after every change: its point on the centre line took the nearest member vertex (the face,
  a span away) and slid with it (`analyse.line_through`). Caught by the annotation check on a real L-section; `tests/test_annotations.py`.
- **A sum looked free to the agent.** Its workbench works on the answer without the derived design intent; there a box's overall width was open,
  and bound as an input it held the outer faces so a wider span had to run into the wall between the cells (generated 2- and 4-cell boxes: 88 % →
  50 % and 40 % editable). Now driven as the sheet stands, and refused as an input (`SUM`); the boxes reach 100 %. `tests/test_coverage.py`.
- **A relation can be carried with the other side giving way** — a finding, not a bug: `check_relation` reports `gives`.
- **Committing a big unit was slow**: 656 → 336 s of CPU for 25 new values on 173A's L-section (each size's plan built once per anchor, a
  formula's names once), the same result.

## What remains — honestly

- **What a model does with the new harness is NOT VERIFIED.** The baseline is the last paid run (old harness); the ceiling is what binding can
  reach. A run on the new tools needs the owner's go-ahead (a paid one), or a free Token Harbor model (zero cost, quality unmeasured).
- **Naming quality is not measured**: the metric needs a NAMED value, not a right one. A wrong name (173A's `ReturnWallTopWidth` measuring the stem's
  bottom, F4) counts; a part named for the wrong thing (its "ToeWalls" in the L-section are the height gauges, F6) counts as found.
- **Linking the same component's two drawings** (the return wall's C/S and its L-section, F5) is still the agent's call (`share_sizes` on evidence
  from `compare_views` / `search_drawing`); nothing links them by itself, on purpose — equal numbers are not one size.
- **A dimension whose written number disagrees with what it measures** (a drafter's number over geometry not drawn to it) is said
  (`coverage`: "writes 3600 but measures 3425 mm") but cannot follow any change; the person decides which is meant.
- **Refusal kinds are diagnoses from measured evidence**, not proofs: an entity spanning a moved and a fixed line is called *the model does not
  carry it* unless the fixed line is the drawing's outermost or the gap is owned; a clash with an entity no part owns is called incomplete with
  "define the part, then check again". The kind never relaxes a check.
- Drawings with no DIMENSION entities (BRG80, the general arrangement sample) state their sizes as text: the metric cannot measure them (0 / 0).
- **Unread dimensions** cap the ceiling: their points lie on no two set-out lines — a point on a slope, a dimension declared horizontal between
  vertically aligned points (it measures 0: five on the L-section), an angle or a radius. 10 of 95 on 173A, 18 of 136 on 20A, 16 of 122 on Bridge
  No.7A, 8 of 21 on the L-section.
- **Committing a unit with many values still takes minutes** (336 s of CPU for 25 on one unit): the whole-unit check per left-out size during the
  design intent remains; a run that names many values in one unit waits for it.

## Tests run (2026-10-22/23, this tree)

| What | Result |
|---|---|
| `uv run pytest tests` — the whole suite, on the final tree | 815 passed, 1 failed: `test_production … hanging_or_lying_bridge[process.exit(3);-exited]` timed out at its 1.5 s budget while three benchmark processes loaded the machine; its three variants pass when run alone (3 passed). The run before the last two speed-ups: 813 passed, 3 failed — fixed (the SUM check pre-empting V1 on two lines of different axes; the migration check counting `__pycache__`) |
| the new and changed tests | `test_refusals` 11, `test_coverage` 7, `test_relations` 6, `test_scale` 5, `test_frames` 5, centre-line dimension 1; design intent and plans 104, program / formulas / engine 120 — all passed |
| `uv run ruff check src tests tools` | clean |
| `cd web && bun run typecheck && bun run test && bun run build` | clean; vitest 134 passed; bundle rebuilt |
| `node e2e/workspace.e2e.mjs`, `node e2e/agent.e2e.mjs` (scripted model, own scratch servers) | 57 / 57, 67 / 67 |
| `tools/param_bench.py` (22 cases) | the numbers above; no model call |

## Reproduce

```bash
uv sync
uv run pytest tests/test_refusals.py tests/test_coverage.py tests/test_relations.py tests/test_scale.py tests/test_frames.py -q -p no:cacheprovider
uv run python -I tools/param_bench.py --cases tools/bench_cases.json --ceiling --domain bridge --md out/agent-logs/bench.md
uv run python tools/component_inventory.py ~/Downloads/173A.dxf <copy of the 173A autosave> --domain bridge
uv run pytest tests/test_relations.py -k barrel -q -p no:cacheprovider     # production's barrel relation: carried, which side gives, rebound
cd web && bun run typecheck && bun run test && bun run build && node e2e/workspace.e2e.mjs
```
