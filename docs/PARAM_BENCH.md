# The parametrization benchmark — what is measured, how, and the baseline

`tools/param_bench.py` measures how parametric a drawing is, by the engine, with no model call and nothing written to the inputs. It answers the
brief's question — *can the agent parametrize 70–80 % of a representative new GAD?* — with a metric that does not count naming as parametrizing.

```bash
uv run python -I tools/param_bench.py --cases tools/bench_cases.json --ceiling --domain bridge --annotation 10 \
    --out out/agent-logs/<dir>/bench.jsonl --md out/agent-logs/<dir>/bench.md
uv run python -I tools/param_bench.py --cases tools/bench_cases.json --only 173A          # one case, the baseline only
```

The cases (`tools/bench_cases.json`): the owner's two parametrized sheets (173A, 20A — read from a COPY of their saved work), two GADs nobody has
parametrized (Bridge No.7A, mib173), four more real drawings, the generated box culvert of 1–4 cells (`plan_bench.Box`) and the ten `examples/`.
A case whose drawing is not on the machine is skipped and said. Real drawings live in `~/Downloads`, saved work copies in `out/agent-logs/` (both
outside git): to measure fresh saved work, copy the autosave (`~/.local/state/dxf-autoparam/<drawing>-<hash>.autoparam.json`) and point `saved` at
the copy — never at the live file.

## The metric

Everything is measured on the drawing's own **DIMENSION entities** — what its drafter thought worth stating. A dimension is tied to the two set-out
lines its own definition points lie on (`coverage.py`); one whose points lie on no two lines (an angle, a radius, a sloped dimension) is *unread*
and counts against the drawing.

| measure | definition |
|---|---|
| **parametrized** (the headline) | a value somebody NAMED (a person, or the agent — not a value the engine generated, `GapX1`, `ThkY2`…) moves both of the dimension's lines, **and** that value can be edited: its step of +10 % and of −10 % (a level: ±0.1 m) each regenerate the whole sheet with every check holding. share = parametrized / all dimensions |
| driven | the same without the edit test (what `coverage` reports to the agent) |
| editable values | every named value stepped ±10 %: the share whose two steps are both accepted. Each refused step's failed checks by KIND (`refusal.py`): *the edit cannot be drawn* (a real limit), *the model does not carry this change* (a binding is missing), *an accepted plan says otherwise*, *a rule*, *the solver* — and *already failing* when the sheet as it stands fails the same check |
| views | the values bound in more than one view: the share editable — an accepted step means every view measured the new value (the sheet refuses a view that does not follow) |
| annotation | for up to 10 editable lengths: the sheet exported before and after +10 %, every DIMENSION the value drives found in the export by where the engine put it, and the number it shows (its text override, or measurement × DIMLFAC) must have changed in proportion to the distance it measures |
| identified | (cases that list the components the drawing labels itself) a component is found when some part's NAME holds its words; with the dimensions on those parts and how many are parametrized |
| cost | (cases with a recorded run) that run's model calls and tokens from the ledger (`.cache/ai/usage.jsonl`, by the run's start and end), per parametrized dimension. The ledger carries USD only when `VERTEX_PRICES` was set; it was not, so tokens are the measure |

Two states per case:

