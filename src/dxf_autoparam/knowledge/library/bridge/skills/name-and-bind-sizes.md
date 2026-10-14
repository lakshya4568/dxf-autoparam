---
{"id": "name-and-bind-sizes", "title": "Name a size and bind it to the drawing", "kind": "recipe",
 "purpose": "Turn a size the drawing shows into a named value the engine can drive, without letting library knowledge supply the number.",
 "applies_to": ["any sheet with written or measured sizes"],
 "tools": ["find_values", "inspect_candidates", "inspect_dimensions", "define_parameters", "what_moves", "check_rule", "record_finding", "ask_person"],
 "related": ["read-the-drawing", "relate-views-and-levels", "handle-uncertainty"],
 "derived_from": ["skills/propose-dimension-bindings/SKILL.md", "skills/handle-uncertainty/SKILL.md"]}
---
## Purpose
A value is named and bound only where the drawing shows it. The library helps with the NAME and with the question "is this the size I
think it is?", never with the number.

## Applicability
Every `define_parameters` and `set_levels` call.

## Required inputs
`find_values` / `inspect_candidates` for the sizes the drawing has; `inspect_dimensions` for the ones it states.

## Prerequisites
The part the size belongs to is defined; the view and scope are known; for a level, the datum it is read from.

## Engineering rules (conditions that must hold before a size is bound)
1. **Where it is.** The size is a candidate (c…) with its occurrences, or two lines it spans, or a dimension tied to one pair of lines. The
   engine fills in the value and says what it drives.
2. **Scope.** It belongs to the view and the part you name. A written number beside a part is not automatically that part's size.
3. **Text against linework.** A written value the linework contradicts is a dispute: the engine measures; do not choose by the library.
4. **Unit.** Levels are metres, sizes millimetres (the overview says); a bare number with no unit printed is a question.
5. **Anchor.** What stays and what moves when the size changes is decided in a plan (`propose_plan`), not ad hoc.
6. **Definitions.** The library's definition of a size ("clear height = soffit level − floor level") says what the size IS. Use it to pick
   the right pair of lines; confirm with `check_rule` after binding.

## Procedure
1. `find_values` / `inspect_candidates`: which sizes exist, how often, between which lines.
2. For a name or a definition: `search_library` (topics `formula`, `datum`, `quantity`, `component`). Prefer the drawing's own wording.
3. `define_parameters` in a batch; read each verdict (what it drives, how it moves).
4. `what_moves` on the primary ones: does the drawing stay valid and do the parts move as a designer would expect?
5. `check_rule` for the documented definitions you used; resolve a difference by finding which size you bound wrong.

## Outputs
Named values with evidence, levels with roles, findings.

## Validation
The engine: the drawing is reproduced exactly at the current values, no fixed line moves, every value moves something.

## Failure handling
- A definition's datum is disputed in the library (its record lists a conflict): a difference may be the datum, not an error: ask_person.
- The library gives a typical number: it is not used; if the drawing does not show the size, the size is not bound.

## Source traceability
Adapted from the source skills `propose-dimension-bindings` and `handle-uncertainty`: its conditions for a binding (verified text and
unit, correct scope, a measurement target with evidence, no open dispute, anchor stated, locks respected, deterministic validation) are
kept; here the engine's measurement replaces the source's "a person verifies" step because the drawing itself is the evidence.
