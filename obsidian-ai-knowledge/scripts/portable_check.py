from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

from common import default_vault


IGNORED_PARTS = {"__pycache__", ".pytest_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def portability_issues(skill_root: Path, vault: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    required = [
        skill_root / "SKILL.md",
        skill_root / "scripts" / "common.py",
        skill_root / "scripts" / "recall_solution.py",
        skill_root / "scripts" / "update_problem.py",
        skill_root / "scripts" / "validate_knowledge.py",
        skill_root / "references" / "portability.md",
        skill_root / "assets" / "global-agent-instructions.md",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing portable skill file: {path}")
    requirements = skill_root / "scripts" / "requirements.txt"
    if requirements.exists():
        try:
            import yaml  # noqa: F401
        except ImportError:
            errors.append(f"PyYAML is unavailable; install with: {sys.executable} -m pip install -r {requirements}")
    if not vault.exists():
        errors.append(f"vault not found: {vault}")
    elif not (vault / "00-AI知识库" / "_系统" / "config.yaml").exists():
        errors.append(f"knowledge config not found under vault: {vault}")

    hardcoded = re.compile(r"(?i)[A-Z]:\\Users\\[^\\]+")
    for path in skill_root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts) or path.suffix in IGNORED_SUFFIXES:
            continue
        if path.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in hardcoded.finditer(text):
            value = match.group(0)
            if "%USERPROFILE%" not in value:
                warnings.append(f"device-specific path in {path.relative_to(skill_root)}: {value}")
                break

    agents = codex_home() / "AGENTS.md"
    if not agents.exists() or "obsidian-ai-knowledge" not in agents.read_text(encoding="utf-8", errors="replace"):
        warnings.append(f"global trigger rule is not installed: {agents}")
    return errors, warnings


def export_skill(skill_root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in skill_root.rglob("*"):
            if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts) or path.suffix in IGNORED_SUFFIXES:
                continue
            archive.write(path, Path("obsidian-ai-knowledge") / path.relative_to(skill_root))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check or export the Obsidian AI knowledge skill for another device.")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--export", type=Path, help="Create a portable skill zip without vault data")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parents[1]
    vault = (args.vault or default_vault()).expanduser().resolve(strict=False)
    errors, warnings = portability_issues(skill_root, vault)
    if args.export:
        export_skill(skill_root, args.export.resolve(strict=False))
        print(f"Exported skill package: {args.export.resolve(strict=False)}")
    for warning in sorted(set(warnings)):
        print(f"WARNING: {warning}")
    for error in sorted(set(errors)):
        print(f"ERROR: {error}")
    print(f"Portable check: {'FAILED' if errors else 'OK'} ({len(set(errors))} errors, {len(set(warnings))} warnings)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())