- **baseline** — the saved work as it is; a drawing nobody parametrized has 0 by definition (the engine names nothing).
- **ceiling** — every dimension the agent's own `coverage` tool lists as not driven is bound through the very path a model's call takes
  (`define_parameters` with the dimension's id, validated item by item, taken back if it breaks the drawing), and the unit committed as a run
  commits it: the whole-sheet checks and the design intent derived (which side of each size stays). Repeated while a pass binds something —
  `coverage` lists a part's first open dimensions, as it would to an agent. The names are placeholders (`Auto<part><n>`): the ceiling says what the
  harness lets an agent reach on that drawing — not what a model will do, and not naming quality. For the generated boxes the saved work is the
  generator's own parametrization (the right names on every occurrence, parts by member): what full knowledge reaches, then the ceiling on top.

What it does not measure: whether a name is the right engineering word, whether a value is a design input or a result, whether the drawn
direction of growth is what a designer would choose (the design intent sweep does that: `tools/sweep_sides.py`), and engineering adequacy (never
claimed).

## Results (2026-10-22/23)

Measured with no model call on 2026-10-22/23 (`tools/bench_cases.json`; raw rows `out/agent-logs/20261022-bench-final/`). 173A
was measured again on the final code (the ceiling bound in passes) and came out identical. The other rows are from the
same day's run on code that differs only by the two speed-ups (no result changes) and those passes, which matter only where a part has more open
dimensions than one coverage listing shows: 20A (2 listed but not yet bound — its ceiling is a lower bound), mib173 (42 listed but not yet bound — its ceiling is a lower bound).
Refresh them with `uv run python -I tools/param_bench.py --cases tools/bench_cases.json --only 20A,mib173 --ceiling --domain bridge`.
Case times are left out: the machine slept during the run.

| case | saved work | dimensions | baseline: parametrized (driven) | ceiling: parametrized (driven) | editable values (baseline → ceiling) | shared values editable in every view | annotation correct |
|---|---|---|---|---|---|---|---|
| 173A | yes | 95 | 58 = 61 % (58) | 83 = 87 % (84) | 46/46 → 64/65 | 10/10 | 32/32 |
| 20A | yes | 136 | 67 = 49 % (86) | 96 = 71 % (116) | 52/59 → 75/83 | 0/0 | 12/12 |
| Bridge-7A | no | 122 | 0 = 0 % (0) | 106 = 87 % (106) | 0/0 → 87/87 | 0/0 | 10/10 |
| mib173 | no | 200 | 0 = 0 % (0) | 144 = 72 % (144) | 0/0 → 106/106 | 0/0 | 19/19 |
| BVP-minor | no | 40 | 0 = 0 % (0) | 39 = 98 % (39) | 0/0 → 30/30 | 0/0 | 40/44 |
| gad-1790232095 | no | 93 | 0 = 0 % (0) | 77 = 83 % (80) | 0/0 → 61/64 | 0/0 | 12/12 |
| L-section | no | 21 | 0 = 0 % (0) | 13 = 62 % (13) | 0/0 → 12/12 | 0/0 | 11/11 |
| BRG80 | no | 0 | 0 = — (0) | 0 = — (0) | 0/0 → 0/0 | 0/0 | — |
| GAD-general | no | 0 | 0 = — (0) | 0 = — (0) | 0/0 → 0/0 | 0/0 | — |
| box-1cell | yes | 7 | 6 = 86 % (6) | 7 = 100 % (7) | 5/5 → 6/6 | 0/0 | 9/9 |
| box-2cell | yes | 8 | 7 = 88 % (7) | 8 = 100 % (8) | 5/5 → 6/6 | 0/0 | 10/10 |
| box-3cell | yes | 9 | 8 = 89 % (8) | 9 = 100 % (9) | 5/5 → 6/6 | 0/0 | 11/11 |
| box-4cell | yes | 10 | 9 = 90 % (9) | 10 = 100 % (10) | 5/5 → 6/6 | 0/0 | 12/12 |
| ex-box-half | no | 18 | 0 = 0 % (0) | 17 = 94 % (17) | 0/0 → 13/13 | 0/0 | 18/18 |
| ex-2cell | no | 11 | 0 = 0 % (0) | 11 = 100 % (11) | 0/0 → 9/9 | 0/0 | 17/17 |
| ex-3cell | no | 11 | 0 = 0 % (0) | 11 = 100 % (11) | 0/0 → 10/10 | 0/0 | 16/16 |
| ex-deck | no | 5 | 0 = 0 % (0) | 5 = 100 % (5) | 0/0 → 5/5 | 0/0 | 5/5 |
| ex-girder | no | 6 | 0 = 0 % (0) | 6 = 100 % (6) | 0/0 → 6/6 | 0/0 | 6/6 |
| ex-pier | no | 6 | 0 = 0 % (0) | 6 = 100 % (6) | 0/0 → 6/6 | 0/0 | 6/6 |
| ex-retaining | no | 6 | 0 = 0 % (0) | 6 = 100 % (6) | 0/0 → 5/5 | 0/0 | 7/7 |
| ex-well | no | 5 | 0 = 0 % (0) | 5 = 100 % (5) | 0/0 → 5/5 | 0/0 | 5/5 |
| ex-xx | no | 0 | 0 = — (0) | 0 = — (0) | 0/0 → 0/0 | 0/0 | — |

### Re-measured on 2026-10-23 (round 2: side choices, named sums, joints, parts at 0)

No model call (raw rows `out/agent-logs/20261023-bench-20A/`, `-7A/`, `-final/`). The table above is the code of 2026-10-22; these rows are the
code of 2026-10-23 (commits `2f19cd1` … `2c0b44a`). The other cases were not re-run.

| case | dimensions | baseline: parametrized (driven) | ceiling: parametrized (driven) | editable values (baseline → ceiling) | annotation correct |
|---|---|---|---|---|---|
| 173A | 95 | 58 = 61 % (58) | 83 = 87 % (84) | 46/46 → 64/65 | 32/32 |
| 20A | 136 | 68 = 50 % (87) | 106 = 78 % (118) | 53/60 → 80/85 | 12/12 |
| Bridge-7A | 122 | 0 = 0 % (0) | 106 = 87 % (106) | 0/0 → 88/88 | 10/10 |
| box-1cell … box-4cell | 7 … 10 | 86 … 90 % | 100 % | 5/5 → 6/6 | all |

20A's gain is the build's named-sum rule (an overall dimension nobody named, made up whole of named or dimensioned sizes, is taken after them; before,
it could leave a named size inside it worked out). The slope rule as first written cost 20A eight dimensions (72 %): it bound corners along a face
that turns, a set-out the design intent cannot stack through; it now binds only along edges that keep their slope.

**2026-10-27 — curved structure** (raw rows `out/agent-logs/20261027-bench-curves/`, all 22 cases, no model call). An ellipse arc or a spline larger
than 10× the drawing's text height is now structure, set out from its two ends (the plans' quarter-ellipse wing walls); a project saved before keeps
reading its curves as marks (its ids number the structure as it was read then). Read fresh, with the curves:

