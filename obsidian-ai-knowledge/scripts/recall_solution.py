from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import iter_record_paths, load_config, resolve_vault, split_frontmatter
from decision_index import (
    DECISION_MARKERS,
    build_entries as build_decision_entries,
    search_entries as search_decision_entries,
    search_index as search_decision_index,
)
from project_space import find_project_note
from search_knowledge import search_records, stringify, trust_state
from solution_index import search_index


ANSWER_TYPES = {"problem", "playbook"}
PROBE_THRESHOLD = 35
DECISION_PROBE_THRESHOLD = 20
ROUTES = {"auto", "problem", "decision", "project"}
PROBLEM_ROUTE_MARKERS = (
    "\u62a5\u9519", "\u9519\u8bef", "\u5931\u8d25", "\u5f02\u5e38", "\u5d29\u6e83", "\u65e0\u6cd5", "\u4e0d\u5de5\u4f5c", "\u914d\u7f6e", "\u5b89\u88c5",
    "error", "exception", "traceback", "failed", "failure", "crash", "bug", "config", "install",
)


def answer_priority(item: dict[str, Any]) -> tuple[int, int, str]:
    record_type = str(item.get("record_type") or "").casefold()
    status = str(item.get("status") or "").casefold()
    trust = str(item.get("trust_state") or "").casefold()
    relevance = int(item.get("score") or 0)
    if record_type == "problem":
        type_bonus = {"solved": 35, "closed": 30, "open": 12, "investigating": 10}.get(status, 8)
    elif record_type == "playbook":
        type_bonus = 30
    elif record_type == "session":
        type_bonus = 8
    else:
        type_bonus = 0
    trust_bonus = {"trusted": 18, "pending-review": 0, "unverified": -12, "low-confidence": -20}.get(trust, -5)
    return relevance + type_bonus + trust_bonus, relevance, str(item.get("path") or "")


