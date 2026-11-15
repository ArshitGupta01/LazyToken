"""Tests for AST code intelligence, impact analysis, skipped files tracking, and secret hardening."""

import json
from pathlib import Path
import tempfile
import unittest

import broker
import features
import kn
import source_index


class CodeIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db = kn.connect(self.root / "network.sqlite3")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_ast_python_symbols_and_calls(self):
        code = """class DataProcessor:
    def process_records(self, records):
        self.validate(records)
        save_data(records)

    def validate(self, records):
        if not records:
            raise ValueError("empty")

def save_data(data):
    return len(data)
"""
        symbols = source_index.python_symbols(code)
        symbol_names = [s[0] for s in symbols]
        self.assertIn("DataProcessor", symbol_names)
        self.assertIn("process_records", symbol_names)
        self.assertIn("DataProcessor.process_records", symbol_names)
        self.assertIn("validate", symbol_names)
        self.assertIn("DataProcessor.validate", symbol_names)
        self.assertIn("save_data", symbol_names)

        calls = source_index.python_calls(code)
        # Check call extraction
        call_tuples = [(c[0], c[1]) for c in calls]
        self.assertIn(("DataProcessor.process_records", "validate"), call_tuples)
        self.assertIn(("DataProcessor.process_records", "save_data"), call_tuples)
        self.assertIn(("process_records", "validate"), call_tuples)

    def test_ast_javascript_symbols(self):
        code = """export class StoreService {
    constructor() {}
}
export async function fetchCatalog(query) {
    return [];
}
const calculateTotal = (items) => {
    return 100;
};
"""
        symbols = source_index.javascript_symbols(code)
        names = [s[0] for s in symbols]
        self.assertIn("StoreService", names)
        self.assertIn("fetchCatalog", names)
        self.assertIn("calculateTotal", names)

    def test_skipped_files_tracking(self):
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "valid.py").write_text("def hello(): pass\n", encoding="utf-8")
        # Oversized file > 1MB
        (repo / "large.py").write_bytes(b"A" * 1_000_005)
        # Binary file with null byte
        (repo / "binary.py").write_bytes(b"hello\x00world")

        res = kn.sync(repo, self.db)
        self.assertEqual(res["files"], 1)
        self.assertEqual(res["skipped_count"], 2)
        skipped_reasons = {item["path"]: item["reason"] for item in res["skipped"]}
        self.assertEqual(skipped_reasons.get("large.py"), "oversized")
        self.assertEqual(skipped_reasons.get("binary.py"), "binary")

        # Verify DB records
        rows = self.db.execute("SELECT path, reason FROM index_skipped_files").fetchall()
        db_reasons = {r[0]: r[1] for r in rows}
        self.assertEqual(db_reasons.get("large.py"), "oversized")
        self.assertEqual(db_reasons.get("binary.py"), "binary")

    def test_sensitive_path_denial_and_secret_redaction(self):
        repo = self.root / "repo"
        repo.mkdir()
        (repo / ".env").write_text("API_KEY=secret_key_value\n", encoding="utf-8")
        (repo / "id_rsa").write_text("PRIVATE_KEY_BYTES\n", encoding="utf-8")
        (repo / "service.py").write_text(
            'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
            'GH_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyzAB"\n'
            'AUTH_HEADER = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"\n'
            "def safe_fn():\n"
            "    return True\n",
            encoding="utf-8",
        )
        kn.sync(repo, self.db)
        project = repo.name

        # .env inspection denied
        res_env = features.inspect_source(
            kn, {"project": project, "path": ".env", "start_line": 1, "end_line": 1}, self.db
        )
        self.assertIn("error", res_env)
        self.assertIn("sensitive credential pattern", res_env["error"])

        # id_rsa inspection denied
        res_key = features.inspect_source(
            kn, {"project": project, "path": "id_rsa", "start_line": 1, "end_line": 1}, self.db
        )
        self.assertIn("error", res_key)
        self.assertIn("sensitive credential pattern", res_key["error"])

        # Multi-pattern secret scanner redacts keys in normal code
        res_service = features.inspect_source(
            kn, {"project": project, "path": "service.py", "start_line": 1, "end_line": 5}, self.db
        )
        self.assertNotIn("error", res_service)
        lines = [item["text"] for item in res_service["lines"]]
        self.assertEqual(lines[0], "[redacted: possible credential]")
        self.assertEqual(lines[1], "[redacted: possible credential]")
        self.assertEqual(lines[2], "[redacted: possible credential]")
        self.assertEqual(lines[3], "def safe_fn():")

    def test_relational_impact_analysis_and_ponytail_advice(self):
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "core.py").write_text(
            "class Engine:\n" "    def execute(self, task):\n" "        return task\n",
            encoding="utf-8",
        )
        (repo / "client1.py").write_text(
            "from core import Engine\n"
            "def run_worker1():\n"
            "    e = Engine()\n"
            "    return e.execute('task1')\n",
            encoding="utf-8",
        )
        (repo / "client2.py").write_text(
            "from core import Engine\n"
            "def run_worker2():\n"
            "    e = Engine()\n"
            "    return e.execute('task2')\n",
            encoding="utf-8",
        )
        kn.sync(repo, self.db)
        project = repo.name

        # Impact analysis on symbol 'Engine.execute'
        impact = features.impact_analysis(
            kn, {"project": project, "target": "Engine.execute"}, self.db
        )
        self.assertNotIn("error", impact)
        self.assertEqual(impact["target"], "Engine.execute")
        self.assertEqual(impact["target_type"], "symbol")
        self.assertEqual(impact["blast_radius"], "medium")
        self.assertEqual(impact["inbound_call_count"], 2)
        self.assertIn("client1.py", impact["affected_files"])
        self.assertIn("client2.py", impact["affected_files"])
        self.assertIn("Ponytail", impact["ponytail_guidance"])
        self.assertTrue(len(impact["decision_ladder"]) >= 4)

        # Impact analysis via direct MCP call action
        mcp_res = kn.call("inspect_impact", {"project": project, "target": "core.py"}, self.db)
        self.assertNotIn("error", mcp_res)
        self.assertEqual(mcp_res["target_type"], "file")
        self.assertIn("client1.py", mcp_res["affected_files"])
        self.assertIn("client2.py", mcp_res["affected_files"])

    def test_rehydrate_in_task_context(self):
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "auth.py").write_text(
            "def validate_session(token):\n    return True\n", encoding="utf-8"
        )
        kn.sync(repo, self.db)
        project = repo.name

        # Turn 1: Retrieve
        turn1 = broker.task_context(
            kn,
            {"project": project, "task": "validate_session auth", "session_id": "test-session"},
            self.db,
        )
        self.assertTrue(turn1["results"])

        # Turn 2: Suppressed
        turn2 = broker.task_context(
            kn,
            {"project": project, "task": "validate_session auth", "session_id": "test-session"},
            self.db,
        )
        self.assertEqual(turn2["results"], [])
        self.assertGreater(turn2["suppressed_seen"], 0)

        # Turn 3: Rehydrated
        turn3 = broker.task_context(
            kn,
            {
                "project": project,
                "task": "validate_session auth",
                "session_id": "test-session",
                "rehydrate": True,
            },
            self.db,
        )
        self.assertTrue(turn3["results"])
        self.assertTrue(turn3.get("rehydrated"))


if __name__ == "__main__":
    unittest.main()
