"""Unit tests for Persistent Task-Session State & Recovery (Milestone 4 / Feature 20)."""

from __future__ import annotations

import tempfile
import sqlite3
import threading
import features
import unittest
from pathlib import Path

import broker
import kn


class TestTaskSessionSchemaMigration(unittest.TestCase):
    """Unit tests for Migration 6 task session schema creation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = kn.connect(Path(self.temp_dir.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_v6_session_state_is_migrated_with_its_owner(self):
        legacy = sqlite3.connect(":memory:")
        legacy.row_factory = sqlite3.Row
        legacy.executescript(
            """
            CREATE TABLE lazytoken_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);
            INSERT INTO lazytoken_migrations VALUES(6,0);
            CREATE TABLE task_sessions(session_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,goal TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active',source_digest TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
            INSERT INTO task_sessions VALUES('same','project-a','old','active','',0,0);
            CREATE TABLE session_decisions(id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,decision TEXT NOT NULL,rationale TEXT NOT NULL DEFAULT '',recorded_at INTEGER NOT NULL);
            INSERT INTO session_decisions VALUES(1,'same','keep','',0);
        """
        )
        features.migrate(legacy)
        self.assertEqual(
            legacy.execute("SELECT project_id FROM session_decisions").fetchone()[0], "project-a"
        )
        legacy.execute("INSERT INTO task_sessions VALUES('same','project-b','','active','',0,0)")
        self.assertEqual(legacy.execute("SELECT count(*) FROM task_sessions").fetchone()[0], 2)
        legacy.close()

    def test_concurrent_v6_migrations_are_idempotent(self):
        path = Path(self.temp_dir.name) / "legacy.sqlite3"
        legacy = sqlite3.connect(path)
        legacy.executescript(
            """
            CREATE TABLE lazytoken_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);
            INSERT INTO lazytoken_migrations VALUES(6,0);
            CREATE TABLE task_sessions(session_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,goal TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active',source_digest TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
        """
        )
        legacy.close()
        start = threading.Barrier(2)
        errors = []

        def migrate():
            db = sqlite3.connect(path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                start.wait()
                features.migrate(db)
            except Exception as exc:
                errors.append(exc)
            finally:
                db.close()

        threads = [threading.Thread(target=migrate) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_migration_6_tables_exist(self) -> None:
        tables = {
            r[0]
            for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        required_tables = [
            "task_sessions",
            "session_decisions",
            "session_blockers",
            "session_test_outcomes",
            "session_breadcrumbs",
        ]
        for tbl in required_tables:
            self.assertIn(tbl, tables, f"Missing Migration 6 table: {tbl}")

    def test_migration_6_indexes_exist(self) -> None:
        indexes = {
            r[0]
            for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        required_indexes = [
            "session_decisions_idx",
            "session_blockers_idx",
            "session_test_outcomes_idx",
            "session_breadcrumbs_idx",
        ]
        for idx in required_indexes:
            self.assertIn(idx, indexes, f"Missing Migration 6 index: {idx}")

    def test_migration_6_registered_in_migrations_table(self) -> None:
        row = self.db.execute("SELECT 1 FROM lazytoken_migrations WHERE version=6").fetchone()
        self.assertIsNotNone(row, "Migration version 6 not recorded in lazytoken_migrations")


class TestSessionCheckpointPersistence(unittest.TestCase):
    """Unit tests for session checkpoint persistence across restarts."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.db = kn.connect(self.db_path)
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "app.py").write_text("def run_app(): pass\n", encoding="utf-8")
        kn.sync(self.repo, self.db)
        self.project = str(self.repo.resolve())

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_project_isolation_updates_and_clear(self):
        other = Path(self.temp_dir.name) / "other"
        other.mkdir()
        (other / "other.py").write_text("pass\n")
        kn.sync(other, self.db)
        first = {
            "project": self.project,
            "session_id": "shared",
            "goal": "private",
            "decisions": ["secret"],
            "blockers": [{"blocker": "build", "status": "open"}],
        }
        broker.session_checkpoint(kn, first, self.db)
        second = broker.session_checkpoint(
            kn, {"project": str(other), "session_id": "shared", "goal": "other"}, self.db
        )
        self.assertEqual(second["goal"], "other")
        self.assertEqual(second["asserted_state"]["decisions"], [])
        result = broker.session_checkpoint(
            kn,
            {
                "project": self.project,
                "session_id": "shared",
                "blockers": [{"blocker": "build", "status": "resolved"}],
            },
            self.db,
        )
        self.assertEqual(result["asserted_state"]["blockers"][0]["status"], "resolved")
        broker.clear_session(
            kn, {"project": self.project, "session_id": "shared", "include_state": True}, self.db
        )
        result = broker.session_checkpoint(
            kn, {"project": self.project, "session_id": "shared"}, self.db
        )
        self.assertEqual(result["goal"], "")
        self.assertEqual(
            broker.session_checkpoint(kn, {"project": str(other), "session_id": "shared"}, self.db)[
                "goal"
            ],
            "other",
        )

    def test_read_only_and_write_error(self):
        self.db.execute("PRAGMA query_only=ON")
        result = broker.session_checkpoint(
            kn, {"project": self.project, "session_id": "new", "goal": "unsaved"}, self.db
        )
        self.assertIn("error", result)
        result = broker.session_checkpoint(
            kn, {"project": self.project, "session_id": "new", "read_only": True}, self.db
        )
        self.assertNotIn("error", result)
        self.db.execute("PRAGMA query_only=OFF")

    def test_acknowledge_synced_baseline(self):
        args = {"project": self.project, "session_id": "baseline"}
        broker.session_checkpoint(kn, args, self.db)
        (self.repo / "app.py").write_text("def changed(): pass\n")
        self.assertIn(
            "error",
            broker.session_checkpoint(
                kn, dict(args, acknowledge_source=True, goal="must roll back"), self.db
            ),
        )
        self.assertEqual(broker.session_checkpoint(kn, args, self.db)["goal"], "")
        kn.sync(self.repo, self.db)
        self.assertTrue(
            broker.session_checkpoint(kn, args, self.db)["source_invalidation"]["invalidated"]
        )
        self.assertFalse(
            broker.session_checkpoint(kn, dict(args, acknowledge_source=True), self.db)[
                "source_invalidation"
            ]["invalidated"]
        )

    def test_checkpoint_persists_goals_decisions_blockers_tests_breadcrumbs(self) -> None:
        session_id = "sess-persisted-1"
        args = {
            "project": self.project,
            "session_id": session_id,
            "goal": "Refactor app entrypoint",
            "decisions": [
                {"decision": "Use dependency injection", "rationale": "Better testability"}
            ],
            "blockers": [{"blocker": "Database connection pool exhausted", "status": "open"}],
            "test_outcomes": [
                {
                    "test_name": "test_app_startup",
                    "outcome": "passed",
                    "exit_code": 0,
                    "duration_ms": 14.5,
                }
            ],
            "breadcrumbs": [{"crumb_type": "checkpoint", "payload": "App initialized safely"}],
        }
        res1 = broker.session_checkpoint(kn, args, self.db)
        self.assertEqual(res1["session_id"], session_id)
        self.assertEqual(res1["goal"], "Refactor app entrypoint")

        # Close and reopen connection to simulate process restart
        self.db.close()
        fresh_db = kn.connect(self.db_path)
        try:
            res2 = broker.session_checkpoint(
                kn, {"project": self.project, "session_id": session_id}, fresh_db
            )
            self.assertEqual(res2["goal"], "Refactor app entrypoint")
            # Verify decisions
            decisions = res2["asserted_state"]["decisions"]
            self.assertEqual(len(decisions), 1)
            self.assertEqual(decisions[0]["decision"], "Use dependency injection")

            # Verify blockers
            blockers = res2["asserted_state"]["blockers"]
            self.assertEqual(len(blockers), 1)
            self.assertEqual(blockers[0]["blocker"], "Database connection pool exhausted")

            # Verify test outcomes
            tests = res2["asserted_state"]["test_outcomes"]
            self.assertEqual(len(tests), 1)
            self.assertEqual(tests[0]["test_name"], "test_app_startup")
            self.assertEqual(tests[0]["outcome"], "passed")

            # Verify recovery breadcrumbs
            crumbs = res2["recovery_breadcrumbs"]
            self.assertEqual(len(crumbs), 1)
            self.assertIn("App initialized safely", crumbs[0]["payload"])
        finally:
            fresh_db.close()
            self.db = kn.connect(self.db_path)


