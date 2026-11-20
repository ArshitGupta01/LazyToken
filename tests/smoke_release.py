"""Explicit Windows release smoke test. Uses isolated temporary data, never agent tasks."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def smoke(package):
    package = Path(package).resolve()
    executable = package / "TokSmart" / "TokSmart.exe"
    installer = package / "install.ps1"
    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    assert (package / "TokSmart" / "_internal" / "vendor" / "PYTHON-LICENSE.txt").is_file()
    assert (package / "TokSmart" / "_internal" / "docs" / "CLIENT_COMPATIBILITY.md").is_file()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        project = root / "project"
        project.mkdir()
        (project / "AuthService.py").write_text("class AuthService: pass", encoding="utf-8")
        env = os.environ.copy()
        env["KN_HOME"] = str(root / "data")
        env["LAZYTOKEN_DISABLE_AUTOWATCH"] = "1"
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        env["USERPROFILE"] = str(root / "profile")
        env["HOME"] = str(root / "profile")
        (root / "profile").mkdir()
        import shutil

        assert shutil.which("python", path=env["PATH"]) is None
        assert shutil.which("node", path=env["PATH"]) is None

        def run(*args):
            result = subprocess.run(
                [str(executable), *args], env=env, capture_output=True, text=True, timeout=30
            )
            if result.returncode:
                raise AssertionError(result.stderr or result.stdout)
            return json.loads(result.stdout)

        run("init", "--project", str(project))
        from tokenizers import Tokenizer, models, pre_tokenizers

        tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer.save(str(root / "tokenizer.json"))
        env["LAZYTOKEN_TOKENIZER_MODEL"] = "fixture-words"
        env["LAZYTOKEN_TOKENIZER_FILE"] = str(root / "tokenizer.json")
        context = run(
            "context",
            "--project",
            str(project),
            "--task",
            "auth",
            "--budget",
            "600",
            "--model",
            "fixture-words",
            "--strict-budget",
        )
        assert context["budget_type"] == "tokenizer:fixture-words", context
        prompt = subprocess.run(
            [str(executable), "context", "--project", str(project), "--task", "auth", "--prompt"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert prompt.returncode == 0 and "AuthService.py" in prompt.stdout, prompt.stderr
        assert "untrusted evidence" in prompt.stdout
        result = run(
            "lazytoken",
            "complete_task",
            "--json",
            json.dumps(
                {
                    "project": str(project),
                    "task": "Fixture checkpoint",
                    "outcome": "success",
                    "resolution": "A synthetic lesson for package verification only.",
                    "evidence": "Synthetic fixture",
                    "paths": ["AuthService.py"],
                }
            ),
        )
        assert result["status"] == "pending"
        try:
            watching = run("watch", "start", "--interval", ".25", "--debounce", "0")
            assert watching["running"], watching
            (project / "AuthService.py").write_text("class AuthService: changed = 1")
            deadline = time.monotonic() + 8
            expected = (
                __import__("hashlib").sha256((project / "AuthService.py").read_bytes()).hexdigest()
            )
            while time.monotonic() < deadline:
                import sqlite3

                with sqlite3.connect(root / "data/network.sqlite3") as inspect:
                    current = inspect.execute(
                        "SELECT digest FROM files WHERE path='AuthService.py'"
                    ).fetchone()
                inspect.close()
                if current and current[0] == expected:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Packaged background watcher did not update indexed source")
        finally:
            run("watch", "stop")
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_task_context",
                "arguments": {"project": str(project), "task": "auth", "budget": 600},
            },
        }
        initialize = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
        rpc = subprocess.run(
            [str(executable), "mcp", "--compact-tools"],
            env=env,
            input=json.dumps(initialize)
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
            + "\n"
            + json.dumps(request)
            + "\n",
            text=True,
            capture_output=True,
            timeout=30,
        )
        startup, reply = [json.loads(line) for line in rpc.stdout.splitlines()]
        assert "get_task_context" in startup["result"]["instructions"], startup
        assert "result" in reply and not reply["result"]["isError"], reply
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = subprocess.Popen(
            [str(executable), "dashboard", "--port", str(port), "--no-browser"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        page = response.read()
                        assert (
                            b"inspector-minimize" in page and b'id="relation-filters"' not in page
                        )
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("Dashboard did not start")
            for asset in (
                "theme.js",
                "graph3d.js",
                "vendor/three.module.js",
                "vendor/three.core.js",
                "vendor/OrbitControls.js",
                "api/projects",
            ):
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/{asset}", timeout=5
                ) as response:
                    assert response.status == 200
        finally:
            server.terminate()
            server.wait(timeout=10)
        target = root / "installed"

        def manage(action, *extra):
            result = subprocess.run(
                [
                    str(shell),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(installer),
                    "-Action",
                    action,
                    "-InstallRoot",
                    str(target),
                    "-Source",
                    str(executable.parent),
                    *extra,
                ],
                capture_output=True,
                text=True,
                timeout=45,
            )
            assert result.returncode == 0, result.stderr

        manage("install")
        first = (target / "current.txt").read_text()
        installed = target / "versions" / first / "TokSmart.exe"
        assert (
            subprocess.run(
                [str(installed), "doctor"], env=env, capture_output=True, timeout=20
            ).returncode
            == 0
        )
        manage("upgrade")
        assert (target / "current.txt").read_text() != first
        manage("rollback")
        assert (target / "current.txt").read_text() == first
        manage("uninstall", "-ConfirmUninstall")
        assert not target.exists()
        import sqlite3

        with sqlite3.connect(root / "data/network.sqlite3") as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute("SELECT count(*) FROM assets").fetchone()[0] == 0
        db.close()
        # The bootstrap validates the versioned zip before executing its managed helper.
        import hashlib

        archive = next(package.glob("toksmart-v*-windows-x64.zip"))
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()

        def user_path():
            return subprocess.run(
                [
                    str(shell),
                    "-NoProfile",
                    "-Command",
                    '[Console]::Write([Environment]::GetEnvironmentVariable("Path","User"))',
                ],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout

        path_before = user_path()
        verified = root / "verified cli"
        install = subprocess.run(
            [
                str(shell),
                "-NoProfile",
                "-File",
                str(package / "bootstrap.ps1"),
                "-PackagePath",
                str(archive),
                "-ExpectedSha256",
                checksum,
                "-InstallRoot",
                str(verified),
                "-NoPathRegistration",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert install.returncode == 0, install.stderr

        def cli(*args):
            process = subprocess.run(
                [str(shell), "-NoProfile", "-File", str(verified / "dispatch.ps1"), *args],
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert process.returncode == 0, process.stderr or process.stdout
            return process.stdout

        assert json.loads(cli("doctor"))["installation_integrity"] == "ok"
        command_env = {**env, "PATH": str(verified / "bin") + os.pathsep + env["PATH"]}
        command = subprocess.run(
            [
                str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe"),
                "/d",
                "/c",
                "toksmart",
                "doctor",
            ],
            env=command_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert (
            command.returncode == 0 and json.loads(command.stdout)["installation_integrity"] == "ok"
        ), (command.stderr or command.stdout)
        cli("setup", "--project", str(project), "--client", "codex", "--apply")
        config = root / "profile/.codex/config.toml"
        assert "dispatch.ps1" in config.read_text()
        env["LAZYTOKEN_DISABLE_AUTOWATCH"] = "0"
        cli("watch", "start")
        try:
            failed = subprocess.run(
                [
                    str(shell),
                    "-NoProfile",
                    "-File",
                    str(verified / "dispatch.ps1"),
                    "update",
                    "--package",
                    str(archive),
                    "--sha256",
                    "0" * 64,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert failed.returncode != 0
            assert json.loads(cli("watch", "status"))[
                "running"
            ], "Failed update must resume the prior watcher"
            cli("update", "--package", str(archive), "--sha256", checksum)
            assert json.loads(cli("watch", "status"))[
                "running"
            ], "Update must resume automatic sync"
            path_during_update = user_path()
            cli("rollback")
            assert json.loads(cli("watch", "status"))[
                "running"
            ], "Rollback must resume automatic sync"
        finally:
            cli("watch", "stop")
        cli("uninstall", "--yes", "--remove-clients")
        assert not config.exists() and not verified.exists()
        assert (
            path_before == path_during_update == user_path()
        ), "Portable lifecycle must not change the real user PATH"
        assert (root / "data/network.sqlite3").exists()
        print(
            "PASS: standalone runtime, configured tokenizer, pending checkpoint, MCP, dashboard, assets, install/upgrade/rollback/uninstall, preserved isolated SQLite data; verified zip bootstrap, stable MCP path, launcher update/rollback/uninstall and owned client removal."
        )


if __name__ == "__main__":
    smoke(sys.argv[1])
