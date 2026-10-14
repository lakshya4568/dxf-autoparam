---
name: propose-dimension-bindings
description: Use to suggest which written dimension may set which parameter on a drawing. This is the binding playbook. In this repository every binding stays blocked until a person verifies the value and its unit; use it to prepare candidates for that review.
---

# Propose dimension bindings (binding playbook)

## Status today
Binding is **blocked** for every record in this repository. There is no human verification of any printed value, unit or scope. The steps below prepare candidates for a person to verify. They do not bind anything.

## When to use
- A person asks which written dimension should set a parameter, and wants the candidates prepared.
- Before changing a model value, to confirm the value came from a verified dimension.

## Conditions that must ALL hold before a binding can be proposed as ready
1. **Verified text and units.** The printed text was checked by a person against the picture, and its unit is printed or confirmed. Not in this repository today.
2. **Correct scope.** The dimension belongs to the view and component that the parameter describes. Check `view` and the part it measures.
3. **Measurement target with evidence.** The dimension's `measures_from` and `measures_to` are recorded and supported by the drawing. A pixel measurement of the linework is not part of this layer.
4. **No open dispute.** No `conflicts` entry covers the dimension, and the sheet has no unresolved dispute that touches it. A `superseded` reading is not used.
5. **Anchor and edit policy stated.** Say where the edit would anchor and whether it changes geometry. Without a live CAD snapshot, no CAD entity is named.
6. **User locks respected.** If a runtime CAD snapshot is supplied, its `user_locks` are never overridden.
7. **Deterministic validation before any mutation.** `ctx.py validate <pack>` reports `valid: true`, and every candidate's binding is `blocked` with reasons, or a person has recorded the verification.

## Steps
1. Build the pack: `.venv/bin/python agent-context/ctx.py pack <record_id> --task dimension_binding`.
   To limit it: `--scope '{"dimension_ids": ["D1", "D2"]}'`.
2. Validate: `.venv/bin/python agent-context/ctx.py validate <pack_id>`.
3. For each candidate, read `raw_text` (what is printed), `candidate` (the agent's reading), `binding.reasons`.
4. Resolve the evidence ids you cite: `.venv/bin/python agent-context/ctx.py evidence <evidence_id>`.
5. Write the candidate table: evidence id, printed text, reading, unit, scope, and the reasons that block it.

## Required evidence per candidate
- The evidence id; the printed text; the reading; the unit (or "no unit printed"); the view; the reasons that block it.

## Permitted output
- A candidate list, each marked `candidate_only`, with its blocking reasons.
- The exact verification a person would need to do for each candidate (for example "confirm the unit of D2 against the title block").

## Blocked output
- Any binding marked ready, bound or applied.
- Writing a value into a parameter, a model or a CAD entity.
- Using a knowledge-base formula as if it fixed the value (formulas are text; `executed` is false).

## Abstain or ask for review when
- A reason is `unit_missing`, `confidence_low`, `doubt_recorded`, `superseded_reading`, `unresolved_disputes_on_sheet` or `rows_incomplete`.
- The sheet is ungrounded or partly grounded.
- The page is an RDSO page: its values were read by eye and are not verified (`page_values_not_verified`).
