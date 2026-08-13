from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from health_report import refresh_report, run_health, save_report  # noqa: E402


def note(record_type: str, **values: object) -> str:
    metadata = {
        "schema_version": 2,
        "record_type": record_type,
        "record_id": f"{record_type}-test",
        "status": "active" if record_type != "inbox" else "pending",
        "created": "2026-07-01",
        "updated": "2026-07-01",
        "review_state": "reviewed" if record_type != "inbox" else "pending",
        "confidence": "high" if record_type != "inbox" else "low",
        "source": "codex",
        **values,
    }
    frontmatter = ["---", *(f"{key}: {value}" for key, value in metadata.items()), "---", ""]
    return "\n".join(frontmatter) + "# Test\n\nShort.\n"


class HealthReportTests(unittest.TestCase):
    def make_vault(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        system = vault / "00-AI知识库" / "_系统"
        system.mkdir(parents=True)
        (system / "config.yaml").write_text(
            "schema_version: 2\n"
            "knowledge_root: 00-AI知识库\n"
            "quality:\n"
            "  inbox_review_days: 7\n"
            "  open_problem_review_days: 30\n"
            "  recent_session_days: 14\n"
            "  stub_body_chars: 120\n",
            encoding="utf-8",
        )
        return vault

    def write_record(self, vault: Path, folder: str, name: str, content: str) -> None:
        path = vault / "00-AI知识库" / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_detects_stale_items_stubs_and_sources(self) -> None:
        vault = self.make_vault()
        self.write_record(vault, "Inbox", "Inbox.md", note("inbox"))
        self.write_record(
            vault,
            "问题",
            "Problem.md",
            note("problem", status="open", review_state="reviewed", confidence="high", source="claude"),
        )

        result = run_health(vault, today=date(2026, 8, 4))

        self.assertEqual(1, len(result["issues"]["stale_inbox"]))
        self.assertEqual(1, len(result["issues"]["stale_problems"]))
        self.assertEqual(2, len(result["issues"]["stubs"]))
        self.assertEqual({"claude": 1, "codex": 1}, result["counts"]["source"])

    def test_detects_overdue_project_review(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "项目",
            "Project.md",
            note("project", status="active", next_action="ship", review_due="2026-08-01"),
        )

        result = run_health(vault, today=date(2026, 8, 5))

        self.assertEqual(1, len(result["issues"]["overdue_project_reviews"]))
        self.assertEqual(4, result["issues"]["overdue_project_reviews"][0]["overdue_days"])

    def test_detects_stale_and_unknown_project_sources(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "项目",
            "Stale.md",
            note("project", status="active", next_action="review", freshness_state="stale"),
        )
        self.write_record(
            vault,
            "项目",
            "Unknown.md",
            note("project", status="active", next_action="scan"),
        )

        result = run_health(vault, today=date(2026, 8, 5))

        self.assertEqual(1, len(result["issues"]["stale_project_sources"]))
        self.assertEqual(1, len(result["issues"]["unknown_project_sources"]))
    def test_recent_session_avoids_capture_gap(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "会话",
            "Session.md",
            note("session", status="completed", completed_at="2026-08-03", ai_tool="codex"),
        )

        result = run_health(vault, today=date(2026, 8, 4))

        self.assertFalse(result["recent_session_gap"])
        self.assertEqual(1, result["session_gap_days"])
        self.assertEqual({"codex": 1}, result["counts"]["ai_tool"])

    def test_save_report_is_idempotent(self) -> None:
        vault = self.make_vault()
        result = run_health(vault, today=date(2026, 8, 4))

        path, first_changed = save_report(vault, result)
        _, second_changed = save_report(vault, result)

        self.assertTrue(first_changed)
        self.assertFalse(second_changed)
        self.assertIn("# 知识库健康报告", path.read_text(encoding="utf-8"))

    def test_refresh_report_rechecks_new_link_target(self) -> None:
        vault = self.make_vault()
        dashboard = vault / "00-AI知识库" / "00 - Dashboard.md"
        dashboard.write_text(
            "---\nrecord_type: dashboard\n---\n\n"
            "# Dashboard\n\n[[00-AI知识库/_系统/知识库健康报告]]\n",
            encoding="utf-8",
        )
        self.assertEqual(1, len(run_health(vault, today=date(2026, 8, 4))["validation"]["warnings"]))

        result, path, changed = refresh_report(vault, today=date(2026, 8, 4))

        self.assertTrue(changed)
        self.assertEqual([], result["validation"]["warnings"])
        self.assertIn("- Warnings：0", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
