"""Single-worker, metadata-first automatic synchronization for selected projects."""

from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

_CHILDREN = {}


class StoreLock:
    def __init__(self, path, create=True):
        self.path = Path(path)
        self.file = None
        self.create = create
        self.error = None

    def acquire(self):
        from onboarding import regular_path

        if not self.create and not self.path.is_file():
            return False
        flags = os.O_RDWR | (os.O_CREAT if self.create else 0)
        try:
            regular_path(self.path)
            self.file = os.fdopen(os.open(self.path, flags, 0o600), "r+b")
            if self.create and self.path.stat().st_size == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, ValueError):
            if self.file is None:
                self.error = "Watcher lock is inaccessible or unsafe."
            if self.file:
                self.file.close()
                self.file = None
            return False

    def close(self):
        if self.file:
            self.file.close()
            self.file = None


def status(directory):
    directory = Path(directory)
    path = directory / "watch-status.json"
    try:
        result = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (ValueError, OSError):
        result = {"warning": "Watcher status file is unreadable."}
    if not isinstance(result, dict):
        result = {"warning": "Watcher status file is invalid."}
    lock = StoreLock(directory / "watch.lock", create=False)
    if not (directory / "watch.lock").is_file():
        running = False
    else:
        acquired = lock.acquire()
        running = not acquired and not lock.error
        if lock.error:
            result["error"] = lock.error
        lock.close()
    result["running"] = running
    return result


# shortcut: metadata polling may miss timestamp-preserving edits; periodic full verification catches them.
def snapshot(kn, root):
    if not root.is_dir():
        return None
    values = {}
    for relative in kn.list_files(root):
        try:
            stat = (root / relative).stat()
            values[relative] = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
        except OSError:
            values[relative] = ("unreadable",)
    return values


def _get_dir_mtimes(root):
    dir_mtimes = {}
    skip_dirs = {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".idea",
        ".vscode",
    }
    try:
        dir_mtimes[""] = root.stat().st_mtime_ns
        for dirpath, dirnames, _ in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
            rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
            if rel_dir == ".":
                rel_dir = ""
            try:
                dir_mtimes[rel_dir] = Path(dirpath).stat().st_mtime_ns
            except OSError:
                pass
    except OSError:
        pass
    return dir_mtimes


def incremental_snapshot(kn, root, state):
    """Fast incremental directory reconciliation using directory mtimes and os.scandir."""
    if not root.is_dir():
        return None
    dir_cache = state.setdefault("dir_mtime_cache", {})
    file_cache = state.setdefault("file_cache", {})
    skip_dirs = {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".idea",
        ".vscode",
    }

    new_dir_mtimes = {}
    new_file_cache = {}

    def scan_dir(dir_path, rel_prefix=""):
        try:
            d_stat = dir_path.stat()
            d_mtime = d_stat.st_mtime_ns
            new_dir_mtimes[rel_prefix] = d_mtime
        except OSError:
            return

        cached_mtime = dir_cache.get(rel_prefix)
        # If this is a subdirectory whose mtime has not changed, reuse cached file entries without stating them
        if rel_prefix and cached_mtime is not None and cached_mtime == d_mtime:
            prefix_slash = f"{rel_prefix}/"
            for rel_file, stat_tuple in file_cache.items():
                if rel_file.startswith(prefix_slash) and "/" not in rel_file[len(prefix_slash) :]:
                    new_file_cache[rel_file] = stat_tuple
            # Still scan for potential subdirectories
            try:
                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in skip_dirs and not entry.name.startswith("."):
                                sub_rel = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
                                scan_dir(Path(entry.path), sub_rel)
            except OSError:
                pass
            return

        # Scan directory entries with os.scandir
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in skip_dirs and not entry.name.startswith("."):
                                sub_rel = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
                                scan_dir(Path(entry.path), sub_rel)
                        elif entry.is_file(follow_symlinks=False):
                            rel_file = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
                            st = Path(entry.path).stat()
                            new_file_cache[rel_file] = (
                                st.st_mtime_ns,
                                st.st_ctime_ns,
                                st.st_size,
                                st.st_ino,
                            )
                    except OSError:
                        rel_file = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
                        new_file_cache[rel_file] = ("unreadable",)
        except OSError:
            pass

    scan_dir(root, "")
    state["dir_mtime_cache"] = new_dir_mtimes
    state["file_cache"] = new_file_cache
    return new_file_cache


