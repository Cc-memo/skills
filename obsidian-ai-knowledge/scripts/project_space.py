from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from common import knowledge_root, load_config, resolve_vault, split_frontmatter


PROJECT_TYPES: dict[str, tuple[str, str]] = {
    "software": (
        "06 - 架构版本与测试.md",
        """## 架构边界\n\n## 版本与发布\n\n## 测试矩阵\n\n## 部署与运行\n\n## 技术债务\n""",
    ),
    "research": (
        "06 - 资料假设与结论.md",
        """## 研究问题\n\n## 资料与证据\n\n## 假设\n\n## 已验证结论\n\n## 未决问题\n""",
    ),
    "configuration": (
        "06 - 环境配置与回滚.md",
        """## 环境基线\n\n## 配置变更\n\n## 备份位置\n\n## 回滚步骤\n\n## 验证清单\n""",
    ),
    "document": (
        "06 - 版本审阅与交付.md",
        """## 文档范围\n\n## 版本记录\n\n## 审阅意见\n\n## 修改闭环\n\n## 最终交付\n""",
    ),
    "system": (
        "06 - 架构配置与验证.md",
        """## 系统架构\n\n## 配置与依赖\n\n## 自动化入口\n\n## 验证与健康检查\n\n## 升级与回滚\n""",
    ),
    "general": (
        "06 - 范围资源与依赖.md",
        """## 项目范围\n\n## 资源\n\n## 依赖\n\n## 约束\n\n## 验收标准\n""",
    ),
}


MANAGED_MARKER = "%% generated-by: obsidian-ai-knowledge/project-space-v1 %%"


def safe_folder_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "-", value).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise ValueError("project title cannot produce an empty folder name")
    return cleaned


