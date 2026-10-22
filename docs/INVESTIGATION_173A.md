# Why the 173A session failed — root causes, evidence, and what was changed (2026-10-21)

Traced from the run's own records and reproduced on copies (never through the live server). No paid model was called for any of this (one free
Token Harbor evaluation on a generated drawing, §4).

| Source | What it holds |
|---|---|
| `out/agent-logs/20261021-162110/` | run R1 (gemini-3.8 / 3.7 flash, 112 turns, 120 tool calls, ended `partial`): `events.jsonl`, `run.log`, `sheet.log`, the 40 pictures the model was given |
| `out/agent-logs/20261021-investigation/owner-2136.autoparam.json` | the owner's saved work at 21:36 (revision 338: the run's result plus four hours of the owner's own edits) |
| `out/agent-logs/20261021-investigation/*.py` | the reproduction scripts (each reads a copy; see "Reproduce" at the end) |

## 1. What the person met, measured

- **Value steps are accepted, the geometry they produce is wrong.** Every one of the 69 values stepped ±10 % / ±10 mm (levels ±0.1 m) on the owner's copy:
  255 of 260 steps accepted (`steps-owner.jsonl`). But U01's set-out hangs the bottom slab from the TOP of the box: `y3 = y11 − GapY2` (`setout.py … U01 y`),
  where `GapY2` is the 3800 overall-height dimension the engine named itself. Raising ClearHeight by 500 with the road level held lifts the bottom
  slab, the PCC and the granular fill by 500 too; the 3800 dimension stays "3800" because both its feet rose (`dims_follow.py … ClearHeight=3350`).
  At the owner's values (ClearHeight 2798) the bottom slab sat 52 mm low: the wearing course drawn as 150 was 202, under a note still saying 150.
- **Side choices are refused.** 137 of 183 (75 %) start / centre / end choices were refused (`anchors-all.jsonl`); in the box section and its neighbours
  (U01–U04) almost all of them. The reasons, counted: centre needs a drawn line at the middle (50); members would cross (24 — in U01 a knock-on of the
  drifting bottom slab: the 1:1 slope is set out from the bottom of the PCC, which drifted, so it ran into the road-level kink); a held level in the push
  with nothing allowed to absorb (`…is set by a site level … needs +1`, 20, every ClearHeight / top-slab / fill choice in U01 among them); a shared value
  would stop driving in its own unit (12); the size does not drive / is worked out (6); a size on both axes (5); a person's value the new
  parametrization would drop (5); one side per axis per assembly (`plans on the y axis disagree`, 4); others (11).
- **A refused side choice changed the drawing anyway** (`U08.Rise1`: the formulas were cleared before the plan was tried, and stayed cleared).
- **Dimensions follow what they stand on.** On U01, 12 of 12 linear dimensions moved with the edge under each foot for every single change tried, and their
  text took the new measure. What looked like "dimensions not moving" was the geometry under them moving the wrong way (above), or an aligned dimension
  tilting because one of its two feet moved and the other did not.

## 2. Root causes (first divergence first)

**RC-1 — an overall dimension that spans a held level becomes a load-bearing input.** `build.py` sizes a structure "from inside" before hanging it on its
levels (`pin_key`). The 3800 overall height (y3–y11) touches no held level at its ends, so it is taken as an inside size — but the road level (y6, a site
input after `set_levels`) lies *inside* it. The box is then hung from the road by ClearHeight, the bottom slab from the top slab by 3800, and the real
gap between the road and the bottom slab (the 150 wearing course) becomes the "worked out" one. First divergence: turn 15 (`set_levels` made y6 a site
input), after which the agent's `WearingCourseThickness` (accepted as worked out at turn 14) never became an input, and later `share_sizes` refused it
("U01 has no candidate WearingCourseThickness", turns 39, 60). Independent evidence that the chain is wrong: the production railway box engine sets
`z_bot = bedLvl − wearC − tSB` (bed level, wearing course, bottom slab — `production show railway_rcc_box`), and the CAD agent's level chain for a box
hangs every level from the bed / road level (`aagento-bridge/knowledge/formulas.json`, `chain.rcc_box`).

