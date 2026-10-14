---
{"id": "gad-workflow", "title": "From a drawing to a checked parametric model, using the library", "kind": "workflow",
 "purpose": "The order of work for a whole sheet — observe, retrieve, plan, act, verify, correct — and where library knowledge enters each step.",
 "applies_to": ["any sheet"],
 "tools": ["inspect_sheet", "zoom_view", "list_skills", "load_skill", "search_library", "account_instruction", "open_unit", "define_parts", "define_parameters", "set_levels", "set_formulas", "check_rule", "state_plan", "record_finding", "finish"],
 "related": ["read-the-drawing", "name-and-bind-sizes", "relate-views-and-levels", "handle-uncertainty"],
 "derived_from": ["skills/README.md", "skills/find-source-evidence/SKILL.md"]}
---
## Purpose
Work the sheet in a loop that checks itself: look, retrieve only what the drawing calls for, plan, make small edits the engine checks, compare
with what the library documents, and correct. The library is context for the loop. The engine and the drawing decide every value.

## Applicability
Any sheet. When no skill matches the drawing's printed words, the general recipes still apply and the model names everything from what it sees.

## Required inputs
- The person's instruction (account_instruction first), the sheet and the open view as pictures, and `inspect_sheet`.
- The drawing's own printed words (what `list_skills` matches on).

## Procedure
1. **Observe.** `inspect_sheet`, then `zoom_view` what you need. Read the printed words: title, notes, labels, level texts. A group the engine
   took for a table may be a view: look.
2. **Retrieve (progressively).** `list_skills` shows which skills match the drawing's words. Load the recipe you need (`read-the-drawing`
   first), then the matching structure skill's `recognition` section. Load `components`, `representation`, `rules` only when you are using
   them. `search_library` for a word or a definition; `get_reference` for one record. Do not load what the task does not need.
3. **Decide what the drawing is** from the drawing, using the library's cues as questions to put to it. Say it with `set_structure`.
   If cues disagree, or two skills fit, ask_person or say so in `record_finding` (kind gap).
4. **Plan.** `account_instruction` (every sentence of the person's request accounted for), `propose_plan` for a change, `state_plan` for
   what appears in more than one view.
5. **Act in small checked batches.** `open_unit`, `define_parts`, `define_parameters`, `set_levels`, `set_formulas`, `share_sizes`.
   The engine validates every batch and takes back what breaks the drawing.
6. **Verify against documented definitions.** `check_rule` with the library's definitions and the values you defined: a difference is a
   question to answer (a datum read differently, a value bound to the wrong size), never an edit made to match the library.
7. **Correct or stop.** A refusal comes back with expected / measured / cause: repair what is yours, ask the person for what is theirs.
   Stop (finish) when the engine's gate accepts; never loop on the same refusal.
8. **Leave a trace.** `record_finding` for what you applied, assumed, found in conflict, or could not settle.

## Dependencies
Recipes `read-the-drawing`, `name-and-bind-sizes`, `relate-views-and-levels`, `handle-uncertainty`; the structure skills (`family:*`).

## Outputs
A parametric model the engine has checked; a plan across views; findings that cite what was applied.

## Validation
The engine's checks (V1–V16, the finish gate), `check_rule` for documented definitions (advisory), and the run's verdict, which lists
what the library was used for.

## Failure handling
- A tool refusal: read `failure.cause` and `failure.repair`; "person" means ask.
- The library has nothing for this drawing: continue without it; that is normal, not an error.
- The library and the drawing disagree: the drawing wins; record the conflict.
- The run's library budget is used up: work from what you already loaded.

## Source traceability
Adapted for this agent from the source skills `skills/README.md` and `skills/find-source-evidence` (migrated under `knowledge/agent_context`).
The loop itself is this project's: see `docs/AGENT_SESSION.md`.
