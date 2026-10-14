"""Adapter: RDSO documents, the RCC box page extracts, and their known problems.

Saved, readable, checked and verified are reported separately:
  saved    - the page's JSON and Markdown exist and the JSON parses
  readable - the Markdown is not empty
  checked  - compared with the picture; 'view_level', 'spot_check', 'second_pass' or 'none', taken from the
             hand-written notes in agent/out/file-status/CHECKED_BY_HAND.txt
  verified - always 'none' here: no record in the repository shows a value verified against the picture

Nothing is inferred beyond those notes. A page-level check is never reported as verification of every number.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..common import canonical_json, clip, read_json, read_jsonl, rel, sha256_text, read_text
from ..model import Collector, make_source
from ..policy import (
    BINDING_NO_HUMAN,
    BINDING_NOT_A_VALUE,
    DRAWING_EPISTEMIC,
    eligibility,
    permission_blockers,
)

EXTRACTS = "knowledge/sources/rdso/extracts/rcc-box"
SCRATCH = "agent/out/rdso-extract"
CHECK_RANK = {"none": 0, "coverage_only": 1, "view_level": 2, "spot_check": 3, "second_pass": 4}
PAGE_KINDS = ("components", "parameters", "revisions", "notes_block", "tables", "reinforcement", "unclear", "not_read")
BAR_MARK = re.compile(r"^[a-h][0-9]?$|^g[0-9]$|^f[12]$")


def collect(col: Collector) -> None:
    root = col.root
    _register(col)
    manifest = _manifest(root)
    checked = _checked_notes(root)
    audit = _audit_counts(root)
    for doc_id in sorted(manifest):
        _extract_document(col, doc_id, manifest[doc_id], checked.get(doc_id, {}), audit.get(doc_id))
    _component_index_hazards(col)


def _manifest(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    path = root / SCRATCH / "_manifest.tsv"
    text = read_text(path) or ""
    for line in text.splitlines()[1:]:
        cells = line.split("\t")
        if len(cells) >= 4:
            out[cells[0]] = {"pages": int(cells[1]), "size_mb": cells[2], "file": cells[3]}
    return out


def _checked_notes(root: Path) -> dict[str, dict[str, Any]]:
    """Parse CHECKED_BY_HAND.txt: doc_id | status_override | picture | not checked | open points."""
    out: dict[str, dict[str, Any]] = {}
    text = read_text(root / "agent/out/file-status/CHECKED_BY_HAND.txt") or ""
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) != 5:
            continue
        doc_id, override, picture, not_checked, open_points = cells
        levels = _picture_levels(picture)
        out[doc_id] = {"override": override, "picture": picture, "not_checked": not_checked,
                       "open_points": open_points, "levels": levels}
    return out


def _picture_levels(picture: str) -> dict[int, str]:
    """Which pages were compared with the picture, and how strongly. Only explicit page numbers count."""
    levels: dict[int, str] = {}
    for clause in picture.split(";"):
        match = re.match(r"\s*p(\d+)(?:\s+to\s+p(\d+))?", clause)
        if not match:
            continue
        first = int(match.group(1))
        last = int(match.group(2) or first)
        lowered = clause.lower()
        if "second pass" in lowered:
            level = "second_pass"
        elif "spot check" in lowered:
            level = "spot_check"
        elif "general arrangement" in lowered or "view level" in lowered:
            level = "view_level"
        elif "coverage" in lowered:
            level = "coverage_only"
        else:
            continue
        for page in range(first, last + 1):
            if CHECK_RANK[level] > CHECK_RANK.get(levels.get(page, "none"), 0):
                levels[page] = level
    return levels


def _audit_counts(root: Path) -> dict[str, dict[str, Any]]:
    """The 2026-10-09 audit table: doc, pages, json count, validity. Used only to report conflicts."""
    out: dict[str, dict[str, Any]] = {}
    text = read_text(root / SCRATCH / "_STATUS_AUDIT.txt") or ""
    for line in text.splitlines():
        cells = line.split()
        if cells and cells[0].startswith("RDSO-RCC-BOX") and len(cells) >= 3 and cells[1].isdigit():
            out[cells[0]] = {"pages": int(cells[1]), "json": int(cells[2])}
    return out


def _register(col: Collector) -> None:
    """knowledge/sources/rdso/doc_map.jsonl: one row per downloaded or listed RDSO document."""
    root = col.root
    rows, problems = read_jsonl(root / "knowledge/sources/rdso/doc_map.jsonl")
    for problem in problems:
        col.issue("unreadable_index_line", "knowledge/sources/rdso/doc_map.jsonl", problem, severity="error",
                  affects=("retrieval",), detected_by="rdso.register")
    for row in sorted(rows, key=lambda r: r.get("doc_id", "")):
        doc_id = row.get("doc_id")
        if not doc_id:
            continue
        file_path = root / row["file"] if row.get("file") else None
        present = bool(file_path and file_path.is_file())
        record = make_source(
            root,
            record_id=f"rdso-doc:{doc_id}",
            kind="rdso_document",
            title=clip(row.get("title") or doc_id, 200) or doc_id,
            paths=[],
            category="B",
            family=(row.get("families") or [None])[0],
            existing_ids={"doc_id": doc_id, "file": row.get("file")},
            completeness={"pdf_present": present, "pages": row.get("pages"), "quality": row.get("quality"),
                          "no_text": row.get("no_text"), "read_by": row.get("read_by")},
            verification={"human_verified": False, "checked_against_picture": "none",
                          "title_read_by": row.get("read_by")},
            trust={"label_source": "vlm", "epistemic": "REFERENCE_OBSERVED", "doc_type": row.get("doc_type"),
                   "issuing_body": row.get("issuing_body")},
            eligibility=eligibility(
                retrieval_ok=present,
                retrieval_reason="document_register_entry",
                binding_blockers=[BINDING_NOT_A_VALUE],
                finetune_blockers=permission_blockers("unconfirmed") + ["no_human_label"],
            ),
            provenance={"file": row.get("file"), "source_url": row.get("source_url"),
                        "site_listing_text": clip(row.get("site_listing_text"), 200)},
            summary=clip(row.get("summary"), 300),
        )
        record["fingerprint"] = sha256_text(canonical_json(row))
        if not present:
            record["issues"].append(col.issue("missing_file", f"rdso-doc:{doc_id}",
                                              f"PDF not found at {row.get('file')}", severity="warning",
                                              affects=("retrieval",), detected_by="rdso.register"))
        col.add_source(record)


def _extract_document(col: Collector, doc_id: str, meta: dict[str, Any], note: dict[str, Any],
                      audit: dict[str, Any] | None) -> None:
    root = col.root
    folder = root / EXTRACTS / doc_id
    scratch = root / SCRATCH / doc_id
    pages = meta["pages"]
    levels: dict[int, str] = note.get("levels", {})
    saved: list[int] = []
    page_records: list[dict[str, Any]] = []
    for number in range(1, pages + 1):
        record, ok = _page(col, doc_id, number, folder, scratch, levels.get(number, "none"))
        page_records.append(record)
        if ok:
            saved.append(number)
    doc_md = (folder / "doc.md").is_file()
    doc_json = (folder / "doc.json").is_file()
    label = _status_label(note, pages, saved, doc_md, folder.is_dir() and any(folder.iterdir()))
    status_conflicts = _status_conflicts(col, doc_id, pages, saved, label, audit)
    evidence_dir_files = sum(1 for p in scratch.rglob("*") if p.is_file()) if scratch.is_dir() else 0
    record = make_source(
        root,
        record_id=f"rdso-extract:{doc_id}",
        kind="rdso_extract",
        title=clip(meta.get("file") or doc_id, 200) or doc_id,
        paths=sorted(p for p in folder.iterdir() if p.suffix in {".json", ".md"}) if folder.is_dir() else [],
        category="A",
        family="rcc_box",
        existing_ids={"doc_id": doc_id, "file": meta.get("file"), "evidence_folder": rel(root, scratch)},
        completeness={
            "pages_expected": pages,
            "pages_saved": len(saved),
            "pages_saved_list": saved,
            "doc_md": doc_md,
            "doc_json": doc_json,
            "evidence_files": evidence_dir_files,
            "status_label": label,
            "capability": _doc_capability(label, saved, pages),
        },
        verification={"human_verified": False, "checked_against_picture": _doc_checked(levels, pages),
                      "verified_values": "none", "not_checked_yet": note.get("not_checked")},
        trust={"label_source": "vlm", "epistemic": DRAWING_EPISTEMIC, "reading_method": "by eye, no OCR"},
        eligibility=eligibility(
            retrieval_ok=bool(saved),
            retrieval_reason="saved_pages_unverified",
            binding_blockers=[BINDING_NO_HUMAN, "page_values_not_verified"],
            finetune_blockers=permission_blockers("unconfirmed") + ["no_human_label"],
        ),
        provenance={"manifest": f"{SCRATCH}/_manifest.tsv", "picture_check_notes": note.get("picture")},
        summary=f"{len(saved)} of {pages} pages saved; {label}",
    )
    if note.get("open_points") and note["open_points"].lower() != "none recorded":
        record["issues"].append(col.issue("open_point", f"rdso-extract:{doc_id}", clip(note["open_points"], 400) or "",
                                          severity="warning", affects=("binding", "finetune"),
                                          detected_by="rdso.checked_notes"))
    if doc_id == "RDSO-RCC-BOX-10157-6TO-10157-10":
        ledger = scratch / "DISPLAYED_LEDGER.txt"
        if ledger.is_file():
            record["issues"].append(col.issue(
                "unverified_claim", f"rdso-extract:{doc_id}",
                "scratch ledgers in this folder say values were displayed; the status notes say page 1 values were never "
                "read from a displayed image. The ledger is not evidence for those values.",
                severity="error", affects=("retrieval", "binding", "finetune"),
                evidence=(rel(root, ledger),), detected_by="rdso.scratch_claims"))
    record["issues"].extend(status_conflicts)
    col.add_source(record)


def _status_label(note: dict[str, Any], pages: int, saved: list[int], doc_md: bool, started: bool) -> str:
    if note.get("override"):
        return note["override"]
    if len(saved) == pages and doc_md:
        return "All pages saved"
    if saved:
        return "Partly saved"
    return "Started, nothing saved" if started else "Not started"


def _doc_capability(label: str, saved: list[int], pages: int) -> str:
    if label == "All pages saved":
        return "all_pages_saved_not_verified"
    if saved:
        return f"partly_saved_{len(saved)}_of_{pages}"
    return "nothing_saved"


def _doc_checked(levels: dict[int, str], pages: int) -> str:
    if not levels:
        return "none"
    weakest = min(CHECK_RANK[levels.get(p, "none")] for p in range(1, pages + 1))
    return next(name for name, rank in CHECK_RANK.items() if rank == weakest)


def _status_conflicts(col: Collector, doc_id: str, pages: int, saved: list[int], label: str,
                      audit: dict[str, Any] | None) -> list[str]:
    issues: list[str] = []
    if audit is not None and audit["json"] != len(saved):
        issues.append(col.issue(
            "status_conflict", f"rdso-extract:{doc_id}",
            f"_STATUS_AUDIT.txt (2026-10-09 22:37) says {audit['json']} JSON pages; the disk has {len(saved)}. "
            "The disk count is used; the audit is out of date.",
            severity="warning", affects=("binding",), evidence=("agent/out/rdso-extract/_STATUS_AUDIT.txt",),
            detected_by="rdso.audit_compare"))
    return issues


def _page(col: Collector, doc_id: str, number: int, folder: Path, scratch: Path, checked_level: str) -> tuple[
        dict[str, Any], bool]:
    root = col.root
    rid = f"rdso:{doc_id}:p{number}"
    json_path = folder / f"p{number}.json"
    md_path = folder / f"p{number}.md"
    data: dict[str, Any] | None = None
    parse_error: str | None = None
    if json_path.is_file():
        try:
            data = read_json(json_path)
        except ValueError as exc:
            parse_error = str(exc)
    saved = data is not None and md_path.is_file()
    readable = md_path.is_file() and md_path.stat().st_size > 0
    missing_crops: list[str] = []
    crops_opened: list[str] = []
    if isinstance(data, dict):
        crops_opened = [c for c in data.get("crops_opened") or [] if isinstance(c, str)]
        missing_crops = [c for c in crops_opened if not (root / c).is_file()]
    record = make_source(
        root,
        record_id=rid,
        kind="rdso_page",
        title=f"{doc_id} page {number}",
        paths=[p for p in (json_path, md_path) if p.is_file()],
        category="A",
        family="rcc_box",
        owner=f"rdso-extract:{doc_id}",
        existing_ids={"doc_id": doc_id, "page": number},
        completeness={
            "saved": saved,
            "json_parses": data is not None and parse_error is None,
            "readable": readable,
            "page_kind": (data or {}).get("page_kind") if isinstance(data, dict) else None,
            "crops_opened": len(crops_opened),
            "crops_missing": len(missing_crops),
            "unclear": len((data or {}).get("unclear") or []) if isinstance(data, dict) else None,
            "not_read": len((data or {}).get("not_read") or []) if isinstance(data, dict) else None,
            "coverage_checked": (data or {}).get("coverage_checked") if isinstance(data, dict) else None,
        },
        verification={"human_verified": False, "checked_against_picture": checked_level, "verified_values": "none"},
        trust={"label_source": "vlm", "epistemic": DRAWING_EPISTEMIC},
        eligibility=eligibility(
            retrieval_ok=saved,
            retrieval_reason="saved_page_unverified" if saved else "page_not_saved",
            binding_blockers=[BINDING_NO_HUMAN, "page_values_not_verified"],
            finetune_blockers=permission_blockers("unconfirmed") + ["no_human_label"],
        ),
        provenance={"json": rel(root, json_path), "markdown": rel(root, md_path),
                    "evidence_folder": rel(root, scratch / f"p{number}") if (scratch / f"p{number}").is_dir() else None},
        summary=(clip((data or {}).get("title_printed") if isinstance(data, dict) else None, 200)
                 or f"{doc_id} page {number}"),
    )
    if parse_error:
        record["issues"].append(col.issue("unreadable_page", rid, parse_error, severity="error",
                                          affects=("retrieval", "binding", "finetune"), detected_by="rdso.page"))
    if missing_crops:
        record["issues"].append(col.issue(
            "missing_crop", rid, f"{len(missing_crops)} cited crop(s) not on disk: {', '.join(missing_crops[:4])}",
            severity="error", affects=("binding",), evidence=tuple(missing_crops[:10]), detected_by="rdso.page"))
    col.add_source(record)
    if isinstance(data, dict) and saved:
        _page_observations(col, rid, doc_id, data, record, checked_level)
    return record, saved


def _page_observations(col: Collector, rid: str, doc_id: str, data: dict[str, Any], source: dict[str, Any],
                       checked_level: str) -> None:
    family = "rcc_box"

    def add(local: str, obs_kind: str, raw: str | None, candidate: dict[str, Any] | None = None,
            fields: dict[str, Any] | None = None, binding: list[str] | None = None, retrieval_ok: bool = True) -> None:
        col.add_observation({
            "evidence_id": f"{rid}#{local}",
            "owner_id": rid,
            "owner_kind": "rdso_page",
            "local_id": local,
            "obs_kind": obs_kind,
            "category": "A",
            "family": family,
            "view": None,
            "raw_text": clip(raw, 500),
            "candidate_interpretation": candidate,
            "fields": fields or {},
            "geometry": None,
            "confidence": None,
            "source_id": source["id"],
            "source_fingerprint": source["fingerprint"],
            "trust": {"label_source": "vlm", "epistemic": DRAWING_EPISTEMIC, "human_verified": False,
                      "review_state": "not_verified", "flags": {"checked_level": checked_level}},
            "eligibility": eligibility(
                retrieval_ok=retrieval_ok and bool(raw or candidate),
                retrieval_reason="rdso_page_reading_unverified",
                binding_blockers=binding if binding is not None else [BINDING_NO_HUMAN, BINDING_NOT_A_VALUE],
                finetune_blockers=permission_blockers("unconfirmed") + ["no_human_label"],
            ),
        })

    for index, item in enumerate(data.get("components") or []):
        if isinstance(item, dict):
            add(f"component:{index}", "rdso_component", item.get("name_printed"),
                candidate={"what_it_is_as_drawn": item.get("what_it_is_as_drawn"),
                           "how_drawn": item.get("how_drawn"), "where": item.get("where")},
                fields={"values_printed": item.get("values_printed")})
    for index, item in enumerate(data.get("parameters") or []):
        if isinstance(item, dict):
            add(f"parameter:{index}", "rdso_parameter", item.get("name"),
                candidate={"value_printed": item.get("value_printed"), "where": item.get("where")},
                binding=[BINDING_NO_HUMAN, "value_text_only_unit_not_structured"])
    for index, item in enumerate(data.get("reinforcement") or []):
        if isinstance(item, dict):
            add(f"reinforcement:{index}", "rdso_reinforcement", item.get("mark"),
                candidate={"shape_or_description": item.get("shape_or_description"),
                           "formula_or_spacing_printed": item.get("formula_or_spacing_printed"),
                           "where": item.get("where")},
                binding=[BINDING_NO_HUMAN, BINDING_NOT_A_VALUE, "reinforcement_mark_not_a_dimension"])
    for index, item in enumerate(data.get("revisions") or []):
        if isinstance(item, dict):
            add(f"revision:{index}", "rdso_revision", item.get("text"),
                candidate={"mark": item.get("mark"), "date_printed": item.get("date_printed"),
                           "what_it_touches": item.get("what_it_touches")},
                binding=[BINDING_NO_HUMAN, BINDING_NOT_A_VALUE, "revision_status_unresolved"])
    for index, item in enumerate(data.get("notes_block") or []):
        if isinstance(item, dict):
            add(f"note:{index}", "rdso_note", item.get("text"), candidate={"no": item.get("no")},
                binding=[BINDING_NO_HUMAN, BINDING_NOT_A_VALUE])
    for index, item in enumerate(data.get("tables") or []):
        if isinstance(item, dict):
            rows = item.get("rows") or []
            add(f"table:{index}", "rdso_table", item.get("title_printed"),
                candidate={"columns": item.get("columns"), "row_count": len(rows)},
                fields={"rows": rows[:40], "rows_complete": item.get("rows_complete"), "notes": item.get("notes")},
                binding=[BINDING_NO_HUMAN, BINDING_NOT_A_VALUE]
                + (["rows_incomplete"] if item.get("rows_complete") is False else []))
    for index, text in enumerate(data.get("unclear") or []):
        add(f"unclear:{index}", "rdso_unclear", text if isinstance(text, str) else canonical_json(text),
            binding=["unclear_reading_not_bindable"])
    for index, text in enumerate(data.get("not_read") or []):
        add(f"not_read:{index}", "rdso_not_read", text if isinstance(text, str) else canonical_json(text),
            binding=["region_not_read"])


def _component_index_hazards(col: Collector) -> None:
    """The cross-PDF component index lists bar marks (a1, b, g1 ...) as components. Reported, not removed."""
    root = col.root
    text = read_text(root / SCRATCH / "_qa/COMPONENT_INDEX.md") or ""
    marks: list[str] = []
    for line in text.splitlines():
        cells = [c.strip().strip("`") for c in line.split("|")]
        if len(cells) > 2 and BAR_MARK.match(cells[1] or ""):
            marks.append(cells[1])
    if marks:
        col.issue(
            "reinforcement_marks_in_component_index", "agent/out/rdso-extract/_qa/COMPONENT_INDEX.md",
            f"{len(marks)} rows of the component index are reinforcement bar marks ({', '.join(sorted(set(marks))[:8])}). "
            "They are not components; use reinforcement entries instead.",
            severity="warning", affects=("binding",), evidence=("agent/out/rdso-extract/_qa/COMPONENT_INDEX.md",),
            detected_by="rdso.component_index",
        )
    no_index = ["RDSO-RCC-BOX-10161-10161-1", "RDSO-RCC-BOX-10166-10166-1", "RDSO-RCC-BOX-RDSO-B-10155-6-TO-10155-10"]
    col.issue("component_index_missing", "rdso-extract/component-index",
              "no component index for: " + ", ".join(no_index), severity="info", affects=("binding",),
              detected_by="rdso.component_index")
