"""Synthetic repository for UNIT TESTS ONLY. Never used as data, never shipped as a dataset.

It builds a tiny repository in a temporary folder with: one grounded sheet (with an ambiguous dimension, a disputed
dimension and an arithmetic check that fails), one partly grounded sheet, one ungrounded sheet, a KB with unreviewed
entries, a DISPUTED conflict, a proposal, an unresolved citation, an RDSO extract page that cites a missing crop, a
status document that claims a folder that no longer exists, and a vector sheet.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

REAL_SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
SHEET_GROUNDED = "aaaaaaaaaaaa-p1"
SHEET_PARTIAL = "bbbbbbbbbbbb-p1"
SHEET_UNGROUNDED = "cccccccccccc-p1"
BRIDGE = "brg-0123456789"
DOC = "RDSO-SYNTHETIC-DOC"
VECTOR = "v-dddddddddddd-p1"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _jsonl(path: Path, rows: list[dict]) -> None:
    _write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def _grounding(partial: bool) -> dict:
    dims = [
        {"id": "D1", "text": "T1", "view": "V1", "value": 0.72, "unit": "m", "measures_from": "rail level",
         "measures_to": "top of slab", "sets": "depth", "mode": "single", "orientation": "vertical",
         "confidence": "high"},
        {"id": "D2", "text": "T2", "view": "V1", "value": 3.5, "unit": None, "measures_from": "a", "measures_to": "b",
         "sets": "width", "mode": "single", "orientation": "horizontal", "confidence": "low",
         "doubt": "unit not printed"},
    ]
    checks = [
        {"what": "level chain", "numbers": "1+2=3", "result": 3, "expected": 3, "tolerance": 0.001, "passed": True},
        {"what": "span sum", "numbers": "4+4=9", "result": 8, "expected": 9, "tolerance": 0.001, "passed": False},
    ]
    if partial:
        dims = []
        checks = []
    return {
        "meta": {"schema_version": "grounding-0.3", "agent": "synthetic"},
        "sheet": {"scope": "full_gad"},
        "bridge": {"family": "rcc_box"},
        "views": [{"id": "V1", "type": "plan", "title_raw": "PLAN", "box": [10, 10, 200, 200]}],
        "texts": [
            {"id": "T1", "view": "V1", "raw": "0.72", "kind": "dimension", "box": [20, 20, 40, 30],
             "confidence": "high", "value": 0.72, "unit": "m"},
            {"id": "T2", "view": "V1", "raw": "3500", "kind": "dimension", "box": [50, 50, 80, 60],
             "confidence": "low", "value": 3500, "unit": None, "doubt": "smudged"},
            {"id": "T3", "view": "V1", "raw": "OLD 0.60", "kind": "level", "box": [90, 90, 120, 100],
             "confidence": "medium", "superseded_by": "T1"},
        ],
        "levels": [{"id": "L1", "text": "T1", "datum": "rail", "value_m": 100.0, "for": "track", "status": "PROPOSED",
                    "confidence": "high"}] if not partial else [],
        "parts": [{"id": "P1", "class": "box_barrel", "label": "BOX", "status": "PROPOSED",
                   "status_evidence": "title", "appears_in": ["V1"], "confidence": "high"}],
        "repeats": [],
        "dimensions": dims,
        "relations": [{"type": "part_of", "from": "P1", "to": "P1", "evidence": "self", "confidence": "low"}],
        "parameters": [{"name": "clear_width", "value": 4.0, "unit": "m", "source": "written", "from": ["T1"],
                        "confidence": "high"}] if not partial else [],
        "checks": checks,
        "disputes": [{"what": "clear height", "value_a": "3.60 m", "evidence_a": "printed",
                      "value_b": "4.0 m", "evidence_b": "handwritten"}] if not partial else [],
        "absent": [{"class": "weep_hole", "view": "V1", "why": "note requires them; none drawn"}],
        "doubts": [{"about": "status of black ink", "issue": "conflicting notes"}],
        "tables": [],
    }


def make_repository(tmp: Path) -> Path:
    root = tmp / "repo"
    (root / "agent-context").mkdir(parents=True)
    _write(root / "ROOT_MARKER", "synthetic\n")
    shutil.copytree(REAL_SCHEMAS, root / "agent-context" / "schemas")

    sheets, catalog, bridges = [], [], []
    specs = [
        (SHEET_GROUNDED, "rcc_box", True, "needs_review", _grounding(False)),
        (SHEET_PARTIAL, "rcc_box", True, "needs_review", _grounding(True)),
        (SHEET_UNGROUNDED, "rcc_slab", True, None, None),
    ]
    for rid, family, permitted, status, grounding in specs:
        sha = (rid.replace("-", "") + "0" * 64)[:64]
        folder = root / "bridges" / family / BRIDGE / "sheets" / rid
        raw = root / "bridges" / family / BRIDGE / "raw" / f"{sha}.tif"
        _write(raw, "raw drawing bytes\n")
        view = folder / "view.jpg"
        _write(view, "picture\n")
        grounding_rel = None
        if grounding is not None:
            gpath = folder / "grounding" / "agent-grounding.json"
            _write(gpath, json.dumps(grounding, ensure_ascii=False, indent=1))
            _write(folder / "grounding" / "checks.md", "checks\n")
            grounding_rel = gpath.relative_to(root).as_posix()
            _write(root / "agent" / "state" / "done" / f"{rid}.json",
                   json.dumps({"record_id": rid, "status": status}))
        sheets.append({
            "record_id": rid, "kind": "raster", "source_file": f"{rid}.tif", "sha256": sha, "page": 1,
            "page_count": 1, "sheet_role": "gad_main", "family": family, "structure_type": "phys.structure.x",
            "box_kind": "culvert", "cells": "single", "skew_deg": None, "whole_or_extension": "whole",
            "scale_printed": None, "drawing_no": "SYN/1", "authority_printed": None, "legibility": "fair",
            "permission_to_train": "yes" if permitted else "unconfirmed", "permission_basis": "synthetic",
            "classification_ref": f"catalog/classification/?#{rid}", "confidence": "high", "second_look": False,
            "notes": "", "bridge_ids": [BRIDGE], "bridge_family": family,
            "sheet_dir": folder.relative_to(root).as_posix(),
            "raw_path": raw.relative_to(root).as_posix(), "view_path": view.relative_to(root).as_posix(),
            "grounding_path": grounding_rel, "vector_paths": None,
        })
        catalog.append({"record_id": rid, "family": family, "classification": {"family": family},
                        "grounding": {"state": status or "none"}})
    bridges.append({"bridge_id": BRIDGE, "identity_quality": "full", "identity_string": "synthetic|bridge",
                    "family": "rcc_box", "sheet_ids": [s["record_id"] for s in sheets],
                    "raster_sheet_ids": [s["record_id"] for s in sheets], "vector_sheet_ids": [],
                    "permission_to_train": "unconfirmed", "needs_review": True, "aliases": [],
                    "identity_basis": "title_read", "kb_family_id": "kb.family.rcc_box",
                    "structure_text": "synthetic box"})
    _jsonl(root / "bridges/_index/sheets.jsonl", sheets)
    _jsonl(root / "bridges/_index/bridges.jsonl", bridges)
    _jsonl(root / "catalog/gad_catalog.jsonl", catalog)

    _write(root / "knowledge/kb/topics.json", json.dumps({"topics": [
        {"id": "component"}, {"id": "formula"}, {"id": "conflict"}, {"id": "rule"}, {"id": "standard_drawing"},
        {"id": "teaching"}]}))
    _jsonl(root / "knowledge/kb/entries/component.jsonl", [
        {"id": "kb.component.box_barrel", "topic": "component", "names": {"canonical": "Box barrel", "aliases": []},
         "evidence_status": "COMMON_PRACTICE", "review_state": "seed_unreviewed",
         "merged_from": [{"origin": "knowledge/missing_source.md", "id": "box barrel"}],
         "kind": "component", "use": {"grounding": True, "qa_training": False, "retrieval": True, "validator": False},
         "grounding": {"class": "box_barrel"}, "definition": "The barrel of a box culvert.", "teaching": {
             "what": "the box", "on_sheet": "a rectangle in section"}},
    ])
    _jsonl(root / "knowledge/kb/entries/formula.jsonl", [
        {"id": "kb.formula.synthetic_sum", "topic": "formula", "names": {"canonical": "SYN-SUM", "aliases": []},
         "evidence_status": "NORMATIVE", "review_state": "seed_unreviewed",
         "merged_from": [{"origin": "aagento-bridge/knowledge/formulas.json", "id": "SYN-SUM"}],
         "kind": "definition", "use": {"qa_training": True},
         "definition": "total = a + b", "payload": {"expression": "a + b", "applies": {"families": ["rcc_box"]}}},
    ])
    _jsonl(root / "knowledge/kb/entries/conflict.jsonl", [
        {"id": "kb.conflict.kc_synth", "topic": "conflict", "names": {"canonical": "KC-SYN", "aliases": []},
         "evidence_status": "DISPUTED", "review_state": "seed_unreviewed",
         "merged_from": [{"origin": "knowledge/SHEET_SCOPES.md", "id": "KC-SYN"}], "kind": "conflict",
         "definition": "two sources disagree"},
    ])
    _jsonl(root / "knowledge/kb/proposals/synthetic/proposal.jsonl", [
        {"id": "kb.component.box_barrel", "topic": "component", "names": {"canonical": "Box barrel"},
         "evidence_status": "REFERENCE_OBSERVED", "review_state": "proposed",
         "definition": "proposed wording"},
    ])
    _write(root / "knowledge/kb/proposals/synthetic/_read_log.md", "# Synthetic read log\n")
    _write(root / "ontology/component-types.json", json.dumps({
        "classes": [{"id": "phys.component.box_barrel", "canonical_name": "Box barrel", "definition": "barrel"}]}))
    _write(root / "REPORT.md", "# Report\n\nTop-level folders now: _archive, bridges.\n")

    rdso_root = root / "knowledge/sources/rdso/extracts/rcc-box" / DOC
    _write(root / "agent/out/rdso-extract/_manifest.tsv", f"doc_id\tpages\tsize_mb\tfile\n{DOC}\t2\t1.0\tsynthetic.pdf\n")
    page1 = {"doc_id": DOC, "file": "synthetic.pdf", "page": 1, "pages_in_file": 2, "title_printed": "PAGE ONE",
             "components": [{"name_printed": "box barrel", "what_it_is_as_drawn": "a box", "how_drawn": "section",
                             "where": ["V1"], "values_printed": []}],
             "parameters": [{"name": "fill height", "value_printed": "4.0 m", "where": "title"}],
             "tables": [], "notes_block": [], "notations": [], "reinforcement": [], "revisions": [],
             "unclear": ["digit under the stamp, two readings: 3 or 8"], "not_read": ["title block strip"],
             "crops_opened": [f"agent/out/rdso-extract/{DOC}/p1/crops/missing.png"], "coverage_checked": True,
             "page_kind": "general arrangement", "views": [], "refers_to": [], "language_notes": None,
             "drawing_no_printed": None, "date_printed": None, "loading_printed": None, "description": "d"}
    _write(rdso_root / "p1.json", json.dumps(page1))
    _write(rdso_root / "p1.md", "# page 1\n")
    _write(rdso_root / "doc.md", "# doc\n")
    _write(rdso_root / "doc.json", json.dumps({"doc_id": DOC}))
    # page 2 is not saved (no json, no md)
    _write(root / "agent/out/file-status/CHECKED_BY_HAND.txt",
           f"{DOC} | | p1 general arrangement (view level) | p2 not saved | page 1 values were never read from a displayed image\n")

    vec_folder = root / "vector-pdfs/rcc_box/vbr-eeeeeeeeee/sheets" / VECTOR
    _write(vec_folder / "sheet.json", json.dumps({"record_id": VECTOR, "bridge_id": "vbr-eeeeeeeeee",
                                                   "family": "rcc_box", "classification": {"source": "title"},
                                                   "permission_to_train": "unconfirmed", "review": [],
                                                   "placed": True, "split": None}))
    _write(vec_folder / "vector/meta.json", "{}")
    _jsonl(vec_folder / "vector/text.jsonl", [
        {"id": "T1", "page": 1, "text": "SECTION A-A", "x": 10.0, "y": 20.0, "w": 50.0, "h": 5.0, "font": "Arial",
         "size": 5.0, "color": [0, 0, 0], "rotation": 0.0},
        {"id": "T2", "page": 1, "text": "   ", "x": 1.0, "y": 1.0, "w": 1.0, "h": 1.0},
    ])
    _jsonl(root / "vector-pdfs/_index/sheets.jsonl", [{
        "record_id": VECTOR, "bridge_id": "vbr-eeeeeeeeee", "family": "rcc_box", "kind": "vector",
        "pdf_kind": "vector_text", "sha256": "d" * 64, "original_name": "synthetic.pdf", "size": 1,
        "path_objects": 3, "sheet_path": vec_folder.relative_to(root).as_posix()}])
    _jsonl(root / "vector-pdfs/_index/review_queue.jsonl", [])
    return root


def context_of(root: Path) -> Path:
    return root / "agent-context"
