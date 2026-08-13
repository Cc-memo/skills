from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import resolve_vault
from recall_solution import recall_solutions


def _clean(value: Any) -> str:
    return str(value or "").strip()


def build_review(payload: dict[str, Any], *, vault: Path, limit: int = 3) -> dict[str, Any]:
    problems = payload.get("problems") or []
    if not isinstance(problems, list):
        raise ValueError("problems must be a list")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(problems, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"problem {index} must be an object")
        symptom = _clean(item.get("symptom"))
        if not symptom:
            raise ValueError(f"problem {index} requires symptom")
        query_parts = [
            symptom,
            _clean(item.get("error_signature")),
            _clean(item.get("technology")),
            _clean(item.get("project")),
            _clean(item.get("root_cause")),
        ]
        query = " ".join(part for part in query_parts if part)
        matches = recall_solutions(vault, query, limit=limit) if query else []
        normalized.append(
            {
                "candidate_id": f"problem-candidate-{index}",
                "symptom": symptom,
                "error_signature": _clean(item.get("error_signature")),
                "technology": _clean(item.get("technology")),
                "project": _clean(item.get("project")),
                "status": _clean(item.get("status")) or "investigating",
                "root_cause": _clean(item.get("root_cause")),
                "evidence": item.get("evidence") if isinstance(item.get("evidence"), list) else [],
                "recommended_action": (
                    "update_existing_problem"
                    if any(match.get("record_type") == "problem" for match in matches)
                    else "create_problem_or_inbox_after_verification"
                ),
                "historical_matches": [
                    {
                        "record_id": match.get("record_id"),
                        "title": match.get("title"),
                        "record_type": match.get("record_type"),
                        "status": match.get("status"),
                        "trust_state": match.get("trust_state"),
                        "score": match.get("score"),
                        "root_cause": match.get("root_cause"),
                        "path": match.get("relative_path") or match.get("path"),
                    }
                    for match in matches
                ],
            }
        )

    return {
        "schema_version": 1,
        "review_type": "conversation_review",
        "conversation_title": _clean(payload.get("conversation_title")),
        "conversation_summary": _clean(payload.get("conversation_summary")),
        "decisions": payload.get("decisions") if isinstance(payload.get("decisions"), list) else [],
        "deliverables": payload.get("deliverables") if isinstance(payload.get("deliverables"), list) else [],
        "open_questions": payload.get("open_questions") if isinstance(payload.get("open_questions"), list) else [],
        "problems": normalized,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review a conversation summary, expose problem candidates, and recall prior solutions."
    )
    parser.add_argument("--input", required=True, type=Path, help="JSON conversation review payload")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    review = build_review(payload, vault=resolve_vault(args.vault), limit=max(args.limit, 1))
    rendered = json.dumps(review, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
