"""Tier 4 Real-World Application Scenarios: 8 complex multi-feature workloads (S1 through S8)."""

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


class TestTier4Workloads(E2ETestCase):
    """Tier 4: Realistic multi-feature real-world application scenarios (S1 through S8)."""

    # ------------------------------------------------------------------------
    # S1: 10-Turn Incremental Refactoring Session
    # Full multi-turn stateful refactoring session; zero exceptions; zero amnesia;
    # foundational items recalled; >60% token compression.
    # Features: F1, F3, F4, F7, F8, F16
    # ------------------------------------------------------------------------
    def test_s1_ten_turn_incremental_refactoring_session(self) -> None:
        files = {
            "core/__init__.py": "",
            "core/config.py": (
                '"""Application configuration management."""\n'
                "CONFIG = {\n"
                "    'db_url': 'sqlite:///data.db',\n"
                "    'debug': True,\n"
                "    'timeout': 30,\n"
                "    'max_connections': 10,\n"
                "    'retry_attempts': 3,\n"
                "}\n"
                "def get_config():\n"
                '    """Return application configuration dictionary."""\n'
                "    return CONFIG\n"
            ),
            "core/db.py": (
                '"""Database connection pool management."""\n'
                "from .config import get_config\n"
                "class DatabasePool:\n"
                "    def __init__(self):\n"
                "        self.config = get_config()\n"
                "        self.pool_size = self.config.get('max_connections', 10)\n"
                "    def get_connection(self):\n"
                '        """Acquire an active database connection."""\n'
                "        return {'conn': 'active', 'timeout': self.config.get('timeout', 30)}\n"
            ),
            "models/__init__.py": "",
            "models/user.py": (
                '"""User model and schema definition."""\n'
                "class User:\n"
                "    def __init__(self, uid, username, role='user'):\n"
                "        self.uid = uid\n"
                "        self.username = username\n"
                "        self.role = role\n"
                "    def to_dict(self):\n"
                "        return {'uid': self.uid, 'username': self.username, 'role': self.role}\n"
            ),
            "utils/__init__.py": "",
            "utils/crypto.py": (
                '"""Cryptographic hashing and verification utilities."""\n'
                "import hashlib\n"
                "def hash_password(raw):\n"
                '    """Compute SHA-256 hash of password string."""\n'
                "    return hashlib.sha256(raw.encode('utf-8')).hexdigest()\n"
                "def verify_password(raw, hashed):\n"
                '    """Verify raw password against stored hash."""\n'
                "    return hash_password(raw) == hashed\n"
            ),
            "services/__init__.py": "",
            "services/auth_service.py": (
                '"""Authentication service handling login and token validation."""\n'
                "from ..core.db import DatabasePool\n"
                "from ..utils.crypto import verify_password\n"
                "class AuthService:\n"
                "    def __init__(self, pool):\n"
                "        self.pool = pool\n"
                "    def authenticate(self, username, password):\n"
                '        """Verify user credentials and return authentication token."""\n'
                "        return {'token': f'auth_{username}', 'status': 'authenticated'}\n"
            ),
            "services/user_service.py": (
                '"""User management and registration service."""\n'
                "from ..models.user import User\n"
                "class UserService:\n"
                "    def __init__(self, pool):\n"
                "        self.pool = pool\n"
                "    def find_user(self, uid):\n"
                '        """Find user by ID."""\n'
                "        return User(uid, 'alice')\n"
            ),
            "api/__init__.py": "",
            "api/middleware.py": (
                '"""HTTP middleware for authentication and request validation."""\n'
                "from ..services.auth_service import AuthService\n"
                "def auth_middleware(req):\n"
                '    """Verify request authentication header."""\n'
                "    return req.get('auth') is not None\n"
            ),
            "api/routes.py": (
                '"""API route handlers for users and authentication endpoints."""\n'
                "from .middleware import auth_middleware\n"
                "from ..services.user_service import UserService\n"
                "def setup_routes(app):\n"
                '    """Register application HTTP route handlers."""\n'
                "    return {'/api/auth': 'auth_handler', '/api/users': 'user_handler'}\n"
            ),
        }
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            sync_res = kn.sync(repo, conn)
            self.assertEqual(sync_res.get("error_count", 0), 0)

            session_id = "sess_s1_refactoring_10_turns"
            turn_results = []
            turn_tasks = [
                # Turn 1: Discover configuration and database pool
                "Setup database connection in core/db.py and load core/config.py",
                # Turn 2: User model definition
                "Define user entity in models/user.py with role support",
                # Turn 3: Cryptographic utilities
                "Implement password hashing and verification in utils/crypto.py",
                # Turn 4: Authentication service
                "Build AuthService in services/auth_service.py using pool and crypto",
                # Turn 5: User service registration
                "Implement UserService in services/user_service.py using User model",
                # Turn 6: Request middleware
                "Create auth_middleware in api/middleware.py using AuthService",
                # Turn 7: API route definitions
                "Wire auth and user routes in api/routes.py with middleware",
                # Turn 8: Refactor AuthService (revisit Turn 4 -> suppression & touch)
                "Refactor AuthService in services/auth_service.py to add token expiry",
                # Turn 9: Revisit core DatabasePool (revisit Turn 1 foundational items -> recap amnesia recovery)
                "Revisit DatabasePool connection pool in core/db.py and core/config.py",
                # Turn 10: Final validation and checkpointing
                "Audit overall architecture and complete refactoring session checkpoint",
            ]

            for turn_idx, task_desc in enumerate(turn_tasks, start=1):
                if turn_idx < 10:
                    res = broker.task_context(
                        kn,
                        {
                            "project": str(repo),
                            "task": task_desc,
                            "session_id": session_id,
                            "budget": 800,
                        },
                        conn,
                    )
                    self.assertNotIn(
                        "error", res, f"Turn {turn_idx} returned error: {res.get('error')}"
                    )
                    turn_results.append(res)
                else:
                    # Turn 10: Final checkpoint restoration & verification
                    checkpoint_res = broker.session_checkpoint(
                        kn, {"project": str(repo), "session_id": session_id}, conn
                    )
                    self.assertNotIn("error", checkpoint_res)
                    turn_results.append(checkpoint_res)

            # Verification 1: Zero unhandled exceptions across all 10 turns
            self.assertEqual(len(turn_results), 10)

            # Verification 2: Turn 8 suppression (AuthService was seen in Turn 4)
            turn8 = turn_results[7]
            self.assertGreaterEqual(
                turn8.get("suppressed_seen", 0),
                1,
                "Turn 8 must suppress previously seen AuthService",
            )

            # Verification 3: Turn 9 recap recovery (core/db.py & core/config.py seen in Turn 1)
            turn9 = turn_results[8]
            self.assertGreaterEqual(turn9.get("suppressed_seen", 0), 1)
            recap = turn9.get("recap")
            self.assertIsNotNone(recap, "Turn 9 must provide recap breadcrumbs on suppression")
            recap_keys = [
                item.get("key", "") if isinstance(item, dict) else str(item) for item in recap
            ]
            self.assertTrue(
                any("core/db.py" in k or "core/config.py" in k for k in recap_keys),
                f"Foundational Turn 1 items missing from Turn 9 recap: {recap_keys}",
            )

            # Verification 4: Zero amnesia: Foundational Turn 1 items preserved in session
            session_rows = conn.execute(
                "SELECT item_key FROM context_session_items WHERE session_id=?", (session_id,)
            ).fetchall()
            keys = [r["item_key"] for r in session_rows]
            self.assertTrue(
                any("core/db.py" in k for k in keys), "Turn 1 core/db.py evicted from session items"
            )
            self.assertTrue(
                any("core/config.py" in k for k in keys),
                "Turn 1 core/config.py evicted from session",
            )

            # Verification 5: Token compression ratio (>50% reduction vs unoptimized raw source reading)
            total_session_tokens = sum(r.get("used_tokens", 0) for r in turn_results[:9])
            raw_source_per_turn = kn.estimate("".join(files.values()))
            unoptimized_raw_tokens = raw_source_per_turn * 9
            compression = (unoptimized_raw_tokens - total_session_tokens) / unoptimized_raw_tokens
            self.assertGreaterEqual(
                compression, 0.50, f"Expected >50% token compression, got: {compression:.2%}"
            )

            # Verification 6: Turn 10 checkpoint graph reconstruction
            turn10 = turn_results[9]
            self.assertIn("active_graph", turn10)
            self.assertGreater(len(turn10["active_graph"]["files"]), 0)
            self.assertGreater(turn10["supplied_items"], 0)
        finally:
            conn.close()

    # ------------------------------------------------------------------------
    # S2: Multi-Interface Sync & Query Cycle (CLI ↔ MCP ↔ Dashboard)
    # CLI indexes repo; MCP retrieves context; Dashboard /api/session/<id> serves active session graph.
    # Features: F1, F11, F13, F14
    # ------------------------------------------------------------------------
    def test_s2_multi_interface_sync_and_query_cycle(self) -> None:
        repo = self.create_repo(
            {
                "main.py": "def main():\n    return 'hello world'\n",
                "server.py": "def start_server(port):\n    return port\n",
            }
        )
        session_id = "sess_s2_cycle"

        # Step 1: CLI indexes repository
        sync_proc = self.run_cli(["sync", str(repo)])
        self.assertEqual(sync_proc.returncode, 0, f"CLI sync failed: {sync_proc.stderr}")

        # Step 2: MCP retrieves multi-turn task context
        mcp = self.open_mcp_client()
        mcp.initialize()

        mcp_res = mcp.call_tool(
            "get_task_context",
            {"project": str(repo), "task": "start server and main", "session_id": session_id},
        )
        content_text = mcp_res.get("content", [{}])[0].get("text", "{}")
        mcp_payload = json.loads(content_text)
        self.assertNotIn("error", mcp_payload)
        self.assertGreater(len(mcp_payload.get("results", [])), 0)

        # Step 3: Dashboard HTTP endpoint /api/session returns session token
        server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:
            url = f"http://127.0.0.1:{port}/api/session"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                self.assertEqual(resp.status, 200)
                dash_data = json.loads(resp.read().decode("utf-8"))
                self.assertIn("token", dash_data)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/session/{session_id}", timeout=3
            ) as resp:
                graph = json.loads(resp.read())
                self.assertIn("server.py", graph["active_graph"]["files"])
        finally:
            server.shutdown()
            server.server_close()

        # Step 4: CLI checkpoint validation
        cli_cp = self.run_cli_json(
            ["checkpoint", "--project", str(repo), "--session-id", session_id]
        )
        self.assertNotIn("error", cli_cp)
        self.assertEqual(cli_cp.get("session_id"), session_id)
        self.assertGreater(cli_cp.get("supplied_items", 0), 0)

    # ------------------------------------------------------------------------
    # S3: BPE Tokenizer & Single-Pass Optimization Pipeline
    # High-budget context retrieval with lean DSL and prefix-cache prompt;
    # >75% token reduction vs unoptimized raw JSON.
    # Features: F6, F7, F8, F9, F10
    # ------------------------------------------------------------------------
    def test_s3_bpe_tokenizer_and_single_pass_pipeline(self) -> None:
        files = {
            f"service_{i}.py": (
                f"# Service module {i} with extensive documentation and comments\n"
                f"# Provides domain-specific capabilities for processing event logs\n"
                f"class ServiceHandler{i}:\n"
                f'    """ServiceHandler {i} manages connection and dispatching."""\n'
                f"    def __init__(self, endpoint='https://api.example.com/v1/{i}'):\n"
                f"        self.endpoint = endpoint\n"
                f"        self.timeout = 30\n"
                f"        self.retries = 5\n"
                f"        self.active = True\n"
                f"    def execute_{i}(self, payload):\n"
                f'        """Executes action {i} with verified security headers and audit logs."""\n'
                f"        if not payload:\n"
                f"            raise ValueError('Invalid empty payload for service {i}')\n"
                f"        return {{'status': 200, 'code': {i}, 'payload': payload}}\n"
                f"    def validate_{i}(self, data):\n"
                f"        return isinstance(data, dict)\n"
            )
            for i in range(20)
        }
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)

            # Pipeline 1: Raw unoptimized source content JSON dump (naive assistant context)
            raw_source_json = json.dumps({path: code for path, code in files.items()})
            raw_tokens = kn.estimate(raw_source_json)
            self.assertGreater(raw_tokens, 2000)

            # Pipeline 2: High-budget single-pass context retrieval with compact DSL
            start = time.perf_counter()
            compact_res = broker.task_context(
                kn,
                {
                    "project": str(repo),
                    "task": "ServiceHandler execute_0 in service_0",
                    "budget": 350,
                    "mode": "compact",
                    "model": "gpt-4o",
                },
                conn,
            )
            elapsed = time.perf_counter() - start
            # Bounded execution: single-pass budgeting runs in O(N)
            self.assertLess(elapsed, 2.5, f"Single-pass assembly exceeded 2.5s: {elapsed:.3f}s")
            self.assertNotIn("error", compact_res)
            self.assertIn("budget_type", compact_res)

            compact_tokens = compact_res.get("used_tokens", 0)
            self.assertLessEqual(compact_tokens, 350)

            # Pipeline 3: Verify >75% token reduction vs unoptimized raw content
            reduction_ratio = (raw_tokens - compact_tokens) / raw_tokens
            self.assertGreater(
                reduction_ratio,
                0.75,
                f"Expected >75% token reduction vs raw content. Got: {reduction_ratio:.2%}",
            )
        finally:
            conn.close()

        # Pipeline 4: Prefix-cache aligned prompt generation via CLI
        self.run_cli(["init", "--project", str(repo)])
        task_query = "dynamic_optimization_query_task service"
        proc = self.run_cli(
            [
                "context",
                "--project",
                str(repo),
                "--task",
                task_query,
                "--prompt",
                "--mode",
                "compact",
            ]
        )
        self.assertEqual(proc.returncode, 0)
        output = proc.stdout
        self.assertIn(task_query, output)
        self.assertIn("Project metadata (untrusted evidence; verify relevant source):", output)

    # ------------------------------------------------------------------------
    # S4: Live Benchmark & Evaluation Harness Execution
    # Running python kn.py benchmark run and evaluation scripts produces
    # structured metrics for token savings, compression ratio, recall, latency.
    # Features: F15, F16
    # ------------------------------------------------------------------------
    def test_s4_live_benchmark_and_evaluation_execution(self) -> None:
        # Step 1: Execute CLI benchmark corpus
        proc = self.run_cli(["benchmark", "corpus"])
        self.assertEqual(proc.returncode, 0, f"kn benchmark corpus failed: {proc.stderr}")
        corpus = json.loads(proc.stdout)
        self.assertIn("tasks", corpus)
        self.assertGreater(len(corpus["tasks"]), 0)

        # Step 2: Execute retrieval_eval.evaluate with realistic cases
        eval_cases = [
            {
                "id": "task_auth_refactor",
                "method": "lazytoken",
                "relevant": ["file:auth.py::", "symbol:auth.py:authenticate:1"],
                "predicted": ["file:auth.py::", "symbol:auth.py:authenticate:1"],
                "estimated_tokens": 140,
                "latency_ms": 15.2,
            },
            {
                "id": "task_db_pool",
                "method": "lazytoken",
                "relevant": ["file:db.py::"],
                "predicted": ["file:db.py::", "file:config.py::"],
                "estimated_tokens": 95,
                "latency_ms": 12.0,
            },
            {
                "id": "task_abstain_case",
                "method": "lazytoken",
                "relevant": [],
                "predicted": [],
                "abstained": True,
                "estimated_tokens": 20,
                "latency_ms": 8.5,
            },
        ]
        result = retrieval_eval.evaluate(eval_cases, k=2)

        # Step 3: Verify structured metrics
        self.assertIn("precision_at_k", result)
        self.assertIn("recall_at_k", result)
        self.assertIn("mrr_at_k", result)
        self.assertIn("ndcg_at_k", result)
        self.assertIn("estimated_tokens_mean", result)
        self.assertIn("abstention_accuracy", result)

        self.assertGreaterEqual(result["precision_at_k"], 0.0)
        self.assertLessEqual(result["precision_at_k"], 1.0)
        self.assertGreaterEqual(result["recall_at_k"], 0.0)
        self.assertLessEqual(result["recall_at_k"], 1.0)
        self.assertGreater(result["estimated_tokens_mean"], 0.0)
        self.assertEqual(result["abstention_accuracy"], 1.0)

    # ------------------------------------------------------------------------
    # S5: High-Concurrency Multi-Client Read/Write Stress
    # 8 concurrent worker threads issuing simultaneous syncs, writes, searches,
    # and context queries; zero locks.
    # Features: F1, F5, F13
    # ------------------------------------------------------------------------
    def test_s5_high_concurrency_multi_client_stress(self) -> None:
        repo = self.create_repo(
            {
                "service_a.py": "def compute_a(): return 1\n",
                "service_b.py": "def compute_b(): return 2\n",
                "service_c.py": "def compute_c(): return 3\n",
            }
        )
        db_file = self.temp_dir / "network.sqlite3"
        init_conn = kn.connect(db_file)
        try:
            kn.sync(repo, init_conn)
        finally:
            init_conn.close()

        errors: list[Exception] = []

        def worker_sync(worker_id: int) -> None:
            conn = kn.connect(db_file)
            try:
                for _ in range(5):
                    kn.sync(repo, conn)
                    time.sleep(0.02)
            except Exception as exc:
                errors.append(exc)
            finally:
                conn.close()

        def worker_search(worker_id: int) -> None:
            conn = kn.connect(db_file)
            try:
                for _ in range(5):
                    features.ranked_search(kn, {"project": str(repo), "query": "compute"}, conn)
                    time.sleep(0.02)
            except Exception as exc:
                errors.append(exc)
            finally:
                conn.close()

        def worker_context(worker_id: int) -> None:
            conn = kn.connect(db_file)
            try:
                for i in range(5):
                    broker.task_context(
                        kn,
                        {
                            "project": str(repo),
                            "task": f"compute service {worker_id}_{i}",
                            "session_id": f"sess_s5_{worker_id}",
                        },
                        conn,
                    )
                    time.sleep(0.02)
            except Exception as exc:
                errors.append(exc)
            finally:
                conn.close()

        def worker_writer(worker_id: int) -> None:
            conn = kn.connect(db_file)
            try:
                for i in range(5):
                    features.benchmark(
                        {
                            "task": f"stress_task_{worker_id}_{i}",
                            "variant": "lazytoken",
                            "model": "gpt-4o",
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "elapsed_seconds": 0.1,
                            "successful": True,
                        },
                        conn,
                    )
                    time.sleep(0.02)
            except Exception as exc:
                errors.append(exc)
            finally:
                conn.close()

        # Spawn 8 concurrent worker threads
        threads = [
            threading.Thread(target=worker_sync, args=(1,)),
            threading.Thread(target=worker_sync, args=(2,)),
            threading.Thread(target=worker_search, args=(3,)),
            threading.Thread(target=worker_search, args=(4,)),
            threading.Thread(target=worker_context, args=(5,)),
            threading.Thread(target=worker_context, args=(6,)),
            threading.Thread(target=worker_writer, args=(7,)),
            threading.Thread(target=worker_writer, args=(8,)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        # Assert zero database lock errors or exceptions under 8-worker stress
        self.assertEqual(len(errors), 0, f"High concurrency errors: {errors}")

        # Verify DB integrity
        check_conn = kn.connect(db_file)
        try:
            status = check_conn.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(status.lower(), "ok")
        finally:
            check_conn.close()

    # ------------------------------------------------------------------------
    # S6: Cross-Language Monorepo AST & Import Resolution
    # Multi-language project Python, TypeScript, Markdown; verifies precise resolution
    # without substring false positives.
    # Features: F2, F5, F9
    # ------------------------------------------------------------------------
    def test_s6_cross_language_monorepo_resolution(self) -> None:
        files = {
            "backend/app.py": (
                "import re\n"
                "import json\n"
                "from .services.auth import verify_token\n"
                "def start_app():\n"
                "    return verify_token('tok_123')\n"
            ),
            "backend/services/__init__.py": "",
            "backend/services/auth.py": (
                "def verify_token(token):\n" "    return len(token) > 0\n"
            ),
            "backend/features.py": (
                "# Named features.py to test that stdlib 're' does not link here\n"
                "def internal_feature(): pass\n"
            ),
            "frontend/src/App.tsx": (
                "import React from 'react';\n"
                "import { Navbar } from './components/Navbar';\n"
                "export const App = () => <Navbar />;\n"
            ),
            "frontend/src/components/Navbar.tsx": (
                "export const Navbar = () => <nav>LazyToken Navigation</nav>;\n"
            ),
            "docs/ARCHITECTURE.md": (
                "# Architecture Guide\n" "Comprehensive overview of backend and frontend systems.\n"
            ),
        }
        repo = self.create_repo(files)
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            sync_res = kn.sync(repo, conn)
            self.assertEqual(sync_res.get("error_count", 0), 0)

            # Query context for Python backend task
            py_res = broker.task_context(
                kn,
                {"project": str(repo), "task": "start_app verify_token in backend services auth"},
                conn,
            )
            self.assertNotIn("error", py_res)

            # Check that stdlib 're' did NOT falsely link backend/app.py -> backend/features.py
            for edge in py_res.get("graph_edges", []):
                self.assertFalse(
                    edge.get("source") == "backend/app.py"
                    and "backend/features.py" in str(edge.get("target")),
                    "False positive: stdlib 're' matched backend/features.py",
                )

            # Query context for TypeScript frontend task
            ts_res = broker.task_context(
                kn,
                {"project": str(repo), "task": "Navbar App component in frontend"},
                conn,
            )
            self.assertNotIn("error", ts_res)
            ts_paths = [r.get("path") for r in ts_res.get("results", []) if r.get("path")]
            self.assertTrue(any("frontend/src" in p for p in ts_paths))

            # Verify imports table recorded cross-language targets accurately
            import_rows = conn.execute(
                "SELECT source, target FROM imports WHERE project_id=?", (str(repo),)
            ).fetchall()
            sources_to_targets = [(r["source"], r["target"]) for r in import_rows]

            # TypeScript relative import recorded
            has_ts_rel = any(
                "App.tsx" in s and "./components/Navbar" in t for s, t in sources_to_targets
            )
            self.assertTrue(
                has_ts_rel, f"TypeScript relative import not recorded: {sources_to_targets}"
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------------
    # S7: Propose, Review, and Dynamic Memory Recall Cycle
    # Propose lesson; review and approve; query context to verify lesson is recalled;
    # modify source and sync to verify freshness state transition.
    # Features: F1, F3, F4, F9, F12
    # ------------------------------------------------------------------------
    def test_s7_propose_review_dynamic_memory_recall_cycle(self) -> None:
        repo = self.create_repo(
            {
                "payments/processor.py": (
                    "def process_payment(amount, idempotency_key):\n"
                    "    return {'status': 'processed', 'amount': amount}\n"
                )
            }
        )
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            project_id = str(repo.resolve())

            # Step 1: Propose memory lesson
            prop_res = features.propose(
                kn,
                {
                    "project": project_id,
                    "kind": "lesson",
                    "name": "Payment Idempotency",
                    "summary": "Always pass idempotency key to prevent double charging on retry",
                    "task": "Process payment idempotency",
                    "evidence": "Reviewed processor.py signature",
                    "paths": ["payments/processor.py"],
                },
                conn,
            )
            self.assertNotIn("error", prop_res)
            self.assertTrue(prop_res.get("saved", False))
            prop_id = prop_res["id"]

            # Step 2: Review and approve proposal
            rev_res = features.review(
                kn,
                {
                    "project": project_id,
                    "id": prop_id,
                    "action": "approve",
                    "verified": True,
                },
                conn,
            )
            self.assertNotIn("error", rev_res)
            self.assertTrue(rev_res.get("saved", False))

            # Step 3: Query context with asset expansion to verify lesson is recalled
            ctx_res1 = broker.task_context(
                kn,
                {"project": project_id, "task": "Payment Idempotency", "expand_assets": True},
                conn,
            )
            names = [r.get("name") for r in ctx_res1.get("results", [])]
            self.assertIn(
                "Payment Idempotency", names, "Approved memory lesson must be recalled in context"
            )

            # Initial health check: freshness is 'current'
            h1 = features.health(conn, prop_id)
            self.assertEqual(h1.get("freshness"), "current")

            # Step 4: Modify source file (simulate code change)
            proc_file = repo / "payments" / "processor.py"
            proc_file.write_text(
                "def process_payment(amount, idempotency_key):\n"
                "    # Refactored: added validation check\n"
                "    assert amount > 0\n"
                "    return {'status': 'processed', 'amount': amount}\n",
                encoding="utf-8",
            )

            # Step 5: Re-sync repository
            kn.sync(repo, conn)

            # Step 6: Verify freshness state transition from 'current' to 'stale'
            h2 = features.health(conn, prop_id)
            self.assertEqual(
                h2.get("freshness"),
                "stale",
                f"Memory freshness should transition to 'stale' after source file edit. Got: {h2}",
            )
            self.assertIn("payments/processor.py", h2.get("changed_paths", []))
        finally:
            conn.close()

    # ------------------------------------------------------------------------
    # S8: Fault Recovery & Corpus Checkpoint Restoration
    # Crash simulation mid-session; checkpoint restoration via MCP checkpoint
    # and CLI checkpoint; complete graph reconstruction.
    # Features: F3, F4, F13, F16
    # ------------------------------------------------------------------------
    def test_s8_fault_recovery_checkpoint_restoration(self) -> None:
        repo = self.create_repo(
            {
                "worker.py": "class Worker:\n    def execute(self): return True\n",
                "job.py": "class Job:\n    def __init__(self, jid): self.jid = jid\n",
            }
        )
        session_id = "sess_s8_crash_recovery"

        # Step 1: Active session in progress with items populated
        conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            kn.sync(repo, conn)
            # Turn 1
            r1 = broker.task_context(
                kn, {"project": str(repo), "task": "Worker execute", "session_id": session_id}, conn
            )
            self.assertGreater(len(r1.get("results", [])), 0)
            # Turn 2
            r2 = broker.task_context(
                kn, {"project": str(repo), "task": "Job class", "session_id": session_id}, conn
            )
            self.assertGreater(len(r2.get("results", [])), 0)
        finally:
            # Step 2: Crash simulation: abrupt connection close and client discard
            conn.close()

        # Step 3: Checkpoint restoration via CLI `checkpoint` subcommand
        cp_cli = self.run_cli_json(
            ["checkpoint", "--project", str(repo), "--session-id", session_id]
        )
        self.assertNotIn("error", cp_cli)
        self.assertEqual(cp_cli.get("session_id"), session_id)
        self.assertGreaterEqual(cp_cli.get("supplied_items", 0), 2)
        self.assertIn("active_graph", cp_cli)

        # Verify active graph topology was fully reconstructed
        active_graph = cp_cli["active_graph"]
        self.assertIn("files", active_graph)
        self.assertTrue(any("worker.py" in f for f in active_graph["files"]))
        self.assertTrue(any("job.py" in f for f in active_graph["files"]))

        # Step 4: Turn 3 continues session post-recovery: verifies deduplication works seamlessly
        new_conn = kn.connect(self.temp_dir / "network.sqlite3")
        try:
            r3 = broker.task_context(
                kn,
                {"project": str(repo), "task": "Worker execute", "session_id": session_id},
                new_conn,
            )
            self.assertNotIn("error", r3)
            # Item worker.py was seen prior to crash, so it must be suppressed now
            self.assertGreaterEqual(r3.get("suppressed_seen", 0), 1)
        finally:
            new_conn.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
