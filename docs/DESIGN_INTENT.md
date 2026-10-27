# Recovering design intent from an existing DXF (v3)

> The DXF is the compiled output. This layer reconstructs the program that was in the designer's head:
> parts → named values → formulas and constraints → set-out lines → geometry — and proves every piece of it
> by changing values and measuring what happens. It extends `AUTO_PARAMETRIZATION.md` (v1 engine, v2 AI +
> validator); nothing there is replaced.

## 1. The question, answered

**If Gemini is given a rich representation of an existing DXF — exact geometry, topology, dimensions, layers,
relationships, a rendered view, regions — can it reliably infer the design intent needed for a parametric model?**

**Partially — and the part it cannot do is exactly the part that must be deterministic.** Measured on the X-X
sectional elevation (one view, a culvert extension, 420 entities, no other sheet):

| Gemini does reliably | Must be deterministic (and is) | Cannot come from one drawing |
|---|---|---|
| What the parts ARE: it grouped all 52 regions into 14 parts in a 3-level tree (proposed box → barrel, slabs, courses, flooring, drop wall; existing culvert → barrel, headwall, footing; temporary works; tracks) with no region left over | Every number: positions, sizes, areas, which lines are equal, which regions touch — measured once, given as ids | Which of two redundant sizes is the input (overall width or cell span?) |
| Engineering names from the knowledge pack, proposed vs existing, which parts a draftsman would leave as drawn | Whether a claimed size, formula or relation is TRUE on the drawing (V1–V7) | Design rules not drawn (cover, minimum thickness, code limits) |
| Design intent in words: "when the barrel gets longer the flooring and drop wall move with it, the slabs keep their thickness, the levels stay" | Whether the model DOES what it claims (V12 behaviours, V13 constraints) — by changing each value and measuring every part | Behaviour beyond the drawn state: whether a 3-cell version keeps the same wall, how wings change with skew |
| Constraints: levels fixed, parts connected, symmetry | Enforcing a constraint in closed form when the model does not keep it (rewrite one set-out line) | Intent the drawing itself got wrong |
| Repairing its own claims from structured errors (5 rejected formulas → 0 in one repair round) | Regeneration, slopes kept, notes updated, DXF written, validity (V8) | |

So: **AI for semantics and intent, engine for geometry and truth, a person for the genuinely ambiguous.** The one
claim the measurement contradicted on X-X is instructive — Gemini said the top slab moves up when the clear height
grows; with the bed and formation levels both fixed, the model (correctly) keeps it in place and the cushion
absorbs it. That is a design decision, not a geometry fact, and the UI puts it in front of a person.

What is missing from a single drawing, and how to get it:
- **Other views** (plan, cross-section): the same pipeline per view (`--view N`), then a cross-view link of shared
  sizes — not built yet.
- **How the design behaves under change**: an edited copy of the drawing (`learn`, §6) shows which sizes the designer
  changes together and what stays.
- **Code/standard rules**: the knowledge layer of aagento-bridge (`knowledge/*.json`), already compiled into the
  prompt as names and formulas; enforcement stays in the engine.

## 2. The pipeline as built

```
DXF ─► dxf_read (all entity types, blocks, units, repair) ─► analyse (datums, gaps, candidate values)
     │
     ├─► topology   planar graph → REGIONS (atomic parts), holes, nesting, adjacency, hatch fill
     ├─► cadjson    the CAD JSON: entities + regions + relationships + datums + candidates + baseline
     └─► render     faithful picture · labelled set-out lines · region map (R ids)
                │
                ▼
          Gemini (ai/prompt.py, ai/schema.py)  — structured answer, ids only, no measuring
                │  parts tree · line roles · levels · parameters (+evidence, confidence) · formulas ·
                │  relations · behaviours (grow / move / fixed / keep …) · constraints · questions
                ▼
          validator.apply ── V1–V7 claims true on the drawing?
                │           intent.check_constraints  V13 (enforced in closed form where possible)
                │           intent.check_behaviours   V12 (each value changed, every part measured)
                │           check_regeneration        V8  (±10%, structured cause when it breaks)
                │           V15 proposed value reshaping existing work · V14 regions in no part
                ├─ errors ─► repair round (Gemini sees the validator's reasons) ─┐
                ▼                                                               │
          a person: what to parametrize (hold parts, keep values, drop constraints) ◄┘
                ▼
          Program (params → formulas → set-out lines → geometry) ─► regenerate ─► DXF (+ notes updated)
```

| Stage | Module | Deterministic? |
|---|---|---|
| Reading, units, blocks, repair | `dxf_read.py`, `dxf_repair.py` | yes |
| Set-out lines, sizes, candidate values | `analyse.py` | yes |
| Regions, adjacency, nesting, fill | `topology.py` | yes |
| CAD JSON (and split files) | `cadjson.py` | yes |
| Pictures (faithful, labelled, region map) | `render.py` | yes |
| Parts, names, intent | Gemini via `ai/` | no — proposals only |
| Truth of claims, enforcement, measurement | `validator.py`, `intent.py` | yes |
| Dependency graph | `graph.py` | yes (from the program, never from the AI) |
| Learning from an edited example | `learn.py` | yes |
| Regeneration, DXF writing | `program.py`, `regen.py`, `dxf_write.py` | yes |

## 3. The CAD JSON — the drawing made easier to reason about than the DXF

`dxf-autoparam json drawing.dxf [--view N] [--ai] [--split DIR] [-o file.json]`, or **CAD JSON** in the app.

