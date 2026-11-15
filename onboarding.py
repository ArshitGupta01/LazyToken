"""Offline setup preview, opt-in client configuration and guarded rollback."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib


def digest(data):
    return hashlib.sha256(data).hexdigest()


def configuration_path(client, profile):
    if client == "codex":
        return profile / ".codex" / "config.toml"
    if client == "antigravity":
        return profile / ".gemini" / "config" / "mcp_config.json"
    raise ValueError("Supported clients: codex, antigravity.")


def managed_root():
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False) and executable.parent.parent.name == "versions":
        root = executable.parent.parent.parent
        if (root / ".lazytoken-install").is_file():
            return root
    return None


def entry(kn):
    root = managed_root()
    if root:
        command = str(
            Path(os.environ["SystemRoot"])
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        args = ["-NoProfile", "-File", str(root / "dispatch.ps1"), "mcp", "--compact-tools"]
    else:
        command = sys.executable
        args = (
            ["mcp", "--compact-tools"]
            if getattr(sys, "frozen", False)
            else [str(Path(kn.__file__).resolve()), "mcp", "--compact-tools"]
        )
    return {"command": command, "args": args, "env": {"KN_HOME": str(kn.data_root().resolve())}}


def regular_path(path):
    for part in (path, *path.parents):
        if (part.exists() or part.is_symlink()) and (
            part.is_symlink() or getattr(part.lstat(), "st_file_attributes", 0) & 0x400
        ):
            raise ValueError("Configuration paths must not contain symlinks or junctions.")


def server_entries(data, client):
    key = "mcp_servers" if client == "codex" else "mcpServers"
    if not isinstance(data, dict) or not isinstance(data.get(key, {}), dict):
        raise ValueError("Invalid client configuration.")
    servers = data.get(key, {})
    if "lazytoken" in servers and not isinstance(servers["lazytoken"], dict):
        raise ValueError("Invalid LazyToken registration.")
    return servers


def preview(kn, project, clients=(), profile=None):
    root = Path(project)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("Select an existing absolute repository directory.")
    profile = Path(profile) if profile else Path.home()
    server = entry(kn)
    changes = []
    for client in dict.fromkeys(clients):
        path = configuration_path(client, profile)
        regular_path(path)
        before = path.read_bytes() if path.exists() else b""
        text = before.decode("utf-8-sig")
        if client == "codex":
            parsed = tomllib.loads(text)
            existing = server_entries(parsed, client).get("lazytoken")
            addition = (
                "\n[mcp_servers.lazytoken]\ncommand = "
                + json.dumps(server["command"])
                + "\nargs = "
                + json.dumps(server["args"])
                + "\n[mcp_servers.lazytoken.env]\nKN_HOME = "
                + json.dumps(server["env"]["KN_HOME"])
                + "\n"
            )
            after = (text + addition).encode("utf-8")
            if existing is None:
                tomllib.loads(after.decode())
            else:
                after = before
        else:
            parsed = json.loads(text) if text.strip() else {}
            existing = server_entries(parsed, client).get("lazytoken")
            parsed.setdefault("mcpServers", {})["lazytoken"] = server
            after = json.dumps(parsed, ensure_ascii=False, indent=2).encode("utf-8")
        changes.append(
            {
                "client": client,
                "path": str(path),
                "status": "existing_entry_preserved" if existing is not None else "add",
                "matches_suggested_entry": existing == server if existing is not None else None,
                "before": before,
                "after": after,
            }
        )
    return {
        "project": str(root.resolve()),
        "database": str(kn.data_root()),
        "changes": changes,
        "server": server,
    }


def atomic_write(path, data):
    path = Path(path)
    regular_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".lazytoken-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def apply(kn, plan):
    # Validate every destination before the first configuration write.
    for change in plan["changes"]:
        path = Path(change["path"])
        regular_path(path)
        current = path.read_bytes() if path.exists() else b""
        if current != change["before"]:
            raise ValueError("Configuration changed after preview; rerun setup.")
    db = kn.connect()
    try:
        indexed = kn.sync(Path(plan["project"]), db)
    finally:
        db.close()
    if indexed.get("error") or indexed["error_count"]:
        raise ValueError(
            "Indexing failed or reported unreadable files; client configuration was not changed."
        )
    receipts = []
    receipt = kn.data_root() / ("setup-" + str(time.time_ns()) + ".json")
    try:
        for change in plan["changes"]:
            if change["status"] != "add":
                continue
            path = Path(change["path"])
            regular_path(path)
            existed = path.exists()
            current = path.read_bytes() if existed else b""
            if current != change["before"]:
                raise ValueError("Configuration changed during setup; rerun preview.")
            backup = path.with_name(path.name + ".lazytoken-" + str(time.time_ns()) + ".bak")
            # Backups are exclusive; retained for a later operator rollback.
            backup.parent.mkdir(parents=True, exist_ok=True)
            with backup.open("xb") as target:
                target.write(change["before"])
            receipts.append(
                {
                    "path": str(path),
                    "backup": str(backup),
                    "before_hash": digest(change["before"]),
                    "after_hash": digest(change["after"]),
                    "existed": existed,
                }
            )
            atomic_write(path, change["after"])
        atomic_write(
            receipt,
            json.dumps(
                {
                    "format": "lazytoken-setup-v1",
                    "owner": str(managed_root()) if managed_root() else None,
                    "changes": receipts,
                },
                indent=2,
            ).encode(),
        )
    except Exception:
        for record in reversed(receipts):
            path = Path(record["path"])
            if path.exists() and digest(path.read_bytes()) == record["after_hash"]:
                if record["existed"]:
                    atomic_write(path, Path(record["backup"]).read_bytes())
                else:
                    path.unlink()
        raise
    return {
        "configured": True,
        "index": indexed,
        "receipt": str(receipt),
        "note": "Existing LazyToken entries are preserved. Restart selected clients. Rerun setup after changing executable location.",
    }


def rollback(receipt):
    data = json.loads(Path(receipt).read_text(encoding="utf-8"))
    if data.get("format") != "lazytoken-setup-v1":
        raise ValueError("Invalid setup receipt.")
    for record in data["changes"]:
        path = Path(record["path"])
        backup = Path(record["backup"])
        regular_path(path)
        regular_path(backup)
        if (
            not path.exists()
            or digest(path.read_bytes()) != record["after_hash"]
            or digest(backup.read_bytes()) != record["before_hash"]
        ):
            raise ValueError(
                "Configuration or backup changed; rollback refused to preserve newer edits."
            )
    for record in data["changes"]:
        if record["existed"]:
            atomic_write(Path(record["path"]), Path(record["backup"]).read_bytes())
        else:
            Path(record["path"]).unlink()
    return {
        "restored": len(data["changes"]),
        "note": "Original bytes or file absence restored. Backups and receipt retained.",
    }


def diagnose(kn):
    profile = Path.home()
    clients = []
    for name in ("codex", "antigravity"):
        path = configuration_path(name, profile)
        result = {
            "client": name,
            "config_exists": path.is_file(),
            "binary_detected": shutil.which(name) is not None,
            "registered": False,
        }
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8-sig")
                data = tomllib.loads(text) if name == "codex" else json.loads(text)
                result["registered"] = "lazytoken" in server_entries(data, name)
                result["configuration_valid"] = True
            except (ValueError, OSError, TypeError, AttributeError):
                result["configuration_valid"] = False
        clients.append(result)
    return {
        "database": str(kn.data_root()),
        "clients": clients,
        "note": "Configuration validation does not prove a live client connection; restart the client and check its tool list.",
    }


def connection_test(kn):
    server = entry(kn)
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    try:
        result = subprocess.run(
            [server["command"], *server["args"]],
            input="".join(json.dumps(request) + "\n" for request in requests),
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, **server["env"], "LAZYTOKEN_DISABLE_AUTOWATCH": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        initialize = next((r for r in replies if r.get("id") == 1), {})
        listing = next((r for r in replies if r.get("id") == 2), {})
        names = [tool.get("name") for tool in listing.get("result", {}).get("tools", [])]
        ok = result.returncode == 0 and "result" in initialize and "get_task_context" in names
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError) as exc:
        return {
            "mcp_initialize": False,
            "error": type(exc).__name__,
            "note": "Check the launcher and run doctor for repair guidance.",
        }
    return {
        "mcp_initialize": ok,
        "tools_available": len(names),
        "note": "Local handshake and tool discovery only; restart your client and check its tool list.",
    }


def remove_managed_clients(kn, root):
    root = Path(root).resolve()
    if not (root / ".lazytoken-install").is_file():
        raise ValueError("Select a managed installation root.")
    count = 0
    for receipt in sorted(kn.data_root().glob("setup-*.json"), reverse=True):
        data = json.loads(receipt.read_text(encoding="utf-8"))
        if data.get("owner") != str(root) or data.get("removed") or not data.get("changes"):
            continue
        restored = rollback(receipt)
        count += restored["restored"]
        data["removed"] = True
        atomic_write(receipt, json.dumps(data, indent=2).encode())
    return {
        "removed_managed_entries": count,
        "note": "Unmanaged or subsequently edited configurations are never overwritten.",
    }