class TestEpistemicLayering(unittest.TestCase):
    """Unit tests for separating observed, asserted, and verified states."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = kn.connect(Path(self.temp_dir.name) / "test.sqlite3")
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "core.py").write_text(
            "class CoreEngine:\n    def execute(self): pass\n", encoding="utf-8"
        )
        kn.sync(self.repo, self.db)
        self.project = str(self.repo.resolve())

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_epistemic_layers_distinct_separation(self) -> None:
        session_id = "sess-epistemic"
        # Seed an item in session
        broker.task_context(
            kn,
            {"project": self.project, "task": "CoreEngine execute", "session_id": session_id},
            self.db,
        )

        cp = broker.session_checkpoint(
            kn,
            {
                "project": self.project,
                "session_id": session_id,
                "goal": "Optimize engine",
                "decisions": ["Keep backward compatibility"],
                "test_outcomes": [
                    {"test_name": "test_core_perf", "outcome": "passed", "exit_code": 0}
                ],
            },
            self.db,
        )

        # 1. Observed State
        self.assertIn("observed_state", cp)
        self.assertIsInstance(cp["observed_state"], dict)
        self.assertIn("files", cp["observed_state"])
        self.assertIn("symbols", cp["observed_state"])
        self.assertIn("active_graph", cp["observed_state"])

        # 2. Asserted State
        self.assertIn("asserted_state", cp)
        self.assertIsInstance(cp["asserted_state"], dict)
        self.assertEqual(cp["asserted_state"]["goal"], "Optimize engine")
        self.assertEqual(len(cp["asserted_state"]["decisions"]), 1)

        # 3. Verified State
        self.assertIn("verified_state", cp)
        self.assertIsInstance(cp["verified_state"], dict)
        self.assertEqual(len(cp["asserted_state"]["test_outcomes"]), 1)
        self.assertEqual(cp["asserted_state"]["test_outcomes"][0]["test_name"], "test_core_perf")


class TestSourceVersionInvalidation(unittest.TestCase):
    """Unit tests for detecting modified and deleted files against checkpoint digests."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = kn.connect(Path(self.temp_dir.name) / "test.sqlite3")
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "module_a.py").write_text("def alpha(): pass\n", encoding="utf-8")
        (self.repo / "module_b.py").write_text("def beta(): pass\n", encoding="utf-8")
        kn.sync(self.repo, self.db)
        self.project = str(self.repo.resolve())

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_clean_source_no_invalidation(self) -> None:
        session_id = "sess-clean"
        cp = broker.session_checkpoint(
            kn, {"project": self.project, "session_id": session_id}, self.db
        )
        inv = cp.get("source_invalidation", {})
        self.assertFalse(inv.get("invalidated", True))
        self.assertEqual(inv.get("changed_files"), [])
        self.assertEqual(inv.get("deleted_files"), [])

    def test_file_modification_triggers_invalidation(self) -> None:
        session_id = "sess-mod"
        # First checkpoint records initial source digest
        broker.session_checkpoint(kn, {"project": self.project, "session_id": session_id}, self.db)

        # Modify module_a.py on disk without sync
        (self.repo / "module_a.py").write_text("def alpha(): return 'modified'\n", encoding="utf-8")

        cp = broker.session_checkpoint(
            kn, {"project": self.project, "session_id": session_id}, self.db
        )
        inv = cp.get("source_invalidation", {})
        self.assertTrue(inv.get("invalidated", False))
        self.assertIn("module_a.py", inv.get("changed_files", []))

    def test_file_deletion_triggers_invalidation(self) -> None:
        session_id = "sess-del"
        broker.session_checkpoint(kn, {"project": self.project, "session_id": session_id}, self.db)

        # Delete module_b.py from disk
        (self.repo / "module_b.py").unlink()

        cp = broker.session_checkpoint(
            kn, {"project": self.project, "session_id": session_id}, self.db
        )
        inv = cp.get("source_invalidation", {})
        self.assertTrue(inv.get("invalidated", False))
        self.assertIn("module_b.py", inv.get("deleted_files", []))