class ProjectWatcher:
    def __init__(
        self,
        kn,
        connection,
        debounce=1.0,
        full_interval=300.0,
        min_interval=0.5,
        max_interval=15.0,
        idle_backoff_steps=5,
    ):
        self.kn = kn
        self.db = connection
        self.debounce = debounce
        self.full_interval = full_interval
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.effective_interval = min_interval
        self.idle_backoff_steps = idle_backoff_steps
        self.consecutive_idle = 0
        self.projects = {}

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        indexed = self.db.execute("SELECT id,root FROM projects ORDER BY root").fetchall()
        active = {row["id"] for row in indexed}
        self.projects = {key: value for key, value in self.projects.items() if key in active}

        has_changes = False
        has_pending = False

        for row in indexed:
            project = row["id"]
            root = Path(row["root"])
            state = self.projects.setdefault(
                project,
                {
                    "observed": None,
                    "applied": None,
                    "pending_since": None,
                    "last_change": now,
                    "last_full": None,
                    "dir_mtime_cache": {},
                    "file_cache": {},
                },
            )
            retry = 10 if state.get("error_count", 0) else self.full_interval
            full = (
                state["applied"] is None
                or state["last_full"] is None
                or now - state["last_full"] >= retry
            )
            try:
                if full:
                    current = snapshot(self.kn, root)
                    if current is not None:
                        state["file_cache"] = dict(current)
                        state["dir_mtime_cache"] = _get_dir_mtimes(root)
                else:
                    current = incremental_snapshot(self.kn, root, state)
            except (OSError, subprocess.SubprocessError):
                current = None

            if current is None:
                if state.get("state") != "unavailable":
                    self.db.execute(
                        "INSERT OR IGNORE INTO index_errors SELECT project_id,path FROM files WHERE project_id=?",
                        (project,),
                    )
                    self.db.commit()
                state["state"] = "unavailable"
                state["error"] = "Repository unavailable; existing index preserved."
                state["observed"] = None
                state["applied"] = None
                continue

            if current != state["observed"]:
                state["observed"] = current
                state["last_change"] = now
                if state["pending_since"] is None:
                    state["pending_since"] = now
                has_changes = True

            if state["pending_since"] is not None:
                has_pending = True

            changed = current != state["applied"]
            settled = now - state["last_change"] >= self.debounce
            overdue = state["pending_since"] is not None and now - state["pending_since"] >= 10
            if not full and not (changed and (settled or overdue)):
                continue

            hints = (
                None
                if full
                else {
                    path
                    for path in current.keys() | state["applied"].keys()
                    if current.get(path) != state["applied"].get(path)
                }
            )
            try:
                result = self.kn.sync(root, self.db, changed_hint=hints)
                if "error" in result:
                    raise OSError("Repository became unavailable")
                state.update(
                    state="watching",
                    applied=current,
                    pending_since=None,
                    last_sync=int(time.time()),
                    error_count=result["error_count"],
                    last_result={
                        key: result[key] for key in ("added", "changed", "removed", "error_count")
                    },
                )
                state.pop("error", None)
                if full:
                    state["last_full"] = now
                has_changes = True
            except (OSError, sqlite3.Error, subprocess.SubprocessError):
                self.db.rollback()
                state["state"] = "retrying"
                state["error"] = "Sync failed; retrying without discarding the previous index."
                state["applied"] = None

        # Adaptive interval calculation
        if has_changes or has_pending:
            self.consecutive_idle = 0
            self.effective_interval = self.min_interval
        else:
            self.consecutive_idle += 1
            scale = min(self.consecutive_idle, self.idle_backoff_steps)
            step_size = (self.max_interval - self.min_interval) / max(1, self.idle_backoff_steps)
            self.effective_interval = min(self.max_interval, self.min_interval + scale * step_size)
            try:
                self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                pass

        return {
            project: {
                key: value
                for key, value in state.items()
                if key
                not in (
                    "observed",
                    "applied",
                    "pending_since",
                    "last_change",
                    "last_full",
                    "dir_mtime_cache",
                    "file_cache",
                )
            }
            for project, state in self.projects.items()
        }


