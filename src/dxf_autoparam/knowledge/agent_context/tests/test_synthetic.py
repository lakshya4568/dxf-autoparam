"""Unit tests on a synthetic repository (see fixtures.py). Synthetic data is for these tests only."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from fixtures import BRIDGE, DOC, SHEET_GROUNDED, SHEET_PARTIAL, SHEET_UNGROUNDED, VECTOR, make_repository  # noqa: E402

from agentctx import Context  # noqa: E402
from agentctx.common import sha256_file  # noqa: E402
from agentctx.registry import collect_input_hashes  # noqa: E402

PAGE = f"rdso:{DOC}:p1"


class SyntheticRepository(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.root = make_repository(cls.tmp)
        cls.ctx = Context(root=cls.root, context_dir=cls.root / "agent-context")
        cls.summary = cls.ctx.build_registry()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def obs(self, owner: str, local: str) -> dict:
        result = self.ctx.get_evidence(f"{owner}#{local}")
        self.assertTrue(result["found"], f"{owner}#{local} not found")
        return result["record"]

    # --- build and schemas ----------------------------------------------------------------------------------------
    def test_build_is_clean_and_records_validate(self) -> None:
        self.assertEqual(self.summary["problems"], [])
        report = self.ctx.check()
        for table, values in report["record_schemas"].items():
            self.assertEqual(values["invalid"], 0, f"{table}: {values['examples']}")

    def test_build_does_not_modify_inputs(self) -> None:
        before = collect_input_hashes(self.root)
        self.ctx.build_registry()
        self.assertEqual(before, collect_input_hashes(self.root))

    def test_rebuild_is_deterministic(self) -> None:
        names = ["registry/sources.jsonl", "registry/observations.jsonl", "registry/issues.jsonl",
                 "knowledge/knowledge.jsonl", "knowledge/search_index.json", "knowledge/GLOBAL_INDEX.md"]
        first = {n: sha256_file(self.root / "agent-context" / n) for n in names}
        self.ctx.build_registry()
        second = {n: sha256_file(self.root / "agent-context" / n) for n in names}
        self.assertEqual(first, second)

    # --- raw text and candidate readings are kept apart ---------------------------------------------------------------
    def test_raw_text_and_candidate_are_separate(self) -> None:
        record = self.obs(SHEET_GROUNDED, "T2")
        self.assertEqual(record["raw_text"], "3500")
        self.assertEqual(record["candidate_interpretation"]["value"], 3500)
        self.assertFalse(record["trust"]["human_verified"])
        self.assertEqual(record["trust"]["review_state"], "needs_review")

    def test_live_item_is_read_from_the_source_file(self) -> None:
        result = self.ctx.get_evidence(f"{SHEET_GROUNDED}#T2", live=True)
        self.assertEqual(result["live_item"]["raw"], "3500")

    def test_every_observation_binding_is_blocked_with_a_reason(self) -> None:
        for obs in self.ctx.store.observations.values():
            binding = obs["eligibility"]["binding"]
            self.assertTrue(binding.startswith("blocked:"), obs["evidence_id"])
            self.assertTrue(binding.split(":", 1)[1], obs["evidence_id"])

    def test_ambiguous_dimension_reports_its_blockers(self) -> None:
        d2 = self.obs(SHEET_GROUNDED, "D2")["eligibility"]["binding"]
        for reason in ("no_human_verification", "unit_missing", "confidence_low", "doubt_recorded",
                       "unresolved_disputes_on_sheet"):
            self.assertIn(reason, d2)
        self.assertEqual(self.obs(SHEET_GROUNDED, "D1")["candidate_interpretation"]["unit"], "m")

    def test_superseded_text_is_flagged_not_hidden(self) -> None:
        record = self.obs(SHEET_GROUNDED, "T3")
        self.assertTrue(record["trust"]["flags"]["superseded"])
        self.assertIn("superseded_reading", record["eligibility"]["binding"])

    # --- source status and issues -----------------------------------------------------------------------------------
    def test_failed_check_is_a_warning_and_disputes_are_issues(self) -> None:
        status = self.ctx.get_source_status(SHEET_GROUNDED)
        kinds = {i["kind"]: i for i in status["issues"]}
        self.assertEqual(kinds["failed_check"]["severity"], "warning")
        self.assertIn("unresolved_disputes", kinds)
        self.assertEqual(status["completeness"]["capability"], "grounded_needs_review")

    def test_partial_grounding_is_reported_not_fabricated(self) -> None:
        status = self.ctx.get_source_status(SHEET_PARTIAL)
        kinds = {i["kind"] for i in status["issues"]}
        self.assertIn("partial_grounding", kinds)
        self.assertEqual(status["observations"].get("dimension", 0), 0)

    def test_ungrounded_sheet_is_identity_only_with_no_observations(self) -> None:
        status = self.ctx.get_source_status(SHEET_UNGROUNDED)
        self.assertEqual(status["completeness"]["capability"], "picture_only_ungrounded")
        self.assertEqual(status["observations"], {})
        self.assertEqual(status["eligibility"]["finetune"].split(":")[0], "blocked")

    def test_missing_crop_and_unclear_reading_are_kept(self) -> None:
        status = self.ctx.get_source_status(PAGE)
        self.assertTrue(status["completeness"]["saved"])
        self.assertEqual(status["completeness"]["crops_missing"], 1)
        self.assertIn("missing_crop", {i["kind"] for i in status["issues"]})
        unclear = [o for o in self.ctx.store.observations.values()
                   if o["owner_id"] == PAGE and o["obs_kind"] == "rdso_unclear"]
        self.assertEqual(len(unclear), 1)
        self.assertIn("two readings", unclear[0]["raw_text"])

    def test_unsaved_page_is_reported_as_not_saved(self) -> None:
        status = self.ctx.get_source_status(f"rdso:{DOC}:p2")
        self.assertFalse(status["completeness"]["saved"])
        self.assertEqual(status["eligibility"]["retrieval"].split(":")[0], "blocked")

    def test_document_claim_stays_a_claim(self) -> None:
        status = self.ctx.get_source_status(f"rdso-extract:{DOC}")
        self.assertEqual(status["completeness"]["status_label"], "Partly saved")
        self.assertIn("open_point", {i["kind"] for i in status["issues"]})
        self.assertEqual(status["verification"]["verified_values"], "none")

    def test_stale_report_claim_is_detected(self) -> None:
        issues = [i for i in self.ctx.store.issues.values() if i["kind"] == "stale_document"]
        self.assertEqual(len(issues), 1)
        self.assertIn("_archive", issues[0]["description"])
        self.assertIn("no longer exist: _archive", issues[0]["description"])

    def test_broken_citation_origin_is_kept_as_written(self) -> None:
        knowledge = self.ctx.store.knowledge["kb:kb.component.box_barrel"]
        unresolved = [c for c in knowledge["citations"] if c.get("resolved") is False]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["origin"], "knowledge/missing_source.md")
        issue_kinds = {self.ctx.store.issues[i]["kind"] for i in self.ctx.store.issues
                       if self.ctx.store.issues[i]["subject"] == "kb-file:component"}
        self.assertIn("unresolved_citation_origin", issue_kinds)

    # --- knowledge categories, trust, proposals ----------------------------------------------------------------------
    def test_normative_label_without_review_is_flagged(self) -> None:
        record = self.ctx.get_evidence("kb:kb.formula.synthetic_sum")["record"]
        self.assertEqual(record["category"], "B")
        self.assertEqual(record["eligibility"]["retrieval"], "eligible:unreviewed_reference_labelled_normative_not_verified")
        self.assertEqual(record["trust"]["evidence_status"], "NORMATIVE")
        self.assertFalse(record["expression"]["executed"])
        self.assertTrue(record["eligibility"]["binding"].startswith("blocked:"))

    def test_disputed_conflict_is_category_d(self) -> None:
        record = self.ctx.get_evidence("kb:kb.conflict.kc_synth")["record"]
        self.assertEqual(record["category"], "D")
        self.assertIn("evidence_disputed", record["eligibility"]["finetune"])

    def test_proposal_stays_a_proposal_and_does_not_replace_the_entry(self) -> None:
        proposal = self.ctx.get_evidence("proposal:proposal:1")
        self.assertTrue(proposal["found"])
        self.assertEqual(proposal["record"]["category"], "D")
        self.assertTrue(proposal["record"]["proposal_status"].startswith("unmerged:"))
        self.assertEqual(proposal["record"]["eligibility"]["retrieval"],
                         "eligible:proposed_or_disputed_do_not_present_as_accepted")
        entry = self.ctx.get_evidence("kb.component.box_barrel")["record"]
        self.assertEqual(entry["trust"]["review_state"], "seed_unreviewed")
        self.assertEqual(entry["statement"], "The barrel of a box culvert.")

    def test_search_keeps_labels_and_filters_by_category(self) -> None:
        hits = self.ctx.search_knowledge("box barrel", categories={"C", "B"})
        self.assertTrue(hits)
        for hit in hits:
            self.assertIn(hit["category"], {"B", "C"})
            self.assertIn("review_state", hit["trust"])
            self.assertIn("retrieval", hit["eligibility"])
        only_d = self.ctx.search_knowledge("disputed conflict", categories={"D"})
        self.assertTrue(all(h["category"] == "D" for h in only_d))

    def test_issue_ids_resolve_through_get_evidence(self) -> None:
        issue_id = next(i for i in self.ctx.store.issues if i.startswith("issue:failed_check:"))
        result = self.ctx.get_evidence(issue_id)
        self.assertTrue(result["found"])
        self.assertEqual(result["kind"], "issue")
        self.assertEqual(result["record"]["severity"], "warning")

    def test_unknown_evidence_id_is_reported_not_guessed(self) -> None:
        self.assertFalse(self.ctx.get_evidence("zzzz#nothing")["found"])
        self.assertFalse(self.ctx.get_evidence("kb:kb.missing")["found"])

    # --- vector corpus ----------------------------------------------------------------------------------------------
    def test_vector_text_is_an_observation_with_page_geometry(self) -> None:
        record = self.obs(VECTOR, "T1")
        self.assertEqual(record["obs_kind"], "vector_text")
        self.assertEqual(record["geometry"]["space"], "page_pt")
        self.assertEqual(record["trust"]["label_source"], "observed_vector")

    def test_empty_vector_span_is_not_retrievable(self) -> None:
        self.assertEqual(self.obs(VECTOR, "T2")["eligibility"]["retrieval"], "blocked:no_text")

    # --- packs ------------------------------------------------------------------------------------------------------
    def test_pack_claims_cite_stored_evidence_and_validate(self) -> None:
        pack = self.ctx.build_evidence_pack(SHEET_GROUNDED, "dimension_binding", write=False)
        report = self.ctx.validate_evidence_pack(pack)
        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(pack["claims"])
        for claim in pack["claims"]:
            self.assertTrue(claim["evidence_ids"])
            self.assertTrue(claim["source_ids"])
        for item in pack["candidate_interpretations"]:
            self.assertEqual(item["binding"]["status"], "blocked")
            self.assertTrue(item["binding"]["reasons"])

    def test_ungrounded_pack_has_no_fabricated_content(self) -> None:
        pack = self.ctx.build_evidence_pack(SHEET_UNGROUNDED, "geometric_relationships", write=False)
        self.assertEqual(pack["completeness"]["status"], "limited_ungrounded")
        self.assertEqual(pack["claims"], [])
        self.assertEqual(pack["candidate_interpretations"], [])
        self.assertTrue(self.ctx.validate_evidence_pack(pack)["valid"])

    def test_partial_pack_lists_missing_sections(self) -> None:
        pack = self.ctx.build_evidence_pack(SHEET_PARTIAL, "geometric_relationships", write=False)
        self.assertEqual(pack["completeness"]["status"], "partially_grounded")
        self.assertTrue(any("empty" in m or m in ("views", "dimension_text", "parts", "levels")
                            for m in pack["completeness"]["missing"]))

    def test_no_cad_snapshot_means_unavailable_and_no_entity_ids(self) -> None:
        pack = self.ctx.build_evidence_pack(SHEET_GROUNDED, "geometric_relationships", write=False)
        self.assertEqual(pack["live_cad_binding"]["status"], "unavailable")
        self.assertNotIn("cad_entity_id", json.dumps(pack))
        self.assertTrue(self.ctx.validate_evidence_pack(pack)["valid"])

    def test_cad_snapshot_is_echoed_not_invented(self) -> None:
        snapshot = self.tmp / "snapshot.json"
        snapshot.write_text(json.dumps({
            "snapshot_id": "snap-1", "document_version": "v7",
            "entities": [{"entity_id": "E1", "kind": "line", "locked": False}],
            "mappings": [{"evidence_id": f"{SHEET_GROUNDED}#D1", "entity_id": "E1"},
                         {"evidence_id": f"{SHEET_GROUNDED}#D2", "entity_id": "E9"}],
        }))
        pack = self.ctx.build_evidence_pack(SHEET_GROUNDED, "geometric_relationships", cad_snapshot=snapshot, write=False)
        self.assertEqual(pack["live_cad_binding"]["status"], "available")
        self.assertEqual([m["entity_id"] for m in pack["live_cad_binding"]["mappings"]], ["E1"])
        self.assertEqual([m["entity_id"] for m in pack["live_cad_binding"]["unmapped_mappings"]], ["E9"])
        self.assertEqual(self.ctx.validate_evidence_pack(pack)["valid"], True)

    def test_invalid_cad_snapshot_is_refused_not_used(self) -> None:
        snapshot = self.tmp / "bad_snapshot.json"
        snapshot.write_text(json.dumps({"snapshot_id": "snap-2", "entities": []}))
        pack = self.ctx.build_evidence_pack(SHEET_GROUNDED, "geometric_relationships", cad_snapshot=snapshot, write=False)
        self.assertEqual(pack["live_cad_binding"]["status"], "invalid")
        self.assertIsNone(pack["live_cad_binding"]["snapshot"])

    def test_tampered_pack_is_rejected(self) -> None:
        pack = self.ctx.build_evidence_pack(SHEET_GROUNDED, "dimension_binding", write=False)
        bad = json.loads(json.dumps(pack))
        bad["candidate_interpretations"][0]["binding"]["status"] = "bound"
        self.assertIn("binding_allowed", {e["rule"] for e in self.ctx.validate_evidence_pack(bad)["errors"]})
        edited = json.loads(json.dumps(pack))
        edited["claims"][0]["statement"] = "a different statement"
        self.assertIn("pack_id", {e["rule"] for e in self.ctx.validate_evidence_pack(edited)["errors"]})

    def test_ungrounded_pack_with_injected_dimension_is_rejected(self) -> None:
        pack = self.ctx.build_evidence_pack(SHEET_UNGROUNDED, "source_evidence", write=False)
        bad = json.loads(json.dumps(pack))
        bad["observations"] = {"dimensions": [{
            "evidence_id": f"{SHEET_GROUNDED}#D1", "obs_kind": "dimension", "trust": {}, "eligibility": {}}]}
        rules = {e["rule"] for e in self.ctx.validate_evidence_pack(bad)["errors"]}
        self.assertIn("ungrounded_fabrication", rules)

    def test_changed_source_makes_a_pack_stale(self) -> None:
        pack = self.ctx.build_evidence_pack(SHEET_GROUNDED, "dimension_binding", write=False)
        grounding = self.root / "bridges" / "rcc_box" / BRIDGE / "sheets" / SHEET_GROUNDED / "grounding" / "agent-grounding.json"
        original = grounding.read_text(encoding="utf-8")
        try:
            grounding.write_text(original + "\n", encoding="utf-8")
            report = self.ctx.validate_evidence_pack(pack)
            self.assertIn("changed_since_build", {e["rule"] for e in report["errors"]})
            self.assertTrue(self.ctx.check()["registry_stale"])
        finally:
            grounding.write_text(original, encoding="utf-8")
        self.assertFalse(self.ctx.check()["registry_stale"])

    def test_unknown_task_and_non_source_record_are_refused(self) -> None:
        from agentctx.packs import PackError

        with self.assertRaises(PackError):
            self.ctx.build_evidence_pack(SHEET_GROUNDED, "make_it_up", write=False)
        with self.assertRaises(PackError):
            self.ctx.build_evidence_pack("nope", "source_evidence", write=False)


if __name__ == "__main__":
    unittest.main()
