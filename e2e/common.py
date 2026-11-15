"""Base test case, subprocess runners, and MCP JSON-RPC client for LazyToken E2E tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


class McpClient:
    """Stdio JSON-RPC 2.0 client managing a `python kn.py mcp` subprocess."""

    def __init__(self, env: dict[str, str], cwd: Path) -> None:
        self.env = env
        self.cwd = cwd
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT_DIR / "kn.py"), "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(cwd),
            bufsize=1,
        )
        self._req_id = 0

    def _send_request(self, method: str, params: dict | None = None) -> dict:
        self._req_id += 1
        req: dict = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params is not None:
            req["params"] = params
        payload = json.dumps(req, ensure_ascii=False) + "\n"
        if not self.proc.stdin or self.proc.poll() is not None:
            raise RuntimeError("MCP process is not running.")
        self.proc.stdin.write(payload)
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            stderr_out = self.proc.stderr.read() if self.proc.stderr else ""
            raise EOFError(f"MCP server stdout closed. Stderr: {stderr_out}")
        return json.loads(line)

    def initialize(self, protocol_version: str = "2024-11-05") -> dict:
        res = self._send_request("initialize", {"protocolVersion": protocol_version})
        if "result" in res and isinstance(res["result"], dict):
            merged = dict(res["result"])
            merged["result"] = res["result"]
            merged["jsonrpc"] = res.get("jsonrpc")
            merged["id"] = res.get("id")
            return merged
        return res

    def ping(self) -> dict:
        res = self._send_request("ping")
        return res.get("result", res)

    def list_tools(self) -> list[dict]:
        res = self._send_request("tools/list")
        if "result" in res and isinstance(res["result"], dict):
            return res["result"].get("tools", [])
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        res = self._send_request("tools/call", {"name": name, "arguments": arguments})
        return res.get("result", res)

    def list_resources(self) -> list[dict]:
        res = self._send_request("resources/list")
        if "result" in res and isinstance(res["result"], dict):
            return res["result"].get("resources", [])
        return res if isinstance(res, list) else []

    def read_resource(self, uri: str) -> dict:
        res = self._send_request("resources/read", {"uri": uri})
        return res.get("result", res)

    def close(self) -> None:
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        if self.proc.stdout:
            try:
                self.proc.stdout.close()
            except Exception:
                pass
        if self.proc.stderr:
            try:
                self.proc.stderr.close()
            except Exception:
                pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


class E2ETestCase(unittest.TestCase):
    """Base class for LazyToken E2E tests with complete environment and DB isolation."""

    def setUp(self) -> None:
        self._temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self._temp_dir_obj.name).resolve()
        self.env = {
            **os.environ,
            "KN_HOME": str(self.temp_dir),
            "LAZYTOKEN_DISABLE_AUTOWATCH": "1",
        }
        self._subprocesses: list[subprocess.Popen] = []
        self._mcp_clients: list[McpClient] = []

    def tearDown(self) -> None:
        for client in self._mcp_clients:
            try:
                client.close()
            except Exception:
                pass
        for proc in self._subprocesses:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            self._temp_dir_obj.cleanup()
        except Exception:
            pass

    def create_repo(self, files: dict[str, str]) -> Path:
        """Create a multi-file synthetic code repository in an isolated subdirectory."""
        repo_dir = self.temp_dir / f"repo_{uuid.uuid4().hex[:8]}"
        repo_dir.mkdir(parents=True, exist_ok=True)
        for rel_path, content in files.items():
            file_path = repo_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        return repo_dir

    def run_cli(
        self, args: list[str], check: bool = False, timeout: int = 20
    ) -> subprocess.CompletedProcess:
        """Invoke `python kn.py ...` with isolated environment."""
        cmd = [sys.executable, str(ROOT_DIR / "kn.py"), *args]
        res = subprocess.run(
            cmd,
            env=self.env,
            cwd=str(self.temp_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if check and res.returncode != 0:
            raise subprocess.CalledProcessError(
                res.returncode, cmd, output=res.stdout, stderr=res.stderr
            )
        return res

    def run_cli_json(self, args: list[str], check: bool = True) -> dict:
        """Run CLI and parse stdout as JSON."""
        res = self.run_cli(args, check=check)
        stdout = res.stdout.strip()
        if not stdout:
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"CLI did not output valid JSON.\nExit code: {res.returncode}\nStdout: {res.stdout}\nStderr: {res.stderr}"
            ) from exc

    def open_mcp_client(self) -> McpClient:
        """Spawn and return an active stdio JSON-RPC MCP client."""
        client = McpClient(env=self.env, cwd=self.temp_dir)
        self._mcp_clients.append(client)
        return client
