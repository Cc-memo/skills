from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from decision_index import build_entries, save_index, search_index  # noqa: E402
from recall_solution import detect_route, probe_solution, recall_decisions  # noqa: E402


class DecisionIndexTests(unittest.TestCase):
    def make_vault(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        system = vault / "knowledge" / "_system"
        system.mkdir(parents=True)
        config = system / "config.yaml"
        config.write_text(
            "schema_version: 2\nknowledge_root: knowledge\n"
            "excluded_directories: [templates, _system, project-spaces]\n",
            encoding="utf-8",
        )
        self.previous_config = os.environ.get("OBSIDIAN_AI_CONFIG")
        os.environ["OBSIDIAN_AI_CONFIG"] = str(config)
        self.addCleanup(self.restore_config)
        return vault

    def restore_config(self) -> None:
        if self.previous_config is None:
            os.environ.pop("OBSIDIAN_AI_CONFIG", None)
        else:
            os.environ["OBSIDIAN_AI_CONFIG"] = self.previous_config

    def write_session(
        self,
        vault: Path,
        name: str,
        record_id: str,
        *,
        kind: str,
        confidence: str = "high",
        superseded: bool = False,
        tags: str = "[decision, rollback]",
        decision_index: bool = False,
    ) -> None:
        path = vault / "knowledge" / "sessions" / "2026" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        replacement = "superseded_by: replacement\n" if superseded else ""
        promotion = "decision_index: true\n" if decision_index else ""
        path.write_text(
            "---\nschema_version: 2\nrecord_type: session\n"
            f"record_id: {record_id}\nstatus: completed\noutcome: success\n"
            "created: 2026-08-14\nupdated: 2026-08-14\ncompleted_at: 2026-08-14\n"
            f"summary_kind: {kind}\nreview_state: reviewed\nconfidence: {confidence}\n"
            f"{replacement}{promotion}source_ref: test\ntags: {tags}\n---\n"
            f"# {name}\n\nRollback decision for the previous implementation.\n",
            encoding="utf-8",
        )

    def test_index_keeps_trusted_decisions_and_excludes_unverified_or_superseded(self) -> None:
        vault = self.make_vault()
        self.write_session(vault, "Decision", "session-decision", kind="decision")
        self.write_session(vault, "Ordinary delivery", "session-delivery", kind="delivery", tags="[delivery]")
        self.write_session(
            vault,
            "Promoted delivery",
            "session-promoted-delivery",
            kind="delivery",
            tags="[delivery]",
            decision_index=True,
        )
        self.write_session(vault, "Pending", "session-pending", kind="research", confidence="low")
        self.write_session(vault, "Old", "session-old", kind="retrospective", superseded=True)
        self.assertEqual(
            {item["record_id"] for item in build_entries(vault)},
            {"session-decision", "session-promoted-delivery"},
        )

    def test_decision_query_and_auto_route(self) -> None:
        vault = self.make_vault()
        self.write_session(vault, "Decision", "session-decision", kind="decision")
        save_index(vault)
        self.assertEqual(detect_route("为什么回退之前的方案"), "decision")
        self.assertEqual(detect_route("为什么 ERR_X 配置报错"), "problem")
        results = search_index(vault, "rollback decision", limit=1)
        self.assertEqual(results[0]["record_id"], "session-decision")
        result = probe_solution(vault, "why rollback decision")
        self.assertTrue(result["match"])
        self.assertEqual(result["route"], "decision")
        self.assertEqual(recall_decisions(vault, "rollback decision", limit=1)[0]["record_id"], "session-decision")

    def test_specific_identity_outweighs_generic_research_terms(self) -> None:
        vault = self.make_vault()
        self.write_session(vault, "Generic token research", "session-generic", kind="research", tags="[research]")
        self.write_session(
            vault,
            "Knowledge-OS actual output",
            "session-knowledge-os-output",
            kind="delivery",
            tags="[delivery]",
            decision_index=True,
        )
        save_index(vault)
        results = search_index(vault, "Knowledge-OS research conclusion and actual output", limit=2)
        self.assertEqual(results[0]["record_id"], "session-knowledge-os-output")

    def test_missing_index_fallback_keeps_decision_filter(self) -> None:
        vault = self.make_vault()
        self.write_session(vault, "Decision", "session-decision", kind="decision")
        self.write_session(vault, "Ordinary delivery", "session-delivery", kind="delivery", tags="[delivery]")
        results = recall_decisions(vault, "rollback decision", limit=3)
        self.assertEqual([item["record_id"] for item in results], ["session-decision"])

    def test_project_route_requires_project_name(self) -> None:
        vault = self.make_vault()
        result = probe_solution(vault, "继续项目", route="project")
        self.assertFalse(result["match"])
        self.assertEqual(result["next"], "provide-project")


if __name__ == "__main__":
    unittest.main()
