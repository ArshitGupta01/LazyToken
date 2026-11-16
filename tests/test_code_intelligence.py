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
        self.assertEqual(caller["resolution_method"], "inferred_type")
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

    def test_super_call_resolves_to_parent_class(self):
        """M6 / F18: Verify AST super().method() resolves to parent class, not child."""
        code = """class BaseService:
    def execute(self, payload):
        return True

class CustomService(BaseService):
    def execute(self, payload):
        return super().execute(payload)
"""
        calls = source_index.python_calls(code)
        custom_calls = [
            c
            for c in calls
            if c["caller_symbol"] == "CustomService.execute" and c["callee_name"] == "execute"
        ]
        self.assertEqual(len(custom_calls), 1)
        c = custom_calls[0]
        self.assertEqual(c["receiver"], "super")
        self.assertEqual(c["resolved_callee"], "BaseService.execute")
        self.assertEqual(c["confidence"], "exact")
        self.assertEqual(c["resolution_method"], "super_resolution")

    def test_super_call_multi_level_inheritance(self):
        """M6 / F18: Multi-level inheritance resolution Grandparent -> Parent -> Child."""
        code = """class Grandparent:
    def init_state(self): pass

class Parent(Grandparent):
    def init_state(self):
        super().init_state()

class Child(Parent):
    def init_state(self):
        super().init_state()
"""
        calls = source_index.python_calls(code)
        parent_call = [
            c
            for c in calls
            if c["caller_symbol"] == "Parent.init_state" and c["callee_name"] == "init_state"
        ][0]
        child_call = [
            c
            for c in calls
            if c["caller_symbol"] == "Child.init_state" and c["callee_name"] == "init_state"
        ][0]
        self.assertEqual(parent_call["resolved_callee"], "Grandparent.init_state")
        self.assertEqual(child_call["resolved_callee"], "Parent.init_state")

    def test_super_call_inherited_method_unoverridden_in_parent(self):
        """M6 / F18: Inherited method not overridden in immediate parent resolves to ancestor."""
        code = """class Grandparent:
    def cleanup(self): pass

class Parent(Grandparent):
    pass

class Child(Parent):
    def cleanup(self):
        super().cleanup()
"""
        calls = source_index.python_calls(code)
        child_call = [
            c
            for c in calls
            if c["caller_symbol"] == "Child.cleanup" and c["callee_name"] == "cleanup"
        ][0]
        self.assertEqual(child_call["resolved_callee"], "Grandparent.cleanup")
        self.assertEqual(child_call["confidence"], "exact")
        self.assertEqual(child_call["resolution_method"], "super_resolution")

    def test_super_with_explicit_class_argument(self):
        """M6 / F18: Python 2/3 compatibility syntax super(Child, self).method()."""
        code = """class Base:
    def run(self): pass

class Child(Base):
    def run(self):
        super(Child, self).run()
"""
        calls = source_index.python_calls(code)
        child_call = [
            c for c in calls if c["caller_symbol"] == "Child.run" and c["callee_name"] == "run"
        ][0]
        self.assertEqual(child_call["resolved_callee"], "Base.run")
        self.assertEqual(child_call["confidence"], "exact")
        self.assertEqual(child_call["resolution_method"], "super_resolution")

    def test_super_unresolvable_base_graceful_fallback(self):
        """M6 / F18: Unresolvable/external bases degrade gracefully without false self-attribution."""
        code_ext = """from external_module import ExternalBase

class LocalService(ExternalBase):
    def process(self):
        super().process()
"""
        calls = source_index.python_calls(code_ext)
        call = [
            c
            for c in calls
            if c["caller_symbol"] == "LocalService.process" and c["callee_name"] == "process"
        ][0]
        self.assertEqual(call["resolved_callee"], "ExternalBase.process")
        self.assertEqual(call["confidence"], "inferred")
        self.assertEqual(call["resolution_method"], "super_resolution")

        code_dyn = """class Unknown(dynamic_func()):
    def process(self):
        super().process()
"""
        calls_dyn = source_index.python_calls(code_dyn)
        call_dyn = [
            c
            for c in calls_dyn
            if c["caller_symbol"] == "Unknown.process" and c["callee_name"] == "process"
        ][0]
        self.assertNotEqual(call_dyn["resolved_callee"], "Unknown.process")
        self.assertEqual(call_dyn["confidence"], "provisional")

    def test_super_impact_analysis_inbound_attribution(self):
        """M6 / F18: In synchronized repo, impact analysis on BaseService.process finds DerivedService."""
        repo = self.root / "repo_super_impact"
        repo.mkdir()
        (repo / "services.py").write_text(
            "class BaseService:\n"
            "    def process(self, x):\n"
            "        return x\n\n"
            "class DerivedService(BaseService):\n"
            "    def process(self, x):\n"
            "        return super().process(x)\n",
            encoding="utf-8",
        )
        kn.sync(repo, self.db)
        project = repo.name

        # Impact analysis on BaseService.process
        res = features.impact_analysis(
            kn, {"project": project, "target": "BaseService.process"}, self.db
        )
        self.assertNotIn("error", res)
        self.assertEqual(res["inbound_call_count"], 1)
        caller = res["inbound_callers"][0]
        self.assertEqual(caller["caller_symbol"], "DerivedService.process")
        self.assertEqual(caller["resolution_method"], "super_resolution")

        # DerivedService.process must NOT list itself as caller
        res_derived = features.impact_analysis(
            kn, {"project": project, "target": "DerivedService.process"}, self.db
        )
        self.assertNotIn("error", res_derived)
        derived_callers = [c["caller_symbol"] for c in res_derived["inbound_callers"]]
        self.assertNotIn("DerivedService.process", derived_callers)

    def test_attribute_inference_in_helper_methods(self):
        """M6: Class attributes assigned in helper methods like setup() resolve method calls."""
        code = """class AppWorker:
    def __init__(self):
        self.name = "worker"

    def setup(self):
        self.store = TokenStore()

    def execute(self):
        self.store.save()
"""
        calls = source_index.python_calls(code)
        exec_call = [
            c
            for c in calls
            if c["caller_symbol"] == "AppWorker.execute" and c["callee_name"] == "save"
        ][0]
        self.assertEqual(exec_call["receiver"], "self.store")
        self.assertEqual(exec_call["resolved_callee"], "TokenStore.save")
        self.assertEqual(exec_call["confidence"], "inferred")
        self.assertEqual(exec_call["resolution_method"], "inferred_type")

    def test_attribute_inference_from_class_level_annotations(self):
        """M6: Class-level AnnAssign annotations inform receiver types."""
        code = """class ServiceHandler:
    database: DatabaseClient
    cache: MemoryCache = None

    def handle_request(self):
        self.database.execute_query()
        self.cache.get_item()
"""
        calls = source_index.python_calls(code)
        h_calls = {
            c["callee_name"]: c
            for c in calls
            if c["caller_symbol"] == "ServiceHandler.handle_request"
        }
        self.assertEqual(
            h_calls["execute_query"]["resolved_callee"], "DatabaseClient.execute_query"
        )
        self.assertEqual(h_calls["execute_query"]["confidence"], "inferred")
        self.assertEqual(h_calls["execute_query"]["resolution_method"], "inferred_type")
        self.assertEqual(h_calls["get_item"]["resolved_callee"], "MemoryCache.get_item")
        self.assertEqual(h_calls["get_item"]["confidence"], "inferred")
        self.assertEqual(h_calls["get_item"]["resolution_method"], "inferred_type")

    def test_local_type_inference_from_parameter_annotations(self):
        """M6: Parameter type annotations in standalone and member functions resolve calls."""
        code = """def process_order(gateway: PaymentGateway, validator: OrderValidator):
    gateway.charge()
    validator.validate()
"""
        calls = source_index.python_calls(code)
        c_map = {c["callee_name"]: c for c in calls if c["caller_symbol"] == "process_order"}
        self.assertEqual(c_map["charge"]["resolved_callee"], "PaymentGateway.charge")
        self.assertEqual(c_map["charge"]["confidence"], "inferred")
        self.assertEqual(c_map["charge"]["resolution_method"], "inferred_type")
        self.assertEqual(c_map["validate"]["resolved_callee"], "OrderValidator.validate")
        self.assertEqual(c_map["validate"]["confidence"], "inferred")

    def test_local_variable_type_annotation_in_body(self):
        """M6: Type-annotated local variables inside function body resolve calls."""
        code = """def dispatch_task():
    client: APIClient = get_client()
    client.post_payload()
"""
        calls = source_index.python_calls(code)
        post_call = [
            c
            for c in calls
            if c["caller_symbol"] == "dispatch_task" and c["callee_name"] == "post_payload"
        ][0]
        self.assertEqual(post_call["resolved_callee"], "APIClient.post_payload")
        self.assertEqual(post_call["confidence"], "inferred")
        self.assertEqual(post_call["resolution_method"], "inferred_type")

    def test_javascript_calls_calibrated_confidence(self):
        """M6: JS/TS call extraction distinguishes syntactic, heuristic, and provisional confidence."""
        code = """import { sendAlert } from "./notifier";

export class UserController extends BaseController {
    async handle(id) {
        this.validate(id);
        super.handle(id);
        sendAlert(id);
        const obj = getDynamic();
        obj.customMethod();
    }
    validate(id) {}
}
"""
        calls = source_index.javascript_calls(code)
        c_map = {
            c["callee_name"]: c for c in calls if c["caller_symbol"] == "UserController.handle"
        }
        self.assertEqual(c_map["validate"]["resolved_callee"], "UserController.validate")
        self.assertEqual(c_map["validate"]["confidence"], "syntactic")
        self.assertEqual(c_map["validate"]["resolution_method"], "explicit_class")

        self.assertEqual(c_map["handle"]["resolved_callee"], "BaseController.handle")
        self.assertEqual(c_map["handle"]["confidence"], "syntactic")
        self.assertEqual(c_map["handle"]["resolution_method"], "super_parent_class")

        self.assertEqual(c_map["sendAlert"]["resolved_callee"], "sendAlert")
        self.assertEqual(c_map["sendAlert"]["confidence"], "syntactic")
        self.assertEqual(c_map["sendAlert"]["resolution_method"], "explicit_import")

        self.assertEqual(c_map["customMethod"]["confidence"], "provisional")
        self.assertEqual(c_map["customMethod"]["resolution_method"], "untyped_receiver")

    def test_javascript_builtin_globals_not_marked_exact_class(self):
        """M6: Built-in globals like Math, JSON, console are marked provisional/builtin, not exact."""
        code = """function compute() {
    Math.max(1, 2);
    JSON.parse("{}");
    console.log("ok");
}
"""
        calls = source_index.javascript_calls(code)
        for c in calls:
            self.assertNotEqual(c["confidence"], "exact")
            self.assertEqual(c["confidence"], "provisional")
            self.assertEqual(c["resolution_method"], "builtin")

    def test_language_capabilities_structure(self):
        """M6 / F19: Inspect canonical LANGUAGE_CAPABILITIES dictionary."""
        caps = kn.get_language_capabilities()
        self.assertIn("python", caps)
        self.assertEqual(caps["python"]["tier"], "ast")
        self.assertTrue(caps["python"]["features"]["super_resolution"])
        self.assertIn("typescript", caps)
        self.assertEqual(caps["typescript"]["tier"], "syntactic_regex")
        self.assertFalse(caps["typescript"]["features"]["super_resolution"])
        self.assertIn("kotlin", caps)
        self.assertEqual(caps["kotlin"]["tier"], "line_pattern")
        self.assertFalse(caps["kotlin"]["features"]["call_graph"])
        self.assertIn("document", caps)
        self.assertEqual(caps["document"]["tier"], "text_only")

    def test_language_capabilities_by_extension_lookup(self):
        """M6 / F19: Extension lookup via get_language_capabilities and language_for_file."""
        self.assertEqual(kn.get_language_capabilities(".py")["language"], "python")
        self.assertEqual(kn.get_language_capabilities("ts")["language"], "typescript")
        self.assertEqual(kn.get_language_capabilities(".go")["language"], "go")
        self.assertEqual(kn.get_language_capabilities(".md")["tier"], "text_only")
        self.assertEqual(kn.get_language_capabilities(".unknown")["tier"], "line_pattern")
        self.assertEqual(kn.language_for_file("app/main.py"), "python")
        self.assertEqual(kn.language_for_file("src/index.ts"), "typescript")
        self.assertEqual(kn.language_for_file("README.md"), "document")

    def test_sync_project_language_breakdown_telemetry(self):
        """M6 / F19: kn.sync() includes language_breakdown telemetry."""
        repo = self.root / "repo_lang_breakdown"
        repo.mkdir()
        (repo / "main.py").write_text("def run(): pass\n", encoding="utf-8")
        (repo / "helper.py").write_text("def help(): pass\n", encoding="utf-8")
        (repo / "app.ts").write_text("export class App {}\n", encoding="utf-8")
        (repo / "notes.md").write_text("# Notes\n", encoding="utf-8")
        res = kn.sync(repo, self.db)
        self.assertIn("language_breakdown", res)
        b = res["language_breakdown"]
        self.assertEqual(b["python"]["files"], 2)
        self.assertEqual(b["python"]["tier"], "ast")
        self.assertEqual(b["typescript"]["files"], 1)
        self.assertEqual(b["typescript"]["tier"], "syntactic_regex")
        self.assertEqual(b["document"]["files"], 1)
        self.assertEqual(b["document"]["tier"], "text_only")

    def test_cli_capabilities_command(self):
        """M6 / F19: python kn.py capabilities CLI command supports json, table, text."""
        import subprocess
        import sys

        res_json = subprocess.run(
            [sys.executable, str(Path(kn.__file__)), "capabilities", "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(res_json.stdout)
        self.assertIn("python", data)
        self.assertEqual(data["python"]["tier"], "ast")

        res_table = subprocess.run(
            [sys.executable, str(Path(kn.__file__)), "capabilities", "python", "--format", "table"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("python", res_table.stdout)
        self.assertIn("ast", res_table.stdout)


class ExtractionRegressionTests(unittest.TestCase):
    def test_python_conditional_definitions_and_method_order(self):
        code = """if True:
    def hidden():
        helper()
try:
    pass
except Exception:
    def recovered():
        helper()
class G:
    def run(self): pass
class E(G): pass
class F:
    def run(self): pass
class B(E): pass
class C(F): pass
class D(B, C):
    def run(self): super().run()
"""
        symbols = source_index.python_symbols(code)
        self.assertIn(("hidden", 2), symbols)
        self.assertIn(("recovered", 7), symbols)
        calls = source_index.python_calls(code)
        self.assertTrue(
            any(c["caller_symbol"] == "recovered" and c["callee_name"] == "helper" for c in calls)
        )
        self.assertEqual(
            next(c for c in calls if c["caller_symbol"] == "D.run")["resolved_callee"], "G.run"
        )

    def test_javascript_inline_calls_comments_and_annotated_arrow(self):
        code = """function f() { helper(); }
function g() {
/*
ghost();
*/
real();
}
export const b: () => void = () => {};
"""
        calls = source_index.javascript_calls(code)
        self.assertTrue(
            any(
                c["caller_symbol"] == "f" and c["callee_name"] == "helper" and c["caller_line"] == 1
                for c in calls
            )
        )
        self.assertTrue(
            any(
                c["caller_symbol"] == "g" and c["callee_name"] == "real" and c["caller_line"] == 2
                for c in calls
            )
        )
        self.assertFalse(any(c["callee_name"] == "ghost" for c in calls))
        self.assertIn(("b", 8), source_index.javascript_symbols(code))

    def test_python_inherited_and_shadowed_calls_are_not_exact(self):
        code = """import os
class Base:
    def run(self): pass
class Child(Base):
    def go(self, os):
        self.run()
        os.remove('x')
"""
        calls = source_index.python_calls(code)
        inherited = next(c for c in calls if c["callee_name"] == "run")
        shadowed = next(c for c in calls if c["callee_name"] == "remove")
        self.assertEqual(inherited["resolved_callee"], "Base.run")
        self.assertNotEqual(inherited["confidence"], "exact")
        self.assertNotEqual(shadowed["resolution_method"], "explicit_import")

    def test_javascript_concise_recursive_imports_and_comment_symbols(self):
        code = """import defaultThing, {x as y} from './mod.js';
/*
function phantom() {}
*/
const f = () => helper();
function recur(n) { if (n) recur(n - 1); y(); defaultThing.run(); }
class A { one() { return two(); } }
"""
        symbols = source_index.javascript_symbols(code)
        self.assertNotIn(("phantom", 3), symbols)
        self.assertIn(("A.one", 7), symbols)
        calls = source_index.javascript_calls(code)
        self.assertTrue(
            any(c["caller_symbol"] == "f" and c["callee_name"] == "helper" for c in calls)
        )
        self.assertTrue(
            any(c["caller_symbol"] == "recur" and c["callee_name"] == "recur" for c in calls)
        )
        for name in ("y", "run"):
            self.assertTrue(
                any(
                    c["caller_symbol"] == "recur"
                    and c["callee_name"] == name
                    and c["resolution_method"] == "explicit_import"
                    for c in calls
                )
            )


if __name__ == "__main__":
    unittest.main()
