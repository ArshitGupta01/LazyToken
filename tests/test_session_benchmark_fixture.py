import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import features
import kn

ROOT = Path(__file__).resolve().parents[1]


class SessionFixtureTests(unittest.TestCase):
    def test_preparation_and_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            for variant in ("none", "current", "stale"):
                dest = Path(temp) / variant
                subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "benchmark/prepare_sessions.py"),
                        str(dest),
                        "--follow-up",
                        "--memory",
                        variant,
                    ],
                    check=True,
                    capture_output=True,
                )
                project = dest / "project"
                check = [
                    sys.executable,
                    str(ROOT / "benchmark/session_acceptance.py"),
                    str(project),
                ]
                subprocess.run(check, check=True, capture_output=True)
                self.assertNotEqual(
                    subprocess.run(check + ["--follow-up"], capture_output=True).returncode, 0
                )
                handlers = project / "handlers.py"
                handlers.write_text(
                    handlers.read_text().replace(
                        "    session = store.get(token)",
                        "    session = authenticate(store, token, now)",
                    )
                )
                subprocess.run(check + ["--follow-up"], check=True, capture_output=True)
                with closing(sqlite3.connect(dest / "network.sqlite3")) as db:
                    count = db.execute(
                        "SELECT count(*) FROM memory_proposals WHERE status='approved'"
                    ).fetchone()[0]
                    self.assertEqual(count, int(variant != "none"))
                if variant != "none":
                    with closing(kn.connect(dest / "network.sqlite3")) as db:
                        proposal_id = db.execute("SELECT id FROM memory_proposals").fetchone()[0]
                        self.assertEqual(features.health(db, proposal_id)["freshness"], variant)


if __name__ == "__main__":
    unittest.main()
