"""Adapter: knowledge base, proposals, ontology, teaching cards, book chunks, engineering notes, instructions.

Knowledge records keep the trust labels exactly as the repository wrote them (evidence_status, review_state,
use flags, risk flags, authorship). Nothing here promotes a review state or merges a proposal.
Formulas and rules are indexed as text with their conditions; the expression is never executed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..common import canonical_json, clip, read_json, read_jsonl, read_text, rel, sha256_file, sha256_text
from ..model import Collector, make_source
from ..policy import (
    BINDING_KNOWLEDGE_BLOCKER,
    CATEGORY_NAMES,
    eligibility,
    knowledge_category,
    knowledge_finetune_blockers,
    knowledge_retrieval_reason,
)

ENTRIES = "knowledge/kb/entries"
PROPOSALS = "knowledge/kb/proposals"
CHUNK_EXCERPT = 800
INSTRUCTIONS = [
    "CLAUDE.md", "GEMINI.md", "START_HERE.md", "README.md", "agent/CLAUDE.md", "agent/GEMINI.md",
    "agent/AGENT_BRIEF.md", "agent/CLASSIFY_BRIEF.md", "agent/README.md", "tools/README.md",
    "docs/GROUNDING_SPECIFICATION.md", "docs/BRIDGE_IR_SPECIFICATION.md", "docs/SYNTHETIC_DATA.md",
    "knowledge/sources/rdso/extracts/rcc-box/_PROTOCOL.md", "knowledge/sources/SHEET_SCOPES.md",
    "knowledge/kb/README.md", "catalog/README.md",
]


def collect(col: Collector) -> None:
    kb_index = _load_entries(col)
    _proposals(col, kb_index)
    _ontology(col)
    _teaching(col)
    _books(col)
    _engineering(col)
    _instructions(col)
    _schemas(col)
    _training_artifact(col)
    _kb_files(col)


def _load_entries(col: Collector) -> dict[str, dict[str, Any]]:
    """Normalise every KB entry. Returns kb_id -> normalised knowledge record (used by the proposal check)."""
    root = col.root
    index: dict[str, dict[str, Any]] = {}
    topics = {t["id"] for t in (read_json(root / "knowledge/kb/topics.json") or {}).get("topics", [])}
    folder = root / ENTRIES
    if not folder.is_dir():
        col.issue("missing_corpus", ENTRIES, "knowledge base entries folder is missing", severity="error",
                  affects=("retrieval",), detected_by="kb.entries")
        return index
    for path in sorted(folder.glob("*.jsonl")):
        rows, problems = read_jsonl(path)
        for problem in problems:
            col.issue("unreadable_index_line", rel(root, path), problem, severity="error",
                      affects=("retrieval",), detected_by="kb.entries")
        unresolved_origins = 0
        origin_samples: list[str] = []
        for line_number, entry in enumerate(_lines_with_numbers(path), 1):
            if entry is None:
                continue
            record, unresolved = _knowledge_record(col, entry, path, line_number, topics)
            if record is None:
                continue
            unresolved_origins += unresolved
            if unresolved and len(origin_samples) < 3:
                origin_samples.append(record["id"])
            col.add_knowledge(record)
            index[record["kb_id"]] = record
        source = make_source(
            root,
            record_id=f"kb-file:{path.stem}",
            kind="kb_entries_file",
            title=f"knowledge base entries: {path.stem}",
            paths=[path],
            category=None,
            existing_ids={"topic": path.stem},
            completeness={"entries": sum(1 for r in index.values() if r["topic"] == path.stem)},
            verification={"human_verified": False, "checked_against_picture": "none"},
            trust={"label_source": "llm_assist", "epistemic": "UNKNOWN"},
            eligibility=eligibility(retrieval_ok=True, retrieval_reason="index_entry",
                                    binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                    finetune_blockers=["no_training_permission_record"]),
            provenance={"entries_path": rel(root, path)},
            summary=f"{len(rows)} entries; {unresolved_origins} citation origin(s) not found in the repository",
        )
        if unresolved_origins:
            source["issues"].append(col.issue(
                "unresolved_citation_origin", f"kb-file:{path.stem}",
                f"{unresolved_origins} citation origins in {path.name} do not resolve to a file in the repository "
                f"(examples: {', '.join(origin_samples)}). The citation is kept as written.",
                severity="info", affects=("binding",), detected_by="kb.citations",
            ))
        internal = sum(1 for r in index.values() if r["topic"] == path.stem and r.get("internal_source_ids"))
        if internal:
            source["issues"].append(col.issue(
                "internal_source_id", f"kb-file:{path.stem}",
                f"{internal} entries cite internal source ids (e.g. SRC-GEOMETRY) that are not documents in the repository.",
                severity="info", affects=("binding",), detected_by="kb.citations",
            ))
        col.add_source(source)
    return index


def _lines_with_numbers(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                yield None
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                yield None
                continue
            yield value if isinstance(value, dict) else None


def _origin_exists(root: Path, origin: str) -> bool:
    if not origin or " " in origin and "/" not in origin:
        return False
    candidates = [root / origin, root.parent / origin, root / "knowledge/sources" / origin]
    if origin.startswith("knowledge/"):
        candidates.append(root / "knowledge/sources" / origin[len("knowledge/"):])
    if origin.startswith("rdso/"):
        candidates.append(root / "knowledge/sources" / origin)
    return any(c.exists() for c in candidates)


def _knowledge_record(col: Collector, entry: dict[str, Any], path: Path, line: int,
                      topics: set[str]) -> tuple[dict[str, Any] | None, int]:
    root = col.root
    kb_id = entry.get("id")
    topic = entry.get("topic") or path.stem
    if not kb_id:
        col.issue("missing_id", rel(root, path), f"entry at line {line} has no id", severity="error",
                  affects=("retrieval",), detected_by="kb.entries")
        return None, 0
    review = entry.get("review_state")
    evidence = entry.get("evidence_status")
    category = knowledge_category(topic, review, evidence)
    issues: list[str] = []
    if topic not in topics:
        issues.append(col.issue("unmapped_topic", kb_id, f"topic '{topic}' is not in knowledge/kb/topics.json",
                                severity="warning", affects=("retrieval",), detected_by="kb.entries"))
    if category is None:
        category = "C"
    names = entry.get("names") or {}
    payload = entry.get("payload") or {}
    applies = ((payload.get("applies") or {}).get("families") if isinstance(payload, dict) else None) or []
    citations: list[dict[str, Any]] = []
    unresolved = 0
    internal_ids: list[str] = []
    for item in entry.get("merged_from") or []:
        origin = item.get("origin", "")
        resolved = _origin_exists(root, origin)
        if not resolved:
            unresolved += 1
        citations.append({"origin": origin, "id": item.get("id"), "note": clip(item.get("note"), 200),
                          "resolved": resolved, "kind": "merged_from"})
    for item in entry.get("sources") or []:
        source_id = item.get("source", "") or ""
        if "/" not in source_id and " " not in source_id:
            internal_ids.append(source_id)
            resolved = False
        else:
            resolved = _origin_exists(root, source_id.split(" (")[0])
            if not resolved:
                unresolved += 1
        citations.append({"origin": source_id, "clause": item.get("clause"), "page": item.get("page"),
                          "note": clip(item.get("note"), 200), "resolved": resolved, "kind": "sources"})
    statement = entry.get("definition") or (entry.get("teaching") or {}).get("what") or ""
    teaching = entry.get("teaching") or {}
    expression = payload.get("expression") if isinstance(payload, dict) else None
    fin_blockers = knowledge_finetune_blockers(
        category=category, review_state=review, evidence_status=evidence,
        qa_training=bool((entry.get("use") or {}).get("qa_training")), permitted=False,
    )
    record = {
        "id": f"kb:{kb_id}",
        "kb_id": kb_id,
        "category": category,
        "category_name": CATEGORY_NAMES[category],
        "topic": topic,
        "kind": entry.get("kind"),
        "title": names.get("canonical") or kb_id,
        "aliases": names.get("aliases") or [],
        "statement": clip(statement, 1200),
        "interpretation": clip(teaching.get("on_sheet"), 600),
        "expression": {"text": expression, "executed": False,
                       "status": "not_executable_until_validated"} if expression else None,
        "applies_families": applies,
        "trust": {
            "evidence_status": evidence,
            "review_state": review,
            "use": entry.get("use") or {},
            "risk_flags": entry.get("risk_flags") or [],
            "authored": entry.get("authored"),
            "reviewed": entry.get("reviewed"),
            "label_source": "llm_assist" if entry.get("authored") else "knowledge_lookup",
        },
        "citations": citations,
        "internal_source_ids": internal_ids,
        "conflicts": entry.get("conflicts") or [],
        "relations": [r for r in (entry.get("relations") or []) if isinstance(r, (str, dict))][:20],
        "retrieval_pointers": entry.get("retrieval") or [],
        "rdso_mentions": entry.get("rdso_mentions") or [],
        "sheet_refs": [s.get("record_id") if isinstance(s, dict) else s for s in (entry.get("sheet_evidence") or [])][:40],
        "proposal_status": "none",
        "source_path": rel(root, path),
        "source_line": line,
        "fingerprint": sha256_text(canonical_json(entry)),
        "search_text": " ".join(str(x) for x in [names.get("canonical"), *(names.get("aliases") or []), kb_id, topic,
                                                    entry.get("kind"), statement, teaching.get("what"),
                                                    teaching.get("on_sheet"), expression] if x),
        "eligibility": eligibility(
            retrieval_ok=bool(statement or names.get("canonical")),
            retrieval_reason=knowledge_retrieval_reason(category, review, evidence),
            binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
            finetune_blockers=fin_blockers,
        ),
        "issues": issues,
        "raw": entry,
    }
    if category == "D" and review == "proposed":
        record["issues"].append(col.issue("proposed_knowledge", record["id"],
                                          "proposed in the knowledge base, not reviewed", severity="info",
                                          affects=("binding", "finetune"), detected_by="kb.entries"))
    if evidence == "DISPUTED":
        record["issues"].append(col.issue("disputed_knowledge", record["id"],
                                          "evidence_status DISPUTED: sources disagree; see conflicts",
                                          severity="warning", affects=("binding", "finetune"),
                                          detected_by="kb.entries"))
    return record, unresolved


def _proposals(col: Collector, kb_index: dict[str, dict[str, Any]]) -> None:
    root = col.root
    folder = root / PROPOSALS
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix not in {".jsonl", ".md"}:
            continue
        relpath = rel(root, path)
        if path.suffix == ".jsonl":
            rows, problems = read_jsonl(path)
            for problem in problems:
                col.issue("unreadable_index_line", relpath, problem, severity="error", affects=("retrieval",),
                          detected_by="kb.proposals")
            for number, row in enumerate(rows, 1):
                kb_id = row.get("id")
                existing = kb_index.get(kb_id or "")
                status = "amends_existing_entry" if existing else "new_candidate"
                record = {
                    "id": f"proposal:{path.stem}:{number}",
                    "kb_id": kb_id,
                    "category": "D",
                    "category_name": CATEGORY_NAMES["D"],
                    "topic": row.get("topic"),
                    "kind": row.get("kind"),
                    "title": (row.get("names") or {}).get("canonical") or kb_id,
                    "aliases": (row.get("names") or {}).get("aliases") or [],
                    "statement": clip(row.get("definition") or (row.get("teaching") or {}).get("what"), 1200),
                    "interpretation": clip((row.get("teaching") or {}).get("on_sheet"), 600),
                    "expression": None,
                    "applies_families": [],
                    "trust": {"evidence_status": row.get("evidence_status"), "review_state": row.get("review_state"),
                              "use": row.get("use") or {}, "risk_flags": row.get("risk_flags") or [],
                              "authored": row.get("authored"), "reviewed": row.get("reviewed"),
                              "label_source": "llm_assist"},
                    "citations": [{"origin": relpath, "resolved": True, "kind": "proposal_file"}],
                    "internal_source_ids": [],
                    "conflicts": row.get("conflicts") or [],
                    "relations": [],
                    "retrieval_pointers": [],
                    "rdso_mentions": [],
                    "sheet_refs": [],
                    "proposal_status": "unmerged:" + status,
                    "source_path": relpath,
                    "source_line": number,
                    "fingerprint": sha256_text(canonical_json(row)),
                    "search_text": " ".join(str(x) for x in [kb_id, row.get("topic"), row.get("definition")] if x),
                    "eligibility": eligibility(
                        retrieval_ok=True,
                        retrieval_reason="proposed_or_disputed_do_not_present_as_accepted",
                        binding_blockers=[BINDING_KNOWLEDGE_BLOCKER, "proposal_not_merged"],
                        finetune_blockers=["proposed_or_disputed", "proposal_not_merged",
                                           "review_state_" + str(row.get("review_state"))],
                    ),
                    "issues": [],
                    "raw": row,
                }
                record["issues"].append(col.issue(
                    "proposal_not_merged", record["id"],
                    f"{status.replace('_', ' ')}: {kb_id}. Waiting for owner review; never merged automatically.",
                    severity="info", affects=("binding", "finetune"), detected_by="kb.proposals"))
                col.add_knowledge(record)
        else:
            text = read_text(path) or ""
            heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), path.name)
            col.add_source(make_source(
                root, record_id=f"proposal-log:{path.parent.name}/{path.name}", kind="proposal_log",
                title=clip(heading, 200) or path.name, paths=[path], category="D",
                trust={"label_source": "human_or_llm_log", "epistemic": "UNKNOWN"},
                eligibility=eligibility(retrieval_ok=True, retrieval_reason="proposal_log",
                                        binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                        finetune_blockers=["proposal_not_merged"]),
                provenance={"path": relpath}, summary=clip(text, 200),
            ))


def _ontology(col: Collector) -> None:
    root = col.root
    folder = root / "ontology"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        data = read_json(path)
        if data is None:
            continue
        rows = _ontology_rows(path.name, data)
        col.add_source(make_source(
            root, record_id=f"ontology-file:{path.stem}", kind="ontology_file", title=path.name, paths=[path],
            category="C", existing_ids={"file": rel(root, path)},
            completeness={"items": len(rows)},
            verification={"human_verified": False, "checked_against_picture": "none",
                          "review_state": "seed_unreviewed"},
            trust={"label_source": "llm_assist", "epistemic": "UNKNOWN"},
            eligibility=eligibility(retrieval_ok=True, retrieval_reason="seed_unreviewed_vocabulary",
                                    binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                    finetune_blockers=["review_state_seed_unreviewed", "no_training_permission_record"]),
            provenance={"file": rel(root, path)},
            summary=f"{len(rows)} items",
        ))
        for item in rows:
            item_id = item.get("id") or item.get("term") or item.get("name")
            if not item_id:
                continue
            ontology_id = f"ontology:{item_id}"
            if ontology_id in col.knowledge:
                ontology_id = f"ontology:{path.stem}:{item_id}"
            count = 2
            base_id = ontology_id
            while ontology_id in col.knowledge:
                ontology_id = f"{base_id}#{count}"
                count += 1
            col.add_knowledge({
                "id": ontology_id,
                "kb_id": None,
                "category": "C",
                "category_name": CATEGORY_NAMES["C"],
                "topic": "ontology:" + path.stem,
                "kind": item.get("level") or item.get("tree") or item.get("register"),
                "title": item.get("canonical_name") or item.get("name") or item.get("term") or str(item_id),
                "aliases": item.get("aliases") or [],
                "statement": clip(item.get("definition") or item.get("maps_to") or item.get("what"), 800),
                "interpretation": None,
                "expression": None,
                "applies_families": item.get("families") or [],
                "trust": {"review_state": "seed_unreviewed", "evidence_status": None,
                          "label_source": "llm_assist"},
                "citations": [{"origin": rel(root, path), "resolved": True, "kind": "ontology_file"}],
                "internal_source_ids": [],
                "conflicts": [],
                "relations": [],
                "retrieval_pointers": [],
                "rdso_mentions": [],
                "sheet_refs": [],
                "proposal_status": "none",
                "source_path": rel(root, path),
                "source_line": None,
                "fingerprint": sha256_text(canonical_json(item)),
                "search_text": " ".join(str(x) for x in [item_id, item.get("canonical_name"), item.get("definition"),
                                                         *(item.get("aliases") or [])] if x),
                "eligibility": eligibility(
                    retrieval_ok=True, retrieval_reason="seed_unreviewed_vocabulary",
                    binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                    finetune_blockers=["review_state_seed_unreviewed", "no_training_permission_record"]),
                "issues": [],
                "raw": item,
            })


def _ontology_rows(name: str, data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("classes", "families", "relations", "terms", "abbreviations", "materials"):
            value = data.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
    if name == "terminology.json" and isinstance(data, dict):
        return [t for t in data.get("terms", []) if isinstance(t, dict)]
    return []


def _teaching(col: Collector) -> None:
    root = col.root
    path = root / "knowledge/sources/teaching/glossary_cards_v0.jsonl"
    rows, problems = read_jsonl(path)
    for problem in problems:
        col.issue("unreadable_index_line", rel(root, path), problem, severity="error", affects=("retrieval",),
                  detected_by="kb.teaching")
    col.add_source(make_source(
        root, record_id="teaching-file:glossary_cards_v0", kind="teaching_file", title="glossary cards v0",
        paths=[path], category="C", completeness={"cards": len(rows)},
        trust={"label_source": "llm_assist", "epistemic": "UNKNOWN"},
        eligibility=eligibility(retrieval_ok=bool(rows), retrieval_reason="teaching_cards_unreviewed",
                                binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                finetune_blockers=["review_state_seed_unreviewed"]),
        provenance={"file": rel(root, path)}, summary=f"{len(rows)} cards",
    ))
    for number, card in enumerate(rows, 1):
        term = card.get("term") or f"card{number}"
        slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
        col.add_knowledge({
            "id": f"teach:{slug}",
            "kb_id": None,
            "category": "C",
            "category_name": CATEGORY_NAMES["C"],
            "topic": "teaching",
            "kind": card.get("group"),
            "title": term,
            "aliases": card.get("aliases") or [],
            "statement": clip(card.get("what"), 800),
            "interpretation": clip(card.get("on_sheet"), 600),
            "expression": None,
            "applies_families": [],
            "trust": {"review_state": "seed_unreviewed", "evidence_status": None, "label_source": "llm_assist",
                      "why": clip(card.get("why"), 300)},
            "citations": [{"origin": rel(root, path), "line": number, "resolved": True, "kind": "teaching_card"}],
            "internal_source_ids": [],
            "conflicts": [],
            "relations": [],
            "retrieval_pointers": [],
            "rdso_mentions": [],
            "sheet_refs": [],
            "proposal_status": "none",
            "source_path": rel(root, path),
            "source_line": number,
            "fingerprint": sha256_text(canonical_json(card)),
            "search_text": " ".join(str(x) for x in [term, *(card.get("aliases") or []), card.get("what"),
                                                     card.get("on_sheet")] if x),
            "eligibility": eligibility(
                retrieval_ok=True, retrieval_reason="teaching_card_unreviewed",
                binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                finetune_blockers=["review_state_seed_unreviewed", "no_training_permission_record"]),
            "issues": [],
            "raw": card,
        })


def _books(col: Collector) -> None:
    root = col.root
    folder = root / "knowledge/sources/books/chunks"
    provenance_dir = root / "knowledge/sources/books/provenance"
    engineering_hashes = _hash_map(root / "knowledge/sources/engineering")
    for path in sorted(provenance_dir.glob("*.json")) if provenance_dir.is_dir() else []:
        data = read_json(path) or {}
        digest = data.get("sha256")
        matched = engineering_hashes.get(digest)
        col.add_source(make_source(
            root, record_id=f"book-source:{data.get('source_id', path.stem)}", kind="book_source",
            title=clip(data.get("title") or path.stem, 200) or path.stem, paths=[path], category="B",
            existing_ids={"source_id": data.get("source_id"), "sha256": digest},
            completeness={"authority": data.get("authority"), "provenance_resolved": bool(matched)},
            trust={"label_source": "knowledge_lookup", "epistemic": "UNKNOWN", "authority": data.get("authority")},
            eligibility=eligibility(retrieval_ok=True, retrieval_reason="book_source_register",
                                    binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                    finetune_blockers=["no_training_permission_record"]),
            provenance={"licence_note": data.get("licence_note"), "matched_file": matched},
            summary=clip(data.get("licence_note"), 200),
        ))
    for pdf in sorted((root / "knowledge/sources/books/pdf").glob("*.pdf")) if (root / "knowledge/sources/books/pdf").is_dir() else []:
        col.add_source(make_source(
            root, record_id=f"book-pdf:{pdf.stem}", kind="book_pdf", title=pdf.name, paths=[pdf], category="B",
            trust={"label_source": "knowledge_lookup", "epistemic": "UNKNOWN"},
            eligibility=eligibility(retrieval_ok=True, retrieval_reason="book_pdf_register",
                                    binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                    finetune_blockers=["no_training_permission_record"]),
            provenance={"file": rel(root, pdf)}, summary="book PDF (pointer only; not copied)",
        ))
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("*.jsonl")):
        rows, problems = read_jsonl(path)
        for problem in problems:
            col.issue("unreadable_index_line", rel(root, path), problem, severity="error", affects=("retrieval",),
                      detected_by="books.chunks")
        for number, chunk in enumerate(rows, 1):
            chunk_id = chunk.get("chunk_id") or f"{path.stem}:{number}"
            text = chunk.get("text") or ""
            col.add_knowledge({
                "id": f"chunk:{chunk_id}",
                "kb_id": None,
                "category": "B",
                "category_name": CATEGORY_NAMES["B"],
                "topic": "book_chunk",
                "kind": chunk.get("kind"),
                "title": clip(chunk.get("section") or chunk_id, 200),
                "aliases": [],
                "statement": clip(text, CHUNK_EXCERPT),
                "interpretation": None,
                "expression": None,
                "applies_families": [],
                "trust": {"review_state": "unreviewed", "evidence_status": "UNKNOWN",
                          "label_source": "observed_vector" if chunk.get("ocr") is False else "vlm",
                          "ocr": chunk.get("ocr")},
                "citations": [{"origin": rel(root, path), "page": chunk.get("page"), "section": chunk.get("section"),
                               "source_id": chunk.get("source_id"), "resolved": True, "kind": "book_chunk"}],
                "internal_source_ids": [],
                "conflicts": [],
                "relations": [],
                "retrieval_pointers": [],
                "rdso_mentions": [],
                "sheet_refs": [],
                "proposal_status": "none",
                "source_path": rel(root, path),
                "source_line": number,
                "fingerprint": sha256_text(canonical_json(chunk)),
                "search_text": " ".join(str(x) for x in [chunk.get("section"), text] if x)[:4000],
                "eligibility": eligibility(
                    retrieval_ok=bool(text.strip()), retrieval_reason="book_chunk_unreviewed",
                    binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                    finetune_blockers=["review_state_unreviewed", "no_training_permission_record"]),
                "issues": [],
                "raw": {"chunk_id": chunk_id, "page": chunk.get("page"), "source_id": chunk.get("source_id")},
            })


def _hash_map(folder: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not folder.is_dir():
        return out
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix in {".md", ".txt", ".json"}):
        out[sha256_file(path)] = path.as_posix()
    return out


def _engineering(col: Collector) -> None:
    root = col.root
    folder = root / "knowledge/sources/engineering"
    if not folder.is_dir():
        return
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix in {".md", ".txt"}):
        text = read_text(path) or ""
        headings = [line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")][:6]
        relpath = rel(root, path)
        col.add_source(make_source(
            root, record_id=f"engineering:{relpath}", kind="engineering_note", title=path.name, paths=[path],
            category="B", family=_family_hint(path),
            completeness={"lines": text.count("\n") + 1, "headings": headings},
            trust={"label_source": "llm_assist", "epistemic": "UNKNOWN",
                   "note": "unreviewed research text; no clause verified"},
            eligibility=eligibility(retrieval_ok=bool(text.strip()), retrieval_reason="unreviewed_research_text",
                                    binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                    finetune_blockers=["review_state_unreviewed", "no_training_permission_record"]),
            provenance={"path": relpath}, summary=clip(" | ".join(headings) or text[:200], 300),
        ))


def _family_hint(path: Path) -> str | None:
    name = path.name.lower()
    for key, family in (("rcc-box", "rcc_box"), ("highway-rcc", "rcc_box"), ("pipe", "pipe"), ("psc", "slab"),
                        ("girder", "girder"), ("arch", "arch"), ("skew", "girder")):
        if key in name:
            return family
    return None


def _instructions(col: Collector) -> None:
    root = col.root
    for relpath in INSTRUCTIONS:
        path = root / relpath
        if not path.is_file():
            continue
        text = read_text(path) or ""
        heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), path.name)
        col.add_source(make_source(
            root, record_id=f"instruction:{relpath}", kind="instruction", title=clip(heading, 200) or relpath,
            paths=[path], category="E",
            trust={"label_source": "human_written", "epistemic": "UNKNOWN"},
            eligibility=eligibility(retrieval_ok=True, retrieval_reason="operational_instruction",
                                    binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                    finetune_blockers=["operational_text_not_training_data"]),
            provenance={"path": relpath}, summary=clip(text, 200),
        ))


def _schemas(col: Collector) -> None:
    root = col.root
    for path in sorted((root / "schemas").glob("*.json")) if (root / "schemas").is_dir() else []:
        data = read_json(path) or {}
        props = list((data.get("properties") or {}).keys())
        col.add_source(make_source(
            root, record_id=f"schema:{path.stem}", kind="schema", title=data.get("title") or path.stem,
            paths=[path], category=None,
            completeness={"required": data.get("required") or [], "properties": props[:60],
                          "version": data.get("x-schema-version")},
            trust={"label_source": "human_written", "epistemic": "UNKNOWN"},
            eligibility=eligibility(retrieval_ok=True, retrieval_reason="format_definition",
                                    binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                    finetune_blockers=["not_training_data"]),
            provenance={"path": rel(root, path)},
            summary=clip(data.get("description"), 200),
        ))


def _training_artifact(col: Collector) -> None:
    root = col.root
    path = root / "knowledge/kb/training/qa_reviewed.jsonl"
    rows, _ = read_jsonl(path)
    states: dict[str, int] = {}
    for row in rows:
        key = str(row.get("review_state"))
        states[key] = states.get(key, 0) + 1
    col.add_source(make_source(
        root, record_id="training-artifact:kb-qa-reviewed", kind="training_artifact",
        title="knowledge base Q&A lines (reviewed name, not reviewed content)", paths=[path], category=None,
        completeness={"lines": len(rows), "review_states": states},
        verification={"human_verified": False, "checked_against_picture": "none"},
        trust={"label_source": "llm_assist", "epistemic": "UNKNOWN"},
        eligibility=eligibility(retrieval_ok=False, retrieval_reason="training_artifact_not_context",
                                binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                finetune_blockers=["review_state_not_reviewed", "drafts_present"]),
        provenance={"path": rel(root, path), "note": "items are not copied into agent-context"},
        summary=f"{len(rows)} lines; review states {states}",
    ))


def _kb_files(col: Collector) -> None:
    root = col.root
    for relpath in ("knowledge/kb/import_report.md", "knowledge/kb/topics.json"):
        path = root / relpath
        if path.is_file():
            col.add_source(make_source(
                root, record_id=f"kb-file:{path.name}", kind="kb_file", title=path.name, paths=[path], category=None,
                trust={"label_source": "human_written", "epistemic": "UNKNOWN"},
                eligibility=eligibility(retrieval_ok=True, retrieval_reason="kb_register",
                                        binding_blockers=[BINDING_KNOWLEDGE_BLOCKER],
                                        finetune_blockers=["not_training_data"]),
                provenance={"path": relpath}, summary=f"knowledge base file {path.name}",
            ))

