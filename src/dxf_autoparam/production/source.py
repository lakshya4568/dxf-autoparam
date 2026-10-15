"""Where the production bridge knowledge comes from: the aagento-bridge checkout, read (never written).

The production app dispatches every bridge family through ONE object, `BRIDGE_REGISTRY` (src/app/features/bridges/models/bridge-registry.ts):
each key names its defaults, rule engine, scene renderer and mappers by the symbols the registry imports. Which module is authoritative is
therefore not a matter of file names — the bridges folder holds stale root-level duplicates of several engines — but of what the registry
imports. This module reads that from the registry's own source and fingerprints those modules (and the local modules they import), so a
manifest generated from one revision can tell when the production code it describes has changed.

    src = locate()                       # the checkout (AAGENTO_BRIDGE_DIR, else ../aagento-bridge next to this project) or None
    reg = registry_modules(src)          # family key → {defaults, rule_engine, scene_renderer, …: {symbol, path}}
    fingerprint(src, reg["railway_rcc_box"])
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

BRIDGES = Path("src/app/features/bridges")
REGISTRY = BRIDGES / "models" / "bridge-registry.ts"
ROLES = ("defaults", "ruleEngine", "sceneRenderer", "workspaceMapper", "versionPayloadMapper", "computedLevelsMapper", "initial2DScaleAndPan",
         "viewButtons", "canvasBasePoint")
_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")
_ANY_IMPORT = re.compile(r"(?:import|export)\s[^;]*?from\s*['\"](\.{1,2}/[^'\"]+)['\"]|require\(\s*['\"](\.{1,2}/[^'\"]+)['\"]\s*\)")


def project_root() -> Path:
    """This project's checkout (the folder holding pyproject.toml), found from this file; the working directory when installed elsewhere."""
    for p in Path(__file__).resolve().parents:
        if (p / "pyproject.toml").is_file():
            return p
    return Path.cwd()


@dataclass
class Source:
    root: Path

    @property
    def registry(self) -> Path:
        return self.root / REGISTRY

    @property
    def bridges(self) -> Path:
        return self.root / BRIDGES

    def rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.root.resolve()).as_posix()


def locate(explicit: str | os.PathLike | None = None) -> Source | None:
    """The aagento-bridge checkout: an explicit path, else AAGENTO_BRIDGE_DIR, else the sibling folder of this project. None when absent —
    the committed manifest still answers questions about the knowledge; only execution and freshness checks need the checkout."""
    for cand in (explicit, os.environ.get("AAGENTO_BRIDGE_DIR"), project_root().parent / "aagento-bridge"):
        if cand and (Path(cand) / REGISTRY).is_file():
            return Source(Path(cand).resolve())
    return None


def _resolve(base: Path, spec: str) -> Path | None:
    p = (base.parent / spec).resolve()
    # dotted module names are common ("rcc-box.defaults", "project-detail.constants"): the extension is appended, never substituted
    for cand in (Path(str(p) + ".ts"), p / "index.ts", p):
        if cand.is_file():
            return cand
    return None


def _entries(text: str) -> dict[str, str]:
    """The registry object's entries, key → body text, by brace matching (the file is plain object literals)."""
    start = text.index("BRIDGE_REGISTRY")
    start = text.index("{", text.index("=", start))
    out: dict[str, str] = {}
    i, depth, key, body0 = start + 1, 1, None, None
    while i < len(text) and depth > 0:
        c = text[i]
        if c in "'\"" and depth == 1 and key is None:
            j = text.index(c, i + 1)
            k = text[i + 1:j]
            rest = text[j + 1:].lstrip()
            if rest.startswith(":"):
                key = k
            i = j
        elif c == "/" and text[i:i + 2] == "//":
            i = text.index("\n", i)
            continue
        elif c == "{":
            depth += 1
            if depth == 2 and key is not None:
                body0 = i
        elif c == "}":
            depth -= 1
            if depth == 1 and key is not None and body0 is not None:
                out[key] = text[body0:i + 1]
                key, body0 = None, None
        i += 1
    return out


