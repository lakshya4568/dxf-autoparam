---
{"id": "read-the-drawing", "title": "Read a drawing: what it is, what its parts are called", "kind": "recipe",
 "purpose": "Decide what kind of structure a sheet shows and name its parts and levels, using the library's vocabulary as questions to put to the drawing.",
 "applies_to": ["any sheet", "unnamed or mislabelled views", "extension sheets", "sheets that show part of a structure"],
 "tools": ["inspect_sheet", "zoom_view", "describe_views", "set_structure", "define_parts", "search_library", "get_reference", "record_finding"],
 "related": ["gad-workflow", "name-and-bind-sizes", "handle-uncertainty"],
 "derived_from": ["skills/interpret-components/SKILL.md", "skills/find-source-evidence/SKILL.md"]}
---
## Purpose
Say what the drawing is and what its parts are, from the drawing, with the library's definitions as candidates and its misreadings as warnings.

## Applicability
Before parts, values or links are defined on a sheet whose structure is not already named, and whenever a printed word needs interpreting.

## Required inputs
The sheet pictures, `inspect_sheet`, the printed words (title block, notes, labels, level texts).

## Recognition cues
- The structure's name and type are usually printed (title, notes, a size note such as "N x width x height"); a shape alone is weaker.
- `list_skills` ranks the structure skills by the printed words that match; load the `recognition` section of the best one or two and read
  its look-alikes: they are the ways this match is usually wrong.
- Views a structure usually has are in its `representation` section: compare with the views the sheet really has.

## Procedure
1. Read the printed words. For each one that names a part, a level or a structure, `search_library` (topics `component`, `drawing_label`,
   `datum`, `abbreviation`) and read the definition with its review state.
2. Decide the structure with `set_structure` in your own words; `family` is yours. Record the cues you used (record_finding, kind applied)
   and any look-alike you excluded and why.
3. Name parts after the drawing: a library name is offered, not required. Use it only when it is what the drawing shows.
4. For a group that holds drawn linework: zoom_view it before calling it a table or notes; describe_views to say what it is.
5. A label you cannot place is a gap, not a guess: record_finding kind gap, or ask_person when it changes what is built.

## Engineering rules
- A part the sheet does not draw is not a part ("absent" entries in the library record what a drawing lacks).
- A reinforcement bar mark (a1, b, g1 …) is not a component.
- A dotted or differently coloured outline may be existing work: check the notes before treating it as new.
- On an extension sheet the existing structure and the new work both appear; the title says which is which.
- A sheet that shows part of a structure (a detail, a reinforcement sheet) is not a complete arrangement.

## Outputs
`set_structure` (type, views), parts with evidence, findings.

## Validation
The engine's checks on parts (regions exist, no overlap with held parts). A name used in a formula must be defined first.

## Failure handling
Two skills fit, or none: say so; continue with the drawing's own words. The library's labels are unreviewed vocabulary: never use one to
overrule what the drawing prints.

## Source traceability
Adapted from the source skills `interpret-components` and `find-source-evidence` (migrated under `knowledge/agent_context/skills`);
the family look-alikes come from each structure skill's own `recognition` section.