def recall_solutions(vault: Path, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    indexed = search_index(vault, query, limit=limit)
    if indexed is not None:
        strongest = max((int(item.get("score") or 0) for item in indexed), default=0)
        if strongest < PROBE_THRESHOLD:
            evidence = search_records(
                vault,
                query,
                record_type="session",
                trusted_only=True,
                limit=max(limit * 2, 6),
                snippet_width=260,
            )
            merged = sorted(indexed + evidence, key=lambda item: (-int(item.get("score") or 0), item.get("path", "")))
            return merged[: max(limit, 1)]
        clues = search_records(vault, query, limit=max(limit * 2, 6), snippet_width=260)
        clues = [item for item in clues if item.get("trust_state") != "trusted"]
        return indexed + clues[: max(0, limit - len(indexed))]
    results = search_records(vault, query, record_type=None, limit=max(limit * 4, 16), snippet_width=520)
    answers = [item for item in results if item.get("record_type") in ANSWER_TYPES]
    answers.sort(key=lambda item: (-answer_priority(item)[0], -answer_priority(item)[1], answer_priority(item)[2]))
    clues = [item for item in results if item.get("trust_state") != "trusted"]
    selected = answers[: max(limit, 1)]
    selected_ids = {item.get("record_id") for item in selected}
    selected.extend(item for item in clues if item.get("record_id") not in selected_ids)
    return selected[: max(limit, 1)]


def recall_decisions(vault: Path, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
    indexed = search_decision_index(vault, query, limit=limit)
    if indexed is not None:
        return indexed
    return search_decision_entries(vault, build_decision_entries(vault), query, limit=max(limit, 1))


def detect_route(query: str, *, project: str | None = None) -> str:
    if project:
        return "project"
    normalized = query.casefold()
    if any(marker.casefold() in normalized for marker in PROBLEM_ROUTE_MARKERS):
        return "problem"
    if any(marker.casefold() in normalized for marker in DECISION_MARKERS):
        return "decision"
    return "problem"


def project_probe(vault: Path, project: str | None) -> dict[str, Any]:
    if not project:
        return {"match": False, "route": "project", "reason": "project-required", "next": "provide-project"}
    try:
        project_note = find_project_note(vault, load_config(vault), project)
        metadata, _ = split_frontmatter(project_note.read_text(encoding="utf-8"))
    except (OSError, ValueError, FileNotFoundError):
        return {"match": False, "route": "project", "reason": "project-not-found", "next": "solve-directly"}
    return {
        "match": True,
        "route": "project",
        "project": project_note.stem,
        "record_id": metadata.get("record_id"),
        "status": metadata.get("status"),
        "freshness_state": metadata.get("freshness_state", "unknown"),
        "next_action": stringify(metadata.get("next_action"))[:180],
        "next": "load-project-context",
    }


def _compact_match(candidate: dict[str, Any], *, route: str) -> dict[str, Any]:
    return {
        "match": True,
        "route": route,
        "record_id": candidate.get("record_id"),
        "record_type": candidate.get("record_type"),
        "score": int(candidate.get("score") or 0),
        "trust_state": candidate.get("trust_state"),
        "root_cause": stringify(candidate.get("root_cause"))[:160],
        "next": "load-detail",
    }


def probe_solution(
    vault: Path,
    query: str,
    *,
    min_score: int = PROBE_THRESHOLD,
    route: str = "auto",
    project: str | None = None,
) -> dict[str, Any]:
    selected_route = detect_route(query, project=project) if route == "auto" else route
    if selected_route == "project":
        return project_probe(vault, project)
    if selected_route == "decision":
        indexed = recall_decisions(vault, query, limit=1)
        decision_threshold = min(min_score, DECISION_PROBE_THRESHOLD)
        if indexed and int(indexed[0].get("score") or 0) >= decision_threshold:
            return _compact_match(indexed[0], route="decision")
        return {
            "match": False,
            "route": "decision",
            "reason": "weak-match" if indexed else "no-candidate",
            "score": int(indexed[0].get("score") or 0) if indexed else 0,
            "next": "solve-directly",
        }
    indexed = search_index(vault, query, limit=1)
    if indexed is None:
        return {
            "match": False,
            "route": "problem",
            "reason": "index-missing",
            "next": "solve-directly",
        }
    if not indexed:
        return {
            "match": False,
            "route": "problem",
            "reason": "no-candidate",
            "next": "solve-directly",
        }
    candidate = indexed[0]
    score = int(candidate.get("score") or 0)
    if score < min_score:
        return {
            "match": False,
            "route": "problem",
            "reason": "weak-match",
            "score": score,
            "next": "solve-directly",
        }
    return _compact_match(candidate, route="problem")


def solution_signature(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("record_type") or "").casefold(),
        stringify(item.get("solution_type")).casefold().strip(),
        stringify(item.get("root_cause")).casefold().strip(),
    )


def group_recall_results(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    trusted = [item for item in results if item.get("trust_state") == "trusted"]
    clues = [item for item in results if item.get("trust_state") != "trusted"]
    if not trusted:
        return {"primary": [], "alternatives": [], "evidence": [], "clues": clues}

    primary = trusted[:1]
    seen = {solution_signature(primary[0])}
    alternatives: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for item in trusted[1:]:
        signature = solution_signature(item)
        has_solution_detail = bool(signature[1] or signature[2])
        if item.get("record_type") in {"problem", "playbook"} and has_solution_detail and signature not in seen:
            alternatives.append(item)
            seen.add(signature)
        else:
            evidence.append(item)
    return {"primary": primary, "alternatives": alternatives, "evidence": evidence, "clues": clues}


def render_cues(query: str, results: list[dict[str, Any]], max_chars: int = 1400) -> str:
    lines = [
        "# \u65e2\u6709\u7b54\u6848\u5019\u9009",
        "",
        f"- \u67e5\u8be2\uff1a{query}",
        "- \u7528\u6cd5\uff1a\u9009\u62e9\u4e00\u4e2a record_id \u540e\uff0c\u518d\u7528 `--record-id <id> --mode detail` \u83b7\u53d6\u8be6\u60c5\u3002",
        "",
    ]
    for index, item in enumerate(results, start=1):
        root_cause = stringify(item.get("root_cause"))
        if len(root_cause) > 90:
            root_cause = root_cause[:87].rstrip() + "\u2026"
        lines.extend([
            f"{index}. {item.get('title') or '\u672a\u547d\u540d\u8bb0\u5f55'}",
            f"   id={item.get('record_id') or '\u2014'} | type={item.get('record_type') or '\u2014'} | trust={item.get('trust_state') or '\u2014'} | score={item.get('score')}",
            f"   root={root_cause or '\u2014'} | path={item.get('relative_path') or item.get('path') or '\u2014'}",
        ])
    if not results:
        lines.append("\u6682\u65e0\u53ef\u4fe1\u5019\u9009\u3002")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 12].rstrip() + "\n\u2026\uff08\u5df2\u622a\u65ad\uff09"


def extract_sections(body: str, wanted: tuple[str, ...]) -> list[tuple[str, str]]:
    headings = re.compile(r"(?m)^##\s+(.+?)\s*$")
    matches = list(headings.finditer(body))
    sections: list[tuple[str, str]] = []
    wanted_set = {item.casefold() for item in wanted}
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        if heading.casefold() not in wanted_set:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content = re.sub(r"\n{3,}", "\n\n", body[match.end() : end]).strip()
        if content:
            sections.append((heading, content))
    return sections


def load_record_detail(vault: Path, record_id: str) -> tuple[Path, dict[str, Any], str] | None:
    config = load_config(vault)
    for path in iter_record_paths(vault, config):
        metadata, body = split_frontmatter(path.read_text(encoding="utf-8"), strict=False)
        if str(metadata.get("record_id") or "") == record_id:
            return path, metadata, body
    return None


def render_detail(vault: Path, record_id: str, max_chars: int = 3200) -> str:
    loaded = load_record_detail(vault, record_id)
    if loaded is None:
        return f"# \u8bb0\u5f55\u8be6\u60c5\n\n\u672a\u627e\u5230 record_id\uff1a{record_id}"
    path, metadata, body = loaded
    trust = trust_state(metadata)
    lines = [
        "# \u65e2\u6709\u7b54\u6848\u8be6\u60c5",
        "",
        f"- \u6807\u9898\uff1a{path.stem}",
        f"- record_id\uff1a{record_id}",
        f"- \u7c7b\u578b/\u72b6\u6001/\u53ef\u4fe1\u5ea6\uff1a{metadata.get('record_type') or '\u2014'} / {metadata.get('status') or '\u2014'} / {trust}",
        f"- \u9879\u76ee\uff1a{stringify(metadata.get('project')) or '\u2014'}",
        f"- \u6839\u56e0\uff1a{stringify(metadata.get('root_cause')) or '\u2014'}",
        f"- \u65b9\u6848\u7c7b\u578b\uff1a{stringify(metadata.get('solution_type')) or '\u2014'}",
        f"- \u6765\u6e90\uff1a{metadata.get('source_ref') or '\u2014'}",
        "",
    ]
    wanted = ("\u73b0\u8c61", "\u6839\u56e0", "\u6700\u7ec8\u65b9\u6848", "\u89e3\u51b3\u65b9\u6848", "\u9a8c\u8bc1", "\u9a8c\u8bc1\u7ed3\u679c", "\u9632\u6b62\u590d\u53d1", "\u53ef\u590d\u7528\u7ed3\u8bba", "\u9650\u5236", "\u9057\u7559\u4e8b\u9879")
    for heading, content in extract_sections(body, wanted):
        lines.extend([f"## {heading}", "", content, ""])
    if len(lines) <= 12:
        lines.extend(["## \u6458\u8981", "", re.sub(r"\s+", " ", body).strip()[:1400], ""])
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 12].rstrip() + "\n\u2026\uff08\u8be6\u60c5\u5df2\u622a\u65ad\uff09"


