from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from common import iter_record_paths, load_config, resolve_vault, split_frontmatter
from output_report import analyze_session


SEARCH_FIELDS = (
    "record_id",
    "tags",
    "project",
    "area",
    "symptoms",
    "error_signatures",
    "error_signature",
    "technologies",
    "technology",
    "aliases",
    "alias",
    "root_cause",
    "solution_type",
    "applies_to",
    "next_action",
    "summary_kind",
    "deliverables",
    "changed_files",
    "validation_evidence",
    "key_decisions",
    "source_ref",
)


def tokens(query: str) -> list[str]:
    normalized = query.casefold().strip()
    parts = re.findall(r"[a-z0-9_.+-]+|[\u4e00-\u9fff]+", normalized)
    result: list[str] = []
    for part in parts:
        result.append(part)
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", part):
            result.extend(part[index : index + 2] for index in range(len(part) - 1))
    return list(dict.fromkeys(result))


def load_retrieval_routes(vault: Path, config: dict[str, Any] | None = None) -> dict[str, Any]:
    current_config = config or load_config(vault)
    configured = current_config.get("retrieval_routes")
    if not configured:
        return {}
    path = Path(str(configured)).expanduser()
    if not path.is_absolute():
        path = vault / path
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def expanded_query_tokens(
    vault: Path,
    query: str,
    config: dict[str, Any] | None = None,
) -> tuple[list[str], set[str]]:
    original = tokens(query)
    original_set = set(original)
    normalized = query.casefold()
    routes = load_retrieval_routes(vault, config)
    groups = routes.get("query_expansions") or {}
    if isinstance(groups, list):
        iterable = enumerate(groups)
    elif isinstance(groups, dict):
        iterable = groups.items()
    else:
        iterable = []

    expanded: list[str] = []
    for _, aliases in iterable:
        if not isinstance(aliases, list):
            continue
        normalized_aliases = [str(alias).casefold().strip() for alias in aliases if str(alias).strip()]
        if not any(alias in normalized for alias in normalized_aliases):
            continue
        for alias in normalized_aliases:
            for token in tokens(alias):
                if token not in original_set and token not in expanded:
                    expanded.append(token)
    return original + expanded, set(expanded)


