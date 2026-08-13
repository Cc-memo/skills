from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import split_frontmatter  # noqa: E402
from portable_check import export_skill, portability_issues  # noqa: E402
from update_problem import append_event, update_problem  # noqa: E402


class ProblemLifecycleTests(unittest.TestCase):
    def base_record(self) -> tuple[dict[str, object], str]:
        metadata: dict[str, object] = {
            "schema_version": 2,
            "record_type": "problem",
            "record_id": "problem-demo",
            "status": "investigating",
            "severity": "medium",
            "created": "2026-08-12",
            "updated": "2026-08-12",
            "project": "Demo",
            "area": "test",
            "root_cause": "",
            "solution_type": "",
            "reusable": False,
            "occurrences": 1,
            "source_session": "[[First]]",
            "source": "test",
            "source_ref": "test:problem",
            "review_state": "pending",
            "confidence": "low",
            "tags": ["test"],
        }
        body = """# Demo

## 现象

Failure.

## 影响

Impact.

## 环境与上下文

Context.

## 已尝试方案

Attempt.

## 根因

Pending.

## 最终方案

Pending.

## 验证

未完成。

## 防止复发

Pending.

## 可复用结论

Pending.

## 后续记录

### 2026-08-12 — 首次发现

- 状态：investigating
- 摘要：首次复现。
- 会话：[[First]]
- 验证：未完成。

## 关联记录

- [[First]]
"""
        return metadata, body

    def test_solved_update_appends_event_and_updates_fields(self) -> None:
        metadata, body = self.base_record()
        updated = update_problem(
            Path("problem.md"),
            metadata,
            body,
            event_date="2026-08-13",
            event_title="已解决",
            status="solved",
            summary="Confirmed root cause.",
            session="[[Second]]",
            validation="Tests passed.",
            root_cause="Encoding mismatch",
            solution_type="bugfix",
            solution="Use UTF-8.",
        )
        result_metadata, result_body = split_frontmatter(updated)
        self.assertEqual(result_metadata["status"], "solved")
        self.assertEqual(str(result_metadata["resolved_at"]), "2026-08-13")
        self.assertEqual(result_metadata["occurrences"], 2)
        self.assertIn("### 2026-08-13 — 已解决", result_body)
        self.assertLess(result_body.index("### 2026-08-13 — 已解决"), result_body.index("## 关联记录"))

    def test_solved_update_requires_concrete_evidence(self) -> None:
        metadata, body = self.base_record()
        with self.assertRaisesRegex(ValueError, "root-cause"):
            update_problem(
                Path("problem.md"),
                metadata,
                body,
                event_date="2026-08-13",
                event_title="已解决",
                status="solved",
                summary="Done.",
                session="[[Second]]",
                validation="Tests passed.",
            )

    def test_duplicate_event_is_rejected(self) -> None:
        _, body = self.base_record()
        with self.assertRaisesRegex(ValueError, "duplicate follow-up"):
            append_event(body, "ignored", "2026-08-12", "首次发现")


class PortabilityTests(unittest.TestCase):
    def test_portable_check_and_export(self) -> None:
        skill_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "Vault"
            (vault / "00-AI知识库" / "_系统").mkdir(parents=True)
            (vault / "00-AI知识库" / "_系统" / "config.yaml").write_text(
                "schema_version: 2\nknowledge_root: 00-AI知识库\n",
                encoding="utf-8",
            )
            errors, _ = portability_issues(skill_root, vault)
            self.assertEqual(errors, [])
            output = Path(temp_dir) / "skill.zip"
            export_skill(skill_root, output)
            self.assertTrue(output.exists())
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
            self.assertIn("obsidian-ai-knowledge/SKILL.md", names)
            self.assertIn("obsidian-ai-knowledge/scripts/update_problem.py", names)
            self.assertFalse(any("__pycache__" in name for name in names))


if __name__ == "__main__":
    unittest.main()