| Section | What it holds | Questions it answers directly |
|---|---|---|
| `drawing` | units, extent, layers (types and roles on each, colour, linetype), symmetry axes, level datum, reader notes | What is on which layer? Is the sheet symmetric? |
| `entities` | per entity: id (`L…` line, `PL…` polyline, `A…` arc, `C…` circle, `H…` hatch, `D…` dimension, `T…` text, `LD…` leader, `B…` block), layer, colour / linetype / lineweight, block path; LINE start/end/length/angle/orientation; polyline vertices/closed/area/perimeter/inclined segments; arc centre/radius/angles/sweep/length; hatch pattern and the regions it fills; dimension measurement, definition points, the set-out lines and entities it measures, the candidate it confirms; text content, what it states (level, numbers, slope H:V, existing / proposed), the region it sits in, the nearest entity; leader tip → entity / region; `datums` (the set-out lines its points sit on), `connects_to` (shared points, T-junctions, crossings), `bounds_regions` | What is connected to this entity? What does this dimension measure? What does this note say and about what? |
| `topology.regions` | every closed area: area, perimeter, width, height, outline, interior point, holes, `inside_region` (nesting), `touches` (neighbour, side, shared length), `fill` (hatch pattern), datums it spans, bounding entities | What are the atomic parts? What rests on what? Which areas are material, which openings? |
| `topology.open_features` | structural entities bounding nothing (ground, rails, level lines) | What is linear, not an area? |
| `datums` | set-out lines, stated levels, the baseline formula of each | Where is each line set out from? |
| `relationships` | thickness / opening / offset / pitch / step / slope between lines (+ the region across, the faces, dimensions, centring axis, evidence, confidence); repeated distances; parallel / perpendicular / collinear / equal-length / symmetric entities; mirrored regions; repeated (congruent) regions with pitch; rests_on / beside / inside; regions on stated levels | Which sizes repeat? Which parts are symmetric? Which parts sit on the bed level? |
| `candidates` | measured sizes grouped when equal (`c…`) — the ids parameters name | Which values could be parameters? |
| `baseline` | the generic model the engine built | What does the geometry alone already drive? |

`--split` writes `drawing.json`, `geometry.json`, `topology.json`, `datums.json`, `relationships.json`,
`parameters.json`. The `--ai` form drops pattern / hatch-line entities (summarised by layer), trims minor offsets
and adjacency duplicated on regions: X-X is ~43k tokens instead of ~87k.

**Why regions.** GADs are drawn with loose LINEs; "the wing wall" exists only as the area its lines bound.
`topology.py` builds the planar arrangement: segments split at crossings and T-junctions, dangling chains set
aside, faces traced with half-edges (face on the left), holes assigned to the innermost containing region,
adjacency from shared half-edges, fill from hatch boundaries. On X-X: 188 nodes, 239 edges, 52 regions in 10 ms.
Regions are what Gemini segments; the region map picture labels them so the image and the JSON share ids.

## 4. What Gemini is asked (`ai/schema.py`, `ai/prompt.py`)

Strict structured output (pydantic `response_schema`), every claim by id:

- `components`: `name`, `type` (knowledge concept), `level` (assembly / component / subcomponent), `parent`,
  `regions`, `entities`, `existing`, `parametrize` (recommendation), `confidence`, `evidence`.
- `line_roles`: which set-out line is the inner face / soffit / toe … of which part.
- `levels`, `parameters` (+ `importance`, `recommended`, `confidence`, `evidence`), `datum_formulas`, `relations`.
- `behaviours`: per parameter, what happens to each part when it INCREASES — `grows`, `shrinks`, `moves`, `fixed`,
  `keeps_thickness`, `keeps_level`, `stays_centred`, `stays_symmetric`, `stays_connected`, `keeps_slope` (per axis).
- `constraints`: `distance`, `fixed`, `symmetric`, `centred`, `equal`, `connected`, `slope`, `parallel`,
  `perpendicular`, `collinear` over datums / parts / entities.
- `questions`.