def stringify(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(map(str, value))
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    return "" if value is None else str(value)


def recency_bonus(value: Any) -> int:
    if not value:
        return 0
    try:
        updated = value if isinstance(value, date) else datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return 0
    age = (date.today() - updated).days
    if age <= 30:
        return 5
    if age <= 180:
        return 3
    if age <= 365:
        return 1
    return 0


def is_superseded(metadata: dict[str, Any]) -> bool:
    if metadata.get("superseded_by"):
        return True
    lifecycle = str(metadata.get("lifecycle_state") or "").casefold()
    return lifecycle in {"withdrawn", "superseded", "reverted", "deprecated"}


def trust_state(metadata: dict[str, Any]) -> str:
    if is_superseded(metadata):
        return "superseded"
    output_category = str(metadata.get("_output_category") or "").casefold()
    if output_category in {"verified-delivery", "knowledge-output"}:
        return "trusted"
    if output_category == "needs-review":
        return "pending-review"
    if output_category in {"needs-validation", "needs-evidence", "incomplete"}:
        return "unverified"
    review = str(metadata.get("review_state") or "").casefold()
    confidence = str(metadata.get("confidence") or "").casefold()
    validation = str(metadata.get("validation_state") or "").casefold().replace("-", "_")
    if confidence == "low":
        return "low-confidence"
    if validation in {"failed", "partial", "not_run", "pending"}:
        return "unverified"
    if review == "pending":
        return "pending-review"
    if review in {"reviewed", "promoted"}:
        return "trusted"
    return "unreviewed"


def evidence_bonus(metadata: dict[str, Any]) -> int:
    if is_superseded(metadata):
        return -100
    score = 0
    review = str(metadata.get("review_state") or "").casefold()
    confidence = str(metadata.get("confidence") or "").casefold()
    record_type = str(metadata.get("record_type") or "").casefold()
    status = str(metadata.get("status") or "").casefold()
    validation = str(metadata.get("validation_state") or "").casefold().replace("-", "_")
    outcome = str(metadata.get("outcome") or "").casefold()
    maturity = str(metadata.get("maturity") or "").casefold()

    score += {"promoted": 10, "reviewed": 7, "pending": -4}.get(review, 0)
    score += {"high": 4, "medium": 1, "low": -5}.get(confidence, 0)
    if metadata.get("source_ref"):
        score += 2
    if metadata.get("summary_kind") in {"delivery", "verification", "decision", "research", "method"}:
        score += 3

    if record_type == "session":
        output_category = str(metadata.get("_output_category") or "").casefold()
        score += {
            "verified-delivery": 14,
            "knowledge-output": 12,
            "needs-review": 2,
            "needs-validation": -4,
            "needs-evidence": -8,
            "incomplete": -10,
        }.get(output_category, 0)
        score += {"passed": 10, "partial": -2, "failed": -12, "not_run": -5}.get(validation, 0)
        score += {"success": 4, "partial": 0, "failed": -8, "blocked": -6}.get(outcome, 0)
        if metadata.get("actual_output") is True:
            score += 3
    elif record_type == "problem":
        score += {"solved": 14, "closed": 10, "investigating": 4, "open": 2}.get(status, 0)
        if metadata.get("root_cause"):
            score += 4
    elif record_type == "playbook":
        score += {"stable": 16, "verified": 12, "draft": -2, "deprecated": -20}.get(maturity, 0)
    return score


def should_include(metadata: dict[str, Any], *, include_superseded: bool, trusted_only: bool) -> bool:
    state = trust_state(metadata)
    if state == "superseded" and not include_superseded:
        return False
    if trusted_only and state != "trusted":
        return False
    return True


def score_record(
    path: Path,
    metadata: dict[str, Any],
    body: str,
    query: str,
    query_tokens: list[str],
    expansion_tokens: set[str] | None = None,
    *,
    return_expanded: bool = False,
) -> tuple[int, list[str]] | tuple[int, list[str], list[str]]:
    title = path.stem.casefold()
    exact = query.casefold().strip()
    field_text = {field: stringify(metadata.get(field)).casefold() for field in SEARCH_FIELDS}
    body_text = body.casefold()
    score = recency_bonus(metadata.get("updated")) + evidence_bonus(metadata)
    matched: list[str] = []
    expanded_matched: list[str] = []
    expansion_tokens = expansion_tokens or set()

    if exact and exact in title:
        score += 30
    elif exact and exact in body_text:
        score += 8

    for token in query_tokens:
        token_score = 0
        if token in title:
            token_score += 12
        if token in field_text["record_id"]:
            token_score += 10
        if token in field_text["tags"]:
            token_score += 8
        for field in SEARCH_FIELDS[3:]:
            if token in field_text[field]:
                token_score += 6
        if token in field_text["project"]:
            token_score += 6
        if token in body_text:
            token_score += min(body_text.count(token), 4) * 2
        if token_score:
            if token in expansion_tokens:
                token_score = max(1, round(token_score * 0.4))
                expanded_matched.append(token)
            score += token_score
            matched.append(token)
    if return_expanded:
        return score, matched, expanded_matched
    return score, matched


def snippet(body: str, matched: list[str], width: int = 180) -> str:
    compact = re.sub(r"\s+", " ", body).strip()
    if not compact:
        return ""
    positions = [compact.casefold().find(token) for token in matched]
    positions = [position for position in positions if position >= 0]
    start = max((min(positions) if positions else 0) - 40, 0)
    excerpt = compact[start : start + width]
    return ("…" if start else "") + excerpt + ("…" if start + width < len(compact) else "")


def search_records(
    vault: Path,
    query: str,
    *,
    record_type: str | None = None,
    project: str | None = None,
    status: str | None = None,
    limit: int = 10,
    include_superseded: bool = False,
    trusted_only: bool = False,
    snippet_width: int = 180,
) -> list[dict[str, Any]]:
    config = load_config(vault)
    query_tokens, expansion_tokens = expanded_query_tokens(vault, query, config)
    results: list[dict[str, Any]] = []

    for path in iter_record_paths(vault, config):
        metadata, body = split_frontmatter(path.read_text(encoding="utf-8"), strict=False)
        effective_metadata = dict(metadata)
        if metadata.get("record_type") == "session":
            session_analysis = analyze_session(path, metadata, body)
            effective_metadata["validation_state"] = session_analysis.validation_state
            effective_metadata["_output_category"] = session_analysis.category
        if record_type and metadata.get("record_type") != record_type:
            continue
        if status and metadata.get("status") != status:
            continue
        if project and project.casefold() not in stringify(metadata.get("project")).casefold():
            continue
        if not should_include(effective_metadata, include_superseded=include_superseded, trusted_only=trusted_only):
            continue
        score, matched, expanded_matched = score_record(
            path,
            effective_metadata,
            body,
            query,
            query_tokens,
            expansion_tokens,
            return_expanded=True,
        )
        if score <= 0 or not matched:
            continue
        results.append(
            {
                "score": score,
                "path": str(path),
                "relative_path": str(path.relative_to(vault)),
                "title": path.stem,
                "record_type": metadata.get("record_type"),
                "record_id": metadata.get("record_id"),
                "status": metadata.get("status"),
                "updated": str(metadata.get("updated") or ""),
                "project": metadata.get("project"),
                "area": metadata.get("area"),
                "root_cause": metadata.get("root_cause"),
                "solution_type": metadata.get("solution_type"),
                "tags": metadata.get("tags"),
                "last_verified": str(metadata.get("last_verified") or ""),
                "times_used": metadata.get("times_used"),
                "superseded_by": metadata.get("superseded_by"),
                "summary_kind": metadata.get("summary_kind"),
                "review_state": metadata.get("review_state"),
                "confidence": metadata.get("confidence"),
                "validation_state": effective_metadata.get("validation_state"),
                "output_category": effective_metadata.get("_output_category"),
                "source_ref": metadata.get("source_ref"),
                "trust_state": trust_state(effective_metadata),
                "matched": matched,
                "expanded_matched": expanded_matched,
                "snippet": snippet(body, matched, width=snippet_width),
            }
        )

    results.sort(key=lambda item: (-item["score"], item["path"]))
    return results[: max(limit, 1)]


def render_context(query: str, results: list[dict[str, Any]], max_chars: int) -> str:
    lines = [
        "# AI 知识调取包",
        "",
        f"- 查询：{query}",
        "- 排序：关键词相关度 + 审核/验证/来源证据；默认排除已取代记录。",
        "- 使用：先核对来源和当前项目状态，再复用根因、决策或方法。",
        "",
    ]
    for index, item in enumerate(results, start=1):
        lines.extend(
            [
                f"## {index}. {item['title']}",
                "",
                f"- 类型：{item['record_type'] or 'unknown'} / {item['trust_state']} / score {item['score']}",
                f"- 路径：{item['path']}",
                f"- 项目：{stringify(item.get('project')) or '—'}",
                f"- 分类：{item.get('summary_kind') or '—'}",
                f"- 来源：{item.get('source_ref') or '—'}",
                f"- 命中：{', '.join(item['matched'])}",
                f"- 摘要：{item.get('snippet') or '—'}",
                "",
            ]
        )
        if len("\n".join(lines)) >= max_chars:
            lines.append("…（已按上下文预算截断）")
            break
    if not results:
        lines.extend(["## 未找到", "", "没有找到可复用的正式记录；不要假装发生了语义召回。", ""])
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 12].rstrip() + "\n…（已截断）"


def main() -> int:
    parser = argparse.ArgumentParser(description="Search verified Obsidian AI knowledge before starting similar work.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--type", dest="record_type")
    parser.add_argument("--project")
    parser.add_argument("--status")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--snippets", action="store_true")
    parser.add_argument("--context", action="store_true", help="Render a compact AI context packet")
    parser.add_argument("--max-chars", type=int, default=8000)
    parser.add_argument("--trusted-only", action="store_true")
    parser.add_argument("--include-superseded", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    results = search_records(
        vault,
        args.query,
        record_type=args.record_type,
        project=args.project,
        status=args.status,
        limit=args.limit,
        include_superseded=args.include_superseded,
        trusted_only=args.trusted_only,
        snippet_width=420 if args.context else 180,
    )
    if args.context:
        print(render_context(args.query, results, max(args.max_chars, 1000)))
    elif args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif results:
        for result in results:
            print(
                f"{result['score']:>3}  {result['trust_state']:<14}  "
                f"{result['record_type'] or '-':<9}  {result['path']}"
            )
            if args.snippets:
                print(f"     {result['snippet']}")
    else:
        print("No matching knowledge records found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
