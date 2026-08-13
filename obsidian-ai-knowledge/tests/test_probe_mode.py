from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from recall_solution import probe_solution  # noqa: E402
from solution_index import save_index  # noqa: E402


class ProbeModeTests(unittest.TestCase):
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

    def write_problem(self, vault: Path) -> None:
        path = vault / "knowledge" / "problems" / "current.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\nschema_version: 2\nrecord_type: problem\nrecord_id: problem-x\n"
            "status: solved\nreview_state: reviewed\nconfidence: high\n"
            "root_cause: exact signature\nerror_signatures: [ERR_X]\nsource_ref: test\n---\n# X\n",
            encoding="utf-8",
        )

    def test_probe_returns_direct_solve_for_weak_match(self) -> None:
        vault = self.make_vault()
        self.write_problem(vault)
        save_index(vault)
        result = probe_solution(vault, "unrelated question")
        self.assertFalse(result["match"])
        self.assertEqual(result["next"], "solve-directly")

    def test_probe_returns_only_compact_match(self) -> None:
        vault = self.make_vault()
        self.write_problem(vault)
        save_index(vault)
        result = probe_solution(vault, "ERR_X")
        self.assertTrue(result["match"])
        self.assertEqual(set(result), {"match", "record_id", "record_type", "score", "trust_state", "root_cause", "next"})
        self.assertEqual(result["next"], "load-detail")


if __name__ == "__main__":
    unittest.main()
