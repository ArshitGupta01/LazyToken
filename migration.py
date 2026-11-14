"""Explicit copy-only migration. Legacy databases are never modified or merged."""

import hashlib
import json
from pathlib import Path
import time
import data_ops


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def migrate(source, destination, apply=False):
    source = Path(source).resolve()
    destination = Path(destination).absolute()
    if not source.is_file():
        return {"error": "Legacy source database does not exist."}
    if source == destination.resolve():
        return {
            "error": "Source and destination must differ; choose the new default data directory."
        }
    if destination.exists():
        return {"error": "Destination already exists. No overwrite or merge is permitted."}
    if not apply:
        return {
            "preview": True,
            "source": str(source),
            "destination": str(destination),
            "next": "Add --apply to create a verified backup and copy. Source remains untouched.",
        }
    from onboarding import regular_path, atomic_write

    regular_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stamp = str(time.time_ns())
    backup = destination.parent / ("legacy-migration-" + stamp + ".sqlite3")
    saved = data_ops.copy_database(source, backup)
    if "error" in saved:
        return saved
    copied = data_ops.copy_database(backup, destination)
    if "error" in copied:
        return {**copied, "backup": str(backup)}
    receipt = destination.parent / ("migration-" + stamp + ".json")
    atomic_write(
        receipt,
        json.dumps(
            {
                "format": "lazytoken-migration-v1",
                "source": str(source),
                "destination": str(destination),
                "backup": str(backup),
                "hash": file_hash(destination),
            },
            indent=2,
        ).encode(),
    )
    return {
        "migrated": True,
        "source_unchanged": True,
        "destination": str(destination),
        "backup": str(backup),
        "receipt": str(receipt),
    }


def rollback(receipt):
    data = json.loads(Path(receipt).read_text())
    if data.get("format") != "lazytoken-migration-v1":
        return {"error": "Invalid migration receipt."}
    destination = Path(data["destination"])
    if (
        destination.name != "network.sqlite3"
        or destination.parent.resolve() != Path(receipt).parent.resolve()
    ):
        return {"error": "Receipt does not identify its own migration database."}
    from onboarding import regular_path

    regular_path(destination)
    if (
        not destination.is_file()
        or file_hash(destination) != data["hash"]
        or any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm"))
    ):
        return {
            "error": "Migrated store changed or may be active; rollback refused. Source and backup are retained."
        }
    destination.unlink()
    return {"rolled_back": True, "source_unchanged": True, "backup_retained": data["backup"]}


def delete_default_store(kn, confirmation):
    # A separate operator command. Never recursively delete directories or legacy/overridden stores.
    root = kn.default_data_root().absolute()
    from onboarding import regular_path

    if (
        not Path(confirmation).is_absolute()
        or Path(confirmation).absolute() != root
        or kn.data_root().absolute() != root
    ):
        return {
            "error": "Confirm the exact default LazyToken directory. Legacy and KN_HOME override stores cannot be deleted by this command."
        }
    try:
        regular_path(root)
    except ValueError as exc:
        return {"error": str(exc)}
    database = root / "network.sqlite3"
    if not database.is_file():
        return {"error": "Default database not found."}
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm")):
        return {
            "error": "Database may be active. Stop LazyToken processes before explicit data deletion."
        }
    import sqlite3

    try:
        from urllib.parse import quote

        connection = sqlite3.connect(
            "file:" + quote(database.as_posix(), safe="/:") + "?mode=ro", uri=True
        )
        try:
            connection.execute("SELECT version FROM lazytoken_migrations LIMIT 1").fetchone()
        finally:
            connection.close()
        database.unlink()
    except (OSError, sqlite3.Error):
        return {"error": "Database could not be safely identified or removed."}
    return {
        "deleted": str(database),
        "note": "Only the default database file was removed. Application files, backups and other user files were preserved.",
    }
