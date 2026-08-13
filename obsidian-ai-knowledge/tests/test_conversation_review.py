from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from conversation_review import build_review  # noqa: E402


class ConversationReviewTests(unittest.TestCase):
    def test_summary_exposes_problems_and_recalls_history(self) -> None:
        payload = {
            "conversation_title": "修复终端激活",
            "conversation_summary": "确认终端与项目解释器不一致。",
            "decisions": ["使用 PowerShell hook"],
            "deliverables": ["launcher.ps1"],
            "open_questions": ["第二台设备路径待验证"],
            "problems": [
                {
                    "symptom": "终端未自动激活 Conda 环境",
                    "error_signature": "No vars found to activate",
                    "technology": "PyCharm Conda",
                    "project": "Demo",
                    "status": "investigating",
                }
            ],
        }
        matches = [
            {
                "record_id": "problem-existing",
                "title": "既有问题",
                "record_type": "problem",
                "status": "solved",
                "trust_state": "trusted",
                "score": 120,
                "root_cause": "终端自定义器未生成激活变量",
                "relative_path": "问题/既有问题.md",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir, patch("conversation_review.recall_solutions", return_value=matches):
            result = build_review(payload, vault=Path(temp_dir))
        problem = result["problems"][0]
        self.assertEqual(problem["recommended_action"], "update_existing_problem")
        self.assertEqual(problem["historical_matches"][0]["record_id"], "problem-existing")
        self.assertEqual(result["decisions"], ["使用 PowerShell hook"])

    def test_unmatched_problem_stays_candidate(self) -> None:
        payload = {"conversation_summary": "发现一个待验证问题。", "problems": [{"symptom": "构建偶发失败"}]}
        with tempfile.TemporaryDirectory() as temp_dir, patch("conversation_review.recall_solutions", return_value=[]):
            result = build_review(payload, vault=Path(temp_dir))
        self.assertEqual(result["problems"][0]["recommended_action"], "create_problem_or_inbox_after_verification")


if __name__ == "__main__":
    unittest.main()
