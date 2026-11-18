"""The pinned real-repository assessment rejects drifting or unsafe labels."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest

from benchmark import real_repo_assessment


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class RealRepoAssessmentTests(unittest.TestCase):
    def test_assessment_uses_isolated_index_and_reports_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            git(root, "init", "-q")
            git(root, "config", "user.name", "TokSmart Test")
            git(root, "config", "user.email", "test@example.invalid")
            (root / "handler.py").write_text("def handle_request():\n    return True\n")
            git(root, "add", "handler.py")
            git(root, "commit", "-qm", "fixture")
            corpus = {
                "schema": "toksmart-real-repo-cases-v1",
                "revision": git(root, "rev-parse", "HEAD"),
                "label_provenance": "Test-authored label for a committed source file.",
                "cases": [
                    {
                        "id": "handler",
                        "task": "Find handle_request",
                        "relevant": ["handler.py"],
                        "expected_abstention": False,
                        "rationale": "handler.py defines handle_request.",
                    }
                ],
            }
            report = real_repo_assessment.assess(root, corpus)
            self.assertEqual(report["indexed_files"], 1)
            self.assertEqual(report["metrics"]["recall_at_k"], 1.0)
            self.assertGreaterEqual(report["observations"][0]["latency_ms"], 0)
            self.assertFalse((root / "network.sqlite3").exists())
            self.assertIn(
                "Estimated response tokens are not provider usage", report["limitations"][1]
            )

            (root / "handler.py").write_text("def changed():\n    return True\n")
            with self.assertRaisesRegex(ValueError, "uncommitted or untracked files"):
                real_repo_assessment.validate_cases(corpus, root)
            (root / "handler.py").write_text("def handle_request():\n    return True\n")
            (root / "extra.py").write_text("def extra():\n    pass\n")
            with self.assertRaisesRegex(ValueError, "uncommitted or untracked files"):
                real_repo_assessment.validate_cases(corpus, root)

    def test_revision_and_path_labels_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            git(root, "init", "-q")
            git(root, "config", "user.name", "TokSmart Test")
            git(root, "config", "user.email", "test@example.invalid")
            (root / "source.py").write_text("def source():\n    pass\n")
            git(root, "add", "source.py")
            git(root, "commit", "-qm", "fixture")
            corpus = {
                "schema": "toksmart-real-repo-cases-v1",
                "revision": "0" * 40,
                "label_provenance": "Test labels",
                "cases": [
                    {
                        "id": "one",
                        "task": "source",
                        "relevant": ["source.py"],
                        "expected_abstention": False,
                        "rationale": "source definition",
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "revision differs"):
                real_repo_assessment.validate_cases(corpus, root)
            corpus["revision"] = git(root, "rev-parse", "HEAD")
            corpus["cases"][0]["relevant"] = ["../source.py"]
            with self.assertRaisesRegex(ValueError, "not a file"):
                real_repo_assessment.validate_cases(corpus, root)
