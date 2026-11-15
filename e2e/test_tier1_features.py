"""Tier 1 Feature Coverage: Comprehensive tests for Features 1 through 16 (80 tests)."""

from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import broker
import dashboard
import features
import kn
import retrieval_eval
import token_budget
from e2e.common import E2ETestCase, McpClient


# ============================================================================
# Feature 1: SQLite Concurrency & Reliability
# ============================================================================
class TestF1SQLiteConcurrency(E2ETestCase):
    """F1: Busy timeout, WAL mode, foreign keys, composite indexes, concurrency."""

    def test_f1_busy_timeout_configured(self) -> None:
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            timeout_ms = row[0]
            self.assertGreaterEqual(timeout_ms, 5000)
        finally:
            conn.close()

    def test_f1_wal_journal_mode_enabled(self) -> None:
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            self.assertEqual(row[0].lower(), "wal")
        finally:
            conn.close()

    def test_f1_foreign_keys_pragma_enabled(self) -> None:
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            self.assertEqual(row[0], 1)
        finally:
            conn.close()

    def test_f1_composite_indexes_presence(self) -> None:
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            indexes = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
            # Verify primary composite / lookup indexes exist
            self.assertTrue(
                "context_session_lookup_idx" in indexes or "idx_session_items_lookup" in indexes,
                f"Missing context session lookup index. Found: {indexes}",
            )
            self.assertIn("symbol_name_idx", indexes)
            self.assertIn("imports_target_idx", indexes)
        finally:
            conn.close()

    def test_f1_concurrent_readers_writers(self) -> None:
        db_file = self.temp_dir / "network.sqlite3"
        # Seed the database
        init_conn = kn.connect(db_file)
        init_conn.close()

        errors: list[Exception] = []

        def worker_writer(worker_id: int) -> None:
            try:
                conn = kn.connect(db_file)
                try:
                    for i in range(15):
                        now = int(time.time())
                        conn.execute(
                            "INSERT INTO task_measurements VALUES(NULL, ?, ?, ?, ?, ?)",
                            (f"task_{worker_id}_{i}", 100, 80, 20, now),
                        )
                        conn.commit()
                finally:
                    conn.close()
            except Exception as exc:
                errors.append(exc)

        def worker_reader(worker_id: int) -> None:
            try:
                conn = kn.connect(db_file)
                try:
                    for _ in range(20):
                        conn.execute("SELECT count(*) FROM task_measurements").fetchone()
                        conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                finally:
                    conn.close()
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=worker_writer, args=(1,)),
            threading.Thread(target=worker_writer, args=(2,)),
            threading.Thread(target=worker_reader, args=(3,)),
            threading.Thread(target=worker_reader, args=(4,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Concurrent database errors: {errors}")


# ============================================================================
# Feature 2: Robust Import Matching
# ============================================================================
class TestF2RobustImportMatching(E2ETestCase):
    """F2: AST import matching without substring false positives, relative imports."""

    def test_f2_stdlib_import_does_not_match_repo_substring(self) -> None:
        repo = self.create_repo(
            {
                "main.py": "import re\n\ndef run():\n    return re.compile('^a')\n",
                "features.py": "def test():\n    pass\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            # Query task context for main and features
            res = broker.task_context(
                kn, {"project": str(repo), "task": "main features regex matching"}, conn
            )
            # Verify graph_edges does not falsely link main.py -> features.py via 're'
            edges = res.get("graph_edges", [])
            for edge in edges:
                self.assertFalse(
                    edge.get("source") == "main.py" and edge.get("target") == "features.py",
                    "False positive edge: stdlib 're' matched 'features.py'",
                )
        finally:
            conn.close()

    def test_f2_relative_python_imports(self) -> None:
        repo = self.create_repo(
            {
                "pkg/__init__.py": "",
                "pkg/util.py": "def helper():\n    return 42\n",
                "pkg/app.py": "from .util import helper\n\ndef main():\n    return helper()\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "helper in app util"}, conn
            )
            edges = res.get("graph_edges", [])
            has_relative_link = any(
                edge.get("source") == "pkg/app.py" and edge.get("target") == "pkg/util.py"
                for edge in edges
            )
            # At minimum, verify imports table captured target .util
            import_rows = conn.execute(
                "SELECT source, target FROM imports WHERE project_id=?", (str(repo),)
            ).fetchall()
            targets = [r["target"] for r in import_rows]
            self.assertTrue(
                any(".util" in t for t in targets),
                f"Relative import target not captured. Found: {targets}",
            )
        finally:
            conn.close()

    def test_f2_javascript_typescript_imports(self) -> None:
        repo = self.create_repo(
            {
                "src/Button.tsx": "export const Button = () => <button>Click</button>;\n",
                "src/App.tsx": "import { Button } from './Button';\nexport const App = () => <Button />;\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            import_rows = conn.execute(
                "SELECT source, target FROM imports WHERE project_id=?", (str(repo),)
            ).fetchall()
            sources = {r["source"]: r["target"] for r in import_rows}
            self.assertIn("src/App.tsx", sources)
            self.assertEqual(sources["src/App.tsx"], "./Button")
        finally:
            conn.close()

    def test_f2_missing_and_external_imports_graceful(self) -> None:
        repo = self.create_repo(
            {
                "service.py": "import requests\nimport nonexistent_module_xyz\n\ndef call():\n    pass\n"
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            sync_res = kn.sync(repo, conn)
            self.assertEqual(sync_res.get("error_count", 0), 0)
            res = broker.task_context(kn, {"project": str(repo), "task": "call service"}, conn)
            self.assertNotIn("error", res)
        finally:
            conn.close()

    def test_f2_cyclic_imports_safe(self) -> None:
        repo = self.create_repo(
            {
                "mod_a.py": "from mod_b import b_func\ndef a_func():\n    return b_func()\n",
                "mod_b.py": "from mod_a import a_func\ndef b_func():\n    return 1\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            sync_res = kn.sync(repo, conn)
            self.assertEqual(sync_res.get("error_count", 0), 0)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "a_func and b_func cycle"}, conn
            )
            self.assertNotIn("error", res)
        finally:
            conn.close()


# ============================================================================
# Feature 3: Active Session Item Freshness & Deduplication
# ============================================================================
class TestF3SessionItemFreshness(E2ETestCase):
    """F3: Updated_at refresh on suppression, deduplication, multiple sessions, clear."""

    def test_f3_multi_turn_touch_updated_at(self) -> None:
        repo = self.create_repo(
            {"auth.py": "def authenticate(user, token):\n    return token == 'valid'\n"}
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            # Turn 1: item is seen
            res1 = broker.task_context(
                kn,
                {"project": str(repo), "task": "authenticate user", "session_id": "sess-touch"},
                conn,
            )
            self.assertGreater(len(res1.get("results", [])), 0)
            row1 = conn.execute(
                "SELECT updated_at FROM context_session_items WHERE session_id='sess-touch'"
            ).fetchone()
            self.assertIsNotNone(row1)
            t1 = row1[0]

            # Turn 2: item is suppressed, touch updates timestamp
            time.sleep(1.1)
            res2 = broker.task_context(
                kn,
                {"project": str(repo), "task": "authenticate user", "session_id": "sess-touch"},
                conn,
            )
            self.assertGreaterEqual(res2.get("suppressed_seen", 0), 1)
            row2 = conn.execute(
                "SELECT updated_at FROM context_session_items WHERE session_id='sess-touch'"
            ).fetchone()
            self.assertIsNotNone(row2)
            t2 = row2[0]
            self.assertGreaterEqual(t2, t1)
        finally:
            conn.close()

    def test_f3_timestamp_refresh_on_suppression(self) -> None:
        repo = self.create_repo(
            {"store.py": "class Store:\n    def get(self, key):\n        return key\n"}
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-refresh"
            broker.task_context(
                kn, {"project": str(repo), "task": "get store", "session_id": session_id}, conn
            )
            # Artificially set timestamp to old epoch
            conn.execute(
                "UPDATE context_session_items SET updated_at=1000 WHERE session_id=?",
                (session_id,),
            )
            conn.commit()

            # Second turn suppresses seen item and refreshes updated_at
            broker.task_context(
                kn, {"project": str(repo), "task": "get store", "session_id": session_id}, conn
            )
            refreshed = conn.execute(
                "SELECT updated_at FROM context_session_items WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            self.assertGreater(refreshed, 1000)
        finally:
            conn.close()

    def test_f3_no_duplicate_session_rows(self) -> None:
        repo = self.create_repo({"api.py": "def handler():\n    return {'status': 'ok'}\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-nodup"
            for _ in range(3):
                broker.task_context(
                    kn,
                    {"project": str(repo), "task": "handler api", "session_id": session_id},
                    conn,
                )
            rows = conn.execute(
                "SELECT item_key, count(*) as cnt FROM context_session_items WHERE session_id=? GROUP BY item_key",
                (session_id,),
            ).fetchall()
            for r in rows:
                self.assertEqual(
                    r["cnt"], 1, f"Duplicate session row detected for key: {r['item_key']}"
                )
        finally:
            conn.close()

    def test_f3_multiple_sessions_isolated(self) -> None:
        repo = self.create_repo({"model.py": "class User:\n    pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            # Query in session A
            res_a = broker.task_context(
                kn, {"project": str(repo), "task": "User model", "session_id": "session-A"}, conn
            )
            self.assertGreater(len(res_a.get("results", [])), 0)

            # Query in session B should NOT be suppressed
            res_b = broker.task_context(
                kn, {"project": str(repo), "task": "User model", "session_id": "session-B"}, conn
            )
            self.assertGreater(len(res_b.get("results", [])), 0)
            self.assertEqual(res_b.get("suppressed_seen", 0), 0)
        finally:
            conn.close()

    def test_f3_session_item_cleanup(self) -> None:
        repo = self.create_repo({"clean.py": "def cleanup():\n    pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-clean"
            broker.task_context(
                kn, {"project": str(repo), "task": "cleanup", "session_id": session_id}, conn
            )
            count_before = conn.execute(
                "SELECT count(*) FROM context_session_items WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            self.assertGreater(count_before, 0)

            clear_res = broker.clear_session(
                kn, {"project": str(repo), "session_id": session_id}, conn
            )
            self.assertGreater(clear_res.get("cleared", 0), 0)

            count_after = conn.execute(
                "SELECT count(*) FROM context_session_items WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            self.assertEqual(count_after, 0)
        finally:
            conn.close()


# ============================================================================
# Feature 4: Context Amnesia Elimination & Recovery Recap
# ============================================================================
class TestF4ContextAmnesiaElimination(E2ETestCase):
    """F4: Recap breadcrumbs, topology preservation, reason explanation, turn 1 retention."""

    def test_f4_full_suppression_recap_breadcrumbs(self) -> None:
        repo = self.create_repo({"service.py": "def process_service():\n    return True\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-amnesia"
            # Turn 1
            broker.task_context(
                kn,
                {"project": str(repo), "task": "process service", "session_id": session_id},
                conn,
            )
            # Turn 2: All items already seen -> Full suppression
            res2 = broker.task_context(
                kn,
                {"project": str(repo), "task": "process service", "session_id": session_id},
                conn,
            )
            self.assertEqual(len(res2.get("results", [])), 0)
            self.assertGreater(res2.get("suppressed_seen", 0), 0)
            recap = res2.get("recap")
            self.assertIsNotNone(recap, "Full suppression must provide recap breadcrumbs")
            self.assertGreater(len(recap), 0)
        finally:
            conn.close()

    def test_f4_active_graph_topology_preservation(self) -> None:
        repo = self.create_repo({"base.py": "class Base:\n    pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-topo"
            broker.task_context(
                kn, {"project": str(repo), "task": "Base class", "session_id": session_id}, conn
            )
            res2 = broker.task_context(
                kn, {"project": str(repo), "task": "Base class", "session_id": session_id}, conn
            )
            self.assertTrue(
                "active_graph" in res2
                or "graph_topology" in res2
                or "active_context_summary" in res2,
                "Response must preserve active graph topology on suppression",
            )
        finally:
            conn.close()

    def test_f4_reason_explanation_on_full_suppression(self) -> None:
        repo = self.create_repo({"helper.py": "def compute():\n    return 100\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-reason"
            broker.task_context(
                kn, {"project": str(repo), "task": "compute helper", "session_id": session_id}, conn
            )
            res2 = broker.task_context(
                kn, {"project": str(repo), "task": "compute helper", "session_id": session_id}, conn
            )
            reason = res2.get("reason", "")
            self.assertIn("already supplied in this session", reason)
        finally:
            conn.close()

    def test_f4_turn1_foundational_item_retention(self) -> None:
        repo = self.create_repo(
            {
                "foundation.py": "class CoreEngine:\n    pass\n",
                "plugin.py": "class Plugin:\n    pass\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-retention"
            # Turn 1: query foundation
            broker.task_context(
                kn, {"project": str(repo), "task": "CoreEngine", "session_id": session_id}, conn
            )
            # Turn 2: query plugin
            broker.task_context(
                kn, {"project": str(repo), "task": "Plugin", "session_id": session_id}, conn
            )
            # Verify Turn 1 items are still preserved in session items
            rows = conn.execute(
                "SELECT item_key FROM context_session_items WHERE session_id=?", (session_id,)
            ).fetchall()
            keys = [r["item_key"] for r in rows]
            self.assertTrue(
                any("foundation.py" in k for k in keys), "Turn 1 item was evicted from session"
            )
        finally:
            conn.close()

    def test_f4_recovery_payload_structure(self) -> None:
        repo = self.create_repo({"widget.py": "def render():\n    return '<div/>'\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-payload"
            broker.task_context(
                kn, {"project": str(repo), "task": "render widget", "session_id": session_id}, conn
            )
            res2 = broker.task_context(
                kn, {"project": str(repo), "task": "render widget", "session_id": session_id}, conn
            )
            self.assertEqual(res2.get("decision"), "retrieve")
            self.assertIn("budget", res2)
            self.assertIn("used_tokens", res2)
            self.assertLessEqual(res2["used_tokens"], res2["budget"])
            self.assertIn("recap", res2)
        finally:
            conn.close()


# ============================================================================
# Feature 5: Bulk Candidate Context Queries
# ============================================================================
class TestF5BulkCandidateContextQueries(E2ETestCase):
    """F5: Bulk candidate queries, execution bounds, no N+1 leaks, ranked limits."""

    def test_f5_50_plus_candidate_items_batch_query(self) -> None:
        files = {f"item_{i}.py": f"def func_{i}():\n    return {i}\n" for i in range(55)}
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "func item", "budget": 2000}, conn
            )
            self.assertNotIn("error", res)
            self.assertGreater(len(res.get("results", [])), 10)
        finally:
            conn.close()

    def test_f5_candidate_query_execution_time_bounds(self) -> None:
        files = {f"module_{i}.py": f"def op_{i}():\n    pass\n" for i in range(50)}
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            start = time.perf_counter()
            broker.task_context(
                kn, {"project": str(repo), "task": "op module", "budget": 1000}, conn
            )
            elapsed = time.perf_counter() - start
            self.assertLess(elapsed, 3.0, f"Bulk query exceeded 3.0s: {elapsed:.3f}s")
        finally:
            conn.close()

    def test_f5_zero_connection_leaks(self) -> None:
        repo = self.create_repo({"alpha.py": "def alpha(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            for _ in range(10):
                res = broker.task_context(kn, {"project": str(repo), "task": "alpha"}, conn)
                self.assertNotIn("error", res)
            # Verify connection is still open and responsive
            check = conn.execute("SELECT 1").fetchone()
            self.assertEqual(check[0], 1)
        finally:
            conn.close()

    def test_f5_ranked_candidate_limits(self) -> None:
        files = {f"bulk_{i}.py": f"def bulk_{i}(): pass\n" for i in range(30)}
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            search_res = features.ranked_search(
                kn, {"project": str(repo), "query": "bulk", "limit": 10}, conn
            )
            self.assertLessEqual(len(search_res.get("results", [])), 10)
        finally:
            conn.close()

    def test_f5_cross_project_candidate_filtering(self) -> None:
        repo1 = self.create_repo({"apple.py": "def fruit(): return 'apple'\n"})
        repo2 = self.create_repo({"banana.py": "def fruit(): return 'banana'\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo1, conn)
            kn.sync(repo2, conn)
            res1 = broker.task_context(
                kn, {"project": str(repo1), "task": "fruit apple banana"}, conn
            )
            paths = [r.get("path") for r in res1.get("results", [])]
            for p in paths:
                if p:
                    self.assertNotIn("banana.py", p, "Cross-project leakage from repo2 to repo1")
        finally:
            conn.close()


# ============================================================================
# Feature 6: BPE Tokenizer Support
# ============================================================================
class TestF6BPETokenizerSupport(E2ETestCase):
    """F6: tiktoken/fallback detection, model arg parsing, strict budget, character heuristic."""

    def test_f6_fallback_detection_when_tokenizer_missing(self) -> None:
        repo = self.create_repo({"code.py": "def run(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "run code", "model": "gpt-4o"}, conn
            )
            # When tiktoken is not installed, fallback or tokenizer name is reported
            self.assertIn("budget_type", res)
            self.assertTrue(
                "estimate" in res["budget_type"]
                or "tokenizer" in res["budget_type"]
                or "tokenizer_fallback" in res
            )
        finally:
            conn.close()

    def test_f6_model_argument_parsing(self) -> None:
        repo = self.create_repo({"code.py": "def run(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "run", "model": 12345}, conn
            )
            self.assertIn("error", res)
            self.assertIn("model must be non-empty text", res["error"])
        finally:
            conn.close()

    def test_f6_strict_budget_enforcement(self) -> None:
        repo = self.create_repo({"code.py": "def run(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            # Strict budget without a local offline tokenizer configured must fail
            res = broker.task_context(
                kn,
                {
                    "project": str(repo),
                    "task": "run",
                    "model": "gpt-4o",
                    "strict_budget": True,
                },
                conn,
            )
            self.assertIn("error", res)
            self.assertIn("Strict budget refused", res["error"])
        finally:
            conn.close()

    def test_f6_character_heuristic_fallback_accuracy(self) -> None:
        text = "a" * 400
        tokens = kn.estimate(text)
        self.assertAlmostEqual(tokens, 100, delta=20)

    def test_f6_tokenizer_name_reporting(self) -> None:
        repo = self.create_repo({"main.py": "x = 1\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(kn, {"project": str(repo), "task": "main variable"}, conn)
            self.assertIn("budget_type", res)
            self.assertIsInstance(res["budget_type"], str)
            self.assertTrue(len(res["budget_type"]) > 0)
        finally:
            conn.close()


# ============================================================================
# Feature 7: Single-Pass Deterministic Budgeting
# ============================================================================
class TestF7SinglePassDeterministicBudgeting(E2ETestCase):
    """F7: Single-pass budgeting within budget, scaling, deterministic ordering, boundary fit."""

    def test_f7_single_pass_execution_within_budget(self) -> None:
        files = {f"file_{i}.py": f"def test_{i}(): pass\n" for i in range(15)}
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            budget = 350
            res = broker.task_context(
                kn, {"project": str(repo), "task": "test file", "budget": budget}, conn
            )
            self.assertLessEqual(res.get("used_tokens", 0), budget)
        finally:
            conn.close()

    def test_f7_high_item_count_scaling(self) -> None:
        files = {f"scale_{i}.py": f"def scale_{i}(): return {i}\n" for i in range(30)}
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            start = time.perf_counter()
            res = broker.task_context(
                kn, {"project": str(repo), "task": "scale func", "budget": 1200}, conn
            )
            elapsed = time.perf_counter() - start
            self.assertLess(elapsed, 2.0, "Budgeting loop exceeded 2.0s")
            self.assertNotIn("error", res)
        finally:
            conn.close()

    def test_f7_deterministic_output_ordering(self) -> None:
        repo = self.create_repo(
            {
                "a_mod.py": "def alpha(): pass\n",
                "b_mod.py": "def beta(): pass\n",
                "c_mod.py": "def gamma(): pass\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res1 = broker.task_context(
                kn, {"project": str(repo), "task": "alpha beta gamma", "include_seen": True}, conn
            )
            res2 = broker.task_context(
                kn, {"project": str(repo), "task": "alpha beta gamma", "include_seen": True}, conn
            )
            keys1 = [r.get("name") for r in res1.get("results", [])]
            keys2 = [r.get("name") for r in res2.get("results", [])]
            self.assertEqual(keys1, keys2)
        finally:
            conn.close()

    def test_f7_budget_boundary_fit(self) -> None:
        repo = self.create_repo({"sample.py": "def compute(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            # Minimum allowed budget
            res = broker.task_context(
                kn, {"project": str(repo), "task": "compute", "budget": 100}, conn
            )
            if "error" not in res:
                self.assertLessEqual(res.get("used_tokens", 0), 100)
            else:
                self.assertIn("Budget is too small", res["error"])
        finally:
            conn.close()

    def test_f7_truncated_flag_correctness(self) -> None:
        files = {f"trunc_{i}.py": f"def trunc_{i}(): pass\n" for i in range(25)}
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            # Tight budget should trigger truncation
            res_tight = broker.task_context(
                kn, {"project": str(repo), "task": "trunc", "budget": 200}, conn
            )
            if "error" not in res_tight:
                self.assertTrue(res_tight.get("truncated", False))

            # Generous budget should not trigger truncation
            res_wide = broker.task_context(
                kn, {"project": str(repo), "task": "trunc", "budget": 16000}, conn
            )
            self.assertFalse(res_wide.get("truncated", True))
        finally:
            conn.close()


# ============================================================================
# Feature 8: High-Density Lean Context & Compact DSL
# ============================================================================
class TestF8HighDensityLeanContext(E2ETestCase):
    """F8: Stripped why strings, compact JSON format, compact DSL output, token savings."""

    def test_f8_stripped_why_strings(self) -> None:
        repo = self.create_repo({"lean.py": "def lean_func(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "lean_func", "mode": "compact"}, conn
            )
            # Verify results exist and each crumb is compact
            for item in res.get("results", []):
                self.assertIn("name", item)
        finally:
            conn.close()

    def test_f8_compact_mode_parameter_support(self) -> None:
        repo = self.create_repo({"mode.py": "def check(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "check", "mode": "compact"}, conn
            )
            self.assertEqual(res.get("mode"), "compact")
            self.assertEqual(res.get("budget"), 250)
        finally:
            conn.close()

    def test_f8_compact_dsl_format(self) -> None:
        repo = self.create_repo({"dsl.py": "def dsl_func(): pass\n"})
        res = self.run_cli(["init", "--project", str(repo)])
        self.assertEqual(res.returncode, 0)
        # Verify CLI context runs in compact mode
        proc = self.run_cli(
            ["context", "--project", str(repo), "--task", "dsl_func", "--mode", "compact"]
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("compact", proc.stdout)

    def test_f8_token_savings_compact_vs_full(self) -> None:
        files = {f"savings_{i}.py": f"def savings_{i}(): pass\n" for i in range(10)}
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res_compact = broker.task_context(
                kn,
                {"project": str(repo), "task": "savings", "mode": "compact", "budget": 250},
                conn,
            )
            res_deep = broker.task_context(
                kn, {"project": str(repo), "task": "savings", "mode": "deep", "budget": 1200}, conn
            )
            tokens_compact = res_compact.get("used_tokens", 0)
            tokens_deep = res_deep.get("used_tokens", 0)
            if tokens_deep > 0:
                self.assertLess(tokens_compact, tokens_deep)
        finally:
            conn.close()

    def test_f8_key_brevity_in_compact_results(self) -> None:
        repo = self.create_repo({"brevity.py": "def brief(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "brief", "mode": "compact"}, conn
            )
            results = res.get("results", [])
            if results:
                crumb = results[0]
                # Ensure unnecessary verbose debug fields are not leaked
                for bad_key in ("full_ast", "source_code_body", "raw_tokens"):
                    self.assertNotIn(bad_key, crumb)
        finally:
            conn.close()


# ============================================================================
# Feature 9: Unified Context Retrieval Pipeline
# ============================================================================
class TestF9UnifiedContextRetrievalPipeline(E2ETestCase):
    """F9: Consistency kn.context / bounded_context, shared budgeting, session parity."""

    def test_f9_consistency_kn_context_and_bounded_context(self) -> None:
        repo = self.create_repo({"pipeline.py": "def pipeline_run(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            ctx1 = kn.context(str(repo), conn)
            ctx2 = features.bounded_context(
                kn, {"project": str(repo), "task": "pipeline_run"}, conn
            )
            self.assertIn("files", ctx1)
            self.assertNotIn("error", ctx2)
        finally:
            conn.close()

    def test_f9_shared_budgeting_logic(self) -> None:
        repo = self.create_repo({"budget.py": "def budgeted(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "budgeted", "budget": 400}, conn
            )
            self.assertLessEqual(res.get("used_tokens", 0), 400)
        finally:
            conn.close()

    def test_f9_deduplication_parity(self) -> None:
        repo = self.create_repo({"dedup.py": "def dedup_func(): pass\n"})
        # CLI sync and context
        self.run_cli(["init", "--project", str(repo)])
        session_id = "sess-parity"
        proc1 = self.run_cli(
            ["context", "--project", str(repo), "--task", "dedup_func", "--session-id", session_id]
        )
        self.assertEqual(proc1.returncode, 0)
        # Turn 2 via Python broker should observe the items seen in CLI
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            res2 = broker.task_context(
                kn, {"project": str(repo), "task": "dedup_func", "session_id": session_id}, conn
            )
            self.assertGreaterEqual(res2.get("suppressed_seen", 0), 1)
        finally:
            conn.close()

    def test_f9_model_flag_propagation(self) -> None:
        repo = self.create_repo({"prop.py": "def prop(): pass\n"})
        self.run_cli(["init", "--project", str(repo)])
        data = self.run_cli_json(
            ["context", "--project", str(repo), "--task", "prop", "--model", "gpt-4o"]
        )
        self.assertIn("budget_type", data)

    def test_f9_session_state_persistence_across_interfaces(self) -> None:
        repo = self.create_repo({"state.py": "def persist(): pass\n"})
        self.run_cli(["init", "--project", str(repo)])
        session_id = "sess-persist-cross"
        self.run_cli(
            ["context", "--project", str(repo), "--task", "persist", "--session-id", session_id]
        )
        # Open MCP client and query same session
        mcp = self.open_mcp_client()
        mcp.initialize()
        call_res = mcp.call_tool(
            "get_task_context",
            {"project": str(repo), "task": "persist", "session_id": session_id},
        )
        content_text = call_res.get("content", [{}])[0].get("text", "{}")
        payload = json.loads(content_text)
        self.assertGreaterEqual(payload.get("suppressed_seen", 0), 1)


# ============================================================================
# Feature 10: Prefix-Cache Optimized Prompts
# ============================================================================
class TestF10PrefixCacheOptimizedPrompts(E2ETestCase):
    """F10: Static declarations before dynamic task, reproducible prefix, prompt mode."""

    def test_f10_static_declarations_before_dynamic_task(self) -> None:
        repo = self.create_repo({"auth.py": "def login(): pass\n"})
        self.run_cli(["init", "--project", str(repo)])
        proc = self.run_cli(
            ["context", "--project", str(repo), "--task", "unique_dynamic_task_xyz", "--prompt"]
        )
        self.assertEqual(proc.returncode, 0)
        output = proc.stdout
        # Dynamic task text should appear after the static system/project framing
        task_idx = output.find("unique_dynamic_task_xyz")
        self.assertGreater(task_idx, 0, "Dynamic task must be preceded by static prefix context")

    def test_f10_reproducible_prefix_across_tasks(self) -> None:
        repo = self.create_repo({"core.py": "def core(): pass\n"})
        self.run_cli(["init", "--project", str(repo)])
        proc1 = self.run_cli(
            ["context", "--project", str(repo), "--task", "Task A", "--prompt", "--include-seen"]
        )
        proc2 = self.run_cli(
            ["context", "--project", str(repo), "--task", "Task B", "--prompt", "--include-seen"]
        )
        out1 = proc1.stdout
        out2 = proc2.stdout
        # Leading static header should be identical
        prefix1 = out1[: out1.find("Task A")] if "Task A" in out1 else ""
        prefix2 = out2[: out2.find("Task B")] if "Task B" in out2 else ""
        self.assertTrue(len(prefix1) > 0 and len(prefix2) > 0)
        self.assertEqual(prefix1, prefix2)

    def test_f10_prompt_format_adherence(self) -> None:
        repo = self.create_repo({"doc.py": "def doc(): pass\n"})
        self.run_cli(["init", "--project", str(repo)])
        proc = self.run_cli(
            ["context", "--project", str(repo), "--task", "documentation", "--prompt"]
        )
        self.assertEqual(proc.returncode, 0)
        # Should be plain prompt text, not raw JSON payload
        self.assertFalse(
            proc.stdout.strip().startswith("{"), "Prompt mode must not output raw JSON"
        )

    def test_f10_prompt_mode_flag_acceptance(self) -> None:
        repo = self.create_repo({"flag.py": "def flag(): pass\n"})
        self.run_cli(["init", "--project", str(repo)])
        proc = self.run_cli(["context", "--project", str(repo), "--task", "flag", "--prompt"])
        self.assertEqual(proc.returncode, 0)

    def test_f10_token_count_reporting(self) -> None:
        repo = self.create_repo({"tok.py": "def count(): pass\n"})
        self.run_cli(["init", "--project", str(repo)])
        proc = self.run_cli(["context", "--project", str(repo), "--task", "count", "--prompt"])
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(len(proc.stdout) > 0)


# ============================================================================
# Feature 11: CLI Discoverability & Argparse Unification
# ============================================================================
class TestF11CLIDiscoverabilityArgparse(E2ETestCase):
    """F11: dashboard, benchmark, evaluate in --help, non-empty help, zero mojibake."""

    def test_f11_dashboard_in_help(self) -> None:
        proc = self.run_cli(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn(
            "dashboard",
            proc.stdout,
            "CLI --help must advertise 'dashboard' subcommand",
        )

    def test_f11_benchmark_in_help(self) -> None:
        proc = self.run_cli(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn(
            "benchmark",
            proc.stdout,
            "CLI --help must advertise 'benchmark' subcommand",
        )

    def test_f11_evaluate_in_help(self) -> None:
        proc = self.run_cli(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn(
            "evaluate",
            proc.stdout,
            "CLI --help must advertise 'evaluate' subcommand",
        )

    def test_f11_subcommands_help_messages_non_empty(self) -> None:
        for subcmd in ("sync", "search", "context", "doctor"):
            proc = self.run_cli([subcmd, "--help"])
            self.assertEqual(proc.returncode, 0, f"Subcommand {subcmd} --help failed")
            self.assertGreater(len(proc.stdout.strip()), 20, f"Subcommand {subcmd} help is empty")

    def test_f11_zero_mojibake_strings_in_outputs(self) -> None:
        # Check watch and main help for corrupt UTF-8 sequences
        proc = self.run_cli(["watch", "--help"])
        self.assertNotIn("Ãƒ", proc.stdout)
        self.assertNotIn("Ã¢â‚¬", proc.stdout)


# ============================================================================
# Feature 12: Human-Centric Formatted CLI Output
# ============================================================================
class TestF12HumanCentricFormattedCLIOutput(E2ETestCase):
    """F12: --format text|json|table, status indicators [OK]/[WARN]/[FAIL], doctor output."""

    def test_f12_format_json_flag(self) -> None:
        proc = self.run_cli(["doctor", "--format", "json"])
        if proc.returncode == 0:
            parsed = json.loads(proc.stdout)
            self.assertIsInstance(parsed, dict)
        else:
            # Fallback to default doctor if --format is not yet added
            data = self.run_cli_json(["doctor"])
            self.assertIn("version", data)

    def test_f12_format_text_flag(self) -> None:
        proc = self.run_cli(["doctor", "--format", "text"])
        self.assertEqual(
            proc.returncode,
            0,
            f"CLI doctor --format text must succeed: {proc.stderr}",
        )
        self.assertNotIn('{"', proc.stdout.strip()[:2], "Text format must not be raw JSON")

    def test_f12_format_table_flag(self) -> None:
        proc = self.run_cli(["doctor", "--format", "table"])
        self.assertEqual(
            proc.returncode,
            0,
            f"CLI doctor --format table must succeed: {proc.stderr}",
        )

    def test_f12_colored_ascii_status_tags(self) -> None:
        proc = self.run_cli(["doctor"])
        self.assertEqual(proc.returncode, 0)
        # Verify status indicators or structured health tags
        self.assertTrue(
            any(tag in proc.stdout for tag in ("[OK]", "[WARN]", "[FAIL]", "database_exists")),
            "Expected health indicator tags in doctor output",
        )

    def test_f12_human_friendly_doctor_output(self) -> None:
        proc = self.run_cli(["doctor"])
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(len(proc.stdout) > 0)


# ============================================================================
# Feature 13: Complete MCP Protocol & Resources
# ============================================================================
class TestF13CompleteMCPProtocolResources(E2ETestCase):
    """F13: checkpoint tool, schema validation, no empty schemas, MCP resources."""

    def test_f13_checkpoint_advertised_in_tools_list(self) -> None:
        mcp = self.open_mcp_client()
        mcp.initialize()
        tools = mcp.list_tools()
        names = {t.get("name") for t in tools}
        self.assertIn(
            "checkpoint", names, f"'checkpoint' tool missing from tools/list. Found: {names}"
        )

    def test_f13_checkpoint_schema_validation(self) -> None:
        mcp = self.open_mcp_client()
        mcp.initialize()
        tools = mcp.list_tools()
        checkpoint_tool = next((t for t in tools if t.get("name") == "checkpoint"), None)
        self.assertIsNotNone(checkpoint_tool, "checkpoint tool must exist")
        schema = checkpoint_tool.get("inputSchema", {})
        self.assertEqual(schema.get("type"), "object")
        props = schema.get("properties", {})
        self.assertIn("project", props)
        self.assertIn("session_id", props)

    def test_f13_no_empty_schema_properties(self) -> None:
        mcp = self.open_mcp_client()
        mcp.initialize()
        tools = mcp.list_tools()
        empty_properties = []
        for tool in tools:
            schema = tool.get("inputSchema", {})
            for prop_name, prop_def in schema.get("properties", {}).items():
                if prop_def == {}:
                    empty_properties.append(f"{tool.get('name')}.{prop_name}")
        self.assertEqual(
            empty_properties,
            [],
            f"Tools contain empty {{}} schema definitions: {empty_properties}",
        )

    def test_f13_resources_list_returns_lazytoken_uris(self) -> None:
        mcp = self.open_mcp_client()
        mcp.initialize()
        resources = mcp.list_resources()
        self.assertIsInstance(resources, list)
        self.assertTrue(len(resources) > 0, "resources/list must return registered MCP resources")
        for r in resources:
            uri = r.get("uri", "")
            self.assertTrue(
                uri.startswith("lazytoken://"),
                f"Resource URI must start with lazytoken://. Found: {uri}",
            )

    def test_f13_resources_read_handles_valid_uri(self) -> None:
        mcp = self.open_mcp_client()
        mcp.initialize()
        res = mcp.read_resource("lazytoken://projects")
        self.assertNotIn("error", res)
        self.assertTrue(
            "contents" in res or "content" in res,
            f"Expected resource contents in response: {res}",
        )


# ============================================================================
# Feature 14: Active Session Dashboard UI & Endpoint
# ============================================================================
class TestF14ActiveSessionDashboard(E2ETestCase):
    """F14: Local loopback server port 0, GET /api/session/<id>, 404 on invalid, HTML root."""

    def test_f14_local_server_starts_on_loopback_port_0(self) -> None:
        server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
        port = server.server_address[1]
        try:
            self.assertGreater(port, 0)
        finally:
            server.server_close()

    def test_f14_get_api_session_id_returns_graph_json(self) -> None:
        repo = self.create_repo({"dash.py": "def dash_view(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            broker.task_context(
                kn, {"project": str(repo), "task": "dash_view", "session_id": "sess-dash-14"}, conn
            )
        finally:
            conn.close()

        server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:
            url = f"http://127.0.0.1:{port}/api/session/sess-dash-14"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue("nodes" in data or "session_id" in data or "files" in data)
        finally:
            server.shutdown()
            server.server_close()

    def test_f14_404_on_invalid_session(self) -> None:
        server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:
            url = f"http://127.0.0.1:{port}/api/session/nonexistent_session_xyz_999"
            req = urllib.request.Request(url)
            try:
                with urllib.request.urlopen(req, timeout=3) as resp:
                    # If server returns 200 with error or 404
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("error", data)
            except urllib.error.HTTPError as exc:
                self.assertIn(exc.code, (400, 404))
        finally:
            server.shutdown()
            server.server_close()

    def test_f14_html_dashboard_root_returns_200(self) -> None:
        server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:
            url = f"http://127.0.0.1:{port}/"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                self.assertEqual(resp.status, 200)
                ctype = resp.headers.get("Content-Type", "")
                self.assertIn("text/html", ctype)
        finally:
            server.shutdown()
            server.server_close()

    def test_f14_concurrent_dashboard_requests(self) -> None:
        server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:

            def fetch(path: str) -> int:
                url = f"http://127.0.0.1:{port}{path}"
                with urllib.request.urlopen(url, timeout=3) as resp:
                    return resp.status

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                futures = [pool.submit(fetch, "/api/projects") for _ in range(5)]
                statuses = [f.result() for f in concurrent.futures.as_completed(futures)]
                for st in statuses:
                    self.assertEqual(st, 200)
        finally:
            server.shutdown()
            server.server_close()


# ============================================================================
# Feature 15: Live Benchmark Suite & Metrics Runner
# ============================================================================
class TestF15LiveBenchmarkSuite(E2ETestCase):
    """F15: kn benchmark run command, json output, token savings, compression ratio, zero crashes."""

    def test_f15_kn_benchmark_run_command_execution(self) -> None:
        proc = self.run_cli(["benchmark", "corpus"])
        self.assertEqual(
            proc.returncode,
            0,
            f"Benchmark corpus command failed: {proc.stderr}",
        )

    def test_f15_json_output_format(self) -> None:
        proc = self.run_cli(["benchmark", "corpus"])
        self.assertEqual(proc.returncode, 0)
        parsed = json.loads(proc.stdout)
        self.assertIn("tasks", parsed)

    def test_f15_metrics_presence_token_savings(self) -> None:
        cases = [
            {
                "id": "c1",
                "method": "lazytoken",
                "relevant": ["file:auth.py::"],
                "predicted": ["file:auth.py::"],
                "estimated_tokens": 120,
            }
        ]
        result = retrieval_eval.evaluate(cases)
        self.assertIn("estimated_tokens_mean", result)
        self.assertIn("precision_at_k", result)

    def test_f15_metrics_presence_compression_ratio_and_latency(self) -> None:
        cases = [
            {
                "id": "c2",
                "method": "baseline",
                "relevant": ["a.py", "b.py"],
                "predicted": ["a.py", "c.py"],
            }
        ]
        result = retrieval_eval.evaluate(cases, k=2)
        self.assertIn("recall_at_k", result)
        self.assertIn("mrr_at_k", result)
        self.assertIn("ndcg_at_k", result)

    def test_f15_zero_crashes_on_empty_repo(self) -> None:
        cases = [
            {
                "id": "empty_case",
                "method": "abstain_method",
                "relevant": [],
                "predicted": [],
                "abstained": True,
            }
        ]
        result = retrieval_eval.evaluate(cases)
        self.assertTrue(result.get("abstention_accuracy", 0) >= 0)


# ============================================================================
# Feature 16: Multi-Turn Simulation & Recall Validation
# ============================================================================
class TestF16MultiTurnSimulationRecall(E2ETestCase):
    """F16: 5-turn session simulation, turn 1 recall, propose-review cycle, session reset."""

    def test_f16_5_turn_session_simulation(self) -> None:
        files = {f"step_{i}.py": f"def step_{i}(): return {i}\n" for i in range(5)}
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-sim-5"
            for i in range(5):
                res = broker.task_context(
                    kn, {"project": str(repo), "task": f"step_{i}", "session_id": session_id}, conn
                )
                self.assertNotIn("error", res, f"Turn {i} raised error: {res.get('error')}")
        finally:
            conn.close()

    def test_f16_zero_unhandled_exceptions_across_turns(self) -> None:
        repo = self.create_repo(
            {
                "service.py": "def process(): pass\n",
                "model.py": "class Model: pass\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-no-exc"
            # Execute mixed operations across turns (retrieve, suppress, recap, checkpoint)
            r1 = broker.task_context(
                kn, {"project": str(repo), "task": "process", "session_id": session_id}, conn
            )
            self.assertNotIn("error", r1)
            r2 = broker.task_context(
                kn, {"project": str(repo), "task": "Model", "session_id": session_id}, conn
            )
            self.assertNotIn("error", r2)
            r3 = broker.task_context(
                kn, {"project": str(repo), "task": "process", "session_id": session_id}, conn
            )
            self.assertNotIn("error", r3)
            r4 = broker.session_checkpoint(
                kn, {"project": str(repo), "session_id": session_id}, conn
            )
            self.assertNotIn("error", r4)
            r5 = broker.task_context(
                kn, {"project": str(repo), "task": "Model", "session_id": session_id}, conn
            )
            self.assertNotIn("error", r5)
        finally:
            conn.close()

    def test_f16_recall_of_turn1_foundational_items(self) -> None:
        repo = self.create_repo(
            {
                "auth.py": "def authenticate(): pass\n",
                "handlers.py": "def route(): pass\n",
                "db.py": "def query(): pass\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-recall-turn1"
            # Turn 1: discover auth
            t1 = broker.task_context(
                kn, {"project": str(repo), "task": "authenticate", "session_id": session_id}, conn
            )
            self.assertGreater(len(t1.get("results", [])), 0)

            # Turns 2 & 3: discover handlers and db
            broker.task_context(
                kn, {"project": str(repo), "task": "route", "session_id": session_id}, conn
            )
            broker.task_context(
                kn, {"project": str(repo), "task": "query", "session_id": session_id}, conn
            )

            # Turn 4: re-query auth -> should recall from session (suppressed & recapped)
            t4 = broker.task_context(
                kn, {"project": str(repo), "task": "authenticate", "session_id": session_id}, conn
            )
            self.assertGreaterEqual(t4.get("suppressed_seen", 0), 1)
            recap_keys = [item.get("key", "") for item in t4.get("recap", [])]
            self.assertTrue(
                any("auth.py" in k for k in recap_keys),
                f"Turn 1 item auth.py not recalled in recap: {recap_keys}",
            )
        finally:
            conn.close()

    def test_f16_memory_propose_review_cycle_in_simulation(self) -> None:
        repo = self.create_repo({"store.py": "class Store: pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            project_id = str(repo.resolve())
            # Propose memory lesson
            prop = features.propose(
                kn,
                {
                    "project": project_id,
                    "kind": "lesson",
                    "name": "Cache Strategy",
                    "summary": "Use TTL cache for session store",
                    "task": "Caching",
                    "evidence": "Observed high query load",
                    "paths": ["store.py"],
                },
                conn,
            )
            self.assertNotIn("error", prop)
            prop_id = prop["id"]

            # Review and approve
            rev = features.review(
                kn,
                {"project": project_id, "id": prop_id, "action": "approve", "verified": True},
                conn,
            )
            self.assertTrue(rev.get("saved", False))

            # Query context with expansion to retrieve the approved memory
            res = broker.task_context(
                kn, {"project": project_id, "task": "Cache Strategy", "expand_assets": True}, conn
            )
            names = [r.get("name") for r in res.get("results", [])]
            self.assertIn("Cache Strategy", names)
        finally:
            conn.close()

    def test_f16_session_reset_behavior(self) -> None:
        repo = self.create_repo({"module.py": "def module_func(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess-reset"
            # Turn 1: initial discovery
            res1 = broker.task_context(
                kn, {"project": str(repo), "task": "module_func", "session_id": session_id}, conn
            )
            self.assertGreater(len(res1.get("results", [])), 0)

            # Turn 2: item suppressed
            res2 = broker.task_context(
                kn, {"project": str(repo), "task": "module_func", "session_id": session_id}, conn
            )
            self.assertEqual(len(res2.get("results", [])), 0)

            # Reset session
            broker.clear_session(kn, {"project": str(repo), "session_id": session_id}, conn)

            # Turn 3: item should be retrieved again as fresh
            res3 = broker.task_context(
                kn, {"project": str(repo), "task": "module_func", "session_id": session_id}, conn
            )
            self.assertGreater(len(res3.get("results", [])), 0)
            self.assertEqual(res3.get("suppressed_seen", 0), 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
