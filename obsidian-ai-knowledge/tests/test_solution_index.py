from __future__ import annotations

import sys
import tempfile
import unittest
import os
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from solution_index import build_entries, save_index, search_index  # noqa: E402


class SolutionIndexTests(unittest.TestCase):
    def make_vault(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        system = vault / "knowledge" / "_system"
        system.mkdir(parents=True)
        (system / "config.yaml").write_text(
            "schema_version: 2\nknowledge_root: knowledge\n"
            "excluded_directories: [templates, _system, project-spaces]\n",
            encoding="utf-8",
        )
        self.previous_config = os.environ.get("OBSIDIAN_AI_CONFIG")
        os.environ["OBSIDIAN_AI_CONFIG"] = str(system / "config.yaml")
        self.addCleanup(self.restore_config)
        return vault

    def restore_config(self) -> None:
        if self.previous_config is None:
            os.environ.pop("OBSIDIAN_AI_CONFIG", None)
        else:
            os.environ["OBSIDIAN_AI_CONFIG"] = self.previous_config

    def write(self, vault: Path, relative: str, content: str) -> None:
        path = vault / "knowledge" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_index_contains_only_trusted_current_answers(self) -> None:
        vault = self.make_vault()
        header = "---\nschema_version: 2\nrecord_type: {kind}\nrecord_id: {id}\nstatus: {status}\n"
        trusted = header.format(kind="problem", id="problem-current", status="solved") + (
            "project: Demo\nreview_state: reviewed\nconfidence: high\n"
            "root_cause: exact signature mismatch\nerror_signatures: [ERR_EXACT]\n"
            "technologies: [Python]\nsource_ref: test\n---\n# Current\n"
        )
        pending = header.format(kind="session", id="session-pending", status="completed") + (
            "review_state: pending\nconfidence: low\nsource_ref: test\n---\n# Pending\n"
        )
        superseded = header.format(kind="problem", id="problem-old", status="solved") + (
            "review_state: reviewed\nconfidence: high\nsuperseded_by: problem-current\n"
            "source_ref: test\n---\n# Old\n"
        )
        self.write(vault, "problems/2026/current.md", trusted)
        self.write(vault, "sessions/2026/pending.md", pending)
        self.write(vault, "problems/2026/old.md", superseded)
        entries = build_entries(vault)
        self.assertEqual([item["record_id"] for item in entries], ["problem-current"])

    def test_exact_error_signature_ranks_first(self) -> None:
        vault = self.make_vault()
        for name, record_id, signature in (("weak", "problem-weak", "ERR_OTHER"), ("exact", "problem-exact", "ERR_EXACT")):
            self.write(vault, f"problems/2026/{name}.md", (
                "---\nschema_version: 2\nrecord_type: problem\n"
                f"record_id: {record_id}\nstatus: solved\nreview_state: reviewed\nconfidence: high\n"
                f"error_signatures: [{signature}]\nsource_ref: test\n---\n# {name}\n"
            ))
        save_index(vault)
        results = search_index(vault, "ERR_EXACT", limit=2)
        self.assertEqual(results[0]["record_id"], "problem-exact")


if __name__ == "__main__":
    unittest.main()