def render_item(index: int, item: dict[str, Any]) -> list[str]:
    expanded = ", ".join(item.get("expanded_matched") or []) or "\u2014"
    return [
        f"### {index}. {item.get('title') or '\u672a\u547d\u540d\u8bb0\u5f55'}",
        "",
        f"- \u7c7b\u578b\uff1a{item.get('record_type') or 'unknown'}\uff1b\u72b6\u6001\uff1a{item.get('status') or '\u2014'}\uff1b\u53ef\u4fe1\u5ea6\uff1a{item.get('trust_state')}",
        f"- \u8def\u5f84\uff1a{item.get('path')}",
        f"- \u9879\u76ee\uff1a{stringify(item.get('project')) or '\u2014'}",
        f"- \u6839\u56e0\uff1a{stringify(item.get('root_cause')) or '\u2014'}",
        f"- \u65b9\u6848\u7c7b\u578b\uff1a{stringify(item.get('solution_type')) or '\u2014'}",
        f"- \u6700\u8fd1\u9a8c\u8bc1\uff1a{item.get('last_verified') or item.get('updated') or '\u2014'}",
        f"- \u6765\u6e90\uff1a{item.get('source_ref') or '\u2014'}",
        f"- \u547d\u4e2d\uff1a{', '.join(item.get('matched') or [])}",
        f"- \u540c\u4e49\u6269\u5c55\u547d\u4e2d\uff1a{expanded}",
        f"- \u6458\u8981\uff1a{item.get('snippet') or '\u2014'}",
        "",
    ]


