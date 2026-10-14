"""Validation: packs against their schema, the registry and the current files; the registry against the repository.

A pack is valid only if every claim resolves to a stored item, every source it names is still the one it was built
from, no binding is marked as allowed, no CAD id appears without a snapshot, and an ungrounded record has no
grounded observations. Each failure is reported with its rule name. Nothing is repaired automatically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import sha256_file, write_text
from .packs import CAD_FORBIDDEN_KEYS, TASKS, pack_identity
from .store import Store

GROUNDED_KINDS = {"view", "text", "dimension", "level", "part", "relation", "repeat", "parameter", "table",
                  "check", "dispute", "absent", "doubt"}
UNGROUNDED_STATUSES = {"none", "identity_only", "limited_ungrounded"}


def _schema(context_dir: Path, name: str) -> dict[str, Any] | None:
    path = context_dir / "schemas" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def validate_snapshot_shape(context_dir: Path, snapshot: Any) -> list[str]:
    schema = _schema(context_dir, "cad-snapshot.schema.json")
    if schema is None:
        return ["schemas/cad-snapshot.schema.json is missing"]
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in sorted(validator.iter_errors(snapshot), key=lambda e: list(e.absolute_path))]


def validate_pack(store: Store, pack: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def err(rule: str, message: str) -> None:
        errors.append({"rule": rule, "message": message})

    def warn(rule: str, message: str) -> None:
        warnings.append({"rule": rule, "message": message})

    schema = _schema(store.context_dir, "evidence-pack.schema.json")
    if schema is not None:
        import jsonschema

        validator = jsonschema.Draft202012Validator(schema)
        for error in sorted(validator.iter_errors(pack), key=lambda e: list(e.absolute_path)):
            where = "/".join(str(p) for p in error.absolute_path) or "(root)"
            err("schema", f"{where}: {error.message}")

    if pack.get("derived") is not True or pack.get("pack_kind") != "derived_evidence_pack":
        err("derived", "pack is not marked as a derived evidence pack")
    task = (pack.get("task") or {}).get("name")
    if task not in TASKS:
        err("task", f"unknown task '{task}'")

    if pack_identity(pack) != pack.get("pack_id"):
        err("pack_id", "pack_id does not match its content: the pack was edited after it was built")

    for ref in pack.get("source_references") or []:
        current = store.sources.get(ref["record_id"])
        if current is None:
            err("source_reference", f"{ref['record_id']} is not in the registry")
            continue
        if current["fingerprint"] != ref["fingerprint"]:
            err("stale_reference", f"{ref['record_id']} changed in the registry since the pack was built")
        for relpath in ref.get("source_paths") or []:
            path = store.root / relpath
            built = (pack.get("input_hashes") or {}).get(relpath)
            if built is not None and path.is_file() and sha256_file(path) != built:
                err("changed_since_build", f"{relpath} changed on disk since the pack was built")

    capability = (pack.get("completeness") or {}).get("status")
    caps = (pack.get("completeness") or {}).get("capabilities") or {}
    observation_kinds = {item.get("obs_kind") for key in (pack.get("observations") or {})
                         for item in (pack["observations"].get(key) or [])}
    if capability in UNGROUNDED_STATUSES:
        leaked = sorted(k for k in observation_kinds if k in GROUNDED_KINDS)
        if leaked:
            err("ungrounded_fabrication", f"record is {capability} but the pack holds grounded observations: {leaked}")
        if caps.get("views") or caps.get("dimension_text"):
            err("ungrounded_fabrication", "record is ungrounded but capabilities claim views or dimension text")

    for claim in pack.get("claims") or []:
        if not claim.get("evidence_ids"):
            err("claim_without_evidence", f"{claim.get('claim_id')} cites no evidence")
        for evidence_id in claim.get("evidence_ids") or []:
            if evidence_id not in store.observations and evidence_id not in store.knowledge \
                    and evidence_id not in store.sources:
                err("unresolved_evidence", f"{claim.get('claim_id')} cites {evidence_id}, which is not stored")
        for source_id in claim.get("source_ids") or []:
            if source_id.startswith("pack-") or source_id not in store.sources:
                err("source_not_registered", f"{claim.get('claim_id')} cites source '{source_id}' (not a registry source)")
        if (claim.get("trust") or {}).get("human_verified") is True:
            err("verification_claim", f"{claim.get('claim_id')} claims human verification the repository does not hold")

    for item in pack.get("candidate_interpretations") or []:
        binding = (item.get("binding") or {}).get("status")
        if binding != "blocked":
            err("binding_allowed", f"candidate {item.get('evidence_id')} has binding status '{binding}'; only 'blocked' is valid")
        if not (item.get("binding") or {}).get("reasons"):
            err("binding_reasons", f"candidate {item.get('evidence_id')} is blocked without a reason")

    cad = pack.get("live_cad_binding") or {}
    if cad.get("status") != "available":
        leaked = _find_keys(pack, CAD_FORBIDDEN_KEYS)
        if leaked:
            err("cad_ids_without_snapshot", f"CAD-like id keys present without a snapshot: {sorted(set(leaked))}")
        if cad.get("status") not in ("unavailable", "invalid"):
            err("live_cad_binding", f"unexpected live CAD status '{cad.get('status')}'")
    if cad.get("status") == "available" and cad.get("unmapped_mappings"):
        warn("cad_mapping", f"{len(cad['unmapped_mappings'])} mapping(s) point to entities missing from the snapshot")

    permitted = set(pack.get("permitted_next_actions") or [])
    blocked = {b.get("action") for b in pack.get("blocked_next_actions") or []}
    overlap = sorted(permitted & blocked)
    if overlap:
        err("actions", f"actions both permitted and blocked: {overlap}")
    if not pack.get("agent_summary"):
        err("summary", "agent_summary is empty")
    if caps.get("verified_values"):
        err("verification_claim", "capabilities report verified values; the repository holds none")

    return {
        "pack_id": pack.get("pack_id"),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked": ["schema", "derived", "pack_id", "source_references", "claims", "candidates", "cad", "ungrounded",
                    "actions", "summary"],
    }


def _find_keys(obj: Any, keys: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys:
                found.append(key)
            found.extend(_find_keys(value, keys))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_find_keys(value, keys))
    return found


RECORD_SCHEMAS = {
    "source-record.schema.json": "sources",
    "knowledge-record.schema.json": "knowledge",
    "issue.schema.json": "issues",
}


def validate_records(store: Store) -> dict[str, Any]:
    """Every source, knowledge record and issue against its schema. Observations are checked by the tests."""
    import jsonschema

    report: dict[str, Any] = {}
    for schema_name, table in RECORD_SCHEMAS.items():
        schema = _schema(store.context_dir, schema_name)
        validator = jsonschema.Draft202012Validator(schema)
        rows = getattr(store, table).values()
        errors: list[str] = []
        for row in rows:
            for error in validator.iter_errors(row):
                errors.append(f"{row.get('id')}: {error.message}")
                break
        report[table] = {"checked": len(rows), "invalid": len(errors), "examples": errors[:5]}
    return report


def check_registry(store: Store, packs_dir: Path) -> dict[str, Any]:
    """Stale inputs, stale packs, broken references. Read-only; reports only."""
    from .registry import collect_input_hashes

    built = store.manifest.get("input_hashes", {})
    current = collect_input_hashes(store.root)
    changed = sorted(p for p in built if p in current and current[p] != built[p])
    removed = sorted(p for p in built if p not in current)
    added = sorted(p for p in current if p not in built)
    broken_sources = []
    for record in store.sources.values():
        for relpath in record.get("source_paths") or []:
            if not (store.root / relpath).exists():
                broken_sources.append({"record": record["id"], "path": relpath})
    unresolved_citations = sum(1 for k in store.knowledge.values() for c in (k.get("citations") or [])
                               if c.get("resolved") is False)
    pack_reports = []
    if packs_dir.is_dir():
        for path in sorted(packs_dir.glob("*.json")):
            if path.name == "index.json":
                continue
            pack = json.loads(path.read_text(encoding="utf-8"))
            pack_reports.append({"file": path.name, **validate_pack(store, pack)})
    report = {
        "record_schemas": validate_records(store),
        "registry_inputs": {"tracked": len(built), "changed": changed, "removed": removed, "added": added},
        "registry_stale": bool(changed or removed or added),
        "broken_source_paths": broken_sources,
        "unresolved_citations": unresolved_citations,
        "packs": pack_reports,
        "packs_stale": [p["file"] for p in pack_reports if not p["valid"]],
    }
    lines = ["# Check report (generated by agentctx; do not edit)", "",
             f"Registry inputs tracked: {len(built)}. Changed: {len(changed)}. Removed: {len(removed)}. "
             f"Added: {len(added)}. Registry stale: {report['registry_stale']}.", "",
             f"Broken source paths: {len(broken_sources)}. Unresolved citation origins (kept as written): {unresolved_citations}.",
             "", "## Packs", ""]
    lines += [f"- `{p['file']}`: {'valid' if p['valid'] else 'INVALID'}; errors {len(p['errors'])}, warnings {len(p['warnings'])}"
              for p in pack_reports] or ["- no packs in packs/"]
    lines.append("")
    write_text(store.context_dir / "reports" / "check_report.md", "\n".join(lines))
    return report
