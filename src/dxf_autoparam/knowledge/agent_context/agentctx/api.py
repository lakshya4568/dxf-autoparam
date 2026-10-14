"""The public operations. Agent skills, the CLI and other applications all call these, and nothing else.

    import sys; sys.path.insert(0, "agent-context")
    from agentctx import Context
    ctx = Context()                                   # the repository this package sits in
    ctx.search_knowledge("weep hole", categories={"B", "C"})
    ctx.get_evidence("21cc08a32dd8-p1#D1")
    ctx.get_source_status("21cc08a32dd8-p1")
    pack = ctx.build_evidence_pack("21cc08a32dd8-p1", "dimension_binding")
    ctx.validate_evidence_pack(pack)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import CONTEXT_DIR, DEFAULT_ROOT, write_json
from .packs import TASKS, PackError, build_pack
from .registry import build
from .store import RegistryMissing, Store
from .validate import check_registry, validate_pack


class Context:
    def __init__(self, root: Path | str | None = None, context_dir: Path | str | None = None) -> None:
        self.root = Path(root or DEFAULT_ROOT).resolve()
        if context_dir is None:
            context_dir = CONTEXT_DIR if self.root == DEFAULT_ROOT.resolve() else self.root / "agent-context"
        self.context_dir = Path(context_dir).resolve()
        self._store: Store | None = None

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = Store(self.root, self.context_dir)
        return self._store

    def _reset(self) -> None:
        self._store = None

    # --- build ---------------------------------------------------------------------------------------------------
    def build_registry(self) -> dict[str, Any]:
        """Rebuild the registry, knowledge index and reports from the repository. Deterministic."""
        summary = build(self.root, self.context_dir)
        self._reset()
        return summary

    # --- the five operations ---------------------------------------------------------------------------------------
    def search_knowledge(self, query: str, *, categories: set[str] | None = None, topics: set[str] | None = None,
                         include_sources: bool = False, limit: int = 20) -> list[dict[str, Any]]:
        """Find knowledge records by words. Each hit keeps its category and trust labels."""
        return self.store.search_knowledge(query, categories=categories, topics=topics,
                                           include_sources=include_sources, limit=limit)

    def search_observations(self, query: str, *, owner: str | None = None, obs_kinds: set[str] | None = None,
                            limit: int = 50) -> list[dict[str, Any]]:
        """Find drawing observations (category A) by words, optionally within one record."""
        return self.store.search_observations(query, owner=owner, obs_kinds=obs_kinds, limit=limit)

    def get_evidence(self, evidence_id: str, *, live: bool = False) -> dict[str, Any]:
        """Resolve an evidence id (`<record_id>#<local>`, `kb:<id>`, a source id) to its stored record."""
        return self.store.get_evidence(evidence_id, live=live)

    def get_source_status(self, record_id: str) -> dict[str, Any]:
        """Completeness, verification, eligibility for each purpose, issues, and whether sources changed."""
        return self.store.get_source_status(record_id)

    def build_evidence_pack(self, record_id: str, task: str, *, scope: dict[str, Any] | None = None,
                            cad_snapshot: Path | str | None = None, write: bool = True,
                            out_dir: Path | str | None = None) -> dict[str, Any]:
        """A focused, derived pack for one record and one task. Written to agent-context/packs/ unless write=False."""
        pack = build_pack(self.store, record_id, task, scope=scope,
                          cad_snapshot=Path(cad_snapshot) if cad_snapshot else None)
        if write:
            folder = Path(out_dir) if out_dir else self.context_dir / "packs"
            write_json(folder / f"{pack['pack_id']}.json", pack)
            _update_pack_index(folder)
        return pack

    def validate_evidence_pack(self, pack: dict[str, Any] | Path | str) -> dict[str, Any]:
        """Check a pack (dict or file) against its schema, the registry, and the current files."""
        if not isinstance(pack, dict):
            pack = json.loads(Path(pack).read_text(encoding="utf-8"))
        return validate_pack(self.store, pack)

    # --- checks ---------------------------------------------------------------------------------------------------
    def check(self) -> dict[str, Any]:
        """Changed inputs, stale packs, broken source paths. Reports only."""
        return check_registry(self.store, self.context_dir / "packs")

    def tasks(self) -> dict[str, str]:
        return dict(TASKS)


def _update_pack_index(folder: Path) -> None:
    entries = []
    for path in sorted(folder.glob("pack-*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        entries.append({"file": path.name, "pack_id": pack["pack_id"], "task": pack["task"]["name"],
                        "record_id": pack["subject"]["record_id"], "completeness": pack["completeness"]["status"]})
    write_json(folder / "index.json", {"packs": entries})


# Module-level convenience functions, bound to the repository this package is in.
_default: Context | None = None


def _ctx() -> Context:
    global _default
    if _default is None:
        _default = Context()
    return _default


def search_knowledge(query: str, **kwargs: Any) -> list[dict[str, Any]]:
    return _ctx().search_knowledge(query, **kwargs)


def get_evidence(evidence_id: str, **kwargs: Any) -> dict[str, Any]:
    return _ctx().get_evidence(evidence_id, **kwargs)


def get_source_status(record_id: str) -> dict[str, Any]:
    return _ctx().get_source_status(record_id)


def build_evidence_pack(record_id: str, task: str, **kwargs: Any) -> dict[str, Any]:
    return _ctx().build_evidence_pack(record_id, task, **kwargs)


def validate_evidence_pack(pack: dict[str, Any] | Path | str) -> dict[str, Any]:
    return _ctx().validate_evidence_pack(pack)


__all__ = ["Context", "PackError", "RegistryMissing", "search_knowledge", "get_evidence", "get_source_status",
           "build_evidence_pack", "validate_evidence_pack", "build"]
