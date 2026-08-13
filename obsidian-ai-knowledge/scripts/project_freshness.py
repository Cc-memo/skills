from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from common import knowledge_root, load_config, resolve_vault, split_frontmatter
from project_space import find_project_note, update_frontmatter


DEFAULT_WATCH = [
    "package.json",
    "pyproject.toml",
    "README.md",
    "PRODUCT.md",
    "ROADMAP.md",
    "CHANGELOG.md",
    "docs/CHANGELOG.md",
    "AGENTS.md",
]
SENSITIVE_PARTS = {
    ".env",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "secret",
    "secrets",
    "session",
    "sessions",
    "token",
    "tokens",
    "authorization",
    "private-key",
    "private_key",
}
EXCLUDED_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".next", ".cache", "__pycache__"}


def is_sensitive(path: Path) -> bool:
    for part in path.parts:
        lowered = part.casefold()
        stem = Path(lowered).stem
        if lowered in SENSITIVE_PARTS or stem in SENSITIVE_PARTS:
            return True
        if any(marker in lowered for marker in ("cookie", "credential", "secret", "token", "authorization")):
            return True
    return False


def is_excluded(path: Path) -> bool:
    return any(part.casefold() in EXCLUDED_DIRS for part in path.parts)


def scalar_yaml(value: Any) -> str:
    return yaml.safe_dump(value, allow_unicode=True, default_flow_style=True, sort_keys=False).splitlines()[0]


def source_root(metadata: dict[str, Any]) -> Path | None:
    raw = metadata.get("repo") or metadata.get("workspace")
    if not raw:
        return None
    return Path(os.path.expandvars(str(raw))).expanduser().resolve(strict=False)


def watched_paths(root: Path, metadata: dict[str, Any]) -> list[Path]:
    entries = metadata.get("freshness_watch") or DEFAULT_WATCH
    if isinstance(entries, str):
        entries = [entries]
    found: dict[str, Path] = {}
    for raw_entry in entries:
        entry = str(raw_entry).strip()
        if not entry:
            continue
        expanded_text = os.path.expandvars(entry)
        expanded = Path(expanded_text).expanduser()
        has_glob = any(char in expanded_text for char in "*?[")
        if expanded.is_absolute() and has_glob:
            candidates = [Path(match) for match in glob.glob(str(expanded), recursive=True)]
        elif expanded.is_absolute():
            candidates = [expanded]
        elif has_glob:
            candidates = list(root.glob(entry))
        else:
            candidates = [root / expanded]
        for candidate in candidates:
            resolved = candidate.resolve(strict=False)
            if not resolved.is_file() or is_sensitive(resolved) or is_excluded(resolved):
                continue
            found[str(resolved).casefold()] = resolved
    return sorted(found.values(), key=lambda path: str(path).casefold())


