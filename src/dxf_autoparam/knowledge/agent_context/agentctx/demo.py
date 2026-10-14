"""Demonstration packs from real records already in the repository, with their true completeness states.

Nothing here is a fixture. Records are chosen from the registry by what they hold (grounded, partly grounded,
ungrounded, vector-only, saved or unsaved page). Each pack is written to agent-context/packs/ and validated.
"""

from __future__ import annotations

from typing import Any

from .api import Context


def _first(ids: list[str]) -> str | None:
    return ids[0] if ids else None


def run_demo(ctx: Context) -> dict[str, Any]:
    store = ctx.store
    sheets = sorted((s for s in store.sources.values() if s["kind"] == "drawing_sheet"), key=lambda s: s["id"])
    grounding = sorted((s for s in store.sources.values() if s["kind"] == "grounding"), key=lambda s: s["id"])
    partial_owner = _first([g["owner"] for g in grounding
                            if (g.get("completeness") or {}).get("sections_empty")])
    selections: list[tuple[str | None, str, str]] = [
        ("21cc08a32dd8-p1", "dimension_binding",
         "grounded RUB sheet with open disputes and revision conflicts"),
        (_first([s["id"] for s in sheets if s.get("family") == "pipe"
                 and (s.get("completeness") or {}).get("capability") == "grounded_needs_review"]),
         "component_interpretation", "grounded pipe culvert sheet"),
        (_first([s["id"] for s in sheets if s.get("family") == "rcc_box"
                 and (s.get("completeness") or {}).get("capability") == "picture_only_ungrounded"]),
         "source_evidence", "ungrounded RCC box sheet: identity and picture only (limited pack)"),
        (partial_owner, "geometric_relationships", "grounded sheet with missing grounding sections (partial)"),
        ("v-993a513ea007-p1", "geometric_relationships", "vector sheet: text layer only, no grounding"),
        ("rdso:RDSO-RCC-BOX-10152-R-SERIES:p1", "source_evidence", "saved RDSO page, checked at view level"),
        ("rdso:RDSO-RCC-BOX-10157-6TO-10157-10:p1", "dimension_binding",
         "RDSO page whose values were never read from a displayed image"),
        ("rdso:RDSO-RCC-BOX-10157-6TO-10157-10:p3", "source_evidence", "RDSO page that is not saved"),
    ]
    results: list[dict[str, Any]] = []
    for record_id, task, why in selections:
        if not record_id:
            results.append({"task": task, "why": why, "status": "no matching record in this repository"})
            continue
        pack = ctx.build_evidence_pack(record_id, task)
        report = ctx.validate_evidence_pack(pack)
        results.append({
            "why": why,
            "pack_id": pack["pack_id"],
            "record_id": record_id,
            "task": task,
            "completeness": pack["completeness"]["status"],
            "missing": pack["completeness"]["missing"],
            "claims": len(pack.get("claims", [])),
            "candidates": len(pack.get("candidate_interpretations", [])),
            "conflicts": len(pack.get("conflicts", [])),
            "live_cad_binding": pack["live_cad_binding"]["status"],
            "valid": report["valid"],
            "errors": report["errors"],
            "written_to": f"agent-context/packs/{pack['pack_id']}.json",
        })
    return {"packs": results, "valid": all(r.get("valid") for r in results if "valid" in r)}
