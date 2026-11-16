"""Comprehensive unit tests for 5-mode empirical retrieval ablation suite (LT-P1-201 / F17)."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
from benchmark import graph_ablation
from benchmark.graph_ablation import (
    MODES,
    MODE_DESCRIPTIONS,
    plain_grep_search,
    lexical_search_no_graph,
    lexical_search_with_graph,
    verified_memory_no_graph,
    full_lazytoken_pipeline,
    run_ablation,
    format_comparative_table,
    generate_markdown_report,
)
import kn
import features
import retrieval_eval


class TestRetrievalAblation5Modes(unittest.TestCase):
    """Unit tests validating the 5-mode empirical retrieval ablation suite."""

    def test_all_five_modes_registered_and_configured(self):
        """Verify that all 5 required ablation modes are registered and documented."""
        expected_modes = [
            "grep_baseline",
            "lexical_no_graph",
            "lexical_with_graph",
            "verified_memory_no_graph",
            "full_pipeline",
        ]
        self.assertEqual(MODES, expected_modes)
        for mode in expected_modes:
            self.assertIn(mode, MODE_DESCRIPTIONS)
            self.assertIsInstance(MODE_DESCRIPTIONS[mode], str)
            self.assertTrue(len(MODE_DESCRIPTIONS[mode]) > 10)

    def test_mode1_plain_grep_discovers_raw_text_without_sqlite(self):
        """Mode 1: Verify raw file grep scans disk without SQLite index or database."""
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            # Create raw source files on disk
            (repo_root / "payment_gateway.py").write_text(
                "class PaymentGateway:\n"
                "    def process_charge(self, amount: int) -> bool:\n"
                "        return amount > 0\n",
                encoding="utf-8",
            )
            (repo_root / "order_service.py").write_text(
                "from payment_gateway import PaymentGateway\n"
                "class OrderService:\n"
                "    def checkout(self, total: int):\n"
                "        gw = PaymentGateway()\n"
                "        return gw.process_charge(total)\n",
                encoding="utf-8",
            )
            (repo_root / "unrelated.py").write_text(
                "def render_template():\n    return '<html></html>'\n",
                encoding="utf-8",
            )

            # 1. Search matching PaymentGateway process_charge
            res = plain_grep_search(repo_root, "process_charge PaymentGateway charge")
            self.assertEqual(res["method"], "grep_baseline")
            self.assertFalse(res["abstained"])
            retrieved = res["retrieved_files"]
            self.assertIn("payment_gateway.py", retrieved)
            self.assertIn("order_service.py", retrieved)
            self.assertNotIn("unrelated.py", retrieved)
            self.assertGreater(res["tokens"], 0)

            # 2. Search with stop words
            res_stopwords = plain_grep_search(repo_root, "the process_charge in a payment_gateway")
            self.assertIn("payment_gateway.py", res_stopwords["retrieved_files"])

            # 3. Search with non-matching query -> should abstain
            res_nomatch = plain_grep_search(repo_root, "xenon quasar zephyr")
            self.assertTrue(res_nomatch["abstained"])
            self.assertEqual(res_nomatch["retrieved_files"], [])
            self.assertEqual(res_nomatch["tokens"], 0)

            # 4. Search with empty/whitespace query -> should abstain
            res_empty = plain_grep_search(repo_root, "   ")
            self.assertTrue(res_empty["abstained"])
            self.assertEqual(res_empty["retrieved_files"], [])

    def test_mode2_lexical_no_graph_ranked_search(self):
        """Mode 2: Verify lexical search uses SQLite FTS without graph expansion."""
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            repo_root.mkdir()
            (repo_root / "crypto_auth.py").write_text(
                "def verify_signature(data: str, sig: str) -> bool:\n    return len(sig) == 64\n",
                encoding="utf-8",
            )
            db_path = Path(temp_dir) / "test.sqlite3"
            conn = kn.connect(db_path)
            try:
                kn.sync(repo_root, conn)
                res = lexical_search_no_graph(
                    kn, repo_root.name, "verify_signature crypto_auth", conn
                )
                self.assertEqual(res["method"], "lexical_no_graph")
                self.assertIn("crypto_auth.py", res["retrieved_files"])
                self.assertFalse(res["abstained"])
                self.assertGreater(res["tokens"], 0)

                # Non-matching query
                no_res = lexical_search_no_graph(kn, repo_root.name, "unmatched_symbol_xyz", conn)
                self.assertTrue(no_res["abstained"])
                self.assertEqual(no_res["retrieved_files"], [])
            finally:
                conn.close()

    def test_mode3_lexical_with_graph_caller_expansion(self):
        """Mode 3: Verify lexical + AST graph expansion discovers inbound callers."""
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            repo_root.mkdir()
            (repo_root / "vault.py").write_text(
                "class Vault:\n"
                "    def unlock(self, key: str) -> bool:\n"
                "        return key == 'secret'\n",
                encoding="utf-8",
            )
            (repo_root / "guard.py").write_text(
                "from vault import Vault\n"
                "class Guard:\n"
                "    def enter(self, key: str):\n"
                "        v = Vault()\n"
                "        return v.unlock(key)\n",
                encoding="utf-8",
            )
            db_path = Path(temp_dir) / "test.sqlite3"
            conn = kn.connect(db_path)
            try:
                kn.sync(repo_root, conn)
                res = lexical_search_with_graph(
                    kn, repo_root.name, "unlock Vault", "Vault.unlock", conn
                )
                self.assertEqual(res["method"], "lexical_with_graph")
                self.assertIn("vault.py", res["retrieved_files"])
                self.assertIn("guard.py", res["retrieved_files"])
                self.assertGreater(res["tokens"], 0)
            finally:
                conn.close()

    def test_mode4_verified_memory_no_graph(self):
        """Mode 4: Verify domain lessons retrieval without graph expansion."""
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            repo_root.mkdir()
            (repo_root / "billing.py").write_text(
                "def charge(amount: int):\n    return True\n",
                encoding="utf-8",
            )
            db_path = Path(temp_dir) / "test.sqlite3"
            conn = kn.connect(db_path)
            try:
                kn.sync(repo_root, conn)
                project = repo_root.name
                conn.execute(
                    "INSERT INTO assets(kind, scope, name, summary, created_at, project_id) "
                    "VALUES('lesson', 'global', 'Billing Contract', 'charge requires non-negative amount in billing.py', 1000, ?)",
                    (project,),
                )
                conn.commit()

                self.assertFalse(
                    verified_memory_no_graph(kn, project, "charge billing amount", conn)[
                        "has_lesson"
                    ]
                )
                proposal = features.propose(
                    kn,
                    {
                        "project": project,
                        "kind": "lesson",
                        "name": "Billing Contract",
                        "summary": "charge requires non-negative amount in billing.py",
                        "task": "charge billing amount",
                        "evidence": "fixture",
                        "paths": ["billing.py"],
                    },
                    conn,
                )
                self.assertNotIn("error", proposal)
                approved = features.review(
                    kn,
                    {
                        "project": project,
                        "id": proposal["id"],
                        "action": "approve",
                        "verified": True,
                    },
                    conn,
                )
                self.assertNotIn("error", approved)

                res = verified_memory_no_graph(kn, project, "charge billing amount", conn)
                self.assertEqual(res["method"], "verified_memory_no_graph")
                self.assertTrue(res["has_lesson"])
                self.assertIn("billing.py", res["retrieved_files"])
                self.assertFalse(res["abstained"])
                self.assertGreater(res["tokens"], 0)

                (repo_root / "billing.py").write_text(
                    "def charge(amount): return False\n", encoding="utf-8"
                )
                kn.sync(repo_root, conn)
                self.assertFalse(
                    verified_memory_no_graph(kn, project, "charge billing amount", conn)[
                        "has_lesson"
                    ]
                )

                # Unrelated query with no matching lesson
                res_nomatch = verified_memory_no_graph(
                    kn, project, "astronomy galaxies telescope", conn
                )
                self.assertTrue(res_nomatch["abstained"])
                self.assertEqual(res_nomatch["retrieved_files"], [])
            finally:
                conn.close()

    def test_mode5_full_lazytoken_pipeline(self):
        """Mode 5: Verify full unified pipeline with broker context and AST impact analysis."""
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            repo_root.mkdir()
            (repo_root / "service.py").write_text(
                "class Service:\n    def execute(self):\n        return True\n",
                encoding="utf-8",
            )
            (repo_root / "controller.py").write_text(
                "from service import Service\n"
                "def run():\n    s = Service()\n    return s.execute()\n",
                encoding="utf-8",
            )
            db_path = Path(temp_dir) / "test.sqlite3"
            conn = kn.connect(db_path)
            try:
                kn.sync(repo_root, conn)
                res = full_lazytoken_pipeline(
                    kn, repo_root.name, "execute Service run", "Service.execute", conn, budget=800
                )
                self.assertEqual(res["method"], "full_pipeline")
                self.assertIn("service.py", res["retrieved_files"])
                self.assertIn("controller.py", res["retrieved_files"])
                self.assertGreater(res["tokens"], 0)
                self.assertEqual(
                    res["tokens"],
                    kn.estimate(json.dumps(res["broker_context"], ensure_ascii=False))
                    + kn.estimate(json.dumps(res["impact"], ensure_ascii=False)),
                )
            finally:
                conn.close()

    def test_run_ablation_executes_all_5_modes(self):
        """Verify run_ablation executes all 5 modes across all benchmark scenarios."""
        results = run_ablation()
        self.assertEqual(len(results), 4)

        for r in results:
            self.assertIn("id", r)
            self.assertIn("name", r)
            self.assertIn("task", r)
            self.assertIn("target_symbol", r)
            self.assertIn("modes", r)
            modes = r["modes"]

            # Standard 5-mode keys
            for mode_key in MODES:
                self.assertIn(mode_key, modes)
                self.assertIsInstance(modes[mode_key]["tokens"], int)
                self.assertGreaterEqual(modes[mode_key]["tokens"], 0)
                self.assertIn("savings_vs_raw", modes[mode_key])

            # Numbered mode keys
            self.assertIn("Mode_1_Grep_Baseline", modes)
            self.assertIn("Mode_2_Lexical_No_Graph", modes)
            self.assertIn("Mode_3_Lexical_With_Graph", modes)
            self.assertIn("Mode_4_Verified_Memory_No_Graph", modes)
            self.assertIn("Mode_5_Full_Pipeline", modes)

            # Legacy mode keys for backward compatibility
            self.assertIn("Mode_A_Lexical", modes)
            self.assertIn("Mode_B_Lexical_Memory", modes)
            self.assertIn("Mode_C_Graph", modes)
            self.assertIn("Mode_D_Full_Pipeline", modes)

            # Graph & full pipeline must discover callers
            self.assertTrue(modes["full_pipeline"]["caller_discovered"])
            self.assertTrue(modes["Mode_D_Full_Pipeline"]["caller_discovered"])

    def test_retrieval_eval_metrics_across_5_modes(self):
        """Verify retrieval_eval computes valid standard IR metrics across all 5 modes."""
        results = run_ablation()
        eval_summary = results.eval_summary

        self.assertIn("k", eval_summary)
        self.assertEqual(eval_summary["k"], 5)
        self.assertIn("methods", eval_summary)
        methods = eval_summary["methods"]

        for mode_key in MODES:
            self.assertIn(mode_key, methods)
            m = methods[mode_key]
            self.assertEqual(m["cases"], 4)
            self.assertIsInstance(m["precision_at_k"], float)
            self.assertGreater(m["precision_at_k"], 0.0)
            self.assertIsInstance(m["recall_at_k"], float)
            self.assertGreater(m["recall_at_k"], 0.0)
            self.assertIsInstance(m["mrr_at_k"], float)
            self.assertGreater(m["mrr_at_k"], 0.0)
            self.assertIsInstance(m["ndcg_at_k"], float)
            self.assertGreater(m["ndcg_at_k"], 0.0)
            self.assertEqual(m["abstention_accuracy"], 1.0)
            self.assertGreater(m["estimated_tokens_mean"], 0)

        # Mode 3 (Graph) and Mode 5 (Full Pipeline) should outperform Mode 2 (Lexical) on MRR and Recall
        self.assertGreaterEqual(
            methods["lexical_with_graph"]["recall_at_k"], methods["lexical_no_graph"]["recall_at_k"]
        )
        self.assertGreaterEqual(
            methods["full_pipeline"]["recall_at_k"], methods["lexical_no_graph"]["recall_at_k"]
        )
        self.assertGreaterEqual(
            methods["full_pipeline"]["mrr_at_k"], methods["lexical_no_graph"]["mrr_at_k"]
        )

    def test_format_comparative_table_and_markdown_generation(self):
        """Verify table formatting and markdown ablation report generation."""
        results = run_ablation()
        table = format_comparative_table(results.eval_summary, results.raw_repo_tokens)
        self.assertIsInstance(table, str)
        self.assertIn("LazyToken 5-Mode Retrieval Ablation Evaluation (k=5)", table)
        for mode in MODES:
            self.assertIn(mode, table)
        self.assertIn("Precision@5", table)
        self.assertIn("Recall@5", table)
        self.assertIn("MRR@5", table)
        self.assertIn("NDCG@5", table)
        self.assertIn("Abstention", table)
        self.assertIn("Tokens", table)
        self.assertIn("Savings vs Raw", table)

        report = generate_markdown_report(results, results.eval_summary)
        self.assertIn("# LazyToken 5-Mode Empirical Retrieval Ablation Report", report)
        self.assertIn("## 1. Executive Summary & Comparative Matrix", report)
        self.assertIn("## 2. Standard IR Evaluation Metrics Across All 5 Modes", report)
        self.assertIn("## 3. Key Empirical Findings", report)
        self.assertIn("## 4. Detailed Per-Scenario Telemetry", report)
        for mode in MODES:
            self.assertIn(mode, report)

    def test_expanded_retrieval_cases_json_has_25_plus_cases(self):
        """Verify retrieval_cases.json has 25+ diverse cases covering all required domains."""
        cases_file = ROOT / "benchmark" / "retrieval_cases.json"
        self.assertTrue(cases_file.exists())
        data = json.loads(cases_file.read_text(encoding="utf-8-sig"))
        cases = data.get("cases", [])

        # 1. Size constraint: at least 25 cases
        self.assertGreaterEqual(len(cases), 25)

        # 2. Schema validity: every case has id, fixture, task, relevant
        case_ids = set()
        fixtures = set()
        for c in cases:
            self.assertIn("id", c)
            self.assertIn("fixture", c)
            self.assertIn("task", c)
            self.assertIn("relevant", c)
            self.assertNotIn(c["id"], case_ids, f"Duplicate case id: {c['id']}")
            case_ids.add(c["id"])
            fixtures.add(c["fixture"])

        # 3. Domain coverage
        self.assertIn("fixture_sessions", fixtures)
        self.assertIn("fixture_notebook", fixtures)
        self.assertIn("fixture_multicomponent", fixtures)

        # Must have cases covering session state, memory state, multi-component, and ablations
        has_session = any("session" in c["id"] for c in cases)
        has_memory = any("memory" in c["id"] for c in cases)
        has_multi = any("multi" in c["id"] for c in cases)
        has_ablation = any("ablation" in c["id"] for c in cases)
        has_nomatch = any("no-match" in c["id"] for c in cases)

        self.assertTrue(has_session, "Must include session state cases")
        self.assertTrue(has_memory, "Must include memory state cases")
        self.assertTrue(has_multi, "Must include multi-component cases")
        self.assertTrue(has_ablation, "Must include ablation cases")
        self.assertTrue(has_nomatch, "Must include abstention / no-match cases")


if __name__ == "__main__":
    unittest.main()
