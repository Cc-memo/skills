from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from common import atomic_write_text, iter_record_paths, knowledge_root, load_config, record_manifest, split_frontmatter
from search_knowledge import is_superseded, stringify, trust_state, tokens


INDEX_NAME = "problem-solution-index.json"
INDEX_SCHEMA_VERSION = 1
INDEX_TYPES = {"problem", "playbook"}


def index_path(vault: Path, config: dict[str, Any] | None = None) -> Path:
    config = config or load_config(vault)
    configured = config.get("solution_index")
    if configured:
        path = Path(str(configured)).expanduser()
        return path if path.is_absolute() else vault / path
    return knowledge_root(vault, config) / "_系统" / INDEX_NAME


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()]
    return []


def _section(body: str, names: tuple[str, ...]) -> str:
    headings = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", body))
    wanted = {name.casefold() for name in names}
    for number, match in enumerate(headings):
        if match.group(1).strip().casefold() not in wanted:
            continue
        end = headings[number + 1].start() if number + 1 < len(headings) else len(body)
        return re.sub(r"\s+", " ", body[match.end():end]).strip()
    return ""


def _derived(metadata: dict[str, Any], body: str, names: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for name in names:
        values.extend(_list_value(metadata.get(name)))
    section = _section(body, names)
    if section:
        values.append(section[:500])
    return list(dict.fromkeys(values))


def build_entries(vault: Path) -> list[dict[str, Any]]:
    config = load_config(vault)
    entries: list[dict[str, Any]] = []
    for path in iter_record_paths(vault, config):
        metadata, body = split_frontmatter(path.read_text(encoding="utf-8"), strict=False)
        record_type = str(metadata.get("record_type") or "").casefold()
        status = str(metadata.get("status") or "").casefold()
        maturity = str(metadata.get("maturity") or "").casefold()
        if record_type not in INDEX_TYPES or is_superseded(metadata) or trust_state(metadata) != "trusted":
            continue
        if record_type == "problem" and status not in {"solved", "closed"}:
            continue
        if record_type == "playbook" and maturity in {"draft", "deprecated"}:
            continue
        symptoms = _derived(metadata, body, ("symptoms", "现象", "问题", "触发条件"))
        errors = _derived(metadata, body, ("error_signatures", "error_signature", "错误签名", "报错"))
        technologies = _derived(metadata, body, ("technologies", "technology", "技术", "技术栈"))
        aliases = _derived(metadata, body, ("aliases", "alias", "别名", "tags"))
        root_cause = stringify(metadata.get("root_cause")) or _section(body, ("根因", "根本原因"))
        solution_summary = (
            stringify(metadata.get("solution_summary"))
            or _section(body, ("最终方案", "解决方案", "可复用结论", "方法"))
        )
        entries.append({
            "record_id": metadata.get("record_id"),
            "record_type": record_type,
            "title": path.stem,
            "status": status,
            "maturity": maturity,
            "project": stringify(metadata.get("project")),
            "symptoms": symptoms,
            "error_signatures": errors,
            "technologies": technologies,
            "aliases": aliases,
            "root_cause": root_cause,
            "solution_type": stringify(metadata.get("solution_type")),
            "solution_summary": solution_summary[:700],
            "applies_to": stringify(metadata.get("applies_to")),
            "tags": _list_value(metadata.get("tags")),
            "updated": str(metadata.get("updated") or ""),
            "last_verified": str(metadata.get("last_verified") or metadata.get("updated") or ""),
            "trust_state": trust_state(metadata),
            "relative_path": path.relative_to(vault).as_posix(),
        })
    return sorted(entries, key=lambda item: (item["record_type"], item["title"]))


def build_index(vault: Path) -> dict[str, Any]:
    config = load_config(vault)
    entries = build_entries(vault)
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": date.today().isoformat(),
        "record_count": len(entries),
        "record_types": sorted(INDEX_TYPES),
        "source_manifest": record_manifest(vault, config),
        "entries": entries,
    }


def save_index(vault: Path, output: Path | None = None) -> Path:
    path = output or index_path(vault)
    payload = build_index(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def load_index(vault: Path) -> dict[str, Any] | None:
    path = index_path(vault)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != INDEX_SCHEMA_VERSION:
        return None
    if not isinstance(payload.get("entries"), list):
        return None
    source_manifest = payload.get("source_manifest")
    if source_manifest and source_manifest != record_manifest(vault):
        return None
    return payload


def _entry_text(entry: dict[str, Any]) -> str:
    fields = ("title", "project", "symptoms", "error_signatures", "technologies", "aliases", "root_cause", "solution_type", "applies_to", "tags")
    return " ".join(stringify(entry.get(field)) for field in fields).casefold()


def score_entry(entry: dict[str, Any], query: str) -> tuple[int, list[str]]:
    query_lower = query.casefold().strip()
    query_tokens = tokens(query)
    matched: list[str] = []
    score = 0
    exact_fields = ("error_signatures", "symptoms", "technologies", "aliases", "tags")
    for field in exact_fields:
        values = [str(value).casefold() for value in _list_value(entry.get(field))]
        for value in values:
            if value and value in query_lower:
                score += 45 if field == "error_signatures" else 20
    text = _entry_text(entry)
    for token in query_tokens:
        if token in text:
            matched.append(token)
            score += 8 if token in " ".join(map(str, entry.get("error_signatures") or [])).casefold() else 3
    if query_lower and query_lower in str(entry.get("title") or "").casefold():
        score += 25
    if entry.get("record_type") == "problem" and entry.get("status") in {"solved", "closed"}:
        score += 16
    if entry.get("record_type") == "playbook" and entry.get("maturity") in {"stable", "verified"}:
        score += 14
    return score, matched


def search_index(vault: Path, query: str, limit: int = 3) -> list[dict[str, Any]] | None:
    payload = load_index(vault)
    if payload is None:
        return None
    results: list[dict[str, Any]] = []
    for entry in payload["entries"]:
        score, matched = score_entry(entry, query)
        if score <= 0:
            continue
        results.append({**entry, "score": score, "matched": matched, "path": str(vault / entry["relative_path"]), "snippet": entry.get("solution_summary") or entry.get("root_cause") or ""})
    results.sort(key=lambda item: (-item["score"], item.get("record_type", ""), item.get("title", "")))
    return results[: max(1, limit)]
