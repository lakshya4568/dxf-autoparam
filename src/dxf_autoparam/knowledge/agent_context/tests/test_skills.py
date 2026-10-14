"""Every id, command and repository path an agent skill cites must resolve. Runs on the committed registry."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTEXT = HERE.parent
sys.path.insert(0, str(CONTEXT))

from agentctx import Context  # noqa: E402
from agentctx.common import DEFAULT_ROOT  # noqa: E402

COMMANDS = {"build", "status", "search", "evidence", "pack", "validate", "check", "tasks", "demo"}
RX_EVIDENCE = re.compile(r"\b[0-9a-f]{12}-p\d+#[A-Za-z0-9_:.\-]+")
RX_RECORD = re.compile(r"\b(?:v-)?[0-9a-f]{12}-p\d+\b")
RX_KB = re.compile(r"\bkb[:.][a-z_]+\.[A-Za-z0-9_.\-]+")
RX_ISSUE = re.compile(r"\bissue:[a-z_]+:[^\s`),;]+")
RX_RDSO = re.compile(r"\brdso:[A-Za-z0-9_.\-]+:p\d+(?:#[A-Za-z0-9_:.\-]+)?")
RX_CHUNK = re.compile(r"\bKB-BRIDGE-ENGINEERING-KNOWLEDGE-[A-Za-z0-9\-]+:p\d+:\d+")
RX_PATH = re.compile(r"`((?:knowledge|agent|catalog|ontology|reports|docs|tools|schemas|agent-context)/[^`\s]+)`")
RX_COMMAND = re.compile(r"ctx\.py\s+([a-z]+)")


def skill_files() -> list[Path]:
    return sorted((CONTEXT / "skills").rglob("SKILL.md"))


class SkillsCiteOnlyWhatResolves(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ctx = Context()
        cls.store = cls.ctx.store

    def _resolves(self, token: str) -> bool:
        store = self.store
        if "#" in token:
            return token in store.observations
        return (token in store.sources or token in store.knowledge or token in store.kb_by_kb_id
                or token in store.issues or ("kb:" + token) in store.knowledge
                or ("chunk:" + token) in store.knowledge)

    def test_skill_files_exist(self) -> None:
        self.assertGreaterEqual(len(skill_files()), 5)

    def test_every_frontmatter_has_name_and_description(self) -> None:
        for path in skill_files():
            head = path.read_text(encoding="utf-8").split("---")[1]
            self.assertIn("name:", head, path)
            self.assertIn("description:", head, path)

    def test_every_cited_command_exists(self) -> None:
        for path in skill_files():
            for command in RX_COMMAND.findall(path.read_text(encoding="utf-8")):
                self.assertIn(command, COMMANDS, f"{path.name} cites ctx.py {command}")

    def test_every_cited_id_resolves(self) -> None:
        missing: list[str] = []
        for path in skill_files():
            text = path.read_text(encoding="utf-8")
            tokens = set(RX_EVIDENCE.findall(text)) | set(RX_RECORD.findall(text)) | set(RX_KB.findall(text)) \
                | set(RX_ISSUE.findall(text)) | set(RX_RDSO.findall(text)) | set(RX_CHUNK.findall(text))
            for token in sorted(tokens):
                if token.startswith("kb.") and self._resolves("kb:" + token):
                    continue
                if token.startswith("kb:") and self._resolves(token[3:]):
                    continue
                if RX_CHUNK.fullmatch(token) and self._resolves("chunk:" + token):
                    continue
                if not self._resolves(token):
                    missing.append(f"{path.relative_to(CONTEXT)}: {token}")
        self.assertEqual(missing, [], "ids cited in skills that do not resolve")

    def test_every_cited_repository_path_exists(self) -> None:
        missing: list[str] = []
        for path in skill_files():
            for relpath in RX_PATH.findall(path.read_text(encoding="utf-8")):
                if any(mark in relpath for mark in ("*", "<", ">", "...")):
                    continue
                if not (Path(DEFAULT_ROOT) / relpath.rstrip("/")).exists():
                    missing.append(f"{path.relative_to(CONTEXT)}: {relpath}")
        self.assertEqual(missing, [], "paths cited in skills that do not exist")


if __name__ == "__main__":
    unittest.main()
