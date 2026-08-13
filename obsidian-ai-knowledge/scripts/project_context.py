from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from common import iter_record_paths, load_config, resolve_vault, split_frontmatter
from project_space import find_project_note


FOCUS_PAGES = {
    "overview": ["07 - AI启动上下文.md", "01 - 阶段总结.md", "10 - 知识新鲜度与归档.md", "08 - 风险假设与依赖.md"],
    "status": ["01 - 阶段总结.md", "09 - 项目事件日志.md", "10 - 知识新鲜度与归档.md"],
    "implementation": ["07 - AI启动上下文.md", "01 - 阶段总结.md", "08 - 风险假设与依赖.md", "09 - 项目事件日志.md", "03 - 建议与决策.md"],
    "debugging": ["02 - 问题与报错.md", "09 - 项目事件日志.md", "08 - 风险假设与依赖.md", "07 - AI启动上下文.md"],
    "decision": ["03 - 建议与决策.md", "09 - 项目事件日志.md", "01 - 阶段总结.md"],
    "handoff": ["07 - AI启动上下文.md", "01 - 阶段总结.md", "08 - 风险假设与依赖.md", "09 - 项目事件日志.md", "10 - 知识新鲜度与归档.md", "02 - 问题与报错.md"],
    "all": ["07 - AI启动上下文.md", "01 - 阶段总结.md", "02 - 问题与报错.md", "03 - 建议与决策.md", "04 - 会话与时间线.md", "05 - 交付与复盘.md", "08 - 风险假设与依赖.md", "09 - 项目事件日志.md", "10 - 知识新鲜度与归档.md", "11 - 总结分类与调取.md"],
}
FOCUS_KINDS = {
    "overview": {"status", "decision", "risk", "method"},
    "status": {"status", "change", "delivery", "verification"},
    "implementation": {"change", "configuration", "decision", "method", "risk", "status"},
    "debugging": {"problem", "verification", "method", "risk"},
    "decision": {"decision", "research", "retrospective"},
    "handoff": {"handoff", "status", "change", "problem", "decision", "risk", "verification"},
    "all": {"status", "change", "delivery", "verification", "problem", "decision", "research", "configuration", "retrospective", "method", "risk", "handoff"},
}
KIND_KEYWORDS = {
    "problem": ("报错", "错误", "故障", "失败", "修复", "根因", "bug", "error", "fix"),
    "decision": ("决策", "取舍", "为什么", "方案", "adr", "decision"),
    "research": ("调研", "对比", "github", "研究", "research"),
    "configuration": ("配置", "插件", "环境", "样式", "configuration"),
    "delivery": ("交付", "发布", "上线", "版本", "release"),
    "verification": ("验证", "测试", "验收", "test", "verify"),
    "retrospective": ("复盘", "回顾", "遗漏", "retrospective"),
    "handoff": ("交接", "继续开发", "启动上下文", "handoff"),
    "risk": ("风险", "假设", "依赖", "risk"),
    "method": ("方法", "经验", "手册", "playbook"),
    "status": ("状态", "进展", "阶段", "status", "progress"),
}