| case | dimensions | ceiling before → now | editable values (ceiling) | annotation correct |
|---|---|---|---|---|
| Bridge-7A | 122 | 106 = 87 % → 112 = 92 % (plan unit 19 → 25 of 31) | 94/94 | 10/10 |
| mib173 | 200 | 144 = 72 % → 186 = 93 % (no structural curve: the gain is not from this change; the earlier figure was one pass, a lower bound) | 141/141 | 19/19 |
| gad-1790232095 | 93 | 77 = 83 % → 80 = 86 % | 64/64 | 12/12 |
| 173A, 20A (saved work, read as made) | 95, 136 | unchanged: 83 = 87 %, 106 = 78 % (baselines 58, 60) | 64/65, 82/87 | 32/32, 12/12 |
| the other 16 (BVP-minor, L-section, BRG80, GAD-general, box-1…4cell, ex-*) | | unchanged | unchanged | unchanged |

Read fresh with the curves, 173A's ceiling was 87 = 92 % (its plan unit 39 → 43 of 50) — measured before the fix of a contact tested on a curve's
chord, so NOT VERIFIED as a final number; its bench case starts from saved work.

Refused ±10 % steps, failed checks by kind (the ceiling where measured, else the baseline):

- 173A: incomplete_model 2
- 20A: incomplete_model 31, invalid_edit 9
- Bridge-7A: none
- mib173: none
- BVP-minor: none
- gad-1790232095: incomplete_model 8
- L-section: none
- BRG80: none
- GAD-general: none
- box-1cell: none
- box-2cell: none
- box-3cell: none
- box-4cell: none
- ex-box-half: none
- ex-2cell: none
- ex-3cell: none
- ex-deck: none
- ex-girder: none
- ex-pier: none
- ex-retaining: none
- ex-well: none
- ex-xx: none

173A: components found by name 16/17

| component | parts | dimensions on them | parametrized |
|---|---|---|---|
| top slab | U01.TopSlab, U03_05.TopSlab | 8 | 6 |
| bottom slab | U01.BottomSlab, U03_05.BottomSlab | 3 | 1 |
| side walls | U01.SideWalls, U03_05.SideWalls | 11 | 11 |
| haunches | U01.Haunches | 0 | 0 |
| wearing course | U01.WearingCourse, U03_05.WearingCourse, U07.WearingCourse | 5 | 3 |
| PCC base course | U01.PccBaseCourse, U02.PccBaseCourse, U03_05.PccBaseCourse, U04.PCCBaseCourse, U07.PccBaseCourse | 8 | 8 |
| granular filling | U01.GranularFilling, U03_05.GranularFilling, U07.GranularFilling | 11 | 8 |
| boulder backing | U01.BoulderBacking, U02.BoulderBacking | 0 | 0 |
| return wall | U02.ReturnWall, U03_05.ReturnWalls | 18 | 10 |
| return wall foundation | U02.Foundation, U04.Foundation | 10 | 9 |
| toe wall | U03_05.ToeWalls, U04.ToeWalls | 12 | 5 |
| shear key | U03_05.ShearKey, U07.ShearKey | 2 | 2 |
| earth retainer | U03_05.EarthRetainer, U06.EarthRetainer | 20 | 14 |
| height gauge | — | 0 | 0 |
| sump | U08.Sump1, U08.Sump2, U09.Sump1, U09.Sump2 | 2 | 2 |
| soak pit | U08.SoakPit, U09.SoakPit | 2 | 2 |
| inspection chamber | U09.InspectionChamber | 0 | 0 |

