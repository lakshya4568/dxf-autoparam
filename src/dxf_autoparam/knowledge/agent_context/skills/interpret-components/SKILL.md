---
name: interpret-components
description: Use to name the parts a drawing shows (box barrel, wing wall, pile cap and so on), using the knowledge-base definitions as candidate context. Use when a sheet must be described by its components.
---

# Interpret components

## When to use
- Someone asks what components a sheet shows, or what a printed label means.
- Before proposing a dimension binding or a relationship, to name the parts it belongs to.

## Steps
1. Build the pack: `.venv/bin/python agent-context/ctx.py pack <record_id> --task component_interpretation`.
   Validate it: `.venv/bin/python agent-context/ctx.py validate <pack_id>`.
2. Read `component_definitions` (knowledge-base definitions matched by part class), `unmatched_part_classes`, and `candidate_interpretations`.
3. For a printed label with no part class, search the vocabulary: `.venv/bin/python agent-context/ctx.py search "<label>" --category C`.
4. Resolve each cited definition: `.venv/bin/python agent-context/ctx.py evidence <kb_id>`.
5. Write the answer: each component, its evidence id, the class the grounding gave it, and the definition with its review state.

## Required evidence
- For each component: the part's evidence id (`<record_id>#P<n>`) and the knowledge record it is matched to.
- The review state of each definition (almost all are `seed_unreviewed`).

## Permitted output
- "The record reads part P3 as class `box_barrel` (agent reading). The knowledge base defines it as ... (unreviewed)."
- A list of unmatched classes, reported as open.

## Blocked output
- Adding a component the sheet does not draw. `absent` entries record what is missing from the drawing; they are not parts.
- Treating a reinforcement bar mark (for example `a1`, `b`, `g1`) as a component. The component index lists some marks by mistake; the issue `reinforcement_marks_in_component_index` says so.
- Calling a definition authoritative because its `evidence_status` is NORMATIVE. Review state decides, not the label.

## Abstain or ask for review when
- The sheet is ungrounded (no parts are filed).
- A part's status is UNKNOWN or its class is unmatched.
- Two definitions disagree (a `conflict` record or `DISPUTED` status is linked).
