"""In-memory collection of records while the registry is built.

Adapters only call add_* and issue(). The collector refuses duplicate ids (a duplicate id would make
evidence lookups ambiguous) and records the problem instead of overwriting.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .policy import ISSUE_SEVERITIES


class Collector:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sources: dict[str, dict[str, Any]] = {}
        self.observations: dict[str, dict[str, Any]] = {}
        self.knowledge: dict[str, dict[str, Any]] = {}
        self.issues: dict[str, dict[str, Any]] = {}
        self.problems: list[str] = []
        self.notes: Counter[str] = Counter()

    def add_source(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._add(self.sources, record, "source")

    def add_observation(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._add(self.observations, record, "observation")

    def add_knowledge(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._add(self.knowledge, record, "knowledge")

    def _add(self, table: dict[str, dict[str, Any]], record: dict[str, Any], what: str) -> dict[str, Any]:
        key = record["id"] if what != "observation" else record["evidence_id"]
        if key in table or key in self.sources or key in self.knowledge:
            self.problems.append(f"duplicate {what} id: {key}")
            return record
        table[key] = record
        self.notes[what] += 1
        return record

    def issue(
        self,
        kind: str,
        subject: str,
        description: str,
        *,
        severity: str = "warning",
        affects: tuple[str, ...] = (),
        evidence: tuple[str, ...] = (),
        detected_by: str = "",
    ) -> str:
        """Create an issue record and return its id. Issue ids are stable: kind plus subject."""
        if severity not in ISSUE_SEVERITIES:
            raise ValueError(f"unknown severity {severity!r}")
        base = f"issue:{kind}:{subject}"
        issue_id, number = base, 2
        while issue_id in self.issues:
            issue_id = f"{base}#{number}"
            number += 1
        self.issues[issue_id] = {
            "id": issue_id,
            "kind": kind,
            "subject": subject,
            "severity": severity,
            "affects": sorted(set(affects)),
            "description": description,
            "evidence": list(evidence),
            "detected_by": detected_by,
        }
        return issue_id


def make_source(
    root: Path,
    *,
    record_id: str,
    kind: str,
    title: str,
    paths: list[Path] | tuple[Path, ...] = (),
    category: str | None = None,
    family: str | None = None,
    owner: str | None = None,
    bridge_ids: list[str] | tuple[str, ...] = (),
    existing_ids: dict[str, Any] | None = None,
    completeness: dict[str, Any] | None = None,
    verification: dict[str, Any] | None = None,
    trust: dict[str, Any] | None = None,
    eligibility: dict[str, str] | None = None,
    provenance: dict[str, Any] | None = None,
    summary: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One source record. The fingerprint covers every listed file, so a changed file shows up as stale."""
    from .common import fingerprint, rel, sha256_file  # local import keeps model.py free of file access at import

    path_list = [Path(p) for p in paths]
    existing = [p for p in path_list if p.is_file()]
    record: dict[str, Any] = {
        "id": record_id,
        "kind": kind,
        "category": category,
        "title": title,
        "summary": summary,
        "family": family,
        "owner": owner,
        "bridge_ids": sorted(set(bridge_ids)),
        "source_paths": [rel(root, p) for p in path_list],
        "source_sha256": sha256_file(existing[0]) if len(existing) == 1 else None,
        "fingerprint": fingerprint(root, path_list),
        "existing_ids": existing_ids or {},
        "completeness": completeness or {},
        "verification": verification or {"human_verified": False, "checked_against_picture": "none"},
        "trust": trust or {},
        "eligibility": eligibility or {},
        "provenance": provenance or {},
        "issues": [],
    }
    if extra:
        record.update(extra)
    return record