class TestIdempotentSessionRecovery(unittest.TestCase):
    """Unit tests ensuring repeated checkpoint operations have zero side effects or duplicates."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = kn.connect(Path(self.temp_dir.name) / "test.sqlite3")
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "main.py").write_text("def main(): pass\n", encoding="utf-8")
        kn.sync(self.repo, self.db)
        self.project = str(self.repo.resolve())

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_repeated_checkpoint_no_duplicate_records(self) -> None:
        session_id = "sess-idempotent"
        args = {
            "project": self.project,
            "session_id": session_id,
            "goal": "Build robust idempotency",
            "decisions": ["Always check before insert"],
            "blockers": ["Network latency"],
            "breadcrumbs": ["Step 1 completed"],
        }
        # Call 5 times in a loop with identical input
        for _ in range(5):
            broker.session_checkpoint(kn, args, self.db)

        # Verify exact counts in database
        d_count = self.db.execute(
            "SELECT count(*) FROM session_decisions WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        self.assertEqual(d_count, 1)

        b_count = self.db.execute(
            "SELECT count(*) FROM session_blockers WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        self.assertEqual(b_count, 1)

        c_count = self.db.execute(
            "SELECT count(*) FROM session_breadcrumbs WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        self.assertEqual(c_count, 1)


if __name__ == "__main__":
    unittest.main()
