import http.client
import json
import sqlite3
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard
import broker
import kn


class LocalReviewTests(unittest.TestCase):
    def test_session_graph_is_scoped_and_ambiguous_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"KN_HOME": temp}):
            db = kn.connect()
            roots = [Path(temp) / "one", Path(temp) / "two"]
            for root in roots:
                root.mkdir()
                (root / "sample.py").write_text("def sample(): pass\n", encoding="utf-8")
                (root / (root.name + ".py")).write_text(
                    "def sample_extra(): pass\n", encoding="utf-8"
                )
                kn.sync(root, db)
            broker.task_context(
                kn, {"project": str(roots[0]), "task": "sample", "session_id": "shared/id"}, db
            )
            server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                conn.request("GET", "/api/session/shared%2Fid")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                payload = json.loads(response.read())
                self.assertEqual(payload["project"], str(roots[0].resolve()))
                self.assertGreater(payload["supplied_items"], 0)
                self.assertIn("sample.py", payload["active_graph"]["files"])
                self.assertNotIn("two.py", payload["active_graph"]["files"])
                conn.request("GET", "/api/session/shared%2Fid?project=")
                response = conn.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
                broker.task_context(
                    kn, {"project": str(roots[1]), "task": "sample", "session_id": "shared/id"}, db
                )
                conn.request("GET", "/api/session/shared%2Fid")
                response = conn.getresponse()
                self.assertEqual(response.status, 409)
                response.read()
                conn.request(
                    "GET", "/api/session/shared%2Fid?project=" + quote(str(roots[1]), safe="")
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                payload = json.loads(response.read())
                self.assertEqual(payload["project"], str(roots[1].resolve()))
                self.assertIn("sample.py", payload["active_graph"]["files"])
                self.assertNotIn("one.py", payload["active_graph"]["files"])
                conn.request("GET", "/api/session/missing")
                response = conn.getresponse()
                self.assertEqual(response.status, 404)
                response.read()
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                thread.join()
                db.close()

    def test_invalid_input_and_unavailable_database_return_json_errors(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"KN_HOME": temp}):
            kn.connect().close()
            server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                conn.request("GET", "/api/lazytoken?action=search&limit=invalid")
                response = conn.getresponse()
                self.assertEqual(response.status, 400)
                self.assertIn("error", json.loads(response.read()))
                with patch(
                    "dashboard.read_projects", side_effect=sqlite3.OperationalError("fixture")
                ):
                    conn.request("GET", "/api/projects")
                    response = conn.getresponse()
                    self.assertEqual(response.status, 503)
                    self.assertIn("error", json.loads(response.read()))
                conn.request("GET", "/api/projects")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), [])
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                thread.join()

    def test_review_requires_same_origin_and_session_token(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"KN_HOME": temp}):
            root = Path(temp) / "project"
            root.mkdir()
            (root / "source.py").write_text("class Account: pass", encoding="utf-8")
            db = kn.connect(Path(temp) / "network.sqlite3")
            kn.sync(root, db)
            p = kn.feature_call(
                "propose",
                {
                    "project": str(root.resolve()),
                    "kind": "lesson",
                    "name": "Account",
                    "summary": "Account behavior",
                    "task": "Fix",
                    "evidence": "Source",
                    "paths": ["source.py"],
                },
                db,
            )
            db.close()
            server = dashboard.LocalServer(("127.0.0.1", 0), dashboard.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_port
                host = f"127.0.0.1:{port}"
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                for asset in (
                    "/graph3d.js",
                    "/vendor/three.module.js",
                    "/vendor/three.core.js",
                    "/vendor/OrbitControls.js",
                ):
                    conn.request("GET", asset)
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertIn("javascript", response.getheader("Content-Type"))
                    response.read()
                conn.request("GET", "/vendor/THREE-LICENSE.txt")
                response = conn.getresponse()
                self.assertEqual(response.status, 404)
                response.read()
                payload = json.dumps(
                    {"project": str(root.resolve()), "id": p["id"], "action": "approve"}
                )
                conn.request(
                    "POST",
                    "/api/review",
                    payload,
                    {
                        "Content-Type": "application/json",
                        "Origin": "http://attacker.example",
                        "X-LazyToken-Review": server.review_token,
                    },
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                conn.request(
                    "POST",
                    "/api/review",
                    payload,
                    {
                        "Content-Type": "application/json",
                        "Origin": "http://" + host,
                        "X-LazyToken-Review": "wrong",
                    },
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                conn.request(
                    "POST",
                    "/api/review",
                    payload,
                    {
                        "Content-Type": "application/json",
                        "Origin": "http://" + host,
                        "X-LazyToken-Review": server.review_token,
                    },
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["status"], "approved")
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
