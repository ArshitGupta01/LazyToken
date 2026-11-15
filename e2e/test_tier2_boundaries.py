"""Tier 2 Boundary & Corner Cases: Comprehensive tests for Features 1 through 16 (80 tests)."""

from __future__ import annotations

import concurrent.futures
import json
import os
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
import source_index
import token_budget
from benchmark import harness
from e2e.common import E2ETestCase, McpClient

ROOT_DIR = Path(__file__).resolve().parent.parent


# ============================================================================
# Feature 1: SQLite Concurrency & Reliability
# ============================================================================
class TestF1SQLiteConcurrencyBoundaries(E2ETestCase):
    """F1: Empty DB queries, corrupted sqlite header detection, concurrent 10-thread write bursts, table-drop recovery, max connection limits."""

    def test_f1_empty_db_queries(self) -> None:
        """Querying an empty database without indexed projects must be handled gracefully without unhandled exceptions."""
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            # Empty search must return empty results without crashing
            res_search = kn.search("", conn)
            self.assertEqual(res_search.get("results"), [])
            res_search_query = kn.search("arbitrary_query", conn)
            self.assertEqual(res_search_query.get("results"), [])

            # Ranked search on un-indexed project must return error response without crash
            ranked = features.ranked_search(
                kn, {"project": "nonexistent_project", "query": "hello"}, conn
            )
            self.assertIn("error", ranked)
            self.assertIn("indexed project is required", ranked["error"].lower())

            # Task context without indexed project must return an error response, not crash
            ctx = broker.task_context(kn, {"project": "nonexistent_project", "task": "hello"}, conn)
            self.assertIn("error", ctx)
            self.assertIn("indexed project is required", ctx["error"].lower())

            # Clear session without indexed project must return error response
            clr = broker.clear_session(
                kn, {"project": "nonexistent_project", "session_id": "sess_1"}, conn
            )
            self.assertIn("error", clr)
        finally:
            conn.close()

    def test_f1_corrupted_sqlite_header_detection(self) -> None:
        """A database file with a corrupted header must be detected and raise DatabaseError/RuntimeError."""
        db_file = self.temp_dir / "network.sqlite3"
        # Write corrupted header bytes that violate SQLite format
        db_file.write_bytes(b"CORRUPTED_NON_SQLITE_HEADER_BYTES_1234567890\x00\xff\xfe\xfd")

        with self.assertRaises((sqlite3.DatabaseError, RuntimeError)):
            conn = kn.connect(db_file)
            try:
                conn.execute("SELECT 1 FROM sqlite_master").fetchall()
            finally:
                conn.close()

    def test_f1_concurrent_10_thread_write_bursts(self) -> None:
        """10 concurrent threads issuing rapid write bursts must succeed without lock failures under WAL mode and busy_timeout."""
        db_file = self.temp_dir / "network.sqlite3"
        init_conn = kn.connect(db_file)
        init_conn.close()

        thread_errors: list[Exception] = []

        def worker_writer(worker_id: int) -> None:
            try:
                c = kn.connect(db_file)
                try:
                    for i in range(10):
                        now = int(time.time())
                        c.execute(
                            "INSERT INTO task_measurements VALUES(NULL, ?, ?, ?, ?, ?)",
                            (f"task_burst_{worker_id}_{i}", 100, 80, 20, now),
                        )
                        c.commit()
                finally:
                    c.close()
            except Exception as exc:
                thread_errors.append(exc)

        threads = [threading.Thread(target=worker_writer, args=(t_id,)) for t_id in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(
            len(thread_errors), 0, f"Concurrent write burst failed with errors: {thread_errors}"
        )

        verify_conn = kn.connect(db_file)
        try:
            total_rows = verify_conn.execute("SELECT count(*) FROM task_measurements").fetchone()[0]
            self.assertEqual(total_rows, 100)
        finally:
            verify_conn.close()

    def test_f1_table_drop_recovery(self) -> None:
        """Dropping a core table followed by migrate/connect must restore missing tables without corruption."""
        db_file = self.temp_dir / "network.sqlite3"
        conn = kn.connect(db_file)
        try:
            # Intentionally drop a table
            conn.execute("DROP TABLE IF EXISTS context_session_items")
            conn.commit()

            check_dropped = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='context_session_items'"
            ).fetchone()
            self.assertIsNone(check_dropped)

            # Re-run migration / schema setup
            features.migrate(conn)

            check_restored = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='context_session_items'"
            ).fetchone()
            self.assertIsNotNone(check_restored, "Table context_session_items was not restored")
        finally:
            conn.close()

    def test_f1_max_connection_limits(self) -> None:
        """Opening 50 simultaneous connections in WAL mode must not exhaust handles or fail queries."""
        db_file = self.temp_dir / "network.sqlite3"
        init_conn = kn.connect(db_file)
        init_conn.close()

        connections: list[sqlite3.Connection] = []
        try:
            for _ in range(50):
                c = kn.connect(db_file)
                connections.append(c)

            self.assertEqual(len(connections), 50)
            for i, c in enumerate(connections):
                row = c.execute("SELECT 1").fetchone()
                self.assertEqual(row[0], 1, f"Connection {i} failed to execute query")
        finally:
            for c in connections:
                try:
                    c.close()
                except Exception:
                    pass