**RC-2 — a side choice pushes everything beyond the size, held levels included.** `assembly.predicted` moves every line beyond an occurrence by the change,
up to the edge of the assembly. A held level beyond it (formation above the slab, road below) cannot move, so the choice is refused — even where the
drawing has a gap nothing holds (the earth cushion between the fill and the formation level) that is exactly what should absorb the change. The plain set-out
already lets that gap absorb (a value step works); the person's explicit choice cannot.

**RC-3 — "centred" needs a drawn line at the middle.** `centre_candidates` looks only for an existing datum at the middle of the occurrence or assembly; a
thickness, a footing, a course has none. 50 refusals.

**RC-4 — one anchor per axis per assembly.** `compile_plans` refuses two plans on one axis and assembly with different policies, so a person cannot say
"this course grows down, that wall grows up". Documented as a known limit (DESIGN_INTENT §12).

**RC-5 — a refusal is not a transaction.** `SheetModel.anchor` commits the cleared hand-written formulas before it builds the plan; when the plan is refused the
formulas stay cleared and the revision moved.

**RC-6 — the clarifying-question commitment is never checked.** `account_instruction` lets a clause be `handled_by: question`; `Bench.commitments` has no
branch for it, so it passes with no question asked. The model read the "ask me" sentences (thinking at turns 1, 21, 33), asked nothing, and recorded an
assumption instead ("Standard RDSO detail uses 600 mm boulder backing", turn 86); the gate said `commitments_kept ✓`. The engine's own undecided /
provisional growth directions — exactly the case the instruction said to ask about — are hidden from the model (`design_intent.strip`) and never turn into
a question.

**RC-7 — a shared value cannot take another view.** `share_sizes` refuses a value that is already shared ("already shared", 4 times for TopSlabThickness
with the earth-retainer detail); there is no way to add an occurrence, so the third view kept its own TopSlabThickness (the owner later changed it alone).

**RC-8 — parts are not checked against the drawing's own labels.** In the long section the agent's `ToeWalls` are the two height-gauge frames (the label
"HEIGHT GAUGE (AS PER DWG. NO. RDSO/M-0001)" with its leader on them; `render_parts.py … ToeWalls`). The label was readable on the tile it was given
(IMG5). `inspect_regions` reports notes inside a region, not labels whose leader points at it, and `define_parts` accepts any name for any region.

**RC-9 — the pictures bury the drawing.** A tile of the long section carries ~100 line labels in its margins, hairlines across the whole drawing and
the tile frames drawn over the overview (IMG4, IMG5); the overview of a large unit is too small for its text, which the model must then get from tiles.

**RC-10 — the look budget blocks verification.** `what_moves(ClearHeight)` at turn 99 was refused ("you have looked for 12 turns without an edit"): the
agent was checking the anomaly the person's own edit had made.

## 3. Plan — generic fixes, each proven offline

1. RC-1 in `build.py`: a gap with a held (site-input) line strictly inside it is a sum across that level — ordered after every gap that does not span
   one, so it is worked out whenever the two sides can be set out from the level. Test: a generated box section with road / formation levels and an
   overall dimension; ClearHeight moves only the top; the overall dimension follows.
2. RC-2 in `assembly.stack`: a push that reaches a held line stops at the nearest gap the set-out does not hold (a worked-out gap) between the size and that
   line — that gap absorbs; refused only when every gap on the way is held, saying which.