def run(kn, interval=2.0, debounce=1.0):
    directory = kn.data_root()
    directory.mkdir(parents=True, exist_ok=True)
    lock = StoreLock(directory / "watch.lock")
    if not lock.acquire():
        return {"error": lock.error} if lock.error else {"already_running": True}
    from onboarding import atomic_write

    stop = directory / "watch-stop.json"
    connection = None
    try:
        stop.unlink(missing_ok=True)
        connection = kn.connect()
        min_int = min(0.5, interval / 2) if interval > 0.5 else interval
        max_int = max(15.0, interval * 4)
        engine = ProjectWatcher(
            kn, connection, debounce=debounce, min_interval=min_int, max_interval=max_int
        )
        while True:
            if stop.exists():
                break
            poll_interval = engine.effective_interval
            report = {
                "pid": os.getpid(),
                "updated_at": int(time.time()),
                "interval_seconds": round(poll_interval, 2),
            }
            try:
                report["projects"] = engine.tick()
            except sqlite3.Error:
                connection.rollback()
                report["error"] = "Database temporarily unavailable; automatic sync will retry."
            atomic_write(directory / "watch-status.json", json.dumps(report).encode())
            deadline = time.monotonic() + poll_interval
            while time.monotonic() < deadline and not stop.exists():
                time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    except KeyboardInterrupt:
        pass
    finally:
        if connection:
            try:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                pass
            connection.close()
        atomic_write(
            directory / "watch-status.json",
            json.dumps({"pid": os.getpid(), "stopped_at": int(time.time())}).encode(),
        )
        lock.close()
    return {"stopped": True}


def ensure(kn, connection):
    row = connection.execute("PRAGMA database_list").fetchone()
    expected = kn.data_root() / "network.sqlite3"
    if not row or not row[2] or Path(row[2]).resolve() != expected.resolve():
        return {
            "running": False,
            "note": "Automatic worker applies to the configured network.sqlite3 store only.",
        }
    if not connection.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
        return {"running": False, "note": "No selected repositories."}
    return start(kn)


def start(kn, force=False, interval=2.0, debounce=1.0):
    if not force and os.environ.get("LAZYTOKEN_DISABLE_AUTOWATCH") == "1":
        return {"running": False, "disabled": True}
    directory = kn.data_root()
    if not (directory / "network.sqlite3").is_file():
        return {"running": False, "note": "Initialize storage and add a selected repository first."}
    existing = status(directory)
    if existing["running"]:
        return existing
    args = [sys.executable]
    if not getattr(sys, "frozen", False):
        args.append(str(Path(kn.__file__).resolve()))
    args += ["watch", "run", "--interval", str(interval), "--debounce", str(debounce)]
    env = {**os.environ, "KN_HOME": str(directory.resolve())}
    options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": env,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(args, **options)
    _CHILDREN[str(directory.resolve())] = process
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = status(directory)
        if result["running"] and result.get("pid") == process.pid:
            return result
        if process.poll() is not None:
            return {
                "running": False,
                "error": "Watcher did not start; run lazytoken watch run to see local errors.",
            }
        time.sleep(0.05)
    return {
        "running": status(directory)["running"],
        "note": "Watcher initialization is in progress; use watch status.",
    }


def stop(kn):
    directory = kn.data_root()

    def reap():
        process = _CHILDREN.pop(str(directory.resolve()), None)
        if process:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _CHILDREN[str(directory.resolve())] = process

    if not status(directory)["running"]:
        reap()
        return {"stopped": True}
    from onboarding import atomic_write

    atomic_write(directory / "watch-stop.json", b"{}")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not status(directory)["running"]:
            reap()
            return {"stopped": True}
        time.sleep(0.1)
    return {
        "error": "Watcher is still finishing a sync. Retry watch stop before lifecycle maintenance."
    }
