"""The engineering knowledge that came from the foundation model's `agent-context`: copied exactly, and independent of where it came from.

What is measured: every migrated file matches the hash the manifest recorded (and, when the source folder is next to this project, the
source's own bytes); the migration tool reads the source and never writes to it; the library works with the source folder absent; and no
code of this project points at the source folder."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src" / "dxf_autoparam" / "knowledge" / "agent_context"
SOURCE = Path(os.environ.get("AGENT_CONTEXT_SRC") or ROOT.parent / "Aagento-GAD-Foundation-Model" / "agent-context")
needs_source = pytest.mark.skipif(not SOURCE.is_dir(), reason="the source folder is not next to this project (the migrated copy is self-contained)")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tool():
    spec = importlib.util.spec_from_file_location("migrate_agent_context", ROOT / "tools" / "migrate_agent_context.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((DEST / "MIGRATION.json").read_text())


def test_every_migrated_file_matches_the_hash_the_manifest_recorded(manifest):
    assert manifest["totals"]["files"] == len(manifest["files"]) >= 60
    for e in manifest["files"]:
        stored = (DEST / e["stored"]).read_bytes()
        assert sha(stored) == e["stored_sha256"], e["stored"]
        original = gzip.decompress(stored) if e["transform"] == "gzip" else stored
        assert sha(original) == e["sha256"] and len(original) == e["bytes"], e["path"]
    on_disk = {p.relative_to(DEST).as_posix() for p in DEST.rglob("*") if p.is_file() and "__pycache__" not in p.parts} - {"MIGRATION.json", "MIGRATION.md"}
    assert on_disk == {e["stored"] for e in manifest["files"]}, "a file is here that the manifest does not know, or the other way round"


def test_only_large_generated_data_is_compressed_and_nothing_else_is_changed(manifest):
    zipped = {e["path"] for e in manifest["files"] if e["transform"] == "gzip"}
    assert zipped == {"registry/observations.jsonl", "knowledge/knowledge.jsonl", "knowledge/search_index.json", "registry/sources.jsonl"}
    for e in manifest["files"]:
        if e["transform"] == "none":
            assert e["stored"] == e["path"] and e["bytes"] == e["stored_bytes"]
        else:
            assert e["bytes"] > 1_000_000 and e["stored"] == e["path"] + ".gz"


def test_the_skills_the_source_wrote_are_all_there_and_unedited(manifest):
    paths = {e["path"] for e in manifest["files"]}
    fam = {"arch", "girder", "other", "pipe", "rcc_box", "rcc_slab", "rob", "rub_other"}
    assert {f"skills/families/{f}/SKILL.md" for f in fam} <= paths
    assert {f"skills/{s}/SKILL.md" for s in ("find-source-evidence", "interpret-components", "propose-dimension-bindings",
                                             "propose-geometric-relationships", "handle-uncertainty")} <= paths
    assert {"README.md", "schemas/knowledge-record.schema.json", "registry/issues.jsonl", "knowledge/GLOBAL_INDEX.md", "agentctx/api.py"} <= paths


def test_the_data_the_runtime_reads_is_well_formed():
    rows = [json.loads(line) for line in gzip.decompress((DEST / "knowledge" / "knowledge.jsonl.gz").read_bytes()).decode().splitlines()]
    assert len(rows) == 2914 and {r["category"] for r in rows} == {"B", "C", "D", "E"}
    schema = json.loads((DEST / "schemas" / "knowledge-record.schema.json").read_text())
    assert set(schema["required"]) <= set(rows[0])
    assert all(r["expression"] is None or r["expression"]["executed"] is False for r in rows)  # the source's own promise: expressions are text


@needs_source
def test_the_migrated_files_are_the_sources_own_bytes(manifest):
    problems = tool().verify(DEST, SOURCE)
    assert problems == []


@needs_source
def test_the_tool_reads_the_source_and_never_writes_to_it(tmp_path):
    t = tool()
    before = [(p.relative_to(SOURCE).as_posix(), t.sha256_file(p), p.stat().st_mtime_ns) for p in t.source_files(SOURCE)]
    m1 = t.migrate(SOURCE, tmp_path / "a")
    after = [(p.relative_to(SOURCE).as_posix(), t.sha256_file(p), p.stat().st_mtime_ns) for p in t.source_files(SOURCE)]
    assert before == after
    m2 = t.migrate(SOURCE, tmp_path / "b")
    assert m1 == m2, "the same source must give the same manifest (no timestamps, deterministic compression)"
    assert t.verify(tmp_path / "a", SOURCE) == []
    assert json.loads((DEST / "MIGRATION.json").read_text())["source_tree_sha256"] == m1["source_tree_sha256"]


def test_a_changed_migrated_file_is_caught(tmp_path):
    t = tool()
    copy = tmp_path / "ctx"
    shutil.copytree(DEST, copy)
    assert t.verify(copy) == []
    target = copy / "skills" / "families" / "pipe" / "SKILL.md"
    target.write_text(target.read_text() + "\nedited\n")
    assert any("skills/families/pipe/SKILL.md" in p for p in t.verify(copy))
    (copy / "README.md").unlink()
    assert any("missing: README.md" in p for p in t.verify(copy))


def test_the_library_works_with_the_source_folder_absent(monkeypatch, tmp_path):
    """No lookup reaches outside the project: point the source at nothing and open, search, load and discover."""
    from dxf_autoparam.ai import library as L

    monkeypatch.setenv("AGENT_CONTEXT_SRC", str(tmp_path / "nowhere"))
    L.open_domain.cache_clear()
    lib = L.open_domain("bridge")
    assert lib is not None and len(lib.skills) == 13
    assert lib.search("soffit level", topics={"formula"})
    assert L.KnowledgeSession(lib).call("load_skill", {"id": "family:rcc_box"})["found"]
    assert lib.discover(["RCC BOX CULVERT"])[0]["skill"] == "family:rcc_box"
    for src in lib.sources:  # every source folder the library reads is inside this project
        assert str(src.root).startswith(str(ROOT)), src.root


def test_no_code_of_this_project_points_at_the_source_folder():
    skip = {DEST, ROOT / "src" / "dxf_autoparam" / "knowledge" / "library"}
    offenders = []
    for p in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").glob("*.py")):
        if any(s in p.parents for s in skip) or p.name == "test_migration.py":
            continue
        text = p.read_text(errors="replace")
        if "Aagento-GAD-Foundation-Model" in text or "/Users/" in text:
            offenders.append(p.relative_to(ROOT).as_posix())
    assert offenders == []
