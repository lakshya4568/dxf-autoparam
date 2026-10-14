"""Adapter: status documents and their claims, compared with the disk.

Each status document is registered as a source (kind status_document, no category). When a document states a
count or a folder that the disk does not confirm, that is recorded as a status_conflict or stale_document issue.
The disk value is the one reported; the document is never edited or trusted over the disk.
"""

from __future__ import annotations

import re

from ..common import clip, read_jsonl, read_text
from ..model import Collector, make_source
from ..policy import BINDING_KNOWLEDGE_BLOCKER, eligibility

STATUS_DOCS = [
    "REPORT.md", "grounding_audit.md", "agent/out/rdso-extract/_STATUS_AUDIT.txt",
    "agent/out/rdso-extract/_STATUS_REPORT.md", "agent/out/rdso-extract/_VERIFICATION.md",
    "agent/out/rdso-extract/_RUN_LOG.md", "agent/out/rdso-extract/READ_ME_FIRST.md",
    "agent/out/file-status/READ_ME_FIRST.md", "agent/out/file-status/CHECKED_BY_HAND.txt",
    "catalog/SUMMARY.md", "knowledge/kb/import_report.md", "agent/out/_NEXT.md",
]
ID_RX = re.compile(r"\b(?:v-)?[0-9a-f]{12}-p\d+\b")


def collect(col: Collector) -> None:
    root = col.root
    for relpath in STATUS_DOCS:
        path = root / relpath
        if not path.is_file():
            continue
        text = read_text(path) or ""
        heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), path.name)
        record = make_source(
            root, record_id=f"status:{relpath}", kind="status_document", title=clip(heading, 200) or relpath,
            paths=[path], category=None,
            completeness={"lines": text.count("\n") + 1},
            trust={"label_source": "human_or_llm_note", "epistemic": "UNKNOWN",
                   "note": "a claim in this document is not trusted until the disk confirms it"},
            eligibility=eligibility(retrieval_ok=True, retrieval_reason="status_note",
                                    binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                    finetune_blockers=["not_training_data"]),
            provenance={"path": relpath}, summary=clip(text, 200),
        )
        col.add_source(record)
    _report_folders(col)
    _rdso_claim(col)
    _catalog_claim(col)
    _grounding_audit(col)


def _report_folders(col: Collector) -> None:
    root = col.root
    text = read_text(root / "REPORT.md") or ""
    match = re.search(r"Top-level folders now:\s*(.+)", text)
    if not match:
        return
    claimed = [name.strip().rstrip(".") for name in match.group(1).split(",") if name.strip()]
    missing = [name for name in claimed if not (root / name).exists()]
    if missing:
        col.issue(
            "stale_document", "REPORT.md",
            f"REPORT.md (2026-10-09) lists top-level folders that no longer exist: {', '.join(missing)}. "
            "The disk is authoritative; the report is historical.",
            severity="warning", affects=("retrieval",), evidence=("REPORT.md",), detected_by="status.report_folders",
        )


def _rdso_claim(col: Collector) -> None:
    root = col.root
    text = read_text(root / "agent/out/rdso-extract/READ_ME_FIRST.md") or ""
    match = re.search(r"(\d+) of (\d+) PDFs complete.*?(\d+) of (\d+) pages saved", text, re.S)
    if not match:
        return
    claimed_pages = int(match.group(3))
    disk_pages = sum(1 for r in col.sources.values() if r.get("kind") == "rdso_page"
                     and (r.get("completeness") or {}).get("saved"))
    if claimed_pages != disk_pages:
        col.issue(
            "status_conflict", "agent/out/rdso-extract/READ_ME_FIRST.md",
            f"the older RDSO status page says {claimed_pages} pages saved; the disk has {disk_pages}. "
            "The disk count is reported.",
            severity="warning", affects=("binding",), evidence=("agent/out/rdso-extract/READ_ME_FIRST.md",),
            detected_by="status.rdso_claim",
        )


def _catalog_claim(col: Collector) -> None:
    root = col.root
    text = read_text(root / "catalog/SUMMARY.md") or ""
    match = re.search(r"Classified \(any source\):\s*(\d+)\.\s*Grounded.*?:\s*(\d+)", text)
    if not match:
        return
    claimed_classified, claimed_grounded = int(match.group(1)), int(match.group(2))
    rows, _ = read_jsonl(root / "catalog/gad_catalog.jsonl")
    disk_classified = sum(1 for r in rows if r.get("classification"))
    disk_grounded = sum(1 for r in rows if (r.get("grounding") or {}).get("state") not in (None, "none"))
    if (claimed_classified, claimed_grounded) != (disk_classified, disk_grounded):
        col.issue(
            "status_conflict", "catalog/SUMMARY.md",
            f"catalog summary says {claimed_classified} classified and {claimed_grounded} grounded; the catalog rows "
            f"show {disk_classified} and {disk_grounded}. The rows are reported.",
            severity="warning", affects=("binding",), evidence=("catalog/SUMMARY.md",),
            detected_by="status.catalog_claim",
        )


def _grounding_audit(col: Collector) -> None:
    """grounding_audit.md gives a verdict per sheet. A verdict that names a difference is raised as an issue."""
    root = col.root
    text = read_text(root / "grounding_audit.md") or ""
    for line in text.splitlines():
        if not line.startswith("|") or "`" not in line:
            continue
        ids = ID_RX.findall(line)
        if not ids:
            continue
        verdict = line.split("|")[-2] if line.count("|") >= 2 else ""
        lowered = verdict.lower()
        if ("small difference" in lowered or "was **wrong**" in lowered) and not lowered.strip().startswith("no"):
            record_id = ids[0]
            col.issue(
                "audit_difference", record_id,
                f"grounding audit (title block read at zoom): {clip(verdict, 300)}",
                severity="warning", affects=("binding",), evidence=("grounding_audit.md",),
                detected_by="status.grounding_audit",
            )
