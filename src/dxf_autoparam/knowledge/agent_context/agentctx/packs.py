"""Task-specific evidence packs: a focused, derived bundle for one record and one task.

A pack is a derived artefact. Every claim cites evidence ids that resolve to stored items, and every item keeps its
trust labels. Raw printed text and the agent's reading of it are kept in separate fields. A value is never presented
as bound, verified or executable here: binding is blocked, and a live CAD binding exists only when a runtime snapshot
is supplied (and then only with the ids that snapshot holds).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .common import GENERATOR, PACK_VERSION, canonical_json, clip, sha256_text
from .store import Store

TASKS: dict[str, str] = {
    "source_evidence": "Find the sources and stored observations for a record, with their trust labels and gaps.",
    "component_interpretation": "Interpret the components the record shows, using knowledge-base definitions as candidates.",
    "dimension_binding": "List written dimensions as candidates for a parameter. Binding stays blocked until a person "
                         "verifies the value and its unit.",
    "geometric_relationships": "Describe the views, levels, parts and relations the record shows. Nothing here edits "
                               "or measures a CAD entity.",
}
SUBJECT_KINDS = ("drawing_sheet", "vector_sheet", "rdso_page", "rdso_extract")
CAD_FORBIDDEN_KEYS = ("cad_entity_id", "entity_id", "cad_id", "occurrence_id")
MAX_ITEMS = 60
BINDING_GUIDANCE = (
    "A dimension may set a parameter only when a person has verified the printed text and its unit, the view and "
    "component scope is confirmed, and no open dispute covers it. This pack records none of those, so every binding "
    "stays blocked."
)


class PackError(ValueError):
    pass


def build_pack(store: Store, record_id: str, task: str, *, scope: dict[str, Any] | None = None,
               cad_snapshot: Path | None = None, max_items: int = MAX_ITEMS) -> dict[str, Any]:
    if task not in TASKS:
        raise PackError(f"unknown task '{task}'. Tasks: {', '.join(sorted(TASKS))}")
    subject = store.sources.get(record_id)
    if subject is None:
        raise PackError(f"'{record_id}' is not a source record in the registry (try: ctx.py status <id>)")
    if subject["kind"] not in SUBJECT_KINDS:
        raise PackError(f"packs are built for {', '.join(SUBJECT_KINDS)}; '{record_id}' is {subject['kind']}")
    scope = dict(scope or {})
    observations = _observations_for(store, subject)
    kinds = Counter(o["obs_kind"] for o in observations)
    capability, missing = _capability(subject, kinds, store)
    cad = _cad_binding(store, cad_snapshot)
    refs = _source_references(store, subject, observations)
    pack: dict[str, Any] = {
        "pack_version": PACK_VERSION,
        "pack_kind": "derived_evidence_pack",
        "derived": True,
        "generator": GENERATOR,
        "built_from": {"registry_digest": store.manifest.get("registry_digest")},
        "task": {"name": task, "description": TASKS[task], "requested_scope": scope},
        "subject": {"record_id": record_id, "kind": subject["kind"], "title": subject.get("title"),
                    "family": subject.get("family"), "bridge_ids": subject.get("bridge_ids") or [],
                    "source_paths": subject.get("source_paths") or []},
        "completeness": {"status": capability, "capabilities": _capability_table(subject, kinds, cad),
                         "missing": missing, "notes": _notes(subject)},
        "source_references": refs,
        "source_fingerprints": {r["record_id"]: r["fingerprint"] for r in refs},
        "input_hashes": _input_hashes(store, refs),
    }
    builders = {
        "source_evidence": _source_evidence,
        "component_interpretation": _component_interpretation,
        "dimension_binding": _dimension_binding,
        "geometric_relationships": _geometric_relationships,
    }
    pack["live_cad_binding"] = cad
    builders[task](store, subject, observations, pack, scope, max_items)
    pack["agent_summary"] = _summary(pack)
    pack["pack_id"] = pack_identity(pack)
    return pack


def pack_identity(pack: dict[str, Any]) -> str:
    """The id is a digest of the whole pack body, so any edit to a claim, candidate or source changes it."""
    body = {key: value for key, value in pack.items() if key != "pack_id"}
    return "pack-" + sha256_text(canonical_json(body))[:16]


def _observations_for(store: Store, subject: dict[str, Any]) -> list[dict[str, Any]]:
    if subject["kind"] == "rdso_extract":
        prefix = f"rdso:{subject['existing_ids']['doc_id']}:p"
        return sorted((o for o in store.observations.values() if o["owner_id"].startswith(prefix)),
                      key=lambda o: o["evidence_id"])
    return sorted((o for o in store.observations.values() if o["owner_id"] == subject["id"]),
                  key=lambda o: o["evidence_id"])


def _capability(subject: dict[str, Any], kinds: Counter[str], store: Store | None = None) -> tuple[str, list[str]]:
    comp = subject.get("completeness") or {}
    missing: list[str] = []
    if subject["kind"] == "drawing_sheet":
        cap = comp.get("capability")
        if cap == "source_missing":
            return "none", ["raw drawing file"]
        if cap in ("grounded", "grounded_needs_review"):
            for name in ("views", "dimension_text", "parts", "levels"):
                if not kinds.get({"views": "view", "dimension_text": "dimension", "parts": "part",
                                  "levels": "level"}[name]):
                    missing.append(name)
            if store is not None:
                grounding = store.sources.get(f"grounding:{subject['id']}") or {}
                for section in (grounding.get("completeness") or {}).get("sections_empty", []):
                    if section not in missing:
                        missing.append(f"grounding section empty: {section}")
            return ("grounded_unverified" if not missing else "partially_grounded"), missing
        if cap == "picture_only_ungrounded":
            return "limited_ungrounded", ["grounding (no views, dimensions, parts or levels filed)"]
        return "identity_only", ["picture", "grounding"]
    if subject["kind"] == "vector_sheet":
        return ("vector_text_observed" if kinds.get("vector_text") else "none"), (
            [] if kinds.get("vector_text") else ["text layer"])
    if subject["kind"] == "rdso_page":
        if comp.get("saved"):
            return "page_saved_unverified", []
        return "not_saved", ["page json and markdown"]
    pages = comp.get("pages_expected") or 0
    saved = comp.get("pages_saved") or 0
    return ("pages_saved_partial" if saved < pages else "all_pages_saved_unverified"), (
        [f"{pages - saved} page(s) not saved"] if saved < pages else [])


def _capability_table(subject: dict[str, Any], kinds: Counter[str], cad: dict[str, Any]) -> dict[str, Any]:
    comp = subject.get("completeness") or {}
    return {
        "picture": bool(comp.get("picture_present")),
        "identity": True,
        "views": bool(kinds.get("view")),
        "dimension_text": bool(kinds.get("dimension")),
        "levels": bool(kinds.get("level")),
        "parts": bool(kinds.get("part")),
        "relations": bool(kinds.get("relation")),
        "parameters": bool(kinds.get("parameter") or kinds.get("rdso_parameter")),
        "vector_text": bool(kinds.get("vector_text")),
        "disputes_recorded": kinds.get("dispute", 0),
        "verified_values": 0,
        "live_cad_binding": cad["status"] == "available",
    }


def _notes(subject: dict[str, Any]) -> list[str]:
    notes = ["No value in this pack is verified by a person; the registry holds no verification record."]
    if subject["kind"] == "drawing_sheet" and (subject.get("completeness") or {}).get("grounding") == "none":
        notes.append("This sheet is not grounded. The pack holds identity and picture only; no views, dimensions or "
                     "parts are reported for it.")
    if subject["kind"] == "rdso_page":
        notes.append("Page reads were made by eye (no OCR). Saved is not the same as checked against the picture.")
    return notes


def _source_references(store: Store, subject: dict[str, Any], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = [{"record_id": subject["id"], "kind": subject["kind"], "role": "subject",
             "fingerprint": subject["fingerprint"], "source_paths": subject.get("source_paths") or []}]
    owners = {o["source_id"] for o in observations}
    owners.discard(subject["id"])
    for source_id in sorted(owners):
        record = store.sources.get(source_id)
        if record:
            refs.append({"record_id": source_id, "kind": record["kind"], "role": "observation_source",
                         "fingerprint": record["fingerprint"], "source_paths": record.get("source_paths") or []})
    return refs


def _input_hashes(store: Store, refs: list[dict[str, Any]]) -> dict[str, str]:
    built = store.manifest.get("input_hashes", {})
    wanted: set[str] = set()
    for ref in refs:
        wanted.update(ref["source_paths"])
    return {p: built[p] for p in sorted(wanted) if p in built}


def _obs_item(obs: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": obs["evidence_id"],
        "obs_kind": obs["obs_kind"],
        "view": obs.get("view"),
        "raw_text": obs.get("raw_text"),
        "candidate_interpretation": obs.get("candidate_interpretation"),
        "geometry": obs.get("geometry"),
        "trust": obs.get("trust"),
        "eligibility": obs.get("eligibility"),
    }


def _select(observations: list[dict[str, Any]], kinds: set[str], max_items: int, pack: dict[str, Any],
            key: str) -> list[dict[str, Any]]:
    chosen = [o for o in observations if o["obs_kind"] in kinds]
    shown = chosen[:max_items]
    if len(chosen) > len(shown):
        pack.setdefault("truncation", {})[key] = {"total": len(chosen), "included": len(shown)}
    return [_obs_item(o) for o in shown]


def _claim(claims: list[dict[str, Any]], kind: str, statement: str, obs: dict[str, Any]) -> None:
    claims.append({
        "claim_id": f"C{len(claims) + 1}",
        "kind": kind,
        "statement": statement,
        "evidence_ids": [obs["evidence_id"]],
        "source_ids": [obs["source_id"]],
        "trust": obs.get("trust"),
        "eligibility": obs.get("eligibility"),
    })


def _blockers(binding: str) -> list[str]:
    return binding.split(":", 1)[1].split("+") if binding.startswith("blocked:") else []


def _source_evidence(store: Store, subject: dict[str, Any], observations: list[dict[str, Any]],
                     pack: dict[str, Any], scope: dict[str, Any], max_items: int) -> None:
    claims: list[dict[str, Any]] = []
    counts = Counter(o["obs_kind"] for o in observations)
    pack["observations_summary"] = dict(sorted(counts.items()))
    pack["observations"] = {
        "views": _select(observations, {"view"}, max_items, pack, "views"),
        "texts": _select(observations, {"text", "vector_text", "rdso_note", "rdso_component"}, max_items, pack, "texts"),
    }
    for item in pack["observations"]["views"][:10]:
        _claim(claims, "observation", f"view {item['raw_text']!r} is recorded on this sheet", _by_id(observations, item))
    pack["claims"] = claims
    pack["unresolved_questions"] = _unresolved(store, subject, observations)
    pack["conflicts"] = _conflicts(store, subject, observations)
    pack["formulas"] = []
    pack["component_definitions"] = []
    pack["candidate_interpretations"] = []
    pack["permitted_next_actions"] = [
        "cite evidence ids from this pack in your answer",
        "report which sections are missing, as listed under completeness",
    ]
    pack["blocked_next_actions"] = _blocked_common()


def _component_interpretation(store: Store, subject: dict[str, Any], observations: list[dict[str, Any]],
                              pack: dict[str, Any], scope: dict[str, Any], max_items: int) -> None:
    claims: list[dict[str, Any]] = []
    parts = _select(observations, {"part"}, max_items, pack, "parts")
    absent = _select(observations, {"absent"}, max_items, pack, "absent")
    pack["observations"] = {"parts": parts, "absent": absent}
    definitions: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for obs in observations:
        if obs["obs_kind"] != "part":
            continue
        cls = (obs.get("candidate_interpretation") or {}).get("class")
        ids = store.component_definitions.get(cls or "", [])
        if not ids:
            unmatched.append(cls or "(no class)")
            continue
        entries = []
        for rid in ids[:3]:
            record = store.knowledge[rid]
            entries.append({"id": rid, "title": record["title"], "statement": record.get("statement"),
                            "category": record["category"], "trust": record.get("trust"),
                            "eligibility": record.get("eligibility")})
        definitions.append({"class": cls, "evidence_id": obs["evidence_id"], "definitions": entries})
        _claim(claims, "reference", f"part class '{cls}' is defined in the knowledge base as candidate context",
               obs)
    pack["component_definitions"] = definitions
    pack["unmatched_part_classes"] = sorted(set(unmatched))
    pack["formulas"] = []
    pack["candidate_interpretations"] = [
        {"evidence_id": o["evidence_id"], "raw_text": o.get("raw_text"), "candidate": o.get("candidate_interpretation"),
         "status": "candidate_only", "binding": {"status": "blocked", "reasons": ["not_a_value_observation"]}}
        for o in observations if o["obs_kind"] == "part"][:max_items]
    pack["claims"] = claims
    pack["unresolved_questions"] = _unresolved(store, subject, observations)
    pack["conflicts"] = _conflicts(store, subject, observations)
    pack["permitted_next_actions"] = [
        "name a part only when the sheet draws or writes it; use the candidate class and its evidence id",
        "use knowledge-base definitions as candidate context, labelled with their review state",
    ]
    pack["blocked_next_actions"] = _blocked_common() + [
        {"action": "add a component that is only listed as absent", "reason": "absent entries record what is not drawn"},
    ]


def _dimension_binding(store: Store, subject: dict[str, Any], observations: list[dict[str, Any]],
                       pack: dict[str, Any], scope: dict[str, Any], max_items: int) -> None:
    claims: list[dict[str, Any]] = []
    wanted_ids = set(scope.get("dimension_ids") or [])
    dims = [o for o in observations if o["obs_kind"] in {"dimension", "level", "parameter", "rdso_parameter"}
            and (not wanted_ids or o["local_id"] in wanted_ids)]
    shown = dims[:max_items]
    if len(dims) > len(shown):
        pack.setdefault("truncation", {})["dimensions"] = {"total": len(dims), "included": len(shown)}
    candidates = []
    for obs in shown:
        reasons = _blockers(obs["eligibility"]["binding"])
        cand = obs.get("candidate_interpretation") or {}
        candidates.append({
            "evidence_id": obs["evidence_id"],
            "obs_kind": obs["obs_kind"],
            "view": obs.get("view"),
            "raw_text": obs.get("raw_text"),
            "candidate": cand,
            "geometry": obs.get("geometry"),
            "status": "candidate_only",
            "binding": {"status": "blocked", "reasons": reasons},
        })
        value = cand.get("value")
        _claim(claims, "observation",
               f"{obs.get('raw_text')!r} on {obs.get('view') or 'the sheet'} is read as {value} {cand.get('unit') or '(no unit)'}"
               " (agent reading; not verified)", obs)
    pack["candidate_interpretations"] = candidates
    pack["observations"] = {"dimensions": [_obs_item(o) for o in shown]}
    pack["binding_policy"] = BINDING_GUIDANCE
    pack["claims"] = claims
    pack["conflicts"] = _conflicts(store, subject, observations)
    pack["unresolved_questions"] = _unresolved(store, subject, observations)
    pack["formulas"] = _formula_candidates(store, subject, pack)
    pack["component_definitions"] = []
    if not dims:
        pack["permitted_next_actions"] = ["report that no grounded dimension text exists for this record"]
    else:
        pack["permitted_next_actions"] = [
            "list candidates with their raw text, reading and blockers",
            "propose a binding only as a candidate for a person to verify",
            "name every open dispute that covers the dimension",
        ]
    pack["blocked_next_actions"] = _blocked_common() + [
        {"action": "bind a dimension to a parameter", "reason": "no human verification and no verified unit in the repository"},
        {"action": "write a value into a model or a CAD entity", "reason": "no live CAD snapshot binding unless one is supplied"},
    ]


def _geometric_relationships(store: Store, subject: dict[str, Any], observations: list[dict[str, Any]],
                             pack: dict[str, Any], scope: dict[str, Any], max_items: int) -> None:
    claims: list[dict[str, Any]] = []
    pack["observations"] = {
        "views": _select(observations, {"view"}, max_items, pack, "views"),
        "parts": _select(observations, {"part"}, max_items, pack, "parts"),
        "relations": _select(observations, {"relation"}, max_items, pack, "relations"),
        "repeats": _select(observations, {"repeat"}, max_items, pack, "repeats"),
        "levels": _select(observations, {"level"}, max_items, pack, "levels"),
    }
    for obs in observations:
        if obs["obs_kind"] == "relation":
            cand = obs.get("candidate_interpretation") or {}
            _claim(claims, "observation", f"{cand.get('from')} {cand.get('type')} {cand.get('to')} (agent reading)", obs)
    pack["claims"] = claims
    pack["formulas"] = _formula_candidates(store, subject, pack)
    pack["component_definitions"] = []
    pack["candidate_interpretations"] = [
        {"evidence_id": o["evidence_id"], "candidate": o.get("candidate_interpretation"), "status": "candidate_only",
         "binding": {"status": "blocked", "reasons": ["not_a_value_observation"]}}
        for o in observations if o["obs_kind"] in {"relation", "repeat"}][:max_items]
    pack["conflicts"] = _conflicts(store, subject, observations)
    pack["unresolved_questions"] = _unresolved(store, subject, observations)
    pack["permitted_next_actions"] = [
        "describe views, levels, parts and relations as recorded, with their evidence ids",
        "propose a relationship as a candidate, with the evidence that supports it",
    ]
    cad_note = ("a live CAD binding is available for this pack" if pack["live_cad_binding"]["status"] == "available"
                else "no runtime CAD snapshot: picture coordinates and vector paths are not CAD entities")
    pack["blocked_next_actions"] = _blocked_common() + [
        {"action": "edit or select a CAD entity", "reason": cad_note},
        {"action": "measure geometry from the picture", "reason": "this pack has no pixel measurement"},
    ]


def _unresolved(store: Store, subject: dict[str, Any], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for obs in observations:
        if obs["obs_kind"] in {"doubt", "absent", "rdso_unclear", "rdso_not_read"}:
            out.append({"evidence_id": obs["evidence_id"], "kind": obs["obs_kind"], "text": obs.get("raw_text")})
    for issue in store.issues_for(subject["id"]):
        if issue["severity"] in ("warning", "error"):
            out.append({"issue_id": issue["id"], "kind": issue["kind"], "text": issue["description"]})
    return out[:100]


def _conflicts(store: Store, subject: dict[str, Any], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for obs in observations:
        if obs["obs_kind"] == "dispute":
            out.append({"evidence_id": obs["evidence_id"], "kind": "written_or_drawn_dispute",
                        "text": obs.get("raw_text"), "candidate": obs.get("candidate_interpretation"),
                        "resolution": "not decided by this pack"})
        if obs["obs_kind"] == "check" and (obs.get("fields") or {}).get("passed") is False:
            out.append({"evidence_id": obs["evidence_id"], "kind": "arithmetic_check_disagrees",
                        "text": obs.get("raw_text"), "candidate": obs.get("candidate_interpretation")})
    for issue in store.issues_for(subject["id"]):
        if issue["kind"] in ("status_conflict", "unverified_claim", "audit_difference"):
            out.append({"issue_id": issue["id"], "kind": issue["kind"], "text": issue["description"]})
    return out[:100]


def _formula_candidates(store: Store, subject: dict[str, Any], pack: dict[str, Any]) -> list[dict[str, Any]]:
    family = subject.get("family")
    out: list[dict[str, Any]] = []
    for record in sorted(store.knowledge.values(), key=lambda r: r["id"]):
        if record["topic"] not in ("formula", "rule", "level_chain"):
            continue
        applies = record.get("applies_families") or []
        if applies and family not in applies:
            continue
        out.append({
            "id": record["id"],
            "title": record["title"],
            "statement": record.get("statement"),
            "expression": record.get("expression"),
            "applicability": applies or "not stated in the record",
            "trust": record.get("trust"),
            "eligibility": record.get("eligibility"),
            "executed": False,
        })
        if len(out) >= 12:
            break
    return out


def _blocked_common() -> list[dict[str, str]]:
    return [
        {"action": "state a value as verified", "reason": "no human verification is recorded in the repository"},
        {"action": "promote a proposal or an unreviewed entry into accepted knowledge",
         "reason": "proposals and unreviewed entries are never merged or promoted by this layer"},
        {"action": "use this pack as training data", "reason": "packs are derived artefacts, not labels or sources"},
    ]


def _by_id(observations: list[dict[str, Any]], item: dict[str, Any]) -> dict[str, Any]:
    return next(o for o in observations if o["evidence_id"] == item["evidence_id"])


def _summary(pack: dict[str, Any]) -> str:
    cap = pack["completeness"]["status"]
    subject = pack["subject"]
    lines = [
        f"Task {pack['task']['name']} for {subject['record_id']} ({subject['kind']}, family {subject.get('family')}). "
        f"Completeness: {cap}.",
    ]
    if cap in ("none", "identity_only", "limited_ungrounded"):
        lines.append("Only identity and picture are available. Do not describe views, dimensions or parts for this record.")
    lines.append(f"Claims: {len(pack.get('claims', []))}. Candidates: {len(pack.get('candidate_interpretations', []))}. "
                 f"Conflicts: {len(pack.get('conflicts', []))}. Open questions: {len(pack.get('unresolved_questions', []))}.")
    lines.append("Every dimension is a candidate; binding is blocked. CAD binding: "
                 + pack["live_cad_binding"]["status"] + ".")
    return " ".join(lines)


def _cad_binding(store: Store, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "unavailable",
                "reason": "no runtime CAD snapshot supplied; PDF primitives and picture coordinates are not CAD entities",
                "snapshot": None}
    try:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "reason": f"snapshot could not be read: {exc}", "snapshot": None}
    from .validate import validate_snapshot_shape

    errors = validate_snapshot_shape(store.context_dir, snapshot)
    if errors:
        return {"status": "invalid", "reason": "snapshot does not match schemas/cad-snapshot.schema.json",
                "errors": errors, "snapshot": None}
    entity_ids = {e["entity_id"] for e in snapshot.get("entities", [])}
    return {
        "status": "available",
        "snapshot_id": snapshot["snapshot_id"],
        "document_version": snapshot["document_version"],
        "views": snapshot.get("views", []),
        "entities": snapshot.get("entities", []),
        "user_locks": snapshot.get("user_locks", []),
        "mappings": [m for m in snapshot.get("mappings", []) if m.get("entity_id") in entity_ids],
        "unmapped_mappings": [m for m in snapshot.get("mappings", []) if m.get("entity_id") not in entity_ids],
        "snapshot": "supplied by the caller; echoed, never created here",
    }


def load_pack(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = ["build_pack", "TASKS", "PackError", "load_pack", "Counter", "clip"]
