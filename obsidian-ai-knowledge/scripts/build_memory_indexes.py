from __future__ import annotations

import argparse
from pathlib import Path

from common import resolve_vault
from decision_index import save_index as save_decision_index
from solution_index import save_index as save_solution_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Build compact solution and decision recall indexes.")
    parser.add_argument("--vault", type=Path)
    args = parser.parse_args()
    vault = resolve_vault(args.vault)
    solution_path = save_solution_index(vault)
    decision_path = save_decision_index(vault)
    print(f"Solution index: {solution_path}")
    print(f"Decision index: {decision_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