def git_snapshot(root: Path) -> dict[str, Any] | None:
    probe = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if probe.returncode:
        return None
    git_root = Path(probe.stdout.strip()).resolve(strict=False)
    revision = subprocess.run(
        ["git", "-C", str(git_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout.strip()
    commit_time = subprocess.run(
        ["git", "-C", str(git_root), "log", "-1", "--format=%cI"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout.strip()
    dirty_probe = subprocess.run(
        ["git", "-C", str(git_root), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return {
        "root": str(git_root),
        "revision": revision,
        "commit_time": commit_time,
        "dirty": bool(dirty_probe.stdout.strip()),
    }


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot(metadata: dict[str, Any]) -> dict[str, Any]:
    root = source_root(metadata)
    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    if root is None or not root.exists():
        return {
            "state": "unknown",
            "checked_at": checked_at,
            "reason": "missing source root",
            "root": str(root) if root else None,
            "files": [],
        }

    git = git_snapshot(root)
    files = watched_paths(root, metadata)
    latest_mtime = max((path.stat().st_mtime for path in files), default=None)
    digest = hashlib.sha256()
    if git:
        digest.update(f"git:{git['revision']}:{int(git['dirty'])}\n".encode("utf-8"))
    file_items = []
    for path in files:
        file_hash = file_digest(path)
        try:
            display = path.relative_to(root).as_posix()
        except ValueError:
            display = str(path)
        stat = path.stat()
        digest.update(f"file:{display}:{stat.st_size}:{file_hash}\n".encode("utf-8"))
        file_items.append({"path": display, "size": stat.st_size, "sha256": file_hash})

    if not git and not files:
        return {
            "state": "unknown",
            "checked_at": checked_at,
            "reason": "no Git repository or watched files",
            "root": str(root),
            "files": [],
        }
    revision = git["revision"] if git else f"files:{len(files)}"
    return {
        "state": "observed",
        "checked_at": checked_at,
        "root": str(root),
        "fingerprint": digest.hexdigest(),
        "revision": revision,
        "latest_mtime": (
            datetime.fromtimestamp(latest_mtime).astimezone().isoformat(timespec="seconds") if latest_mtime else None
        ),
        "git": git,
        "files": file_items,
    }


def compare_snapshot(metadata: dict[str, Any], snapshot: dict[str, Any]) -> str:
    if snapshot.get("state") == "unknown":
        return "unknown"
    baseline = str(metadata.get("source_fingerprint") or "").strip()
    if not baseline:
        return "unknown"
    return "current" if baseline == snapshot.get("fingerprint") else "stale"


def persist_snapshot(path: Path, snapshot: dict[str, Any], state: str, *, accept: bool) -> None:
    text = path.read_text(encoding="utf-8")
    fields = {
        "freshness_state": scalar_yaml("current" if accept else state),
        "source_checked_at": scalar_yaml(snapshot.get("checked_at")),
        "source_observed_fingerprint": scalar_yaml(snapshot.get("fingerprint")),
        "source_observed_revision": scalar_yaml(snapshot.get("revision")),
        "source_latest_mtime": scalar_yaml(snapshot.get("latest_mtime")),
    }
    if accept:
        fields["source_fingerprint"] = scalar_yaml(snapshot.get("fingerprint"))
        fields["source_revision"] = scalar_yaml(snapshot.get("revision"))
        fields["source_accepted_at"] = scalar_yaml(snapshot.get("checked_at"))
    path.write_text(update_frontmatter(text, fields), encoding="utf-8")


def inspect_project(vault: Path, project: str, *, mode: str = "check") -> dict[str, Any]:
    config = load_config(vault)
    note_path = find_project_note(vault, config, project)
    metadata, _ = split_frontmatter(note_path.read_text(encoding="utf-8"))
    snapshot = build_snapshot(metadata)
    state = compare_snapshot(metadata, snapshot)
    if mode == "accept" and snapshot.get("state") == "unknown":
        raise ValueError(f"cannot accept unknown source state: {snapshot.get('reason')}")
    if mode in {"scan", "accept"}:
        persist_snapshot(note_path, snapshot, state, accept=mode == "accept")
    return {
        "project": note_path.stem,
        "project_note": str(note_path.relative_to(vault)),
        "mode": mode,
        "freshness_state": "current" if mode == "accept" else state,
        "baseline_fingerprint": metadata.get("source_fingerprint"),
        **snapshot,
    }


def all_projects(vault: Path) -> list[str]:
    config = load_config(vault)
    project_dir = knowledge_root(vault, config) / str(config["record_directories"]["project"])
    return [str(path.relative_to(vault)) for path in sorted(project_dir.rglob("*.md"))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare project knowledge with a safe repository/file fingerprint.")
    parser.add_argument("--vault", type=Path)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--project", help="Project title or project note path")
    target.add_argument("--all", action="store_true", help="Inspect all formal project records")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scan", action="store_true", help="Persist observed state without accepting a new baseline")
    mode.add_argument("--accept", action="store_true", help="Accept the observed fingerprint after human review")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    selected_mode = "accept" if args.accept else "scan" if args.scan else "check"
    projects = all_projects(vault) if args.all else [args.project]
    results = [inspect_project(vault, project, mode=selected_mode) for project in projects]
    if args.json:
        print(json.dumps(results if args.all else results[0], ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f"{result['project']}: {result['freshness_state']} ({selected_mode})")
            if result.get("reason"):
                print(f"  reason: {result['reason']}")
            print(f"  watched files: {len(result.get('files', []))}")
    return 0 if all(result["freshness_state"] != "unknown" for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