def date_value(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date.min


def wikilink_target(value: Any) -> str:
    match = re.search(r"\[\[([^]|#]+)", str(value or ""))
    return match.group(1).strip() if match else str(value or "").strip()


def project_matches(metadata: dict[str, Any], title: str, project_note: Path, body: str) -> bool:
    raw = metadata.get("project")
    target = wikilink_target(raw)
    project_rel = project_note.with_suffix("").as_posix().casefold()
    if target:
        folded = target.replace("\\", "/").casefold()
        if folded == project_rel or Path(target).stem.casefold() == title.casefold():
            return True
    return bool(re.search(rf"\[\[[^]]*{re.escape(title)}(?:\||\]|#)", body, re.IGNORECASE))


def infer_summary_kind(metadata: dict[str, Any], title: str, body: str) -> str:
    explicit = str(metadata.get("summary_kind") or "").strip().casefold()
    if explicit in FOCUS_KINDS["all"]:
        return explicit
    record_type = metadata.get("record_type")
    if record_type == "problem":
        return "problem"
    if record_type == "playbook":
        return "method"
    if record_type == "inbox":
        capture_kind = str(metadata.get("capture_kind") or "").casefold()
        if capture_kind in FOCUS_KINDS["all"]:
            return capture_kind
    haystack = f"{title}\n{body[:2500]}".casefold()
    for kind, keywords in KIND_KEYWORDS.items():
        if any(keyword.casefold() in haystack for keyword in keywords):
            return kind
    return "change" if record_type == "session" else "status"


def compact_body(body: str, limit: int) -> str:
    cleaned = re.sub(r"%%.*?%%", "", body, flags=re.DOTALL)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 18)].rstrip() + "\n\n…（已按预算截断）"


def source_link(vault: Path, path: Path) -> str:
    return f"[[{path.relative_to(vault).with_suffix('').as_posix()}|{path.stem}]]"


def collect_records(vault: Path, config: dict[str, Any], title: str, project_note: Path, focus: str, recent_sessions: int) -> list[dict[str, Any]]:
    selected = []
    for path in iter_record_paths(vault, config):
        if path == project_note:
            continue
        try:
            metadata, body = split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if not project_matches(metadata, title, project_note.relative_to(vault), body):
            continue
        if metadata.get("superseded_by") or str(metadata.get("lifecycle_state") or "").casefold() in {"withdrawn", "superseded", "reverted", "deprecated"}:
            continue
        kind = infer_summary_kind(metadata, path.stem, body)
        if kind not in FOCUS_KINDS[focus]:
            continue
        record_type = str(metadata.get("record_type") or "")
        status = str(metadata.get("status") or "")
        priority = 20
        if record_type == "problem" and status in {"open", "investigating"}:
            priority = 100
        elif kind == "handoff":
            priority = 90
        elif kind in {"decision", "risk"}:
            priority = 70
        elif record_type == "session":
            priority = 50
        selected.append({
            "path": path,
            "metadata": metadata,
            "body": body,
            "kind": kind,
            "priority": priority,
            "sort_date": date_value(metadata.get("updated") or metadata.get("completed_at") or metadata.get("created")),
        })
    selected.sort(key=lambda item: (item["priority"], item["sort_date"]), reverse=True)
    session_count = 0
    filtered = []
    for item in selected:
        if item["metadata"].get("record_type") == "session":
            session_count += 1
            if session_count > recent_sessions:
                continue
        filtered.append(item)
    return filtered


def space_folder(vault: Path, metadata: dict[str, Any]) -> Path:
    target = wikilink_target(metadata.get("project_space"))
    if not target:
        raise ValueError("project_space is missing")
    return (vault / target).with_suffix("").parent


