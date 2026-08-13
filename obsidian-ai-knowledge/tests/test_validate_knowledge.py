from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from validate_knowledge import validate_vault  # noqa: E402
from common import extract_wikilinks  # noqa: E402


PROJECT_BODY = """
# Project

## 目标
## 当前状态
## 关键决策
## 已完成
## 当前风险
## 下一步
## 关联记录
"""


def project_note(record_id: str, extra: str = "") -> str:
    frontmatter = f"""---
schema_version: 2
record_type: project
record_id: {record_id}
status: active
priority: high
created: 2026-08-04
updated: 2026-08-04
area: tests
source: test
review_state: reviewed
confidence: high
next_action: verify
project_type: general
project_space: "[[00-AI知识库/项目空间/Project/00 - 项目驾驶舱]]"
context_note: "[[00-AI知识库/项目空间/Project/07 - AI启动上下文]]"
risk_log: "[[00-AI知识库/项目空间/Project/08 - 风险假设与依赖]]"
event_log: "[[00-AI知识库/项目空间/Project/09 - 项目事件日志]]"
freshness_note: "[[00-AI知识库/项目空间/Project/10 - 知识新鲜度与归档]]"
retrieval_note: "[[00-AI知识库/项目空间/Project/11 - 总结分类与调取]]"
last_reviewed: 2026-08-05
review_due: 2026-08-19
tags:
  - test
{extra}---
"""
    return frontmatter + textwrap.dedent(PROJECT_BODY)


class ValidateKnowledgeTests(unittest.TestCase):
    def make_vault(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        system = vault / "00-AI知识库" / "_系统"
        system.mkdir(parents=True)
        (system / "config.yaml").write_text(
            "schema_version: 2\nknowledge_root: 00-AI知识库\n",
            encoding="utf-8",
        )
        return vault

    def test_valid_project_has_no_errors(self) -> None:
        vault = self.make_vault()
        project = vault / "00-AI知识库" / "项目" / "Project.md"
        project.parent.mkdir(parents=True)
        project.write_text(project_note("project-test"), encoding="utf-8")
        result = validate_vault(vault)
        self.assertEqual([], result["errors"])

    def test_duplicate_record_id_is_error(self) -> None:
        vault = self.make_vault()
        projects = vault / "00-AI知识库" / "项目"
        projects.mkdir(parents=True)
        (projects / "One.md").write_text(project_note("project-duplicate"), encoding="utf-8")
        (projects / "Two.md").write_text(project_note("project-duplicate"), encoding="utf-8")
        result = validate_vault(vault)
        self.assertIn("duplicate record_id: project-duplicate", result["errors"])

    def test_mojibake_is_error(self) -> None:
        vault = self.make_vault()
        project = vault / "00-AI知识库" / "项目" / "Project.md"
        project.parent.mkdir(parents=True)
        project.write_text(project_note("project-mojibake") + "\n姝ir\n", encoding="utf-8")
        result = validate_vault(vault)
        self.assertTrue(any("mojibake" in error for error in result["errors"]))

    def test_wikilinks_inside_code_are_ignored(self) -> None:
        text = "real [[Target]] and `[[InlineExample]]`\n```md\n[[FenceExample]]\n```"
        self.assertEqual(["Target"], extract_wikilinks(text))


if __name__ == "__main__":
    unittest.main()
