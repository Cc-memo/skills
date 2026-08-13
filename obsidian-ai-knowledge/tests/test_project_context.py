from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from project_context import build_context  # noqa: E402


KNOWLEDGE_ROOT = "00-AI\u77e5\u8bc6\u5e93"
SYSTEM_DIR = "_\u7cfb\u7edf"
PROJECT_DIR = "\u9879\u76ee"
PROJECT_SPACE = "\u9879\u76ee\u7a7a\u95f4"
SESSION_DIR = "\u4f1a\u8bdd"
PROBLEM_DIR = "\u95ee\u9898"


class ProjectContextTests(unittest.TestCase):
    def make_vault(self, freshness: str = "current") -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        system = vault / KNOWLEDGE_ROOT / SYSTEM_DIR
        system.mkdir(parents=True)
        (system / "config.yaml").write_text(
            f"schema_version: 2\nknowledge_root: {KNOWLEDGE_ROOT}\nexcluded_directories: [{SYSTEM_DIR}, {PROJECT_SPACE}]\n",
            encoding="utf-8",
        )
        project = vault / KNOWLEDGE_ROOT / PROJECT_DIR / "Demo.md"
        project.parent.mkdir(parents=True)
        project.write_text(
            "---\nschema_version: 2\nrecord_type: project\nrecord_id: project-demo\nstatus: active\n"
            "priority: high\ncreated: 2026-08-05\nupdated: 2026-08-05\narea: test\nsource: test\n"
            "review_state: reviewed\nconfidence: high\nnext_action: Continue implementation\nproject_type: software\n"
            f'project_space: "[[{KNOWLEDGE_ROOT}/{PROJECT_SPACE}/Demo/00 - Dashboard]]"\n'
            f"freshness_state: {freshness}\nlast_reviewed: 2026-08-05\nreview_due: 2026-08-19\ntags: [test]\n"
            "---\n\n# Demo\n\n## Goal\n\nBuild safely.\n\n## Current status\n\nActive.\n",
            encoding="utf-8",
        )
        space = vault / KNOWLEDGE_ROOT / PROJECT_SPACE / "Demo"
        space.mkdir(parents=True)
        for filename, body in {
            "07 - AI Startup Context.md": "# Startup\n\nRead risks.",
            "01 - Stage Summary.md": "# Summary\n\nCurrent work.",
            "08 - Risks.md": "# Risks\n\nDependency risk.",
            "09 - Events.md": "# Events\n\nLatest milestone.",
            "10 - Freshness.md": "# Freshness\n\nReview source.",
            "02 - Problems.md": "# Problems\n\nOpen issues.",
        }.items():
            (space / filename).write_text(body, encoding="utf-8")
        session = vault / KNOWLEDGE_ROOT / SESSION_DIR / "2026" / "2026-08-05 - Session.md"
        session.parent.mkdir(parents=True)
        session.write_text(
            f'---\nschema_version: 2\nrecord_type: session\nrecord_id: session-demo\nstatus: completed\noutcome: success\ncreated: 2026-08-05\nupdated: 2026-08-05\ncompleted_at: 2026-08-05\nproject: "[[{KNOWLEDGE_ROOT}/{PROJECT_DIR}/Demo]]"\narea: test\nai_tool: codex\nworkspace: test\nknowledge_value: high\nsource: test\nreview_state: reviewed\nconfidence: high\nsummary_kind: change\ntags: [test]\n---\n\n# Session\n\nImplemented feature.\n',
            encoding="utf-8",
        )
        problem = vault / KNOWLEDGE_ROOT / PROBLEM_DIR / "2026" / "2026-08-05 - Problem.md"
        problem.parent.mkdir(parents=True)
        problem.write_text(
            f'---\nschema_version: 2\nrecord_type: problem\nrecord_id: problem-demo\nstatus: open\nseverity: high\ncreated: 2026-08-05\nupdated: 2026-08-05\nproject: "[[{KNOWLEDGE_ROOT}/{PROJECT_DIR}/Demo]]"\narea: test\nroot_cause: unknown\nsolution_type: pending\nreusable: false\noccurrences: 1\nsource_session: "[[Session]]"\nsource: test\nreview_state: reviewed\nconfidence: medium\ntags: [test]\n---\n\n# Blocking Problem\n\nMust solve first.\n',
            encoding="utf-8",
        )
        return vault

    def test_debugging_prioritizes_open_problem_and_obeys_budget(self) -> None:
        vault = self.make_vault()
        result = build_context(vault, "Demo", focus="debugging", max_chars=3000, recent_sessions=2)
        text = (vault / result["output"]).read_text(encoding="utf-8")

        self.assertLessEqual(len(text), 3000)
        self.assertIn("Blocking Problem", text)
        self.assertNotIn("Implemented feature", text)

    def test_stale_warning_is_at_top(self) -> None:
        vault = self.make_vault(freshness="stale")
        result = build_context(vault, "Demo", focus="handoff", max_chars=5000)
        text = (vault / result["output"]).read_text(encoding="utf-8")

        self.assertIn("source_freshness: stale", text)
        self.assertLess(text.index("来源已变化"), text.index("## 项目档案"))

    def test_superseded_session_is_excluded_from_context(self) -> None:
        vault = self.make_vault()
        session = vault / KNOWLEDGE_ROOT / SESSION_DIR / "2026" / "2026-08-06 - Old.md"
        session.write_text(
            f'---\nschema_version: 2\nrecord_type: session\nrecord_id: session-old\nstatus: completed\n'
            'outcome: success\ncreated: 2026-08-06\nupdated: 2026-08-06\ncompleted_at: 2026-08-06\n'
            f'project: "[[{KNOWLEDGE_ROOT}/{PROJECT_DIR}/Demo]]"\narea: test\nai_tool: codex\nworkspace: test\n'
            'knowledge_value: high\nsource: test\nreview_state: reviewed\nconfidence: high\nsummary_kind: change\n'
            'superseded_by: "[[Replacement]]"\ntags: [test]\n---\n\n# Superseded implementation\n\nDo not reuse this.\n',
            encoding="utf-8",
        )
        result = build_context(vault, "Demo", focus="status", max_chars=8000, recent_sessions=5)
        text = (vault / result["output"]).read_text(encoding="utf-8")

        self.assertNotIn("Superseded implementation", text)
        self.assertIn("Implemented feature", text)
    def test_status_focus_includes_recent_session(self) -> None:
        vault = self.make_vault()
        result = build_context(vault, "Demo", focus="status", max_chars=8000)
        text = (vault / result["output"]).read_text(encoding="utf-8")

        self.assertIn("Implemented feature", text)
        self.assertNotIn("Blocking Problem", text)


if __name__ == "__main__":
    unittest.main()
