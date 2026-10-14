"""Build the registry: run every adapter over the repository and write the derived files.

The build reads the repository and writes only inside agent-context/. It is deterministic: the same inputs
give byte-identical files (no timestamps, sorted keys, sorted records).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .common import CONTEXT_DIR, DEFAULT_ROOT, GENERATOR, REGISTRY_VERSION, sha256_file, sha256_text, write_json, write_jsonl, write_text
from .knowledge import build_token_index, global_index_markdown
from .model import Collector
from .policy import PURPOSES
from .adapters import drawings, kb_sources, rdso, status, vector

ADAPTERS = ("drawings", "vector", "rdso", "kb_sources", "status")


def build(root: Path | None = None, context_dir: Path | None = None) -> dict[str, Any]:
    root = Path(root or DEFAULT_ROOT).resolve()
    if context_dir is None:
        context_dir = CONTEXT_DIR if root == DEFAULT_ROOT else root / "agent-context"
    context_dir = Path(context_dir).resolve()
    col = Collector(root)
    drawings.collect(col)
    vector.collect(col)
    rdso.collect(col)
    kb_sources.collect(col)
    status.collect(col)
    _attach_issues(col)
    summary = _write(col, context_dir)
    return summary


def _attach_issues(col: Collector) -> None:
    """Every issue is listed on the record it names, so `status` can show it without a search."""
    for issue in col.issues.values():
        subject = issue["subject"]
        for table in (col.sources, col.knowledge):
            record = table.get(subject) or table.get(subject.split(":picture")[0].split("#")[0])
            if record is not None and issue["id"] not in record["issues"]:
                record["issues"].append(issue["id"])


def _write(col: Collector, context_dir: Path) -> dict[str, Any]:
    registry = context_dir / "registry"
    knowledge_dir = context_dir / "knowledge"
    reports = context_dir / "reports"
    sources = [col.sources[k] for k in sorted(col.sources)]
    observations = [col.observations[k] for k in sorted(col.observations)]
    knowledge = [col.knowledge[k] for k in sorted(col.knowledge)]
    issues = [col.issues[k] for k in sorted(col.issues)]
    for record in sources + knowledge:
        record["issues"] = sorted(set(record["issues"]))

    write_jsonl(registry / "sources.jsonl", sources)
    write_jsonl(registry / "observations.jsonl", observations)
    write_jsonl(registry / "issues.jsonl", issues)
    write_jsonl(knowledge_dir / "knowledge.jsonl", knowledge)
    token_index = build_token_index(knowledge + sources)
    write_json(knowledge_dir / "search_index.json", {"tokens": token_index, "records": len(knowledge) + len(sources)})
    write_text(knowledge_dir / "GLOBAL_INDEX.md", global_index_markdown(
        knowledge=knowledge, sources=sources, observations_count=len(observations), issues=issues))

    counts = {
        "sources": len(sources),
        "observations": len(observations),
        "knowledge": len(knowledge),
        "issues": len(issues),
        "source_kinds": dict(sorted(Counter(s["kind"] for s in sources).items())),
        "knowledge_categories": dict(sorted(Counter(k["category"] for k in knowledge).items())),
        "observation_kinds": dict(sorted(Counter(o["obs_kind"] for o in observations).items())),
        "issue_kinds": dict(sorted(Counter(i["kind"] for i in issues).items())),
        "eligibility": _eligibility_counts(sources + knowledge + observations),
    }
    digest_input = "\n".join(s["id"] + " " + s["fingerprint"] for s in sources)
    manifest = {
        "registry_version": REGISTRY_VERSION,
        "generator": GENERATOR,
        "adapters": list(ADAPTERS),
        "counts": counts,
        "registry_digest": sha256_text(digest_input),
        "input_hashes": collect_input_hashes(col.root),
        "problems": col.problems,
        "notes": dict(col.notes),
    }
    write_json(registry / "manifest.json", manifest)
    _reports(reports, counts, issues, col.problems, sources, knowledge)
    return {"counts": counts, "problems": col.problems, "digest": manifest["registry_digest"],
            "context_dir": str(context_dir)}


INPUT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("bridges/_index", "*.jsonl"),
    ("catalog", "gad_catalog.jsonl"),
    ("catalog/box_screen", "*.jsonl"),
    ("catalog/classification", "*.jsonl"),
    ("catalog", "SUMMARY.md"),
    ("agent/state/done", "*.json"),
    ("vector-pdfs/_index", "*.jsonl"),
    ("knowledge/kb/entries", "*.jsonl"),
    ("knowledge/kb/training", "*.jsonl"),
    ("knowledge/kb", "topics.json"),
    ("ontology", "*.json"),
    ("knowledge/sources/teaching", "*.jsonl"),
    ("knowledge/sources/books/chunks", "*.jsonl"),
    ("knowledge/sources/books/provenance", "*.json"),
    ("knowledge/sources/rdso", "doc_map.jsonl"),
    ("agent/out/rdso-extract", "_manifest.tsv"),
    ("agent/out/rdso-extract", "_STATUS_AUDIT.txt"),
    ("agent/out/file-status", "CHECKED_BY_HAND.txt"),
    ("schemas", "*.json"),
    (".", "REPORT.md"),
    (".", "grounding_audit.md"),
)


def collect_input_hashes(root: Path) -> dict[str, str]:
    """Hash of every input file the registry reads (not the renders, not the PDFs). Used to detect changes."""
    found: dict[str, str] = {}

    def take(path: Path) -> None:
        if path.is_file():
            found[path.relative_to(root).as_posix()] = sha256_file(path)

    for folder, pattern in INPUT_PATTERNS:
        base = root / folder
        if base.is_dir():
            for path in sorted(base.glob(pattern)):
                take(path)
    for path in sorted((root / "knowledge/kb/proposals").rglob("*")) if (root / "knowledge/kb/proposals").is_dir() else []:
        if path.suffix in {".jsonl", ".md"}:
            take(path)
    for path in sorted((root / "knowledge/sources/engineering").rglob("*")) if (root / "knowledge/sources/engineering").is_dir() else []:
        if path.suffix in {".md", ".txt"}:
            take(path)
    for path in sorted((root / "knowledge/sources/rdso/extracts/rcc-box").glob("*/*")) if (root / "knowledge/sources/rdso/extracts/rcc-box").is_dir() else []:
        if path.suffix in {".json", ".md"}:
            take(path)
    for path in sorted((root / "bridges").glob("*/*/sheets/*/grounding/**/*")) if (root / "bridges").is_dir() else []:
        take(path)
    for path in sorted((root / "vector-pdfs").glob("*/*/sheets/*/sheet.json")) if (root / "vector-pdfs").is_dir() else []:
        take(path)
    for path in sorted((root / "vector-pdfs").glob("*/*/sheets/*/vector/meta.json")) if (root / "vector-pdfs").is_dir() else []:
        take(path)
    for path in sorted((root / "vector-pdfs").glob("*/*/sheets/*/vector/text.jsonl")) if (root / "vector-pdfs").is_dir() else []:
        take(path)
    return found


def _eligibility_counts(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for purpose in PURPOSES:
        tally: Counter[str] = Counter()
        for record in records:
            value = (record.get("eligibility") or {}).get(purpose)
            if value:
                tally["eligible" if value.startswith("eligible:") else "blocked"] += 1
        out[purpose] = dict(sorted(tally.items()))
    return out


def _reports(reports: Path, counts: dict[str, Any], issues: list[dict[str, Any]], problems: list[str],
             sources: list[dict[str, Any]], knowledge: list[dict[str, Any]]) -> None:
    lines = [
        "# Build report (generated by agentctx; do not edit)",
        "",
        f"Registry version {REGISTRY_VERSION}. Derived from the repository; nothing in the repository was changed.",
        "",
        "## Counts",
        "",
        f"- Source records: {counts['sources']}",
        f"- Observations (category A): {counts['observations']}",
        f"- Knowledge records (B, C, D, E): {counts['knowledge']}",
        f"- Issues: {counts['issues']}",
        "",
        "## Eligibility, each purpose on its own",
        "",
        "| Purpose | Eligible | Blocked |",
        "|---|---|---|",
    ]
    for purpose in PURPOSES:
        tally = counts["eligibility"][purpose]
        lines.append(f"| {purpose} | {tally.get('eligible', 0)} | {tally.get('blocked', 0)} |")
    lines += ["", "Binding is blocked everywhere until a person records a verification; fine-tuning follows the "
              "pipeline's rules (permission, human label, review state) and is not changed here.", ""]
    lines += ["## Source kinds", "", "| Kind | Records |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in counts["source_kinds"].items()]
    lines += ["", "## Build problems", ""]
    lines += [f"- {p}" for p in problems] or ["- none"]
    lines.append("")
    write_text(reports / "build_report.md", "\n".join(lines))

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        by_kind.setdefault(issue["kind"], []).append(issue)
    lines = ["# Issues (generated by agentctx; do not edit)", "",
             "Each issue names its subject, its severity and the purposes it blocks. Nothing is fixed automatically.", ""]
    for kind in sorted(by_kind):
        group = by_kind[kind]
        lines += [f"## {kind} ({len(group)})", ""]
        for issue in group[:50]:
            affects = ", ".join(issue["affects"]) or "none"
            lines.append(f"- `{issue['subject']}` [{issue['severity']}; blocks: {affects}] {issue['description']}")
        if len(group) > 50:
            lines.append(f"- … {len(group) - 50} more in registry/issues.jsonl")
        lines.append("")
    write_text(reports / "issues.md", "\n".join(lines))

    coverage = Counter()
    for source in sources:
        if source["kind"] == "drawing_sheet":
            coverage[(source.get("family") or "-", (source.get("completeness") or {}).get("capability", "-"))] += 1
    lines = ["# Coverage (generated by agentctx; do not edit)", "",
             "Drawing sheets by family and capability (what evidence exists for each sheet).", "",
             "| Family | Capability | Sheets |", "|---|---|---|"]
    lines += [f"| {fam} | {cap} | {n} |" for (fam, cap), n in sorted(coverage.items())]
    lines.append("")
    write_text(reports / "coverage.md", "\n".join(lines))
