"""Copy aagento-bridge's graded engineering knowledge into this project's bridge library, byte for byte, with where it came from.

    uv run python tools/import_graded_knowledge.py [--repo DIR] [--ref BRANCH] [--check]

What it does, and does not do:
  • The source repository is only READ, through `git show <ref>:<path>`: nothing is checked out, created or changed there (another session may
    be working in it on another branch).
  • The files are the knowledge layer as aagento-bridge keeps it — sources (with their trust), concepts, families (recognition, components,
    required inputs, level chains), formulas (with status: DERIVED, ASSUMPTION, DISPUTED …), rules (NORMATIVE only where a verified clause is
    cited), defaults (each with its status), conflicts (KC-n: the positions and how each was resolved, or that it is OPEN) and the clause index
    of the IRBM 2024 copy in hand. Nothing is edited: a correction is made there and imported again.
  • `PROVENANCE.json` records the repository, the ref, its commit and the sha256 of every file; `--check` (and the tests) compare.

The destination is `src/dxf_autoparam/knowledge/library/bridge/graded/`. The runtime reads it through `dxf_autoparam.ai.library`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src" / "dxf_autoparam" / "knowledge" / "library" / "bridge" / "graded"
DEFAULT_REPO = ROOT.parent / "aagento-bridge"
DEFAULT_REF = "feature/upce-cad-migration"
FILES = {  # stored name → path in the source repository
    "sources.json": "knowledge/sources.json",
    "concepts.json": "knowledge/concepts.json",
    "families.json": "knowledge/families.json",
    "formulas.json": "knowledge/formulas.json",
    "rules.json": "knowledge/rules.json",
    "defaults.json": "knowledge/defaults.json",
    "conflicts.json": "knowledge/conflicts.json",
    "irbm-2024.json": "knowledge/extracted/irbm-2024.json",
}
PROVENANCE = "PROVENANCE.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def check(dest: Path = DEST) -> list[str]:
    """What differs from the provenance record: a missing file, a changed one, or one nobody recorded."""
    prov = json.loads((dest / PROVENANCE).read_text(encoding="utf-8"))
    bad = []
    for name, rec in prov["files"].items():
        p = dest / name
        if not p.is_file():
            bad.append(f"{name}: missing")
        elif sha256(p.read_bytes()) != rec["sha256"]:
            bad.append(f"{name}: changed since it was imported (edit it in the source repository and import again)")
    extra = sorted(p.name for p in dest.iterdir() if p.is_file() and p.name not in prov["files"] and p.name != PROVENANCE)
    bad += [f"{n}: not in the provenance record" for n in extra]
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    ap.add_argument("--ref", default=DEFAULT_REF)
    ap.add_argument("--check", action="store_true", help="only compare the stored files with PROVENANCE.json")
    a = ap.parse_args()
    if a.check:
        bad = check()
        print("\n".join(bad) or f"graded knowledge as imported ({len(json.loads((DEST / PROVENANCE).read_text())['files'])} files)")
        return 1 if bad else 0
    commit = git(a.repo, "rev-parse", a.ref).decode().strip()
    DEST.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, src in FILES.items():
        data = git(a.repo, "show", f"{commit}:{src}")
        json.loads(data)  # it is JSON, or nothing is written
        (DEST / name).write_bytes(data)
        files[name] = {"source_path": src, "sha256": sha256(data), "bytes": len(data)}
    prov = {"format": "graded-knowledge/1", "repository": "aagento-bridge", "ref": a.ref, "commit": commit,
            "note": "Copied byte for byte by tools/import_graded_knowledge.py; never edited here.", "files": files}
    (DEST / PROVENANCE).write_text(json.dumps(prov, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"imported {len(files)} files from {a.ref} @ {commit[:10]} into {DEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
