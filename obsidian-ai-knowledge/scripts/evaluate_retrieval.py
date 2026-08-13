from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from common import load_config, resolve_vault
from recall_solution import recall_solutions


def default_cases_path(vault: Path) -> Path:
    config = load_config(vault)
    return vault / str(config.get("knowledge_root", "00-AI知识库")) / "_系统" / "检索验收案例.yaml"


def default_report_path(vault: Path) -> Path:
    config = load_config(vault)
    return vault / str(config.get("knowledge_root", "00-AI知识库")) / "_系统" / "检索验收报告.md"


def load_cases(path: Path) -> list[dict[str, Any]]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = loaded.get("cases") if isinstance(loaded, dict) else None
    if not isinstance(cases, list):
        raise ValueError(f"cases must be a YAML list: {path}")
    return [case for case in cases if isinstance(case, dict)]


def evaluate_case(vault: Path, case: dict[str, Any], *, limit: int) -> dict[str, Any]:
    query = str(case.get("query") or "").strip()
    results = recall_solutions(vault, query, limit=limit)
    ids = [str(item.get("record_id") or "") for item in results]
    expected = [str(value) for value in case.get("expected_any") or []]
    forbidden = [str(value) for value in case.get("forbidden") or []]
    expected_hits = [value for value in expected if value in ids]
    forbidden_hits = [value for value in forbidden if value in ids]
    trusted_required = bool(case.get("trusted_required"))
    trusted_hits = [
        item["record_id"]
        for item in results
        if item.get("record_id") in expected_hits and item.get("trust_state") == "trusted"
    ]
    passed = bool(expected_hits) and not forbidden_hits and (not trusted_required or bool(trusted_hits))
    return {
        "name": str(case.get("name") or query),
        "query": query,
        "passed": passed,
        "expected_hits": expected_hits,
        "forbidden_hits": forbidden_hits,
        "trusted_hits": trusted_hits,
        "top_ids": ids,
    }


def evaluate(vault: Path, cases: list[dict[str, Any]], *, limit: int = 8) -> dict[str, Any]:
    results = [evaluate_case(vault, case, limit=limit) for case in cases]
    passed = sum(1 for result in results if result["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "hit_at_k": passed / len(results) if results else 0.0,
        "results": results,
    }


def render_report(report: dict[str, Any], limit: int) -> str:
    lines = [
        "# 检索回归验收",
        "",
        f"- 结果：{report['passed']}/{report['total']} 通过",
        f"- hit@{limit}：{report['hit_at_k']:.0%}",
        f"- 失败：{report['failed']}",
        "",
    ]
    for result in report["results"]:
        mark = "PASS" if result["passed"] else "FAIL"
        lines.extend(
            [
                f"## [{mark}] {result['name']}",
                "",
                f"- 查询：{result['query']}",
                f"- 预期命中：{', '.join(result['expected_hits']) or '—'}",
                f"- 可信命中：{', '.join(result['trusted_hits']) or '—'}",
                f"- 禁止命中：{', '.join(result['forbidden_hits']) or '—'}",
                f"- 前 {limit} 项：{', '.join(result['top_ids']) or '—'}",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic regression cases for knowledge retrieval.")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    cases_path = (args.cases or default_cases_path(vault)).resolve(strict=False)
    limit = max(args.limit, 1)
    report = evaluate(vault, load_cases(cases_path), limit=limit)
    rendered = render_report(report, limit)
    if args.save or args.output:
        output = (args.output or default_report_path(vault)).resolve(strict=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(rendered)
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())