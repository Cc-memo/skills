from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from common import knowledge_root, load_config, resolve_vault


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_community_plugins(vault: Path, config: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    community_path = vault / ".obsidian" / "community-plugins.json"
    enabled_community: set[str] = set()
    if community_path.exists():
        community_data = load_json(community_path)
        if isinstance(community_data, list):
            enabled_community = {str(item) for item in community_data}
        else:
            errors.append("community-plugins.json must be a JSON array")
    else:
        errors.append("community-plugins.json not found")
    required_community = config.get("plugins", {}).get("required_community", [])
    for plugin_id in required_community:
        manifest = vault / ".obsidian" / "plugins" / str(plugin_id) / "manifest.json"
        if not manifest.exists():
            errors.append(f"required community plugin is not installed: {plugin_id}")
        if str(plugin_id) not in enabled_community:
            errors.append(f"required community plugin is disabled: {plugin_id}")

    homepage_data = vault / ".obsidian" / "plugins" / "homepage" / "data.json"
    if "homepage" in enabled_community:
        if not homepage_data.exists() or "00-AI知识库/00 - AI知识库首页" not in homepage_data.read_text(encoding="utf-8"):
            errors.append("Homepage plugin is not configured for the AI knowledge dashboard")
    linter_data = vault / ".obsidian" / "plugins" / "obsidian-linter" / "data.json"
    if "obsidian-linter" in enabled_community and linter_data.exists():
        if load_json(linter_data).get("lintOnSave") is True:
            warnings.append("Linter lint-on-save is enabled; automatic rewrites may conflict with knowledge templates")
    templater_data = vault / ".obsidian" / "plugins" / "templater-obsidian" / "data.json"
    if "templater-obsidian" in enabled_community:
        if not templater_data.exists():
            errors.append("Templater data.json not found")
        else:
            templater = load_json(templater_data)
            if templater.get("trigger_on_file_creation") is True:
                errors.append("Templater trigger_on_file_creation must remain disabled")
            if templater.get("templates_folder") != "00-AI知识库/模板/Templater":
                errors.append("Templater template folder is not configured for the AI knowledge system")
    quickadd_data = vault / ".obsidian" / "plugins" / "quickadd" / "data.json"
    if "quickadd" in enabled_community:
        if not quickadd_data.exists():
            errors.append("QuickAdd data.json not found")
        else:
            quickadd = load_json(quickadd_data)
            choices = quickadd.get("choices", []) if isinstance(quickadd, dict) else []
            project_choice = next(
                (choice for choice in choices if isinstance(choice, dict) and choice.get("id") == "ai-knowledge-project-space"),
                None,
            )
            if project_choice is None:
                errors.append("QuickAdd complete-project macro is not configured")
            else:
                if project_choice.get("type") != "Macro" or project_choice.get("command") is not True:
                    errors.append("QuickAdd complete-project choice must be an enabled Macro command")
                commands = (project_choice.get("macro") or {}).get("commands", [])
                expected_script = "00-AI知识库/_系统/脚本/create-project-space.js"
                if not any(
                    isinstance(command, dict)
                    and command.get("type") == "UserScript"
                    and command.get("path") == expected_script
                    for command in commands
                ):
                    errors.append("QuickAdd complete-project macro is missing the project-space UserScript")
                if not (vault / expected_script).exists():
                    errors.append("QuickAdd project-space UserScript file is missing")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Obsidian AI knowledge system installation and runtime prerequisites.")
    parser.add_argument("--vault", type=Path)
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        config = load_config(vault)
    except Exception as exc:
        errors.append(f"config: {exc}")
        config = {}
    root = knowledge_root(vault, config)

    if not vault.exists():
        errors.append(f"vault does not exist: {vault}")
    if not root.exists():
        errors.append(f"knowledge root does not exist: {root}")

    core_path = vault / ".obsidian" / "core-plugins.json"
    if core_path.exists():
        core = load_json(core_path)
        for plugin in ("bases", "properties", "templates"):
            if not core.get(plugin):
                errors.append(f"Obsidian core plugin is disabled: {plugin}")
    else:
        warnings.append("core-plugins.json not found")

    templates_path = vault / ".obsidian" / "templates.json"
    if templates_path.exists():
        templates = load_json(templates_path)
        expected = f"{config.get('knowledge_root', '00-AI知识库')}/模板"
        if templates.get("folder") != expected:
            warnings.append(f"template folder is {templates.get('folder')!r}, expected {expected!r}")
    else:
        errors.append("templates.json not found")

    plugin_errors, plugin_warnings = check_community_plugins(vault, config)
    errors.extend(plugin_errors)
    warnings.extend(plugin_warnings)

    for path in root.rglob("*.base") if root.exists() else []:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("views"), list) or not data["views"]:
                errors.append(f"{path.name}: missing views")
                continue
            names = [view.get("name") for view in data["views"]]
            if len(names) != len(set(names)):
                errors.append(f"{path.name}: duplicate view names")
            formulas = set((data.get("formulas") or {}).keys())
            for view in data["views"]:
                for prop in view.get("order", []):
                    if isinstance(prop, str) and prop.startswith("formula.") and prop[8:] not in formulas:
                        errors.append(f"{path.name}: undefined formula in order: {prop}")
        except Exception as exc:
            errors.append(f"{path.name}: invalid YAML: {exc}")

    home = Path.home()
    skill_root = home / ".codex" / "skills" / "obsidian-ai-knowledge"
    for required in (
        skill_root / "SKILL.md",
        skill_root / "scripts" / "search_knowledge.py",
        skill_root / "scripts" / "validate_knowledge.py",
        skill_root / "scripts" / "health_report.py",
        skill_root / "scripts" / "project_space.py",
        skill_root / "scripts" / "project_freshness.py",
        skill_root / "scripts" / "project_context.py",
        skill_root / "scripts" / "update_problem.py",
        skill_root / "scripts" / "portable_check.py",
        skill_root / "references" / "problem-lifecycle.md",
        skill_root / "references" / "portability.md",
        skill_root / "assets" / "global-agent-instructions.md",
        root / "_系统" / "调取路由.yaml",
        home / ".codex" / "skills" / "obsidian-markdown" / "SKILL.md",
        home / ".codex" / "skills" / "obsidian-bases" / "SKILL.md",
    ):
        if not required.exists():
            errors.append(f"required skill file missing: {required}")

    for instructions, marker in (
        (home / ".codex" / "AGENTS.md", "$obsidian-ai-knowledge"),
        (home / ".claude" / "CLAUDE.md", "obsidian-ai-knowledge"),
    ):
        if not instructions.exists() or marker not in instructions.read_text(encoding="utf-8"):
            errors.append(f"global capture instruction missing: {instructions}")

    validator = skill_root / "scripts" / "validate_knowledge.py"
    if validator.exists():
        child_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, str(validator), "--vault", str(vault)],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        )
        if result.returncode:
            errors.append("knowledge validation failed")
            errors.extend(line for line in result.stdout.splitlines() if line.startswith("ERROR:"))
        warnings.extend(line.removeprefix("WARNING: ") for line in result.stdout.splitlines() if line.startswith("WARNING:"))

    health_report = root / "_系统" / "知识库健康报告.md"
    if root.exists() and not health_report.exists():
        warnings.append("knowledge health report has not been generated")

    for warning in sorted(set(warnings)):
        print(f"WARNING: {warning}")
    for error in sorted(set(errors)):
        print(f"ERROR: {error}")
    print(f"Doctor: {'FAILED' if errors else 'OK'} ({len(set(errors))} errors, {len(set(warnings))} warnings)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