3. RC-3: centred about the middle of the occurrence itself when no line is drawn there (a construction line, never drawn).
4. RC-4: plans with different sides on one axis and assembly compiled together (each size's own side), where their predictions are compatible.
5. RC-5: `anchor` as a transaction — nothing kept when refused.
6. RC-6: a `question` commitment needs a question asked (or a stated reason the condition did not arise); the growth directions of named sizes that rest on
   convention or could not be decided are told to the model when the person asked to be asked.
7. RC-7: `share_sizes` extends an existing shared value with new occurrences.
8. RC-8: `inspect_regions` reports the labels pointing at each region; `define_parts` flags a part whose regions the drawing labels as something else.
9. RC-9: model pictures without hairlines over the drawing, line labels capped to the lines that matter, tile frames only on a separate key picture.
10. RC-10: verification reads (`what_moves`, `inspect_lines`, `check_behaviour`) are not counted as idle looking.
11. UI: original geometry dashed in its own colour on top of nothing important, a non-blue dark accent, the camera kept on selection and edits (checked in
    headless Chrome).

## 4. Results (2026-10-22) — measured offline, no paid model called

| | before | after | how measured |
|---|---|---|---|
| side choices accepted, the owner's values | 46 of 183 (25 %) | 74 of 192 (39 %) | `tools/sweep_sides.py` on the 21:36 copy |
| side choices accepted, from the drawing as drawn | — | 82 of 192 (43 %) | the same, `--from-drawn` |
| value steps accepted (±10 %, ±10 mm, levels ±0.1 m) | 255 of 260 | 271 of 272 | the same |
| refusals that changed the sheet | 1 (`U08.Rise1`) | 0 | the same (`mutated_on_refusal`) |
| U01 (the box section): side choices accepted | 0 of 36 | 8 of 36 (10 from as drawn) | the same |
| U01: what ClearHeight +500 moves (road level held) | the bottom slab, PCC and fill +500; the 3800 stays "3800" | the top slab and above only; the overall dimension reads 4300 | `setout.py`, `dims_follow.py` |

(The values listed changed with RC-1: `U01.WearingCourseThickness` is an input now and `U01.GapY2` — the 3800 overall height the engine had named — is
worked out; `U02.ThkY4`, `U03_05.Rise1` and `U03_05.ThkY16` are inputs the reordered set-out now lists.)

What each root cause became:

- **RC-1 fixed** (`build.py`, `deferred`): U01 now sets out `y4 = y6 − WearingCourseThickness`, `y3 = y4 − BottomSlabThickness`. Generated box between road
  and formation levels: `tests/test_levels_chain.py`, 9 tests, 5 fail on the old code.
- **RC-2 fixed** (`assembly.absorb`): the nearest gap nothing holds absorbs a push into a held line; refused only when every gap is held, each named with why.
  Found on the way and fixed: a line that may not be rewritten but is set out from the assembly (a person's formula) was taken as the line that stays, and
  11 side choices in U08 that had been accepted were refused until it was not (`tests/test_anchor_absorb.py`, 13 expected outcomes, + 4 tests); and the
  full suite caught the engine's own default using it — a generated box's slabs grew down into the cell — so a gap gives only for a side somebody chose.
- **RC-3 fixed** (`assembly.MID`): centred about the size's own middle when nothing is drawn there.
- **RC-4 not done.** Two plans with different sides on one axis and assembly are still refused (4 of the remaining refusals). DESIGN_INTENT §13.3.
- **RC-5 fixed** (`SheetModel.anchor` as a transaction; a refusal says which side would keep what may not move, or that none would).
- **RC-6 fixed** (`ai/run.py`): a `question` commitment needs a question asked or answered (or the clause accounted for again with why); `finish` lists the
  undecided / convention growth directions when one is open. `tests/test_run_tasks.py` +3.
- **RC-7 fixed** (`SheetModel.share` extends a shared value with new views; `share_sizes` takes one new occurrence of an existing name).
  `tests/test_share_extend.py`, 4 tests.
- **RC-8 fixed** (`ai/labels.py`): `inspect_regions` → `labelled`; `define_parts` → `drawing_says` / `label_doubt`; `finish` lists the doubts; the page's
  parts list shows them. `tests/test_labels.py` (the height-gauge case, generated).
- **RC-9 fixed** (`viewplan.MAX_LABELLED` 24, hairlines only up to 16 labels, tile corners instead of frames). The picture tests pass; the model's reading
  of the cleaner pictures is NOT VERIFIED (that needs a model run).
- **RC-10 fixed** (`ai/loop.py`): the reads that verify an edit get twice the look allowance once something was edited. `tests/test_run_tasks.py` +1.
- **UI**: dark accent amber (no blue in dark); the original dashed in its own colour under the current drawing, on by default, read once per changed
  entity; the drawing stays put on the screen when a panel opens or closes (the cause of the "reset" on a selection: the canvas centre moved with the
  panel); a parts tree with highlight and label doubts; a progress bar and "Regenerating…" while a stepped value is out. `web/test` 129 pass,
  `node e2e/workspace.e2e.mjs` 52 of 52, `node e2e/agent.e2e.mjs` 67 of 67 — which now checks what the person sees: two corners of the drawing stay at
  the same window position through the whole run, the Agent dock opening included (it compared the camera state, which a resize now changes on purpose).

Verified on the final tree: `uv run pytest tests` 785 passed (17.5 min); `uv run ruff check src tests tools` clean; web typecheck, vitest, build;
both e2e above; `dxf-autoparam agent-eval` (scripted, free): the careful script 1.00 in every category, the careless and wrong-part ones caught.

One real model, at no cost (`agent-eval --free deepseek-v4-flash:free`, the generated two-view box; nothing of the owner's drawing was sent): the first
attempt ended `failed` on its second turn — Token Harbor, under heavy load, answered 200 with a body that was not JSON and the decode error went through the
loop; fixed in `ai/gateway.py` (tried again like a server error, then named as not answering; `tests/test_tokenharbor.py`). The second: 24 turns, 47 tool
calls, 21 min, not finished when scored. It asked 4 multiple-choice questions (the foundation level, which views to change), named the four sizes right and
took the anchor from the instruction; it put 4 of 8 parts on the wrong regions and applied nothing (AI 0.69, engine integrity 1.00, unsafe 0). One run of
one free model: not a measurement of Gemini, and no before/after — the effect of these fixes on a paid Gemini run is NOT VERIFIED.

What still refuses (owner's values, 118): members that would cross (25 — the plan check is stricter than a value step, which accepts the same value: an
inconsistency left open), a shared value that would stop driving in another view (20 — the stacking is one-dimensional per axis: `U02.FootingRearProjection`
pushes every line beyond the footing's rear edge, the boulder backing's outer face on the wall above it included, so `BoulderBackingThickness`
spans the push and would become worked out; a push limited to the lines the moving face actually carries, in two dimensions, is the fix, not done),
a held line in the push (27: 14 with every gap on the way held, 13 with none — most of them right: a clear height whose lower line is the road level cannot
grow downward, and the refusal now says which side can), nothing on the axis left to stay when centred about the size's own middle (7), a size on both
axes (6), a person's value the new set-out would drop (6), worked-out sizes (6), unrelated parts moving (5), RC-4 (4), others (12). Measured with the
final code (`sides-final-owner.log`, `sides-final-drawn.log` in the investigation folder).

Not verified: a Gemini run on the fixed code (the question commitment, the label doubts and the cleaner pictures are proven with scripted models on
generated drawings, and seen once with a free model, below). The owner's server must be restarted to run this code.

## 5. Reproduce

```bash
cp ~/.local/state/dxf-autoparam/173A-<hash>.autoparam.json out/agent-logs/<dir>/copy.autoparam.json
uv run python tools/sweep_sides.py ~/Downloads/173A.dxf out/agent-logs/<dir>/copy.autoparam.json --out out/agent-logs/<dir>/sides.jsonl    # ~16 min
uv run pytest tests/test_levels_chain.py tests/test_anchor_absorb.py tests/test_share_extend.py tests/test_labels.py tests/test_run_tasks.py -q
cd web && bun run test && node e2e/workspace.e2e.mjs --out ../out/agent-logs/<dir>/e2e
```

The investigation's own scripts (set-out per axis, dimension feet, part renders, the run trace) are in the git-ignored
`out/agent-logs/20261021-investigation/`.

## 6. Research used

- Driving vs driven dimensions: a dimension that would over-constrain a closed profile is made driven (reference) — SolidWorks
  ([automatic driven dimensions](https://help.solidworks.com/2019/english/SolidWorks/sldworks/c_driven_dimensions.htm)), Inventor
  ([driven dimensions](https://help.autodesk.com/cloudhelp/2023/ENU/Inventor-Help/files/GUID-026FE8D3-AFBB-4834-BC18-73D9CFF78185.htm)), Altair
  ([reference values](https://2022.help.altair.com/2022/cast/en_us/topics/shared/parametric/sketching/dimension_c.htm)). RC-1 is that rule for a
  sum that spans a held level: worked out, never the input that carries the chain.
- DXF linear dimensions: `defpoint2` / `defpoint3` are the extension-line origins, `defpoint` the dimension line
  ([ezdxf](https://ezdxf.readthedocs.io/en/stable/dxfentities/dimension.html)) — what the engine moves with the edges (the dimensions were right, §1).
- Marks on pictures for a vision model: Set-of-Mark prompting ([arXiv 2310.11441](https://arxiv.org/pdf/2310.11441)) — numbered marks on regions ground
  the model's answers, and they must stay readable; nothing there sets a number, so the caps here (24 labels, 16 hairlines) are this repo's own, unmeasured.
