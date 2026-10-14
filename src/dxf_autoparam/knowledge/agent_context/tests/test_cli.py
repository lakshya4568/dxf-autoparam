"""The command-line wrapper, run on the synthetic repository (tests only)."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from fixtures import SHEET_GROUNDED, SHEET_UNGROUNDED, make_repository  # noqa: E402

from agentctx.cli import main  # noqa: E402


def run(args: list[str]) -> tuple[int, object]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(args)
    text = out.getvalue().strip()
    return code, (json.loads(text) if text else None)


class CommandLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = make_repository(Path(cls._tmp.name))
        cls.r = ["--root", str(cls.root)]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_build_then_status_search_evidence(self) -> None:
        code, built = run(self.r + ["build"])
        self.assertEqual(code, 0)
        self.assertEqual(built["problems"], [])
        code, status = run(self.r + ["status", SHEET_GROUNDED])
        self.assertEqual(code, 0)
        self.assertEqual(status["completeness"]["capability"], "grounded_needs_review")
        code, hits = run(self.r + ["search", "box", "barrel", "--category", "C"])
        self.assertEqual(code, 0)
        self.assertTrue(all(h["category"] == "C" for h in hits))
        code, found = run(self.r + ["evidence", f"{SHEET_GROUNDED}#D1"])
        self.assertEqual(code, 0)
        self.assertTrue(found["found"])
        code, missing = run(self.r + ["evidence", "nothing#here"])
        self.assertEqual(code, 1)
        self.assertFalse(missing["found"])

    def test_pack_without_writing_and_validation_file(self) -> None:
        code, summary = run(self.r + ["pack", SHEET_UNGROUNDED, "--task", "source_evidence", "--no-write"])
        self.assertEqual(code, 0)
        self.assertEqual(summary["completeness"], "limited_ungrounded")
        self.assertIsNone(summary["written_to"])
        code, pack = run(self.r + ["pack", SHEET_GROUNDED, "--task", "dimension_binding", "--print"])
        path = self.root / "agent-context" / "packs" / f"{pack['pack_id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(pack), encoding="utf-8")
        code, report = run(self.r + ["validate", str(path)])
        self.assertEqual(code, 0)
        self.assertTrue(report["valid"], report["errors"])

    def test_check_reports_and_pack_task_list(self) -> None:
        code, report = run(self.r + ["check"])
        self.assertIn("registry_inputs", report)
        code, tasks = run(self.r + ["tasks"])
        self.assertIn("dimension_binding", tasks)

    def test_unknown_pack_task_is_an_argument_error(self) -> None:
        from contextlib import redirect_stderr

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(self.r + ["pack", SHEET_GROUNDED, "--task", "guess"])


if __name__ == "__main__":
    unittest.main()