173A — the recorded run (R1, 2026-10-21, gemini-3.8-flash, 112 turns, partial): 112 model calls, 5,694,436 input tokens (2,157,391 cached), 36,381 output; USD: no price in the ledger; 98,180 input tokens and 1.93 calls per parametrized dimension

20A — the recorded run (R1, 2026-10-20, gemini-3.8-flash, 90 turns, partial): 90 model calls, 2,441,943 input tokens (1,558,076 cached), 16,865 output; USD: no price in the ledger; 36,447 input tokens and 1.34 calls per parametrized dimension

**How to read it.**

- **Before — the two sheets a paid run parametrized (old harness):** 173A is 61 % parametrized as saved
  (58 of 95; every one of its 46 named values editable, all
  10 shared values editable in every view); its longitudinal section only 15/50 — the return walls, toe walls and earth retainer there
  were drawn and dimensioned and not reachable. 20A is 49 % (67 of 136): 86
  are driven by a named value, but 19 of them by values whose ±10 % edit is refused.
- **After — what binding through the new harness reaches (the ceiling):** 173A 87 % (its longitudinal section 39/50), 20A
  71 %. Two GADs nobody had parametrized: Bridge No.7A 87 %, mib173 72 %. Other real drawings: BVP
  98 %, gad-1790232095 83 %, the L-section 62 %. At or above 70 %: 6 of 7 real drawings
  with dimensions; at or above 80 %: 4.
- **Generated drawings:** the box culvert of 1–4 cells — the generator's own parametrization 86–90 %, the rest bound 100 %, every edit accepted;
  the examples 94–100 %.
- **What stops the ceiling** (dimensions not parametrized = unread / driven by a value whose ±10 % edit is refused / listed but not bound — its
  binding refused, or not reached in one pass): 173A 12 = 10 / 1 / 1; 20A 40 = 18 / 20 / 2; Bridge-7A 16 = 16 / 0 / 0; mib173 56 = 14 / 0 / 42; BVP-minor 1 = 1 / 0 / 0; gad-1790232095 16 = 13 / 3 / 0; L-section 8 = 8 / 0 / 0. Unread: a point on no two set-out lines (a slope, a dimension declared horizontal between vertically aligned points —
  it measures 0 —, an angle or a radius). Dimensions that write another number than they measure (their number cannot follow, said by
  coverage): mib173 19, BVP-minor 4.
- **Failed checks of the refused ±10 % edits, by kind** (the ceiling): 20A — the model does not carry it 31, the edit cannot be drawn 9; 173A — the model does not carry it 2; gad-1790232095 — the model does not carry it 8; every other case none.
- **Annotation:** every dimension the sampled edits drive showed its new number after export, except the four checks on BVP of one dimension that
  writes 3600 over 3425 drawn — the drawing's own disagreement, which coverage now says.
- **Components found by name on 173A:** 16 of 17 that the drawing labels (not the height gauge — and the L-section's
  "ToeWalls" ARE the height gauges, F6: found by name, wrong by geometry).
- **Cost of the recorded runs (old harness):** 173A R1 112 calls, 5,694,436 input tokens (2,157,391 cached) —
  98,180 input tokens and 1.93 calls per parametrized dimension; 20A R1
  90 calls, 2,441,943 — 36,447 and 1.34. No USD: the ledger
  has no price (`VERTEX_PRICES` unset).

**Against the 70–80 % target:** the harness lets an agent reach it on 6 of 7 real drawings, and 80 % or more on 4. What a MODEL
reaches with the new harness is **NOT VERIFIED**: it needs one paid run (the owner's go-ahead); the free models were too slow to measure it
(`docs/BRIDGE_GEOMETRY_HARNESS.md`).
