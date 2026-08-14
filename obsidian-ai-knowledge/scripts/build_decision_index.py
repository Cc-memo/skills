from __future__ import annotations

import argparse
from pathlib import Path

from common import resolve_vault
from decision_index import save_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the compact trusted research and decision index.")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path = save_index(resolve_vault(args.vault), args.output)
    print(f"Saved decision index to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