The prompt teaches the CAD JSON field by field, walks one reasoning example ("R7 is hatched, rests on R12, the note
inside says WING WALL …"), and keeps the draftsman's rules (design inputs only, proposed vs existing, slopes and
notes are the engine's). No reference drawing's values or labels are in it.

## 5. Intent, checked by measurement (`intent.py`)

- **Parts** are measured on their own outlines (region corners on set-out lines, circles by centre and radius),
  never via entities shared with a neighbour — the closed form needs no regeneration and is exact.
- **Impact** (`measure_impact`): each named value +10% (≥ 50 mm; levels +0.5 m) → every part classified per axis as
  grows / shrinks / moves / fixed. Shown per parameter ("Measured: ProposedBarrel grows x, DownstreamDropWall moves x").
- **Behaviours (V12)**: each AI claim compared with that measurement → confirmed / contradicted (with the numbers) /
  held (a person froze the part). A contradiction goes back to Gemini in the repair round.
- **Constraints (V13)**: true on the drawing? kept when every value changes? If it holds as drawn but not under change,
  the engine rewrites ONE set-out line so it holds by construction — `distance` → `b = a ± value`, `symmetric` /
  `centred` → `b = 2·axis − a`, `equal` → `d = c + (b − a)`, `fixed` → constant — never over a line the AI, a slope, a
  site level or a held part sets. Otherwise it is sent back.
- **V8 with a cause**: a named value that breaks the drawing when it grows is an error, sent back with the lines that
  moved and the lines that stayed ("moved x91 = x56 + BarrelLength; stayed x89 = x87 − 0.125·(y10 − y20) …").
- **V15**: a value of proposed work that also reshapes existing work (they share a set-out line) is flagged.
- **Selection**: `hold` parts (their own lines become constants; a line shared with a free part is SPLIT — the held
  part's own entities move to a fixed copy, so an extension can grow while the old box stays as built), `exclude`
  values (frozen into the formulas), `drop` constraints. Default = the AI's recommendation; "Parametrize entire
  drawing" clears it. Applied without a new AI call.
- **Review**: anything the AI marks below 75% confidence is listed with Accept / Reject.

The dependency graph (`graph.py`, `/api/graph.json`) is built from the program: parameter → set-out lines →
entities → parts, relations, notes.

## 6. Learning from an example (`learn.py`)

`dxf-autoparam learn original.dxf edited.dxf` or **Learn from edit** in the app:

1. entities matched by handle (else order); every set-out line of the original read again in the edit;
2. sizes compared: the changed ones are the edited inputs (and whether all occurrences changed together), the rest
   are the invariants of that edit;
3. every part measured (grows / moves / fixed);
4. with a program: the parameter changes that explain the edit by least squares on the linear set-out, and the lines
   the program cannot explain — where its intent differs from the designer's.

Tested both ways: an edit made by the program is explained exactly (`OpenX1 +500`, no residual); a designer dragging
one corner the program cannot move alone is pointed out with the line and the parts it bounds. This is the path to
rules learned from existing parameterized drawings: each edited pair is a set of measured behaviours.

## 7. Research → what is used here

| Idea (source) | Used for | Not used, and why |
|---|---|---|
| CAD sketches as geometric-constraint graphs (SketchGraphs, Seff et al. 2020) | datums + gaps + constraints are that graph for set-out drawings; relationships in the CAD JSON | learned constraint prediction — no labelled GAD corpus yet; the app's accept / reject decisions can become one |
| Face-adjacency graphs for segmentation (B-rep graph nets such as UV-Net / BRepNet, 2021) | `topology.py`: the 2D equivalent — regions and their adjacency are the units Gemini labels | a trained segmenter; Gemini + knowledge pack does the labelling without training data |
| Planar arrangements / half-edge face tracing (computational geometry, DCEL) | region extraction from loose lines | — |
| CAD as a program / language (DeepCAD 2021, SkexGen 2022, Text2CAD 2024) | the output is a program (`Program`: params → formulas → lines → geometry), exported as JSON | sequence-model generation; here the program is recovered from a drawing, not generated |
| LLMs are weak at exact coordinates, strong at semantics (multimodal CAD-assistant work, 2024–25) | the model never measures; ids + pictures + measured JSON; every number re-checked | letting the model write coordinates |
| Structured output with a response schema (Gemini API) | `AIAnswer`, shallow nesting, enums for behaviours / constraint types | free text |
| Variational constraint solvers (D-Cubed, SolveSpace, FreeCAD's planegcs) | — | set-out drawings are linear chains; closed-form propagation is exact and explains itself. A numeric solver is the next step only for non-linear constraints (tangency, arcs at angles) |
| Programming by example / inverse procedural modelling | `learn.py`: fit the program to an edited example, report the residual | — |
| Human-in-the-loop verification of AI proposals | selection, review list, behaviours shown confirmed / contradicted | — |

## 8. Reusing UPCE (aagento-bridge)

UPCE is the execution model; this is the rule-discovery model. The program here maps onto UPCE directly:
parameters → `values`, set-out formulas → kernel formulas (the same expression language subset: names, + − × ÷,
min/max/abs/sqrt/round), parts → components with `regions` as their geometry, relations → relationships,
constraints → documented relations, behaviours → `perturbationTest` expectations. The port plan in
`AUTO_PARAMETRIZATION.md` §12 still holds; the new pieces to port are `topology.py` (regions) and `intent.py`
(behaviour / constraint checks), both pure geometry with no structure types.

## 9. Lint triage (ruff 0.16 default rules, 60 findings at the start)

| Rule | n | Verdict | Action |
|---|---|---|---|
| BLE001 / S110 blind `except` | 23 | **2 real**: `relation_values` dropped relations that failed to evaluate (a frozen value showed as nothing); the writer swallowed `upright` errors (broken data → wrong coordinates written). **Reader fallbacks** (text formatting, curve flattening, layer flags, extents, hatch pattern) were legitimate but too wide. **2 intentional boundaries** (HTTP request: traceback + error to the page; per-entity repair: counted by name) | narrowed to `DATA_ERRORS` (ezdxf.DXFError, ValueError, ArithmeticError, IndexError, KeyError); one counted per-entity boundary in the reader (`unsupported["TYPE (unreadable: Exc)"]`); dimension render failures counted *and named*; relations shown as "not computable"; repair catches only `GeminiUnavailable` / API errors; boundaries annotated |
| B023 closure over loop variable | 6 | no live bug (called inside the same iteration) — fragile | bound explicitly as defaults |
| PLR0124 `v != v` | 1 | a NaN test | `math.isnan` |
| RUF034 useless if/else | 1 | a duplicated branch (dead logic) | removed |
| ISC004 implicit concatenation in a list | 1 | intended one string, ambiguous | parenthesised |
| PLW1510 `subprocess.run` without `check` | 1 | intentional (failure handled) | `check=False` explicit |
| RUF007, FURB167, I001, UP037, RUF100, C408, SIM102, PIE808, PLR1733, RUF059 | 27 | style | fixed |

Narrowing found one real case immediately: ezdxf's `make_path` signals "no path for this type" with `TypeError`
(MTEXT / INSERT inside dimension blocks); the first narrowing counted every dimension as unreadable — visible in
the reader's counts and caught by the tests — and is now handled at that one call. `pyproject.toml` pins
`required-version = ">=0.16,<0.17"` so the rule set cannot drift; `uv run ruff check src tests tools` is clean.

## 9b. The parametrization agent (`ai/agent.py`) — why the one big answer was replaced

Measured on X-X with the person's instructions: the one-shot answer used `ClearHeight` in constraints without
defining it; the repair round then re-derived the whole 30 kB answer, thinking 62,474 tokens before being cut off
at the output limit with nothing usable. One wrong name in a big self-consistent JSON ripples into a dozen rejections,
and every fix is a rewrite. The model's attention went to bookkeeping, not engineering.

The agent works the way a draftsman works in CAD: small questions, small edits, each checked at once.

| Tools to look | Tools to edit (each checked at once; verdict in one line) |
|---|---|
| `inspect_regions` (size, fill, neighbours, notes inside, its edge lines and what each is set out from, sizes across it) | `set_structure`, `define_part` / `remove_part` |
| `inspect_lines` (formula, the chain it hangs from, which parameters move it, parts on it) | `define_parameter` / `remove_parameter` — names a candidate or two lines; **the engine fills the value** |
| `find_values` (candidates near a value / across a region / on an axis) | `set_level`, `set_formula` (one line), `set_relation` |
| `what_moves(parameter)` (every part: grows / shrinks / moves / fixed; drawing still valid?) | `add_constraint` / `remove_constraint`, `state_behaviour` |
| `knowledge(query)` (this project's concept names, formulas, families) | `ask_person`, `finish` (refused once while problems remain) |

- **Playbook** in the system prompt: structure → parts from regions → design inputs per part → levels → set each
  line out from the line it is connected to → verify with `what_moves` → behaviours and constraints → finish.
- **Every edit** goes into the answer under construction; after each batch of calls the engine validates once and
  each call gets its own verdict (`ok`, or `rejected` with the validator's reason), plus the open problems.
  A `define_parameter` that is accepted answers with what it moves.
- **Small prefix:** system ~1.5k + tools ~1.4k + overview ~2.3k tokens (compact rows) + three pictures, cached
  explicitly with the tools (~9k tokens instead of ~80k). Details come from the tools, on demand.
- **Thinking:** the first (planning) step at the configured level (high); edit steps at
  `VERTEX_AGENT_STEP_THINKING` (default: the same as `VERTEX_THINKING_LEVEL`, i.e. high) — set it to `medium`/`low` only to save tokens.
- **Bounded:** `VERTEX_AGENT_MAX_STEPS` (30) and `VERTEX_AGENT_MAX_OUTPUT_TOKENS` (150k, output + thinking);
  tool results older than eight steps are trimmed to their verdicts (three was measured too few: the agent re-read regions) (the conversation is re-sent every step);
  Stop works between steps; each step is cached on disk, so an identical replay is free.
- **Batch tools** (`define_parts`, `define_parameters`, `set_formulas`, `set_levels`, `add_constraints`,
  `state_behaviours`): one call carries many items, each with its own verdict. A model left with one-item tools made one
  call per turn.
- **Progress is enforced:** after four look-up-only turns the results carry a nudge ("define the parts now"); after six,
  look-ups are refused until an edit is made.
- While the agent builds, every value stays editable; the AI's own "keep as drawn" recommendations (and the person's
  selection) are applied to the final result. A named candidate the set-out does not drive (a height between two fixed
  levels) is kept as a value its formulas can use, and an accepted parameter that is not kept says so.
- **Revise** = the agent starting from the current answer with the person's request: it makes the asked edits only.

Measured on X-X with the instruction "only the proposed structure; existing culvert and tracks as drawn; barrel length
and clear height will change; bed and formation levels fixed":

| run | steps | output + thinking | input (cached) | result |
|---|---|---|---|---|
| one-shot, before | 2 calls (2nd cut off) | ~89k + 65k wasted | ~167k (155k) | stopped by the person; nothing usable |
| agent v1 (one-item tools) | 25 (cap) | 17,883 | 490k (290k) | 6 parts, 0 parameters: it kept looking |
| agent v2 (batch tools, nudge, lines + edges in the overview) | 20 (cap) | 11,155 | 539k (319k) | 7 parts covering all 52 regions, BarrelLength + ClearHeight editable, Bed / Formation levels fixed, slabs / flooring / drop wall kept as drawn, soffit and slab-top formulas, **0 rejections**; barrel +1000 / clear height +100 regenerate, notes rewritten, DXF 0 audit errors |

v2 ran out of steps before behaviours and constraints; the refusal after six look-up turns, `set_levels`, the larger
inspect batches and the no-early-freeze fix came after it (no live run yet). Most input is the conversation re-sent
each step (tool results); trimming keeps the last eight steps whole.
- The result has the one-shot answer's shape (`AIAnswer`), so validation, selection, saving and the app are unchanged.
  `dxf-autoparam ai --oneshot` keeps the old path for comparison.

## 9c. Generic by construction — not a rule per drawing

**Why a new drawing kept breaking something.** A named size was only a LABEL on whatever line-to-line chain the
geometry engine happened to choose for that drawing. If the chain did not use it, rule V9 silently dropped the name
("drives nothing"); what worked therefore depended on each drawing's topology. Read from the agent's own thoughts on
`gad_ezdxf_b`: "I'm grappling with why certain parameter definitions are being rejected" — it could not know.

**The rule now (one rule, every drawing): a named dimension drives its geometry.** For each occurrence of a named
size the engine sets one end out from the other plus the value (both ends about the axis when the size is centred on
one), never moving a line a site level, an AI formula, a slope or a held part sets, reproducing the drawing exactly
and keeping it valid when the value changes. A size that both ends of which other inputs fix is a RESULT, and is
kept as a worked-out quantity (a relation measured between its lines, which notes follow), with the reason ("lies
between y13 (BedLevel) and y32 (follows FormationLevel) …") and how to make it an input instead.

**Agent tools absorb trivia instead of rejecting it** (measured: 12 of 25 steps lost on the failed run): names are
made PascalCase by the tool, one `remove` call removes many things, a region claimed by a part leaves its old part,
structure families with their parts are in the overview (no look-ups), `knowledge` takes several queries.

**The property check, on every drawing** (`dxf-autoparam check *.dxf`, `tests/test_generic_drawings.py`, no AI):
P1 reads and builds regions / CAD JSON / overview · P2 reproduces exactly · P3 every named size drives or is explained
(never lost) · P4 +10 % stays valid or the break is explained · P5 the changed DXF exports and re-opens clean.
Result: 19 views of 16 drawings (slab deck, girder deck, pier, retaining wall, well, 2- and 3-cell boxes, the RCC
half-section, the X-X culvert extension, and the real sheets gad_ezdxf_a / b, gad_r12, drawing2, lsection_oldexport,
mib173 with 2,349 entities) — **all pass, 0 named sizes lost**, exports 12–2,209 entities updated, 0 audit errors.
Run it on any new drawing before spending tokens: a failure there is an engine gap, fixed once for all drawings.

## 10. Running Gemini: model, caches, failures

- **Model:** Gemini 3.8 Flash, thinking **high** (fallback 3.7 Flash @high on 429 / 503 / 504 / timeouts).
- **Answer cache on disk** keyed by everything sent, including model and thinking level.
- **Explicit Vertex prompt cache** for the repeated prefix (system prompt, three pictures, knowledge, CAD JSON);
  the first call creates it, repair rounds send only their rejection list, `close()` deletes it. Per model (a fallback
  builds its own); refused / expired caches fall back to the whole request.
- **Deadlines:** the SDK sends `VERTEX_TIMEOUT_MS` as `X-Server-Timeout`. At 3 min, a repair that thought longer was
  cut off by Vertex with 504 on both models — self-inflicted, not capacity. Default now 10 min.
- **Output budget:** thinking counts against `max_output_tokens`. At 32,768 with high thinking the first X-X answer was
  cut off mid-JSON (finish `MAX_TOKENS`) and crashed the parser. Now: 65,536 by default; a reply that is not complete
  JSON is logged with its (billed) tokens, retried, and — when the thinking ate the budget — retried with medium
  thinking; tokens of failed attempts are added to the run's totals.
- **Thinking, visible:** every call streams (`generate_content_stream`, `include_thoughts=True`); the model's thought
  summaries go to the app as they arrive (Gemini tab, with each call, retry and round verdict) and are stored with the
  answer, so a cached or re-opened answer still shows how it was reached.
- **The person's instructions:** free text (which parts / views to parametrize or keep as drawn, values that will change,
  grouping by region ids) sent after the cached prefix; the prompt says how each kind of instruction maps onto the
  answer (parametrize=false, recommended, fixed constraints …) and that the drawing stays the authority. Repair rounds
  carry them too. **Revise** sends the previous answer + the request + what is still rejected against the same cached
  prefix (the session keeps one client per drawing / view, so its prompt cache serves follow-ups).
- The app runs Gemini as a background job with a progress feed (`/api/ai/progress`); one job at a time; opening another
  drawing or view while it works is refused. **Stop** (`/api/ai/stop`) is checked at every streamed message and in
  back-offs; the stream is closed so Vertex stops generating; a stopped first call keeps what the person had, a stopped
  repair keeps the best validated round. Vertex reports no usage for a cut stream: the stop is logged, the tokens are not.
- Tested without network against a fake Vertex (`tests/test_vertex.py`) and a stand-in Gemini for the app's jobs
  (`tests/test_server_ai.py`); `tools/serve_replay.py` shows the UI with a replayed answer, every event marked [replay].

## 11. Results (X-X, one view, Gemini 3.8 Flash @high, explicit prompt cache)

Measured 2026-10-06 (`tests/fixtures/sectional_elevation_xx.answer.json` is that answer; `tests/test_live_answer.py`
replays it on every test run):

| | round 1 | round 2 | round 3 (kept: best is now chosen) |
|---|---|---|---|
| accepted | 9 levels, 29 params, 13 formulas, 2 relations, 20 parts, 9 constraints, 14 behaviours | … 10 constraints, 21 behaviours | — |
| rejected | 13 | 1 | 2 |
| input / cached tokens | 80,744 / 77,441 (cache created) | 90,701 / 77,441 (reused) | 89,186 / 77,441 (reused) |
| output + thinking | 13,434 + 13,193 (170 s) | 13,504 + 42,291 (337 s) | 13,456 + 16,193 (182 s) |

- **Segmentation:** 20 parts in 3 levels covering all 52 regions — proposed box (barrel, top / bottom slab, courses,
  parapet, apron, drop wall, earth fill), existing box (barrel, top / bottom slab, bedding, headwall, drop wall),
  shoring, tracks (existing vs proposed). Existing headwall / drop wall recommended "keep as drawn".
- **The remaining rejections** (both rounds 2–3) were one engine-side gap: the barrel end's sloped foot was set out from
  the parapet axis, so lengthening the barrel flipped an outline. The engine now re-anchors such a line on the line that
  moves (nearest line of its chain that keeps every entity valid, never setting in motion a part the AI did not say
  moves). Replayed: **0 rejections, 21/21 behaviours confirmed, 10/10 constraints kept**, barrel +1000 mm valid, tracks
  unaffected.
- **Hold existing fixed:** no proposed value moves any existing part (entities owned by length of border; shared set-out
  lines split). One real conflict remains and is reported: with existing work held, widening the proposed track spacing
  +10% pushes the overshoot track into the existing track's zone.
- Edit ProposedBarrelLength 11073 → 12073, ClearHeight 1200 → 1300 (existing held): no issues, notes
  "BARREL LENGTH=12073", "1300", "1300" rewritten, DXF re-opens with 0 audit errors.

Remaining limits: one view at a time; parts are labelled from regions (a part drawn only with open lines needs
`entities`); behaviour checks measure bounding boxes (a part that changes shape inside the same box reads as fixed);
constraint enforcement covers linear constraints only.

## 12. Instruction-guided, assembly-aware plans (`plan.py`, `assembly.py`)

**What was wrong.** A size drove its two lines; which side stayed was decided per size, and everything else hung
where the spanning tree had put it. So an anchor choice (`SheetModel.anchor`, "the start stays") rewrote two lines and
left the middle wall of a two-cell box to absorb the change (300 → 800 mm at ClearSpan 3000 → 2500) — and it was
accepted, because validation proved only that no outline inverted. On a box drawn as separate members the default
set-out grew the two cells from opposite sides and the middle wall inverted at +10 %.

**What a change is now.** A PLAN, built from the person's words and the drawing, stored with the answer (saved,
undone and redone with it), compiled into the existing program and measured before it is committed:

| | |
|---|---|
| driver | a named value, the exact occurrences it drives, the value asked for |
| anchor | one policy for the assembly on that axis — `centered` (about a line; a drawn centre line first), `start_fixed`, `end_fixed`, `as_set_out` — with its evidence (the instruction, an earlier plan, the only policy that keeps a fixed line where it is) or a question listing each alternative's predicted effect per part |
| directives | `keep_value` (the size stays, it may move) · `keep_fixed` (stays where drawn for this edit; stays parametric) · `no_parameter` · `exclude` (held as built, no value of its own) · `preserve` thickness / symmetry / level / connection · `annotations_only` · `follow` · `translate` · `resize` · `review` (unclear: a person decides) |
| tied parts | parts drawn on the assembly's lines, touching it, or only hung on it by the set-out: each needs an accepted behaviour, or the plan asks |
| questions | ambiguous words ("don't touch", "preserve the foundation"), unread text, an undecided anchor, the AI's own inferences |

**Compiled** (inside `validator.apply`): `exclude` → held; `keep_fixed` → its lines that would follow the value are
pinned where drawn; the anchor → `assembly.stack`, which re-sets the assembly's lines on that axis out from the anchor
in closed form — each occurrence pushes what lies beyond it, lines inside an opening stay with their side (a long
occurrence takes its change in its widest free run, never through a short member), every other size keeps its drawn
value, the drawing's own chain formulas and named sizes are reused, and a line a person, a slope, a level or existing
work owns is never rewritten (the policy is refused instead).

**Measured** (`verify_plan`, V16): the value up, down, at the asked value and back; on the regenerated ENTITIES, not
bounding boxes — the driver's occurrences, the anchor line, every assembly line as predicted, fixed parts point by
point, kept values, thickness, symmetry, contacts torn, members running into each other, unrelated parts, dimensions,
notes, every other named value still driving. A failure blocks the commit (`commit_answer`), and slider edits on a
unit with an accepted plan are checked against it.

**Who decides what.** (Revised: see `AGENT_SESSION.md`.) The model reads the instruction — nothing else does. The built-in phrase
matcher (`plan.read_instruction`, generic English against THIS drawing's names) is NOT on any path a person uses: `build_plan(…,
reader=False)` in the agent, and the page has no plan panel any more. It stays as a narrow, non-authoritative first pass for the free
benchmark (`plan-bench`) and tests. What the model proposes is checked, never interpreted: each directive quotes the person's own words
(a clause not in their text makes it a proposal they accept), every sentence of the instruction must be accounted for, references must
resolve, a proposal that contradicts itself on one part is a conflict, and the engine predicts and measures the plan; a person settles
the rest.

**Measured on generated drawings with known intent** (`dxf-autoparam plan-bench`, no model): 54/54 cases (boxes of
1–4 cells drawn as separate members, two views in projection, foundation, wing walls, an unrelated detail; the
generator draws the intended result) — but these phrasings are self-authored. On phrasings written without looking at
the reader: 2/10 and 3/10 before tuning, a third set after tuning 6/12 — and in every set 0 misreadings became an
applicable plan (each became a question). Remaining: the reader's phrasing coverage; one anchor policy per axis and
assembly; dimension lines stay where drawn (their points follow).

## 13. Which side of a size stays — growth direction as design intent (`design_intent.py`)

**The problem.** A named size is two lines. When its value grows one end moves and the other stays, or both move half — and until this layer that was an
accident of the set-out, a tree rooted at the left-most line of each axis: of the 38 named lengths of a ten-unit sheet read by the agent, 26 kept their
start fixed, 11 their end, one its centre (by coincidence). A symmetric box widened on its right side only; a slab thickened into the cell below it.
Nobody had decided that, and nothing said so.

**The decision**, per axis and per *assembly* (the lines that move as one structure — a view of a section and the detail beside it are told apart by the
lines they share), by evidence, in this order — every decision says which evidence it rests on:

| | evidence | result |
|---|---|---|
| 1 SYMMETRY | the faces of the structure the size belongs to mirror about a line (a drawn centre line, the drawing's axis, the middle of a closed outline; plain lines only when most of them mirror, and on the vertical axis only in plan views) | `centered` about it: each side moves half |
| 2 FIXED | only one side can stay: the other would move a stated level, existing work or a held part | that side stays |
| 3 EXISTING | the size is new work against existing work | the existing side stays, the new work grows away from it |
| 4 CONVENTION | nothing in the drawing says | the left / bottom side stays, **marked `provisional`** and shown as an assumption |

What touches a side moves with it (a backfill against a wall, a slab resting on it); what is only hung on the lines by the set-out stays where it is
drawn. Slopes and projections are equations (`x8 = x1 + (y11 − y2)`) and are solved from whichever end the anchor needs.

**Tried for real, never assumed.** Each candidate is written as ordinary plans, the unit is built with them, every promise is measured on the
regenerated geometry (V16), every named size of the unit — not only the planned ones — must still grow 1 mm per mm of its value (an anchor that
rewrites the line a size drives would turn that input into a reading, silently), and a size that was independent must not start to move with another. A
size that breaks a candidate is left out of it (it keeps the set-out's direction, and the decision says so); when no side can stay, the set-out decides, as
drawn, and the decision says what stood in the way (`undecided`). Measured on the nine example drawings with up to ten sizes each taken from the generic
set-out's own tree — which includes sizes that overlap — 8 of the 18 axes could not be decided: an overall width named beside the parts it is the sum of
cannot be an input together with them, and no side can stay for both.

**Stored as plans** with `anchor.source == "design intent"`: measured every time, undone with the step they belong to, saved with the project. A person's
plan (`propose_plan`, `anchor`, the chooser under each value) **always outranks it**, and the default is derived again around their choice. The agent never
sees the derived plans (it starts from what was written; `strip`), so it cannot be misled into thinking a plan exists; `commit_answer` derives them for the
answer it commits (`intent=False` skips; a derived plan that does not hold is dropped and the answer commits without it, `intent_skipped` says why), and
`SheetModel.resolve_intent(unit?)` / `POST /api/sheet/intent` derive them again for work that is older or whose evidence a person changed.

**Where it is seen.** `GET /api/sheet/param` → `growth[]`: per unit, which line stays (measured) and the intent behind it (who, status, evidence). The
Values panel shows it under the value — *Left stays · Centred · Right stays* (bottom/top on y), "engine's default, provisional" in amber, "your choice" —
and a click is the person's own plan. The run's verdict carries a note for every direction that rests on convention or could not be decided, and for the
sizes left out of a structure's growth.

**What it does not do.** It decides a direction, not a design: a structure whose faces do not mirror, with nothing fixed and nothing existing, gets the
convention (and says so). Sizes left out of an assembly keep the set-out's direction. A twin view that shares no line with the section (a detail
drawn beside it) is its own assembly: its sizes follow their own evidence, not the section's.

**Measured.** On the real ten-unit sheet read by the agent (offline copy, nothing paid): the clear span of the half elevation, which grew only to the
right, now grows equally on both sides about the centre of the closed outline (left lines −0.5, right +0.5 per mm), wall thicknesses outward; across
every unit no named size gained a failing check at ±10 % and none stopped being an input. On the generated boxes (1–3 cells) the whole box — walls,
footing, wings, the pitching on them — is where the generator draws it at the new span, centred; on every example drawing the intent either holds or is
absent, the drawing is reproduced exactly at its drawn values and no named size stops driving what it drove (`tests/test_design_intent.py`).

### 13.1 When no side can stay — ways to settle it, each tried for real

An axis ends `undecided` when every way of growing it breaks something. The reason is now said as data, not only as a sentence: the lines nothing may move
(`Stack.blocked` → `AxisDecision.blocked`: line, what sets it — a site level *by name*, a held part *by name*, a part another decision keeps still, a
person's formula, a slope — and how it moves against how the side needs it to) and the sizes the attempts broke on. The Values panel says it under the value
(*Undecided — no side can stay: pinned by site levels FormationLevel, BedLevel*) and offers **Ways to settle it**.

The engine proposes only changes **only a person may make**, each of which it has TRIED, exactly as `_attempt` tries a side:

| change | when it is a candidate | written as |
|---|---|---|
| **leave a pinned level free** | the lines that stood in the way of a side are all site levels: freeing them lets that side stay (the structure then grows away from the level that stays) | the level's role → `derived` (it follows the structure's sizes, and stops being an input) |
| **release a held part** | the blocking lines belong to a part kept as drawn | the part (and what it is made of) parametrized again, its sizes inputs again (`unlock_part`'s rule) |
| **read a size instead of setting it** | the attempts broke on sizes that cannot all be inputs (an overall size named beside the parts it adds up, two overlapping sizes) | the size kept as drawn: a named quantity measured between its lines, not an input |

A candidate is offered only if, with it written into the answer, **(1)** the unit builds with no new finding, **(2)** the intent derived around it decides the
axis (decided or provisional) and leaves nothing that was decided undecided, **(3)** no input stops being one except the ones it names (the card says which
stop and which become inputs — freeing a level makes the size between it and the next one an input), and **(4)** the whole sheet, asked as a commit would ask
it (shared sizes still followed, plans measured, values a person set not lost silently) says yes — then put back exactly. What was tried and did not hold is
listed with why; nothing else is offered. Each card says which side stays, what grows and moves with the size being looked at, which sizes are left out of the
growth, and what a person's own value it would discard (confirmed before it does).

**Choosing** (`SheetModel.settle`, `POST /api/sheet/settle`) writes the change as the person's own decision (`answer["settled"]` records what it was and what it
is, so it is shown, kept, and can be taken back), derives the default again around it (the decision's evidence leads with *your choice: …*), and commits in
**one step** only if the whole sheet holds — one undo takes it back; `unsettle` / *Take back* writes it back and derives again. A choice that no longer
settles the direction when the sheet is checked is not kept. The ways are asked with `GET /api/sheet/settle?name=&unit=` and kept for the revision they were
worked out on (each way builds the unit: seconds per way, bounded to 60 s per axis, and the page says when it stopped).

Two defects found on the way and fixed, because they made the ways untrue: a part an engine-derived plan keeps still was kept still against *every other*
plan too (a foundation held for the width plan blocked the height plan that must move it) — a derived plan's pins now bind its own assembly only (a person's
`keep_fixed` still binds everywhere); and the status / evidence of a derived plan was stamped before the decision was made, so a *provisional* direction showed
as decided, without its evidence — the plans now carry the final decision's.

**Measured** (offline copy of the real project, nothing paid; the page's browser test passes on it and on a generated pinned box): of its 10 units' 17 axes, 8
are undecided. For 5 of them the engine offers verified ways — site levels left free (3 ways on a chain pinned at both ends, each saying which side then stays
and which sizes it leaves out of the growth; 2 on a footing-and-wall pair), the one held part released, one size read instead of set — and for 3 it offers none
and says why. On the nine example drawings (sizes taken from the generic set-out's own tree, which overlap) 7 of the 8 undecided axes get a verified way (a size
read instead of set), the eighth the list of what did not hold. On generated boxes pinned at both ends, freeing either level gives exactly the geometry the
generator draws for that side (`tests/test_design_intent.py`).

**Still undecidable**, and said as such, never offered a guess: a view whose parts hang on another view's lines once that view's decision has rewritten the
set-out (a part "set out from the assembly but the plan says nothing about it": a decision about a *part*, per assembly, that none of the changes above
makes — for a twin view beside the first, one value with an occurrence in each, §13.2 now decides it); two pipes that must stay touching while a size moves them apart, and members that would cross (a connection or a clash, not a pin); an axis whose
only blocker is a person's formula, a slope or existing work (said as "not something to release here"). A way that settles the axis may still leave the size
being looked at *out of the growth* (it keeps the set-out's direction): the card says so, and the value says so after.

### 13.2 One value, two assemblies — a twin view beside the first

A size drawn in two views side by side (two half sections of one bridge, one `ClearSpan`) is one value with an occurrence in each of two assemblies on the
axis. Each assembly's plan is verified on the whole unit, and the value moves the other assembly too — so every candidate for either one failed the same
way (*unrelated part moves*, *fixed part moves*, *a binding was lost*) whichever side was tried, and a symmetric structure was left growing from the left
(a live run: both ends of the span undecided, the span drawn "the right end stays"). Two rules, both about what a plan answers for:

- **The other assembly's parts are not this plan's** (`plan._sibling_parts`): the parts drawn on, or hung from, the lines of the value's occurrences in
  another assembly are neither taken along by this plan (they are not its followers or attached parts) nor held by it, and their movement through the value
  is not "unrelated" — the plan of that assembly answers for them.
- **A candidate must leave every occurrence of every size driving** (`design_intent._holds`): a size in the group is checked on all its occurrences, in every
  assembly, not only on the ones in the assembly being decided (it used to be: a plan that broke the same size in the other view passed, and failed later).

Held on a generated twin (two boxes side by side, one `ClearSpan` and one `OuterWall` for both; `tests/test_design_intent_twin.py`, which fails on the
code before this change): both assemblies are *decided, centred about each view's drawn centre line*, and the two faces of each clear span move equal
distances apart. On the real sheet's twin unit: both assemblies decided centred with `ClearSpan` and `WallThickness`; the two sizes whose plans cannot
stand beside them (`HaunchSize`, `BoulderBackingThickness`) are left out of the growth and said. When every side fails the same way the reason now says so
("whichever side stays the same thing breaks, so it is about the structure and not the side"), instead of listing three identical failures.

Not done, measured: building the group up one size at a time when cutting it down ends with nothing (sizes whose plans take each other's lines) would
decide 6 of the 18 axes the nine examples leave undecided, and two more of the real sheet's — but it adds half again to the derivation of a large unit
(94 → 141 s for the 974-entity section), leaves the dropped sizes without the ways-to-settle that an undecided axis offers, and gives "decided" to an axis of
which one size in five is kept. It waits for a person to say it is wanted.

### 13.3 A person's side choice — the levels a box hangs from, a gap that gives, a middle nobody drew (2026-10-22)

Found on the 173A sheet (`docs/INVESTIGATION_173A.md`): 137 of 183 side choices refused, and the accepted value steps moving the wrong lines. Four rules
changed, each held on generated drawings before the real sheet:

- **A size that spans a held level is a sum across it, not an input** (`build.py`, `deferred`). An overall dimension whose two ends touch no level, with a
  site level strictly inside it, was taken as an inside size — and the box was hung from the road by its clear height and the bottom slab from the top slab
  by the overall height. Such a gap is now ordered after every gap that does not span a level (and an unnamed opening the engine only guessed after the
  named sizes), so it is worked out whenever both sides can be set out from the level: the wearing course and the bottom slab hang from the road level, as
  the production box engine and the CAD agent's level chain set them out. `tests/test_levels_chain.py` (5 of its 9 tests fail on the code before).
- **A push into a held line is taken by a gap nothing holds on the way** (`assembly.absorb`). The nearest gap between the size and the held line that is not
  set out from either side, and not spanned by a named size, gives (an earth cushion under a formation level); the choice is refused only when every gap on
  the way is held, and the refusal names each one with why ("WearingCourseThickness holds it"). A line that may not be rewritten but is itself set out from
  the assembly (a person's formula on it, a slope's foot) is not in the way: it moves with what it hangs on, and it is never taken as the line that stays.
  Only for a side somebody chose (a person, the agent's plan): the engine's own default never makes a gap give (`stack(give=False)` for design intent) —
  with it, a generated box's slabs started growing down into the cell, the cell's clear height giving, because that left no size out
  (`tests/test_design_intent.py` holds that a box still stands on its base).
- **Centred without a drawn middle is about the size's own middle** (`assembly.MID`): each occurrence grows half each way about its own centre — a
  construction line, never drawn. Asked for, never assumed: the design intent still centres only about evidence (§13).
- **A choice is one transaction** (`SheetModel.anchor`): refused, the sheet is exactly as it was (it used to keep the formulas it had cleared on the way);
  accepted, it is one undo step. A refusal says which side would keep what may not move ("— its end (right / top) staying keeps what may not move"), or
  that none would.

Measured on a copy of the owner's work (`tools/sweep_sides.py`, every value stepped, every side tried and undone): side choices accepted 46 of 183 → 74 of
192 at the owner's values, 82 of 192 from the drawing as drawn; value steps 255 of 260 → 271 of 272; no refusal changes the sheet. What still refuses, by
cause: members that would cross (25), a shared value that would stop driving in another view (20 — the stacking is one-dimensional per axis: it pushes a
line beyond the size on another layer too), a held line in the push (27 — most of them right: the road level under a clear height), a size on both axes (6),
one side per axis and assembly (4, below). Not done: two sizes of one assembly on
one axis with different sides (`compile_plans` still refuses plans that disagree on the anchor).

### 13.4 Two structures on one line, a part kept as drawn, a person's side (2026-10-26)

Found on Bridge No.7A after a paid run (`out/agent-logs/FINDINGS-20261026-7A.md`), each fixed generically and measured on a copy of the saved work:

- **Existing and new work on one line are two lines** (`intent.split_structures`, called by `validator.apply` before anything is bound). In a longitudinal
  section the old box and its extension run along the same horizontal lines (soffit, top of slab); a value named on one moved the other. A line both
  structures run *along* gets an existing copy (`<line>e`): the existing work's entities, its parts and the sizes measured on it (the agent's `component`
  first, else the entities drawn across the gap, else the region it was observed in) move to the copy, and each is set out from its own sizes. Kept as one:
  a line where they *meet across* (the joint at the old box's end — the extension stays attached), a level that is a site input or a check, a line with
  a formula on it. Every build starts by putting the split back (`unsplit_structures`; `Gap.split_of`), so it never outlives its answer. 7A's
  L-section: values moving both structures 12 of 19 → 10 of 19; what remains is the joints and lines set out from the other structure through a chain.
- **Each structure is set out from its own lines** (`build.Decisions.owner`): a gap from a line only existing work uses to one only new work uses is
  taken last, so neither hangs from the other except through a joint or a level. And a size's "what touches the assembly follows" stops at the other
  structure (`plan.build_plan`): the extension touching the old box at their joint no longer follows the old box's values. Still open (measured on
  7A's L-section after both, intent re-derived: 11 of 19 values move both structures): the joints along the barrel, and the stacking, which pushes
  every line beyond a size on its axis — the other structure's lines on that axis too.
- **A part kept as drawn stays where it is drawn**, so a size that pushes into it is refused. Holding the fill beside a box left its clear span unable to
  grow from the centre. define_parts now says what a held part meets, the refusal names the part ("x3 is set by a held part (EarthFillSlope, kept as drawn
  where it is: release it and it follows …)"), and the agent is told to hold only what a draftsman never changes.
- **A person's side carries what the default carries**: `_person_plan` adds the "what touches the assembly moves with its side" directive the design-intent
  plans have — a side used to be refused for a course under the box the plan said nothing about.
