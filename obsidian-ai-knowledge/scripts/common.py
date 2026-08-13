from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterator

import yaml


DEFAULT_KNOWLEDGE_ROOT = "00-AI知识库"
DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 2,
    "knowledge_root": DEFAULT_KNOWLEDGE_ROOT,
    "excluded_directories": ["模板", "_系统", "项目空间"],
    "record_directories": {
        "project": "项目",
        "problem": "问题",
        "session": "会话",
        "playbook": "经验",
        "inbox": "Inbox",
    },
    "project_spaces": {
        "root": "项目空间",
        "default_type": "general",
        "review_days": 14,
    },
    "freshness": {
        "default_watch": ["package.json", "pyproject.toml", "README.md", "PRODUCT.md", "ROADMAP.md", "CHANGELOG.md", "docs/CHANGELOG.md", "AGENTS.md"],
    },
    "plugins": {
        "required_community": [],
    },
    "solution_index": None,
    "quality": {
        "stale_active_project_days": 90,
        "stable_playbook_min_uses": 2,
        "inbox_review_days": 7,
        "open_problem_review_days": 30,
        "draft_playbook_review_days": 30,
        "recent_session_days": 14,
        "stub_body_chars": 120,
    },
}


def default_vault() -> Path:
    configured = os.environ.get("OBSIDIAN_AI_VAULT")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Documents" / "Obsidian Vault"


def resolve_vault(value: Path | None) -> Path:
    vault = (value or default_vault()).expanduser()
    return vault.resolve(strict=False)


def merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def load_config(vault: Path) -> dict[str, Any]:
    default_path = vault / DEFAULT_KNOWLEDGE_ROOT / "_系统" / "config.yaml"
    configured_path = os.environ.get("OBSIDIAN_AI_CONFIG")
    path = Path(configured_path).expanduser() if configured_path else default_path
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config must be a YAML object: {path}")
    return merge_dict(DEFAULT_CONFIG, loaded)


def knowledge_root(vault: Path, config: dict[str, Any]) -> Path:
    return vault / str(config.get("knowledge_root", DEFAULT_KNOWLEDGE_ROOT))


def split_frontmatter(text: str, *, strict: bool = True) -> tuple[dict[str, Any], str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        if strict:
            raise ValueError("missing YAML frontmatter")
        return {}, normalized
    end = normalized.find("\n---\n", 4)
    if end == -1:
        if strict:
            raise ValueError("unterminated YAML frontmatter")
        return {}, normalized
    metadata = yaml.safe_load(normalized[4:end]) or {}
    if not isinstance(metadata, dict):
        if strict:
            raise ValueError("frontmatter must be an object")
        return {}, normalized[end + 5 :]
    return metadata, normalized[end + 5 :]


def iter_record_paths(vault: Path, config: dict[str, Any]) -> Iterator[Path]:
    root = knowledge_root(vault, config)
    excluded = set(map(str, config.get("excluded_directories", [])))
    if not root.exists():
        return
    for path in root.rglob("*.md"):
        relative_parts = path.relative_to(root).parts
        if any(part in excluded for part in relative_parts):
            continue
        yield path


def extract_wikilinks(text: str) -> list[str]:
    without_fences = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    without_code = re.sub(r"`[^`\n]*`", "", without_fences)
    return re.findall(r"!?\[\[([^\n]+?)\]\]", without_code)


def normalize_wikilink(value: str) -> str:
    target = value.split("|", 1)[0].split("#", 1)[0].split("^", 1)[0].strip()
    target = target.replace("\\", "/")
    return target[:-3] if target.casefold().endswith(".md") else target


def build_note_index(vault: Path) -> tuple[set[str], set[str]]:
    paths: set[str] = set()
    stems: set[str] = set()
    for path in vault.rglob("*.md"):
        if ".obsidian" in path.parts:
            continue
        relative = path.relative_to(vault).with_suffix("").as_posix()
        paths.add(relative.casefold())
        stems.add(path.stem.casefold())
    return paths, stems
