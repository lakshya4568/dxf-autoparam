# The agent session — one instruction, one run

What replaced the three Run buttons and the rule-based "Plan a change" panel. Everything here is implemented and tested
(`tests/test_run.py`, `tests/test_acceptance.py`, `tests/test_baseline.py`, `tools/ui_check.mjs`); the model is replaced by a
script in every test, so nothing has been billed.

## What the person does

The Agent tab has one prompt, a scope (this view · the selection · the value in focus · the whole drawing — context for the prompt, never
a second set of instructions), **Run**, and while it works **Stop**. The agent decides which stages the task needs. A run is always in one
state of a machine, and the page shows only what the server reports:

```
queued → running ⇄ paused (a chunk of turns used)      ⇄ awaiting_user (a decision is the person's)
                 → stopping → stopped                   ⇄ exhausted (a hard limit; continue with more turns)
                 → completed | partial | failed         (failed by the model not answering can be retried)
```

`completed` only when every criterion of the verdict holds; otherwise `partial` with the list of what remains. The verdict is derived
from the engine, never from a message: finished by the engine's gate · every unit's edits applied to the sheet · nothing pending · no
open problem · every accepted plan measured (V16) · every requested value applied · nothing waiting for the person · no refused edit left
(each is asked again of the engine's current state) · shared values still drive their views · every sentence of the instruction accounted for.

## Who does what

| The model (Gemini, via `ai/vertex.py`) | The engine (deterministic) |
|---|---|
| reads the instruction clause by clause (`account_instruction`: its quote, what it means, what handles it) | checks every quote is in the person's text and every sentence is accounted for |
| looks: the sheet and the open view as pictures, `inspect_sheet`, `zoom_view` (as often as it needs) | draws the pictures from the regenerated geometry, stamped with the revision, with ids and the pixel frame |
| names views (`describe_views`), parts, values, levels, links (`share_sizes`), formulas, constraints | validates every edit at once (V1–V15), measures every binding, takes back what breaks the drawing |
| proposes the plan (`propose_plan`: value, anchor, directives with the person's words, its own questions) | resolves references, predicts each anchor, asks what only a person can decide, compiles the accepted plan into the set-out, measures it (V16) |
| asks (`ask_person`) | pauses the run, applies the person's answers itself (not relayed by the model) and rebuilds the waiting plans |
| `finish` | the gate, then the sheet's transaction: refused as a whole, with nothing changed, if the sheet changed meanwhile or would no longer hold |

No second engine or solver: the closed-form datum program (`program.py`, `assembly.py`, `plan.py`) is what compiles and regenerates. A general
constraint solver was not needed for what is supported (linear set-out, anchors, equalities); a case outside that is refused or asked,
not approximated.

## Budgets pause, they never cut (`ai/loop.py`)

`Budget`: `soft_turns` (a chunk — the run pauses and can be continued, nothing lost, nothing done twice), `max_turns`, `max_tool_calls`,
`wall_s` (working time; waiting for a person does not count), `max_tokens` (output + thinking), `call_s` (one model call), and a limit on
turns of only looking. Set per run in the page (Options and budget) or by `AUTOPARAM_*` / `VERTEX_AGENT_MAX_STEPS`. Stop abandons the
call in flight; the turn it would have made does not happen. A change made by a person while the run works is never overwritten silently:
the run asks whether to apply its edits on top of it.

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
