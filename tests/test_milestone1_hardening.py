"""Comprehensive tests for Milestone 1: SQLite Graph & Session Recall Hardening."""

from __future__ import annotations
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

import kn
import features
import broker
from broker import _resolve_import_target
from source_index import python_imports, javascript_imports


class Milestone1HardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "test_m1.sqlite3"
        self.db = kn.connect(self.db_path)
        self.project = str(self.root.resolve())

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    # --- 1. Concurrency & PRAGMAs ---
    def test_pragma_busy_timeout_and_foreign_keys_configured(self):
        busy_timeout = self.db.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertEqual(busy_timeout, 5000)
        foreign_keys = self.db.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(foreign_keys, 1)

    def test_composite_indexes_exist_and_accelerate_queries(self):
        # Verify index existence
        indexes = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name IS NOT NULL"
            ).fetchall()
        }
        expected_indexes = {
            "context_session_lookup_idx",
            "memory_proposals_asset_idx",
            "memory_proposals_proj_kind_idx",
            "asset_link_evidence_endpoints_idx",
            "asset_link_evidence_target_idx",
            "asset_projects_project_idx",
            "imports_target_idx",
        }
        for idx in expected_indexes:
            self.assertIn(idx, indexes, f"Missing index: {idx}")

        # Verify EXPLAIN QUERY PLAN shows index usage
        # 1. context_session_items
        plan = [
            row["detail"]
            for row in self.db.execute(
                "EXPLAIN QUERY PLAN SELECT item_key FROM context_session_items "
                "WHERE project_id=? AND session_id=? ORDER BY updated_at DESC, item_key LIMIT 30",
                ("p1", "s1"),
            ).fetchall()
        ]
        self.assertTrue(
            any("context_session_lookup_idx" in d or "USING INDEX" in d for d in plan),
            f"Query did not use index: {plan}",
        )

        # 2. memory_proposals
        plan = [
            row["detail"]
            for row in self.db.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM memory_proposals WHERE asset_id=? AND status=?",
                (1, "pending"),
            ).fetchall()
        ]
        self.assertTrue(
            any("memory_proposals_asset_idx" in d or "USING INDEX" in d for d in plan),
            f"Query did not use index: {plan}",
        )

        # 3. imports target lookup via imports_target_idx
        plan = [
            row["detail"]
            for row in self.db.execute(
                "EXPLAIN QUERY PLAN SELECT source FROM imports INDEXED BY imports_target_idx "
                "WHERE project_id=? AND target=?",
                ("p1", "target"),
            ).fetchall()
        ]
        self.assertTrue(
            any("imports_target_idx" in d for d in plan),
            f"Query did not use index: {plan}",
        )

        # 4. asset_projects project lookup
        plan = [
            row["detail"]
            for row in self.db.execute(
                "EXPLAIN QUERY PLAN SELECT asset_id FROM asset_projects WHERE project_id=?",
                ("p1",),
            ).fetchall()
        ]
        self.assertTrue(
            any("asset_projects_project_idx" in d or "USING INDEX" in d for d in plan),
            f"Query did not use index: {plan}",
        )

    # --- 2. Substring False-Positive Prevention ---
    def test_standard_library_import_does_not_create_substring_false_positives(self):
        # Create files where main.py imports re and helper
        # Project also has features.py and retrieval_eval.py which contain "re" as a substring
        (self.root / "helper.py").write_text("def assist():\n    return 42\n", encoding="utf-8")
        (self.root / "features.py").write_text("class Features:\n    pass\n", encoding="utf-8")
        (self.root / "retrieval_eval.py").write_text(
            "def evaluate():\n    pass\n", encoding="utf-8"
        )
        (self.root / "main.py").write_text(
            "import re\nimport helper\ndef run():\n    return helper.assist()\n",
            encoding="utf-8",
        )
        kn.sync(self.root, self.db)

        # Direct helper check
        active_files = {"main.py", "helper.py", "features.py", "retrieval_eval.py"}
        # re should NOT resolve to features.py or retrieval_eval.py
        self.assertIsNone(_resolve_import_target("main.py", "re", active_files))
        # helper should resolve to helper.py
        self.assertEqual(_resolve_import_target("main.py", "helper", active_files), "helper.py")

        # Session checkpoint graph check
        checkpoint = kn.feature_call(
            "checkpoint",
            {"project": self.project, "session_id": "test-session"},
            self.db,
        )
        edges = checkpoint["active_graph"]["edges"]
        self.assertFalse(
            any(e["source"] == "main.py" and e["target"] == "features.py" for e in edges),
            "Phantom edge found between main.py and features.py!",
        )
        self.assertFalse(
            any(e["source"] == "main.py" and e["target"] == "retrieval_eval.py" for e in edges),
            "Phantom edge found between main.py and retrieval_eval.py!",
        )

    # --- 3. Relative Import Resolution for JS/TS & Python ---
    def test_relative_import_resolution_javascript_and_typescript(self):
        active_files = {
            "src/components/Header.tsx",
            "src/utils/calc.ts",
            "src/index.js",
            "src/services/api.js",
            "src/services/index.js",
        }
        # ../ from subfolder
        resolved = _resolve_import_target(
            "src/components/Header.tsx", "../utils/calc", active_files
        )
        self.assertEqual(resolved, "src/utils/calc.ts")

        # ./ from same folder
        resolved = _resolve_import_target("src/components/Header.tsx", "./Header", active_files)
        self.assertIsNone(resolved)  # Cannot import self

        # ./services resolving to index.js
        resolved = _resolve_import_target("src/index.js", "./services", active_files)
        self.assertEqual(resolved, "src/services/index.js")

        # ./services/api with extension missing
        resolved = _resolve_import_target("src/index.js", "./services/api", active_files)
        self.assertEqual(resolved, "src/services/api.js")

    def test_relative_import_resolution_python(self):
        active_files = {
            "pkg/sub/worker.py",
            "pkg/broker.py",
            "pkg/sub/utils.py",
        }
        # .. from subpackage
        resolved = _resolve_import_target("pkg/sub/worker.py", "..broker", active_files)
        self.assertEqual(resolved, "pkg/broker.py")

        # . from same package
        resolved = _resolve_import_target("pkg/sub/worker.py", ".utils", active_files)
        self.assertEqual(resolved, "pkg/sub/utils.py")

        # AST import extraction for from . import helper
        code = "from . import helper\nfrom ..parent import model\n"
        extracted = python_imports(code)
        self.assertIn(".helper", extracted)
        self.assertIn("..parent", extracted)

    # --- 4. Active Session Item Freshness & Deduplication ---
    def test_session_item_timestamp_refreshed_on_suppression_prevents_eviction(self):
        (self.root / "foundational.py").write_text(
            "class FoundationalCore:\n    pass\n", encoding="utf-8"
        )
        kn.sync(self.root, self.db)

        session_id = "long-session"
        # Turn 1: Retrieve foundational.py
        ret1 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "FoundationalCore setup",
                "session_id": session_id,
                "budget": 800,
            },
            self.db,
        )
        self.assertTrue(ret1["results"])
        initial_row = self.db.execute(
            "SELECT item_key, updated_at FROM context_session_items "
            "WHERE project_id=? AND session_id=? AND item_key LIKE '%foundational.py%'",
            (self.project, session_id),
        ).fetchone()
        self.assertIsNotNone(initial_row)
        item_key = initial_row["item_key"]

        # Simulate that Turn 1 happened in the past (100 seconds ago)
        past_ts = int(time.time()) - 100
        self.db.execute(
            "UPDATE context_session_items SET updated_at=? WHERE project_id=? AND session_id=?",
            (past_ts, self.project, session_id),
        )

        # Insert 35 intermediate dummy items into the session with timestamps between past_ts+1 and past_ts+35
        dummy_rows = [
            (self.project, session_id, f"dummy:{i:02}", f"hash_{i}", past_ts + 1 + i)
            for i in range(35)
        ]
        self.db.executemany("INSERT INTO context_session_items VALUES(?,?,?,?,?)", dummy_rows)
        self.db.commit()

        # If not refreshed, foundational item (timestamp past_ts) would be evicted by LIMIT 30
        # Now run Turn 2: Query FoundationalCore again
        ret2 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "FoundationalCore setup",
                "session_id": session_id,
                "budget": 800,
            },
            self.db,
        )
        self.assertGreater(ret2["suppressed_seen"], 0)

        # Verify timestamp was updated in context_session_items to current time (> past_ts + 35)
        updated_row = self.db.execute(
            "SELECT updated_at FROM context_session_items WHERE project_id=? AND session_id=? AND item_key=?",
            (self.project, session_id, item_key),
        ).fetchone()
        self.assertGreater(updated_row["updated_at"], past_ts + 35)

        # Call checkpoint: foundational item MUST be retained in recent_keys and active_graph
        cp = kn.call("checkpoint", {"project": self.project, "session_id": session_id}, self.db)
        self.assertIn(item_key, cp["recent_keys"])
        self.assertIn("foundational.py", cp["active_graph"]["files"])

    # --- 5. Context Amnesia Elimination & Recovery Recap ---
    def test_full_suppression_returns_recovery_recap_and_active_graph(self):
        (self.root / "core.py").write_text(
            "class CoreEngine:\n    def start(self): pass\n", encoding="utf-8"
        )
        kn.sync(self.root, self.db)

        session_id = "amnesia-test-session"
        # Turn 1: retrieve
        ret1 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "CoreEngine start",
                "session_id": session_id,
                "budget": 800,
            },
            self.db,
        )
        self.assertTrue(ret1["results"])

        # Turn 2: same task in same session -> full suppression
        ret2 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "CoreEngine start",
                "session_id": session_id,
                "budget": 800,
            },
            self.db,
        )
        self.assertEqual(ret2["results"], [])
        self.assertGreater(ret2["suppressed_seen"], 0)

        # Amnesia elimination: recap and active graph are present
        self.assertIn("recap", ret2)
        self.assertTrue(len(ret2["recap"]) > 0)
        self.assertIn("active_context_summary", ret2)
        self.assertIn("active_graph", ret2)
        self.assertIn("core.py", ret2["active_graph"]["files"])
        self.assertIn("graph_topology", ret2)

    # --- 6. Cross-Turn Graph Edge Preservation ---
    def test_cross_turn_graph_edge_preservation(self):
        (self.root / "helper.py").write_text("def assist():\n    return 42\n", encoding="utf-8")
        (self.root / "service.py").write_text(
            "import helper\ndef run():\n    return helper.assist()\n", encoding="utf-8"
        )
        kn.sync(self.root, self.db)

        session_id = "cross-turn-session"

        # Turn 1: Query only helper
        ret1 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "assist helper",
                "session_id": session_id,
                "budget": 800,
            },
            self.db,
        )
        self.assertIn("helper.py", [r.get("path") for r in ret1["results"]])

        # Turn 2: Query service (service imports helper)
        ret2 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "service run",
                "session_id": session_id,
                "budget": 800,
            },
            self.db,
        )
        # Even if results only has service.py, the edge service.py -> helper.py must be computed
        self.assertIn("graph_edges", ret2)
        edges = ret2["graph_edges"]
        self.assertTrue(
            any(e["source"] == "service.py" and e["target"] == "helper.py" for e in edges),
            f"Cross-turn edge missing from {edges}",
        )

    # --- 7. Bulk Query Performance and Correctness ---
    def test_bulk_query_correctness_and_n_plus_one_elimination(self):
        for i in range(10):
            (self.root / f"mod_{i}.py").write_text(f"class Module{i}: pass\n", encoding="utf-8")
        kn.sync(self.root, self.db)

        # Propose and review a memory asset
        proposal = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "bulk_lesson",
                "summary": "Demonstrates bulk retrieval without N+1 queries",
                "task": "bulk testing",
                "evidence": "Observed evidence in unit tests",
                "paths": ["mod_0.py", "mod_1.py"],
            },
            self.db,
        )
        self.assertIn("id", proposal)
        proposal_id = proposal["id"]
        rev = features.review(
            kn,
            {
                "project": self.project,
                "id": proposal_id,
                "action": "approve",
                "verification_state": "verified",
            },
            self.db,
        )
        self.assertEqual(rev.get("status"), "approved")

        ret = kn.call(
            "get_task_context",
            {"project": self.project, "task": "Module bulk_lesson testing", "budget": 2000},
            self.db,
        )
        self.assertNotIn("error", ret)
        self.assertTrue(len(ret["results"]) > 0)
        asset_crumbs = [r for r in ret["results"] if r.get("type") == "asset"]
        if asset_crumbs:
            self.assertIn("evidence_paths", asset_crumbs[0])
            self.assertIn("mod_0.py", asset_crumbs[0]["evidence_paths"])

    # --- 8. Additional Edge Cases ---
    def test_actual_local_stdlib_named_file_matches(self):
        # If project legitimately defines a local re.py, import re SHOULD match it
        active_files = {"main.py", "re.py"}
        self.assertEqual(_resolve_import_target("main.py", "re", active_files), "re.py")
        active_files_nested = {"src/main.py", "src/re.py"}
        self.assertEqual(
            _resolve_import_target("src/main.py", "re", active_files_nested), "src/re.py"
        )

    def test_cross_turn_graph_edge_reverse_direction(self):
        (self.root / "helper.py").write_text("def assist():\n    return 42\n", encoding="utf-8")
        (self.root / "service.py").write_text(
            "import helper\ndef run():\n    return helper.assist()\n", encoding="utf-8"
        )
        kn.sync(self.root, self.db)

        session_id = "reverse-session"
        # Turn 1: Retrieve service
        ret1 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "service run",
                "session_id": session_id,
                "budget": 800,
            },
            self.db,
        )
        self.assertIn("service.py", [r.get("path") for r in ret1["results"]])

        # Turn 2: Retrieve helper
        ret2 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "assist helper",
                "session_id": session_id,
                "budget": 800,
            },
            self.db,
        )
        # Verify edge service.py -> helper.py is present
        self.assertIn("graph_edges", ret2)
        edges = ret2["graph_edges"]
        self.assertTrue(
            any(e["source"] == "service.py" and e["target"] == "helper.py" for e in edges),
            f"Reverse cross-turn edge missing from {edges}",
        )

    def test_full_suppression_tight_budget_graceful_handling(self):
        (self.root / "small.py").write_text("class Small: pass\n", encoding="utf-8")
        kn.sync(self.root, self.db)

        session_id = "tight-budget-session"
        # Turn 1
        kn.call(
            "get_task_context",
            {"project": self.project, "task": "Small", "session_id": session_id, "budget": 800},
            self.db,
        )
        # Turn 2 with tight budget of 150
        ret2 = kn.call(
            "get_task_context",
            {"project": self.project, "task": "Small", "session_id": session_id, "budget": 150},
            self.db,
        )
        self.assertNotIn("error", ret2)
        self.assertEqual(ret2["results"], [])
        self.assertGreater(ret2["suppressed_seen"], 0)
        self.assertIn("recap", ret2)

    def test_concurrent_connection_busy_timeout(self):
        db2 = kn.connect(self.db_path)
        try:
            self.assertEqual(db2.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
            self.assertEqual(db2.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            db2.close()

    # --- 9. Challenger Edge Cases: Import Target Resolution ---
    def test_challenger_edge_cases_import_target_resolution(self):
        # 1. Standard library imports do not match arbitrary nested subdirectories
        self.assertIsNone(
            _resolve_import_target("main.py", "string", {"main.py", "vendor/foo/string.py"})
        )
        self.assertIsNone(
            _resolve_import_target("main.py", "difflib", {"main.py", "sub/difflib.py"})
        )
        self.assertIsNone(_resolve_import_target("main.py", "re", {"main.py", "tools/re.py"}))
        self.assertIsNone(_resolve_import_target("main.py", "io", {"main.py", "helpers/io.py"}))

        # 2. Self-import guard & bare stem restriction
        self.assertIsNone(
            _resolve_import_target("server.py", "server", {"server.py", "sub/server.py"})
        )
        self.assertIsNone(
            _resolve_import_target("server.py", "server.py", {"server.py", "sub/server.py"})
        )
        self.assertIsNone(_resolve_import_target("main.py", "server", {"main.py", "sub/server.py"}))

        # 3. TypeScript declaration index files (.d.ts, /index.d.ts)
        self.assertEqual(
            _resolve_import_target(
                "src/main.ts", "./types", {"src/main.ts", "src/types/index.d.ts"}
            ),
            "src/types/index.d.ts",
        )
        self.assertEqual(
            _resolve_import_target(
                "src/main.ts", "./types/index", {"src/main.ts", "src/types/index.d.ts"}
            ),
            "src/types/index.d.ts",
        )

        # 4. Windows backslash normalization in import targets
        self.assertEqual(
            _resolve_import_target(
                "src/main.ts", ".\\components\\button", {"src/main.ts", "src/components/button.tsx"}
            ),
            "src/components/button.tsx",
        )
        self.assertEqual(
            _resolve_import_target(
                "src/app/main.ts",
                "..\\components\\button",
                {"src/app/main.ts", "src/components/button.tsx"},
            ),
            "src/components/button.tsx",
        )

    def test_checkpoint_active_graph_avoids_phantom_stdlib_and_self_edges(self):
        (self.root / "vendor" / "foo").mkdir(parents=True, exist_ok=True)
        (self.root / "sub").mkdir(parents=True, exist_ok=True)
        (self.root / "vendor" / "foo" / "string.py").write_text(
            "STR = 'vendor'\n", encoding="utf-8"
        )
        (self.root / "sub" / "server.py").write_text("class SubServer: pass\n", encoding="utf-8")
        (self.root / "main.py").write_text(
            "import string\nprint(string.ascii_letters)\n", encoding="utf-8"
        )
        (self.root / "server.py").write_text("import server\napp = 'main'\n", encoding="utf-8")
        kn.sync(self.root, self.db)

        checkpoint = kn.feature_call(
            "checkpoint",
            {"project": self.project, "session_id": "adversarial-session"},
            self.db,
        )
        edges = checkpoint["active_graph"]["edges"]
        self.assertFalse(
            any(e["source"] == "main.py" and "string.py" in e["target"] for e in edges),
            f"Phantom stdlib edge found in edges: {edges}",
        )
        self.assertFalse(
            any(e["source"] == "server.py" and e["target"] == "sub/server.py" for e in edges),
            f"Phantom self-import edge found in edges: {edges}",
        )

    # --- 10. Challenger Iteration 2 Hardening: Key Parsing, Budget Shedding, & Touch Sync ---
    def test_build_session_graph_key_parsing_and_symbol_free_import_edges(self):
        # 1. Verify build_session_graph extracts clean filenames from file: and import: keys
        recent = [
            "file:config.js:config.js:",
            "file:main.js:main.js:",
            "import:main.js:./config:",
            "symbol:utils.js:helper:10",
            "asset:42",
        ]
        graph = broker.build_session_graph(None, None, self.project, recent)
        files = graph["active_graph"]["files"]
        self.assertNotIn("config.js:config.js:", files)
        self.assertNotIn("main.js:./config", files)
        self.assertNotIn("main.js:main.js:", files)
        self.assertEqual(files, ["config.js", "main.js", "utils.js"])
        self.assertEqual(len(graph["active_graph"]["symbols"]), 1)
        self.assertEqual(graph["active_graph"]["symbols"][0]["name"], "helper")

        # 2. Verify import edges are discovered between files without symbols
        (self.root / "config.js").write_text("module.exports = { port: 3000 };\n", encoding="utf-8")
        (self.root / "main.js").write_text(
            "const config = require('./config');\n", encoding="utf-8"
        )
        kn.sync(self.root, self.db)

        recent_with_db = [
            "file:config.js:config.js:",
            "file:main.js:main.js:",
            "import:main.js:./config:",
        ]
        graph_db = broker.build_session_graph(kn, self.db, self.project, recent_with_db)
        edges = graph_db["active_graph"]["edges"]
        self.assertTrue(
            any(e["source"] == "main.js" and e["target"] == "config.js" for e in edges),
            f"Expected import edge between main.js and config.js, got: {edges}",
        )

    def test_full_suppression_tight_budgets_graceful_recovery(self):
        # Create a module with 15 methods to produce a sizeable suppression recap
        lines = ["class ControllerService:"]
        for i in range(15):
            lines.append(f"    def handle_request_endpoint_action_{i}(self, req, ctx): pass")
        (self.root / "ctrl_service.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
        kn.sync(self.root, self.db)

        session_id = "tight-suppression-session"
        # Turn 1: populate session
        ret1 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "ControllerService handle_request",
                "session_id": session_id,
                "budget": 1200,
            },
            self.db,
        )
        self.assertTrue(ret1["results"])

        # Turn 2: Full suppression under tight budgets (100, 150, 200, 250)
        for b in (100, 150, 200, 250):
            ret = kn.call(
                "get_task_context",
                {
                    "project": self.project,
                    "task": "ControllerService handle_request",
                    "session_id": session_id,
                    "budget": b,
                },
                self.db,
            )
            self.assertNotIn("error", ret, f"Budget {b} failed with error: {ret.get('error')}")
            self.assertEqual(ret["results"], [])
            self.assertGreater(ret["suppressed_seen"], 0)
            self.assertLessEqual(
                ret.get("used_tokens", 0), b, f"Budget {b} exceeded: used={ret.get('used_tokens')}"
            )

    def test_touch_synchronization_active_graph_current_turn(self):
        (self.root / "foundational.py").write_text(
            "class FoundationalCore:\n    pass\n", encoding="utf-8"
        )
        kn.sync(self.root, self.db)

        session_id = "sync-touch-session"
        # Turn 1: Retrieve foundational.py
        ret1 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "FoundationalCore",
                "session_id": session_id,
                "budget": 800,
            },
            self.db,
        )
        self.assertTrue(ret1["results"])

        # Simulate past turn timestamp and insert 35 intermediate dummy items
        past_ts = int(time.time()) - 100
        self.db.execute(
            "UPDATE context_session_items SET updated_at=? WHERE project_id=? AND session_id=?",
            (past_ts, self.project, session_id),
        )
        dummy_rows = [
            (self.project, session_id, f"dummy:{i:02}", f"hash_{i}", past_ts + 1 + i)
            for i in range(35)
        ]
        self.db.executemany("INSERT INTO context_session_items VALUES(?,?,?,?,?)", dummy_rows)
        self.db.commit()

        # Turn 2: Query FoundationalCore again -> full suppression
        # Touch synchronization MUST update context_session_items before build_session_graph runs,
        # so foundational.py appears in ret2's active_graph!
        ret2 = kn.call(
            "get_task_context",
            {
                "project": self.project,
                "task": "FoundationalCore",
                "session_id": session_id,
                "budget": 800,
            },
            self.db,
        )
        self.assertEqual(ret2["results"], [])
        self.assertGreater(ret2["suppressed_seen"], 0)
        self.assertIn("active_graph", ret2)
        active_files = ret2["active_graph"]["files"]
        self.assertIn(
            "foundational.py",
            active_files,
            f"foundational.py missing from current turn active_graph: {active_files}",
        )


if __name__ == "__main__":
    unittest.main()
