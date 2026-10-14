---
name: propose-geometric-relationships
description: Use to describe how the views, levels, parts and repeats of a drawing relate to each other, as candidate relationships with their evidence. Use before any geometry is proposed. This layer does not edit or measure CAD geometry.
---

# Propose geometric relationships

## What this layer can and cannot do
- It can list the views, levels, parts, relations and repeats the record shows, with their evidence ids.
- It can propose a relationship (for example "part P2 sits inside part P1") as a candidate, with the evidence that supports it.
- It cannot measure geometry from the picture, edit a CAD entity, or claim a CAD entity exists. Picture coordinates and vector paths are not CAD entities.
- Live CAD binding is available only when a runtime snapshot is supplied. Without one, `live_cad_binding` is `unavailable`.

## When to use
- Describing how the parts of one sheet are arranged, or how two sheets of one bridge relate.
- Preparing the relationships a later model or check will need.

## Steps
1. Build the pack: `.venv/bin/python agent-context/ctx.py pack <record_id> --task geometric_relationships`.
2. Validate: `.venv/bin/python agent-context/ctx.py validate <pack_id>`.
3. Read `observations.views`, `observations.parts`, `observations.relations`, `observations.repeats`, `observations.levels`.
4. For each relationship you propose, resolve its evidence id: `.venv/bin/python agent-context/ctx.py evidence <evidence_id>`.
5. Check the level chain: a level has a `datum`, a `value_m` (agent reading), and the text it came from. Do not add levels together unless the record gives the chain.

## Required evidence
- The relation's evidence id, its `type`, its `from` and `to` parts, and the `evidence` sentence the grounding recorded.
- The confidence the grounding gave it (`low`, `medium`, `high`).

## Permitted output
- "P2 is part_of P1 (agent reading, confidence medium; evidence <id>)."
- A candidate list, each with `binding.status` blocked and the reason `not_a_value_observation`.

## Blocked output
- Measured dimensions or distances from the picture.
- Any CAD entity id, unless a snapshot supplied it (see `agent-context/schemas/cad-snapshot.schema.json`).
- Claims about how the drawn parts are built, beyond what the record states.

## Abstain or ask for review when
- The sheet is ungrounded (no views, parts or relations are filed).
- A relation has `low` confidence and nothing else supports it.
- The level chain has a `superseded` or disputed level.
