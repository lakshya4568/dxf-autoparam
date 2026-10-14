---
{"id": "relate-views-and-levels", "title": "Relate views, parts and levels across a sheet", "kind": "recipe",
 "purpose": "State which components and sizes appear in more than one view, how they relate, and how the levels chain — as bound relations or as noted ones.",
 "applies_to": ["sheets with more than one view", "level chains", "repeated parts"],
 "tools": ["inspect_sheet", "describe_views", "share_sizes", "state_plan", "set_levels", "set_relation", "get_reference", "record_finding"],
 "related": ["gad-workflow", "name-and-bind-sizes", "handle-uncertainty"],
 "derived_from": ["skills/propose-geometric-relationships/SKILL.md"]}
---
## Purpose
Describe how the parts of one view, and the views of one sheet, relate: the same component in two views, a detail of another, the same size
at another scale, a level derived from other levels — with the evidence for each, and what the engine can and cannot tie.

## Applicability
Whenever a sheet has more than one view, repeated parts (cells, spans, bays), or stated levels.

## Required inputs
`inspect_sheet` (views, units, projection links, shared values), the parts of each unit, the stated levels.

## Recognition cues
- Views drawn in projection share set-out lines: the engine treats them as one unit.
- The same size printed in two views is a candidate for one shared value (`share_sizes`); the engine refuses what does not measure the same.
- A structure skill's `representation` lists the views, repeated units and level chain such a structure usually has: use it as a checklist
  to look for, not as a list to fill in.

## Procedure
1. `describe_views`: name and type each view; relate projections, same-structure views and details (only where the geometry allows).
2. List what appears in more than one view; for each: which part or value in each view, and how they relate.
3. Bind what can be bound: a shared value (`share_sizes`) or views in projection; say as `noted_only`, with the reason, what cannot.
4. Levels: name the stated levels with `set_levels` (role: site input, check only, or derived). Express a derived level as a relation over
   named levels and values (`set_relation`); a relation that names nothing is refused. Do not add levels unless the drawing, or a
   documented chain you confirmed on it, gives the chain.
5. Repeated parts: one definition with the count as a value where the engine supports it; otherwise each occurrence tied by equality.
6. `state_plan` with the links and your assumptions; cite library ids for chains you used; `record_finding` for conflicts.

## Engineering rules
- A relation is stated only with its evidence (the drawing's lines, dimensions or notes).
- A level that is superseded or disputed in the library is not used to derive another.
- A library level chain is a pattern to look for; the numbers come from this drawing.

## Outputs
A stated plan the engine checks (every unit, view, part and value you name exists; every binding you claim is on the sheet), shared values,
relations, levels.

## Validation
`state_plan` refusals; shared values still drive each view; `check_rule` for documented level definitions.

## Failure handling
Cannot tie two views: say `noted_only` and why; do not claim a binding. Two readings of a level: ask_person.

## Source traceability
Adapted from the source skill `propose-geometric-relationships` (what a layer may and may not do with views, levels, parts and repeats;
the level chain rule).
