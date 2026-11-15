import sqlite3
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import features
import kn

ROOT = Path(__file__).resolve().parents[1]


class NotebookFixtureTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "Git required to reproduce parent ignore rules")
    def test_preparation_isolated_from_parent_gitignore(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
            dest = root / "ignored" / "trial"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "benchmark/prepare_notebook.py"),
                    str(dest),
                    "--memory",
                    "current",
                ],
                check=True,
                capture_output=True,
            )
            with closing(sqlite3.connect(dest / "network.sqlite3")) as db:
                paths = {row[0] for row in db.execute("SELECT path FROM files")}
            self.assertTrue({"notebook.py", "test_notebook.py"}.issubset(paths))

    def test_preparation_and_retrieval(self):
        with tempfile.TemporaryDirectory() as temp:
            for variant in ("none", "current", "stale"):
                dest = Path(temp) / variant
                subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "benchmark/prepare_notebook.py"),
                        str(dest),
                        "--memory",
                        variant,
                    ],
                    check=True,
                    capture_output=True,
                )
                with closing(sqlite3.connect(dest / "network.sqlite3")) as db:
                    count = db.execute(
                        "SELECT count(*) FROM memory_proposals WHERE status='approved'"
                    ).fetchone()[0]
                    self.assertEqual(count, int(variant != "none"))

                if variant != "none":
                    with closing(kn.connect(dest / "network.sqlite3")) as db:
                        proposal_id = db.execute("SELECT id FROM memory_proposals").fetchone()[0]
                        self.assertEqual(features.health(db, proposal_id)["freshness"], variant)

                if variant == "current":
                    with closing(kn.connect(dest / "network.sqlite3")) as db:
                        project_id = str((dest / "project").resolve())
                        ctx = kn.feature_call(
                            "task_context",
                            {
                                "project": project_id,
                                "task": "Add case-insensitive tag filtering to the notebook",
                            },
                            db,
                        )
                        self.assertEqual(ctx.get("decision"), "retrieve")
                        self.assertLessEqual(ctx.get("used_tokens", 9999), 250)
                        asset_names = [a.get("name") for a in ctx.get("results", [])]
                        self.assertIn("Notebook tag filtering", asset_names)


if __name__ == "__main__":
    unittest.main()
