from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from common import iter_record_paths, knowledge_root, load_config, normalize_wikilink, resolve_vault, split_frontmatter


RESEARCH_KINDS = {"decision", "method", "research", "retrospective"}
POSITIVE_VALIDATION = re.compile(
    r"(?:\bpassed\b|\bverified\b|\bsuccess(?:ful)?\b|通过|验证完成|验证成功|无错误|未发现(?:错误|异常|问题)|0\s+errors?|0\s+warnings?)",
    re.IGNORECASE,
)
NEGATIVE_VALIDATION = re.compile(
    r"(?:\bfailed\b|\bnot\s+run\b|\buntested\b|\bpending\s+(?:validation|verification|tests?)\b|\b(?:validation|verification|tests?)\s+pending\b|尚未|未验证|未测试|待验证|验证失败|未通过|无法验证|仍需(?:验证|测试|验收))",
    re.IGNORECASE,
)
STRONG_NEGATIVE_VALIDATION = re.compile(
    r"(?:\bfailed\b|\bnot\s+run\b|\buntested\b|尚未|未验证|未测试|验证失败|未通过|无法验证|仍需(?:验证|测试|验收))",
    re.IGNORECASE,
)
EMPTY_VALUES = {"", "-", "无", "暂无", "不适用", "none", "n/a", "null", "[]"}


@dataclass
class RecordAnalysis:
    path: Path
    metadata: dict[str, Any]
    title: str
    record_date: date | None
    project: str
    category: str
    validation_state: str
    score: int
    reasons: list[str]
    deliverables: list[str]
    changed_files: list[str]
    validation_evidence: list[str]
    decisions: list[str]
    next_action: str


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return "\n".join(as_text(item) for item in value)
    return str(value).strip()


