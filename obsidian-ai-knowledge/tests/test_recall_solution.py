from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from recall_solution import recall_solutions, render_recall  # noqa: E402


KNOWLEDGE_ROOT = "00-AI知识库"


class RecallSolutionTests(unittest.TestCase):
    def make_vault(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        system = vault / KNOWLEDGE_ROOT / "_系统"
        system.mkdir(parents=True)
        (system / "config.yaml").write_text(
            f"schema_version: 2\nknowledge_root: {KNOWLEDGE_ROOT}\nexcluded_directories: [模板, _系统, 项目空间]\n",
            encoding="utf-8",
        )
        return vault

    def write(self, vault: Path, relative: str, content: str) -> None:
        path = vault / KNOWLEDGE_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_solved_problem_ranks_above_session(self) -> None:
        vault = self.make_vault()
        common = (
            "---\nschema_version: 2\nrecord_type: {kind}\nrecord_id: {record_id}\nstatus: {status}\n"
            "created: 2026-08-07\nupdated: 2026-08-07\nproject: Demo\narea: test\n"
            "review_state: reviewed\nconfidence: high\nsource: test\ntags: [encoding]\n"
        )
        self.write(
            vault,
            "问题/2026/encoding.md",
            common.format(kind="problem", record_id="problem-encoding", status="solved")
            + "root_cause: PowerShell encoding\nsolution_type: fix\nreusable: true\noccurrences: 2\n"
            + "source_session: test\n---\n# 中文配置变成问号\n\n根因是跨进程编码。\n",
        )
        self.write(
            vault,
            "会话/2026/session.md",
            common.format(kind="session", record_id="session-encoding", status="completed")
            + "outcome: success\ncompleted_at: 2026-08-07\nai_tool: codex\nworkspace: test\n"
            + "knowledge_value: high\nsummary_kind: change\nvalidation_state: passed\n---\n# 修复编码\n\nPowerShell encoding fix.\n",
        )
        results = recall_solutions(vault, "PowerShell encoding 中文配置", limit=5)
        self.assertEqual(results[0]["record_id"], "problem-encoding")
        self.assertEqual(results[0]["trust_state"], "trusted")

    def test_recall_output_separates_unverified_clues(self) -> None:
        vault = self.make_vault()
        self.write(
            vault,
            "会话/2026/pending.md",
            "---\nschema_version: 2\nrecord_type: session\nrecord_id: session-pending\nstatus: completed\n"
            "outcome: partial\ncreated: 2026-08-07\nupdated: 2026-08-07\ncompleted_at: 2026-08-07\n"
            "area: test\nai_tool: codex\nworkspace: test\nknowledge_value: medium\nsource: test\n"
            "review_state: pending\nconfidence: low\nsummary_kind: change\ntags: [encoding]\n---\n"
            "# Encoding clue\n\n尚未验证 PowerShell encoding。\n",
        )
        results = recall_solutions(vault, "PowerShell encoding", limit=5)
        rendered = render_recall("PowerShell encoding", results)
        self.assertIn("待核对线索", rendered)
        self.assertIn("unverified", rendered)


if __name__ == "__main__":
    unittest.main()