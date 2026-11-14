"""Read-only, actionable local CLI diagnostics."""

import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from urllib.parse import quote
import onboarding


def report(kn):
    root = kn.data_root()
    database = root / "network.sqlite3"
    parent = root
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    checks = {
        "version": kn.VERSION,
        "runtime_bundled": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "data_directory": str(root),
        "data_parent_writable": os.access(parent, os.W_OK),
        "database_exists": database.is_file(),
        "legacy_databases": [str(p / "network.sqlite3") for p in kn.legacy_data_roots()],
    }
    checks["sqlite"] = "not initialized"
    if database.is_file():
        try:
            db = sqlite3.connect(
                "file:" + quote(database.resolve().as_posix(), safe="/:") + "?mode=ro",
                uri=True,
                timeout=2,
            )
            try:
                checks["sqlite"] = db.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                db.close()
        except sqlite3.Error:
            checks["sqlite"] = "unreadable or invalid; restore a verified backup to a new directory"
    checks["clients"] = onboarding.diagnose(kn)["clients"]
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.2):
            checks["dashboard_port_listening"] = True
    except OSError:
        checks["dashboard_port_listening"] = False
    managed = onboarding.managed_root()
    checks["managed_installation"] = str(managed) if managed else None
    checks["installation_integrity"] = "source checkout; use the test suite"
    if getattr(sys, "frozen", False):
        manifest = Path(sys.executable).parent / "release-manifest.json"
        checks["installation_integrity"] = "manifest missing; reinstall a verified package"
        if manifest.is_file():
            import hashlib

            try:
                listing = json.loads(manifest.read_text(encoding="utf-8-sig"))
                base = manifest.parent.resolve()
                bad = []
                for name, expected in listing["files"].items():
                    path = (base / name).resolve()
                    if not path.is_relative_to(base) or not path.is_file():
                        bad.append(name)
                        continue
                    value = hashlib.sha256()
                    with path.open("rb") as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            value.update(block)
                    if value.hexdigest().lower() != expected.lower():
                        bad.append(name)
                checks["installation_integrity"] = "ok" if not bad else {"failed_files": bad[:20]}
            except (ValueError, OSError, KeyError, TypeError, AttributeError):
                checks["installation_integrity"] = "manifest invalid; reinstall a verified package"
    import watcher

    checks["automatic_sync"] = watcher.status(root)
    checks["repairs"] = []
    if not database.is_file():
        checks["repairs"].append("Run lazytoken init, then lazytoken add <absolute repository>.")
    if checks["legacy_databases"]:
        checks["repairs"].append(
            "Legacy data detected. Preview lazytoken migrate-data --source <database>; apply only after reviewing paths."
        )
    if not checks["data_parent_writable"]:
        checks["repairs"].append(
            "Choose a writable directory with KN_HOME; administrator privileges are not normally needed."
        )
    checks["repairs"].append(
        "Use lazytoken setup --project <repository> --client codex to preview MCP registration; add --apply to opt in."
    )
    return checks
