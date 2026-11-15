import io
import json
import os
from pathlib import Path
import tempfile
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import kn
import frameworks
import diagnostics
from source_index import javascript_imports, python_imports
import watcher


class PonytailFixes(unittest.TestCase):
    def test_doctor_reports_malformed_integrity_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "release-manifest.json").write_text('{"files": []}')
            with (
                patch.dict(os.environ, {"KN_HOME": str(root / "data")}),
                patch("diagnostics.sys.frozen", True, create=True),
                patch("diagnostics.sys.executable", str(root / "LazyToken.exe")),
                patch("onboarding.diagnose", return_value={"clients": []}),
            ):
                result = diagnostics.report(kn)
            self.assertIn("manifest invalid", result["installation_integrity"])

    def test_malformed_inputs_return_errors_without_partial_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Auth.py").write_text("class Auth: pass")
            db = kn.connect(root / "fixture.sqlite3")
            try:
                kn.sync(root, db)
                project = str(root.resolve())
                self.assertIn("error", kn.feature_call("search", [], db))
                self.assertIn("error", kn.call("get_task_context", [], db))
                for limit in ("invalid", None, [], True, 1.5):
                    self.assertIn(
                        "error",
                        kn.feature_call(
                            "search", {"project": project, "query": "auth", "limit": limit}, db
                        ),
                    )
                self.assertIn(
                    "error",
                    kn.call(
                        "get_task_context", {"project": project, "task": "auth", "mode": []}, db
                    ),
                )
                self.assertIn("error", kn.feature_call("complete_task", {"attempts": []}, db))
                self.assertFalse(db.in_transaction)
            finally:
                db.close()

    def test_import_like_strings_and_comments_are_not_code(self):
        body = """const example = "import React from 'fake'";
// import x from 'comment';
import {real} from './real';
const lazy=import('./lazy');
object.import('not-a-module');
"""
        self.assertEqual(javascript_imports(body), ["./lazy", "./real"])
        self.assertEqual(python_imports('text = "import flask"\nimport sqlite3\n'), ["sqlite3"])

    def test_failed_mcp_request_rolls_back_and_does_not_reuse_request_id(self):
        with tempfile.TemporaryDirectory() as temp:
            db = kn.connect(Path(temp) / "fixture.sqlite3")
            try:
                request = (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {"name": "fixture"},
                        }
                    )
                    + "\n"
                )
                output = io.StringIO()

                def fail(*args):
                    db.execute("INSERT INTO projects VALUES('fixture','fixture',1)")
                    raise ValueError("synthetic")

                with (
                    patch("kn.call", side_effect=fail),
                    patch("sys.stdin", io.StringIO(request + "bad json\n")),
                    patch("sys.stdout", output),
                ):
                    kn.rpc_server(db)
                self.assertEqual(db.execute("SELECT count(*) FROM projects").fetchone()[0], 0)
                replies = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(replies[0]["id"], 1)
                self.assertEqual(replies[1]["id"], None)
                self.assertEqual(replies[1]["error"]["code"], -32700)
            finally:
                db.close()

    def test_invalid_watch_status_and_inaccessible_lock_are_not_running(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "watch-status.json").write_text("[]")
            (root / "watch.lock").write_bytes(b"0")
            with patch("watcher.os.open", side_effect=PermissionError):
                status = watcher.status(root)
            self.assertFalse(status["running"])
            self.assertIn("error", status)

    def test_background_worker_retries_database_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = kn.connect(root / "fixture.sqlite3")
            reports = []

            def write_status(path, body):
                reports.append(json.loads(body))
                if len(reports) == 2:
                    (root / "watch-stop.json").write_text("{}")

            engine = SimpleNamespace(data_root=lambda: root, connect=lambda: db)
            with (
                patch(
                    "watcher.ProjectWatcher.tick",
                    side_effect=[sqlite3.OperationalError("locked"), {}],
                ) as tick,
                patch("onboarding.atomic_write", side_effect=write_status),
            ):
                self.assertEqual(watcher.run(engine, interval=0), {"stopped": True})
            self.assertEqual(tick.call_count, 2)
            self.assertIn("error", reports[0])
            self.assertEqual(reports[1]["projects"], {})

    def test_framework_edges_update_and_workspace_does_not_change_scoped_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            project = root / "one"
            project.mkdir()
            manifest = project / "package.json"
            manifest.write_text(json.dumps({"dependencies": {"react": "fixture"}}))
            db = kn.connect(root / "store.sqlite3")
            try:
                kn.sync(project, db)
                other = root / "two"
                other.mkdir()
                (other / "package.json").write_text(
                    json.dumps({"dependencies": {"next": "fixture"}})
                )
                kn.sync(other, db)
                shared = kn.get_master_graph(db, limit=100)
                self.assertEqual(shared["edge_count"], 0)
                workspace = kn.get_master_graph(db, limit=100, workspace=True)
                self.assertEqual(workspace["edge_count"], 2)
                scoped = kn.get_master_graph(db, limit=100, project=str(project))
                self.assertEqual(scoped["edge_count"], 1)
                self.assertTrue(all(e["scope"] == str(project) for e in scoped["edges"]))
                manifest.write_text("{invalid")
                kn.sync(project, db)
                edge = db.execute(
                    "SELECT evidence FROM asset_link_evidence WHERE scope=?", (str(project),)
                ).fetchone()
                self.assertTrue(edge[0].startswith("Needs recheck:"))
                manifest.write_text('{"dependencies":{}}')
                kn.sync(project, db)
                self.assertEqual(kn.get_master_graph(db, project=str(project))["edge_count"], 0)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
