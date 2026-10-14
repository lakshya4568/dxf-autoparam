---
{"id": "handle-uncertainty", "title": "Handle what is missing, disputed, unreviewed or conflicting", "kind": "recipe",
 "purpose": "How to report a gap, keep disputed knowledge labelled, and when to stop and ask the person.",
 "applies_to": ["any gap, conflict or ambiguity"],
 "tools": ["ask_person", "record_finding", "get_reference", "state_plan"],
 "related": ["gad-workflow", "read-the-drawing", "name-and-bind-sizes"],
 "derived_from": ["skills/handle-uncertainty/SKILL.md"]}
---
## Purpose
Never fill a gap with a guess and never present unreviewed knowledge as fact. Say which rung of confidence you are on.

## Applicability
Whenever something is missing, ambiguous, disputed in the library, or in conflict with the drawing.

## Procedure
1. **Name the rung.** Read from the drawing (the engine checked it) · read from a note or label (may be wrong) · documented in the
   library (unreviewed context) · confirmed by the person.
2. **Library items carry their own state** (`review_state`, `evidence_status`, category D = proposed or disputed). A NORMATIVE label is a
   label, not a verification. A disputed record is reported with both sides; neither is chosen.
3. **Do not choose between conflicting sources.** The drawing is the evidence for this drawing; a library rule that the drawing
   violates is reported (record_finding kind conflict), not "fixed" by moving a line.
4. **Do not fill a gap.** A missing level, an unlabeled size, a part the sheet does not show: say it is missing.
5. **Proposals are not merged.** A rule or correction you think the library lacks is recorded as kind proposal: it is a note for a person.
6. **Ask when it is the person's.** A decision the drawing and the library cannot settle (which side stays, which datum a level means,
   a disputed definition that changes what is built): `ask_person` with the options you see.

## Phrases
- "The drawing prints … (read from the picture)."
- "The library documents … as an unreviewed reference; this drawing …"
- "Two sources disagree: … says X; … says Y. Both are kept; the question is open."
- "No level is drawn for …, so I did not derive it."

## Validation
`record_finding` rejects a library id that does not exist; the run's verdict lists open conflicts, gaps and proposals.

## Failure handling
If a question would be asked a second time, ask once and apply the answer.

## Source traceability
Adapted from the source skill `handle-uncertainty` (the ladder, the rules on disputed and unreviewed items, how to phrase, when to stop).
