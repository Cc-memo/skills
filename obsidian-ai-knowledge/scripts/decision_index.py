from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from common import iter_record_paths, knowledge_root, load_config, split_frontmatter
from search_knowledge import is_superseded, stringify, tokens, trust_state


INDEX_NAME = "decision-index.json"
INDEX_SCHEMA_VERSION = 1
DECISION_KINDS = {"decision", "research", "retrospective", "method"}
DECISION_MARKERS = (
    "\u51b3\u7b56", "\u4e3a\u4ec0\u4e48\u9009\u62e9", "\u4e3a\u4ec0\u4e48\u4e0d\u7528", "\u4e3a\u4ec0\u4e48\u64a4\u56de",
    "\u5bf9\u6bd4", "\u56de\u9000", "\u56de\u6eda", "\u64a4\u56de", "\u7814\u7a76", "\u8c03\u7814", "\u53d6\u820d",
    "decision", "research", "rollback", "revert", "tradeoff",
)


def index_path(vault: Path, config: dict[str, Any] | None = None) -> Path:
    config = config or load_config(vault)
    configured = config.get("decision_index")
    if configured:
        path = Path(str(configured)).expanduser()
        return path if path.is_absolute() else vault / path
    return knowledge_root(vault, config) / "_系统" / INDEX_NAME


def _section(body: str, names: tuple[str, ...]) -> str:
    headings = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", body))
    wanted = {name.casefold() for name in names}
    for number, match in enumerate(headings):
        if match.group(1).strip().casefold() not in wanted:
            continue
        end = headings[number + 1].start() if number + 1 < len(headings) else len(body)
        return re.sub(r"\s+", " ", body[match.end():end]).strip()
    return ""


def _summary(metadata: dict[str, Any], body: str) -> str:
    values = metadata.get("key_decisions") or metadata.get("decision_summary") or metadata.get("deliverables")
    if values:
        return stringify(values)[:700]
    return (_section(body, ("关键决策", "决策", "研究结论", "完成内容", "限制", "遗留事项")) or re.sub(r"\s+", " ", body).strip())[:700]


def _haystack(path: Path, metadata: dict[str, Any], body: str) -> str:
    fields = (
        path.stem,
        metadata.get("record_id"),
        metadata.get("project"),
        metadata.get("summary_kind"),
        metadata.get("tags"),
        metadata.get("source_ref"),
    )
    return " ".join(stringify(value) for value in fields).casefold()


def is_decision_record(path: Path, metadata: dict[str, Any], body: str) -> bool:
    if str(metadata.get("record_type") or "").casefold() != "session":
        return False
    if is_superseded(metadata) or trust_state(metadata) != "trusted":
        return False
    kind = str(metadata.get("summary_kind") or "").casefold()
    haystack = _haystack(path, metadata, body)
    explicit = metadata.get("decision_index") is True or str(metadata.get("decision_index") or "").casefold() in {"true", "yes", "1"}
    return explicit or kind in DECISION_KINDS or any(marker.casefold() in haystack for marker in DECISION_MARKERS)


def build_entries(vault: Path) -> list[dict[str, Any]]:
    config = load_config(vault)
    entries: list[dict[str, Any]] = []
    for path in iter_record_paths(vault, config):
        metadata, body = split_frontmatter(path.read_text(encoding="utf-8"), strict=False)
        if not is_decision_record(path, metadata, body):
            continue
        entries.append({
            "record_id": metadata.get("record_id"),
            "record_type": "session",
            "title": path.stem,
            "project": stringify(metadata.get("project")),
            "summary_kind": str(metadata.get("summary_kind") or ""),
            "topics": stringify(metadata.get("tags")),
            "summary": _summary(metadata, body),
            "source_ref": stringify(metadata.get("source_ref")),
            "updated": str(metadata.get("updated") or metadata.get("created") or ""),
            "last_verified": str(metadata.get("last_verified") or metadata.get("updated") or ""),
            "trust_state": trust_state(metadata),
            "relative_path": path.relative_to(vault).as_posix(),
        })
    return sorted(entries, key=lambda item: (item.get("updated", ""), item.get("title", "")), reverse=True)


def build_index(vault: Path) -> dict[str, Any]:
    entries = build_entries(vault)
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": date.today().isoformat(),
        "record_count": len(entries),
        "entries": entries,
    }


def save_index(vault: Path, output: Path | None = None) -> Path:
    path = output or index_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_index(vault), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_index(vault: Path) -> dict[str, Any] | None:
    path = index_path(vault)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("entries"), list) else None


def score_entry(entry: dict[str, Any], query: str) -> tuple[int, list[str]]:
    query_lower = query.casefold().strip()
    query_tokens = tokens(query)
    title = str(entry.get("title") or "").casefold()
    identity = " ".join(stringify(entry.get(key)) for key in ("title", "record_id", "topics", "source_ref")).casefold()
    text = " ".join(stringify(entry.get(key)) for key in ("title", "record_id", "project", "summary_kind", "topics", "summary", "source_ref")).casefold()
    matched = [token for token in query_tokens if token in text]
    score = 0
    for token in matched:
        score += 6
        if token in title:
            score += 12
        elif token in identity and re.fullmatch(r"[a-z0-9_.+-]{4,}", token):
            score += 8
    if query_lower and query_lower in title:
        score += 30
    elif query_lower and query_lower in text:
        score += 12
    if entry.get("summary_kind") in DECISION_KINDS:
        score += 8
    for marker in DECISION_MARKERS:
        if marker.casefold() in query_lower and marker.casefold() in text:
            score += 10
    return score, matched


def search_entries(vault: Path, entries: list[dict[str, Any]], query: str, limit: int = 3) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in entries:
        score, matched = score_entry(entry, query)
        if score <= 0:
            continue
        results.append({
            **entry,
            "score": score,
            "matched": matched,
            "path": str(vault / entry["relative_path"]),
            "root_cause": "",
            "solution_type": "decision-evidence",
            "snippet": entry.get("summary") or "",
        })
    results.sort(key=lambda item: (-int(item["score"]), item.get("updated", ""), item.get("title", "")))
    return results[: max(1, limit)]


def search_index(vault: Path, query: str, limit: int = 3) -> list[dict[str, Any]] | None:
    payload = load_index(vault)
    if payload is None:
        return None
    return search_entries(vault, payload["entries"], query, limit=limit)
