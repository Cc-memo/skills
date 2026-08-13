from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from doctor import check_community_plugins  # noqa: E402


class DoctorPluginTests(unittest.TestCase):
    def make_vault(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        (vault / ".obsidian" / "plugins").mkdir(parents=True)
        return vault

    def write_plugin(self, vault: Path, plugin_id: str, data: dict | None = None) -> None:
        folder = vault / ".obsidian" / "plugins" / plugin_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "manifest.json").write_text(json.dumps({"id": plugin_id}), encoding="utf-8")
        if data is not None:
            (folder / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_missing_required_plugin_is_reported(self) -> None:
        vault = self.make_vault()
        config = {"plugins": {"required_community": ["homepage"]}}

        errors, warnings = check_community_plugins(vault, config)

        self.assertIn("community-plugins.json not found", errors)
        self.assertIn("required community plugin is not installed: homepage", errors)
        self.assertIn("required community plugin is disabled: homepage", errors)
        self.assertEqual([], warnings)

    def test_safe_plugin_configuration_passes(self) -> None:
        vault = self.make_vault()
        enabled = ["homepage", "obsidian-linter", "templater-obsidian"]
        (vault / ".obsidian" / "community-plugins.json").write_text(json.dumps(enabled), encoding="utf-8")
        self.write_plugin(vault, "homepage", {"homepages": {"Main Homepage": {"value": "00-AI知识库/00 - AI知识库首页"}}})
        self.write_plugin(vault, "obsidian-linter", {"lintOnSave": False})
        self.write_plugin(
            vault,
            "templater-obsidian",
            {"trigger_on_file_creation": False, "templates_folder": "00-AI知识库/模板/Templater"},
        )

        errors, warnings = check_community_plugins(vault, {"plugins": {"required_community": enabled}})

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_quickadd_complete_project_macro_is_required(self) -> None:
        vault = self.make_vault()
        enabled = ["quickadd"]
        (vault / ".obsidian" / "community-plugins.json").write_text(json.dumps(enabled), encoding="utf-8")
        self.write_plugin(vault, "quickadd", {"choices": []})

        errors, _ = check_community_plugins(vault, {"plugins": {"required_community": enabled}})

        self.assertIn("QuickAdd complete-project macro is not configured", errors)

        script = vault / "00-AI知识库" / "_系统" / "脚本" / "create-project-space.js"
        script.parent.mkdir(parents=True)
        script.write_text("module.exports = async () => {};", encoding="utf-8")
        self.write_plugin(
            vault,
            "quickadd",
            {
                "choices": [
                    {
                        "id": "ai-knowledge-project-space",
                        "type": "Macro",
                        "command": True,
                        "macro": {
                            "commands": [
                                {
                                    "type": "UserScript",
                                    "path": "00-AI知识库/_系统/脚本/create-project-space.js",
                                }
                            ]
                        },
                    },
                ]
            },
        )

        errors, warnings = check_community_plugins(vault, {"plugins": {"required_community": enabled}})

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_dangerous_automatic_rewrites_are_reported(self) -> None:
        vault = self.make_vault()
        enabled = ["obsidian-linter", "templater-obsidian"]
        (vault / ".obsidian" / "community-plugins.json").write_text(json.dumps(enabled), encoding="utf-8")
        self.write_plugin(vault, "obsidian-linter", {"lintOnSave": True})
        self.write_plugin(
            vault,
            "templater-obsidian",
            {"trigger_on_file_creation": True, "templates_folder": "wrong"},
        )

        errors, warnings = check_community_plugins(vault, {"plugins": {"required_community": enabled}})

        self.assertTrue(any("trigger_on_file_creation" in error for error in errors))
        self.assertTrue(any("template folder" in error for error in errors))
        self.assertTrue(any("lint-on-save" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
