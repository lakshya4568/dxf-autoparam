"""Adapter: the main dataset (bridges/, catalog/, agent/state/) -> sheet, bridge, grounding and observation records.

Reads only. Identifiers are the repository's own: record_id (<sha12>-p<page>) and bridge_id (brg-<hex>).
Incomplete input stays incomplete: an ungrounded sheet gets a source record and no observations.
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
    DRAWING_LABEL,
    eligibility,
    permission_blockers,
)

GROUNDING_SECTIONS = (
    "views", "texts", "levels", "parts", "repeats", "dimensions", "relations",
    "parameters", "checks", "disputes", "absent", "doubts", "tables",
)

# Dataset family folder <-> grounding family word. Used only to REPORT differences, never to rewrite them.
FAMILY_WORDS_OK = {
    ("rcc_box", "rub"), ("rcc_box", "rcc_box"), ("rcc_slab", "slab"), ("rcc_slab", "rcc_slab"),
    ("rub_other", "rub"), ("other", "special"), ("pipe", "pipe"), ("girder", "girder"),
    ("arch", "arch"), ("rob", "rob"),
}


def collect(col: Collector) -> None:
    root = col.root
    sheets, problems = read_jsonl(root / "bridges/_index/sheets.jsonl")
    for problem in problems:
        col.issue("unreadable_index_line", "bridges-index/sheets.jsonl", problem, severity="error",
                  affects=("retrieval", "binding", "finetune"), detected_by="drawings.collect")
    catalog_rows, _ = read_jsonl(root / "catalog/gad_catalog.jsonl")
    catalog = {row["record_id"]: row for row in catalog_rows if row.get("record_id")}
    screens = _box_screens(root)
    done = _done_status(root)
    bridges, bridge_problems = read_jsonl(root / "bridges/_index/bridges.jsonl")
    for problem in bridge_problems:
        col.issue("unreadable_index_line", "bridges-index/bridges.jsonl", problem, severity="error",
                  affects=("retrieval",), detected_by="drawings.collect")

    ordered = sorted(sheets, key=lambda row: row["record_id"])
    _aggregate_corpus_issues(col, ordered, catalog)
    for sheet in ordered:
        _sheet(col, sheet, catalog.get(sheet["record_id"]), screens.get(sheet["record_id"]), done.get(sheet["record_id"]))
    for sheet in ordered:
        grounding_file = _grounding_file(root, sheet)
        if grounding_file is not None:
            _grounding(col, sheet, grounding_file, catalog.get(sheet["record_id"]))
    for bridge in sorted(bridges, key=lambda row: row["bridge_id"]):
        _bridge(col, bridge)


def _box_screens(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    folder = root / "catalog/box_screen"
    if folder.is_dir():
        for path in sorted(folder.glob("*.jsonl")):
            for row in read_jsonl(path)[0]:
                if row.get("record_id"):
                    out[row["record_id"]] = row
    return out


def _done_status(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    folder = root / "agent/state/done"
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            value = read_json(path)
            if isinstance(value, dict):
                out[path.stem] = value
    return out


def _grounding_file(root: Path, sheet: dict[str, Any]) -> Path | None:
    path = root / sheet["grounding_path"] if sheet.get("grounding_path") else None
    return path if path is not None and path.is_file() else None


def _aggregate_corpus_issues(col: Collector, sheets: list[dict[str, Any]], catalog: dict[str, dict[str, Any]]) -> None:
    placeholders = [s["record_id"] for s in sheets if "?" in (s.get("classification_ref") or "")]
    if placeholders:
        col.issue(
            "placeholder_reference", "bridges-index/sheets.classification_ref",
            f"{len(placeholders)} sheets carry a placeholder classification_ref ('catalog/classification/?#...'). "
            "The classification itself is found in catalog/gad_catalog.jsonl; the pointer is not resolvable.",
            severity="info", evidence=tuple(placeholders[:5]), detected_by="drawings.aggregate",
        )
    unsorted = [s["record_id"] for s in sheets if s.get("family") == "_unsorted"]
    if unsorted:
        col.issue(
            "not_placed_by_family", "bridges/_unsorted",
            f"{len(unsorted)} sheets are not yet placed in a family folder. Their family is known only from "
            "catalog/gad_catalog.jsonl (classification or box screen).",
            severity="info", evidence=tuple(unsorted[:5]), detected_by="drawings.aggregate",
        )
    missing_catalog = [s["record_id"] for s in sheets if s["record_id"] not in catalog]
    if missing_catalog:
        col.issue(
            "missing_catalog_row", "catalog/gad_catalog.jsonl",
            f"{len(missing_catalog)} sheets have no row in the catalog.", severity="warning",
            evidence=tuple(missing_catalog[:5]), detected_by="drawings.aggregate",
        )


def _sheet(col: Collector, s: dict[str, Any], cat: dict[str, Any] | None, screen: dict[str, Any] | None,
           done: dict[str, Any] | None) -> None:
    root = col.root
    rid = s["record_id"]
    raw_ok = bool(s.get("raw_path")) and (root / s["raw_path"]).is_file()
    picture_ok = bool(s.get("view_path")) and (root / s["view_path"]).is_file()
    grounding_ok = _grounding_file(root, s) is not None
    status = (done or {}).get("status")
    classification = "none"
    if cat and cat.get("classification"):
        classification = "filed_in_catalog"
    if "?" in (s.get("classification_ref") or ""):
        classification = classification + "+placeholder_reference" if classification != "none" else "placeholder_reference"
    if grounding_ok and status == "needs_review":
        capability = "grounded_needs_review"
    elif grounding_ok:
        capability = "grounded"
    elif not raw_ok:
        capability = "source_missing"
    elif picture_ok:
        capability = "picture_only_ungrounded"
    else:
        capability = "identity_only"
    completeness = {
        "raw_file_present": raw_ok,
        "picture_present": picture_ok,
        "grounding": "filed" if grounding_ok else "none",
        "grounding_status": status,
        "classification": classification,
        "box_screen": "filed" if screen else "none",
        "placed_by_family": s.get("family") != "_unsorted",
        "capability": capability,
    }
    family = s.get("family")
    issues: list[str] = []
    fp = sha256_text(canonical_json(s))
    record = make_source(
        root,
        record_id=rid,
        kind="drawing_sheet",
        title=clip(s.get("drawing_no") or s.get("source_file") or rid, 200) or rid,
        paths=[root / s["grounding_path"]] if grounding_ok else [],
        category="A",
        family=family,
        bridge_ids=s.get("bridge_ids") or [],
        existing_ids={
            "record_id": rid,
            "sha256": s.get("sha256"),
            "bridge_ids": s.get("bridge_ids") or [],
            "catalog_family": (cat or {}).get("family"),
            "classification_ref": s.get("classification_ref"),
            "source_file": s.get("source_file"),
        },
        completeness=completeness,
        verification={"human_verified": False, "checked_against_picture": "none", "review_state": status or "not_grounded"},
        trust={"label_source": DRAWING_LABEL, "epistemic": DRAWING_EPISTEMIC, "identity_basis": "title block read by eye"},
        eligibility=eligibility(
            retrieval_ok=picture_ok or raw_ok,
            retrieval_reason="identity_and_picture" if picture_ok else "identity_only",
            binding_blockers=[BINDING_NOT_A_VALUE],
            finetune_blockers=permission_blockers(s.get("permission_to_train")) + ["no_human_label"],
        ),
        provenance={
            "raw_path": s.get("raw_path"),
            "view_path": s.get("view_path"),
            "sheet_dir": s.get("sheet_dir"),
            "grounding_path": s.get("grounding_path"),
            "catalog_row": "catalog/gad_catalog.jsonl" if cat else None,
            "permission_basis": s.get("permission_basis"),
        },
        summary=f"{family} sheet {rid}; capability {capability}",
    )
    record["fingerprint"] = sha256_text(fp + record["fingerprint"])
    if not raw_ok:
        issues.append(col.issue("missing_file", rid, f"raw drawing not found at {s.get('raw_path')}",
                                severity="error", affects=("retrieval", "binding", "finetune"),
                                evidence=(s.get("raw_path") or "",), detected_by="drawings.sheet"))
    if not picture_ok:
        issues.append(col.issue("missing_file", rid + ":picture",
                                f"viewing picture not found at {s.get('view_path')}",
                                severity="warning", affects=("retrieval",), detected_by="drawings.sheet"))
    if status == "needs_review":
        issues.append(col.issue("needs_review", rid, "grounding filed but marked needs_review in agent/state/done",
                                severity="warning", affects=("binding", "finetune"), detected_by="drawings.sheet"))
    record["issues"] = issues
    col.add_source(record)


def _bridge(col: Collector, b: dict[str, Any]) -> None:
    root = col.root
    bid = b["bridge_id"]
    sheets = b.get("sheet_ids") or []
    completeness = {
        "sheets": len(sheets),
        "raster_sheets": len(b.get("raster_sheet_ids") or []),
        "vector_sheets": len(b.get("vector_sheet_ids") or []),
        "identity_quality": b.get("identity_quality"),
        "identity_basis": b.get("identity_basis"),
        "needs_review": bool(b.get("needs_review")),
    }
    record = make_source(
        root,
        record_id=f"bridge:{bid}",
        kind="bridge",
        title=clip(b.get("identity_string") or bid, 200) or bid,
        paths=[root / "bridges/_index/bridges.jsonl"],
        category="A",
        family=b.get("family"),
        owner=None,
        bridge_ids=[bid],
        existing_ids={"bridge_id": bid, "sheet_ids": sheets, "kb_family_id": b.get("kb_family_id")},
        completeness=completeness,
        verification={"human_verified": False, "checked_against_picture": "none"},
        trust={"label_source": DRAWING_LABEL, "epistemic": DRAWING_EPISTEMIC},
        eligibility=eligibility(
            retrieval_ok=bool(sheets),
            retrieval_reason="identity_index_entry",
            binding_blockers=[BINDING_NOT_A_VALUE],
            finetune_blockers=permission_blockers(b.get("permission_to_train")) + ["no_human_label"],
        ),
        provenance={"structure_text": clip(b.get("structure_text"), 300), "aliases": b.get("aliases") or []},
        summary=f"{b.get('family')} bridge {bid}, {len(sheets)} sheet(s)",
    )
    if b.get("needs_review"):
        record["issues"].append(col.issue("needs_review", f"bridge:{bid}", "bridge identity flagged needs_review",
                                          severity="warning", affects=("binding",), detected_by="drawings.bridge"))
    col.add_source(record)


def _grounding(col: Collector, s: dict[str, Any], grounding_file: Path, cat: dict[str, Any] | None) -> None:
    root = col.root
    rid = s["record_id"]
    data = read_json(grounding_file)
    if not isinstance(data, dict):
        col.issue("unreadable_grounding", rid, f"{rel(root, grounding_file)} is not a JSON object",
                  severity="error", affects=("retrieval", "binding", "finetune"), detected_by="drawings.grounding")
        return
    done = _done_status(root).get(rid, {})
    status = done.get("status", "unknown")
    folder = grounding_file.parent
    all_files = sorted(p for p in folder.rglob("*") if p.is_file())
    counts = {sec: len(data.get(sec) or []) for sec in GROUNDING_SECTIONS}
    empty = [sec for sec in GROUNDING_SECTIONS if counts[sec] == 0]
    checks = [c for c in data.get("checks") or [] if isinstance(c, dict)]
    failed = [c for c in checks if c.get("passed") is False]
    failed_hard = [c for c in failed if c.get("informational") is not True]
    failed_info = [c for c in failed if c.get("informational") is True]
    dims = [d for d in data.get("dimensions") or [] if isinstance(d, dict)]
    completeness = {
        "sections": counts,
        "sections_empty": empty,
        "dimensions_with_value": sum(1 for d in dims if d.get("value") is not None),
        "dimensions_with_unit": sum(1 for d in dims if d.get("unit")),
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "disputes": counts["disputes"],
        "doubts": counts["doubts"],
        "absent_components": counts["absent"],
        "capability": "grounded_needs_review" if status == "needs_review" else "grounded",
        "scope": (data.get("sheet") or {}).get("scope"),
    }
    grounding_family = (data.get("bridge") or {}).get("family")
    sheet_family = s.get("family")
    record = make_source(
        root,
        record_id=f"grounding:{rid}",
        kind="grounding",
        title=f"grounding of {rid}",
        paths=all_files,
        category="A",
        family=sheet_family,
        owner=rid,
        bridge_ids=s.get("bridge_ids") or [],
        existing_ids={"record_id": rid, "grounding_schema": (data.get("meta") or {}).get("schema_version")},
        completeness=completeness,
        verification={"human_verified": False, "checked_against_picture": "none",
                      "arithmetic_checks": f"{len(checks) - len(failed)} of {len(checks)} passed in code"},
        trust={"label_source": DRAWING_LABEL, "epistemic": DRAWING_EPISTEMIC, "review_state": status,
               "grounding_worker": (data.get("meta") or {}).get("agent")},
        eligibility=eligibility(
            retrieval_ok=any(counts[sec] for sec in ("texts", "parts", "views")),
            retrieval_reason="grounded_unverified",
            binding_blockers=[BINDING_NO_HUMAN],
            finetune_blockers=permission_blockers(s.get("permission_to_train")) + ["no_human_label"],
        ),
        provenance={"grounding_path": rel(root, grounding_file), "reasons": done.get("reasons", [])},
        summary=f"{len(checks)} checks ({len(failed)} failed), {counts['dimensions']} dimensions, {counts['disputes']} disputes",
    )
    issues = record["issues"]
    if failed_hard:
        issues.append(col.issue("failed_check", rid,
                                f"{len(failed_hard)} arithmetic check(s) disagree with the written numbers "
                                "(recorded by the grounding; not resolved)",
                                severity="warning", affects=("binding", "finetune"), detected_by="drawings.grounding"))
    if failed_info:
        issues.append(col.issue("informational_check_failed", rid,
                                f"{len(failed_info)} check(s) marked informational (smudged or low-confidence reads)",
                                severity="info", affects=("binding",), detected_by="drawings.grounding"))
    if counts["disputes"]:
        issues.append(col.issue("unresolved_disputes", rid,
                                f"{counts['disputes']} written-versus-drawn or revision disputes are open in the grounding",
                                severity="warning", affects=("binding", "finetune"), detected_by="drawings.grounding"))
    if empty:
        issues.append(col.issue("partial_grounding", rid, f"grounding has no entries for: {', '.join(empty)}",
                                severity="info", affects=("binding",), detected_by="drawings.grounding"))
    if grounding_family and sheet_family and (sheet_family, grounding_family) not in FAMILY_WORDS_OK:
        issues.append(col.issue("vocabulary_mismatch", rid,
                                f"family word differs: dataset '{sheet_family}' vs grounding '{grounding_family}'",
                                severity="info", affects=("binding",), detected_by="drawings.grounding"))
    col.add_source(record)
    _grounding_observations(col, rid, data, sheet_family, record, status, bool(counts["disputes"]), s)


def _obs(col: Collector, owner: str, local: str, obs_kind: str, *, owner_kind: str, family: str | None,
         source: dict[str, Any], permission: str | None, review_state: str, raw_text: str | None = None,
         candidate: dict[str, Any] | None = None, fields: dict[str, Any] | None = None,
         geometry: dict[str, Any] | None = None, view: str | None = None, confidence: str | None = None,
         flags: dict[str, Any] | None = None, value_bearing: bool = False, sheet_disputed: bool = False,
         label: str = DRAWING_LABEL) -> None:
    binding = [BINDING_NO_HUMAN]
    if value_bearing:
        cand = candidate or {}
        if cand.get("unit") in (None, ""):
            binding.append("unit_missing")
        if confidence == "low":
            binding.append("confidence_low")
        if (flags or {}).get("doubt"):
            binding.append("doubt_recorded")
        if (flags or {}).get("superseded"):
            binding.append("superseded_reading")
    else:
        binding.append(BINDING_NOT_A_VALUE)
    if sheet_disputed:
        binding.append("unresolved_disputes_on_sheet")
    text_ok = bool(raw_text or (candidate and any(v not in (None, "") for v in candidate.values())))
    record = {
        "evidence_id": f"{owner}#{local}",
        "owner_id": owner,
        "owner_kind": owner_kind,
        "local_id": local,
        "obs_kind": obs_kind,
        "category": "A",
        "family": family,
        "view": view,
        "raw_text": raw_text,
        "candidate_interpretation": candidate,
        "fields": fields or {},
        "geometry": geometry,
        "confidence": confidence,
        "source_id": source["id"],
        "source_fingerprint": source["fingerprint"],
        "trust": {
            "label_source": label,
            "epistemic": DRAWING_EPISTEMIC,
            "human_verified": False,
            "review_state": review_state,
            "flags": flags or {},
        },
        "eligibility": eligibility(
            retrieval_ok=text_ok,
            retrieval_reason="observation_unverified" if text_ok else "no_text",
            binding_blockers=binding,
            finetune_blockers=permission_blockers(permission) + ["no_human_label"],
        ),
    }
    col.add_observation(record)


def _text_box(texts: dict[str, dict[str, Any]], ref: str | None) -> dict[str, Any] | None:
    item = texts.get(ref or "")
    if not item or not item.get("box"):
        return None
    return {"space": "image_px", "box": item["box"], "text_ref": ref}


def _grounding_observations(col: Collector, rid: str, data: dict[str, Any], family: str | None,
                            source: dict[str, Any], status: str, sheet_disputed: bool, s: dict[str, Any]) -> None:
    permission = s.get("permission_to_train")
    texts = {t["id"]: t for t in data.get("texts") or [] if isinstance(t, dict) and "id" in t}
    common = dict(owner_kind="drawing_sheet", family=family, source=source, permission=permission,
                  review_state=status, sheet_disputed=sheet_disputed)
    for view in data.get("views") or []:
        if isinstance(view, dict):
            _obs(col, rid, view["id"], "view", raw_text=view.get("title_raw"), view=view["id"],
                 candidate={"type": view.get("type")},
                 fields={"box": view.get("box"), "half": view.get("half"), "crop": view.get("crop"),
                         "drawn_rotation_deg": view.get("drawn_rotation_deg")},
                 geometry={"space": "image_px", "box": view.get("box")}, **common)
    for text in data.get("texts") or []:
        if isinstance(text, dict):
            _obs(col, rid, text["id"], "text", raw_text=text.get("raw"), view=text.get("view"),
                 candidate={"kind": text.get("kind"), "value": text.get("value"), "unit": text.get("unit")},
                 fields={k: text.get(k) for k in ("handwritten", "ink", "alt_reading", "rotation_deg",
                                                    "superseded_by", "revision", "doubt") if k in text},
                 geometry={"space": "image_px", "box": text.get("box")}, confidence=text.get("confidence"),
                 flags={"superseded": bool(text.get("superseded_by")), "doubt": text.get("doubt")},
                 value_bearing=text.get("kind") in ("dimension", "level"), **common)
    for dim in data.get("dimensions") or []:
        if not isinstance(dim, dict):
            continue
        ref = dim.get("text")
        text = texts.get(ref or "", {})
        cand = {k: dim.get(k) for k in ("value", "unit", "measures_from", "measures_to", "sets", "mode",
                                          "orientation", "chain_group", "total", "baseline_from")}
        _obs(col, rid, dim["id"], "dimension", raw_text=text.get("raw"), view=dim.get("view"), candidate=cand,
             fields={"text_ref": ref}, geometry=_text_box(texts, ref), confidence=dim.get("confidence"),
             flags={"doubt": dim.get("doubt")}, value_bearing=True, **common)
    for level in data.get("levels") or []:
        if isinstance(level, dict):
            ref = level.get("text")
            _obs(col, rid, level["id"], "level", raw_text=(texts.get(ref or "", {}) or {}).get("raw"),
                 candidate={"datum": level.get("datum"), "value": level.get("value_m"), "unit": "m",
                            "for": level.get("for")},
                 fields={"text_ref": ref, "status": level.get("status")}, geometry=_text_box(texts, ref),
                 confidence=level.get("confidence"), value_bearing=True, **common)
    for part in data.get("parts") or []:
        if isinstance(part, dict):
            _obs(col, rid, part["id"], "part", raw_text=part.get("label"), view=(part.get("appears_in") or [None])[0],
                 candidate={k: part.get(k) for k in ("class", "status", "status_evidence", "appears_in", "variant",
                                                     "side", "parent", "index", "material", "repeat")},
                 confidence=part.get("confidence"), flags={"doubt": part.get("doubt")}, **common)
    for rep in data.get("repeats") or []:
        if isinstance(rep, dict):
            _obs(col, rid, rep["id"], "repeat", raw_text=rep.get("count_evidence"),
                 candidate={"unit_class": rep.get("unit_class"), "count": rep.get("count"),
                            "members": rep.get("members")}, **common)
    for index, rel_item in enumerate(data.get("relations") or []):
        if isinstance(rel_item, dict):
            _obs(col, rid, f"rel{index}", "relation", raw_text=rel_item.get("evidence"),
                 candidate={k: rel_item.get(k) for k in ("type", "from", "to")},
                 confidence=rel_item.get("confidence"), **common)
    for param in data.get("parameters") or []:
        if isinstance(param, dict):
            _obs(col, rid, f"param:{param.get('name')}", "parameter", raw_text=None,
                 candidate={"name": param.get("name"), "value": param.get("value"), "unit": param.get("unit"),
                            "source": param.get("source"), "from": param.get("from")},
                 confidence=param.get("confidence"), value_bearing=True, **common)
    for index, check in enumerate(data.get("checks") or []):
        if isinstance(check, dict):
            _obs(col, rid, f"check{index}", "check", raw_text=check.get("what"),
                 candidate={"numbers": check.get("numbers"), "result": check.get("result"),
                            "expected": check.get("expected"), "tolerance": check.get("tolerance")},
                 fields={"passed": check.get("passed"), "informational": check.get("informational")}, **common)
    for index, dispute in enumerate(data.get("disputes") or []):
        if isinstance(dispute, dict):
            _obs(col, rid, f"dispute{index}", "dispute", raw_text=dispute.get("what"),
                 candidate={"value_a": dispute.get("value_a"), "value_b": dispute.get("value_b")},
                 fields={"evidence_a": dispute.get("evidence_a"), "evidence_b": dispute.get("evidence_b")}, **common)
    for index, absent in enumerate(data.get("absent") or []):
        if isinstance(absent, dict):
            _obs(col, rid, f"absent{index}", "absent", raw_text=absent.get("why"),
                 candidate={"class": absent.get("class"), "view": absent.get("view")}, **common)
    for index, doubt in enumerate(data.get("doubts") or []):
        if isinstance(doubt, dict):
            _obs(col, rid, f"doubt{index}", "doubt", raw_text=doubt.get("about"),
                 fields={"issue": doubt.get("issue")}, **common)
    for table in data.get("tables") or []:
        if isinstance(table, dict):
            rows = table.get("rows") or []
            _obs(col, rid, table["id"], "table", raw_text=table.get("title_raw"), view=table.get("view"),
                 candidate={"kind": table.get("kind"), "columns": table.get("columns"), "row_count": len(rows)},
                 fields={"rows": rows[:40], "rows_complete": table.get("rows_complete"),
                         "box": table.get("box")}, confidence=table.get("confidence"),
                 flags={"doubt": table.get("doubt")}, **common)



def describe_grounding_status(root: Path, record_id: str) -> dict[str, Any]:
    """Used by the status command: current grounding file state for one sheet."""
    done = _done_status(root).get(record_id, {})
    folder = root / "bridges"
    match = list(folder.glob(f"*/*/sheets/{record_id}/grounding/agent-grounding.json")) if folder.is_dir() else []
    return {"done_status": done.get("status"), "grounding_file": rel(root, match[0]) if match else None}

