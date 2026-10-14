"""Shared helpers for agentctx: repository root, fingerprints, JSON files.

The repository root is found by tools/paths.py (ROOT_MARKER or START_HERE.md, or the GAD_ROOT variable).
This module loads that file instead of copying its logic, so every tool agrees on where the repository is.

Nothing here writes outside agent-context/, except through write_* called by the registry build.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Iterable

PACKAGE_DIR: Path = Path(__file__).resolve().parent
CONTEXT_DIR: Path = PACKAGE_DIR.parent
GENERATOR: str = "agentctx 1.0"
REGISTRY_VERSION: str = "1.0"
PACK_VERSION: str = "1.0"


def _load_tools_paths() -> Any:
    """Load tools/paths.py by file path, so its ROOT is the one the rest of the repository uses."""
    tools_paths = PACKAGE_DIR.parents[1] / "tools" / "paths.py"
    spec = importlib.util.spec_from_file_location("gad_tools_paths", tools_paths)
    if spec is None or spec.loader is None:
        raise SystemExit(f"agentctx: cannot load {tools_paths}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DEFAULT_ROOT: Path = _load_tools_paths().ROOT


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def rel(root: Path, path: Path | str) -> str:
    """Repository-relative posix path. Paths outside the repository keep their '../' form, so they stay visible."""
    return Path(os.path.relpath(Path(path), root)).as_posix()


def fingerprint(root: Path, paths: Iterable[Path]) -> str:
    """One digest over (path, content hash) of every listed file. A missing file is recorded as MISSING."""
    digest = hashlib.sha256()
    for path in sorted({Path(p) for p in paths}, key=lambda p: str(p)):
        content = sha256_file(path) if path.is_file() else "MISSING"
        digest.update(f"{rel(root, path)}\t{content}\n".encode("utf-8"))
    return digest.hexdigest()


def read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> Any:
    """Parse one JSON file. Returns None when the file is missing; raises ValueError when it is broken."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read a JSONL file. Returns (rows, problems); a broken line is reported, never silently skipped."""
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    if not path.is_file():
        return rows, problems
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"{path.name} line {number}: {exc.msg}")
                continue
            if isinstance(value, dict):
                rows.append(value)
            else:
                problems.append(f"{path.name} line {number}: not a JSON object")
    return rows, problems


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """Write rows as canonical JSON lines (sorted keys), atomically. Returns the number of rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
            count += 1
    os.replace(tmp, path)
    return count


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def clip(text: Any, limit: int = 400) -> str | None:
    if text is None:
        return None
    value = " ".join(str(text).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"