def project_title(body: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def find_project_note(vault: Path, config: dict[str, Any], value: str) -> Path:
    candidate = Path(value)
    if candidate.suffix.casefold() == ".md" or "/" in value or "\\" in value:
        path = candidate if candidate.is_absolute() else vault / candidate
        if path.exists():
            return path
    project_dir = knowledge_root(vault, config) / str(config["record_directories"]["project"])
    matches = [path for path in project_dir.rglob("*.md") if path.stem.casefold() == value.casefold()]
    if not matches:
        raise FileNotFoundError(f"project note not found: {value}")
    if len(matches) > 1:
        raise ValueError(f"multiple project notes match {value!r}")
    return matches[0]


def update_frontmatter(text: str, fields: dict[str, str]) -> str:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError("project note is missing YAML frontmatter")
    end = normalized.find("\n---\n", 4)
    if end == -1:
        raise ValueError("project note has unterminated YAML frontmatter")
    lines = normalized[4:end].split("\n")
    for key, value in fields.items():
        prefix = f"{key}:"
        for index, line in enumerate(lines):
            if line.startswith(prefix):
                lines[index] = f"{key}: {value}"
                break
        else:
            insert_at = next(
                (index for index, line in enumerate(lines) if line.startswith("cssclasses:") or line.startswith("tags:")),
                len(lines),
            )
            lines.insert(insert_at, f"{key}: {value}")
    return "---\n" + "\n".join(lines) + normalized[end:]


def ensure_project_space_section(text: str, links: dict[str, str]) -> str:
    heading = re.search(r"^##\s+项目空间\s*$", text, re.MULTILINE)
    if not heading:
        section = "\n## 项目空间\n\n" + "\n".join(f"- [[{path}|{label}]]" for label, path in links.items()) + "\n"
        marker = "\n## 关联记录"
        if marker in text:
            return text.replace(marker, section + marker, 1)
        return text.rstrip() + section + "\n"

    next_heading = re.search(r"^##\s+", text[heading.end() :], re.MULTILINE)
    section_end = heading.end() + next_heading.start() if next_heading else len(text)
    section = text[heading.start() : section_end].rstrip()
    missing = [f"- [[{path}|{label}]]" for label, path in links.items() if f"[[{path}" not in section]
    if not missing:
        return text
    updated_section = section + "\n" + "\n".join(missing) + "\n\n"
    return text[: heading.start()] + updated_section + text[section_end:].lstrip("\n")


def note_frontmatter(project_link: str, project_kind: str, today: str, cssclass: str) -> str:
    return f"""---
project: "[[{project_link}]]"
project_type: {project_kind}
created: {today}
updated: {today}
cssclasses:
  - ai-knowledge
  - ai-project-space
  - {cssclass}
tags:
  - AI知识库
  - 项目空间
---
"""


def render_base(title: str, project_link: str, space_folder: str) -> str:
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    escaped_link = project_link.replace("\\", "\\\\").replace('"', '\\"')
    escaped_folder = space_folder.replace("\\", "/").replace('"', '\\"')
    return f"""filters:
  and:
    - 'file.ext == "md"'
    - or:
        - 'project == link("{escaped_link}")'
        - 'file.hasLink("{escaped_title}")'
    - not:
        - 'file.inFolder("{escaped_folder}")'
formulas:
  activity: 'file.mtime.relative()'
properties:
  file.name:
    displayName: 记录
  record_type:
    displayName: 类型
  status:
    displayName: 状态
  outcome:
    displayName: 结果
  severity:
    displayName: 严重度
  root_cause:
    displayName: 根因
  review_state:
    displayName: 审核
  summary_kind:
    displayName: 总结分类
  retrieval_priority:
    displayName: 调取优先级
  updated:
    displayName: 更新日期
  formula.activity:
    displayName: 最近活动
views:
  - type: table
    name: 全部记录
    order:
      - file.name
      - record_type
      - status
      - review_state
      - summary_kind
      - retrieval_priority
      - formula.activity
    sort:
      - property: file.mtime
        direction: DESC
  - type: table
    name: 会话时间线
    filters:
      and:
        - 'record_type == "session"'
    order:
      - file.name
      - outcome
      - knowledge_value
      - completed_at
      - formula.activity
    sort:
      - property: completed_at
        direction: DESC
  - type: table
    name: 问题与报错
    filters:
      and:
        - 'record_type == "problem"'
    order:
      - file.name
      - status
      - severity
      - root_cause
      - formula.activity
    sort:
      - property: file.mtime
        direction: DESC
  - type: table
    name: 建议与待审核
    filters:
      and:
        - 'record_type == "inbox"'
    order:
      - file.name
      - capture_kind
      - review_state
      - confidence
      - formula.activity
    sort:
      - property: file.mtime
        direction: DESC
  - type: table
    name: 总结分类
    order:
      - file.name
      - summary_kind
      - retrieval_priority
      - record_type
      - status
      - formula.activity
    sort:
      - property: retrieval_priority
        direction: DESC
      - property: file.mtime
        direction: DESC
  - type: table
    name: 经验与方法
    filters:
      and:
        - 'record_type == "playbook"'
    order:
      - file.name
      - maturity
      - applies_to
      - confidence
      - formula.activity
    sort:
      - property: file.mtime
        direction: DESC
"""


def write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return True


def ensure_project_space(
    vault: Path,
    project: str,
    *,
    project_kind: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    vault = resolve_vault(vault)
    config = load_config(vault)
    note_path = find_project_note(vault, config, project)
    metadata, body = split_frontmatter(note_path.read_text(encoding="utf-8"))
    title = project_title(body, note_path.stem)
    kind = project_kind or str(metadata.get("project_type") or "general")
    if kind not in PROJECT_TYPES:
        raise ValueError(f"unsupported project type: {kind}")
    current_day = today or date.today()
    current_date = current_day.isoformat()
    review_days = int(config.get("project_spaces", {}).get("review_days", 14))
    review_due = (current_day + timedelta(days=review_days)).isoformat()
    root = knowledge_root(vault, config)
    spaces_root = str(config.get("project_spaces", {}).get("root", "项目空间"))
    folder = root / spaces_root / safe_folder_name(title)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "资料").mkdir(exist_ok=True)

    project_link = note_path.relative_to(vault).with_suffix("").as_posix()
    folder_link = folder.relative_to(vault).as_posix()
    filenames = {
        "项目驾驶舱": "00 - 项目驾驶舱.md",
        "阶段总结": "01 - 阶段总结.md",
        "问题与报错": "02 - 问题与报错.md",
        "建议与决策": "03 - 建议与决策.md",
        "会话与时间线": "04 - 会话与时间线.md",
        "交付与复盘": "05 - 交付与复盘.md",
        "AI启动上下文": "07 - AI启动上下文.md",
        "风险假设与依赖": "08 - 风险假设与依赖.md",
        "项目事件日志": "09 - 项目事件日志.md",
        "新鲜度与归档": "10 - 知识新鲜度与归档.md",
        "总结分类与调取": "11 - 总结分类与调取.md",
    }
    type_filename, type_body = PROJECT_TYPES[kind]
    filenames["类型专项"] = type_filename
    links = {label: f"{folder_link}/{filename[:-3]}" for label, filename in filenames.items()}

    project_text = note_path.read_text(encoding="utf-8")
    project_text = update_frontmatter(
        project_text,
        {
            "updated": current_date,
            "project_type": kind,
            "project_space": json.dumps(f"[[{links['项目驾驶舱']}]]", ensure_ascii=False),
            "summary_note": json.dumps(f"[[{links['阶段总结']}]]", ensure_ascii=False),
            "problem_log": json.dumps(f"[[{links['问题与报错']}]]", ensure_ascii=False),
            "decision_log": json.dumps(f"[[{links['建议与决策']}]]", ensure_ascii=False),
            "context_note": json.dumps(f"[[{links['AI启动上下文']}]]", ensure_ascii=False),
            "risk_log": json.dumps(f"[[{links['风险假设与依赖']}]]", ensure_ascii=False),
            "event_log": json.dumps(f"[[{links['项目事件日志']}]]", ensure_ascii=False),
            "freshness_note": json.dumps(f"[[{links['新鲜度与归档']}]]", ensure_ascii=False),
            "retrieval_note": json.dumps(f"[[{links['总结分类与调取']}]]", ensure_ascii=False),
            "last_reviewed": current_date,
            "review_due": review_due,
        },
    )
    project_text = ensure_project_space_section(project_text, links)
    note_path.write_text(project_text, encoding="utf-8")

    frontmatter = note_frontmatter(project_link, kind, current_date, "ai-project-dashboard")
    dashboard = frontmatter + f"""
{MANAGED_MARKER}
# {title} · 项目驾驶舱

> [!abstract] 项目定位
> 本文件夹聚合项目总结、报错、建议、决策、会话、交付和类型专项资料；正式会话与问题仍保存在全局记录目录，避免重复和数据分叉。

## 快速入口

""" + "\n".join(f"- [[{path}|{label}]]" for label, path in links.items() if label != "项目驾驶舱") + f"""

## 当前状态

![[{project_link}#当前状态]]

## 下一步

![[{project_link}#下一步]]

## 当前风险

![[{project_link}#当前风险]]

## 项目记录

![[{folder_link}/项目记录.base#全部记录]]
"""
    summary = note_frontmatter(project_link, kind, current_date, "ai-project-summary") + f"""
{MANAGED_MARKER}
# {title} · 阶段总结

## 本阶段目标

## 已完成成果

## 关键变化

## 未完成与阻塞

## 经验与判断

## 下一阶段建议

## 最近会话

![[{folder_link}/项目记录.base#会话时间线]]
"""
    problems = note_frontmatter(project_link, kind, current_date, "ai-project-problems") + f"""
{MANAGED_MARKER}
# {title} · 问题与报错

> [!warning] 记录原则
> 这里只聚合和分流问题；有现象、排查、根因、方案与验证后，正式问题记录仍写入 `00-AI知识库/问题/YYYY/`。

## 未解决问题

![[{folder_link}/项目记录.base#问题与报错]]

## 临时排查记录

## 复发检查
"""
    decisions = note_frontmatter(project_link, kind, current_date, "ai-project-decisions") + f"""
{MANAGED_MARKER}
# {title} · 建议与决策

## 待审核建议

![[{folder_link}/项目记录.base#建议与待审核]]

## 决策日志

| 日期 | 状态 | 决策 | 原因 | 证据/关联 |
| --- | --- | --- | --- | --- |

## 被否决方案

## 待确认问题
"""
    timeline = note_frontmatter(project_link, kind, current_date, "ai-project-timeline") + f"""
{MANAGED_MARKER}
# {title} · 会话与时间线

## 会话时间线

![[{folder_link}/项目记录.base#会话时间线]]

## 重要节点

| 日期 | 里程碑 | 结果 | 下一步 |
| --- | --- | --- | --- |
"""
    deliverables = note_frontmatter(project_link, kind, current_date, "ai-project-deliverables") + f"""
{MANAGED_MARKER}
# {title} · 交付与复盘

## 成功标准

## 里程碑

## 交付物

| 交付物 | 位置 | 状态 | 验证 |
| --- | --- | --- | --- |

## 指标与证据

## 最终复盘

### 做得好的

### 可以改进的

### 下次不同做法
"""
    context = note_frontmatter(project_link, kind, current_date, "ai-project-context") + f"""
{MANAGED_MARKER}
# {title} · AI启动上下文

> [!important] AI 开始前必读
> 每次开始实质任务前，先读项目档案、本页、风险与事件日志；再确认仓库最新时间戳，避免基于过时状态继续。

## 项目一句话

![[{project_link}#目标]]

## 当前工作基线

![[{project_link}#当前状态]]

## 范围与非目标

## 权威来源

| 类型 | 位置 | 用途 | 新鲜度 |
| --- | --- | --- | --- |

## 敏感与禁止事项

## 已知脆弱点

## 完成定义

## 恢复工作清单

- [ ] 重读项目档案和最近会话。
- [ ] 核对仓库、运行状态与时间戳。
- [ ] 检查未解决问题、风险和已失败尝试。
- [ ] 确认本次成功标准与不做什么。
"""
    risks = note_frontmatter(project_link, kind, current_date, "ai-project-risks") + f"""
{MANAGED_MARKER}
# {title} · 风险假设与依赖

## 风险登记

| ID | 状态 | 概率 | 影响 | 风险 | 触发器 | 缓解/应对 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |

## 假设登记

| ID | 状态 | 假设 | 验证方法 | 截止日期 | 结果 |
| --- | --- | --- | --- | --- | --- |

## 依赖登记

| 依赖 | 类型 | 当前版本/状态 | 故障影响 | 替代/回滚 |
| --- | --- | --- | --- | --- |

## 复核规则

- 风险触发、假设被证伪或依赖变更时，必须更新项目档案和事件日志。
- 未知根因不得标记为已解决。
"""
    events = note_frontmatter(project_link, kind, current_date, "ai-project-events") + f"""
{MANAGED_MARKER}
# {title} · 项目事件日志

> [!note] 追加式记录
> 只追加影响项目判断的事件，不写完整对话。类型使用 `decision`、`attempt`、`failure`、`fix`、`milestone`、`external-change`。

## 事件

| 时间 | 类型 | 事件 | 证据 | 影响 | 下一步 |
| --- | --- | --- | --- | --- | --- |

## 最近正式记录

![[{folder_link}/项目记录.base#全部记录]]
"""
    freshness = note_frontmatter(project_link, kind, current_date, "ai-project-freshness") + f"""
{MANAGED_MARKER}
# {title} · 知识新鲜度与归档

## 复核状态

- 上次复核：{current_date}
- 下次复核：{review_due}
- 复核周期：{review_days} 天

## 信息保鲜清单

- [ ] 当前状态、版本和下一步与仓库一致。
- [ ] 风险、假设和依赖仍有效。
- [ ] 已被取代的结论已标明新来源。
- [ ] 事件日志已记录外部变更和失败尝试。

## 过时与取代规则

- 不删除旧结论；标记已被何记录、版本或证据取代。
- 外部仓库时间戳晚于项目总结时，先重新读取再行动。

## 归档条件

- 成功标准已完成或项目明确终止。
- 交付、验证、未解决问题和复盘已记录。
- 项目状态更新为 `completed` 或 `archived`。

## 归档检查表

- [ ] 最终交付和验证证据已链接。
- [ ] 可复用经验已晋升或标记不晋升原因。
- [ ] 敏感文件与临时产物未进入知识库。
- [ ] 下一任务可仅通过项目档案和启动上下文恢复。
"""
    retrieval = note_frontmatter(project_link, kind, current_date, "ai-project-retrieval") + f"""
{MANAGED_MARKER}
# {title} · 总结分类与调取

> [!tip] 调取原则
> 先按任务意图选择分类，再读取高优先级、未被取代且来源新鲜的正式记录；不要把所有历史记录一次性塞给 AI。

## 总结分类

| 分类 | 适用内容 | 常见提问 |
| --- | --- | --- |
| `status` | 当前状态、进度、下一步 | 现在进展怎么样 |
| `change` | 实现与变更 | 最近改了什么 |
| `delivery` | 发布与交付 | 已经交付了什么 |
| `verification` | 测试与验收 | 如何确认可用 |
| `problem` | 报错、失败与根因 | 这个错误以前出现过吗 |
| `decision` | 决策、取舍与替代方案 | 为什么这样设计 |
| `research` | 调研、对标与证据 | 参考了哪些方案 |
| `configuration` | 环境、插件与配置 | 当前环境怎么搭的 |
| `retrospective` | 复盘、遗漏与错判 | 哪些判断需要纠正 |
| `method` | 可复用方法与手册 | 有哪些经验可复用 |
| `risk` | 风险、假设与依赖 | 继续做有哪些风险 |
| `handoff` | AI/人员交接 | 换一个 AI 如何继续 |

## 调取路由

- **继续开发**：`implementation` → 项目档案 + 启动上下文 + 风险 + 最近事件 + 决策。
- **排查报错**：`debugging` → 未解决问题优先 + failure/fix 事件 + 验证方法。
- **解释设计**：`decision` → 决策 + 调研 + 被拒绝方案 + 取代关系。
- **查看进度**：`status` → 阶段总结 + 最近变更 + 验证 + 下一步。
- **交接 AI**：`handoff` → 新鲜度警告 + 当前状态 + 风险 + 未解决问题 + 最近会话。

## 字段约定

- `summary_kind`：上述分类之一；旧记录可由打包器确定性推断，逐步补齐。
- `retrieval_priority`：建议 0–100；未解决问题、有效决策和当前交接材料优先。
- `supersedes` / `superseded_by`：保留旧结论并显式链接替代关系。

## 常用命令

```powershell
python "$env:USERPROFILE\\.codex\\skills\\obsidian-ai-knowledge\\scripts\\project_freshness.py" --project "{title}" --scan
python "$env:USERPROFILE\\.codex\\skills\\obsidian-ai-knowledge\\scripts\\project_context.py" --project "{title}" --focus handoff
```
"""
    specialized = note_frontmatter(project_link, kind, current_date, "ai-project-specialized") + f"\n{MANAGED_MARKER}\n# {title} · {Path(type_filename).stem[5:]}\n\n{type_body}"

    files = {
        folder / filenames["项目驾驶舱"]: dashboard,
        folder / filenames["阶段总结"]: summary,
        folder / filenames["问题与报错"]: problems,
        folder / filenames["建议与决策"]: decisions,
        folder / filenames["会话与时间线"]: timeline,
        folder / filenames["交付与复盘"]: deliverables,
        folder / filenames["AI启动上下文"]: context,
        folder / filenames["风险假设与依赖"]: risks,
        folder / filenames["项目事件日志"]: events,
        folder / filenames["新鲜度与归档"]: freshness,
        folder / filenames["总结分类与调取"]: retrieval,
        folder / type_filename: specialized,
        folder / "项目记录.base": render_base(title, project_link, folder_link),
    }
    created = [str(path.relative_to(vault)) for path, content in files.items() if write_if_missing(path, content)]
    return {
        "project": title,
        "project_type": kind,
        "project_note": str(note_path.relative_to(vault)),
        "project_space": str(folder.relative_to(vault)),
        "created": created,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or repair a project-centric Obsidian workspace.")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--project", required=True, help="Project title or project note path")
    parser.add_argument("--project-type", choices=sorted(PROJECT_TYPES))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = ensure_project_space(resolve_vault(args.vault), args.project, project_kind=args.project_type)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Project space: {result['project_space']}")
        print(f"Created: {len(result['created'])}")
        for path in result["created"]:
            print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
