from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from common import (
    build_note_index,
    extract_wikilinks,
    iter_record_paths,
    knowledge_root,
    load_config,
    normalize_wikilink,
    resolve_vault,
    split_frontmatter,
)


REQUIRED_COMMON = {
    "schema_version",
    "record_type",
    "record_id",
    "status",
    "created",
    "updated",
    "review_state",
    "confidence",
    "tags",
}
REQUIRED_BY_TYPE = {
    "project": {
        "priority", "area", "source", "next_action", "project_type", "project_space",
        "context_note", "risk_log", "event_log", "freshness_note", "retrieval_note", "last_reviewed", "review_due",
    },
    "problem": {"severity", "project", "area", "root_cause", "solution_type", "reusable", "occurrences", "source_session", "source"},
    "session": {"outcome", "completed_at", "project", "area", "ai_tool", "workspace", "knowledge_value", "source"},
    "playbook": {"maturity", "last_verified", "times_used", "area", "applies_to", "evidence", "source"},
    "inbox": {"capture_kind", "project", "area", "source"},
}
ALLOWED_VALUES = {
    "review_state": {"pending", "reviewed", "promoted"},
    "confidence": {"low", "medium", "high"},
    "outcome": {"success", "partial", "failed", "blocked"},
    "knowledge_value": {"low", "medium", "high"},
    "maturity": {"draft", "verified", "stable", "deprecated"},
}
STATUS_BY_TYPE = {
    "project": {"planned", "active", "blocked", "paused", "completed", "archived"},
    "problem": {"open", "investigating", "solved", "closed"},
    "session": {"completed", "partial", "failed", "blocked"},
    "playbook": {"active", "deprecated"},
    "inbox": {"pending", "reviewed", "promoted", "discarded"},
}
REQUIRED_HEADINGS = {
    "project": {"目标", "当前状态", "关键决策", "已完成", "当前风险", "下一步", "关联记录"},
    "problem": {"现象", "影响", "环境与上下文", "已尝试方案", "根因", "最终方案", "验证", "防止复发", "可复用结论", "关联记录"},
    "session": {"目标", "完成内容", "关键决策", "遇到的问题", "验证结果", "变更文件", "可复用知识", "遗留事项", "关联记录"},
    "playbook": {"适用场景", "判断信号", "标准步骤", "验证清单", "常见失败方式", "不适用场景", "证据与来源"},
    "inbox": {"原始事实", "当前推断", "待验证", "建议归档位置", "敏感信息检查"},
}
DATE_FIELDS = {"created", "updated", "completed_at", "resolved_at", "last_verified", "last_reviewed", "review_due"}
PROJECT_TYPES = {"software", "research", "configuration", "document", "system", "general"}
SUMMARY_KINDS = {"status", "change", "delivery", "verification", "problem", "decision", "research", "configuration", "retrospective", "method", "risk", "handoff"}
FRESHNESS_STATES = {"current", "stale", "unknown"}
PROBLEM_LIFECYCLE_REQUIRED_SINCE = date(2026, 8, 12)
SENSITIVE_VALUE = re.compile(
    r"(?i)(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|cookie|private[_ -]?key)\s*[:=]\s*[\"']?(?!<redacted>|\$\{)[^\s\"']{6,}"
)
MOJIBAKE = re.compile(r"姝|鐭ヨ|娌夋|绯荤|鈥|锛|闂|缁忛")


def valid_date(value: Any) -> bool:
    if value in (None, ""):
        return True
    if isinstance(value, (date, datetime)):
        return True
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)))


def date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def headings(body: str) -> set[str]:
    return {match.strip() for match in re.findall(r"^##\s+(.+?)\s*$", body, re.MULTILINE)}


def section_content(body: str, heading: str) -> str:
    match = re.search(rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)", body)
    return match.group(1).strip() if match else ""


