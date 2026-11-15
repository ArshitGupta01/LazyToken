"""Comprehensive tests for AST code intelligence, impact analysis, skipped files tracking, and secret hardening."""

import json
from pathlib import Path
import tempfile
import unittest

from benchmark.graph_ablation import run_ablation
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
        call_tuples = [(c["caller_symbol"], c["callee_name"]) for c in calls]
        self.assertIn(("DataProcessor.process_records", "validate"), call_tuples)
        self.assertIn(("DataProcessor.process_records", "save_data"), call_tuples)

    def test_nested_function_calls_not_attributed_to_enclosing(self):
        """F2: Nested functions must attribute calls to inner, never to outer."""
        code = """def outer_controller():
    def inner_helper():
        delete_account()
    step_one()
"""
        calls = source_index.python_calls(code)
        outer_calls = [c["callee_name"] for c in calls if c["caller_symbol"] == "outer_controller"]
        inner_calls = [
            c["callee_name"]
            for c in calls
            if c["caller_symbol"] in ("outer_controller.inner_helper", "inner_helper")
        ]

        self.assertIn("step_one", outer_calls)
        self.assertNotIn(
            "delete_account",
            outer_calls,
            "delete_account inside inner_helper must NOT be attributed to outer_controller",
        )
        self.assertIn("delete_account", inner_calls)

    def test_duplicate_method_name_disambiguation(self):
        """F1: Impact analysis must resolve exact qualified symbol calls and not cross-match unrelated classes."""
        repo = self.root / "repo_disambig"
        repo.mkdir()
        (repo / "user_svc.py").write_text(
            "class UserService:\n"
            "    def delete(self, user_id):\n"
            "        return True\n"
            "    def handle_request(self, uid):\n"
            "        return self.delete(uid)\n",
            encoding="utf-8",
        )
        (repo / "file_svc.py").write_text(
            "class FileService:\n"
            "    def delete(self, path):\n"
            "        return True\n"
            "    def cleanup(self):\n"
            "        return self.delete('/tmp')\n",
            encoding="utf-8",
        )
        (repo / "cache_svc.py").write_text(
            "class CacheService:\n"
            "    def delete(self, key):\n"
            "        return True\n"
            "    def evict(self):\n"
            "        return self.delete('k')\n",
            encoding="utf-8",
        )
        kn.sync(repo, self.db)
        project = repo.name

        # Query UserService.delete
        res = features.impact_analysis(
            kn, {"project": project, "target": "UserService.delete"}, self.db
        )
        self.assertNotIn("error", res)
        self.assertEqual(res["target"], "UserService.delete")
        self.assertEqual(res["blast_radius"], "low")
        self.assertEqual(res["inbound_call_count"], 1)

        caller_symbols = [c["caller_symbol"] for c in res["inbound_callers"]]
        caller_files = [c["caller_file"] for c in res["inbound_callers"]]
        self.assertIn("UserService.handle_request", caller_symbols)
        self.assertIn("user_svc.py", caller_files)

        # Unrelated services must NOT be in inbound callers
        self.assertNotIn("FileService.cleanup", caller_symbols)
        self.assertNotIn("CacheService.evict", caller_symbols)
        self.assertNotIn("file_svc.py", caller_files)
        self.assertNotIn("cache_svc.py", caller_files)

    def test_no_static_callers_detected_guidance(self):
        """F3: When 0 callers are detected, system must warn about dynamic dispatch instead of claiming safe removal."""
        repo = self.root / "repo_zero"
        repo.mkdir()
        (repo / "route.py").write_text(
            "def on_user_signup(event):\n    return event\n", encoding="utf-8"
        )
        kn.sync(repo, self.db)
        project = repo.name

        res = features.impact_analysis(
            kn, {"project": project, "target": "on_user_signup"}, self.db
        )
        self.assertNotIn("error", res)
        self.assertEqual(res["blast_radius"], "no_static_callers_detected")
        self.assertIn("NO STATIC CALLERS DETECTED", res["ponytail_guidance"])
        self.assertIn("NOT evidence of safe removal", res["ponytail_guidance"])
        self.assertIn("dynamically", res["ponytail_guidance"])
        self.assertTrue(any("Dynamic dispatch" in rule for rule in res["decision_ladder"]))

    def test_javascript_typescript_ast_class_methods(self):
        """F4: JavaScript/TypeScript symbol extraction parses classes, methods, types, and interfaces."""
        code = """export class StoreService {
    constructor() {}
    async delete(id) {
        return true;
    }
    static getInstance() {
        return null;
    }
}
export interface StoreConfig {
    host: string;
}
export type StoreMode = 'memory' | 'disk';
const calculateTotal = (items) => {
    return 100;
};
"""
        symbols = source_index.javascript_symbols(code)
        names = [s[0] for s in symbols]
        self.assertIn("StoreService", names)
        self.assertIn("StoreService.delete", names)
        self.assertIn("StoreService.getInstance", names)
        self.assertIn("StoreConfig", names)
        self.assertIn("StoreMode", names)
        self.assertIn("calculateTotal", names)

    def test_skipped_files_tracking_and_persistent_inventory(self):
        """F6: Skipped files inventory persists across syncs and tracks reasons."""
        repo = self.root / "repo_skip"
        repo.mkdir()
        (repo / "valid.py").write_text("def hello(): pass\n", encoding="utf-8")
        (repo / "large.py").write_bytes(b"A" * 1_000_005)
        (repo / "binary.py").write_bytes(b"hello\x00world")

        res1 = kn.sync(repo, self.db)
        self.assertEqual(res1["files"], 1)
        self.assertEqual(res1["skipped_count"], 2)
        reasons = {item["path"]: item["reason"] for item in res1["skipped"]}
        self.assertEqual(reasons.get("large.py"), "oversized")
        self.assertEqual(reasons.get("binary.py"), "binary")

        # Second sync with no changes should retain persistent inventory
        res2 = kn.sync(repo, self.db)
        self.assertEqual(res2["skipped_count"], 2)
        reasons2 = {item["path"]: item["reason"] for item in res2["skipped"]}
        self.assertEqual(reasons2.get("large.py"), "oversized")
        self.assertEqual(reasons2.get("binary.py"), "binary")

    def test_sensitive_path_never_indexed(self):
        """F7: Sensitive credential paths are never indexed into files, symbols, or FTS."""
        repo = self.root / "repo_sec"
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

        # Verify sensitive files are NOT in indexed files or symbols
        indexed_files = [r[0] for r in self.db.execute("SELECT path FROM files").fetchall()]
        self.assertNotIn(".env", indexed_files)
        self.assertNotIn("id_rsa", indexed_files)

        # .env inspection denied
        res_env = features.inspect_source(
            kn, {"project": project, "path": ".env", "start_line": 1, "end_line": 1}, self.db
        )
        self.assertIn("error", res_env)
        self.assertIn("sensitive credential pattern", res_env["error"])

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

    def test_rehydrate_in_task_context(self):
        repo = self.root / "repo_rehydrate"
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

    def test_graph_ablation_benchmark_runs_cleanly(self):
        """P0: Graph ablation benchmark runs and outputs valid evaluation telemetry."""
        results = run_ablation()
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertIn("Mode_A_Lexical", r["modes"])
            self.assertIn("Mode_B_Lexical_Memory", r["modes"])
            self.assertIn("Mode_C_Graph", r["modes"])
            self.assertIn("Mode_D_Full_Pipeline", r["modes"])
            self.assertTrue(r["modes"]["Mode_D_Full_Pipeline"]["caller_discovered"])

    def test_nested_attribution_lambdas_decorators_comprehensions(self):
        """LT-P0-002: Test decorators, default args, lambdas, and comprehensions ownership."""
        code = """@route_decorator(build_route())
def complex_controller(default_opt=get_default_val()):
    def inner_sync():
        sync_inner_call()
    async def inner_async():
        async_inner_call()
    fn_lambda = lambda: lambda_dangerous_call()
    filtered = [sanitize(x) for x in fetch_inputs()]
    direct_controller_call()
"""
        calls = source_index.python_calls(code)
        caller_map = {}
        for c in calls:
            caller_map.setdefault(c["caller_symbol"], []).append(c["callee_name"])

        # complex_controller direct calls
        outer_calls = caller_map.get("complex_controller", [])
        self.assertIn("direct_controller_call", outer_calls)
        self.assertIn("sanitize", outer_calls)
        self.assertIn("fetch_inputs", outer_calls)

        # Decorator and default argument calls must NOT belong to complex_controller
        self.assertNotIn("build_route", outer_calls)
        self.assertNotIn("route_decorator", outer_calls)
        self.assertNotIn("get_default_val", outer_calls)

        # Inner sync and async calls must NOT belong to complex_controller
        self.assertNotIn("sync_inner_call", outer_calls)
        self.assertNotIn("async_inner_call", outer_calls)

        # Lambda calls must belong to lambda scope, not outer directly
        self.assertNotIn("lambda_dangerous_call", outer_calls)
        lambda_callers = [k for k in caller_map if "<lambda>" in k]
        self.assertTrue(lambda_callers)
        self.assertIn("lambda_dangerous_call", caller_map[lambda_callers[0]])

        # Inner sync function calls
        inner_sync_calls = caller_map.get("complex_controller.inner_sync", [])
        self.assertIn("sync_inner_call", inner_sync_calls)

        # Inner async function calls
        inner_async_calls = caller_map.get("complex_controller.inner_async", [])
        self.assertIn("async_inner_call", inner_async_calls)

    def test_symbol_ids_and_resolution_evidence(self):
        """LT-P0-001 & LT-P0-003: Symbol IDs, resolution method, and safety telemetry."""
        repo = self.root / "repo_evidence"
        repo.mkdir()
        (repo / "service.py").write_text(
            "class OrderService:\n"
            "    def cancel(self, order_id):\n"
            "        return False\n"
            "    def process(self, order_id):\n"
            "        return self.cancel(order_id)\n",
            encoding="utf-8",
        )
        kn.sync(repo, self.db)
        project = repo.name

        res = features.impact_analysis(
            kn, {"project": project, "target": "OrderService.cancel"}, self.db
        )
        self.assertNotIn("error", res)
        self.assertEqual(res["target"], "OrderService.cancel")
        self.assertIn("uncertainty_notice", res)
        self.assertIn("evidence_breakdown", res)
        self.assertEqual(res["evidence_breakdown"]["confirmed_callers"], 1)

        caller = res["inbound_callers"][0]
        self.assertIn("caller_symbol_id", caller)
        self.assertIn("service.py", caller["caller_symbol_id"])
        self.assertEqual(caller["resolution_method"], "explicit_class")
        self.assertEqual(caller["state"], "resolved")

    def test_additional_secret_patterns_and_security_boundary_notice(self):
        """LT-P0-004: Expanded secret patterns and security boundary disclaimer."""
        repo = self.root / "repo_secrets_expanded"
        repo.mkdir()
        openai_dummy = "sk-" + "abcdefghijklmnopqrstuvwxyz1234567890"
        anthropic_dummy = "sk-ant-" + "api03-abcdefghijklmnopqrstuvwxyz1234567890"
        google_dummy = "AIza" + "SyD-1234567890abcdefghijklmnopqrst"
        slack_dummy = "xox" + "b-1234567890-abcdefghijklmnop"
        (repo / "api_keys.py").write_text(
            f'OPENAI = "{openai_dummy}"\n'
            f'ANTHROPIC = "{anthropic_dummy}"\n'
            f'GOOGLE = "{google_dummy}"\n'
            f'SLACK = "{slack_dummy}"\n',
            encoding="utf-8",
        )
        kn.sync(repo, self.db)
        project = repo.name

        res = features.inspect_source(
            kn, {"project": project, "path": "api_keys.py", "start_line": 1, "end_line": 4}, self.db
        )
        self.assertNotIn("error", res)
        for line in res["lines"]:
            self.assertEqual(line["text"], "[redacted: possible credential]")
        self.assertIn("not a universal security boundary", res["note"])

    def test_javascript_calls_and_ts_declarations(self):
        """LT-P1-101: JS/TS call extraction, abstract classes, enums, namespaces, and impact analysis."""
        repo = self.root / "repo_ts"
        repo.mkdir()
        (repo / "order.ts").write_text(
            'import { notifyUser } from "./notifier";\n'
            "export enum Status { PENDING, CANCELLED }\n"
            "export namespace OrderOps {\n"
            "    export interface Spec { id: string; }\n"
            "}\n"
            "export abstract class BaseService {\n"
            "    abstract cancel(id: string): boolean;\n"
            "}\n"
            "export class OrderService extends BaseService {\n"
            "    cancel(id: string): boolean {\n"
            "        return true;\n"
            "    }\n"
            "    async process(id: string): Promise<boolean> {\n"
            "        const res = this.cancel(id);\n"
            "        notifyUser(id);\n"
            "        return res;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        kn.sync(repo, self.db)
        project = str(repo.resolve())

        symbols = [
            r[0]
            for r in self.db.execute(
                "SELECT name FROM symbols WHERE project_id=?", (project,)
            ).fetchall()
        ]
        self.assertIn("Status", symbols)
        self.assertIn("OrderOps", symbols)
        self.assertIn("Spec", symbols)
        self.assertIn("BaseService", symbols)
        self.assertIn("OrderService", symbols)
        self.assertIn("OrderService.cancel", symbols)
        self.assertIn("OrderService.process", symbols)

        # Impact analysis on OrderService.cancel in TypeScript
        res = features.impact_analysis(
            kn, {"project": project, "target": "OrderService.cancel"}, self.db
        )
        self.assertNotIn("error", res)
        self.assertEqual(res["target"], "OrderService.cancel")
        self.assertEqual(res["inbound_call_count"], 1)
        caller = res["inbound_callers"][0]
        self.assertEqual(caller["caller_symbol"], "OrderService.process")
        self.assertEqual(caller["caller_file"], "order.ts")
        self.assertEqual(caller["resolution_method"], "explicit_class")
        self.assertEqual(caller["state"], "resolved")

    def test_skipped_files_pruning_on_disk_removal(self):
        """LT-P1-102: Deleting a skipped file on disk prunes it from the persistent inventory."""
        repo = self.root / "repo_skip_prune"
        repo.mkdir()
        large_file = repo / "temporary_large.py"
        large_file.write_bytes(b"B" * 1_000_005)
        (repo / "normal.py").write_text("def ok(): pass\n", encoding="utf-8")

        res1 = kn.sync(repo, self.db)
        self.assertEqual(res1["skipped_count"], 1)
        self.assertEqual(res1["skipped"][0]["path"], "temporary_large.py")

        # Delete the large file
        large_file.unlink()

        res2 = kn.sync(repo, self.db)
        self.assertEqual(res2["skipped_count"], 0)
        self.assertEqual(res2["skipped"], [])

    def test_dependencies_provenance_and_edge_kinds(self):
        """LT-P1-103: dependencies feature returns edge_kind and provenance metadata."""
        repo = self.root / "repo_dep_prov"
        repo.mkdir()
        (repo / "client.py").write_text(
            "from api_service import ApiService\nclass App: pass\n", encoding="utf-8"
        )
        (repo / "api_service.py").write_text("class ApiService:\n    pass\n", encoding="utf-8")
        kn.sync(repo, self.db)
        project = repo.name

        dep_res = features.dependencies(kn, {"project": project}, self.db)
        self.assertNotIn("error", dep_res)
        deps = dep_res["dependencies"]
        self.assertTrue(deps)
        match = [d for d in deps if d["source"] == "client.py"][0]
        self.assertEqual(match["edge_kind"], "imports")
        self.assertEqual(match["status"], "resolved")
        self.assertIn("provenance", match)
        self.assertEqual(match["provenance"]["source_file"], "client.py")


if __name__ == "__main__":
    unittest.main()
