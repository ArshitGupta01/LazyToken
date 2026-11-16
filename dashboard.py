"""Loopback-only browser dashboard with explicit local memory review."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sqlite3
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import kn

HERE = Path(__file__).resolve().parent


def database_path() -> Path:
    return kn.data_root() / "network.sqlite3"


def read_graph(project: str = "", workspace: bool = False) -> dict:
    path = database_path()
    if not path.is_file():
        return {
            "error": "No local knowledge database yet. Run lazytoken init, then lazytoken add <absolute repository path>."
        }
    conn = sqlite3.connect(f"file:{quote(path.as_posix(), safe='/:')}?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    try:
        return kn.get_master_graph(conn, 500, project, edge_limit=3000, workspace=workspace)
    finally:
        conn.close()


def read_projects() -> list[dict]:
    path = database_path()
    if not path.is_file():
        return []
    conn = sqlite3.connect(f"file:{quote(path.as_posix(), safe='/:')}?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT p.id,p.root,count(f.path) AS files,p.updated_at FROM projects p LEFT JOIN files f ON f.project_id=p.id GROUP BY p.id ORDER BY p.root"
            )
        ]
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "LazyTokenLocal/0.4"

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            self._get()
        except (ValueError, TypeError):
            self._json({"error": "Invalid request parameters"}, 400)
        except (OSError, sqlite3.Error, RuntimeError):
            self._json(
                {
                    "error": "Local data is temporarily unavailable; retry after checking lazytoken doctor."
                },
                503,
            )

    def _get(self) -> None:
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host", "").lower() not in {
            expected_host,
            f"localhost:{self.server.server_port}",
        }:
            return self._json({"error": "Invalid host"}, 403)
        parsed = urlparse(self.path)
        if parsed.path in ("/api/health", "/api/ping"):
            return self._json({
                "status": "ok",
                "service": "lazytoken",
                "version": kn.VERSION,
                "port": self.server.server_port,
            })
        if parsed.path == "/api/session":
            return self._json({"token": self.server.review_token})
        if parsed.path.startswith("/api/session/"):
            session = unquote(parsed.path[len("/api/session/") :])
            if not session.strip() or len(session) > 120:
                return self._json({"error": "Invalid session ID"}, 400)
            path = database_path()
            if not path.is_file():
                return self._json({"error": "Session not found"}, 404)
            conn = sqlite3.connect(
                f"file:{quote(path.as_posix(), safe='/:')}?mode=ro", uri=True, timeout=2
            )
            conn.row_factory = sqlite3.Row
            try:
                params = parse_qs(parsed.query, keep_blank_values=True)
                requested_values = params.get("project", [])
                if requested_values and (
                    len(requested_values) != 1 or not requested_values[0].strip()
                ):
                    return self._json({"error": "Invalid project"}, 400)
                requested = requested_values[0] if requested_values else ""
                project = kn.resolve_project(requested, conn) if requested else ""
                if requested and not project:
                    return self._json({"error": "Session not found"}, 404)
                projects = [
                    row[0]
                    for row in conn.execute(
                        "SELECT DISTINCT project_id FROM context_session_items WHERE session_id=? AND (?='' OR project_id=?) LIMIT 2",
                        (session, project, project),
                    )
                ]
                if len(projects) != 1:
                    return self._json(
                        {
                            "error": (
                                "Session not found" if not projects else "Session ID is ambiguous"
                            )
                        },
                        404 if not projects else 409,
                    )
                import broker

                return self._json(
                    broker.session_checkpoint(
                        kn, {"project": projects[0], "session_id": session, "read_only": True}, conn
                    )
                )
            finally:
                conn.close()
        if parsed.path == "/api/lazytoken":
            params = parse_qs(parsed.query)
            action = params.get("action", [""])[0]
            if action not in {"search", "proposals", "benchmark_list", "dependencies", "discover"}:
                return self._json({"error": "Unknown action"}, 400)
            if not database_path().is_file():
                return self._json({"error": "Database not found"}, 404)
            args = {k: v[0][:1000] for k, v in params.items() if k != "action"}
            conn = kn.connect(database_path())
            try:
                result = kn.feature_call(action, args, conn)
            finally:
                conn.close()
            return self._json(result, 400 if "error" in result else 200)
        if parsed.path == "/api/projects":
            return self._json(read_projects())
        if parsed.path == "/api/graph":
            params = parse_qs(parsed.query)
            project = params.get("project", [""])[0][:1000]
            workspace = params.get("workspace", ["0"])[0] == "1"
            if project and workspace:
                return self._json({"error": "Choose project or workspace scope."}, 400)
            result = read_graph(project, workspace)
            return self._json(result, 400 if "error" in result else 200)
        if parsed.path not in (
            "/",
            "/index.html",
            "/app.js",
            "/features-ui.js",
            "/styles.css",
            "/graph3d.js",
            "/vendor/three.module.js",
            "/vendor/three.core.js",
            "/vendor/OrbitControls.js",
        ):
            return self._json({"error": "Not found"}, 404)
        target = HERE / (
            "index.html" if parsed.path in ("/", "/index.html") else parsed.path.lstrip("/")
        )
        try:
            resolved_target = target.resolve()
            resolved_here = HERE.resolve()
            if not resolved_target.is_file() or not resolved_target.is_relative_to(resolved_here):
                return self._json(
                    {"error": "Dashboard asset missing; reinstall a verified package."}, 503
                )
        except (OSError, ValueError):
            return self._json({"error": "Access denied"}, 403)
        body = target.read_bytes()
        mime = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }[target.suffix]
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data:",
        )
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        expected_host = f"127.0.0.1:{self.server.server_port}"
        host = self.headers.get("Host", "").lower()
        if host not in {expected_host, f"localhost:{self.server.server_port}"}:
            return self._json({"error": "Invalid host"}, 403)
        if self.path != "/api/review":
            return self._json({"error": "Not found"}, 404)
        if self.headers.get("Origin") != f"http://{host}" or not secrets.compare_digest(
            self.headers.get("X-LazyToken-Review", ""), self.server.review_token
        ):
            return self._json({"error": "Invalid review request"}, 403)
        if self.headers.get_content_type() != "application/json":
            return self._json({"error": "JSON required"}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 16384:
                return self._json({"error": "Invalid request size"}, 400)
            args = json.loads(self.rfile.read(length))
            if not isinstance(args, dict):
                return self._json({"error": "Expected object"}, 400)
            if not database_path().is_file():
                return self._json({"error": "Database not found"}, 404)
            conn = kn.connect(database_path())
            try:
                result = kn.feature_call("review", args, conn)
            finally:
                conn.close()
            return self._json(result, 400 if "error" in result else 200)
        except (ValueError, UnicodeDecodeError, sqlite3.Error, RuntimeError):
            return self._json({"error": "Unable to process review"}, 400)

    def log_message(self, fmt: str, *args: object) -> None:
        pass


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def __init__(self, *args, **kwargs):
        self.review_token = secrets.token_urlsafe(32)
        super().__init__(*args, **kwargs)

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    # Initialize additive schema updates before opening graph reads in read-only mode.
    if database_path().is_file():
        conn = kn.connect(database_path())
        selected = conn.execute("SELECT 1 FROM projects LIMIT 1").fetchone()
        conn.close()
        if selected:
            import watcher

            watcher.start(kn)
    server = LocalServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"LazyToken dashboard: {url} (loopback only; Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