def validate_vault(vault: Path) -> dict[str, Any]:
    config = load_config(vault)
    root = knowledge_root(vault, config)
    errors: list[str] = []
    warnings: list[str] = []
    record_ids: list[str] = []
    titles: list[str] = []
    counts: Counter[str] = Counter()
    records: dict[Path, tuple[dict[str, Any], str]] = {}

    if not root.exists():
        return {"counts": {}, "errors": [f"Knowledge root not found: {root}"], "warnings": []}

    expected_dirs = {key: str(value) for key, value in config.get("record_directories", {}).items()}
    schema_version = config.get("schema_version", 2)
    for path in iter_record_paths(vault, config):
        relative = path.relative_to(vault)
        try:
            text = path.read_text(encoding="utf-8")
            metadata, body = split_frontmatter(text)
        except Exception as exc:
            errors.append(f"{relative}: {exc}")
            continue

        if MOJIBAKE.search(text):
            errors.append(f"{relative}: possible UTF-8 mojibake detected")
        record_type = metadata.get("record_type")
        if record_type == "dashboard":
            counts["dashboard"] += 1
            records[path] = (metadata, body)
            continue
        if record_type not in REQUIRED_BY_TYPE:
            errors.append(f"{relative}: unsupported record_type {record_type!r}")
            continue

        records[path] = (metadata, body)
        counts[record_type] += 1
        titles.append(path.stem)
        missing = sorted((REQUIRED_COMMON | REQUIRED_BY_TYPE[record_type]) - set(metadata))
        if missing:
            errors.append(f"{relative}: missing fields {', '.join(missing)}")
        if metadata.get("schema_version") != schema_version:
            errors.append(f"{relative}: schema_version must be {schema_version}")

        record_id = metadata.get("record_id")
        if not isinstance(record_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", record_id):
            errors.append(f"{relative}: invalid record_id {record_id!r}")
        else:
            record_ids.append(record_id)

        for field, allowed in ALLOWED_VALUES.items():
            if field in metadata and metadata[field] not in (None, "") and metadata[field] not in allowed:
                errors.append(f"{relative}: invalid {field}={metadata[field]!r}")
        summary_kind = metadata.get("summary_kind")
        if summary_kind not in (None, "") and summary_kind not in SUMMARY_KINDS:
            errors.append(f"{relative}: invalid summary_kind={summary_kind!r}")
        retrieval_priority = metadata.get("retrieval_priority")
        if retrieval_priority not in (None, ""):
            if not isinstance(retrieval_priority, int) or isinstance(retrieval_priority, bool) or not 0 <= retrieval_priority <= 100:
                errors.append(f"{relative}: retrieval_priority must be an integer from 0 to 100")
        if metadata.get("status") not in STATUS_BY_TYPE[record_type]:
            errors.append(f"{relative}: invalid status={metadata.get('status')!r} for {record_type}")
        for field in DATE_FIELDS:
            if field in metadata and not valid_date(metadata[field]):
                errors.append(f"{relative}: invalid date in {field}")

        relative_to_root = path.relative_to(root)
        expected_dir = expected_dirs.get(record_type)
        if expected_dir and (not relative_to_root.parts or relative_to_root.parts[0] != expected_dir):
            errors.append(f"{relative}: {record_type} must be stored under {expected_dir}/")
        created = date_value(metadata.get("created"))
        if record_type in {"session", "problem"} and created:
            if len(relative_to_root.parts) < 2 or relative_to_root.parts[1] != str(created.year):
                errors.append(f"{relative}: expected year folder {created.year}")
            if not path.name.startswith(created.isoformat() + " - "):
                warnings.append(f"{relative}: filename should start with {created.isoformat()} -")

        missing_headings = sorted(REQUIRED_HEADINGS[record_type] - headings(body))
        if missing_headings:
            errors.append(f"{relative}: missing sections {', '.join(missing_headings)}")
        if SENSITIVE_VALUE.search(text):
            errors.append(f"{relative}: possible sensitive value detected")
        source_hash = metadata.get("source_hash")
        if source_hash and not re.fullmatch(r"[a-f0-9]{64}", str(source_hash)):
            errors.append(f"{relative}: source_hash must be lowercase SHA-256")
        if record_type in {"session", "problem", "playbook"} and not metadata.get("source_ref"):
            warnings.append(f"{relative}: source_ref is recommended for provenance")
        if record_type == "problem" and metadata.get("status") == "solved" and metadata.get("confidence") == "low":
            warnings.append(f"{relative}: solved problem still has low confidence")
        if record_type == "problem" and created and created >= PROBLEM_LIFECYCLE_REQUIRED_SINCE:
            if "后续记录" not in headings(body):
                errors.append(f"{relative}: problem requires 后续记录 lifecycle section")
            if metadata.get("status") == "solved":
                if not metadata.get("resolved_at"):
                    errors.append(f"{relative}: solved problem requires resolved_at")
                if not str(metadata.get("root_cause") or "").strip():
                    errors.append(f"{relative}: solved problem requires root_cause")
                if not str(metadata.get("solution_type") or "").strip():
                    errors.append(f"{relative}: solved problem requires solution_type")
                verification = section_content(body, "验证")
                if not verification or verification in {"未完成。", "未验证。", "pending"}:
                    errors.append(f"{relative}: solved problem requires concrete 验证 content")
        if record_type == "playbook" and metadata.get("maturity") in {"verified", "stable"} and not metadata.get("evidence"):
            errors.append(f"{relative}: verified playbook requires evidence")
        if record_type == "project":
            if metadata.get("project_type") not in PROJECT_TYPES:
                errors.append(f"{relative}: invalid project_type={metadata.get('project_type')!r}")
            freshness_state = metadata.get("freshness_state")
            if freshness_state not in (None, "") and freshness_state not in FRESHNESS_STATES:
                errors.append(f"{relative}: invalid freshness_state={freshness_state!r}")
            for fingerprint_field in ("source_fingerprint", "source_observed_fingerprint"):
                fingerprint = metadata.get(fingerprint_field)
                if fingerprint and not re.fullmatch(r"[a-f0-9]{64}", str(fingerprint)):
                    errors.append(f"{relative}: {fingerprint_field} must be lowercase SHA-256")
            if not metadata.get("project_space"):
                errors.append(f"{relative}: project_space is required")
            last_reviewed = date_value(metadata.get("last_reviewed"))
            review_due = date_value(metadata.get("review_due"))
            if last_reviewed and review_due and review_due < last_reviewed:
                errors.append(f"{relative}: review_due cannot be before last_reviewed")
        if record_type == "project" and metadata.get("status") == "active":
            updated = date_value(metadata.get("updated"))
            if updated and (date.today() - updated).days > 90:
                warnings.append(f"{relative}: active project has not been updated for more than 90 days")

    for record_id, count in Counter(record_ids).items():
        if count > 1:
            errors.append(f"duplicate record_id: {record_id}")
    for title, count in Counter(title.casefold() for title in titles).items():
        if count > 1:
            warnings.append(f"duplicate record title: {title}")

    note_paths, note_stems = build_note_index(vault)
    incoming: Counter[Path] = Counter()
    outgoing: Counter[Path] = Counter()
    record_by_path = {path.relative_to(vault).with_suffix("").as_posix().casefold(): path for path in records}
    record_by_stem: dict[str, list[Path]] = defaultdict(list)
    for path in records:
        record_by_stem[path.stem.casefold()].append(path)

    for path, (metadata, body) in records.items():
        serialized = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "\n" + body
        for raw_link in extract_wikilinks(serialized):
            target = normalize_wikilink(raw_link)
            if not target or target.casefold().endswith(".base"):
                continue
            target_key = target.casefold()
            target_stem = Path(target).name.casefold()
            if target_key not in note_paths and target_stem not in note_stems:
                warnings.append(f"{path.relative_to(vault)}: unresolved wikilink [[{raw_link}]]")
                continue
            target_path = record_by_path.get(target_key)
            if target_path is None and len(record_by_stem.get(target_stem, [])) == 1:
                target_path = record_by_stem[target_stem][0]
            if target_path and target_path != path:
                outgoing[path] += 1
                incoming[target_path] += 1

    for path, (metadata, _) in records.items():
        if metadata.get("record_type") in {"dashboard", "inbox"}:
            continue
        if not incoming[path] and not outgoing[path]:
            warnings.append(f"{path.relative_to(vault)}: orphan knowledge record")

    return {"counts": dict(sorted(counts.items())), "errors": sorted(set(errors)), "warnings": sorted(set(warnings))}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate schema, links, provenance, and safety of the Obsidian AI knowledge base.")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    args = parser.parse_args()

    result = validate_vault(resolve_vault(args.vault))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Records:", ", ".join(f"{key}={value}" for key, value in result["counts"].items()) or "none")
        for warning in result["warnings"]:
            print(f"WARNING: {warning}")
        for error in result["errors"]:
            print(f"ERROR: {error}")
        print(f"Validation: {'FAILED' if result['errors'] else 'OK'} ({len(result['errors'])} errors, {len(result['warnings'])} warnings)")
    return 1 if result["errors"] or (args.strict and result["warnings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