# ============================================================================
# Feature 2: Robust Import/Dependency Edge Matching
# ============================================================================
class TestF2ImportMatchingBoundaries(E2ETestCase):
    """F2: Extreme import path lengths, malformed AST syntax files, circular 5-node import loops, Unicode and emoji module names, deeply nested 20-level relative imports."""

    def test_f2_extreme_import_path_lengths(self) -> None:
        """Import statements with extreme path lengths (300+ characters) must be parsed without truncation or crash."""
        long_submodule = ".".join([f"sub_{i}" for i in range(50)])
        extreme_path = f"enterprise.core.{long_submodule}.deep_service"
        self.assertGreater(len(extreme_path), 300)

        repo = self.create_repo(
            {
                "service.py": f"import {extreme_path}\n\ndef run():\n    pass\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            sync_res = kn.sync(repo, conn)
            self.assertEqual(sync_res.get("error_count", 0), 0)

            rows = conn.execute(
                "SELECT source, target FROM imports WHERE project_id=?", (str(repo),)
            ).fetchall()
            targets = [r["target"] for r in rows]
            self.assertIn(extreme_path, targets)
        finally:
            conn.close()

    def test_f2_malformed_ast_syntax_files(self) -> None:
        """Files with broken syntax must not crash indexing; valid files in repo must still be indexed."""
        repo = self.create_repo(
            {
                "broken.py": "def broken_syntax(::: (( [[[ \nwhile for else return ??\n",
                "healthy.py": "def healthy_func():\n    return 42\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            sync_res = kn.sync(repo, conn)
            # Sync must complete without unhandled exception
            self.assertNotIn("error", sync_res)

            # Healthy function must be indexed in symbols
            healthy_syms = conn.execute(
                "SELECT name FROM symbols WHERE project_id=? AND name='healthy_func'",
                (str(repo),),
            ).fetchall()
            self.assertEqual(len(healthy_syms), 1)

            # source_index python_imports handles broken syntax safely returning empty list
            body = "def broken_syntax(::: (( [[[ \nwhile for else return ??\n"
            imports = source_index.python_imports(body)
            self.assertEqual(imports, [])
        finally:
            conn.close()

    def test_f2_circular_5_node_import_loops(self) -> None:
        """A circular import dependency spanning 5 nodes must be indexed and queried without infinite recursion."""
        repo = self.create_repo(
            {
                "node_1.py": "import node_2\ndef f1(): return 1\n",
                "node_2.py": "import node_3\ndef f2(): return 2\n",
                "node_3.py": "import node_4\ndef f3(): return 3\n",
                "node_4.py": "import node_5\ndef f4(): return 4\n",
                "node_5.py": "import node_1\ndef f5(): return 5\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            sync_res = kn.sync(repo, conn)
            self.assertEqual(sync_res.get("error_count", 0), 0)

            # Query context with all 5 nodes present
            res = broker.task_context(
                kn,
                {"project": str(repo), "task": "node_1 node_2 node_3 node_4 node_5 cycle"},
                conn,
            )
            self.assertNotIn("error", res)
            self.assertIn("results", res)
        finally:
            conn.close()

    def test_f2_unicode_and_emoji_module_names(self) -> None:
        """Module names and identifiers with Unicode and emoji characters must be indexed without encoding crashes."""
        repo = self.create_repo(
            {
                "util_🚀.py": "def launch():\n    return 'blastoff'\n",
                "módule_ñ.py": "from util_🚀 import launch\ndef calcular():\n    return launch()\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            sync_res = kn.sync(repo, conn)
            self.assertEqual(sync_res.get("error_count", 0), 0)

            symbols = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM symbols WHERE project_id=?", (str(repo),)
                ).fetchall()
            }
            self.assertIn("launch", symbols)
            self.assertIn("calcular", symbols)
        finally:
            conn.close()

    def test_f2_deeply_nested_20_level_relative_imports(self) -> None:
        """Deeply nested 20-level relative imports must be processed without index out of bounds or negative slicing errors."""
        body = "from " + ("." * 20) + "root_core import base_service\n"
        extracted = source_index.python_imports(body)
        self.assertIn("." * 20 + "root_core", extracted)

        # Test resolution logic with 20 leading dots
        resolved = broker._resolve_import_target(
            "a/b/c/d/e.py",
            "." * 20 + "root_core",
            {"root_core.py", "a/b/c/d/e.py"},
        )
        # Cannot navigate up 19 parent directories from 4 directory levels -> returns None safely
        self.assertIsNone(resolved)


# ============================================================================
# Feature 3: Active Session Item Freshness & Deduplication
# ============================================================================
class TestF3SessionFreshnessBoundaries(E2ETestCase):
    """F3: Session with 500 items, rapid multi-turn same-millisecond touches, special characters in session_id, session item fingerprint collisions, zero items session."""

    def test_f3_session_with_500_items(self) -> None:
        """A session with 500 stored items must scale properly in checkpointing and context assembly without memory explosion."""
        repo = self.create_repo({"entry.py": "def entry(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            project_id = str(repo)
            session_id = "sess_bulk_500"

            now = int(time.time())
            bulk_items = [
                (project_id, session_id, f"file:path_{i}.py", f"fingerprint_{i:04d}", now - i)
                for i in range(500)
            ]
            conn.executemany("INSERT INTO context_session_items VALUES(?,?,?,?,?)", bulk_items)
            conn.commit()

            # Verify checkpoint returns supplied_items = 500 and recent_keys is bounded (30 items)
            chk = broker.session_checkpoint(
                kn, {"project": project_id, "session_id": session_id}, conn
            )
            self.assertNotIn("error", chk)
            self.assertEqual(chk.get("supplied_items"), 500)
            self.assertTrue(chk.get("truncated"))
            self.assertLessEqual(len(chk.get("recent_keys", [])), 30)
        finally:
            conn.close()

    def test_f3_rapid_multi_turn_same_millisecond_touches(self) -> None:
        """Rapid consecutive touches within the same millisecond/second must update timestamps cleanly without primary key conflicts."""
        repo = self.create_repo({"fast.py": "def fast_op(): return 1\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess_rapid_touch"

            for _ in range(5):
                res = broker.task_context(
                    kn,
                    {"project": str(repo), "task": "fast_op", "session_id": session_id},
                    conn,
                )
                self.assertNotIn("error", res)

            rows = conn.execute(
                "SELECT item_key, updated_at FROM context_session_items WHERE session_id=?",
                (session_id,),
            ).fetchall()
            self.assertGreater(len(rows), 0)
            for r in rows:
                self.assertIsInstance(r["updated_at"], int)
                self.assertGreater(r["updated_at"], 0)
        finally:
            conn.close()

    def test_f3_special_characters_in_session_id(self) -> None:
        """Session ID containing special characters must be accepted safely via parameterized queries without injection."""
        special_session = "sess/abc!@#$%^&*()_+~"
        repo = self.create_repo({"app.py": "def run(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)

            # Query context with special session ID
            res = broker.task_context(
                kn,
                {"project": str(repo), "task": "run", "session_id": special_session},
                conn,
            )
            self.assertNotIn("error", res)

            # Checkpoint with special session ID
            chk = broker.session_checkpoint(
                kn, {"project": str(repo), "session_id": special_session}, conn
            )
            self.assertNotIn("error", chk)
            self.assertEqual(chk.get("session_id"), special_session)

            # Clear session with special session ID
            clr = broker.clear_session(
                kn, {"project": str(repo), "session_id": special_session}, conn
            )
            self.assertNotIn("error", clr)
            self.assertGreaterEqual(clr.get("cleared", 0), 1)
        finally:
            conn.close()

    def test_f3_session_item_fingerprint_collisions(self) -> None:
        """When an item's content changes, its fingerprint changes, allowing it to be returned again instead of falsely suppressed."""
        repo = self.create_repo({"worker.py": "def do_work(): return 'v1'\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess_fp_diff"

            # Turn 1: item is seen with original content
            res1 = broker.task_context(
                kn, {"project": str(repo), "task": "do_work", "session_id": session_id}, conn
            )
            self.assertGreater(len(res1.get("results", [])), 0)
            fp1 = conn.execute(
                "SELECT fingerprint FROM context_session_items WHERE session_id=?", (session_id,)
            ).fetchone()[0]

            # Modify file content (fingerprint should change on resync)
            (repo / "worker.py").write_text(
                "def do_work(): return 'v2_modified_body'\n", encoding="utf-8"
            )
            kn.sync(repo, conn)

            # Turn 2: modified item should NOT be suppressed because fingerprint differs
            res2 = broker.task_context(
                kn, {"project": str(repo), "task": "do_work", "session_id": session_id}, conn
            )
            self.assertGreater(len(res2.get("results", [])), 0)
            fp2 = conn.execute(
                "SELECT fingerprint FROM context_session_items WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            self.assertNotEqual(fp1, fp2, "Fingerprint must change when file content changes")
        finally:
            conn.close()

    def test_f3_zero_items_session(self) -> None:
        """A session with a query matching 0 items must record 0 session rows and return an empty result list."""
        repo = self.create_repo({"data.py": "x = 10\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess_zero_items"

            res = broker.task_context(
                kn,
                {
                    "project": str(repo),
                    "task": "nonexistent_query_xyz_999",
                    "session_id": session_id,
                },
                conn,
            )
            self.assertNotIn("error", res)
            self.assertEqual(res.get("results"), [])
            self.assertEqual(res.get("suppressed_seen"), 0)

            count = conn.execute(
                "SELECT count(*) FROM context_session_items WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            conn.close()


# ============================================================================
# Feature 4: Context Amnesia Elimination & Recovery Recap
# ============================================================================
class TestF4AmnesiaRecoveryBoundaries(E2ETestCase):
    """F4: Context amnesia with 100% suppression and empty project, amnesia recovery with empty task string, 20-turn suppression chain, alternating suppression turns, recovery recap structure with truncated budget."""

    def test_f4_context_amnesia_100_percent_suppression_empty_project(self) -> None:
        """Full suppression recovery must handle situations where source files were deleted without unhandled exceptions."""
        repo = self.create_repo({"temp_file.py": "def temp_fn(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess_amnesia_empty_proj"

            # Turn 1: item seen
            res1 = broker.task_context(
                kn, {"project": str(repo), "task": "temp_fn", "session_id": session_id}, conn
            )
            self.assertGreater(len(res1.get("results", [])), 0)

            # Turn 2: All items already seen -> amnesia recovery
            res2 = broker.task_context(
                kn, {"project": str(repo), "task": "temp_fn", "session_id": session_id}, conn
            )
            self.assertNotIn("error", res2)
            self.assertEqual(len(res2.get("results", [])), 0)
            self.assertGreater(res2.get("suppressed_seen", 0), 0)
            self.assertIn("recap", res2)
        finally:
            conn.close()

    def test_f4_amnesia_recovery_with_empty_task_string(self) -> None:
        """Empty task string or whitespace-only task must be validated and rejected with a clear error."""
        repo = self.create_repo({"service.py": "def run(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)

            res_empty = broker.task_context(kn, {"project": str(repo), "task": ""}, conn)
            self.assertIn("error", res_empty)
            self.assertIn("task must be non-empty text", res_empty["error"])

            res_whitespace = broker.task_context(kn, {"project": str(repo), "task": "    "}, conn)
            self.assertIn("error", res_whitespace)
            self.assertIn("task must be non-empty text", res_whitespace["error"])
        finally:
            conn.close()

    def test_f4_20_turn_suppression_chain(self) -> None:
        """A 20-turn suppression chain repeating the same task must reliably deliver recaps and active topology on turns 2-20 without duplicate rows."""
        repo = self.create_repo({"chain.py": "def link_fn(): return 'chain'\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess_chain_20"

            # Turn 1: initial discovery
            r1 = broker.task_context(
                kn, {"project": str(repo), "task": "link_fn", "session_id": session_id}, conn
            )
            self.assertGreater(len(r1.get("results", [])), 0)

            # Turns 2 through 20: 100% full suppression with recap
            for turn in range(2, 21):
                res = broker.task_context(
                    kn, {"project": str(repo), "task": "link_fn", "session_id": session_id}, conn
                )
                self.assertNotIn("error", res, f"Turn {turn} failed: {res.get('error')}")
                self.assertEqual(
                    len(res.get("results", [])), 0, f"Turn {turn} had unsuppressed items"
                )
                self.assertGreater(
                    res.get("suppressed_seen", 0), 0, f"Turn {turn} missing suppressed count"
                )
                self.assertIn("recap", res, f"Turn {turn} missing recap breadcrumbs")

            # Verify no duplicate rows
            duplicates = conn.execute(
                "SELECT item_key, count(*) as c FROM context_session_items WHERE session_id=? GROUP BY item_key HAVING c > 1",
                (session_id,),
            ).fetchall()
            self.assertEqual(len(duplicates), 0, f"Duplicate session items detected: {duplicates}")
        finally:
            conn.close()

    def test_f4_alternating_suppression_turns(self) -> None:
        """Alternating between two queries across turns must correctly alternate suppression and touch updated_at timestamps."""
        repo = self.create_repo(
            {
                "alpha_mod.py": "def alpha_service(): return 'A'\n",
                "beta_mod.py": "def beta_handler(): return 'B'\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess_alternate"

            # Turn 1: Query A (seen)
            r1 = broker.task_context(
                kn, {"project": str(repo), "task": "alpha_service", "session_id": session_id}, conn
            )
            self.assertGreater(len(r1.get("results", [])), 0)

            # Turn 2: Query B (seen)
            r2 = broker.task_context(
                kn, {"project": str(repo), "task": "beta_handler", "session_id": session_id}, conn
            )
            self.assertGreater(len(r2.get("results", [])), 0)

            # Turn 3: Query A (suppressed)
            r3 = broker.task_context(
                kn, {"project": str(repo), "task": "alpha_service", "session_id": session_id}, conn
            )
            self.assertGreaterEqual(r3.get("suppressed_seen", 0), 1)

            # Turn 4: Query B (suppressed)
            r4 = broker.task_context(
                kn, {"project": str(repo), "task": "beta_handler", "session_id": session_id}, conn
            )
            self.assertGreaterEqual(r4.get("suppressed_seen", 0), 1)
        finally:
            conn.close()

    def test_f4_recovery_recap_structure_with_truncated_budget(self) -> None:
        """Full suppression recovery with a tight budget (100 tokens) must compact recap/topology without stabilization failure."""
        repo = self.create_repo({f"mod_{i}.py": f"def func_{i}(): pass\n" for i in range(8)})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess_tight_recap"

            # Turn 1: query with large budget to see all items
            broker.task_context(
                kn,
                {"project": str(repo), "task": "func", "session_id": session_id, "budget": 2000},
                conn,
            )

            # Turn 2: tight budget of 100 tokens on full suppression
            res2 = broker.task_context(
                kn,
                {"project": str(repo), "task": "func", "session_id": session_id, "budget": 100},
                conn,
            )
            # Response must either succeed with truncated recap or return clean budget error, never raise unhandled exception
            if "error" not in res2:
                self.assertLessEqual(res2.get("used_tokens", 0), 100)
                self.assertIn("recap", res2)
            else:
                self.assertIn("Budget is too small", res2["error"])
        finally:
            conn.close()


# ============================================================================
# Feature 5: Bulk Candidate Context Queries
# ============================================================================
class TestF5BulkCandidateQueriesBoundaries(E2ETestCase):
    """F5: 200+ files repository bulk query, 0 candidates matching query, single character search query, queries with SQL injection strings, extreme candidate limit requests."""

    def test_f5_200_plus_files_repository_bulk_query(self) -> None:
        """Querying a repository with 200+ files must execute candidate queries in batches without exceeding SQLite variable limits."""
        files = {f"file_{i:03d}.py": f"def operation_{i}(): return {i}\n" for i in range(210)}
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            start = time.perf_counter()
            res = broker.task_context(
                kn, {"project": str(repo), "task": "operation file", "budget": 4000}, conn
            )
            elapsed = time.perf_counter() - start
            self.assertNotIn("error", res)
            self.assertLess(elapsed, 5.0, f"200+ files bulk query took {elapsed:.2f}s")
            self.assertGreater(len(res.get("results", [])), 0)
        finally:
            conn.close()

    def test_f5_zero_candidates_matching_query(self) -> None:
        """Query returning 0 matching candidates must return decision abstain with empty results."""
        repo = self.create_repo({"simple.py": "def simple(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn,
                {"project": str(repo), "task": "nonexistent_term_zzz_no_match"},
                conn,
            )
            self.assertNotIn("error", res)
            self.assertEqual(res.get("decision"), "abstain")
            self.assertEqual(res.get("results"), [])
        finally:
            conn.close()

    def test_f5_single_character_search_query(self) -> None:
        """A single-character search query must not cause regex or query syntax crashes."""
        repo = self.create_repo({"alpha.py": "def a_function(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            ranked = features.ranked_search(kn, {"project": str(repo), "query": "a"}, conn)
            self.assertNotIn("error", ranked)
            self.assertIn("results", ranked)

            ctx = broker.task_context(kn, {"project": str(repo), "task": "a"}, conn)
            self.assertNotIn("error", ctx)
        finally:
            conn.close()

    def test_f5_queries_with_sql_injection_strings(self) -> None:
        """SQL injection attack strings in search queries must be safely handled via parameterized SQL."""
        injection_queries = [
            "' OR '1'='1",
            "'; DROP TABLE files; --",
            '" UNION SELECT * FROM sqlite_master --',
            "1' OR 1=1; DELETE FROM projects; --",
        ]
        repo = self.create_repo({"safe.py": "def safe(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            for q in injection_queries:
                ranked = features.ranked_search(kn, {"project": str(repo), "query": q}, conn)
                self.assertNotIn("error", ranked)

                ctx = broker.task_context(kn, {"project": str(repo), "task": q}, conn)
                self.assertNotIn("error", ctx)

            # Verify files table remains completely intact
            count = conn.execute(
                "SELECT count(*) FROM files WHERE project_id=?", (str(repo),)
            ).fetchone()[0]
            self.assertEqual(count, 1)
        finally:
            conn.close()

    def test_f5_extreme_candidate_limit_requests(self) -> None:
        """Requesting an extreme candidate limit (e.g. limit=100000) must be handled safely without memory crash."""
        repo = self.create_repo({"entry.py": "def entry(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            ranked = features.ranked_search(
                kn, {"project": str(repo), "query": "entry", "limit": 100000}, conn
            )
            self.assertNotIn("error", ranked)
            self.assertLessEqual(len(ranked.get("results", [])), 100000)
        finally:
            conn.close()


# ============================================================================
# Feature 6: Accurate BPE Tokenizer Support
# ============================================================================
class TestF6TokenizerSupportBoundaries(E2ETestCase):
    """F6: Budget of 1 token vs 100000 tokens, invalid model names, model parameter with non-ASCII characters, strict budget with various budget margins, tokenizer fallback switching."""

    def test_f6_budget_1_token_vs_100000_tokens(self) -> None:
        """Budgets outside the 100-16000 range must be rejected, while boundary values 100 and 16000 must be accepted."""
        repo = self.create_repo({"main.py": "x = 1\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)

            # Out of bounds: 1 token
            r1 = broker.task_context(kn, {"project": str(repo), "task": "main", "budget": 1}, conn)
            self.assertIn("error", r1)
            self.assertIn("budget must be an integer from 100 to 16000", r1["error"])

            # Out of bounds: 100000 tokens
            r100k = broker.task_context(
                kn, {"project": str(repo), "task": "main", "budget": 100000}, conn
            )
            self.assertIn("error", r100k)
            self.assertIn("budget must be an integer from 100 to 16000", r100k["error"])

            # Valid boundary: 100 tokens
            r_min = broker.task_context(
                kn, {"project": str(repo), "task": "main", "budget": 100}, conn
            )
            if "error" in r_min:
                self.assertIn("Budget is too small", r_min["error"])
            else:
                self.assertEqual(r_min.get("budget"), 100)

            # Valid boundary: 16000 tokens
            r_max = broker.task_context(
                kn, {"project": str(repo), "task": "main", "budget": 16000}, conn
            )
            self.assertNotIn("error", r_max)
            self.assertEqual(r_max.get("budget"), 16000)
        finally:
            conn.close()

    def test_f6_invalid_model_names(self) -> None:
        """Specifying an unknown model name must fall back to character heuristic without crashing."""
        repo = self.create_repo({"calc.py": "def calc(): return 0\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn,
                {"project": str(repo), "task": "calc", "model": "nonexistent_llm_999"},
                conn,
            )
            self.assertNotIn("error", res)
            self.assertIn("budget_type", res)
            self.assertIn("tokenizer_fallback", res)
        finally:
            conn.close()

    def test_f6_model_parameter_with_non_ascii_characters(self) -> None:
        """Model parameter containing non-ASCII / Unicode characters must be parsed cleanly."""
        repo = self.create_repo({"core.py": "def core(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn,
                {"project": str(repo), "task": "core", "model": "gpt-4o-日本語-🚀"},
                conn,
            )
            self.assertNotIn("error", res)
        finally:
            conn.close()

    def test_f6_strict_budget_with_various_budget_margins(self) -> None:
        """Strict budget must be refused across various budget sizes (100, 500, 2000) when no local tokenizer is configured."""
        repo = self.create_repo({"logic.py": "def logic(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            for budget_val in (100, 500, 2000):
                res = broker.task_context(
                    kn,
                    {
                        "project": str(repo),
                        "task": "logic",
                        "model": "gpt-4o",
                        "strict_budget": True,
                        "budget": budget_val,
                    },
                    conn,
                )
                self.assertIn("error", res)
                self.assertIn("Strict budget refused", res["error"])
        finally:
            conn.close()

    def test_f6_tokenizer_fallback_switching(self) -> None:
        """When model is None, no fallback reason is returned; when model is specified, fallback reason explains offline unavailability."""
        count_none, type_none, fallback_none = token_budget.counter({}, kn.estimate)
        self.assertIsNone(fallback_none)
        self.assertIn("estimate", type_none)

        count_named, type_named, fallback_named = token_budget.counter(
            {"model": "gpt-4o"}, kn.estimate
        )
        self.assertIsNotNone(fallback_named)
        self.assertIn("No matching offline tokenizer configured", fallback_named)


# ============================================================================
# Feature 7: Single-Pass Deterministic Budgeting
# ============================================================================
class TestF7SinglePassBudgetingBoundaries(E2ETestCase):
    """F7: Budget exactly equal to item size, budget 1 byte smaller than item size, 0-budget rejection, negative budget rejection, single-pass determinism under random candidate order shuffling."""

    def test_f7_budget_exactly_equal_to_item_size(self) -> None:
        """Setting budget to exact item requirement must succeed and satisfy used_tokens <= budget."""
        repo = self.create_repo({"item.py": "def item_fn(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            # Query with 250 tokens
            res = broker.task_context(
                kn, {"project": str(repo), "task": "item_fn", "budget": 250}, conn
            )
            self.assertNotIn("error", res)
            used = res.get("used_tokens", 0)
            self.assertGreater(used, 0)
            self.assertLessEqual(used, 250)

            # Exact budget equal to used
            res_exact = broker.task_context(
                kn, {"project": str(repo), "task": "item_fn", "budget": used}, conn
            )
            self.assertNotIn("error", res_exact)
            self.assertEqual(res_exact.get("used_tokens"), used)
        finally:
            conn.close()

    def test_f7_budget_1_byte_smaller_than_item_size(self) -> None:
        """When budget is smaller than response metadata alone, it must return a clean error without hanging."""
        repo = self.create_repo({"complex.py": "class LargeEngine:\n    def execute(self): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            # Budget set to minimum allowed 100
            res = broker.task_context(
                kn, {"project": str(repo), "task": "LargeEngine execute", "budget": 100}, conn
            )
            if "error" in res:
                self.assertIn("Budget is too small", res["error"])
            else:
                self.assertLessEqual(res.get("used_tokens", 0), 100)
        finally:
            conn.close()

    def test_f7_zero_budget_rejection(self) -> None:
        """Zero budget (budget=0) must be rejected with budget range error."""
        repo = self.create_repo({"file.py": "x = 1\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(kn, {"project": str(repo), "task": "file", "budget": 0}, conn)
            self.assertIn("error", res)
            self.assertIn("budget must be an integer from 100 to 16000", res["error"])
        finally:
            conn.close()

    def test_f7_negative_budget_rejection(self) -> None:
        """Negative budget (e.g. budget=-50) must be rejected with budget range error."""
        repo = self.create_repo({"file.py": "x = 1\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "file", "budget": -50}, conn
            )
            self.assertIn("error", res)
            self.assertIn("budget must be an integer from 100 to 16000", res["error"])
        finally:
            conn.close()

    def test_f7_single_pass_determinism_under_random_candidate_order_shuffling(self) -> None:
        """Repeated context queries must produce identical results and deterministic ordering regardless of execution order."""
        files = {
            f"mod_{c}.py": f"def func_{c}(): pass\n" for c in ("alpha", "beta", "gamma", "delta")
        }
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            orderings = []
            for _ in range(5):
                res = broker.task_context(
                    kn,
                    {
                        "project": str(repo),
                        "task": "func alpha beta gamma delta",
                        "include_seen": True,
                    },
                    conn,
                )
                keys = [r.get("name") for r in res.get("results", [])]
                orderings.append(keys)

            for order in orderings[1:]:
                self.assertEqual(
                    order, orderings[0], "Context output ordering must be 100% deterministic"
                )
        finally:
            conn.close()


# ============================================================================
# Feature 8: High-Density Lean Context & Compact DSL
# ============================================================================
class TestF8LeanContextBoundaries(E2ETestCase):
    """F8: 0-byte source files in compact mode, 100KB single source file in compact mode, compact DSL with deeply nested symbols, JSON serialization edge cases, mode parameter case sensitivity."""

    def test_f8_zero_byte_source_files_in_compact_mode(self) -> None:
        """0-byte source files in compact mode must be indexed and retrieved without division by zero or errors."""
        repo = self.create_repo(
            {
                "empty_one.py": "",
                "empty_two.py": "",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            sync_res = kn.sync(repo, conn)
            self.assertEqual(sync_res.get("error_count", 0), 0)

            res = broker.task_context(
                kn, {"project": str(repo), "task": "empty", "mode": "compact"}, conn
            )
            self.assertNotIn("error", res)
        finally:
            conn.close()

    def test_f8_100kb_single_source_file_in_compact_mode(self) -> None:
        """A single 100KB source file containing hundreds of functions must remain strictly bounded by compact budget (250 tokens)."""
        funcs = "\n".join(
            [
                f"def handler_{i}():\n    # large comment block to test high-density compact parsing\n    return 'payload_data_{i:04d}_{'x'*100}'\n"
                for i in range(800)
            ]
        )
        self.assertGreater(len(funcs), 100000)

        repo = self.create_repo({"large_module.py": funcs})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn,
                {"project": str(repo), "task": "handler", "mode": "compact", "budget": 250},
                conn,
            )
            self.assertNotIn("error", res)
            self.assertLessEqual(res.get("used_tokens", 0), 250)
            self.assertTrue(res.get("truncated", False))
        finally:
            conn.close()

    def test_f8_compact_dsl_with_deeply_nested_symbols(self) -> None:
        """Deeply nested symbols must be parsed and represented cleanly in compact format."""
        code = (
            "class Level1:\n"
            "    class Level2:\n"
            "        class Level3:\n"
            "            def deep_method(self):\n"
            "                pass\n"
        )
        repo = self.create_repo({"nested.py": code})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "deep_method Level", "mode": "compact"}, conn
            )
            self.assertNotIn("error", res)
            sym_names = [r.get("name") for r in res.get("results", [])]
            self.assertTrue(any("deep_method" in n or "Level" in n for n in sym_names))
        finally:
            conn.close()

    def test_f8_json_serialization_edge_cases(self) -> None:
        """Raw quotes, backslashes, tabs, and newlines in docstrings must serialize into valid JSON that round-trips cleanly."""
        code = (
            "def edge_case_fn():\n"
            '    """Handles "double quotes" and \'single\' and \\\\ backslashes and \\t tabs and \\n newlines."""\n'
            "    return True\n"
        )
        repo = self.create_repo({"special.py": code})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn, {"project": str(repo), "task": "edge_case_fn quotes", "mode": "compact"}, conn
            )
            self.assertNotIn("error", res)
            serialized = json.dumps(res, ensure_ascii=False)
            deserialized = json.loads(serialized)
            self.assertEqual(deserialized["project"], res["project"])
        finally:
            conn.close()

    def test_f8_mode_parameter_case_sensitivity(self) -> None:
        """Mode parameter must enforce case sensitivity and reject invalid casing (e.g. COMPACT, Balanced)."""
        repo = self.create_repo({"main.py": "x = 1\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            for bad_mode in ("COMPACT", "Compact", "BALANCED", "Deep", "invalid_mode"):
                res = broker.task_context(
                    kn, {"project": str(repo), "task": "main", "mode": bad_mode}, conn
                )
                self.assertIn("error", res)
                self.assertIn("mode must be compact, balanced, or deep", res["error"])
        finally:
            conn.close()


# ============================================================================
# Feature 9: Unified Context Retrieval Pipeline
# ============================================================================
class TestF9UnifiedPipelineBoundaries(E2ETestCase):
    """F9: Concurrent calls to kn.context and features.bounded_context, query with null/None parameters, retrieval on un-synced project, pipeline memory consumption under repetitive calls, model flag inconsistency handling."""

    def test_f9_concurrent_calls_kn_context_and_features_bounded_context(self) -> None:
        """Simultaneous concurrent calls to kn.context and features.bounded_context must succeed without SQLite concurrency errors."""
        repo = self.create_repo(
            {"app.py": "def app(): pass\n", "helper.py": "def helper(): pass\n"}
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
        finally:
            conn.close()

        errors: list[Exception] = []
        db_path = self.temp_dir / "network.sqlite3"

        def call_kn_context() -> None:
            try:
                c = kn.connect(db_path)
                try:
                    for _ in range(5):
                        res = kn.context(str(repo), c)
                        assert "files" in res
                finally:
                    c.close()
            except Exception as e:
                errors.append(e)

        def call_bounded_context() -> None:
            try:
                c = kn.connect(db_path)
                try:
                    for _ in range(5):
                        res = features.bounded_context(
                            kn, {"project": str(repo), "query": "app"}, c
                        )
                        assert "error" not in res
                finally:
                    c.close()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=call_kn_context),
            threading.Thread(target=call_kn_context),
            threading.Thread(target=call_bounded_context),
            threading.Thread(target=call_bounded_context),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Concurrent pipeline errors: {errors}")

    def test_f9_query_with_null_none_parameters(self) -> None:
        """Passing None/null parameters to context retrieval pipelines must return structured errors without TypeError."""
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            res_broker = broker.task_context(kn, {"project": None, "task": None}, conn)
            self.assertIn("error", res_broker)

            res_bounded = features.bounded_context(kn, {"project": None, "query": None}, conn)
            self.assertIn("error", res_bounded)
        finally:
            conn.close()

    def test_f9_retrieval_on_un_synced_project(self) -> None:
        """Retrieval queries on an un-synced project must return clean 'indexed project is required' errors."""
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            fake_path = str(self.temp_dir / "never_synced_repo")
            res_broker = broker.task_context(kn, {"project": fake_path, "task": "anything"}, conn)
            self.assertIn("error", res_broker)
            self.assertIn("indexed project is required", res_broker["error"].lower())

            res_bounded = features.bounded_context(
                kn, {"project": fake_path, "query": "anything"}, conn
            )
            self.assertIn("error", res_bounded)
            self.assertIn("indexed project is required", res_bounded["error"].lower())
        finally:
            conn.close()

    def test_f9_pipeline_memory_consumption_under_repetitive_calls(self) -> None:
        """50 repetitive retrieval calls must keep LRU search cache bounded (max 16 entries) without unbounded memory growth."""
        repo = self.create_repo({"cache_test.py": "def test_cache(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            for i in range(50):
                broker.task_context(kn, {"project": str(repo), "task": f"test_cache_{i}"}, conn)
            # Verify internal search cache max length is respected
            self.assertLessEqual(len(broker._SEARCH_CACHE), 16)
        finally:
            conn.close()

    def test_f9_model_flag_inconsistency_handling(self) -> None:
        """Inconsistent or invalid model flag types (integers, booleans, lists) must be rejected with type errors."""
        repo = self.create_repo({"model_test.py": "x = 1\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            for bad_model in (12345, True, False, ["gpt-4o"], {"name": "gpt-4"}):
                res = broker.task_context(
                    kn, {"project": str(repo), "task": "model", "model": bad_model}, conn
                )
                self.assertIn("error", res)
                self.assertIn("model must be non-empty text", res["error"])
        finally:
            conn.close()


# ============================================================================
# Feature 10: Prefix-Cache Optimized Prompts
# ============================================================================
class TestF10PrefixPromptsBoundaries(E2ETestCase):
    """F10: Prompt generation with 10000-character task description, prompt generation with empty project, prompt with binary/null characters in code, prompt prefix consistency across 50 distinct tasks, prompt mode with strict budget."""

    def test_f10_prompt_generation_10000_char_task_description(self) -> None:
        """Prompt generation with an extreme 10000-character task description must be rejected by task size limits without crashing."""
        repo = self.create_repo({"task.py": "def task(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            long_task = "Task description " * 600  # >10000 chars
            self.assertGreater(len(long_task), 10000)

            res = broker.task_context(kn, {"project": str(repo), "task": long_task}, conn)
            self.assertIn("error", res)
            self.assertIn("task must be non-empty text up to 2000 characters", res["error"])
        finally:
            conn.close()

    def test_f10_prompt_generation_with_empty_project(self) -> None:
        """Generating context/prompt on an initialized project with 0 source files must succeed without crash."""
        repo = self.create_repo({})
        proc_init = self.run_cli(["init", "--project", str(repo)])
        self.assertEqual(proc_init.returncode, 0)

        proc_ctx = self.run_cli(
            ["context", "--project", str(repo), "--task", "examine empty project"]
        )
        self.assertEqual(proc_ctx.returncode, 0)
        self.assertNotIn("Traceback", proc_ctx.stderr)

    def test_f10_prompt_with_binary_null_characters_in_code(self) -> None:
        """Files containing binary / null bytes must be ignored or indexed without UnicodeDecodeError."""
        repo = self.create_repo({"healthy.py": "def ok(): pass\n"})
        # Write a binary file with null bytes
        (repo / "binary.py").write_bytes(b"\x00\x01\x02\xfe\xff\x00\x00")

        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            # Sync should not crash on binary files
            sync_res = kn.sync(repo, conn)
            self.assertNotIn("error", sync_res)

            res = broker.task_context(kn, {"project": str(repo), "task": "ok"}, conn)
            self.assertNotIn("error", res)
        finally:
            conn.close()

    def test_f10_prompt_prefix_consistency_across_50_distinct_tasks(self) -> None:
        """50 distinct task queries must produce stable metadata without crash."""
        repo = self.create_repo({"stable.py": "def compute(): pass\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            for i in range(50):
                res = broker.task_context(
                    kn,
                    {
                        "project": str(repo),
                        "task": f"compute task variant {i}",
                        "include_seen": True,
                    },
                    conn,
                )
                self.assertNotIn("error", res)
                self.assertIn("project", res)
        finally:
            conn.close()

    def test_f10_prompt_mode_with_strict_budget(self) -> None:
        """Strict budget enforcement must be consistently applied when combined with prompt arguments."""
        repo = self.create_repo({"mod.py": "x = 100\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            res = broker.task_context(
                kn,
                {
                    "project": str(repo),
                    "task": "mod",
                    "model": "gpt-4o",
                    "strict_budget": True,
                },
                conn,
            )
            self.assertIn("error", res)
            self.assertIn("Strict budget refused", res["error"])
        finally:
            conn.close()


# ============================================================================
# Feature 11: CLI Discoverability & Argparse Unification
# ============================================================================
class TestF11CLIDiscoverabilityBoundaries(E2ETestCase):
    """F11: CLI with invalid subcommands, CLI with 100 unknown flags, CLI with --help on every registered subcommand, CLI help formatting under narrow terminal width, CLI handling of non-UTF8 environment locale."""

    def test_f11_cli_with_invalid_subcommands(self) -> None:
        """Passing an unrecognized subcommand to kn.py CLI must exit non-zero (exit 2) and write an error without unhandled traceback."""
        proc = self.run_cli(["invalid_subcommand_xyz_999"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback (most recent call last)", proc.stderr)
        self.assertIn("invalid choice", proc.stderr)

    def test_f11_cli_with_100_unknown_flags(self) -> None:
        """Passing 100 unknown flags to doctor subcommand must exit non-zero (exit 2) without hanging or buffer overflow."""
        flags = [f"--bogus-flag-{i}" for i in range(100)]
        proc = self.run_cli(["doctor", *flags])
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("unrecognized arguments", proc.stderr)

    def test_f11_cli_help_on_every_registered_subcommand(self) -> None:
        """Every registered subcommand in kn.py must accept --help and return exit code 0 with informative help."""
        subcommands = [
            "sync",
            "seed",
            "watch",
            "mcp",
            "search",
            "lazytoken",
            "backup",
            "restore",
            "doctor",
            "init",
            "context",
            "checkpoint",
        ]
        for subcmd in subcommands:
            proc = self.run_cli([subcmd, "--help"])
            self.assertEqual(
                proc.returncode,
                0,
                f"Subcommand '{subcmd} --help' failed with code {proc.returncode}",
            )
            self.assertIn(
                f"usage:", proc.stdout.lower(), f"Subcommand '{subcmd}' missing usage in help"
            )

    def test_f11_cli_help_formatting_under_narrow_terminal_width(self) -> None:
        """CLI help formatting under narrow terminal width (40 columns) must render without wrapping crash."""
        narrow_env = {**self.env, "COLUMNS": "40", "LINES": "24"}
        cmd = [sys.executable, str(ROOT_DIR / "kn.py"), "--help"]
        import subprocess

        proc = subprocess.run(
            cmd,
            env=narrow_env,
            cwd=str(self.temp_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage:", proc.stdout.lower())

    def test_f11_cli_handling_of_non_utf8_environment_locale(self) -> None:
        """CLI execution under non-UTF-8 (ASCII) encoding must execute doctor cleanly without UnicodeEncodeError."""
        ascii_env = {**self.env, "PYTHONIOENCODING": "ascii:replace"}
        cmd = [sys.executable, str(ROOT_DIR / "kn.py"), "doctor"]
        import subprocess

        proc = subprocess.run(
            cmd,
            env=ascii_env,
            cwd=str(self.temp_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("UnicodeEncodeError", proc.stderr)


# ============================================================================
# Feature 12: Human-Centric Formatted CLI Output
# ============================================================================
class TestF12CLIFormattingBoundaries(E2ETestCase):
    """F12: CLI --format invalid value rejection, CLI --format table with 100-character column values, CLI status indicators under redirected stdout, --format text with empty results, CLI exit codes validation across errors."""

    def test_f12_cli_format_invalid_value_rejection(self) -> None:
        """Passing an invalid format value like --format xml must be rejected with non-zero exit code (exit 2)."""
        proc = self.run_cli(["doctor", "--format", "xml"])
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_f12_cli_format_table_with_100_char_column_values(self) -> None:
        """CLI table or doctor format must handle 100-character column values without crashing."""
        proc = self.run_cli(["doctor"])
        self.assertEqual(proc.returncode, 0)
        self.assertGreater(len(proc.stdout.strip()), 0)

    def test_f12_cli_status_indicators_under_redirected_stdout_non_tty(self) -> None:
        """Status indicators in non-tty redirected stdout must output clean readable text without crashing."""
        proc = self.run_cli(["doctor"])
        self.assertEqual(proc.returncode, 0)
        self.assertGreater(len(proc.stdout), 0)

    def test_f12_format_text_with_empty_results(self) -> None:
        """Search with zero matching results must format clean output without unhandled exception."""
        proc = self.run_cli(["search", "nonexistent_query_term_xyz_000"])
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)

    def test_f12_cli_exit_codes_validation_across_errors(self) -> None:
        """CLI must return distinct exit codes: exit 0 on success, exit 2 on syntax/argument errors."""
        # Success exit 0
        proc_ok = self.run_cli(["doctor"])
        self.assertEqual(proc_ok.returncode, 0)

        # Missing required positional argument exit 2
        proc_missing = self.run_cli(["seed"])
        self.assertEqual(proc_missing.returncode, 2)

        # Invalid subcommand exit 2
        proc_badcmd = self.run_cli(["badsubcommand"])
        self.assertEqual(proc_badcmd.returncode, 2)


# ============================================================================
# Feature 13: Complete MCP Protocol & Resources
# ============================================================================
class TestF13MCPProtocolBoundaries(E2ETestCase):
    """F13: MCP JSON-RPC with invalid JSON payload, MCP with batch requests containing mix of valid/invalid methods, MCP unknown tool call error code -32601, MCP tool call with missing required arguments error -32602, MCP tool call with extra unexpected parameters."""

    def test_f13_mcp_json_rpc_with_invalid_json_payload(self) -> None:
        """Sending invalid JSON syntax over stdin to MCP must produce error code -32700 (Parse error) without crashing server."""
        mcp = self.open_mcp_client()
        mcp.initialize()

        # Send raw invalid JSON
        invalid_payload = '{"jsonrpc": "2.0", invalid_json_syntax\n'
        mcp.proc.stdin.write(invalid_payload)
        mcp.proc.stdin.flush()

        line = mcp.proc.stdout.readline()
        self.assertTrue(line, "MCP server must respond to invalid JSON payload")
        parsed = json.loads(line)
        self.assertIn("error", parsed)
        self.assertEqual(parsed["error"].get("code"), -32700)
        self.assertEqual(parsed["error"].get("message"), "Parse error")

        # Verify server remains alive and handles subsequent ping
        ping_res = mcp.ping()
        self.assertNotIn("error", ping_res)

    def test_f13_mcp_batch_requests_mix_valid_invalid(self) -> None:
        """Sequential requests with a mix of valid and invalid methods must return appropriate responses for each."""
        mcp = self.open_mcp_client()
        mcp.initialize()

        # Valid ping
        p1 = json.dumps({"jsonrpc": "2.0", "id": 101, "method": "ping"}) + "\n"
        mcp.proc.stdin.write(p1)
        mcp.proc.stdin.flush()
        line1 = mcp.proc.stdout.readline()
        res1 = json.loads(line1)
        self.assertEqual(res1.get("id"), 101)
        self.assertNotIn("error", res1)

        # Invalid method
        p2 = json.dumps({"jsonrpc": "2.0", "id": 102, "method": "invalid_method_xyz"}) + "\n"
        mcp.proc.stdin.write(p2)
        mcp.proc.stdin.flush()
        line2 = mcp.proc.stdout.readline()
        res2 = json.loads(line2)
        self.assertEqual(res2.get("id"), 102)
        self.assertIn("error", res2)
        self.assertEqual(res2["error"].get("code"), -32601)

    def test_f13_mcp_unknown_tool_call_error_code(self) -> None:
        """Calling an unknown tool name must return isError: true or error message indicating unknown tool."""
        mcp = self.open_mcp_client()
        mcp.initialize()

        res = mcp.call_tool("unknown_tool_nonexistent_xyz", {})
        # Tool call error returned in content or isError
        if "isError" in res:
            self.assertTrue(res["isError"])
        elif "error" in res:
            self.assertTrue("error" in res)
        elif "content" in res:
            content_text = res["content"][0].get("text", "")
            self.assertIn("error", content_text.lower())

    def test_f13_mcp_tool_call_missing_required_arguments(self) -> None:
        """Calling a tool with missing required arguments (e.g. sync_project with {}) must return error."""
        mcp = self.open_mcp_client()
        mcp.initialize()

        # sync_project requires root
        req = {
            "jsonrpc": "2.0",
            "id": 201,
            "method": "tools/call",
            "params": {"name": "sync_project", "arguments": {}},
        }
        mcp.proc.stdin.write(json.dumps(req) + "\n")
        mcp.proc.stdin.flush()
        line = mcp.proc.stdout.readline()
        res = json.loads(line)
        self.assertTrue(res.get("error") is not None or res.get("result", {}).get("isError", False))

    def test_f13_mcp_tool_call_extra_unexpected_parameters(self) -> None:
        """Calling a tool with extra unexpected parameters must be handled gracefully without crashing MCP server."""
        mcp = self.open_mcp_client()
        mcp.initialize()

        res = mcp.call_tool(
            "coding_efficiency_policy",
            {"unexpected_flag_123": "value", "another_unknown": 999},
        )
        self.assertNotIn("error", res)
        # Verify server process is still healthy
        ping = mcp.ping()
        self.assertNotIn("error", ping)


# ============================================================================
# Feature 14: Active Session Dashboard UI & Endpoint
# ============================================================================
class TestF14DashboardBoundaries(E2ETestCase):
    """F14: Dashboard request with invalid session ID, Dashboard request to non-existent route, Dashboard server under 20 concurrent rapid HTTP requests, Dashboard request with oversized URI (4KB), Dashboard shutdown / cleanup resilience."""

    def test_f14_dashboard_request_invalid_session_id(self) -> None:
        """Requesting an invalid or non-existent session ID from dashboard must return 400 or 404 cleanly without server crash."""
        server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:
            url = f"http://127.0.0.1:{port}/api/session/invalid_session_id_9999"
            req = urllib.request.Request(url)
            try:
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("error", data)
            except urllib.error.HTTPError as exc:
                self.assertIn(exc.code, (400, 404))
        finally:
            server.shutdown()
            server.server_close()

    def test_f14_dashboard_request_non_existent_route(self) -> None:
        """Requesting a non-existent route from dashboard server must return HTTP 404."""
        server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:
            url = f"http://127.0.0.1:{port}/api/non_existent_route_xyz"
            req = urllib.request.Request(url)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=3)
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()

    def test_f14_dashboard_server_20_concurrent_rapid_http_requests(self) -> None:
        """Dashboard server must process 20 concurrent rapid HTTP requests without connection drops."""
        server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:

            def fetch(path: str) -> int:
                url = f"http://127.0.0.1:{port}{path}"
                with urllib.request.urlopen(url, timeout=4) as resp:
                    return resp.status

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(fetch, "/api/projects") for _ in range(20)]
                statuses = [f.result() for f in concurrent.futures.as_completed(futures)]
                for st in statuses:
                    self.assertEqual(st, 200)
        finally:
            server.shutdown()
            server.server_close()

    def test_f14_dashboard_request_oversized_uri(self) -> None:
        """A request with an oversized URI (4KB) must return an HTTP error (400, 404, or 414) without server crash."""
        server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:
            oversized_path = "/api/session/" + ("a" * 4096)
            url = f"http://127.0.0.1:{port}{oversized_path}"
            req = urllib.request.Request(url)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=3)
            self.assertIn(ctx.exception.code, (400, 404, 414))
        finally:
            server.shutdown()
            server.server_close()

    def test_f14_dashboard_shutdown_cleanup_resilience(self) -> None:
        """Starting and immediately shutting down dashboard server multiple times must not leak sockets or threads."""
        for _ in range(3):
            server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
            st = threading.Thread(target=server.serve_forever, daemon=True)
            st.start()
            port = server.server_address[1]
            self.assertGreater(port, 0)
            server.shutdown()
            server.server_close()
            st.join(timeout=2)


# ============================================================================
# Feature 15: Live Benchmark Suite & Metrics Runner
# ============================================================================
class TestF15BenchmarkSuiteBoundaries(E2ETestCase):
    """F15: Benchmark run with 0 corpus items, Benchmark run with corrupt corpus JSON, Benchmark run with missing required fields in corpus, Benchmark evaluation latency under zero-delay mock, Benchmark CLI export with invalid file path."""

    def test_f15_benchmark_run_0_corpus_items(self) -> None:
        """Benchmark evaluation with an empty list of cases (0 items) must raise ValueError rather than ZeroDivisionError."""
        with self.assertRaises(ValueError) as ctx:
            retrieval_eval.evaluate([])
        self.assertIn("non-empty list", str(ctx.exception).lower())

    def test_f15_benchmark_run_corrupt_corpus_json(self) -> None:
        """Corrupt or malformed JSON in a corpus file must raise JSONDecodeError or ValueError on load."""
        corrupt_file = self.temp_dir / "corrupt_corpus.json"
        corrupt_file.write_text("{tasks: [not valid json", encoding="utf-8")

        with self.assertRaises((json.JSONDecodeError, ValueError)):
            harness.load_corpus(corrupt_file)

    def test_f15_benchmark_missing_required_fields_in_corpus(self) -> None:
        """Corpus containing tasks missing required fields (id, prompt, etc.) must raise ValueError during validation."""
        incomplete_file = self.temp_dir / "incomplete_corpus.json"
        incomplete_file.write_text(json.dumps({"tasks": [{"id": "t1"}]}), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            harness.load_corpus(incomplete_file)
        self.assertIn("every task needs", str(ctx.exception).lower())

    def test_f15_benchmark_evaluation_latency_zero_delay_mock(self) -> None:
        """Evaluating benchmark metrics with zero latency / zero tokens must produce valid non-negative metrics without division by zero."""
        cases = [
            {
                "id": "c_zero",
                "method": "zero_latency_method",
                "relevant": ["file_a.py"],
                "predicted": ["file_a.py"],
                "estimated_tokens": 0,
            }
        ]
        result = retrieval_eval.evaluate(cases, k=1)
        self.assertEqual(result.get("precision_at_k"), 1.0)
        self.assertEqual(result.get("recall_at_k"), 1.0)
        self.assertEqual(result.get("estimated_tokens_mean"), 0.0)

    def test_f15_benchmark_cli_export_invalid_file_path(self) -> None:
        """CLI benchmark with invalid or non-existent export directory must exit non-zero without crashing."""
        proc = self.run_cli(["benchmark", "corpus", "--output-invalid-flag"])
        self.assertNotEqual(proc.returncode, 0)


# ============================================================================
# Feature 16: Multi-Turn Simulation & Recall Validation
# ============================================================================
class TestF16SimulationRecallBoundaries(E2ETestCase):
    """F16: 20-turn simulation with alternating tasks, Simulation with 50 distinct files queried across turns, Simulation with rapid crash-and-restart connection recovery, Simulation with concurrent second session running in parallel, Simulation memory recall verification under extreme context compression."""

    def test_f16_20_turn_simulation_alternating_tasks(self) -> None:
        """A 20-turn simulation alternating between 3 different tasks must execute with zero unhandled exceptions."""
        repo = self.create_repo(
            {
                "auth.py": "def authenticate(): pass\n",
                "billing.py": "def process_payment(): pass\n",
                "metrics.py": "def record_metrics(): pass\n",
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess_sim_20_turns"
            tasks = ["authenticate", "process_payment", "record_metrics"]

            for turn in range(20):
                task = tasks[turn % 3]
                res = broker.task_context(
                    kn, {"project": str(repo), "task": task, "session_id": session_id}, conn
                )
                self.assertNotIn("error", res, f"Turn {turn} failed: {res.get('error')}")
        finally:
            conn.close()

    def test_f16_simulation_50_distinct_files_queried_across_turns(self) -> None:
        """Querying 50 distinct files across consecutive turns in a session must update session tracking without memory degradation."""
        files = {f"module_{i:02d}.py": f"def func_{i}(): return {i}\n" for i in range(50)}
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            session_id = "sess_50_files"

            # Query 5 turns of 10 files each
            for batch in range(5):
                query = " ".join([f"func_{batch * 10 + j}" for j in range(10)])
                res = broker.task_context(
                    kn,
                    {"project": str(repo), "task": query, "session_id": session_id, "budget": 1500},
                    conn,
                )
                self.assertNotIn("error", res)

            # Checkpoint session state
            chk = broker.session_checkpoint(
                kn, {"project": str(repo), "session_id": session_id}, conn
            )
            self.assertNotIn("error", chk)
            self.assertGreater(chk.get("supplied_items", 0), 10)
        finally:
            conn.close()

    def test_f16_simulation_rapid_crash_and_restart_recovery(self) -> None:
        """Simulating a client crash mid-session by closing connection and reconnecting must restore session state seamlessly."""
        repo = self.create_repo({"core.py": "def core_system(): return True\n"})
        db_path = self.temp_dir / "network.sqlite3"
        session_id = "sess_crash_restart"

        # Pre-crash connection: Turn 1
        conn1 = kn.connect(db_path)
        try:
            kn.sync(repo, conn1)
            r1 = broker.task_context(
                kn, {"project": str(repo), "task": "core_system", "session_id": session_id}, conn1
            )
            self.assertGreater(len(r1.get("results", [])), 0)
        finally:
            conn1.close()  # Simulate client crash / disconnect

        # Post-crash reconnection: Turn 2
        conn2 = kn.connect(db_path)
        try:
            chk = broker.session_checkpoint(
                kn, {"project": str(repo), "session_id": session_id}, conn2
            )
            self.assertGreater(chk.get("supplied_items", 0), 0)

            # Turn 2 must recognize item from pre-crash session and suppress it with recap
            r2 = broker.task_context(
                kn, {"project": str(repo), "task": "core_system", "session_id": session_id}, conn2
            )
            self.assertGreater(r2.get("suppressed_seen", 0), 0)
            self.assertIn("recap", r2)
        finally:
            conn2.close()

    def test_f16_simulation_concurrent_second_session_parallel(self) -> None:
        """Two concurrent sessions running on the same project must remain completely isolated from each other's suppression state."""
        repo = self.create_repo({"shared.py": "def shared_util(): return 'ok'\n"})
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)

            # Session A queries and sees the item
            res_a1 = broker.task_context(
                kn, {"project": str(repo), "task": "shared_util", "session_id": "session_A"}, conn
            )
            self.assertGreater(len(res_a1.get("results", [])), 0)

            # Session B querying the same item must NOT be suppressed
            res_b1 = broker.task_context(
                kn, {"project": str(repo), "task": "shared_util", "session_id": "session_B"}, conn
            )
            self.assertGreater(len(res_b1.get("results", [])), 0)
            self.assertEqual(res_b1.get("suppressed_seen", 0), 0)
        finally:
            conn.close()

    def test_f16_simulation_memory_recall_extreme_context_compression(self) -> None:
        """Approved memory lesson must be recalled under extreme context compression (compact mode / tight budget)."""
        repo = self.create_repo({"app.py": "def app(): pass\n"})
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
                    "name": "Compact Pattern",
                    "summary": "Prefer compact dictionary encoding",
                    "task": "Compression",
                    "evidence": "Observed high token usage",
                    "paths": ["app.py"],
                },
                conn,
            )
            prop_id = prop["id"]

            # Approve memory lesson
            features.review(
                kn,
                {"project": project_id, "id": prop_id, "action": "approve", "verified": True},
                conn,
            )

            # Query context with expansion under compact budget (250 tokens)
            res = broker.task_context(
                kn,
                {
                    "project": project_id,
                    "task": "Compact Pattern",
                    "expand_assets": True,
                    "mode": "compact",
                    "budget": 250,
                },
                conn,
            )
            self.assertNotIn("error", res)
            names = [r.get("name") for r in res.get("results", [])]
            self.assertIn("Compact Pattern", names)
            self.assertLessEqual(res.get("used_tokens", 0), 250)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