def as_items(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        text = as_text(item).strip()
        if text.casefold() in EMPTY_VALUES:
            continue
        if text:
            result.append(text)
    return result


def parse_record_date(metadata: dict[str, Any]) -> date | None:
    for key in ("completed_at", "updated", "created"):
        value = metadata.get(key)
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = as_text(value)
        if not text:
            continue
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                continue
    return None


def note_title(path: Path, body: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
    return match.group(1).strip() if match else path.stem


def extract_section(body: str, names: tuple[str, ...]) -> str:
    alternatives = "|".join(re.escape(name) for name in names)
    match = re.search(
        rf"(?ms)^##\s+(?:{alternatives})\s*$\n(.*?)(?=^##\s+|\Z)",
        body,
    )
    return match.group(1).strip() if match else ""


def section_items(section: str, *, limit: int = 12) -> list[str]:
    if not section:
        return []
    result: list[str] = []
    in_fence = False
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or line.startswith((">", "<!--")):
            continue
        line = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+|#{1,6}\s+)", "", line).strip()
        if line.casefold() in EMPTY_VALUES or not line:
            continue
        result.append(line)
        if len(result) >= limit:
            break
    return result


def project_name(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    text = as_text(value)
    if not text:
        return ""
    match = re.search(r"\[\[([^\]]+)\]\]", text)
    target = normalize_wikilink(match.group(1) if match else text)
    return Path(target).name


def explicit_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return as_text(value).casefold() in {"true", "yes", "1"}


def validation_state(metadata: dict[str, Any], evidence: list[str]) -> str:
    explicit = as_text(metadata.get("validation_state")).casefold().replace("-", "_")
    evidence_text = "\n".join(evidence)
    negative_text = re.sub(r"`?0`?\s+(?:failed|failures?|errors?|warnings?)\b", "", evidence_text, flags=re.IGNORECASE)
    positive = bool(POSITIVE_VALIDATION.search(evidence_text))
    negative = bool(NEGATIVE_VALIDATION.search(negative_text))
    strong_negative = bool(STRONG_NEGATIVE_VALIDATION.search(negative_text))

    if explicit in {"failed", "failure"}:
        return "failed"
    if explicit in {"partial", "partially_passed"}:
        return "partial"
    if explicit in {"not_run", "pending", "unknown"}:
        return "not_run"
    if explicit in {"not_applicable", "n_a", "na"}:
        return "not_applicable"
    if explicit in {"passed", "verified", "success"}:
        return "partial" if strong_negative else "passed"
    if positive and negative:
        return "partial"
    if negative:
        return "not_run"
    if positive:
        return "passed"
    return "unknown"


def is_superseded(metadata: dict[str, Any]) -> bool:
    if as_items(metadata.get("superseded_by")):
        return True
    lifecycle = as_text(metadata.get("lifecycle_state")).casefold()
    return lifecycle in {"withdrawn", "superseded", "reverted", "deprecated"}


def analyze_session(path: Path, metadata: dict[str, Any], body: str) -> RecordAnalysis:
    deliverables = as_items(metadata.get("deliverables"))
    deliverables.extend(section_items(extract_section(body, ("交付物", "产出"))))
    changed_files = as_items(metadata.get("changed_files"))
    changed_files.extend(section_items(extract_section(body, ("变更文件", "修改文件"))))
    validation_evidence = as_items(metadata.get("validation_evidence"))
    validation_evidence.extend(section_items(extract_section(body, ("验证结果", "验证", "测试结果"))))
    decisions = as_items(metadata.get("key_decisions"))
    decisions.extend(section_items(extract_section(body, ("关键决策", "结论与决策", "结论"))))
    reusable = section_items(extract_section(body, ("可复用知识", "可复用结论", "经验")))
    next_items = as_items(metadata.get("next_action"))
    next_items.extend(section_items(extract_section(body, ("遗留事项", "下一步")), limit=3))

    validation = validation_state(metadata, validation_evidence)
    summary_kind = as_text(metadata.get("summary_kind")).casefold()
    outcome = as_text(metadata.get("outcome")).casefold()
    review_state = as_text(metadata.get("review_state")).casefold()
    source_ref = as_text(metadata.get("source_ref"))
    project = project_name(metadata.get("project"))

    tangible_output = bool(
        explicit_bool(metadata.get("actual_output"))
        or as_text(metadata.get("output_type"))
        or deliverables
        or changed_files
    )
    research_output = summary_kind in RESEARCH_KINDS and bool(source_ref and decisions)
    reviewed = review_state in {"reviewed", "promoted"}
    superseded = is_superseded(metadata)

    reasons: list[str] = []
    if tangible_output:
        reasons.append("存在交付物或变更证据")
    if research_output:
        reasons.append("来源与关键决策可复核")
    if validation == "passed":
        reasons.append("验证通过")
    elif validation == "partial":
        reasons.append("仅部分验证")
    elif validation in {"not_run", "unknown"}:
        reasons.append("缺少完整验证")
    if reviewed:
        reasons.append("已审核")
    else:
        reasons.append("待审核")

    if superseded:
        category = "superseded"
        reasons = ["已被后续结论取代或撤回"]
    elif research_output and reviewed:
        category = "knowledge-output"
    elif research_output:
        category = "needs-review"
    elif tangible_output and validation == "passed" and outcome == "success" and reviewed:
        category = "verified-delivery"
    elif tangible_output and validation == "passed" and outcome == "success":
        category = "needs-review"
    elif tangible_output:
        category = "needs-validation"
    elif outcome == "success" or decisions:
        category = "needs-evidence"
    else:
        category = "incomplete"

    score = 0
    if tangible_output or research_output:
        score += 25
    if deliverables or changed_files or (source_ref and decisions):
        score += 20
    if validation == "passed":
        score += 25
    elif validation == "partial":
        score += 10
    elif research_output and reviewed:
        score += 20
    if outcome == "success":
        score += 10
    elif outcome == "partial":
        score += 5
    if reviewed:
        score += 10
    if project:
        score += 5
    if reusable or next_items or decisions:
        score += 5
    if superseded:
        score = 0

    return RecordAnalysis(
        path=path,
        metadata=metadata,
        title=note_title(path, body),
        record_date=parse_record_date(metadata),
        project=project,
        category=category,
        validation_state=validation,
        score=min(score, 100),
        reasons=reasons,
        deliverables=deliverables,
        changed_files=changed_files,
        validation_evidence=validation_evidence,
        decisions=decisions,
        next_action=next_items[0] if next_items else "",
    )


def record_link(vault: Path, path: Path, title: str) -> str:
    relative = path.relative_to(vault).with_suffix("").as_posix()
    return f"[[{relative}|{title}]]"


def markdown_cell(value: Any, *, limit: int = 140) -> str:
    text = as_text(value).replace("\n", "；").replace("|", "\\|").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or "—"


def analyze_vault(vault: Path, *, today: date | None = None, recent_days: int = 30) -> dict[str, Any]:
    today = today or date.today()
    config = load_config(vault)
    sessions: list[RecordAnalysis] = []
    projects: list[tuple[Path, dict[str, Any], str]] = []
    problems: list[tuple[Path, dict[str, Any], str]] = []

    for path in iter_record_paths(vault, config):
        try:
            metadata, body = split_frontmatter(path.read_text(encoding="utf-8"), strict=False)
        except (OSError, UnicodeError, ValueError):
            continue
        record_type = as_text(metadata.get("record_type")).casefold()
        if record_type == "session":
            sessions.append(analyze_session(path, metadata, body))
        elif record_type == "project":
            projects.append((path, metadata, note_title(path, body)))
        elif record_type == "problem":
            problems.append((path, metadata, note_title(path, body)))

    sessions.sort(key=lambda item: (item.record_date or date.min, item.path.stat().st_mtime), reverse=True)
    cutoff = today - timedelta(days=recent_days)
    recent_sessions = [item for item in sessions if item.record_date is None or item.record_date >= cutoff]
    open_problems = [item for item in problems if as_text(item[1].get("status")).casefold() in {"open", "investigating"}]

    sessions_by_project: dict[str, list[RecordAnalysis]] = defaultdict(list)
    problems_by_project: dict[str, list[tuple[Path, dict[str, Any], str]]] = defaultdict(list)
    for item in sessions:
        if item.project:
            sessions_by_project[item.project].append(item)
    for item in open_problems:
        name = project_name(item[1].get("project"))
        if name:
            problems_by_project[name].append(item)

    active_projects: list[dict[str, Any]] = []
    for path, metadata, title in projects:
        if as_text(metadata.get("status")).casefold() not in {"active", "blocked", "planned"}:
            continue
        risks: list[str] = []
        freshness = as_text(metadata.get("freshness_state")).casefold() or "unknown"
        if freshness == "stale":
            risks.append("仓库基线已过期")
        elif freshness == "unknown":
            risks.append("仓库新鲜度未知")
        next_action = as_text(metadata.get("next_action"))
        if not next_action:
            risks.append("缺少下一步")
        if problems_by_project.get(title):
            risks.append(f"有 {len(problems_by_project[title])} 个未解决问题")
        recent = [item for item in sessions_by_project.get(title, []) if item.record_date is None or item.record_date >= cutoff]
        if recent and recent[0].category in {"needs-validation", "needs-review", "needs-evidence", "incomplete"}:
            risks.append("最近会话尚未形成已验证产出")
        if not any(item.category in {"verified-delivery", "knowledge-output"} for item in recent):
            risks.append(f"近 {recent_days} 天无已确认产出")
        review_due = parse_record_date({"updated": metadata.get("review_due")})
        if review_due and review_due < today:
            risks.append("项目复盘已逾期")
        active_projects.append(
            {
                "path": path,
                "title": title,
                "status": as_text(metadata.get("status")),
                "freshness": freshness,
                "next_action": next_action,
                "risks": risks,
            }
        )

    counts = defaultdict(int)
    for item in recent_sessions:
        counts[item.category] += 1

    actions: list[str] = []
    for item in recent_sessions:
        if item.category == "needs-validation":
            actions.append(f"补充验证：{record_link(vault, item.path, item.title)}")
        elif item.category == "needs-review":
            actions.append(f"完成审核：{record_link(vault, item.path, item.title)}")
        elif item.category == "needs-evidence":
            actions.append(f"补充交付物、变更文件或来源证据：{record_link(vault, item.path, item.title)}")
        if len(actions) >= 4:
            break
    for project in active_projects:
        if project["risks"]:
            actions.append(f"处理项目风险：{record_link(vault, project['path'], project['title'])}（{project['risks'][0]}）")
        if len(actions) >= 6:
            break
    if not actions:
        actions.append("当前没有高优先级证据缺口；继续按项目下一步推进。")

    return {
        "today": today,
        "recent_days": recent_days,
        "sessions": sessions,
        "recent_sessions": recent_sessions,
        "active_projects": active_projects,
        "open_problems": open_problems,
        "counts": dict(counts),
        "actions": actions,
    }


def render_session_table(vault: Path, items: list[RecordAnalysis], *, limit: int = 20) -> list[str]:
    lines = ["| 日期 | 记录 | 项目 | 分数 | 判定依据 |", "|---|---|---|---:|---|"]
    for item in items[:limit]:
        evidence = "；".join(item.reasons[:3])
        lines.append(
            "| "
            + " | ".join(
                [
                    item.record_date.isoformat() if item.record_date else "—",
                    record_link(vault, item.path, item.title),
                    markdown_cell(item.project),
                    str(item.score),
                    markdown_cell(evidence),
                ]
            )
            + " |"
        )
    if len(lines) == 2:
        lines.append("| — | 暂无 | — | — | — |")
    return lines


def render_report(vault: Path, analysis: dict[str, Any]) -> str:
    today: date = analysis["today"]
    recent_days: int = analysis["recent_days"]
    recent_sessions: list[RecordAnalysis] = analysis["recent_sessions"]
    groups: dict[str, list[RecordAnalysis]] = defaultdict(list)
    for item in recent_sessions:
        groups[item.category].append(item)

    lines = [
        "---",
        "record_type: dashboard",
        "record_id: dashboard-actual-output",
        "status: active",
        f"updated: {today.isoformat()}",
        "cssclasses:",
        "  - ai-knowledge",
        "  - ai-output-center",
        "tags:",
        "  - AI知识库",
        "  - 实际产出",
        "---",
        "",
        "# 实际产出中心",
        "",
        '<div class="ai-output-hero">只统计有交付、来源、验证或明确决策证据的结果；规则分析不冒充模型判断。</div>',
        "",
        "> [!info] 判定口径",
        "> 代码、配置和文档优先看交付物、变更文件与验证；研究和决策优先看 `source_ref`、关键决策与审核状态。分数只用于排序，最终分类由证据状态决定。",
        "",
        "## 今日行动建议",
        "",
    ]
    lines.extend(f"- {action}" for action in analysis["actions"])
    counts = analysis["counts"]
    lines.extend(
        [
            "",
            "## 核心统计",
            "",
            '<div class="ai-output-stats">',
            f'<div><strong>{counts.get("verified-delivery", 0)}</strong><span>已验证交付</span></div>',
            f'<div><strong>{counts.get("knowledge-output", 0)}</strong><span>知识产出</span></div>',
            f'<div><strong>{counts.get("needs-validation", 0)}</strong><span>待验证</span></div>',
            f'<div><strong>{counts.get("needs-review", 0)}</strong><span>待审核</span></div>',
            f'<div><strong>{counts.get("needs-evidence", 0)}</strong><span>缺证据</span></div>',
            "</div>",
            "",
            f"> 统计窗口：最近 {recent_days} 天；已取代记录单独列出，不计入当前产出。",
            "",
            "## 已验证交付",
            "",
        ]
    )
    lines.extend(render_session_table(vault, groups["verified-delivery"]))
    lines.extend(["", "## 研究与决策产出", ""])
    lines.extend(render_session_table(vault, groups["knowledge-output"]))
    lines.extend(["", "## 待验证产出", ""])
    lines.extend(render_session_table(vault, groups["needs-validation"]))
    lines.extend(["", "## 待审核产出", ""])
    lines.extend(render_session_table(vault, groups["needs-review"]))
    lines.extend(["", "## 证据不足或未完成", ""])
    lines.extend(render_session_table(vault, groups["needs-evidence"] + groups["incomplete"]))
    lines.extend(["", "## 已取代或撤回", ""])
    lines.extend(render_session_table(vault, groups["superseded"]))

    lines.extend(["", "## 活跃项目状态", "", "| 项目 | 状态 | 新鲜度 | 风险 | 下一步 |", "|---|---|---|---|---|"])
    for project in analysis["active_projects"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    record_link(vault, project["path"], project["title"]),
                    markdown_cell(project["status"]),
                    markdown_cell(project["freshness"]),
                    markdown_cell("；".join(project["risks"]) if project["risks"] else "无明显风险"),
                    markdown_cell(project["next_action"]),
                ]
            )
            + " |"
        )
    if not analysis["active_projects"]:
        lines.append("| 暂无 | — | — | — | — |")

    lines.extend(["", "## 未解决问题", "", "| 问题 | 项目 | 状态 | 严重度 |", "|---|---|---|---|"])
    for path, metadata, title in analysis["open_problems"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    record_link(vault, path, title),
                    markdown_cell(project_name(metadata.get("project"))),
                    markdown_cell(metadata.get("status")),
                    markdown_cell(metadata.get("severity")),
                ]
            )
            + " |"
        )
    if not analysis["open_problems"]:
        lines.append("| 暂无 | — | — | — |")

    lines.extend(
        [
            "",
            "## 评分解释",
            "",
            "- 明确产出：25 分。",
            "- 交付物、变更文件，或研究来源加关键决策：20 分。",
            "- 验证通过：25 分；部分验证：10 分。",
            "- 成功结果：10 分；已审核：10 分；项目关联：5 分；复用结论、决策或下一步：5 分。",
            "- `verified-delivery` 必须同时满足实际产出、验证通过、成功结果和已审核，不能靠高分替代。",
            "- `knowledge-output` 必须满足研究/决策类型、稳定来源、关键决策和已审核，不要求伪造代码测试。",
            "",
            f"_生成日期：{today.isoformat()}_",
            "",
        ]
    )
    return "\n".join(lines)


def save_report(vault: Path, analysis: dict[str, Any], output: Path | None = None) -> Path:
    config = load_config(vault)
    target = output or knowledge_root(vault, config) / "_系统" / "实际产出报告.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(vault, analysis), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an evidence-first actual-output report for the Obsidian AI knowledge vault.")
    parser.add_argument("--vault", type=Path, help="Obsidian vault path")
    parser.add_argument("--recent-days", type=int, default=30, help="Recent session window")
    parser.add_argument("--save", action="store_true", help="Write the Markdown report")
    parser.add_argument("--json", action="store_true", help="Print summary as JSON")
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    analysis = analyze_vault(vault, recent_days=max(1, args.recent_days))
    output = save_report(vault, analysis) if args.save else None
    summary = {
        "recent_days": analysis["recent_days"],
        "counts": analysis["counts"],
        "active_projects": len(analysis["active_projects"]),
        "open_problems": len(analysis["open_problems"]),
        "output": str(output) if output else None,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Actual output report: {output or 'not saved'}")
        print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())