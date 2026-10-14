"""Adapter: the separate vector-PDF set (vector-pdfs/) -> sheet records and text-layer observations.

This corpus has its own index and its own ids (v-<hex>-p<page>, vbr-<hex>). It is never merged into bridges/.
The PDF's own text layer is observed text (no OCR). Paths and geometry are counted, not copied.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..common import canonical_json, clip, read_json, read_jsonl, rel, sha256_text
from ..model import Collector, make_source
from ..policy import (
    BINDING_NO_HUMAN,
    BINDING_NOT_A_VALUE,
    DRAWING_EPISTEMIC,
    eligibility,
    permission_blockers,
)

LABEL = "observed_vector"


def collect(col: Collector) -> None:
    root = col.root
    base = root / "vector-pdfs"
    if not base.is_dir():
        col.issue("missing_corpus", "vector-pdfs", "the vector-pdfs/ folder is missing", severity="error",
                  affects=("retrieval", "binding", "finetune"), detected_by="vector.collect")
        return
    sheets, problems = read_jsonl(base / "_index/sheets.jsonl")
    for problem in problems:
        col.issue("unreadable_index_line", "vector-pdfs/_index/sheets.jsonl", problem, severity="error",
                  affects=("retrieval",), detected_by="vector.collect")
    review_rows, _ = read_jsonl(base / "_index/review_queue.jsonl")
    open_review: dict[str, list[dict[str, Any]]] = {}
    for item in review_rows:
        if item.get("status") == "open":
            open_review.setdefault(item.get("record_id", ""), []).append(item)
    for sheet in sorted(sheets, key=lambda row: row["record_id"]):
        _sheet(col, sheet, open_review.get(sheet["record_id"], []))


def _sheet(col: Collector, s: dict[str, Any], open_items: list[dict[str, Any]]) -> None:
    root = col.root
    rid = s["record_id"]
    sheet_dir = root / s["sheet_path"] if s.get("sheet_path") else None
    sheet_json_path = sheet_dir / "sheet.json" if sheet_dir else None
    detail = read_json(sheet_json_path) if sheet_json_path and sheet_json_path.is_file() else None
    vector_dir = sheet_dir / "vector" if sheet_dir else None
    text_path = vector_dir / "text.jsonl" if vector_dir else None
    meta_path = vector_dir / "meta.json" if vector_dir else None
    paths = [p for p in (sheet_json_path, meta_path, text_path) if p is not None]
    text_rows, text_problems = _spans(text_path) if text_path else ([], [])
    for problem in text_problems:
        col.issue("unreadable_index_line", rel(root, text_path), problem, severity="error",
                  affects=("retrieval",), detected_by="vector.text")

    classification = (detail or {}).get("classification") or {}
    completeness = {
        "pdf_kind": s.get("pdf_kind"),
        "text_spans": len(text_rows),
        "path_objects": s.get("path_objects"),
        "placed": bool((detail or {}).get("placed")),
        "sheet_json_present": sheet_json_path is not None and sheet_json_path.is_file(),
        "text_layer_present": text_path is not None and text_path.is_file(),
        "semantic_grounding": "none",
        "capability": "vector_text_observed_ungrounded" if text_rows else "vector_without_text_layer",
    }
    record = make_source(
        root,
        record_id=rid,
        kind="vector_sheet",
        title=clip(s.get("original_name") or rid, 200) or rid,
        paths=paths,
        category="A",
        family=s.get("family"),
        bridge_ids=[s["bridge_id"]] if s.get("bridge_id") else [],
        existing_ids={"record_id": rid, "bridge_id": s.get("bridge_id"), "sha256": s.get("sha256"),
                      "corpus": "vector-pdfs"},
        completeness=completeness,
        verification={"human_verified": False, "checked_against_picture": "none", "split": None},
        trust={"label_source": LABEL, "epistemic": DRAWING_EPISTEMIC,
               "classification_source": classification.get("source"),
               "proposed_type_printed": classification.get("proposed_type_printed")},
        eligibility=eligibility(
            retrieval_ok=bool(text_rows),
            retrieval_reason="vector_text_layer_unverified",
            binding_blockers=[BINDING_NOT_A_VALUE],
            finetune_blockers=permission_blockers((detail or {}).get("permission_to_train") or "unconfirmed")
            + ["no_human_label"],
        ),
        provenance={
            "raw_path": (detail or {}).get("raw_path") or s.get("raw_path"),
            "sheet_path": s.get("sheet_path"),
            "split_note": (detail or {}).get("split_note"),
            "source": (detail or {}).get("source"),
        },
        summary=f"{s.get('family')} vector sheet, {len(text_rows)} text spans, {s.get('path_objects')} path objects",
    )
    record["fingerprint"] = sha256_text(canonical_json(s) + "|" + record["fingerprint"])
    issues = record["issues"]
    for review in (detail or {}).get("review") or []:
        issues.append(col.issue("title_conflicts_with_content", rid, clip(str(review), 300) or "review note",
                                severity="warning", affects=("binding", "finetune"), detected_by="vector.review"))
    for item in open_items:
        issues.append(col.issue("open_review_question", rid, clip(item.get("question"), 300) or "open question",
                                severity="warning", affects=("binding",), detected_by="vector.review_queue"))
    if sheet_json_path is not None and not sheet_json_path.is_file():
        issues.append(col.issue("missing_file", rid, "sheet.json not found", severity="error",
                                affects=("retrieval", "binding", "finetune"), detected_by="vector.sheet"))
    col.add_source(record)
    for span in text_rows:
        _span_observation(col, rid, span, s, record)


def _spans(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    return read_jsonl(path)


def _span_observation(col: Collector, rid: str, span: dict[str, Any], s: dict[str, Any],
                      source: dict[str, Any]) -> None:
    text = span.get("text")
    x, y = span.get("x"), span.get("y")
    w, h = span.get("w"), span.get("h")
    geometry = None
    if None not in (x, y, w, h):
        geometry = {"space": "page_pt", "box": [x, y, x + w, y + h]}
    local = span.get("id") or f"span{span.get('page')}"
    col.add_observation({
        "evidence_id": f"{rid}#{local}",
        "owner_id": rid,
        "owner_kind": "vector_sheet",
        "local_id": local,
        "obs_kind": "vector_text",
        "category": "A",
        "family": s.get("family"),
        "view": None,
        "raw_text": text,
        "candidate_interpretation": None,
        "fields": {"font": span.get("font"), "size": span.get("size"), "color": span.get("color"),
                   "rotation": span.get("rotation"), "page": span.get("page")},
        "geometry": geometry,
        "confidence": None,
        "source_id": source["id"],
        "source_fingerprint": source["fingerprint"],
        "trust": {"label_source": LABEL, "epistemic": DRAWING_EPISTEMIC, "human_verified": False,
                  "review_state": "unreviewed", "flags": {}},
        "eligibility": eligibility(
            retrieval_ok=bool(text and str(text).strip()),
            retrieval_reason="vector_text_layer_unverified" if text and str(text).strip() else "no_text",
            binding_blockers=[BINDING_NO_HUMAN, BINDING_NOT_A_VALUE],
            finetune_blockers=permission_blockers("unconfirmed") + ["no_human_label"],
        ),
    })
