"""Unit tests for Persistent Task-Session State & Recovery (Milestone 4 / Feature 20)."""

from __future__ import annotations

import tempfile
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
            tests = res2["verified_state"]["test_outcomes"]
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
        self.assertEqual(len(cp["verified_state"]["test_outcomes"]), 1)
        self.assertEqual(cp["verified_state"]["test_outcomes"][0]["test_name"], "test_core_perf")


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
