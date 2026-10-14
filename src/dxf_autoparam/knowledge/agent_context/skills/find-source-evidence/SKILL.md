---
name: find-source-evidence
description: Use to find what the repository holds about one drawing sheet, one RDSO page or one topic, with the trust label and gaps of each item. Use before answering any question about a drawing.
---

# Find source evidence

## When to use
- Someone asks what a sheet or page shows, or what the repository says about a topic.
- Before any other skill, to learn what is available for the record.

## Steps
1. Get the record's status: `.venv/bin/python agent-context/ctx.py status <record_id>`.
   Read `completeness.capability`, `eligibility`, `issues`, and `observations` (counts by kind).
2. If the capability is `source_missing`, `identity_only` or `picture_only_ungrounded`, stop. Report the gap (see `handle-uncertainty`).
3. Build a source pack: `.venv/bin/python agent-context/ctx.py pack <record_id> --task source_evidence`.
   It writes a file under `agent-context/packs/`. Check it: `.venv/bin/python agent-context/ctx.py validate <pack_id>`.
4. For a specific item, search the stored observations: `.venv/bin/python agent-context/ctx.py search "<words>" --observations --owner <record_id>`.
5. For any item you cite, resolve its id: `.venv/bin/python agent-context/ctx.py evidence <evidence_id>`.
   Use `--live` to read the item from the source file as it is now.
6. For knowledge around the topic: `.venv/bin/python agent-context/ctx.py search "<words>" --category B C` (add D to see disputed or proposed items).

## Required evidence
- The record id, and the evidence id of every fact you state.
- The trust labels of each item: category, `review_state`, `evidence_status`, `human_verified`.

## Permitted output
- A list of facts, each with its evidence id, its category and its review state.
- The gaps: missing sections (`completeness.missing`), open issues (`issues`), disputes (`conflicts`), unresolved questions.

## Blocked output
- Stating any value as verified or correct.
- Presenting a category D item (proposed or disputed) as accepted.
- Citing an id that did not resolve.

## Abstain or ask for review when
- The status says the page or sheet is not saved or not grounded.
- A dispute covers the item you were asked about.
- The pack is invalid (`valid: false`).
