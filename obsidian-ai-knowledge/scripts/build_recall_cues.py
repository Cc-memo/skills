from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import iter_record_paths, load_config, resolve_vault, split_frontmatter
from search_knowledge import is_superseded, stringify, trust_state


def cue_summary(metadata: dict[str, Any], body: str) -> str:
    for key in ("root_cause", "applies_to", "solution_type"):
        value = stringify(metadata.get(key)).strip()
        if value:
            return value
    for line in body.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean[:160]
    return "—"


def build_cues(vault: Path) -> list[dict[str, Any]]:
    config = load_config(vault)
    cues: list[dict[str, Any]] = []
    for path in iter_record_paths(vault, config):
        metadata, body = split_frontmatter(path.read_text(encoding="utf-8"), strict=False)
        record_type = str(metadata.get("record_type") or "")
        if record_type not in {"problem", "playbook"} or is_superseded(metadata):
            continue
        if record_type == "problem" and str(metadata.get("status") or "") not in {"solved", "closed"}:
            continue
        if trust_state(metadata) != "trusted":
            continue
        cues.append(
            {
                "title": path.stem,
                "record_id": metadata.get("record_id"),
                "record_type": record_type,
                "project": stringify(metadata.get("project")) or "—",
                "aliases": stringify(metadata.get("tags")) or "—",
                "updated": metadata.get("last_verified") or metadata.get("updated") or "—",
                "summary": cue_summary(metadata, body),
                "path": path,
            }
        )
    return sorted(cues, key=lambda item: (item["record_type"], item["title"]))


def render_cues(vault: Path, cues: list[dict[str, Any]]) -> str:
    lines = [
        "---",
        "schema_version: 1",
        "record_type: system",
        "record_id: system-solution-recall-cues",
        "status: active",
        "---",
        "",
        "# 问题召回线索",
        "",
        "> [!info] 用途",
        "> 这是已验证问题与稳定经验的轻量提示表。遇到相似任务时，先据此调用 `recall_solution.py`，不要把本页本身当作最终答案。",
        "",
        f"- 已验证线索：{len(cues)}",
        "- 默认排除：未验证、已撤回、已回退、已取代记录",
        "",
        "| 类型 | 线索 | 项目 | 标签/别名 | 根因或适用范围 | 最近验证 |",
        "|---|---|---|---|---|---|",
    ]
    for item in cues:
        relative = item["path"].relative_to(vault).with_suffix("").as_posix()
        cells = [
            item["record_type"],
            f"[[{relative}|{item['title']}]]",
            item["project"],
            item["aliases"],
            item["summary"],
            str(item["updated"]),
        ]
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    lines.extend(["", "## 调取方式", "", "```powershell", 'python scripts/recall_solution.py --query "症状、报错、技术或决策关键词"', "```", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ambient cues for verified solution recall.")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    vault = resolve_vault(args.vault)
    config = load_config(vault)
    output = args.output or (vault / str(config.get("knowledge_root", "00-AI知识库")) / "_系统" / "问题召回线索.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    cues = build_cues(vault)
    output.write_text(render_cues(vault, cues), encoding="utf-8")
    print(f"Saved {len(cues)} recall cues to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())