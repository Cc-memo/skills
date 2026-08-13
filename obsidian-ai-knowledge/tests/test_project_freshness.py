from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from project_freshness import inspect_project  # noqa: E402


KNOWLEDGE_ROOT = "00-AI\u77e5\u8bc6\u5e93"
SYSTEM_DIR = "_\u7cfb\u7edf"
PROJECT_DIR = "\u9879\u76ee"


class ProjectFreshnessTests(unittest.TestCase):
    def make_vault(self, source: Path, watch: list[str] | None = None) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        system = vault / KNOWLEDGE_ROOT / SYSTEM_DIR
        system.mkdir(parents=True)
        (system / "config.yaml").write_text(f"schema_version: 2\nknowledge_root: {KNOWLEDGE_ROOT}\n", encoding="utf-8")
        watch_yaml = ""
        if watch:
            watch_yaml = "freshness_watch:\n" + "".join(f"  - {item}\n" for item in watch)
        project = vault / KNOWLEDGE_ROOT / PROJECT_DIR / "Demo.md"
        project.parent.mkdir(parents=True)
        project.write_text(
            "---\n"
            "schema_version: 2\nrecord_type: project\nrecord_id: project-demo\nstatus: active\n"
            "priority: high\ncreated: 2026-08-05\nupdated: 2026-08-05\narea: test\n"
            f'workspace: "{str(source).replace(chr(92), chr(92) * 2)}"\n'
            f"{watch_yaml}"
            "source: test\nreview_state: reviewed\nconfidence: high\nnext_action: test\n"
            "project_type: software\nproject_space: \"[[space]]\"\nlast_reviewed: 2026-08-05\n"
            "review_due: 2026-08-19\ntags: [test]\n---\n\n# Demo\n",
            encoding="utf-8",
        )
        return vault

    def test_watched_file_change_stays_stale_until_accept(self) -> None:
        source_temp = tempfile.TemporaryDirectory()
        self.addCleanup(source_temp.cleanup)
        source = Path(source_temp.name)
        watched = source / "README.md"
        watched.write_text("one", encoding="utf-8")
        vault = self.make_vault(source)

        self.assertEqual("current", inspect_project(vault, "Demo", mode="accept")["freshness_state"])
        watched.write_text("two", encoding="utf-8")
        self.assertEqual("stale", inspect_project(vault, "Demo", mode="scan")["freshness_state"])
        self.assertEqual("stale", inspect_project(vault, "Demo", mode="check")["freshness_state"])
        self.assertEqual("current", inspect_project(vault, "Demo", mode="accept")["freshness_state"])

    def test_sensitive_watch_is_never_read(self) -> None:
        source_temp = tempfile.TemporaryDirectory()
        self.addCleanup(source_temp.cleanup)
        source = Path(source_temp.name)
        (source / "README.md").write_text("safe", encoding="utf-8")
        secret = source / "x.cookies.txt"
        secret.write_text("secret-one", encoding="utf-8")
        vault = self.make_vault(source, ["README.md", "x.cookies.txt", ".env"])

        first = inspect_project(vault, "Demo", mode="accept")
        secret.write_text("secret-two", encoding="utf-8")
        second = inspect_project(vault, "Demo", mode="check")

        self.assertEqual(["README.md"], [item["path"] for item in first["files"]])
        self.assertEqual("current", second["freshness_state"])

    def test_git_head_change_triggers_stale(self) -> None:
        source_temp = tempfile.TemporaryDirectory()
        self.addCleanup(source_temp.cleanup)
        source = Path(source_temp.name)
        subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=source, check=True)
        readme = source / "README.md"
        readme.write_text("one", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
        subprocess.run(["git", "commit", "-m", "one"], cwd=source, check=True, capture_output=True)
        vault = self.make_vault(source)
        inspect_project(vault, "Demo", mode="accept")

        readme.write_text("two", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
        subprocess.run(["git", "commit", "-m", "two"], cwd=source, check=True, capture_output=True)

        self.assertEqual("stale", inspect_project(vault, "Demo", mode="check")["freshness_state"])


if __name__ == "__main__":
    unittest.main()
