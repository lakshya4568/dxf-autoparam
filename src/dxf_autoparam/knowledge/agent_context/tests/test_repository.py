"""Tests against the real repository. Builds into a temporary folder, so the committed outputs are not touched."""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from agentctx import Context  # noqa: E402
from agentctx.common import DEFAULT_ROOT, sha256_file  # noqa: E402
from agentctx.demo import run_demo  # noqa: E402
from agentctx.registry import collect_input_hashes  # noqa: E402

REAL = Path(DEFAULT_ROOT).resolve()


class RealRepository(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.context_dir = cls.tmp / "agent-context"
        cls.context_dir.mkdir()
        shutil.copytree(REAL / "agent-context" / "schemas", cls.context_dir / "schemas")
        cls.before = collect_input_hashes(REAL)
        cls.ctx = Context(root=REAL, context_dir=cls.context_dir)
        cls.summary = cls.ctx.build_registry()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_build_reports_no_problems_and_counts_match_the_corpus(self) -> None:
        self.assertEqual(self.summary["problems"], [])
        kinds = self.summary["counts"]["source_kinds"]
        self.assertEqual(kinds["drawing_sheet"], 707)
        self.assertEqual(kinds["grounding"], 17)
        self.assertEqual(kinds["vector_sheet"], 53)
        self.assertEqual(kinds["rdso_page"], 150)
        self.assertEqual(kinds["rdso_extract"], 27)
        self.assertEqual(kinds["bridge"], 700)

    def test_build_did_not_modify_any_repository_input(self) -> None:
        self.assertEqual(self.before, collect_input_hashes(REAL))

    def test_rdso_pages_saved_match_the_disk(self) -> None:
        store = self.ctx.store
        saved = [s for s in store.sources.values() if s["kind"] == "rdso_page"
                 and s["completeness"]["saved"]]
        self.assertEqual(len(saved), 134)

    def test_nothing_is_eligible_for_binding_or_fine_tuning(self) -> None:
        counts = self.summary["counts"]["eligibility"]
        self.assertEqual(counts["binding"].get("eligible", 0), 0)
        self.assertEqual(counts["finetune"].get("eligible", 0), 0)
        self.assertGreater(counts["retrieval"].get("eligible", 0), 0)

    def test_vector_text_observations_equal_the_text_layers(self) -> None:
        store = self.ctx.store
        spans = sum(int(s["completeness"]["text_spans"]) for s in store.sources.values()
                    if s["kind"] == "vector_sheet")
        observed = sum(1 for o in store.observations.values() if o["obs_kind"] == "vector_text")
        self.assertEqual(spans, observed)

    def test_grounded_sheet_observations_match_its_grounding_file(self) -> None:
        status = self.ctx.get_source_status("21cc08a32dd8-p1")
        self.assertEqual(status["observations"]["dimension"], 92)
        self.assertEqual(status["observations"]["dispute"], 4)
        self.assertEqual(status["completeness"]["capability"], "grounded_needs_review")

    def test_missing_crops_and_unclear_readings_are_reported_from_real_files(self) -> None:
        pages = [s for s in self.ctx.store.sources.values() if s["kind"] == "rdso_page"]
        total_missing = sum(int(p["completeness"]["crops_missing"] or 0) for p in pages)
        self.assertGreaterEqual(total_missing, 0)
        self.assertTrue(all(isinstance(p["completeness"]["crops_opened"], int) for p in pages if p["completeness"]["saved"]))

    def test_demo_packs_are_valid_and_cover_the_real_completeness_states(self) -> None:
        result = run_demo(self.ctx)
        self.assertTrue(result["valid"], result)
        states = {p["completeness"] for p in result["packs"] if "completeness" in p}
        for expected in ("limited_ungrounded", "grounded_unverified", "page_saved_unverified", "not_saved",
                         "vector_text_observed", "partially_grounded"):
            self.assertIn(expected, states)
        self.assertTrue(all(p["live_cad_binding"] == "unavailable" for p in result["packs"] if "live_cad_binding" in p))

    def test_check_on_a_fresh_build_reports_no_stale_inputs(self) -> None:
        report = self.ctx.check()
        self.assertFalse(report["registry_stale"])
        self.assertEqual(report["broken_source_paths"], [])
        self.assertTrue(all(p["valid"] for p in report["packs"]))

    def test_sampled_observations_match_their_schema(self) -> None:
        import json

        import jsonschema

        schema = json.loads((self.context_dir / "schemas" / "observation.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        rows = list(self.ctx.store.observations.values())
        step = max(1, len(rows) // 400)
        for row in rows[::step]:
            errors = list(validator.iter_errors(row))
            self.assertEqual(errors, [], row["evidence_id"])

    def test_rebuild_is_byte_identical(self) -> None:
        second = self.tmp / "second"
        second.mkdir()
        shutil.copytree(REAL / "agent-context" / "schemas", second / "schemas")
        Context(root=REAL, context_dir=second).build_registry()
        for name in ("registry/sources.jsonl", "registry/observations.jsonl", "knowledge/knowledge.jsonl"):
            self.assertEqual(sha256_file(self.context_dir / name), sha256_file(second / name), name)

    def test_cli_status_and_search_work_on_the_real_registry(self) -> None:
        from agentctx.cli import main

        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--root", str(REAL), "status", "21cc08a32dd8-p1"])
        self.assertEqual(code, 0)
        self.assertIn("grounded_needs_review", out.getvalue())


if __name__ == "__main__":
    unittest.main()
