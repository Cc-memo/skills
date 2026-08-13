from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_recall_cues import build_cues, render_cues  # noqa: E402
from evaluate_retrieval import evaluate  # noqa: E402
from recall_solution import group_recall_results, render_cues, render_detail  # noqa: E402
from search_knowledge import expanded_query_tokens  # noqa: E402


KNOWLEDGE_ROOT = "00-AI知识库"


class RetrievalEnhancementTests(unittest.TestCase):
    def make_vault(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        system = vault / KNOWLEDGE_ROOT / "_系统"
        system.mkdir(parents=True)
        (system / "config.yaml").write_text(
            f"schema_version: 2\nknowledge_root: {KNOWLEDGE_ROOT}\n"
            f"excluded_directories: [模板, _系统, 项目空间]\n"
            f"retrieval_routes: {KNOWLEDGE_ROOT}/_系统/routes.yaml\n",
            encoding="utf-8",
        )
        return vault

    def write_problem(self, vault: Path, name: str, record_id: str, *, superseded: bool = False) -> None:
        directory = vault / KNOWLEDGE_ROOT / "问题" / "2026"
        directory.mkdir(parents=True, exist_ok=True)
        replacement = "superseded_by: '[[replacement]]'\n" if superseded else ""
        (directory / f"{name}.md").write_text(
            "---\nschema_version: 2\nrecord_type: problem\n"
            f"record_id: {record_id}\nstatus: solved\ncreated: 2026-08-09\nupdated: 2026-08-09\n"
            "project: Demo\narea: encoding\nroot_cause: unicode transport\nsolution_type: configuration\n"
            "reusable: true\noccurrences: 1\nsource_session: test\nsource: test\nsource_ref: test:case\n"
            "review_state: reviewed\nconfidence: high\ntags: [unicode, encoding]\n"
            f"{replacement}---\n# {name}\n\nUnicode transport fix.\n",
            encoding="utf-8",
        )

    def test_query_expansion_uses_configured_alias_group(self) -> None:
        vault = self.make_vault()
        routes = vault / KNOWLEDGE_ROOT / "_系统" / "routes.yaml"
        routes.write_text(
            "query_expansions:\n  encoding: [mojibake, unicode, garbled]\n",
            encoding="utf-8",
        )
        query_tokens, expanded = expanded_query_tokens(vault, "mojibake config")
        self.assertIn("unicode", query_tokens)
        self.assertIn("unicode", expanded)
        self.assertNotIn("mojibake", expanded)

    def test_grouping_separates_primary_alternative_evidence_and_clue(self) -> None:
        grouped = group_recall_results(
            [
                {"record_id": "p1", "record_type": "problem", "trust_state": "trusted", "solution_type": "fix", "root_cause": "a"},
                {"record_id": "p2", "record_type": "problem", "trust_state": "trusted", "solution_type": "workaround", "root_cause": "b"},
                {"record_id": "s1", "record_type": "session", "trust_state": "trusted"},
                {"record_id": "s2", "record_type": "session", "trust_state": "unverified"},
            ]
        )
        self.assertEqual(grouped["primary"][0]["record_id"], "p1")
        self.assertEqual(grouped["alternatives"][0]["record_id"], "p2")
        self.assertEqual(grouped["evidence"][0]["record_id"], "s1")
        self.assertEqual(grouped["clues"][0]["record_id"], "s2")

    def test_evaluator_rejects_superseded_result(self) -> None:
        vault = self.make_vault()
        self.write_problem(vault, "Current Unicode Fix", "problem-current")
        self.write_problem(vault, "Old Unicode Fix", "problem-old", superseded=True)
        report = evaluate(
            vault,
            [
                {
                    "name": "unicode",
                    "query": "unicode transport",
                    "expected_any": ["problem-current"],
                    "forbidden": ["problem-old"],
                    "trusted_required": True,
                }
            ],
            limit=3,
        )
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["results"][0]["forbidden_hits"], [])

    def test_cues_only_include_current_trusted_solution(self) -> None:
        vault = self.make_vault()
        self.write_problem(vault, "Current Unicode Fix", "problem-current")
        self.write_problem(vault, "Old Unicode Fix", "problem-old", superseded=True)
        cues = build_cues(vault)
        rendered = render_cues(vault, cues)
        self.assertEqual([cue["record_id"] for cue in cues], ["problem-current"])
        self.assertIn("Current Unicode Fix", rendered)
        self.assertNotIn("Old Unicode Fix", rendered)


    def test_cue_and_detail_are_separate_token_budgets(self) -> None:
        vault = self.make_vault()
        self.write_problem(vault, "Current Unicode Fix", "problem-current")
        results = [
            {
                "title": "Current Unicode Fix",
                "record_id": "problem-current",
                "record_type": "problem",
                "trust_state": "trusted",
                "score": 120,
                "root_cause": "unicode transport",
                "relative_path": "00-AI???\\??\\2026\\Current Unicode Fix.md",
            }
        ]
        cue = render_cues("unicode transport", results, 900)
        detail = render_detail(vault, "problem-current", 1600)
        self.assertLess(len(cue), 1000)
        self.assertIn("problem-current", cue)
        self.assertIn("## \u6458\u8981", detail)
        self.assertIn("Unicode transport fix", detail)


if __name__ == "__main__":
    unittest.main()