def render_context(vault: Path, project_note: Path, focus: str, max_chars: int, recent_sessions: int) -> tuple[str, dict[str, Any]]:
    config = load_config(vault)
    metadata, project_body = split_frontmatter(project_note.read_text(encoding="utf-8"))
    title = project_note.stem
    folder = space_folder(vault, metadata)
    freshness = str(metadata.get("freshness_state") or "unknown")
    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    parts = [
        "---",
        f'project: "[[{project_note.relative_to(vault).with_suffix("").as_posix()}]]"',
        f"focus: {focus}",
        f"generated: {generated}",
        f"source_freshness: {freshness}",
        "cssclasses:",
        "  - ai-knowledge",
        "  - ai-context-pack",
        "tags:",
        "  - AI知识库",
        "  - AI上下文包",
        "---",
        "",
        f"# {title} · AI 上下文包（{focus}）",
        "",
    ]
    if freshness == "stale":
        parts.extend(["> [!danger] 来源已变化", "> 当前仓库/受控文件指纹与知识基线不一致。先核对新变化，不要直接沿用旧结论。", ""])
    elif freshness == "unknown":
        parts.extend(["> [!warning] 新鲜度未知", "> 尚未建立或无法读取来源基线。重要判断前先运行项目新鲜度检查。", ""])
    parts.extend([
        "## 使用方式",
        "",
        "把本文件提供给 AI，并明确本次目标、可修改范围与完成标准。正式项目档案仍是状态唯一事实源。",
        "",
        "## 项目档案",
        "",
        f"来源：{source_link(vault, project_note)}",
        "",
        compact_body(project_body, 5000),
        "",
    ])

    included_pages = []
    for filename in FOCUS_PAGES[focus]:
        path = folder / filename
        if not path.exists():
            continue
        _, body = split_frontmatter(path.read_text(encoding="utf-8"), strict=False)
        parts.extend([f"## {path.stem}", "", f"来源：{source_link(vault, path)}", "", compact_body(body, 2800), ""])
        included_pages.append(str(path.relative_to(vault)))

    records = collect_records(vault, config, title, project_note, focus, recent_sessions)
    if records:
        parts.extend(["## 相关正式记录", ""])
        for item in records:
            path = item["path"]
            metadata_item = item["metadata"]
            parts.extend([
                f"### {path.stem}",
                "",
                f"- 分类：`{item['kind']}`",
                f"- 类型/状态：`{metadata_item.get('record_type', 'unknown')}` / `{metadata_item.get('status', 'unknown')}`",
                f"- 来源：{source_link(vault, path)}",
                "",
                compact_body(item["body"], 1800),
                "",
            ])

    parts.extend([
        "## 本次继续前检查",
        "",
        "- [ ] 新鲜度不是 `stale`，或已明确记录外部变化。",
        "- [ ] 未解决问题、风险、失败尝试已读取。",
        "- [ ] 当前目标、非目标、成功标准明确。",
        "- [ ] 完成后更新会话、项目状态和必要的事件/问题记录。",
        "",
    ])
    text = "\n".join(parts).rstrip() + "\n"
    truncated = False
    if len(text) > max_chars:
        suffix = "\n\n> [!warning] 预算截断\n> 上下文包已达到字符预算；优先保留了项目档案、运行手册和高优先级问题。\n"
        text = text[: max(0, max_chars - len(suffix))].rstrip() + suffix
        truncated = True
    return text, {
        "project": title,
        "focus": focus,
        "freshness_state": freshness,
        "chars": len(text),
        "max_chars": max_chars,
        "truncated": truncated,
        "included_pages": included_pages,
        "included_records": [str(item["path"].relative_to(vault)) for item in records],
    }


def build_context(vault: Path, project: str, *, focus: str = "handoff", max_chars: int = 24000, recent_sessions: int = 5, output: Path | None = None) -> dict[str, Any]:
    if max_chars < 1000:
        raise ValueError("max_chars must be at least 1000")
    config = load_config(vault)
    project_note = find_project_note(vault, config, project)
    text, result = render_context(vault, project_note, focus, max_chars, recent_sessions)
    metadata, _ = split_frontmatter(project_note.read_text(encoding="utf-8"))
    target = output or (space_folder(vault, metadata) / "资料" / f"AI上下文包-{focus}.md")
    if not target.is_absolute():
        target = vault / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    result["output"] = str(target.relative_to(vault)) if target.is_relative_to(vault) else str(target)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a bounded, focus-specific AI context pack from verified Obsidian records.")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--focus", choices=sorted(FOCUS_PAGES), default="handoff")
    parser.add_argument("--max-chars", type=int, default=24000)
    parser.add_argument("--recent-sessions", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = build_context(
        resolve_vault(args.vault),
        args.project,
        focus=args.focus,
        max_chars=args.max_chars,
        recent_sessions=args.recent_sessions,
        output=args.output,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Context pack: {result['output']}")
        print(f"Focus: {result['focus']}; freshness: {result['freshness_state']}; chars: {result['chars']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())