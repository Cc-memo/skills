from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from project_space import ensure_project_space  # noqa: E402


PROJECT = """---
schema_version: 2
record_type: project
record_id: project-demo
status: active
priority: high
created: 2026-08-05
updated: 2026-08-05
area: tests
source: test
review_state: reviewed
confidence: high
next_action: verify
tags:
  - test
---

# Demo Project

## 目标

Build it.

## 当前状态

Active.

## 关键决策

## 已完成

## 当前风险

## 下一步

Verify.

## 关联记录
"""


class ProjectSpaceTests(unittest.TestCase):
    def make_vault(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        system = vault / "00-AI知识库" / "_系统"
        system.mkdir(parents=True)
        (system / "config.yaml").write_text(
            "schema_version: 2\n"
            "knowledge_root: 00-AI知识库\n"
            "excluded_directories:\n"
            "  - 模板\n"
            "  - _系统\n"
            "  - 项目空间\n"
            "record_directories:\n"
            "  project: 项目\n",
            encoding="utf-8",
        )
        project = vault / "00-AI知识库" / "项目" / "Demo Project.md"
        project.parent.mkdir(parents=True)
        project.write_text(PROJECT, encoding="utf-8")
        return vault

    def test_creates_project_space_and_updates_project_note(self) -> None:
        vault = self.make_vault()
        result = ensure_project_space(vault, "Demo Project", project_kind="software", today=date(2026, 8, 5))

        self.assertEqual("00-AI知识库\\项目空间\\Demo Project", result["project_space"])
        self.assertEqual(13, len(result["created"]))
        folder = vault / result["project_space"]
        self.assertTrue((folder / "00 - 项目驾驶舱.md").exists())
        self.assertTrue((folder / "06 - 架构版本与测试.md").exists())
        self.assertTrue((folder / "07 - AI启动上下文.md").exists())
        self.assertTrue((folder / "08 - 风险假设与依赖.md").exists())
        self.assertTrue((folder / "09 - 项目事件日志.md").exists())
        self.assertTrue((folder / "10 - 知识新鲜度与归档.md").exists())
        self.assertTrue((folder / "11 - 总结分类与调取.md").exists())
        self.assertIn('file.hasLink("Demo Project")', (folder / "项目记录.base").read_text(encoding="utf-8"))
        project_text = (vault / "00-AI知识库" / "项目" / "Demo Project.md").read_text(encoding="utf-8")
        self.assertIn("project_type: software", project_text)
        self.assertIn("project_space:", project_text)
        self.assertIn("context_note:", project_text)
        self.assertIn("risk_log:", project_text)
        self.assertIn("event_log:", project_text)
        self.assertIn("freshness_note:", project_text)
        self.assertIn("retrieval_note:", project_text)
        self.assertIn("last_reviewed: 2026-08-05", project_text)
        self.assertIn("review_due: 2026-08-19", project_text)
        self.assertIn("## 项目空间", project_text)

    def test_repairs_missing_links_in_existing_project_space_section(self) -> None:
        vault = self.make_vault()
        project = vault / "00-AI知识库" / "项目" / "Demo Project.md"
        content = project.read_text(encoding="utf-8")
        content = content.replace("\n## 关联记录", "\n## 项目空间\n\n- [[legacy|旧入口]]\n\n## 关联记录")
        project.write_text(content, encoding="utf-8")

        ensure_project_space(vault, "Demo Project", project_kind="software", today=date(2026, 8, 5))
        ensure_project_space(vault, "Demo Project", project_kind="software", today=date(2026, 8, 5))

        project_text = project.read_text(encoding="utf-8")
        self.assertIn("[[legacy|旧入口]]", project_text)
        retrieval_link = "- [[00-AI知识库/项目空间/Demo Project/11 - 总结分类与调取|总结分类与调取]]"
        self.assertEqual(1, project_text.count(retrieval_link))
    def test_is_idempotent_for_generated_files(self) -> None:
        vault = self.make_vault()
        first = ensure_project_space(vault, "Demo Project", project_kind="software", today=date(2026, 8, 5))
        dashboard = vault / first["project_space"] / "00 - 项目驾驶舱.md"
        dashboard.write_text(dashboard.read_text(encoding="utf-8") + "\nManual note.\n", encoding="utf-8")

        second = ensure_project_space(vault, "Demo Project", project_kind="software", today=date(2026, 8, 5))

        self.assertEqual([], second["created"])
        self.assertIn("Manual note.", dashboard.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