def render_recall(query: str, results: list[dict[str, Any]], max_chars: int = 8000) -> str:
    lines = [
        "# \u65e2\u6709\u95ee\u9898\u5feb\u901f\u8c03\u53d6",
        "",
        f"- \u67e5\u8be2\uff1a{query}",
        "- \u8bf4\u660e\uff1a\u9996\u9009\u5df2\u89e3\u51b3\u95ee\u9898\u5361\u548c\u7a33\u5b9a\u7ecf\u9a8c\uff1b\u5176\u4ed6\u5df2\u9a8c\u8bc1\u65b9\u6cd5\u4f5c\u4e3a\u66ff\u4ee3\u65b9\u6848\uff0c\u666e\u901a\u4f1a\u8bdd\u4f5c\u4e3a\u652f\u6301\u8bc1\u636e\u3002",
        "- \u9ed8\u8ba4\u5df2\u6392\u9664\u5df2\u53d6\u4ee3\u3001\u64a4\u56de\u3001\u56de\u9000\u548c\u5e9f\u5f03\u8bb0\u5f55\uff1b\u5f85\u5ba1\u6838/\u672a\u9a8c\u8bc1\u8bb0\u5f55\u4e0d\u80fd\u76f4\u63a5\u5f53\u7b54\u6848\u3002",
        "",
    ]
    grouped = group_recall_results(results)
    sections = (
        ("\u9996\u9009\u5df2\u9a8c\u8bc1\u7b54\u6848", grouped["primary"]),
        ("\u5176\u4ed6\u5df2\u9a8c\u8bc1\u65b9\u6cd5", grouped["alternatives"]),
        ("\u652f\u6301\u8bc1\u636e", grouped["evidence"]),
        ("\u5f85\u6838\u5bf9\u7ebf\u7d22", grouped["clues"]),
    )
    for heading, group in sections:
        lines.extend([f"## {heading}", ""])
        if not group:
            lines.extend(["\u6682\u65e0\u3002", ""])
            continue
        for index, item in enumerate(group, start=1):
            lines.extend(render_item(index, item))
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 12].rstrip() + "\n\u2026\uff08\u5df2\u622a\u65ad\uff09"


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall prior verified solutions for a repeated problem.")
    parser.add_argument("--query", help="Error message, symptom, technology, or decision keywords")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--max-chars", type=int)
    parser.add_argument("--mode", choices=("probe", "cue", "compact", "full", "detail"), default="probe")
    parser.add_argument("--min-score", type=int, default=PROBE_THRESHOLD)
    parser.add_argument("--route", choices=sorted(ROUTES), default="auto")
    parser.add_argument("--project", help="Project name for the project route")
    parser.add_argument("--record-id", help="Fetch one exact record for the second retrieval stage")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    if args.record_id or args.mode == "detail":
        if not args.record_id:
            parser.error("--mode detail requires --record-id")
        print(render_detail(vault, args.record_id, max(args.max_chars or 3200, 800)))
        return 0
    if not args.query:
        parser.error("--query is required unless --record-id is provided")
    if args.mode == "probe":
        print(json.dumps(
            probe_solution(
                vault,
                args.query,
                min_score=max(args.min_score, 1),
                route=args.route,
                project=args.project,
            ),
            ensure_ascii=False,
        ))
        return 0
    selected_route = detect_route(args.query, project=args.project) if args.route == "auto" else args.route
    if selected_route == "project":
        print(json.dumps(project_probe(vault, args.project), ensure_ascii=False))
        return 0
    if selected_route == "decision":
        results = recall_decisions(vault, args.query, limit=max(args.limit, 1))
    else:
        results = recall_solutions(vault, args.query, limit=max(args.limit, 1))
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    elif args.mode == "cue":
        print(render_cues(args.query, results, max(args.max_chars or 1200, 600)))
    elif args.mode == "full":
        print(render_recall(args.query, results, max(args.max_chars or 8000, 1200)))
    else:
        print(render_recall(args.query, results, max(args.max_chars or 2200, 800)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
