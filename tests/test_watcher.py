import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import kn
import features
import watcher


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "store"
        self.directory.mkdir()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "Auth.py").write_text("class Auth: pass")
        self.env = patch.dict(
            os.environ, {"KN_HOME": str(self.directory), "LAZYTOKEN_DISABLE_AUTOWATCH": "1"}
        )
        self.env.start()
        self.db = kn.connect()
        kn.sync(self.root, self.db)
        self.project = str(self.root.resolve())
        self.engine = watcher.ProjectWatcher(kn, self.db, debounce=1, full_interval=300)

    def tearDown(self):
        watcher.stop(kn)
        self.db.close()
        self.env.stop()
        self.temp.cleanup()

    def test_git_inventory_does_not_open_console_windows(self):
        with patch("kn.subprocess.run") as run:
            run.return_value.stdout = b"Auth.py\0"
            self.assertEqual(kn.list_files(self.root), ["Auth.py"])
        expected = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.assertEqual(run.call_args.kwargs["creationflags"], expected)

    def test_invalid_interval_reports_readable_bounds(self):
        import sys

        result = subprocess.run(
            [sys.executable, str(Path(kn.__file__)), "watch", "start", "--interval", "0"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("interval must be 0.25 to 300 seconds", result.stderr)

    def test_changes_are_debounced_and_memory_stales_without_trust_promotion(self):
        proposal = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Auth lesson",
                "summary": "Use the authentication service",
                "task": "Fixture",
                "evidence": "Synthetic fixture",
                "paths": ["Auth.py"],
            },
            self.db,
        )
        features.review(
            kn,
            {"project": self.project, "id": proposal["id"], "action": "approve", "verified": True},
            self.db,
        )
        self.engine.tick(now=0)
        (self.root / "Auth.py").write_text("class UpdatedAuth: pass")
        (self.root / "New.py").write_text("class New: pass")
        self.engine.tick(now=1)
        self.assertEqual(features.health(self.db, proposal["id"])["freshness"], "current")
        self.engine.tick(now=2)
        self.assertEqual(features.health(self.db, proposal["id"])["freshness"], "stale")
        self.assertTrue(
            self.db.execute("SELECT 1 FROM symbols WHERE name='UpdatedAuth'").fetchone()
        )
        self.assertEqual(self.db.execute("SELECT count(*) FROM assets").fetchone()[0], 1)
        (self.root / "New.py").rename(self.root / "Renamed.py")
        (self.root / "Auth.py").unlink()
        self.engine.tick(now=3)
        self.engine.tick(now=4)
        paths = {
            r[0]
            for r in self.db.execute("SELECT path FROM files WHERE project_id=?", (self.project,))
        }
        self.assertEqual(paths, {"Renamed.py"})

    def test_unchanged_files_are_not_reread_and_secrets_are_excluded(self):
        self.engine.tick(now=0)
        (self.root / "Other.py").write_text("class Other: pass")
        (self.root / ".env").write_text("NOT_REAL_SECRET=fixture")
        original = Path.open

        def checked(path, *args, **kwargs):
            if path == self.root / "Auth.py" and args and args[0] == "rb":
                raise AssertionError("Unchanged source reread")
            return original(path, *args, **kwargs)

        self.engine.tick(now=1)
        with patch.object(Path, "open", checked):
            self.engine.tick(now=2)
        self.assertFalse(self.db.execute("SELECT 1 FROM files WHERE path='.env'").fetchone())
        with patch("kn.sync", wraps=kn.sync) as sync:
            self.engine.tick(now=3)
            self.assertEqual(sync.call_count, 0)

    def test_unavailable_project_preserves_index_and_recovers(self):
        self.engine.tick(now=0)
        moved = self.root.with_name("temporarily-offline")
        self.root.rename(moved)
        self.engine.tick(now=1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM files").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM index_errors").fetchone()[0], 1)
        moved.rename(self.root)
        self.engine.tick(now=2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM index_errors").fetchone()[0], 0)

    def test_one_store_lock_and_live_worker_edit_sync(self):
        lock = watcher.StoreLock(self.directory / "watch.lock")
        self.assertTrue(lock.acquire())
        second = watcher.StoreLock(self.directory / "watch.lock")
        self.assertFalse(second.acquire())
        second.close()
        lock.close()
        started = watcher.start(kn, force=True, interval=0.25, debounce=0)
        self.assertTrue(started["running"], started)
        again = watcher.start(kn, force=True)
        self.assertEqual(again["pid"], started["pid"])
        (self.root / "Auth.py").write_text("class LiveChange: pass")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.db.execute("SELECT 1 FROM symbols WHERE name='LiveChange'").fetchone():
                break
            time.sleep(0.1)
        else:
            self.fail("Live worker did not sync the changed file")
        self.assertTrue(watcher.stop(kn)["stopped"])
        self.assertFalse(watcher.status(self.directory)["running"])

    def test_unselected_repository_is_not_indexed(self):
        unrelated = Path(self.temp.name) / "unselected"
        unrelated.mkdir()
        (unrelated / "No.py").write_text("class No: pass")
        self.engine.tick(now=0)
        self.assertFalse(
            self.db.execute(
                "SELECT 1 FROM projects WHERE root=?", (str(unrelated.resolve()),)
            ).fetchone()
        )

    def test_watcher_adaptive_polling_backoff_on_idle(self):
        """M6 / F20: Watcher scales effective polling interval up when repository is idle."""
        watcher_engine = watcher.ProjectWatcher(
            kn, self.db, debounce=0.5, min_interval=0.5, max_interval=5.0, idle_backoff_steps=3
        )
        self.assertEqual(watcher_engine.effective_interval, 0.5)
        # Initial tick sets baseline (has_changes is True on initial sync)
        watcher_engine.tick(now=0)
        self.assertEqual(watcher_engine.effective_interval, 0.5)
        # Successive idle ticks scale interval up
        watcher_engine.tick(now=1)
        self.assertGreater(watcher_engine.effective_interval, 0.5)
        watcher_engine.tick(now=2)
        watcher_engine.tick(now=3)
        self.assertEqual(watcher_engine.effective_interval, 5.0)
        self.assertGreaterEqual(watcher_engine.consecutive_idle, 3)

    def test_watcher_fast_poll_recovery_on_file_change(self):
        """M6 / F20: Watcher immediately recovers to min_interval upon detecting a file change."""
        watcher_engine = watcher.ProjectWatcher(
            kn, self.db, debounce=1.0, min_interval=0.5, max_interval=5.0, idle_backoff_steps=3
        )
        watcher_engine.tick(now=0)
        watcher_engine.tick(now=1)
        watcher_engine.tick(now=2)
        watcher_engine.tick(now=3)
        self.assertEqual(watcher_engine.effective_interval, 5.0)

        # Mutate file
        (self.root / "Auth.py").write_text("class MutatedAuth: pass")
        watcher_engine.tick(now=4)
        # Should instantly reset to min_interval
        self.assertEqual(watcher_engine.effective_interval, 0.5)
        self.assertEqual(watcher_engine.consecutive_idle, 0)

    def test_incremental_directory_reconciliation(self):
        """Nested file edits are detected even when the directory timestamp stays unchanged."""
        sub1 = self.root / "sub1"
        sub1.mkdir()
        (sub1 / "file1.py").write_text("class F1: pass")
        sub2 = self.root / "sub2"
        sub2.mkdir()
        (sub2 / "file2.py").write_text("class F2: pass")

        watcher_engine = watcher.ProjectWatcher(kn, self.db, debounce=0.5, full_interval=300)
        watcher_engine.tick(now=0)  # full scan
        state = watcher_engine.projects[self.project]
        self.assertIn("sub1/file1.py", state["file_cache"])
        self.assertIn("sub2/file2.py", state["file_cache"])

        # Modify only file in sub1 while preserving the directory timestamp.
        before = (sub1.stat().st_atime_ns, sub1.stat().st_mtime_ns)
        (sub1 / "file1.py").write_text("class F1Updated: pass")
        os.utime(sub1, ns=before)
        current = watcher.incremental_snapshot(kn, self.root, state)
        self.assertIsNotNone(current)
        self.assertIn("sub1/file1.py", current)
        self.assertIn("sub2/file2.py", current)
        self.assertNotEqual(current["sub1/file1.py"], state["applied"]["sub1/file1.py"])
        watcher_engine.tick(now=1)
        watcher_engine.tick(now=2)
        self.assertTrue(self.db.execute("SELECT 1 FROM symbols WHERE name='F1Updated'").fetchone())

    def test_burst_write_coalescing_within_debounce(self):
        """M6 / F20: Multiple rapid file edits within debounce window trigger single sync once settled."""
        watcher_engine = watcher.ProjectWatcher(kn, self.db, debounce=1.0, full_interval=300)
        watcher_engine.tick(now=0)

        # Perform 5 rapid writes between t=0.1 and t=0.5
        for i in range(5):
            (self.root / "Auth.py").write_text(f"class AuthV{i}: pass")
            watcher_engine.tick(now=0.1 * (i + 1))

        # Still within debounce (< 1.0s after last change at 0.5s)
        self.assertFalse(self.db.execute("SELECT 1 FROM symbols WHERE name='AuthV4'").fetchone())

        # Tick at t=1.6 (> 1.0s after t=0.5)
        with patch.object(kn, "sync", wraps=kn.sync) as mock_sync:
            watcher_engine.tick(now=1.6)
            self.assertEqual(mock_sync.call_count, 1)

        self.assertTrue(self.db.execute("SELECT 1 FROM symbols WHERE name='AuthV4'").fetchone())


if __name__ == "__main__":
    unittest.main()