def registry_modules(src: Source) -> dict[str, dict[str, dict]]:
    """Per family key: each registered role (defaults, ruleEngine, sceneRenderer, mappers) with the symbol the registry binds and the module
    that symbol is imported from. A role bound to an inline literal (a function or object written in the registry) says so."""
    text = src.registry.read_text()
    symbols: dict[str, Path] = {}
    for names, spec in _IMPORT.findall(text):
        mod = _resolve(src.registry, spec)
        for n in names.split(","):
            n = n.strip()
            if not n:
                continue
            exported, _, local = n.partition(" as ")
            symbols[(local or exported).strip()] = (mod, exported.strip())
    out: dict[str, dict[str, dict]] = {}
    for key, body in _entries(text).items():
        row: dict[str, dict] = {}
        for role in ROLES:
            m = re.search(rf"\b{role}\s*:\s*", body)
            if not m:
                continue
            rest = body[m.end():]
            if rest.startswith("{"):  # an inline object of symbols, e.g. { compute: evaluateX, validate: validateX }
                inner = rest[1:rest.index("}")]
                parts = {}
                for k, v in re.findall(r"(\w+)\s*:\s*(\w+)", inner):
                    mod, exported = symbols.get(v, (None, v))
                    parts[k] = {"symbol": exported, "path": src.rel(mod) if mod else None}
                row[role] = {"inline_object": parts}
                continue
            sym = re.match(r"[A-Za-z_$][\w$]*", rest)
            if sym and sym.group(0) in symbols:
                mod, exported = symbols[sym.group(0)]
                row[role] = {"symbol": exported, "path": src.rel(mod) if mod else None}
            else:
                row[role] = {"inline": True, "text": rest.split("\n", 1)[0][:80]}
        out[key] = row
    return out


def module_paths(row: dict[str, dict]) -> list[str]:
    """Every module path a family's registry entry names (inline objects included), sorted."""
    paths = set()
    for v in row.values():
        if v.get("path"):
            paths.add(v["path"])
        for p in (v.get("inline_object") or {}).values():
            if p.get("path"):
                paths.add(p["path"])
    return sorted(paths)


def closure(src: Source, path: str, limit: int = 60) -> list[str]:
    """The module and the project modules it imports (relative imports, transitively), as repository paths — what decides what a rule engine
    computes. Bounded: a renderer's closure is the whole drawing library, which is fingerprinted by its own module only."""
    seen: list[str] = []
    todo = [src.root / path]
    while todo and len(seen) < limit:
        p = todo.pop()
        r = src.rel(p)
        if r in seen:
            continue
        seen.append(r)
        text = p.read_text(errors="replace")
        for a, b in _ANY_IMPORT.findall(text):
            q = _resolve(p, a or b)
            if q is not None and src.rel(q) not in seen:
                todo.append(q)
    return sorted(seen)


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fingerprint(src: Source, row: dict[str, dict]) -> dict[str, str]:
    """sha256 of the registry, of every module the family's entry names, and of the import closure of its rule engine and defaults."""
    files = {src.rel(src.registry)}
    files |= set(module_paths(row))
    for role in ("ruleEngine", "defaults"):
        v = row.get(role) or {}
        for p in [v.get("path")] + [x.get("path") for x in (v.get("inline_object") or {}).values()]:
            if p:
                files |= set(closure(src, p))
    return {f: sha256(src.root / f) for f in sorted(files)}


def revision(src: Source) -> dict:
    """The checkout's commit and whether the bridges feature (or the constants its engines import) has uncommitted changes."""
    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", "-C", str(src.root), *args], capture_output=True, text=True, timeout=20, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    head = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain", "--", str(BRIDGES), "src/app/features/projects/components/project-detail")
    return {"commit": head or None, "branch": git("rev-parse", "--abbrev-ref", "HEAD") or None,
            "dirty_files": [ln[3:] for ln in dirty.splitlines() if ln.strip()][:40]}
