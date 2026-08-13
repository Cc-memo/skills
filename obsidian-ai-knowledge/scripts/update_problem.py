from __future__ import annotations

import argparse
import difflib
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from common import iter_record_paths, load_config, resolve_vault, split_frontmatter


VALID_STATUSES = {"open", "investigating", "solved", "closed"}


def find_problem(vault: Path, record_id: str) -> tuple[Path, dict[str, Any], str]:
    config = load_config(vault)
    for path in iter_record_paths(vault, config):
        metadata, body = split_frontmatter(path.read_text(encoding="utf-8"), strict=False)
        if metadata.get("record_type") == "problem" and str(metadata.get("record_id") or "") == record_id:
            return path, metadata, body
    raise ValueError(f"problem record not found: {record_id}")


def yaml_text(metadata: dict[str, Any]) -> str:
    return yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip()


def event_block(
    event_date: str,
    title: str,
    *,
    status: str,
    summary: str,
    session: str,
    validation: str,
    root_cause: str | None = None,
    solution: str | None = None,
) -> str:
    lines = [
        f"### {event_date} — {title}",
        "",
        f"- 状态：{status}",
        f"- 摘要：{summary}",
    ]
    if root_cause:
        lines.append(f"- 根因：{root_cause}")
    if solution:
        lines.append(f"- 方案：{solution}")
    lines.extend([f"- 会话：{session}", f"- 验证：{validation}"])
    return "\n".join(lines)


def append_event(body: str, block: str, event_date: str, title: str) -> str:
    marker = f"### {event_date} \u2014 {title}"
    if marker in body:
        raise ValueError(f"duplicate follow-up event: {marker}")
    heading = re.search(r"(?m)^## \u540e\u7eed\u8bb0\u5f55\s*$", body)
    if heading:
        following = body[heading.end() :]
        next_heading = re.search(r"(?m)^##\s+", following)
        insert_at = heading.end() + (next_heading.start() if next_heading else len(following))
        before = body[:insert_at].rstrip()
        after = body[insert_at:].lstrip("\n")
        return before + "\n\n" + block + "\n\n" + after
    related = re.search(r"(?m)^## \u5173\u8054\u8bb0\u5f55\s*$", body)
    section = "## \u540e\u7eed\u8bb0\u5f55\n\n" + block + "\n\n"
    if related:
        return body[: related.start()] + section + body[related.start() :].lstrip("\n")
    return body.rstrip() + "\n\n" + section


def update_problem(
    path: Path,
    metadata: dict[str, Any],
    body: str,
    *,
    event_date: str,
    event_title: str,
    status: str,
    summary: str,
    session: str,
    validation: str,
    root_cause: str | None = None,
    solution_type: str | None = None,
    solution: str | None = None,
    superseded_by: str | None = None,
) -> str:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    if status == "solved":
        effective_root = root_cause or str(metadata.get("root_cause") or "").strip()
        effective_solution_type = solution_type or str(metadata.get("solution_type") or "").strip()
        if not effective_root:
            raise ValueError("solved update requires --root-cause or an existing root_cause")
        if not effective_solution_type:
            raise ValueError("solved update requires --solution-type or an existing solution_type")
        if not validation.strip() or validation.strip() in {"未完成", "未验证", "pending"}:
            raise ValueError("solved update requires concrete validation evidence")

    updated = dict(metadata)
    updated["updated"] = event_date
    updated["status"] = status
    occurrences = updated.get("occurrences") or 0
    try:
        updated["occurrences"] = int(occurrences) + 1
    except (TypeError, ValueError) as exc:
        raise ValueError("occurrences must be an integer") from exc
    if root_cause:
        updated["root_cause"] = root_cause
    if solution_type:
        updated["solution_type"] = solution_type
    if session:
        updated["source_session"] = session
    if status == "solved":
        updated["resolved_at"] = event_date
        updated["review_state"] = "reviewed"
        updated["confidence"] = "high"
    elif status in {"open", "investigating"}:
        updated["resolved_at"] = None
    if superseded_by:
        updated["superseded_by"] = superseded_by
        updated["lifecycle_state"] = "superseded"

    block = event_block(
        event_date,
        event_title,
        status=status,
        summary=summary,
        session=session,
        validation=validation,
        root_cause=root_cause,
        solution=solution,
    )
    updated_body = append_event(body, block, event_date, event_title)
    return "---\n" + yaml_text(updated) + "\n---\n" + updated_body.lstrip("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a dated event and update one existing problem card safely.")
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--event-title", required=True)
    parser.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    parser.add_argument("--summary", required=True)
    parser.add_argument("--session", required=True, help="WikiLink or stable session/source reference")
    parser.add_argument("--validation", required=True)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--root-cause")
    parser.add_argument("--solution-type")
    parser.add_argument("--solution")
    parser.add_argument("--superseded-by")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write the update; default is a unified diff preview")
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    path, metadata, body = find_problem(vault, args.record_id)
    original = path.read_text(encoding="utf-8")
    updated = update_problem(
        path,
        metadata,
        body,
        event_date=args.date,
        event_title=args.event_title,
        status=args.status,
        summary=args.summary,
        session=args.session,
        validation=args.validation,
        root_cause=args.root_cause,
        solution_type=args.solution_type,
        solution=args.solution,
        superseded_by=args.superseded_by,
    )
    if args.apply:
        path.write_text(updated, encoding="utf-8")
        print(f"Updated problem: {path}")
    else:
        print("".join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True), fromfile=str(path), tofile=str(path))))
        print("Preview only. Re-run with --apply after reviewing the diff.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())