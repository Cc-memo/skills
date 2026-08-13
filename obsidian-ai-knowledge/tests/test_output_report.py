from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from output_report import analyze_vault, render_report  # noqa: E402


KNOWLEDGE_ROOT = "00-AI知识库"


class OutputReportTests(unittest.TestCase):
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

    def write_record(self, vault: Path, relative: str, content: str) -> Path:
        path = vault / KNOWLEDGE_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def session_frontmatter(self, record_id: str, *, kind: str = "change", extra: str = "") -> str:
        return (
            "---\n"
            "schema_version: 2\nrecord_type: session\n"
            f"record_id: {record_id}\nstatus: completed\noutcome: success\n"
            "created: 2026-08-07\nupdated: 2026-08-07\ncompleted_at: 2026-08-07\n"
            f'project: "[[{KNOWLEDGE_ROOT}/项目/Demo]]"\n'
            "area: test\nai_tool: codex\nworkspace: test\nknowledge_value: high\nsource: test\n"
            "review_state: reviewed\nconfidence: high\n"
            f"summary_kind: {kind}\n{extra}tags: [test]\n---\n"
        )

    def test_verified_delivery_requires_validation_and_evidence(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "会话/2026/verified.md",
            self.session_frontmatter("session-verified")
            + "# Verified\n\n## 变更文件\n\n- `app.py`\n\n## 验证结果\n\n- 12 tests passed\n",
        )
        analysis = analyze_vault(vault, today=date(2026, 8, 7))
        self.assertEqual(analysis["sessions"][0].category, "verified-delivery")
        self.assertEqual(analysis["sessions"][0].validation_state, "passed")

    def test_mixed_validation_is_not_misclassified_as_passed(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "会话/2026/partial.md",
            self.session_frontmatter("session-partial", extra="validation_state: passed\n")
            + "# Partial\n\n## 变更文件\n\n- `extension.js`\n\n## 验证结果\n\n- 单元测试通过。\n- 尚未进行真实页面验收。\n",
        )
        analysis = analyze_vault(vault, today=date(2026, 8, 7))
        item = analysis["sessions"][0]
        self.assertEqual(item.validation_state, "partial")
        self.assertEqual(item.category, "needs-validation")

    def test_domain_pending_state_does_not_cancel_passed_validation(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "会话/2026/domain-pending.md",
            self.session_frontmatter("session-domain-pending")
            + "# Domain pending\n\n## 变更文件\n\n- `app.py`\n\n## 验证结果\n\n- tests passed; 0 failed; 8 review decisions remain pending.\n",
        )
        analysis = analyze_vault(vault, today=date(2026, 8, 7))
        self.assertEqual(analysis["sessions"][0].validation_state, "passed")
        self.assertEqual(analysis["sessions"][0].category, "verified-delivery")
    def test_explicit_passed_is_not_cancelled_by_reporting_other_pending_items(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "会话/2026/report-count.md",
            self.session_frontmatter("session-report-count", extra="validation_state: passed\n")
            + "# Report count\n\n## 变更文件\n\n- `report.md`\n\n## 验证结果\n\n- tests passed.\n- 报告中仍有 1 条待验证记录。\n",
        )
        analysis = analyze_vault(vault, today=date(2026, 8, 7))
        self.assertEqual(analysis["sessions"][0].validation_state, "passed")
        self.assertEqual(analysis["sessions"][0].category, "verified-delivery")
    def test_passed_but_pending_record_requires_review_not_validation(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "会话/2026/pending-review.md",
            self.session_frontmatter("session-pending-review").replace("review_state: reviewed", "review_state: pending")
            + "# Pending review\n\n## 变更文件\n\n- `app.py`\n\n## 验证结果\n\n- tests passed\n",
        )
        analysis = analyze_vault(vault, today=date(2026, 8, 7))
        item = analysis["sessions"][0]
        self.assertEqual(item.validation_state, "passed")
        self.assertEqual(item.category, "needs-review")
    def test_research_output_uses_source_and_decisions(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "会话/2026/research.md",
            self.session_frontmatter("session-research", kind="research", extra="source_ref: github:example/repo@abc123\n")
            + "# Research\n\n## 关键决策\n\n- 不直接安装，复用确定性分类规则。\n",
        )
        analysis = analyze_vault(vault, today=date(2026, 8, 7))
        self.assertEqual(analysis["sessions"][0].category, "knowledge-output")

    def test_superseded_record_is_excluded_from_current_output(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "会话/2026/withdrawn.md",
            self.session_frontmatter(
                "session-withdrawn",
                extra=f'superseded_by: "[[{KNOWLEDGE_ROOT}/会话/2026/reverted]]"\n',
            )
            + "# Withdrawn\n\n## 变更文件\n\n- `capture.py`\n\n## 验证结果\n\n- tests passed\n",
        )
        analysis = analyze_vault(vault, today=date(2026, 8, 7))
        self.assertEqual(analysis["sessions"][0].category, "superseded")
        self.assertEqual(analysis["sessions"][0].score, 0)

    def test_project_risks_use_open_problem_freshness_and_next_action(self) -> None:
        vault = self.make_vault()
        self.write_record(
            vault,
            "项目/Demo.md",
            "---\nschema_version: 2\nrecord_type: project\nrecord_id: project-demo\nstatus: active\n"
            "priority: high\ncreated: 2026-08-07\nupdated: 2026-08-07\narea: test\nsource: test\n"
            "review_state: reviewed\nconfidence: high\nnext_action: ''\nproject_type: software\n"
            "project_space: ''\nfreshness_state: stale\ntags: [test]\n---\n# Demo\n",
        )
        self.write_record(
            vault,
            "问题/2026/open.md",
            f"---\nschema_version: 2\nrecord_type: problem\nrecord_id: problem-open\nstatus: open\nseverity: high\n"
            f"created: 2026-08-07\nupdated: 2026-08-07\nproject: \"[[{KNOWLEDGE_ROOT}/项目/Demo]]\"\n"
            "area: test\nroot_cause: unknown\nsolution_type: pending\nreusable: false\noccurrences: 1\n"
            "source_session: ''\nsource: test\nreview_state: reviewed\nconfidence: medium\ntags: [test]\n---\n# Open\n",
        )
        analysis = analyze_vault(vault, today=date(2026, 8, 7))
        risks = analysis["active_projects"][0]["risks"]
        self.assertIn("仓库基线已过期", risks)
        self.assertIn("缺少下一步", risks)
        self.assertIn("有 1 个未解决问题", risks)

    def test_rendered_report_explains_non_score_gates(self) -> None:
        vault = self.make_vault()
        report = render_report(vault, analyze_vault(vault, today=date(2026, 8, 7)))
        self.assertIn("不能靠高分替代", report)
        self.assertIn("规则分析不冒充模型判断", report)


if __name__ == "__main__":
    unittest.main()