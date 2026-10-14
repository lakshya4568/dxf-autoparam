---
name: handle-uncertainty
description: Use whenever something is missing, unreviewed, disputed, conflicting or not saved. It says how to report the gap, what to leave open, and when to stop and ask the owner. Use it with every other skill.
---

# Handle uncertainty

## The ladder (say which rung you are on)
1. **Saved**: the page or record exists and parses. Not the same as checked.
2. **Readable**: the text was read. The reading may be wrong.
3. **Checked against the picture**: compared with the drawing, at view level, as a spot check, or as a second pass. The repository says which.
4. **Verified**: a person confirmed the value and its unit. None is recorded in this repository.

Never say a value is verified unless `verification.human_verified` is true with a recorded person. Today it is never true.

## Where the uncertainty is recorded
- `eligibility`: three separate answers (retrieval, binding, finetune). A blocked answer carries its reasons.
- `issues`: each with a severity (`info`, `warning`, `error`) and the purposes it blocks.
- `completeness.missing` and `unresolved_questions` in a pack.
- `conflicts` in a pack: disputes between written and drawn values, failed arithmetic checks, and status claims that the disk does not confirm.

## Rules
1. **Do not choose between conflicting sources.** Report both, with their ids. For status counts, the disk is reported and the older document is listed as a conflict. For drawing values, the dispute stays open.
2. **Do not fill a gap.** A missing section, a page that is not saved, an ungrounded sheet: say so. Do not infer the missing content.
3. **Keep unreviewed knowledge labelled.** "Unreviewed reference" is context. It does not establish a project dimension.
4. **A NORMATIVE label is not verification** unless the record is reviewed and cites a verified clause.
5. **Proposals are not merged.** Say "proposed" and stop there.
6. **A broken citation is kept as written** and reported. Do not repair it.

## How to phrase it
- "The record reads ... (agent reading, not verified)."
- "No views are filed for this sheet, so I cannot describe its layout."
- "Two sources disagree: <id A> says X; <id B> says Y. Both are kept; the dispute is open."

## When to stop and ask the owner
- A conflict or dispute covers the item you were asked to decide.
- A pack is invalid, or a source changed since the build (`ctx.py check` reports `registry_stale`).
- A binding or model change is requested. These always need a person to verify first.
- The question needs a document that is not in the repository.

## Required evidence
- The issue ids or the evidence ids for each uncertainty you report.
