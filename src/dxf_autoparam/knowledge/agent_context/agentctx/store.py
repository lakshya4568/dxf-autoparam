"""Read side: load the registry, resolve evidence ids, report the status of a source, search observations.

Everything here reads files under agent-context/registry and agent-context/knowledge. Repository sources are read
only to check whether they changed since the build, or to show the live item an observation came from.
"""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path
from typing import Any

from .common import canonical_json, read_jsonl, sha256_file
from .knowledge import rank, tokens


class RegistryMissing(RuntimeError):
    pass


class Store:
    def __init__(self, root: Path, context_dir: Path) -> None:
        self.root = root
        self.context_dir = context_dir

    # --- loading -----------------------------------------------------------------------------------------------
    def _need(self, name: str) -> Path:
        path = self.context_dir / name
        if not path.is_file():
            raise RegistryMissing(f"{path} is missing. Run: .venv/bin/python agent-context/ctx.py build")
        return path

    @cached_property
    def manifest(self) -> dict[str, Any]:
        return json.loads(self._need("registry/manifest.json").read_text(encoding="utf-8"))

    @cached_property
    def sources(self) -> dict[str, dict[str, Any]]:
        rows, _ = read_jsonl(self._need("registry/sources.jsonl"))
        return {row["id"]: row for row in rows}

    @cached_property
    def knowledge(self) -> dict[str, dict[str, Any]]:
        rows, _ = read_jsonl(self._need("knowledge/knowledge.jsonl"))
        return {row["id"]: row for row in rows}

    @cached_property
    def kb_by_kb_id(self) -> dict[str, dict[str, Any]]:
        """Accepted knowledge-base entries only. A proposal with the same kb_id never replaces its entry."""
        return {row["kb_id"]: row for row in self.knowledge.values()
                if row.get("kb_id") and row.get("proposal_status") == "none"}

    @cached_property
    def issues(self) -> dict[str, dict[str, Any]]:
        rows, _ = read_jsonl(self._need("registry/issues.jsonl"))
        return {row["id"]: row for row in rows}

    @cached_property
    def observations(self) -> dict[str, dict[str, Any]]:
        rows, _ = read_jsonl(self._need("registry/observations.jsonl"))
        return {row["evidence_id"]: row for row in rows}

    @cached_property
    def token_index(self) -> dict[str, list[str]]:
        data = json.loads(self._need("knowledge/search_index.json").read_text(encoding="utf-8"))
        return data["tokens"]

    @cached_property
    def component_definitions(self) -> dict[str, list[str]]:
        """grounding part class -> knowledge record ids whose grounding.class names it (from the KB, not invented)."""
        out: dict[str, list[str]] = {}
        for record in self.knowledge.values():
            cls = ((record.get("raw") or {}).get("grounding") or {}).get("class")
            if cls and record.get("kb_id"):
                out.setdefault(cls, []).append(record["id"])
        return {k: sorted(v) for k, v in out.items()}

    # --- queries -----------------------------------------------------------------------------------------------
    def issues_for(self, record_id: str) -> list[dict[str, Any]]:
        """Issues on the record, on its owner (an RDSO page inherits its document's, a grounding its sheet's)."""
        ids: set[str] = set()
        record = self.sources.get(record_id) or self.knowledge.get(record_id) or {}
        ids.update(record.get("issues") or [])
        owner = record.get("owner")
        subjects = {record_id} | ({owner} if owner else set())
        for issue in self.issues.values():
            if any(issue["subject"] == s or issue["subject"].startswith(s + ":") for s in subjects):
                ids.add(issue["id"])
        return [self.issues[i] for i in sorted(ids) if i in self.issues]

    def find_source(self, record_id: str) -> dict[str, Any] | None:
        return self.sources.get(record_id)

    def search_knowledge(self, query: str, *, categories: set[str] | None = None, topics: set[str] | None = None,
                         include_sources: bool = False, limit: int = 20) -> list[dict[str, Any]]:
        pool: dict[str, dict[str, Any]] = dict(self.knowledge)
        if include_sources:
            pool.update(self.sources)
        candidates = [rid for rid, rec in pool.items()
                      if (categories is None or rec.get("category") in categories)
                      and (topics is None or rec.get("topic") in topics)]
        ranked = rank(query, pool, self.token_index, candidates)[:limit]
        out = []
        for score, record_id in ranked:
            record = pool[record_id]
            out.append({
                "id": record_id,
                "score": round(score, 3),
                "category": record.get("category"),
                "title": record.get("title"),
                "kind": record.get("kind") or record.get("kind"),
                "topic": record.get("topic"),
                "statement": record.get("statement") or record.get("summary"),
                "trust": record.get("trust") or {},
                "eligibility": record.get("eligibility") or {},
                "source": record.get("source_path") or ", ".join(record.get("source_paths") or []),
            })
        return out

    def search_observations(self, query: str, *, owner: str | None = None, obs_kinds: set[str] | None = None,
                            limit: int = 50) -> list[dict[str, Any]]:
        terms = tokens(query)
        if not terms:
            return []
        hits: list[tuple[int, str]] = []
        for evidence_id, obs in self.observations.items():
            if owner and obs["owner_id"] != owner:
                continue
            if obs_kinds and obs["obs_kind"] not in obs_kinds:
                continue
            text = " ".join(str(x) for x in (obs.get("raw_text"), canonical_json(obs.get("candidate_interpretation") or {}))
                            if x).lower()
            score = sum(1 for term in set(terms) if term in text)
            if score:
                hits.append((score, evidence_id))
        hits.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self._observation_view(self.observations[eid]) for _, eid in hits[:limit]]

    def _observation_view(self, obs: dict[str, Any]) -> dict[str, Any]:
        return {
            "evidence_id": obs["evidence_id"],
            "owner_id": obs["owner_id"],
            "obs_kind": obs["obs_kind"],
            "raw_text": obs.get("raw_text"),
            "candidate_interpretation": obs.get("candidate_interpretation"),
            "view": obs.get("view"),
            "geometry": obs.get("geometry"),
            "trust": obs.get("trust"),
            "eligibility": obs.get("eligibility"),
        }

    def get_evidence(self, evidence_id: str, *, live: bool = False) -> dict[str, Any]:
        """Resolve one evidence id to its stored record (and optionally the live item in the source file)."""
        if "#" in evidence_id:
            obs = self.observations.get(evidence_id)
            if obs is None:
                return {"found": False, "evidence_id": evidence_id, "reason": "no observation with this id"}
            owner = self.sources.get(obs["owner_id"]) or {}
            result = {"found": True, "kind": "observation", "evidence_id": evidence_id,
                      "record": obs, "owner": _summary(owner), "source": self._source_state(owner)}
            if live:
                result["live_item"] = self._live_item(owner, obs)
            return result
        if evidence_id in self.issues:
            return {"found": True, "kind": "issue", "evidence_id": evidence_id, "record": self.issues[evidence_id]}
        record = self.knowledge.get(evidence_id) or self.kb_by_kb_id.get(evidence_id) or self.sources.get(evidence_id)
        if record is None:
            return {"found": False, "evidence_id": evidence_id, "reason": "no record with this id"}
        kind = "knowledge" if evidence_id in self.knowledge or evidence_id in self.kb_by_kb_id else "source"
        result = {"found": True, "kind": kind, "evidence_id": record["id"], "record": record,
                  "source": self._source_state(record)}
        return result

    def get_source_status(self, record_id: str) -> dict[str, Any]:
        record = self.sources.get(record_id) or self.knowledge.get(record_id)
        if record is None:
            return {"found": False, "record_id": record_id, "reason": "not in the registry"}
        issues = self.issues_for(record_id)
        status = {
            "found": True,
            "record_id": record_id,
            "kind": record.get("kind"),
            "category": record.get("category"),
            "title": record.get("title"),
            "family": record.get("family"),
            "bridge_ids": record.get("bridge_ids") or [],
            "completeness": record.get("completeness") or {},
            "verification": record.get("verification") or {},
            "trust": record.get("trust") or {},
            "eligibility": record.get("eligibility") or {},
            "issues": [{"id": i["id"], "kind": i["kind"], "severity": i["severity"], "blocks": i["affects"],
                        "description": i["description"]} for i in issues],
            "source": self._source_state(record),
            "registry_built_from": self.manifest.get("registry_digest"),
            "observations": self._observation_counts(record_id),
        }
        status["summary"] = _one_line_status(status)
        return status

    def _observation_counts(self, record_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for obs in self.observations.values():
            if obs["owner_id"] == record_id:
                counts[obs["obs_kind"]] = counts.get(obs["obs_kind"], 0) + 1
        return dict(sorted(counts.items()))

    def _source_state(self, record: dict[str, Any]) -> dict[str, Any]:
        """Compare each file the record depends on with its hash at build time."""
        built = self.manifest.get("input_hashes", {})
        paths = record.get("source_paths") or []
        if record.get("source_path"):
            paths = paths + [record["source_path"]]
        present, changed, missing = [], [], []
        for relpath in sorted(set(paths)):
            path = (self.root / relpath) if not relpath.startswith("..") else (self.root / relpath).resolve()
            if not path.is_file():
                missing.append(relpath)
                continue
            present.append(relpath)
            if relpath in built and built[relpath] != sha256_file(path):
                changed.append(relpath)
        return {"files_present": len(present), "files_missing": missing, "changed_since_build": changed,
                "stale": bool(changed or missing)}

    def _live_item(self, owner: dict[str, Any], obs: dict[str, Any]) -> Any:
        """The item as it is in the source file right now (grounding JSON, RDSO page JSON or vector text line)."""
        local = obs["local_id"]
        paths = owner.get("source_paths") or []
        if obs["owner_kind"] == "drawing_sheet" and paths:
            data = json.loads((self.root / paths[0]).read_text(encoding="utf-8")) if paths[0].endswith(".json") else None
            if data is None:
                return None
            section = {"view": "views", "text": "texts", "dimension": "dimensions", "level": "levels",
                       "part": "parts", "repeat": "repeats", "table": "tables"}.get(obs["obs_kind"])
            if section:
                return next((item for item in data.get(section, []) if item.get("id") == local), None)
            return None
        if obs["owner_kind"] == "rdso_page" and paths:
            data = json.loads((self.root / paths[0]).read_text(encoding="utf-8"))
            return data
        if obs["owner_kind"] == "vector_sheet":
            text_path = next((p for p in paths if p.endswith("text.jsonl")), None)
            if text_path:
                rows, _ = read_jsonl(self.root / text_path)
                return next((row for row in rows if row.get("id") == local), None)
        return None


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    return {"id": record.get("id"), "kind": record.get("kind"), "title": record.get("title"),
            "family": record.get("family"), "source_paths": record.get("source_paths") or []}


def _one_line_status(status: dict[str, Any]) -> str:
    parts = []
    capability = (status.get("completeness") or {}).get("capability")
    if capability:
        parts.append(capability.replace("_", " "))
    if status["source"]["stale"]:
        parts.append("source changed since build: rebuild")
    blocked = {k: v for k, v in (status.get("eligibility") or {}).items() if str(v).startswith("blocked")}
    if blocked:
        parts.append("blocked for " + ", ".join(sorted(blocked)))
    if status["issues"]:
        parts.append(f"{len(status['issues'])} issue(s)")
    return "; ".join(parts) or "no status recorded"
