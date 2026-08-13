from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from search_knowledge import render_context, score_record, search_records, should_include, tokens  # noqa: E402


KNOWLEDGE_ROOT = "00-AI知识库"


class SearchKnowledgeTests(unittest.TestCase):
    def test_chinese_query_adds_bigrams(self) -> None:
        result = tokens("知识沉淀")
        self.assertIn("知识沉淀", result)
        self.assertIn("知识", result)
        self.assertIn("沉淀", result)

    def test_title_and_metadata_rank_above_body_only(self) -> None:
        query = "root cause"
        query_tokens = tokens(query)
        title_score, _ = score_record(
            Path("Root Cause Playbook.md"),
            {"record_id": "playbook-root-cause", "tags": ["debugging"], "updated": "2026-08-04"},
            "Short body.",
            query,
            query_tokens,
        )
        body_score, _ = score_record(
            Path("Unrelated.md"),
            {"record_id": "session-other", "tags": [], "updated": "2026-08-04"},
            "The root cause appears once in the body.",
            query,
            query_tokens,
        )
        self.assertGreater(title_score, body_score)

    def test_verified_output_ranks_above_pending_review(self) -> None:
        query = "context retrieval"
        query_tokens = tokens(query)
        base = {
            "record_type": "session",
            "record_id": "session-retrieval",
            "review_state": "reviewed",
            "confidence": "high",
            "validation_state": "passed",
            "outcome": "success",
            "updated": "2026-08-07",
        }
        verified_score, _ = score_record(
            Path("Context Retrieval.md"),
            {**base, "_output_category": "verified-delivery"},
            "context retrieval implementation",
            query,
            query_tokens,
        )
        pending_score, _ = score_record(
            Path("Context Retrieval.md"),
            {**base, "review_state": "pending", "_output_category": "needs-review"},
            "context retrieval implementation",
            query,
            query_tokens,
        )
        self.assertGreater(verified_score, pending_score)

    def test_superseded_is_excluded_by_default(self) -> None:
        metadata = {"review_state": "reviewed", "superseded_by": "[[replacement]]"}
        self.assertFalse(should_include(metadata, include_superseded=False, trusted_only=False))
        self.assertTrue(should_include(metadata, include_superseded=True, trusted_only=False))

    def test_search_context_returns_trusted_record_and_excludes_history(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        system = vault / KNOWLEDGE_ROOT / "_系统"
        system.mkdir(parents=True)
        (system / "config.yaml").write_text(
            f"schema_version: 2\nknowledge_root: {KNOWLEDGE_ROOT}\nexcluded_directories: [模板, _系统, 项目空间]\n",
            encoding="utf-8",
        )
        sessions = vault / KNOWLEDGE_ROOT / "会话" / "2026"
        sessions.mkdir(parents=True)
        common = (
            "---\nschema_version: 2\nrecord_type: session\nstatus: completed\noutcome: success\n"
            "created: 2026-08-07\nupdated: 2026-08-07\ncompleted_at: 2026-08-07\n"
            "project: Demo\narea: retrieval\nai_tool: codex\nworkspace: test\nknowledge_value: high\n"
            "source: test\nsource_ref: test:retrieval\nreview_state: reviewed\nconfidence: high\n"
            "summary_kind: delivery\nactual_output: true\nvalidation_state: passed\ntags: [retrieval]\n"
        )
        (sessions / "Current retrieval.md").write_text(
            common
            + "record_id: session-current\n---\n# Current retrieval\n\n## 变更文件\n\n- search.py\n\n## 验证结果\n\n- tests passed\n",
            encoding="utf-8",
        )
        (sessions / "Old retrieval.md").write_text(
            common
            + "record_id: session-old\nsuperseded_by: '[[Current retrieval]]'\n---\n# Old retrieval\n\n## 变更文件\n\n- old.py\n\n## 验证结果\n\n- tests passed\n",
            encoding="utf-8",
        )

        results = search_records(vault, "retrieval", limit=10)
        self.assertEqual([item["title"] for item in results], ["Current retrieval"])
        self.assertEqual(results[0]["trust_state"], "trusted")
        context = render_context("retrieval", results, 4000)
        self.assertIn("Current retrieval", context)
        self.assertNotIn("Old retrieval", context)
        self.assertIn("trusted", context)


if __name__ == "__main__":
    unittest.main()