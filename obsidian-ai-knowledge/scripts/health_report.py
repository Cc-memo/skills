from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from common import iter_record_paths, knowledge_root, load_config, resolve_vault, split_frontmatter
from validate_knowledge import validate_vault


REPORT_NAME = "知识库健康报告.md"
FORMAL_TYPES = {"project", "problem", "session", "playbook"}


def date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def text_value(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else "未标注"


def body_size(body: str) -> int:
    without_code = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    without_headings = re.sub(r"^#{1,6}\s+.*$", "", without_code, flags=re.MULTILINE)
    without_markup = re.sub(r"[\s>*_`#|\[\]()-]+", "", without_headings)
    return len(without_markup)


def record_link(vault: Path, path: Path) -> str:
    target = path.relative_to(vault).with_suffix("").as_posix()
    return f"[[{target}|{path.stem}]]"


def issue_item(vault: Path, path: Path, metadata: dict[str, Any], *, age_days: int | None = None) -> dict[str, Any]:
    item = {
        "path": path.relative_to(vault).as_posix(),
        "title": path.stem,
        "link": record_link(vault, path),
        "record_type": text_value(metadata.get("record_type")),
    }
    if age_days is not None:
        item["age_days"] = age_days
    return item


def run_health(vault: Path, today: date | None = None) -> dict[str, Any]:
    vault = resolve_vault(vault)
    today = today or date.today()
    config = load_config(vault)
    quality = config.get("quality", {})
    thresholds = {
        "inbox_review_days": int(quality.get("inbox_review_days", 7)),
        "open_problem_review_days": int(quality.get("open_problem_review_days", 30)),
        "draft_playbook_review_days": int(quality.get("draft_playbook_review_days", 30)),
        "recent_session_days": int(quality.get("recent_session_days", 14)),
        "stub_body_chars": int(quality.get("stub_body_chars", 120)),
    }
    counters = {
        "record_type": Counter(),
        "status": Counter(),
        "review_state": Counter(),
        "confidence": Counter(),
        "source": Counter(),
        "ai_tool": Counter(),
    }
    issues: dict[str, list[dict[str, Any]]] = {
        "pending_review": [],
        "stale_inbox": [],
        "stale_problems": [],
        "projects_without_next_action": [],
        "overdue_project_reviews": [],
        "stale_project_sources": [],
        "unknown_project_sources": [],
        "stale_draft_playbooks": [],
        "low_confidence_formal": [],
        "stubs": [],
        "unreadable_records": [],
    }
    latest_session: date | None = None

    for path in iter_record_paths(vault, config):
        try:
            metadata, body = split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            issues["unreadable_records"].append(
                {"path": path.relative_to(vault).as_posix(), "title": path.stem, "error": str(exc)}
            )
            continue

        record_type = text_value(metadata.get("record_type"))
        counters["record_type"][record_type] += 1
        if record_type in FORMAL_TYPES | {"inbox"}:
            for key in ("status", "review_state", "confidence", "source"):
                counters[key][text_value(metadata.get(key))] += 1
            if metadata.get("ai_tool") not in (None, ""):
                counters["ai_tool"][text_value(metadata.get("ai_tool"))] += 1

        updated = date_value(metadata.get("updated")) or date_value(metadata.get("created"))
        age_days = (today - updated).days if updated else None
        item = issue_item(vault, path, metadata, age_days=age_days)

        if metadata.get("review_state") == "pending" or (record_type == "inbox" and metadata.get("status") == "pending"):
            issues["pending_review"].append(item)
        if record_type == "inbox" and metadata.get("status") == "pending" and age_days is not None:
            if age_days > thresholds["inbox_review_days"]:
                issues["stale_inbox"].append(item)
        if record_type == "problem" and metadata.get("status") in {"open", "investigating"} and age_days is not None:
            if age_days > thresholds["open_problem_review_days"]:
                issues["stale_problems"].append(item)
        if record_type == "project" and metadata.get("status") == "active" and not str(metadata.get("next_action") or "").strip():
            issues["projects_without_next_action"].append(item)
        if record_type == "project" and metadata.get("status") in {"planned", "active", "blocked"}:
            review_due = date_value(metadata.get("review_due"))
            if review_due and review_due < today:
                review_item = dict(item)
                review_item["due"] = review_due.isoformat()
                review_item["overdue_days"] = (today - review_due).days
                issues["overdue_project_reviews"].append(review_item)
        if record_type == "project":
            freshness_state = str(metadata.get("freshness_state") or "unknown")
            if freshness_state == "stale":
                freshness_item = dict(item)
                freshness_item["source_revision"] = text_value(metadata.get("source_revision"))
                freshness_item["observed_revision"] = text_value(metadata.get("source_observed_revision"))
                issues["stale_project_sources"].append(freshness_item)
            elif freshness_state == "unknown":
                issues["unknown_project_sources"].append(item)
        if record_type == "playbook" and metadata.get("maturity") == "draft" and age_days is not None:
            if age_days > thresholds["draft_playbook_review_days"]:
                item["evidence_count"] = len(metadata.get("evidence") or [])
                issues["stale_draft_playbooks"].append(item)
        if record_type in FORMAL_TYPES and metadata.get("confidence") == "low":
            issues["low_confidence_formal"].append(item)
        if record_type in FORMAL_TYPES | {"inbox"} and body_size(body) < thresholds["stub_body_chars"]:
            item["body_chars"] = body_size(body)
            issues["stubs"].append(item)
        if record_type == "session":
            session_date = date_value(metadata.get("completed_at")) or updated
            if session_date and (latest_session is None or session_date > latest_session):
                latest_session = session_date

    validation = validate_vault(vault)
    session_gap_days = (today - latest_session).days if latest_session else None
    recent_session_gap = latest_session is None or session_gap_days > thresholds["recent_session_days"]
    action_count = sum(len(items) for items in issues.values())
    action_count += len(validation["errors"]) + len(validation["warnings"])
    action_count += int(recent_session_gap)

    return {
        "generated_for": today.isoformat(),
        "thresholds": thresholds,
        "counts": {name: dict(sorted(counter.items())) for name, counter in counters.items()},
        "issues": issues,
        "latest_session": latest_session.isoformat() if latest_session else None,
        "session_gap_days": session_gap_days,
        "recent_session_gap": recent_session_gap,
        "validation": validation,
        "action_count": action_count,
    }


def table(counter: dict[str, int]) -> str:
    if not counter:
        return "_暂无数据_"
    lines = ["| 值 | 数量 |", "| --- | ---: |"]
    lines.extend(f"| {key} | {value} |" for key, value in counter.items())
    return "\n".join(lines)


def issue_lines(items: list[dict[str, Any]], empty: str = "无") -> list[str]:
    if not items:
        return [f"- {empty}"]
    lines = []
    for item in items:
        details = []
        if "age_days" in item:
            details.append(f"距上次更新 {item['age_days']} 天")
        if "body_chars" in item:
            details.append(f"有效正文 {item['body_chars']} 字符")
        if "evidence_count" in item:
            details.append(f"证据 {item['evidence_count']} 条")
        if "due" in item:
            details.append(f"复核到期 {item['due']}")
        if "overdue_days" in item:
            details.append(f"超期 {item['overdue_days']} 天")
        if "error" in item:
            details.append(item["error"])
        suffix = f"（{'；'.join(details)}）" if details else ""
        link = item.get("link") or f"`{item['path']}`"
        lines.append(f"- {link}{suffix}")
    return lines


def render_report(result: dict[str, Any]) -> str:
    validation = result["validation"]
    issues = result["issues"]
    latest = result["latest_session"] or "无会话记录"
    session_status = (
        f"需要关注：距最近会话 {result['session_gap_days']} 天"
        if result["recent_session_gap"] and result["session_gap_days"] is not None
        else "需要关注：尚无会话记录"
        if result["recent_session_gap"]
        else f"正常：距最近会话 {result['session_gap_days']} 天"
    )
    lines = [
        "---",
        "record_type: system",
        "record_id: system-knowledge-health",
        "status: active",
        f"created: {result['generated_for']}",
        f"updated: {result['generated_for']}",
        "cssclasses:",
        "  - ai-knowledge",
        "  - ai-health",
        "tags:",
        "  - AI知识库",
        "  - 健康检查",
        "---",
        "",
        "# 知识库健康报告",
        "",
        "> [!info] 报告性质",
        "> 这是确定性维护提示，不替代 schema、链接、来源与敏感信息校验。报告仅在内容变化时改写。",
        "",
        "## 总览",
        "",
        f"- 报告日期：{result['generated_for']}",
        f"- 正式记录：{sum(result['counts']['record_type'].get(kind, 0) for kind in FORMAL_TYPES)}",
        f"- Inbox：{result['counts']['record_type'].get('inbox', 0)}",
        f"- 待处理信号：{result['action_count']}",
        f"- 最近会话：{latest}（{session_status}）",
        f"- 验证：{len(validation['errors'])} errors / {len(validation['warnings'])} warnings",
        "",
        "## 待处理",
        "",
        f"### 待审核记录（{len(issues['pending_review'])}）",
        "",
        *issue_lines(issues["pending_review"]),
        "",
        f"### Inbox 超期（{len(issues['stale_inbox'])}）",
        "",
        *issue_lines(issues["stale_inbox"]),
        "",
        f"### 长期未解决问题（{len(issues['stale_problems'])}）",
        "",
        *issue_lines(issues["stale_problems"]),
        "",
        f"### 活跃项目缺少下一步（{len(issues['projects_without_next_action'])}）",
        "",
        *issue_lines(issues["projects_without_next_action"]),
        "",
        f"### 项目复核到期（{len(issues['overdue_project_reviews'])}）",
        "",
        *issue_lines(issues["overdue_project_reviews"]),
        "",
        f"### 项目来源已变化（{len(issues['stale_project_sources'])}）",
        "",
        *issue_lines(issues["stale_project_sources"]),
        "",
        f"### 项目来源新鲜度未知（{len(issues['unknown_project_sources'])}）",
        "",
        *issue_lines(issues["unknown_project_sources"]),
        "",
        f"### 草稿经验待复核（{len(issues['stale_draft_playbooks'])}）",
        "",
        *issue_lines(issues["stale_draft_playbooks"]),
        "",
        f"### 低置信度正式记录（{len(issues['low_confidence_formal'])}）",
        "",
        *issue_lines(issues["low_confidence_formal"]),
        "",
        f"### 空壳记录（{len(issues['stubs'])}）",
        "",
        *issue_lines(issues["stubs"]),
        "",
        f"### 无法读取记录（{len(issues['unreadable_records'])}）",
        "",
        *issue_lines(issues["unreadable_records"]),
        "",
        "## 来源覆盖",
        "",
        "### source",
        "",
        table(result["counts"]["source"]),
        "",
        "### ai_tool",
        "",
        table(result["counts"]["ai_tool"]),
        "",
        "## 分布",
        "",
        "### record_type",
        "",
        table(result["counts"]["record_type"]),
        "",
        "### status",
        "",
        table(result["counts"]["status"]),
        "",
        "### review_state",
        "",
        table(result["counts"]["review_state"]),
        "",
        "### confidence",
        "",
        table(result["counts"]["confidence"]),
        "",
        "## 验证摘要",
        "",
        f"- Errors：{len(validation['errors'])}",
        f"- Warnings：{len(validation['warnings'])}",
        "",
        "### Errors",
        "",
        *(f"- {item}" for item in validation["errors"]),
        *([] if validation["errors"] else ["- 无"]),
        "",
        "### Warnings",
        "",
        *(f"- {item}" for item in validation["warnings"]),
        *([] if validation["warnings"] else ["- 无"]),
        "",
        "## 维护阈值",
        "",
        f"- Inbox 复核：{result['thresholds']['inbox_review_days']} 天",
        f"- 未解决问题复核：{result['thresholds']['open_problem_review_days']} 天",
        f"- 草稿经验复核：{result['thresholds']['draft_playbook_review_days']} 天",
        f"- 最近会话窗口：{result['thresholds']['recent_session_days']} 天",
        f"- 空壳正文下限：{result['thresholds']['stub_body_chars']} 字符",
        "",
    ]
    return "\n".join(lines)


def save_report(vault: Path, result: dict[str, Any]) -> tuple[Path, bool]:
    config = load_config(vault)
    path = knowledge_root(vault, config) / "_系统" / REPORT_NAME
    content = render_report(result)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return path, False
    path.write_text(content, encoding="utf-8", newline="\n")
    return path, True


def refresh_report(vault: Path, today: date | None = None) -> tuple[dict[str, Any], Path, bool]:
    result = run_health(vault, today=today)
    path, first_changed = save_report(vault, result)
    result = run_health(vault, today=today)
    path, second_changed = save_report(vault, result)
    return result, path, first_changed or second_changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an advisory health report for the Obsidian AI knowledge base.")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when the report contains action items.")
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    result = run_health(vault)
    if args.save:
        result, path, changed = refresh_report(vault)
        result["report_path"] = str(path)
        result["report_changed"] = changed
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Health: {result['action_count']} action items")
        print(f"Validation: {len(result['validation']['errors'])} errors, {len(result['validation']['warnings'])} warnings")
        if args.save:
            state = "updated" if result["report_changed"] else "unchanged"
            print(f"Report: {result['report_path']} ({state})")
    return 1 if args.strict and result["action_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
