# The agent session — one instruction, one run

What replaced the three Run buttons and the rule-based "Plan a change" panel. Everything here is implemented and tested
(`tests/test_run.py`, `tests/test_run_plan.py`, `tests/test_statement.py`, `tests/test_domain.py`, `tests/test_acceptance.py`, `tests/test_baseline.py`, `tools/ui_check.mjs`); the model is replaced by a
script in every test, so nothing has been billed.

## What the person does

The Agent tab has one prompt, a scope (this view · the selection · the value in focus · the whole drawing — context for the prompt, never
a second set of instructions), **Run**, and while it works **Stop**. The agent decides which stages the task needs. A run is always in one
state of a machine, and the page shows only what the server reports:

```
queued → running ⇄ paused (only if chunks were asked)  ⇄ awaiting_user (a decision is the person's)
                 → stopping → stopped                   ⇄ exhausted (a hard limit; continuing lifts it)
                 → completed | partial | failed         (failed by the model not answering can be retried)
```

`completed` only when every criterion of the verdict holds; otherwise `partial` with the list of what remains. The verdict is derived
from the engine, never from a message: finished by the engine's gate · every unit's edits applied to the sheet · nothing pending · no
open problem · every accepted plan measured (V16) · every requested value applied · nothing waiting for the person · no refused edit left
(each is asked again of the engine's current state) · shared values still drive their views · every sentence of the instruction accounted for ·
**the model's own commitments kept** (a clause it said a plan / links / views / parts / values would handle was handled) · **the plan it stated
still holds on the sheet**. Beside the criteria the verdict carries `notes` (things to read that are not failures: what was left out on
purpose and why, what the plan leaves out, a group the engine doubted that nobody looked at, views never parametrized), `given_up`, the
plan itself, and `finish_summary` — what the model said it did, whole.

## Who does what

| The model (Gemini, via `ai/vertex.py`) | The engine (deterministic) |
|---|---|
| reads the instruction clause by clause (`account_instruction`: its quote, what it means, what handles it) | checks every quote is in the person's text and every sentence is accounted for |
| looks: the sheet and the open view as pictures, `inspect_sheet`, `zoom_view` (as often as it needs) | draws the pictures from the regenerated geometry, stamped with the revision, with ids and the pixel frame |
| names views (`describe_views`), parts, values, levels, links (`share_sizes`), formulas, constraints | validates every edit at once (V1–V15), measures every binding, takes back what breaks the drawing; a relation that names nothing (a bare number) is refused |
| states the plan across views (`state_plan`): which components and dimensions appear in more than one view, as which part or value, how they relate, how that is bound — and what it assumed | checks every unit, view, part and value exists and every binding it claims is on the sheet (a shared value that drives each unit, views in projection, a relation between the views) or is said to be only noted; counts what the plan leaves out |
| proposes the plan (`propose_plan`: value, anchor, directives with the person's words, its own questions) | resolves references, predicts each anchor, asks what only a person can decide, compiles the accepted plan into the set-out, measures it (V16) |
| asks (`ask_person`) | pauses the run, applies the person's answers itself (not relayed by the model) and rebuilds the waiting plans |
| `finish` | the gate, then the sheet's transaction: refused as a whole, with nothing changed, if the sheet changed meanwhile or would no longer hold |

No second engine or solver: the closed-form datum program (`program.py`, `assembly.py`, `plan.py`) is what compiles and regenerates. A general
constraint solver was not needed for what is supported (linear set-out, anchors, equalities); a case outside that is refused or asked,
not approximated.

## Budgets never cut good work (`ai/loop.py`)

`Budget`: `soft_turns` (a chunk — only when a person asks for chunks: the run pauses and can be continued, nothing lost, nothing done twice;
**0, the default, never pauses**), `max_turns` (1000), `max_tool_calls` (6000), `wall_s` (4 h of working time; waiting for a person does not
count), `max_tokens` (2 M output + thinking), `call_s` (one model call), and a limit on turns of only looking. The hard limits are safety nets
against a model that loops, set so that a sheet of any size finishes inside them. When a run does reach one, **continuing lifts exactly the
limit that was reached** by another allowance of its own size (and says so in the timeline); nobody has to type a number. Set per run in the
page (Options and budget) or by `AUTOPARAM_*` / `VERTEX_AGENT_MAX_STEPS`. Stop abandons the
call in flight; the turn it would have made does not happen. A change made by a person while the run works is never overwritten silently:
the run asks whether to apply its edits on top of it.

## What a refused edit is, and what repairs it

The engine takes a refused size back at once, so "the size is no longer in the answer" proves nothing. A refusal is therefore tracked **by its
name** (`define_parameters` item, a shared name, a relation between views, a link in the plan) and is closed only by the **state** the engine
shows now: the size kept by a program that reproduces the drawing, the shared value bound to every unit it named, the link stored in the plan.
A sheet tool that applies part of a call and refuses the rest (`share_sizes`, `describe_views`, `state_plan`) answers `ok: false, partial: true`
and lists what was applied and what was not; what was applied stays applied, what was refused stays open. Leaving one out **on purpose** is
a different, explicit act, and it is said in the verdict (`given_up`, a note): `remove` of the size, `set_relation` with an empty expression,
or a plan link with `bound_by: noted_only` that names the refused share. `finish` is refused once while any of this is open (with the list), and
a second `finish` ends the run with what holds — the verdict then says what is open.

## The plan across views (`ai/statement.py`)

When the instruction asks for it — or whenever views relate — the model states the plan with `state_plan`: for every component or dimension that
appears in more than one view, the places (`unit` / `view`, `part` and / or `value`), how they relate (`same_component`, `detail_of`,
`same_dimension`, `same_dimension_other_scale`, `derived_from`, `other`) and how that is bound (`shared_value`, `projection`, `view_relation`,
`noted_only`), plus assumptions and a summary. Nothing is read for meaning: the names are the model's own. The engine refuses a link that names a
unit, view, part or value the sheet does not hold (and says what it does hold), and a binding that is not there (a shared value that does not
drive every unit named; "projection" across two units; views the sheet does not relate). It is kept in the project (one undoable step, per run;
a reset clears it), asked again of the sheet when the run ends (`plan holds`), and shown in the page. It also **counts what the model did across
views that the plan leaves out**: a shared value not in it, a relation between views with no component in common listed, a name used in several
units for the same value (neither shared nor in the plan), a part name in several units. The model sees these at its first `finish`; the person
sees them as notes. `noted_only` is how a relation the engine cannot tie stays honest: it is shown as "not enforced".

## Groups that are not views

`inspect_sheet` lists `views` (only views) and `other_groups` (tables, notes, the title block) with what each holds as the engine counted it
(drawn items, curved ones, dimensions, texts). A group taken for a table that holds a view's content (many drawn items, dimensions) is
**doubted**, in words, and `zoom_view(view=<its id>)` shows it as drawn. The model says what it is (`describe_views`, `kind`); re-kinded as a
view it becomes a unit of its own (named from the whole id, `UT01`, never taking another unit's name) that can be parametrized. A doubted group
nobody looked at is said at the first `finish` and as a note of a whole-drawing run. In the segmenter a ruled grid with words is a table only
if it holds no dimensions; a plan view that has no hatch used to qualify, because the rule never looked.

## The domain pack is off by default (`ai/domain.py`)

Nothing the model reads names a kind of structure, a family or a value (`tests/test_domain.py` scans every model-visible text for them): the
model names parts, values and levels the way a designer of *this* drawing would, from what it sees, and the engine keeps the names as written.
A pack (`knowledge/<name>.json`: concept names, structure families, formulas, and a drafting guide) is a person's choice for a run
(`options.domain`) or the process (`AUTOPARAM_DOMAIN`); when on, its names are *offered* in the overview and the system prompt, and the
`knowledge` tool exists. The bridge pack is the only one shipped. The engine (analysis, validation, regeneration, the sheet model) never reads it.

## Replaying a recorded run (`tools/replay_trace.py`)

A live run's own model turns are in the client's answer cache (the usage ledger names each key). `RecordedModel` replays them, free, through the
*current* engine: what a change of the engine makes of the model's real behaviour — a call now refused, a promise now checked, a verdict now
different. `--then FILE` adds scripted turns after the recorded ones (never the model's). It is faithful only while the sheet is segmented as it was.

## Pictures

`viewimg.Pictures`: the sheet (views boxed and named), a unit as drawn with its set-out lines or its regions, a crop with every entity tagged
by the id the tools use — all from `display.primitives`, so the picture is what the canvas draws. Every picture carries the revision and
a fingerprint of the geometry drawn; a picture of an older revision is stale, the model is told, and `zoom_view` gives a new one. The
tool result carries the exact position of each tagged entity (the picture is for understanding; the numbers are exact). Pictures go
into the function response as image parts (older ones are dropped from the conversation to bound its cost).

## Value, original, reset, highlight

`baseline.py`: the imported DXF is never edited; a value's original is what its two set-out lines measure on the unmodified analysis
(reported unreliable when it cannot be confirmed). **Reset value** regenerates the sheet without that one override and commits only if
the whole sheet holds; **Reset drawing** returns to the imported state (values, plans, parametrizations, sharing, view corrections), is one
undoable step and keeps the undo history. Clicking a value highlights, by category and across views: what it controls directly, what moves
with it (measured), the notes and dimensions that state it, what a plan keeps fixed or outside the edit, and what waits for a decision;
with the original, the evidence, the lines it sets out, whether it is *validated* (changed a little either way: the sheet regenerates and
something moves), and "Go to view". The **Original** toggle draws the imported geometry of what changed, dotted, from the file's own points.

## Evaluation: the AI and the engine separately (`ai/acceptance.py`)

`dxf-autoparam agent-eval` scores a run in twelve categories against a generated two-view box whose intended result is known exactly:
interpretation, components, values, binding, anchor, dependency planning, invariants, cross-view, geometry, **engine integrity** (the engine
never applies what fails its own promises; a refused change leaves the sheet as imported — whoever erred), validation and recovery,
clarification (a quote not in the person's text counts as unsafe). Offline it runs scripted models of different care — the careless one
loses interpretation and is flagged for a fabricated quote while the engine stays exact; the one that groups the wrong region fails the
geometry and the scores say it was the model's reading, not the engine. `agent-eval --live` is the acceptance run with the real model; it
prints its limits and refuses to start without `--yes-spend` (defaults: 30 turns a chunk, 60 turns, 250 000 output+thinking tokens, 20 min).

## Limits

A run is resumable while the server lives; after a restart its history (verdict, timeline summary) is kept in the project, its in-flight
state is not. One anchor policy per axis and assembly. Dimension lines keep their drawn place. Pictures are drawn by this project's
renderer (text in one font, hatches as faint fills), not by a CAD viewer. The model's reading is untested live; no accuracy figure for
the real model exists until the acceptance run is made.
