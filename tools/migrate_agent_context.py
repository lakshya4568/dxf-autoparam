"""Copy the Aagento GAD foundation model's `agent-context` into this project, verified file by file.

    uv run python tools/migrate_agent_context.py [--source DIR] [--dest DIR] [--verify-only]

What it does, and does not do:
  • The source is only READ. Nothing in it is created, changed or removed (the run compares the source tree before and after).
  • Every file is copied byte for byte, except four large generated data files (> 1 MB: the observations, the knowledge records, the token
    index, the source register) which are stored gzip-compressed with a `.gz` suffix. The compression is deterministic (no timestamp, no name)
    and lossless: `MIGRATION.json` records the sha256 of the original bytes and of the stored bytes, and `--verify-only` (and the tests)
    decompress and compare.
  • `__pycache__`, `*.pyc`, `.DS_Store` and temporary files are not copied.
  • Python files are copied as written. They are SOURCE MATERIAL kept for provenance (and to rebuild the registry from the source repository,
    which this project does not have): nothing in this project imports them, and the linter skips the folder.

The destination is `src/dxf_autoparam/knowledge/agent_context/`. The runtime reads it through `dxf_autoparam.ai.library`; it never needs
the source directory again. Re-running the tool on an unchanged source changes nothing (the manifest has no timestamps).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = ROOT / "src" / "dxf_autoparam" / "knowledge" / "agent_context"
DEFAULT_SOURCE = ROOT.parent / "Aagento-GAD-Foundation-Model" / "agent-context"  # the workspace layout; override with --source or AGENT_CONTEXT_SRC
MANIFEST = "MIGRATION.json"
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache"}
SKIP_SUFFIXES = {".pyc", ".tmp"}
SKIP_NAMES = {".DS_Store"}
COMPRESS_OVER = 1_000_000  # bytes: a data file larger than this is stored gzip-compressed
COMPRESS_SUFFIXES = {".jsonl", ".json"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gzip_bytes(data: bytes) -> bytes:
    """Deterministic gzip: no mtime, no file name."""
    import io

    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, compresslevel=9, mtime=0) as g:
        g.write(data)
    return buf.getvalue()


def source_files(src: Path) -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if name in SKIP_NAMES or p.suffix in SKIP_SUFFIXES or p.is_symlink():
                continue
            out.append(p)
    return sorted(out, key=lambda p: p.relative_to(src).as_posix())


def tree_digest(files: list[tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for rel, digest in files:
        h.update(f"{rel}\t{digest}\n".encode())
    return h.hexdigest()


def migrate(src: Path, dest: Path) -> dict:
    if not src.is_dir():
        raise SystemExit(f"migrate: the source folder does not exist: {src}")
    before = [(p.relative_to(src).as_posix(), sha256_file(p)) for p in source_files(src)]
    entries = []
    dest.mkdir(parents=True, exist_ok=True)
    for p in source_files(src):
        rel = p.relative_to(src).as_posix()
        data = p.read_bytes()
        stored_rel, stored = rel, data
        transform = "none"
        if len(data) > COMPRESS_OVER and p.suffix in COMPRESS_SUFFIXES:
            stored_rel, stored, transform = rel + ".gz", gzip_bytes(data), "gzip"
        target = dest / stored_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != stored:
            target.write_bytes(stored)
        entries.append({"path": rel, "bytes": len(data), "sha256": sha256_bytes(data), "stored": stored_rel, "stored_bytes": len(stored),
                        "stored_sha256": sha256_bytes(stored), "transform": transform})
    # remove files a previous run stored that the source no longer has (the destination mirrors the source exactly)
    keep = {e["stored"] for e in entries} | {MANIFEST, "MIGRATION.md"}
    for p in sorted(dest.rglob("*")):
        if p.is_file() and p.relative_to(dest).as_posix() not in keep:
            p.unlink()
    after = [(p.relative_to(src).as_posix(), sha256_file(p)) for p in source_files(src)]
    if before != after:
        raise SystemExit("migrate: the source changed while it was being copied; run again")
    manifest = {
        "source": "Aagento-GAD-Foundation-Model/agent-context",
        "tool": "tools/migrate_agent_context.py",
        "source_tree_sha256": tree_digest(before),
        "files": entries,
        "totals": {"files": len(entries), "bytes": sum(e["bytes"] for e in entries), "stored_bytes": sum(e["stored_bytes"] for e in entries),
                   "compressed": sum(1 for e in entries if e["transform"] == "gzip")},
        "excluded": {"directories": sorted(SKIP_DIRS), "suffixes": sorted(SKIP_SUFFIXES), "names": sorted(SKIP_NAMES)},
        "classification": {
            "source_material": "every file in this folder: copied from the source, never edited by this project",
            "generated_by_the_source": ["registry/", "knowledge/", "packs/", "reports/"],
            "runtime_built_elsewhere": "the library's own index is built in memory (and may be cached under .cache/library/), never stored here",
        },
    }
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    (dest / "MIGRATION.md").write_text(summary_md(manifest))
    return manifest


def summary_md(m: dict) -> str:
    t = m["totals"]
    gz = [e for e in m["files"] if e["transform"] == "gzip"]
    lines = [
        "# Migrated agent-context (source material)", "",
        (f"Copied from `{m['source']}` by `{m['tool']}`. {t['files']} files, {t['bytes']:,} bytes as they were in the source, "
         f"{t['stored_bytes']:,} bytes stored here. Source tree digest: `{m['source_tree_sha256']}`."), "",
        "Nothing in this folder is edited by this project. Hashes of every file (as in the source, and as stored) are in `MIGRATION.json`;",
        "`uv run python tools/migrate_agent_context.py --verify-only` and `tests/test_migration.py` check them.", "",
        "## Transformations", "",
        "Only one: files larger than 1 MB (generated data) are stored gzip-compressed, losslessly, with a `.gz` suffix:", "",
        *(f"- `{e['path']}` → `{e['stored']}` ({e['bytes']:,} → {e['stored_bytes']:,} bytes)" for e in gz), "",
        "## Not copied", "",
        (f"Directories {', '.join(m['excluded']['directories'])}; suffixes {', '.join(m['excluded']['suffixes'])}; "
         f"names {', '.join(m['excluded']['names'])}."), "",
        "## What each part is", "",
        "| Path | What it is | Used at runtime |", "|---|---|---|",
        "| `skills/` | the source's agent skills (written for its repository command line) | parsed by section by `ai/library.py` |",
        "| `knowledge/knowledge.jsonl.gz` | 2,914 knowledge records (B reference, C vocabulary, D proposed or disputed, E operational) | yes |",
        "| `registry/sources.jsonl.gz`, `registry/issues.jsonl` | the source register and known problems | yes (references) |",
        "| `registry/observations.jsonl.gz` | printed items read from sheets, RDSO pages and vector sheets | the rows of the 17 drawing sheets a model has read, as worked examples on request; the RDSO-page and vector-text rows are kept, not used |",
        "| `schemas/` | the record schemas | validation in tests |",
        "| `knowledge/GLOBAL_INDEX.md`, `reports/`, `packs/`, `README.md` | the source's map, reports and demonstration packs | reference only |",
        "| `agentctx/`, `ctx.py`, `tests/`, `scripts/` | the source's library, tests and scripts: they need the source repository (not present here) | **no** — provenance only |",
        "",
    ]
    return "\n".join(lines)


def verify(dest: Path, src: Path | None = None) -> list[str]:
    """Problems found (an empty list: every stored file matches its recorded hash, and the original bytes match when the source is given)."""
    problems: list[str] = []
    mf = dest / MANIFEST
    if not mf.is_file():
        return [f"{mf} is missing"]
    manifest = json.loads(mf.read_text())
    for e in manifest["files"]:
        p = dest / e["stored"]
        if not p.is_file():
            problems.append(f"missing: {e['stored']}")
            continue
        raw = p.read_bytes()
        if sha256_bytes(raw) != e["stored_sha256"]:
            problems.append(f"stored bytes differ: {e['stored']}")
            continue
        original = gzip.decompress(raw) if e["transform"] == "gzip" else raw
        if sha256_bytes(original) != e["sha256"] or len(original) != e["bytes"]:
            problems.append(f"content differs from the source's: {e['path']}")
        if src is not None:
            sp = src / e["path"]
            if not sp.is_file() or sha256_file(sp) != e["sha256"]:
                problems.append(f"the source file differs or is gone: {e['path']}")
    # what the migration never copies is not looked for either: importing the migrated package (its own tests do) writes a __pycache__ next to it
    on_disk = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file() and not (
        SKIP_DIRS & set(p.relative_to(dest).parts[:-1]) or p.name in SKIP_NAMES or p.suffix in SKIP_SUFFIXES)} - {MANIFEST, "MIGRATION.md"}
    extra = on_disk - {e["stored"] for e in manifest["files"]}
    problems += [f"not in the manifest: {x}" for x in sorted(extra)]
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", default=os.environ.get("AGENT_CONTEXT_SRC") or str(DEFAULT_SOURCE))
    ap.add_argument("--dest", default=str(DEFAULT_DEST))
    ap.add_argument("--verify-only", action="store_true", help="check the destination against its manifest (and the source, when it is there)")
    a = ap.parse_args(argv)
    src, dest = Path(a.source), Path(a.dest)
    if a.verify_only:
        problems = verify(dest, src if src.is_dir() else None)
        print("verified: every file matches its recorded hash" + (" and the source" if src.is_dir() else " (the source folder is not present: checked against the manifest only)")
              if not problems else "\n".join(problems))
        return 1 if problems else 0
    manifest = migrate(src, dest)
    problems = verify(dest, src)
    t = manifest["totals"]
    print(f"migrated {t['files']} files ({t['bytes']:,} bytes → {t['stored_bytes']:,} stored, {t['compressed']} compressed) to {dest}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("verified against the source: all files identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
