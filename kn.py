"""Small, local, deterministic knowledge graph and stdio MCP server."""

from __future__ import annotations

import argparse
import hashlib
import fnmatch
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import features
import broker
import learning
import data_ops
import token_budget
from mcp_schema import TOOLS, WORKFLOW_INSTRUCTIONS, mcp_tools
from source_index import (
    LANGUAGE_CAPABILITIES,
    get_language_capabilities,
    language_for_file,
)

VERSION = "0.5.3"
EXTENSIONS = {
    ".kt",
    ".kts",
    ".java",
    ".swift",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".py",
    ".go",
    ".rs",
    ".cs",
    ".sql",
    ".html",
    ".css",
    ".scss",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".gradle",
    ".md",
}
DENY_NAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    "local.properties",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
DENY_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    ".ssh",
    ".aws",
    "secrets",
    "credentials",
    "build",
    "node_modules",
    "dist",
    "backups",
    "runtime",
    "models",
    "test-results",
    "playwright-report",
    "xcuserdata",
    ".vercel",
    ".pytest_cache",
    ".cache",
    ".storage_vault",
    ".yarn",
    ".pnpm-store",
}
SYMBOLS = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|open|override|suspend|async|export|default|data|sealed|inline|fun|class|object|interface|enum|type|function|const|let|var|def|func|struct|trait|impl)\s+){1,6}(?:fun\s+|function\s+|def\s+|func\s+|class\s+|interface\s+|object\s+|enum\s+|struct\s+|trait\s+|type\s+)?([A-Za-z_$][\w$]*)\s*(?:[<(=:{]|$)"
)
IMPORTS = re.compile(r"^\s*(?:import\s+(?:static\s+)?|from\s+)([\w.$/]+)")


def split_words(value: str) -> list[str]:
    value = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", value)
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return re.findall(r"[^\W_]+", value.casefold())


def search_words(value: str) -> set[str]:
    return set(split_words(value))


def default_data_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        p_ts = Path(local) / "TokSmart"
        p_rm = Path(local) / "RepoMind"
        p_lt = Path(local) / "LazyToken"
        if (p_ts / "network.sqlite3").is_file():
            return p_ts
        if (p_rm / "network.sqlite3").is_file():
            return p_rm
        if (p_lt / "network.sqlite3").is_file():
            return p_lt
        if p_ts.is_dir():
            return p_ts
        return p_lt
    home = Path.home()
    p_ts = home / ".local" / "share" / "TokSmart"
    p_rm = home / ".local" / "share" / "RepoMind"
    p_lt = home / ".local" / "share" / "LazyToken"
    if (p_ts / "network.sqlite3").is_file():
        return p_ts
    if (p_rm / "network.sqlite3").is_file():
        return p_rm
    if (p_lt / "network.sqlite3").is_file():
        return p_lt
    if p_ts.is_dir():
        return p_ts
    return p_lt


def legacy_data_roots() -> list[Path]:
    candidates = [
        Path.home() / ".theekhai-knowledge",
        Path.home() / ".local" / "share" / "LazyToken",
        Path.home() / ".local" / "share" / "RepoMind",
    ]
    if os.environ.get("LOCALAPPDATA"):
        candidates.insert(0, Path(os.environ["LOCALAPPDATA"]) / "RepoMind")
        candidates.insert(1, Path(os.environ["LOCALAPPDATA"]) / "LazyToken")
        candidates.insert(2, Path(os.environ["LOCALAPPDATA"]) / "TheekHai" / "KnowledgeNetwork")
    return [path for path in candidates if (path / "network.sqlite3").is_file()]


def data_root() -> Path:
    configured = os.environ.get("KN_HOME")
    return Path(configured) if configured else default_data_root()


def db_path() -> Path:
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "network.sqlite3"


def _init_schema_and_migrations(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
      CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, root TEXT NOT NULL, updated_at INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS files(project_id TEXT NOT NULL, path TEXT NOT NULL, digest TEXT NOT NULL, bytes INTEGER NOT NULL, PRIMARY KEY(project_id,path));
      CREATE TABLE IF NOT EXISTS symbols(project_id TEXT NOT NULL, path TEXT NOT NULL, name TEXT NOT NULL, line INTEGER NOT NULL, PRIMARY KEY(project_id,path,name,line));
      CREATE TABLE IF NOT EXISTS imports(project_id TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, PRIMARY KEY(project_id,source,target));
      CREATE TABLE IF NOT EXISTS assets(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, summary TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, scope TEXT NOT NULL DEFAULT 'global', project_id TEXT NOT NULL DEFAULT '');
      CREATE TABLE IF NOT EXISTS asset_projects(asset_id INTEGER NOT NULL, project_id TEXT NOT NULL, relation TEXT NOT NULL DEFAULT 'used_in', PRIMARY KEY(asset_id,project_id,relation));
      CREATE TABLE IF NOT EXISTS asset_links(source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, relation TEXT NOT NULL, weight REAL NOT NULL DEFAULT 1.0, evidence TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL, PRIMARY KEY(source_id,target_id,relation));
      CREATE TABLE IF NOT EXISTS asset_link_evidence(source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, relation TEXT NOT NULL, scope TEXT NOT NULL, weight REAL NOT NULL, evidence TEXT NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY(source_id,target_id,relation,scope));
      CREATE TABLE IF NOT EXISTS retrievals(at INTEGER NOT NULL, project_id TEXT NOT NULL DEFAULT '', query_chars INTEGER NOT NULL, result_chars INTEGER NOT NULL, estimated_tokens INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS task_measurements(id INTEGER PRIMARY KEY, task TEXT NOT NULL, baseline_tokens INTEGER NOT NULL, network_tokens INTEGER NOT NULL, indexing_tokens INTEGER NOT NULL, measured_at INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS symbol_calls(project_id TEXT NOT NULL, caller_path TEXT NOT NULL, caller_symbol TEXT NOT NULL, callee_name TEXT NOT NULL, receiver TEXT NOT NULL DEFAULT '', resolved_callee TEXT NOT NULL DEFAULT '', confidence TEXT NOT NULL DEFAULT 'provisional', caller_symbol_id TEXT NOT NULL DEFAULT '', callee_symbol_id TEXT NOT NULL DEFAULT '', resolution_method TEXT NOT NULL DEFAULT 'unresolved', line INTEGER NOT NULL, PRIMARY KEY(project_id,caller_path,caller_symbol,callee_name,receiver,line));
      CREATE TABLE IF NOT EXISTS index_skipped_files(project_id TEXT NOT NULL, path TEXT NOT NULL, reason TEXT NOT NULL, bytes INTEGER NOT NULL, PRIMARY KEY(project_id,path));
      CREATE TABLE IF NOT EXISTS sync_generations(project_id TEXT PRIMARY KEY, generation INTEGER NOT NULL);
      CREATE INDEX IF NOT EXISTS symbol_calls_callee_idx ON symbol_calls(project_id, callee_name);
      CREATE INDEX IF NOT EXISTS symbol_calls_resolved_idx ON symbol_calls(project_id, resolved_callee);
      CREATE INDEX IF NOT EXISTS symbol_calls_caller_id_idx ON symbol_calls(project_id, caller_symbol_id);
      CREATE INDEX IF NOT EXISTS symbol_calls_method_idx ON symbol_calls(project_id, resolution_method);
      CREATE INDEX IF NOT EXISTS symbol_name_idx ON symbols(name);
      CREATE INDEX IF NOT EXISTS asset_name_idx ON assets(name);
      CREATE INDEX IF NOT EXISTS asset_link_source_idx ON asset_links(source_id);
      CREATE INDEX IF NOT EXISTS asset_link_target_idx ON asset_links(target_id);
      CREATE INDEX IF NOT EXISTS asset_link_evidence_scope_idx ON asset_link_evidence(scope);
      CREATE INDEX IF NOT EXISTS asset_link_evidence_endpoints_idx ON asset_link_evidence(source_id, target_id, scope);
      CREATE INDEX IF NOT EXISTS asset_link_evidence_target_idx ON asset_link_evidence(target_id, scope);
      CREATE INDEX IF NOT EXISTS asset_projects_project_idx ON asset_projects(project_id, asset_id);
      CREATE INDEX IF NOT EXISTS imports_target_idx ON imports(project_id, target);
    """
    )
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(assets)")}
    if "scope" not in cols:
        conn.execute("ALTER TABLE assets ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'")
    if "project_id" not in cols:
        conn.execute("ALTER TABLE assets ADD COLUMN project_id TEXT NOT NULL DEFAULT ''")
    call_cols = {r["name"] for r in conn.execute("PRAGMA table_info(symbol_calls)")}
    if "receiver" not in call_cols:
        conn.execute("ALTER TABLE symbol_calls ADD COLUMN receiver TEXT NOT NULL DEFAULT ''")
    if "resolved_callee" not in call_cols:
        conn.execute("ALTER TABLE symbol_calls ADD COLUMN resolved_callee TEXT NOT NULL DEFAULT ''")
    if "confidence" not in call_cols:
        conn.execute(
            "ALTER TABLE symbol_calls ADD COLUMN confidence TEXT NOT NULL DEFAULT 'provisional'"
        )
    if "caller_symbol_id" not in call_cols:
        conn.execute(
            "ALTER TABLE symbol_calls ADD COLUMN caller_symbol_id TEXT NOT NULL DEFAULT ''"
        )
    if "callee_symbol_id" not in call_cols:
        conn.execute(
            "ALTER TABLE symbol_calls ADD COLUMN callee_symbol_id TEXT NOT NULL DEFAULT ''"
        )
    if "resolution_method" not in call_cols:
        conn.execute(
            "ALTER TABLE symbol_calls ADD COLUMN resolution_method TEXT NOT NULL DEFAULT 'unresolved'"
        )
    # Upgrade pre-scope links by attributing them to the project that uses both endpoints.
    conn.execute(
        """INSERT OR IGNORE INTO asset_link_evidence(source_id,target_id,relation,scope,weight,evidence,updated_at)
      SELECT l.source_id,l.target_id,l.relation,
        COALESCE((SELECT CASE WHEN count(DISTINCT a.project_id)=1 THEN min(a.project_id) END FROM asset_projects a JOIN asset_projects b ON b.project_id=a.project_id
          WHERE a.asset_id=l.source_id AND b.asset_id=l.target_id),'__legacy_unscoped__'),
        l.weight,l.evidence,l.updated_at FROM asset_links l
        WHERE NOT EXISTS (SELECT 1 FROM asset_link_evidence e WHERE e.source_id=l.source_id AND e.target_id=l.target_id AND e.relation=l.relation)"""
    )
    conn.commit()
    features.migrate(conn)


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or db_path()
    existed = Path(target).is_file() and Path(target).stat().st_size > 0
    conn = sqlite3.connect(target, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    tables = set()
    version = 0
    if existed:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = (
            conn.execute("SELECT coalesce(max(version),0) FROM lazytoken_migrations").fetchone()[0]
            if "lazytoken_migrations" in tables
            else 0
        )
        if version > 7:
            conn.close()
            raise RuntimeError(
                "Database was created by a newer TokSmart version; upgrade the application before opening it."
            )
        if tables and version < 7:
            # SQLite's backup API includes committed WAL data and leaves the original intact.
            stamp = f"{time.time_ns()}"
            backup_path = Path(target).with_name(Path(target).name + f".pre-v7-{stamp}.sqlite3")
            descriptor = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            try:
                backup = sqlite3.connect(backup_path)
                try:
                    conn.backup(backup)
                finally:
                    backup.close()
            except Exception:
                backup_path.unlink(missing_ok=True)
                conn.close()
                raise
    if (not existed) or ("projects" not in tables) or (version < 7):
        _init_schema_and_migrations(conn)
    return conn


def resolve_project(value: str, conn: sqlite3.Connection) -> str:
    if not value or value == "*":
        return value
    row = conn.execute("SELECT id FROM projects WHERE id=? OR root=?", (value, value)).fetchone()
    if row:
        return str(row[0])
    try:
        if Path(value).is_absolute():
            canonical = str(Path(value).resolve())
            row = conn.execute(
                "SELECT id FROM projects WHERE id=? OR root=?", (canonical, canonical)
            ).fetchone()
            return str(row[0]) if row else ""
    except (OSError, ValueError, RuntimeError):
        return ""
    matches = [
        str(r[0])
        for r in conn.execute("SELECT id FROM projects")
        if Path(str(r[0])).name.casefold() == value.casefold()
    ]
    return matches[0] if len(matches) == 1 else ""


def safe_relative(s: str) -> bool:
    p = Path(s)
    name = p.name.lower()
    sensitive_json = p.suffix.lower() == ".json" and any(
        word in name
        for word in (
            "credential",
            "secret",
            "service-account",
            "service_account",
            "private-key",
            "private_key",
            "token",
        )
    )
    return (
        not p.is_absolute()
        and not p.drive
        and ".." not in p.parts
        and (
            p.suffix.lower() in EXTENSIONS
            or name in {"go.mod", "setup.cfg"}
            or bool(re.fullmatch(r"requirements(?:[-_.][a-z0-9_-]+)?\.txt", name))
        )
        and name not in DENY_NAMES
        and not sensitive_json
        and not any(part.lower().startswith(".env") for part in p.parts)
        and not any(part.lower() in DENY_DIRS for part in p.parts)
        and not p.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pem", ".key"}
    )


def safe_file(root: Path, relative: str, errors: list[str] | None = None) -> bool:
    if not safe_relative(relative):
        return False
    try:
        root = root.resolve()
        candidate = root / relative
        if not candidate.resolve().is_relative_to(root):
            return False
        current = root
        for part in Path(relative).parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return False
        return stat.S_ISREG(info.st_mode)
    except FileNotFoundError:
        return False
    except OSError:
        if errors is not None:
            errors.append(relative)
        return False


def read_project_file(
    root: Path, relative: str, limit: int = 1_000_001, *, ignore_file: bool = False
) -> bytes:
    """Read through held directory handles, refusing links at every project path component."""
    check_path = (
        str(Path(relative).with_name("ignore-rules.py"))
        if ignore_file and Path(relative).name == ".gitignore"
        else relative
    )
    if not safe_relative(check_path):
        raise OSError("Ineligible project path")
    root = Path(os.path.abspath(root))
    parts = Path(relative).parts
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetFileInformationByHandleEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]

        class Attributes(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

        handles = []
        try:
            absolute_parts = (root / relative).parts
            current = Path(absolute_parts[0])
            for index, part in enumerate(absolute_parts):
                if index:
                    current /= part
                final = index == len(absolute_parts) - 1
                handle = kernel.CreateFileW(
                    str(current), 0x80000000 if final else 0x80, 3, None, 3, 0x02200000, None
                )
                if handle == ctypes.c_void_p(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                handles.append(handle)
                info = Attributes()
                if not kernel.GetFileInformationByHandleEx(
                    handle, 9, ctypes.byref(info), ctypes.sizeof(info)
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                if info.attributes & 0x400 or (final and info.attributes & 0x10):
                    raise OSError("Link or directory in project path")
            fd = msvcrt.open_osfhandle(handles[-1], os.O_RDONLY | os.O_BINARY)
            handles.pop()
            with os.fdopen(fd, "rb") as source:
                return source.read(limit)
        finally:
            for handle in reversed(handles):
                kernel.CloseHandle(handle)
    else:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        root_parts = root.parts
        fd = os.open(root_parts[0], flags | os.O_DIRECTORY)
        try:
            for part in root_parts[1:]:
                child = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
                os.close(fd)
                fd = child
            for index, part in enumerate(parts):
                child = os.open(
                    part, flags | (os.O_DIRECTORY if index < len(parts) - 1 else 0), dir_fd=fd
                )
                os.close(fd)
                fd = child
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("Project path is not a regular file")
            with os.fdopen(fd, "rb") as source:
                fd = -1
                return source.read(limit)
        finally:
            if fd != -1:
                os.close(fd)


def _ignore_rules(
    directory: Path, root: Path, errors: list[str] | None = None
) -> list[tuple[str, str, bool]]:
    """Read positive local ignore patterns; re-inclusions stay excluded in fallback mode."""
    try:
        raw = read_project_file(
            root, str((directory / ".gitignore").relative_to(root)), ignore_file=True
        )
        if len(raw) > 1_000_000:
            if errors is not None:
                errors.append(directory.relative_to(root).as_posix())
            return [(directory.relative_to(root).as_posix(), "*", False)]
        lines = raw.decode("utf-8-sig").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError):
        if errors is not None:
            errors.append(directory.relative_to(root).as_posix())
        return [(directory.relative_to(root).as_posix(), "*", False)]
    base = directory.relative_to(root).as_posix()
    result = []
    for line in lines:
        line = line.rstrip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        # Escaped gitignore syntax is deliberately fail-closed in the no-Git fallback.
        if "\\" in line:
            return [(base, "*", False)]
        is_directory = line.endswith("/")
        pattern = line.strip("/")
        if pattern:
            result.append((base, pattern.casefold(), is_directory))
    return result


def _ignored(relative: str, is_dir: bool, rules: list[tuple[str, str, bool]]) -> bool:
    for base, pattern, dir_only in rules:
        prefix = "" if base == "." else base.rstrip("/") + "/"
        if prefix and not relative.casefold().startswith(prefix.casefold()):
            continue
        local = relative[len(prefix) :].casefold()
        parts = local.split("/")
        variants = {pattern, pattern.replace("**/", "")}
        for candidate in variants:
            if "/" not in candidate:
                matches = [
                    i for i, part in enumerate(parts) if fnmatch.fnmatchcase(part, candidate)
                ]
                if any(not dir_only or i < len(parts) - 1 or is_dir for i in matches):
                    return True
            else:
                ancestors = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
                for i, value in enumerate(ancestors):
                    if fnmatch.fnmatchcase(value, candidate) and (
                        not dir_only or i < len(ancestors) - 1 or is_dir
                    ):
                        return True
    return False


def fallback_list_files(root: Path, errors: list[str] | None = None) -> list[str]:
    """Walk without following links. Ignore negations conservatively when Git is unavailable."""
    root = root.resolve()
    found = []
    rules_by_dir = {root: _ignore_rules(root, root, errors)}

    def walk_error(error):
        raise error

    for current, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        directory = Path(current)
        if directory != root:
            rules_by_dir[directory] = rules_by_dir[directory.parent] + _ignore_rules(
                directory, root, errors
            )
        rules = rules_by_dir[directory]
        kept = []
        for name in dirs:
            p = directory / name
            rel = p.relative_to(root).as_posix()
            try:
                attrs = getattr(p.lstat(), "st_file_attributes", 0)
            except FileNotFoundError:
                continue
            except OSError:
                if errors is not None:
                    errors.append(rel)
                continue
            if (
                name.casefold() in DENY_DIRS
                or p.is_symlink()
                or attrs & 0x400
                or _ignored(rel, True, rules)
            ):
                continue
            kept.append(name)
        dirs[:] = kept
        for name in files:
            rel = (directory / name).relative_to(root).as_posix()
            if not _ignored(rel, False, rules) and safe_file(root, rel, errors):
                found.append(rel)
    return sorted(found)


def list_files(root: Path, errors: list[str] | None = None) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "-co", "--exclude-standard"],
            capture_output=True,
            timeout=30,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ).stdout
        paths = [os.fsdecode(item) for item in out.split(b"\0") if item]
    except (FileNotFoundError, subprocess.SubprocessError):
        return fallback_list_files(root, errors)
    return sorted(p for p in paths if safe_file(root, p, errors))


def sync(
    root: Path, conn: sqlite3.Connection, changed_hint: set[str] | None = None, _attempt=0
) -> dict:
    if not root.is_dir():
        return {"error": "Repository is unavailable; the previous index was preserved."}
    original = Path(os.path.abspath(root))
    root = original.resolve()
    orig_long = str(original.parent.resolve() / original.name)
    if (root != Path(orig_long) or original.is_symlink()) and (
        conn.execute(
            "SELECT 1 FROM projects WHERE id=? OR root=?", (str(original), str(original))
        ).fetchone()
        or conn.execute(
            "SELECT 1 FROM projects WHERE id=? OR root=?", (orig_long, orig_long)
        ).fetchone()
    ):
        return {"error": "Indexed project path changed through a link; previous index preserved."}
    project = str(root)

    # 1. Non-locking reads to get baseline state
    generation = conn.execute(
        "SELECT generation FROM sync_generations WHERE project_id=?", (project,)
    ).fetchone()
    generation = generation[0] if generation else 0
    index_state = conn.execute(
        "SELECT extractor_version FROM index_state WHERE project_id=?", (project,)
    ).fetchone()
    reextract = not index_state or index_state[0] < 6

    existing_files = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT path, digest FROM files WHERE project_id=?", (project,)
        ).fetchall()
    }
    existing_skipped = {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            "SELECT path, reason, bytes FROM index_skipped_files WHERE project_id=?", (project,)
        ).fetchall()
    }

    present: set[str] = set()
    added = changed = removed = 0
    errors = []
    changed_paths: list[str] = []
    removed_paths: list[str] = []

    # In-memory staging of database mutations
    files_to_write = []
    skipped_to_write = []
    skipped_to_delete = []
    symbols_to_write = []
    calls_to_write = []
    imports_to_write = []
    paths_to_clean = []

    # 2. File discovery, reading, hashing, and AST parsing completely in memory
    discovery_errors: list[str] = []
    try:
        discovered = list_files(root, discovery_errors)
    except OSError:
        return {"error": "Repository discovery failed; the previous index was preserved."}
    for rel in discovered:
        norm_rel = rel.replace("\\", "/").strip().lower()
        if any(
            re.search(pat, norm_rel)
            for pat in (
                r"(^|/)\.env(\.|$)",
                r"\.(key|pem|pkcs12|pfx|p12)$",
                r"(^|/)id_(rsa|dsa|ecdsa|ed25519)($|\.)",
                r"(^|/)(credentials|secrets|token|master\.key)(\.json|\.ya?ml|\.txt)?$",
            )
        ):
            present.discard(rel)
            skipped_to_write.append((project, rel, "sensitive_credential_path", 0))
            continue
        path = root / rel
        present.add(rel)
        try:
            if changed_hint is not None and rel not in changed_hint and not reextract:
                if rel in existing_files:
                    continue
            raw = read_project_file(root, rel)
            if len(raw) > 1_000_000 or b"\x00" in raw:
                present.discard(rel)
                reason = "oversized" if len(raw) > 1_000_000 else "binary"
                skipped_to_write.append((project, rel, reason, len(raw)))
                continue
            if rel in existing_skipped:
                skipped_to_delete.append((project, rel))
            digest = hashlib.sha256(raw).hexdigest()
            present.add(rel)
            old_digest = existing_files.get(rel)
            if old_digest and old_digest == digest and not reextract:
                continue
            if old_digest:
                changed += 1
            else:
                added += 1
            body = raw.decode("utf-8", errors="replace")
            files_to_write.append((project, rel, digest, len(raw)))
            changed_paths.append(rel)
            paths_to_clean.append((project, rel))

            if path.suffix.lower() == ".py":
                from source_index import python_calls, python_imports, python_symbols

                py_syms = python_symbols(body)
                if py_syms:
                    symbols_to_write.extend(
                        [(project, rel, name, lineno) for name, lineno in py_syms]
                    )
                else:
                    for n, line in enumerate(body.splitlines(), 1):
                        m = SYMBOLS.match(line)
                        if m:
                            symbols_to_write.append((project, rel, m.group(1), n))
                for c in python_calls(body):
                    caller_sym = c["caller_symbol"]
                    caller_line = c.get("caller_line", 0)
                    caller_id = f"{project}:{rel}:{caller_sym}:{caller_line}"
                    callee_resolved = c.get("resolved_callee", c["callee_name"])
                    callee_id = f"{project}::{callee_resolved}"
                    method = c.get("resolution_method", "unresolved")
                    calls_to_write.append(
                        (
                            project,
                            rel,
                            caller_sym,
                            c["callee_name"],
                            c.get("receiver", ""),
                            callee_resolved,
                            c.get("confidence", "provisional"),
                            caller_id,
                            callee_id,
                            method,
                            c["line"],
                        )
                    )
                imports_to_write.extend([(project, rel, target) for target in python_imports(body)])
            elif path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
                from source_index import (
                    javascript_calls,
                    javascript_imports,
                    javascript_symbols,
                )

                js_syms = javascript_symbols(body)
                if js_syms:
                    symbols_to_write.extend(
                        [(project, rel, name, lineno) for name, lineno in js_syms]
                    )
                else:
                    for n, line in enumerate(body.splitlines(), 1):
                        m = SYMBOLS.match(line)
                        if m:
                            symbols_to_write.append((project, rel, m.group(1), n))
                for c in javascript_calls(body):
                    caller_sym = c["caller_symbol"]
                    caller_line = c.get("caller_line", 0)
                    caller_id = f"{project}:{rel}:{caller_sym}:{caller_line}"
                    callee_resolved = c.get("resolved_callee", c["callee_name"])
                    callee_id = f"{project}::{callee_resolved}"
                    method = c.get("resolution_method", "unresolved")
                    calls_to_write.append(
                        (
                            project,
                            rel,
                            caller_sym,
                            c["callee_name"],
                            c.get("receiver", ""),
                            callee_resolved,
                            c.get("confidence", "provisional"),
                            caller_id,
                            callee_id,
                            method,
                            c["line"],
                        )
                    )
                imports_to_write.extend(
                    [(project, rel, target) for target in javascript_imports(body)]
                )
            else:
                for n, line in enumerate(body.splitlines(), 1):
                    m = SYMBOLS.match(line)
                    if m:
                        symbols_to_write.append((project, rel, m.group(1), n))
                    imp = IMPORTS.match(line)
                    if imp:
                        imports_to_write.append((project, rel, imp.group(1)))
        except OSError:
            errors.append(rel)
            skipped_to_write.append((project, rel, "unreadable", 0))
            continue

    # Preserve indexed paths hidden by a transient discovery failure.
    for rel in discovery_errors:
        errors.append(rel)
        affected = {
            path
            for path in existing_files
            if rel == "." or path == rel or path.startswith(rel + "/")
        }
        present.update(affected)
        errors.extend(sorted(affected - set(errors)))
    errors = list(dict.fromkeys(errors))

    # Identify removed files
    files_to_remove = []
    for old_path in existing_files:
        if old_path not in present:
            files_to_remove.append((project, old_path))
            paths_to_clean.append((project, old_path))
            removed_paths.append(old_path)
            removed += 1

    # Check index_skipped_files that no longer exist on disk
    skipped_prune = []
    for old_path in existing_skipped:
        try:
            (root / old_path).lstat()
        except FileNotFoundError:
            skipped_prune.append((project, old_path))
        except OSError:
            if old_path not in errors:
                errors.append(old_path)

    # 3. Short atomic write transaction
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute(
            "SELECT generation FROM sync_generations WHERE project_id=?", (project,)
        ).fetchone()
        if (current[0] if current else 0) != generation:
            conn.rollback()
            if _attempt >= 19:
                return {"error": "Index changed during sync; retry after concurrent writes finish."}
            time.sleep(min(0.01 * (_attempt + 1), 0.1))
            return sync(root, conn, changed_hint=None, _attempt=_attempt + 1)
        conn.execute(
            "INSERT INTO projects(id,root,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET root=excluded.root",
            (project, project, int(time.time())),
        )
        if skipped_to_delete:
            conn.executemany(
                "DELETE FROM index_skipped_files WHERE project_id=? AND path=?", skipped_to_delete
            )
        if skipped_to_write:
            conn.executemany(
                "INSERT OR REPLACE INTO index_skipped_files VALUES(?,?,?,?)", skipped_to_write
            )
        if paths_to_clean:
            conn.executemany("DELETE FROM symbols WHERE project_id=? AND path=?", paths_to_clean)
            conn.executemany("DELETE FROM imports WHERE project_id=? AND source=?", paths_to_clean)
            conn.executemany(
                "DELETE FROM symbol_calls WHERE project_id=? AND caller_path=?", paths_to_clean
            )
        if files_to_remove:
            conn.executemany("DELETE FROM files WHERE project_id=? AND path=?", files_to_remove)
            conn.executemany(
                "DELETE FROM index_skipped_files WHERE project_id=? AND path=?", files_to_remove
            )
        if files_to_write:
            conn.executemany("INSERT OR REPLACE INTO files VALUES(?,?,?,?)", files_to_write)
        if symbols_to_write:
            conn.executemany("INSERT OR IGNORE INTO symbols VALUES(?,?,?,?)", symbols_to_write)
        if calls_to_write:
            conn.executemany(
                "INSERT OR IGNORE INTO symbol_calls VALUES(?,?,?,?,?,?,?,?,?,?,?)", calls_to_write
            )
        if imports_to_write:
            conn.executemany("INSERT OR IGNORE INTO imports VALUES(?,?,?)", imports_to_write)
        if skipped_prune:
            conn.executemany(
                "DELETE FROM index_skipped_files WHERE project_id=? AND path=?", skipped_prune
            )
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (int(time.time()), project))
        conn.execute("DELETE FROM index_errors WHERE project_id=?", (project,))
        conn.executemany(
            "INSERT INTO index_errors VALUES(?,?)", [(project, path) for path in errors]
        )
        conn.execute("INSERT OR REPLACE INTO index_state VALUES(?,6)", (project,))
        conn.execute(
            "INSERT INTO sync_generations VALUES(?,1) ON CONFLICT(project_id) DO UPDATE SET generation=generation+1",
            (project,),
        )
        features.refresh_fts(conn, project, changed_paths, removed_paths)
        import frameworks

        frameworks.update(conn, project)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    all_skipped = [
        {"path": r[0], "reason": r[1], "bytes": r[2]}
        for r in conn.execute(
            "SELECT path, reason, bytes FROM index_skipped_files WHERE project_id=? ORDER BY path",
            (project,),
        ).fetchall()
    ]

    # 4. Telemetry: Language breakdown
    language_breakdown = {}
    for p in present:
        lang = language_for_file(p)
        tier = LANGUAGE_CAPABILITIES.get(lang, {}).get("tier", "text_only")
        entry = language_breakdown.setdefault(lang, {"files": 0, "tier": tier})
        entry["files"] += 1

    return {
        "added": added,
        "changed": changed,
        "removed": removed,
        "unchanged": max(0, len(present) - added - changed - len(errors)),
        "files": len(present),
        "skipped": all_skipped,
        "skipped_count": len(all_skipped),
        "error_count": len(errors),
        "error_paths": errors,
        "language_breakdown": language_breakdown,
    }


def search(
    query: str, conn: sqlite3.Connection, project: str = "", limit: int = 8
) -> dict[str, Any]:
    query_parts = [x for x in re.findall(r"[\w.$/-]+", query) if len(x) > 1]
    terms = (
        split_words(query_parts[0])
        if len(query_parts) == 1
        else [x.casefold() for x in query_parts]
    )
    terms = list(dict.fromkeys(terms))[:8]
    if not terms:
        return {"query": query, "results": []}
    requested_project = project
    project = resolve_project(project, conn) if project else ""
    if requested_project and not project:
        return {"error": "Unknown project. Run sync_project with its absolute path first."}
    rows: list[dict[str, Any]] = []
    term_sql = " OR ".join("lower(name) LIKE ? OR lower(path) LIKE ?" for _ in terms)
    params = tuple(pattern for t in terms for pattern in ("%" + t + "%", "%" + t + "%"))
    where = " AND project_id=?" if project else ""
    if project:
        params = (*params, project)
    symbols = conn.execute(
        f"SELECT project_id,path,name,line FROM symbols WHERE ({term_sql}){where} LIMIT 300", params
    ).fetchall()
    scored = []
    for row in symbols:
        name_words = search_words(row["name"])
        path_words = search_words(row["path"])
        name_hits = sum(1 for t in terms if t in name_words)
        path_hits = sum(1 for t in terms if t in path_words)
        score = (2 * name_hits + path_hits) / len(terms)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: (-x[0], x[1]["name"].casefold(), x[1]["path"]))
    for score, row in scored[:limit]:
        rows.append(
            {
                "type": "symbol",
                "project": Path(row["project_id"]).name,
                "path": row["path"],
                "name": row["name"],
                "line": row["line"],
                "activation": 1.0,
                "match_score": round(score, 2),
            }
        )
    asset_match = " OR ".join("lower(name||' '||summary||' '||tags) LIKE ?" for _ in terms)
    asset_terms = tuple("%" + term + "%" for term in terms)
    if project:
        arows = conn.execute(
            f"SELECT id,kind,name,summary,tags,source FROM assets WHERE (scope='global' OR (scope='project' AND project_id=?)) AND ({asset_match})",
            (project, *asset_terms),
        ).fetchall()
        edge_scope = "(scope='*' OR scope=?)"
        edge_args = (project,)
    else:
        arows = conn.execute(
            f"SELECT id,kind,name,summary,tags,source FROM assets WHERE scope='global' AND ({asset_match})",
            asset_terms,
        ).fetchall()
        edge_scope = "scope='*'"
        edge_args = ()
    activation: dict[int, float] = {
        int(r["id"]): len(set(terms) & search_words(" ".join((r["name"], r["summary"], r["tags"]))))
        / len(terms)
        for r in arows
    }
    activation = {asset_id: score for asset_id, score in activation.items() if score}
    activation = {
        asset_id: score
        for asset_id, score in activation.items()
        if not conn.execute(
            "SELECT 1 FROM memory_proposals WHERE asset_id=? AND status='superseded'", (asset_id,)
        ).fetchone()
    }
    frontier = dict(activation)
    # Two-hop weighted spreading activation; it is deterministic graph traversal, not ML inference.
    for _ in range(2):
        following: dict[int, float] = {}
        for node_id, score in frontier.items():
            for edge in conn.execute(
                f"SELECT source_id,target_id,weight FROM asset_link_evidence WHERE {edge_scope} AND (source_id=? OR target_id=?)",
                (*edge_args, node_id, node_id),
            ):
                neighbor = int(
                    edge["target_id"] if edge["source_id"] == node_id else edge["source_id"]
                )
                if conn.execute(
                    "SELECT 1 FROM memory_proposals WHERE asset_id=? AND status='superseded'",
                    (neighbor,),
                ).fetchone():
                    continue
                visible = (
                    conn.execute(
                        "SELECT 1 FROM assets WHERE id=? AND (scope='global' OR (scope='project' AND project_id=?))",
                        (neighbor, project),
                    ).fetchone()
                    if project
                    else conn.execute(
                        "SELECT 1 FROM assets WHERE id=? AND scope='global'", (neighbor,)
                    ).fetchone()
                )
                if not visible:
                    continue
                candidate = score * float(edge["weight"]) * 0.7
                if candidate > activation.get(neighbor, 0) and candidate > following.get(
                    neighbor, 0
                ):
                    following[neighbor] = candidate
        activation.update(following)
        frontier = following
    asset_ids = sorted(activation, key=lambda k: (-activation[k], k))[:limit]
    for asset_id in asset_ids:
        r = conn.execute(
            "SELECT id,kind,name,summary,tags,source FROM assets WHERE id=?", (asset_id,)
        ).fetchone()
        if not r:
            continue
        used = (
            [
                Path(x[0]).name
                for x in conn.execute(
                    "SELECT project_id FROM asset_projects WHERE asset_id=? AND project_id=?",
                    (asset_id, project),
                )
            ]
            if project
            else []
        )
        item = {
            "type": "asset",
            "kind": r["kind"],
            "name": r["name"],
            "summary": r["summary"],
            "tags": r["tags"],
            "source": r["source"],
            "used_in": used,
            "activation": round(activation[asset_id], 3),
        }
        memory = conn.execute(
            "SELECT id FROM memory_proposals WHERE asset_id=?", (asset_id,)
        ).fetchone()
        if memory:
            item.update(features.health(conn, memory["id"]))
            item["activation"] = round(item["activation"] * (0.5 + 0.5 * item["confidence"]), 3)
            if item["freshness"] == "stale":
                item["activation"] = round(item["activation"] * 0.3, 3)
        rows.append(item)
    rows.sort(
        key=lambda r: (
            -r["activation"],
            -r.get("match_score", 0),
            0 if r["type"] == "symbol" else 1,
            r["name"],
        )
    )
    rows = rows[:limit]
    out = json.dumps({"query": query, "results": rows}, ensure_ascii=False, separators=(",", ":"))
    try:
        conn.execute(
            "INSERT INTO retrievals VALUES(?,?,?,?,?)",
            (int(time.time()), project, len(query), len(out), estimate(out)),
        )
        conn.commit()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass
    return {"query": query, "results": rows, "estimated_tokens": estimate(out)}


def estimate(text: str) -> int:
    # Planning estimate only; real model token counts vary by tokenizer.
    return (len(text) + 3) // 4


def context(project: str, conn: sqlite3.Connection, limit: int = 30) -> dict[str, Any]:
    resolved = resolve_project(project, conn)
    row = (
        conn.execute("SELECT id,root,updated_at FROM projects WHERE id=?", (resolved,)).fetchone()
        if resolved
        else None
    )
    if not row:
        return {"error": "Project is not indexed. Run sync_project with its absolute path."}
    files = conn.execute(
        "SELECT path,bytes FROM files WHERE project_id=? ORDER BY path LIMIT 10", (row["id"],)
    ).fetchall()
    syms = conn.execute(
        "SELECT path,name,line FROM symbols WHERE project_id=? ORDER BY path,line LIMIT 12",
        (row["id"],),
    ).fetchall()
    imports = conn.execute(
        "SELECT source,target FROM imports WHERE project_id=? ORDER BY source,target LIMIT 8",
        (row["id"],),
    ).fetchall()
    result = {
        "project": Path(row["root"]).name,
        "files": [dict(r) for r in files],
        "symbols": [dict(r) for r in syms],
        "imports": [dict(r) for r in imports],
    }
    result["estimated_tokens"] = estimate(json.dumps(result, separators=(",", ":")))
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    try:
        conn.execute(
            "INSERT INTO retrievals VALUES(?,?,?,?,?)",
            (int(time.time()), row["id"], 0, len(encoded), result["estimated_tokens"]),
        )
        conn.commit()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass
    return result


def add_asset(args: dict[str, Any], conn: sqlite3.Connection) -> dict[str, Any]:
    kind, name, summary = (str(args.get(k, "")).strip() for k in ("kind", "name", "summary"))
    if kind in {"lesson", "decision", "pattern", "component"}:
        return {
            "error": "Propose project memories through toksmart/propose and approve them explicitly through review."
        }
    if kind not in {
        "library",
        "package",
        "framework",
        "skill",
        "plugin",
        "mcp",
        "component",
        "decision",
        "lesson",
        "pattern",
    }:
        return {"error": "Unsupported asset kind."}
    if not name or not summary or len(name) > 160 or len(summary) > 1200:
        return {"error": "Name and summary are required (summary max 1200 characters)."}
    project = str(args.get("project", ""))
    project_id = resolve_project(project, conn) if project else ""
    scope = str(
        args.get("scope", "project" if kind in {"decision", "lesson"} and project else "global")
    )
    if scope not in {"global", "project"}:
        return {"error": "scope must be global or project."}
    if project and not project_id:
        return {"error": "The linked project must already be indexed; pass its full root path."}
    if scope == "project" and not project_id:
        return {"error": "Project-scoped assets require an indexed project path."}
    scope_project = project_id if scope == "project" else ""
    old = conn.execute(
        "SELECT id FROM assets WHERE kind=? AND lower(name)=lower(?) AND scope=? AND project_id=? ORDER BY id LIMIT 1",
        (kind, name, scope, scope_project),
    ).fetchone()
    if old:
        conn.execute(
            "UPDATE assets SET summary=?,tags=?,source=? WHERE id=?",
            (summary, str(args.get("tags", ""))[:300], str(args.get("source", ""))[:500], old[0]),
        )
        asset_id = old[0]
    else:
        cur = conn.execute(
            "INSERT INTO assets(kind,name,summary,tags,source,created_at,scope,project_id) VALUES(?,?,?,?,?,?,?,?)",
            (
                kind,
                name,
                summary,
                str(args.get("tags", ""))[:300],
                str(args.get("source", ""))[:500],
                int(time.time()),
                scope,
                scope_project,
            ),
        )
        asset_id = cur.lastrowid
    linked = False
    if project:
        conn.execute(
            "INSERT OR IGNORE INTO asset_projects VALUES(?,?,?)",
            (asset_id, project_id, str(args.get("relation", "used_in"))[:40]),
        )
        linked = True
    conn.commit()
    return {"saved": True, "id": asset_id, "linked_project": linked}


def link_assets(args: dict[str, Any], conn: sqlite3.Connection) -> dict[str, Any]:
    source = str(args.get("source", "")).strip()
    target = str(args.get("target", " ")).strip()
    relation = str(args.get("relation", "related_to")).strip()[:60]
    evidence = str(args.get("evidence", " ")).strip()[:500]
    requested_scope = str(args.get("project", "")).strip()
    scope = (
        resolve_project(requested_scope, conn)
        if requested_scope and requested_scope != "*"
        else requested_scope
    )
    try:
        weight = float(args.get("weight", 0.8))
    except (TypeError, ValueError):
        return {"error": "weight must be between 0.05 and 1.0"}
    if (
        not source
        or not target
        or source.casefold() == target.casefold()
        or not relation
        or not evidence
        or not 0.05 <= weight <= 1.0
        or not requested_scope
    ):
        return {
            "error": "Provide distinct assets, relation, evidence, weight 0.05-1.0, and project scope (or '*' for a global fact)."
        }
    if requested_scope != "*" and not scope:
        return {
            "error": "Project scope must identify an indexed project; use '*' only for a genuinely global relation."
        }
    if scope != "*":
        a = conn.execute(
            "SELECT id FROM assets WHERE lower(name)=lower(?) AND (scope='global' OR (scope='project' AND project_id=?)) ORDER BY CASE scope WHEN 'project' THEN 0 ELSE 1 END LIMIT 1",
            (source, scope),
        ).fetchone()
        b = conn.execute(
            "SELECT id FROM assets WHERE lower(name)=lower(?) AND (scope='global' OR (scope='project' AND project_id=?)) ORDER BY CASE scope WHEN 'project' THEN 0 ELSE 1 END LIMIT 1",
            (target, scope),
        ).fetchone()
    else:
        a = conn.execute(
            "SELECT id FROM assets WHERE lower(name)=lower(?) AND scope='global' ORDER BY id LIMIT 1",
            (source,),
        ).fetchone()
        b = conn.execute(
            "SELECT id FROM assets WHERE lower(name)=lower(?) AND scope='global' ORDER BY id LIMIT 1",
            (target,),
        ).fetchone()
    if not a or not b:
        return {"error": "Both assets must already exist in the selected graph scope."}
    conn.execute(
        "INSERT OR IGNORE INTO asset_links VALUES(?,?,?,?,?,?)",
        (a[0], b[0], relation, weight, evidence, int(time.time())),
    )
    conn.execute(
        "INSERT INTO asset_link_evidence VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id,target_id,relation,scope) DO UPDATE SET weight=excluded.weight,evidence=excluded.evidence,updated_at=excluded.updated_at",
        (a[0], b[0], relation, scope, weight, evidence, int(time.time())),
    )
    conn.commit()
    return {
        "linked": True,
        "source": source,
        "target": target,
        "relation": relation,
        "weight": weight,
        "scope": scope,
    }


def get_master_graph(
    conn: sqlite3.Connection,
    limit: int = 50,
    project: str = "",
    edge_limit: int | None = None,
    workspace: bool = False,
) -> dict[str, Any]:
    project_id = resolve_project(project, conn) if project else ""
    if project and not project_id:
        return {"error": "Unknown project. Run sync_project with its absolute path first."}
    condition = (
        "(scope='global' OR (scope='project' AND project_id=?))" if project_id else "scope='global'"
    )
    values = (project_id,) if project_id else ()
    if workspace:
        condition = (
            "(scope='global' OR (scope='project' AND project_id IN (SELECT id FROM projects)))"
        )
        values = ()
    condition += " AND NOT EXISTS (SELECT 1 FROM memory_proposals m WHERE m.asset_id=assets.id AND m.status='superseded')"
    total_nodes = conn.execute(f"SELECT count(*) FROM assets WHERE {condition}", values).fetchone()[
        0
    ]
    edge_scope = "e.scope='*'"
    edge_values = ()
    if workspace:
        edge_scope = "(e.scope='*' OR e.scope IN (SELECT id FROM projects))"
    elif project_id:
        edge_scope = "(e.scope='*' OR e.scope=?)"
        edge_values = (project_id,)
    nodes = conn.execute(
        f"SELECT id,kind,name,summary,tags,source,scope,project_id FROM assets WHERE {condition} "
        f"ORDER BY CASE WHEN EXISTS (SELECT 1 FROM asset_link_evidence e WHERE {edge_scope} "
        "AND (e.source_id=assets.id OR e.target_id=assets.id)) THEN 0 ELSE 1 END, kind,name LIMIT ?",
        (*values, *edge_values, limit),
    ).fetchall()
    ids = {int(n["id"]) for n in nodes}
    edges = []
    edges_truncated = False
    if workspace:
        edge_rows = conn.execute(
            "SELECT e.source_id,e.target_id,e.relation,e.scope,e.weight,e.evidence,a.name source_name,b.name target_name FROM asset_link_evidence e JOIN assets a ON a.id=e.source_id JOIN assets b ON b.id=e.target_id WHERE e.scope='*' OR e.scope IN (SELECT id FROM projects) ORDER BY a.name,b.name,e.relation"
        )
    elif project_id:
        edge_rows = conn.execute(
            "SELECT e.source_id,e.target_id,e.relation,e.scope,e.weight,e.evidence,a.name source_name,b.name target_name FROM asset_link_evidence e JOIN assets a ON a.id=e.source_id JOIN assets b ON b.id=e.target_id WHERE e.scope='*' OR e.scope=? ORDER BY a.name,b.name,e.relation",
            (project_id,),
        )
    else:
        edge_rows = conn.execute(
            "SELECT e.source_id,e.target_id,e.relation,e.scope,e.weight,e.evidence,a.name source_name,b.name target_name FROM asset_link_evidence e JOIN assets a ON a.id=e.source_id JOIN assets b ON b.id=e.target_id WHERE e.scope='*' ORDER BY a.name,b.name,e.scope,e.relation"
        )
    for edge in edge_rows:
        if edge["source_id"] in ids and edge["target_id"] in ids:
            if edge_limit is not None and len(edges) >= edge_limit:
                edges_truncated = True
                break
            edges.append(
                {
                    "source": edge["source_name"],
                    "target": edge["target_name"],
                    "source_id": edge["source_id"],
                    "target_id": edge["target_id"],
                    "relation": edge["relation"],
                    "weight": edge["weight"],
                    "scope": edge["scope"],
                    "evidence": edge["evidence"],
                }
            )
    result_nodes = []
    for node in nodes:
        item = dict(node)
        memory = conn.execute(
            "SELECT id FROM memory_proposals WHERE asset_id=? AND status='approved'", (item["id"],)
        ).fetchone()
        if memory:
            item.update(features.health(conn, memory["id"]))
        result_nodes.append(item)
    return {
        "nodes": result_nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "total_nodes": total_nodes,
        "nodes_truncated": total_nodes > len(nodes),
        "edges_truncated": edges_truncated,
        "note": "Weights express evidence strength for deterministic spreading activation; they are not trained neural parameters.",
    }


def seed_project(root: Path, conn: sqlite3.Connection) -> dict:
    return {
        "seeded": 0,
        "linked": 0,
        "asset_edges": 0,
        "deprecated": True,
        "note": "Automatic prototype seeds are disabled. Index only explicitly selected repositories and propose knowledge for review.",
    }


def measure_task(args: dict[str, Any], conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        values = [args["baseline_tokens"], args["network_tokens"], args.get("indexing_tokens", 0)]
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
            return {"error": "Token counts must be non-negative integers."}
        baseline, network, indexing = values
    except (KeyError, ValueError, TypeError):
        return {"error": "Provide integer baseline_tokens and network_tokens."}
    task = str(args.get("task", ""))[:240]
    if not task:
        return {"error": "task is required."}
    net = baseline - network - indexing
    conn.execute(
        "INSERT INTO task_measurements(task,baseline_tokens,network_tokens,indexing_tokens,measured_at) VALUES(?,?,?,?,?)",
        (task, baseline, network, indexing, int(time.time())),
    )
    conn.commit()
    return {
        "saved": True,
        "net_tokens_saved": None,
        "percent_saved": None,
        "recorded_difference": net,
        "eligible_for_claim": False,
        "measurement_kind": "legacy_unverified",
        "note": "Use provider-reported usage for both paths; include one-time indexing tokens only once or amortize them across measured reuses.",
    }


def feature_call(action: str, args: dict[str, Any], conn: sqlite3.Connection) -> Any:
    if not isinstance(args, dict):
        return {"error": "payload must be an object."}
    if action == "complete_task":
        return learning.complete_task(sys.modules[__name__], args, conn)
    if action == "policy":
        return {
            "policy": (Path(__file__).resolve().parent / "POLICY.md").read_text(
                encoding="utf-8-sig"
            )
        }
    if action == "task_context":
        return broker.task_context(sys.modules[__name__], args, conn)
    if action == "clear_session":
        return broker.clear_session(sys.modules[__name__], args, conn)
    if action == "checkpoint":
        return broker.session_checkpoint(sys.modules[__name__], args, conn)
    if action == "audit_scopes":
        return features.audit_relationship_scopes(conn)
    if action == "inspect_source":
        return features.inspect_source(sys.modules[__name__], args, conn)
    if action == "search":
        result = features.ranked_search(sys.modules[__name__], args, conn)
        if "error" not in result:
            features.log_retrieval(
                sys.modules[__name__], conn, result["project"], result["query"], result
            )
        return result
    if action == "context":
        return features.bounded_context(sys.modules[__name__], args, conn)
    if action == "benchmark_runs":
        return features.canonical_benchmarks(conn)
    if action == "benchmark_record":
        return features.benchmark(args, conn)
    if action == "benchmark_list":
        return features.benchmark_list(conn)
    if action == "propose":
        return features.propose(sys.modules[__name__], args, conn)
    if action == "proposals":
        return features.proposal_list(sys.modules[__name__], args, conn)
    if action == "review":
        return features.review(sys.modules[__name__], args, conn)
    if action == "export_memories":
        return features.export_memories(sys.modules[__name__], args, conn)
    if action == "retention_memories":
        return features.retention_memories(sys.modules[__name__], args, conn)
    if action == "delete_memory":
        return features.delete_memory(sys.modules[__name__], args, conn)
    if action == "dependencies":
        return features.dependencies(sys.modules[__name__], args, conn)
    if action == "impact":
        return features.impact_analysis(sys.modules[__name__], args, conn)
    if action == "discover":
        return features.discover(conn)
    if action == "capabilities":
        target = args.get("target") or args.get("language") or args.get("extension")
        return get_language_capabilities(target)
    return {"error": "Unknown TokSmart action."}


def checkpoint_wal(conn: sqlite3.Connection | None = None, mode: str = "PASSIVE") -> dict:
    close = False
    if conn is None:
        conn = connect()
        close = True
    try:
        cur = conn.execute(f"PRAGMA wal_checkpoint({mode})")
        res = cur.fetchone()
        return {"busy": res[0], "log": res[1], "checkpointed": res[2]}
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        return {"error": str(e)}
    finally:
        if close:
            conn.close()


def call(name: str, args: dict[str, Any], conn: sqlite3.Connection) -> Any:
    if not isinstance(args, dict):
        return {"error": "arguments must be an object."}
    direct_actions = {
        "coding_efficiency_policy": "policy",
        "get_task_context": "task_context",
        "clear_context_session": "clear_session",
        "inspect_source_range": "inspect_source",
        "capabilities": "capabilities",
        "get_language_capabilities": "capabilities",
        "inspect_impact": "impact",
        "impact": "impact",
        "checkpoint": "checkpoint",
        "session_checkpoint": "checkpoint",
    }
    if name in direct_actions:
        return feature_call(direct_actions[name], args, conn)
    if name in ("toksmart", "repomind", "lazytoken") and args.get("action") in (
        "review",
        "delete_memory",
        "retention_memories",
    ):
        return {
            "error": "MCP clients cannot review or delete memories. Use the local dashboard or operator CLI."
        }
    if name in ("toksmart", "repomind", "lazytoken"):
        payload = args.get("payload", {})
        return (
            feature_call(str(args.get("action", "")), payload, conn)
            if isinstance(payload, dict)
            else {"error": "payload must be an object."}
        )
    if name == "search_knowledge":
        if "budget" in args:
            return features.bounded_context(sys.modules[__name__], args, conn)
        return search(
            str(args.get("query", ""))[:1000],
            conn,
            str(args.get("project", "")),
            max(1, min(12, int(args.get("limit", 8)))),
        )
    if name == "get_master_graph":
        return get_master_graph(
            conn, max(1, min(50, int(args.get("limit", 50)))), str(args.get("project", ""))
        )
    if name == "link_assets":
        return link_assets(args, conn)
    if name == "get_project_context":
        if "budget" in args:
            return features.bounded_context(sys.modules[__name__], args, conn)
        return context(str(args["project"]), conn)
    if name == "sync_project":
        root = Path(str(args["root"]))
        if not root.is_absolute() or not root.is_dir():
            return {"error": "root must be an existing absolute directory."}
        result = sync(root, conn)
        import watcher

        watching = watcher.ensure(sys.modules[__name__], conn)
        result["automatic_sync"] = {
            key: watching[key] for key in ("running", "error", "disabled") if key in watching
        }
        return result
    if name == "record_asset":
        return add_asset(args, conn)
    if name == "seed_project":
        return seed_project(Path(str(args["root"])), conn)
    if name == "record_task_measurement":
        return measure_task(args, conn)
    if name == "token_report":
        totals = conn.execute(
            "SELECT count(*),coalesce(sum(estimated_tokens),0),coalesce(sum(query_chars),0) FROM retrievals"
        ).fetchone()
        projects = [
            dict(r)
            for r in conn.execute(
                "SELECT p.root,count(f.path) files,coalesce(sum(f.bytes),0) indexed_bytes FROM projects p LEFT JOIN files f ON f.project_id=p.id GROUP BY p.id ORDER BY p.root"
            )
        ]
        measured = conn.execute(
            "SELECT count(*),coalesce(sum(baseline_tokens),0),coalesce(sum(network_tokens),0),coalesce(sum(indexing_tokens),0) FROM task_measurements"
        ).fetchone()
        return {
            "retrieval_calls": totals[0],
            "retrieved_estimated_tokens": totals[1],
            "query_characters": totals[2],
            "measured_tasks": measured[0],
            "baseline_tokens": measured[1] if measured[0] else None,
            "network_tokens": measured[2] if measured[0] else None,
            "allocated_indexing_tokens": measured[3] if measured[0] else None,
            "measured_net_saved": None,
            "legacy_recorded_difference": (
                measured[1] - measured[2] - measured[3] if measured[0] else None
            ),
            "eligible_for_claim": False,
            "canonical_run_count": conn.execute(
                "SELECT count(*) FROM benchmark_records"
            ).fetchone()[0],
            "projects": projects,
            "caveat": "Retrieval estimate is approximate text size, not model tokenizer or API billing. Savings use provider-reported counts entered per task.",
        }
    return {"error": "Unknown tool."}


def rpc_server(conn: sqlite3.Connection, compact=False) -> None:
    supported_versions = ("2024-11-05", "2025-03-26", "2025-06-18")

    def error_reply(request_id, code, message):
        sys.stdout.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
                separators=(",", ":"),
            )
            + "\n"
        )
        sys.stdout.flush()

    for raw in sys.stdin:
        rid = None
        try:
            try:
                req = json.loads(raw)
            except json.JSONDecodeError:
                error_reply(None, -32700, "Parse error")
                continue
            if (
                not isinstance(req, dict)
                or req.get("jsonrpc") != "2.0"
                or not isinstance(req.get("method"), str)
                or (
                    "id" in req
                    and (isinstance(req["id"], bool) or not isinstance(req["id"], (str, int)))
                )
            ):
                error_reply(None, -32600, "Invalid request")
                continue
            if "id" not in req:
                continue
            method = req.get("method")
            rid = req.get("id")
            if method == "initialize":
                params = req.get("params", {})
                if not isinstance(params, dict):
                    error_reply(rid, -32602, "Invalid params")
                    continue
                requested = params.get("protocolVersion")
                result = {
                    "protocolVersion": (
                        requested if requested in supported_versions else supported_versions[-1]
                    ),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "toksmart-knowledge-network", "version": VERSION},
                    "instructions": WORKFLOW_INSTRUCTIONS,
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": mcp_tools(compact)}
            elif method == "tools/call":
                p = req.get("params", {})
                if not isinstance(p, dict):
                    error_reply(rid, -32602, "Invalid params")
                    continue
                arguments = p.get("arguments", {})
                if isinstance(arguments, dict):
                    arguments = dict(arguments)
                    if p.get("name") == "get_task_context":
                        arguments["compact_mcp"] = compact
                    elif (
                        p.get("name") in ("toksmart", "repomind", "lazytoken")
                        and arguments.get("action") == "task_context"
                        and isinstance(arguments.get("payload"), dict)
                    ):
                        arguments["payload"] = {**arguments["payload"], "compact_mcp": compact}
                value = call(p.get("name", ""), arguments, conn)
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                            ),
                        }
                    ],
                    "isError": bool(isinstance(value, dict) and "error" in value),
                }
            else:
                error_reply(rid, -32601, "Method not found")
                continue
            if rid is not None:
                sys.stdout.write(
                    json.dumps(
                        {"jsonrpc": "2.0", "id": rid, "result": result}, separators=(",", ":")
                    )
                    + "\n"
                )
                sys.stdout.flush()
        except Exception as e:
            if conn.in_transaction:
                conn.rollback()
            # Never log inputs or source content to stderr; keep MCP stdout protocol-clean.
            if rid is not None:
                error_reply(rid, -32603, type(e).__name__)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("dashboard", "serve"):
        from dashboard import main as dashboard_main

        del sys.argv[1]
        dashboard_main()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "benchmark":
        from benchmark.harness import main as benchmark_main

        raise SystemExit(benchmark_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "prompt-benchmark":
        from benchmark.prompt_modes import main as prompt_benchmark_main

        raise SystemExit(prompt_benchmark_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "evaluate":
        from retrieval_eval import main as evaluation_main

        raise SystemExit(evaluation_main(sys.argv[2:]))
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dashboard", help="Open the local graph dashboard")
    sub.add_parser("serve", help="Start the local server and open dashboard")
    sub.add_parser("benchmark", help="Validate and compare benchmark records")
    sub.add_parser("prompt-benchmark", help="Plan, run and export Normal/Lite/Pro prompt trials")
    sub.add_parser("evaluate", help="Evaluate retrieval against supplied labels")
    ix = sub.add_parser("sync")
    ix.add_argument("root", nargs="?")
    sd = sub.add_parser("seed")
    sd.add_argument("root")
    watch = sub.add_parser(
        "watch", help="Automatic synchronization of previously selected repositories"
    )
    watch.add_argument(
        "action", choices=["start", "stop", "status", "run"], default="status", nargs="?"
    )
    watch.add_argument("--interval", type=float, default=2)
    watch.add_argument("--debounce", type=float, default=1)
    mcp = sub.add_parser("mcp")
    mcp.add_argument(
        "--compact-tools",
        action="store_true",
        help="Advertise a smaller core tool catalog to reduce connection context",
    )
    sr = sub.add_parser("search")
    sr.add_argument("query")
    sr.add_argument("--project", default="")
    impact_cmd = sub.add_parser(
        "impact",
        help="Blast-radius and call-graph impact analysis for a symbol or file (GitNexus + Ponytail style)",
    )
    impact_cmd.add_argument(
        "target",
        help="Symbol name (e.g. 'Class.method' or 'func') or project-relative file path",
    )
    impact_cmd.add_argument("--project", default="")
    for cmd_name in ("toksmart", "repomind", "lazytoken"):
        lt = sub.add_parser(
            cmd_name, help=f"Run a {cmd_name.capitalize()} action with JSON arguments"
        )
        lt.add_argument(
            "action",
            choices=[
                "complete_task",
                "policy",
                "search",
                "context",
                "task_context",
                "clear_session",
                "checkpoint",
                "audit_scopes",
                "inspect_source",
                "impact",
                "benchmark_record",
                "benchmark_list",
                "benchmark_runs",
                "propose",
                "proposals",
                "review",
                "dependencies",
                "discover",
                "capabilities",
            ],
        )
        lt.add_argument("--json", default="{}", help="JSON object, or @path to a UTF-8 JSON file")
    caps_cmd = sub.add_parser(
        "capabilities", help="Inspect language capability tiers and supported features"
    )
    caps_cmd.add_argument(
        "target", nargs="?", default=None, help="Optional language name or file extension"
    )
    caps_cmd.add_argument("--format", choices=("json", "text", "table"), default="json")
    backup = sub.add_parser("backup", help="Copy the current database to a new file")
    backup.add_argument("destination")
    restore = sub.add_parser("restore", help="Restore a backup to a new, empty directory")
    restore.add_argument("source")
    restore.add_argument(
        "--to", required=True, help="Existing empty directory for the restored network.sqlite3"
    )
    doctor = sub.add_parser(
        "doctor",
        help="Check runtime, storage, SQLite, clients and local dashboard without changing settings",
    )
    doctor.add_argument("--format", choices=("json", "text", "table"), default="json")
    migration = sub.add_parser(
        "migrate-data", help="Preview or explicitly copy a legacy database; never merge"
    )
    migration.add_argument("--source")
    migration.add_argument("--apply", action="store_true")
    migration.add_argument("--rollback")
    deletion = sub.add_parser(
        "data-delete",
        help="Separately delete only the inactive default knowledge database; application uninstall preserves it",
    )
    deletion.add_argument("--confirm-directory", required=True)
    remove = sub.add_parser(
        "clients-remove", help="Remove only unchanged client entries owned by this installation"
    )
    remove.add_argument("--install-root", required=True)
    for name in ("update", "rollback", "uninstall"):
        lifecycle = sub.add_parser(
            name, help="Managed installation lifecycle; use the installed toksmart command"
        )
        lifecycle.add_argument("options", nargs=argparse.REMAINDER)
    initialize = sub.add_parser("init", help="Initialize storage and optionally index a project")
    initialize.add_argument("--project")
    add = sub.add_parser("add", help="Index an existing project")
    add.add_argument("root")
    ctx = sub.add_parser("context", help="Get task-aware project metadata")
    ctx.add_argument("--project", required=True)
    ctx.add_argument("--task", required=True)
    ctx.add_argument("--mode", choices=["compact", "balanced", "deep"])
    ctx.add_argument("--budget", type=int)
    ctx.add_argument("--expand-assets", action="store_true")
    ctx.add_argument("--model")
    ctx.add_argument("--strict-budget", action="store_true")
    ctx.add_argument("--session-id")
    ctx.add_argument("--skip-retrieval", action="store_true")
    ctx.add_argument("--include-seen", action="store_true")
    ctx.add_argument(
        "--prompt", action="store_true", help="Output the task and context as an agent prompt"
    )
    checkpoint = sub.add_parser("checkpoint", help="Summarize a project session for continuation")
    checkpoint.add_argument("--project", required=True)
    checkpoint.add_argument("--session-id", required=True)
    checkpoint.add_argument(
        "--acknowledge-source",
        action="store_true",
        help="Accept the current indexed source as the new checkpoint baseline",
    )
    setup = sub.add_parser("setup", help="Preview or explicitly apply local project/client setup")
    setup.add_argument("--project")
    setup.add_argument("--client", action="append", choices=["codex", "antigravity"], default=[])
    setup.add_argument("--apply", action="store_true")
    setup.add_argument("--rollback")
    setup.add_argument("--test-connection", action="store_true")
    sub.add_parser("report")
    a = parser.parse_args()
    if a.cmd == "watch":
        import watcher

        if not 0.25 <= a.interval <= 300 or not 0 <= a.debounce <= 30:
            parser.error("interval must be 0.25 to 300 seconds and debounce 0 to 30 seconds")
        if a.action == "run":
            result = watcher.run(sys.modules[__name__], a.interval, a.debounce)
        elif a.action == "start":
            result = watcher.start(
                sys.modules[__name__], force=True, interval=a.interval, debounce=a.debounce
            )
        elif a.action == "stop":
            result = watcher.stop(sys.modules[__name__])
        else:
            result = watcher.status(data_root())
        print(json.dumps(result, indent=2))
        if "error" in result:
            raise SystemExit(1)
        return
    if a.cmd == "setup":
        import onboarding

        try:
            if a.rollback:
                result = onboarding.rollback(a.rollback)
            elif a.test_connection:
                result = onboarding.connection_test(sys.modules[__name__])
            else:
                project = a.project
                if not project and sys.stdin.isatty():
                    project = input("Repository absolute path: ").strip()
                if not project:
                    parser.error("Provide --project, --test-connection, or --rollback.")
                plan = onboarding.preview(sys.modules[__name__], project, a.client)
                if a.apply:
                    result = onboarding.apply(sys.modules[__name__], plan)
                    import watcher

                    result["watcher"] = watcher.start(sys.modules[__name__])
                else:
                    result = {
                        "preview": True,
                        "project": plan["project"],
                        "database": plan["database"],
                        "server": plan["server"],
                        "clients": [
                            {k: v for k, v in c.items() if k not in ("before", "after")}
                            for c in plan["changes"]
                        ],
                        "discovery": onboarding.diagnose(sys.modules[__name__]),
                        "next": "Add --apply to index this project and apply selected missing MCP entries.",
                    }
            print(json.dumps(result, indent=2))
            if a.test_connection and not result.get("mcp_initialize"):
                raise SystemExit(1)
            return
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            print(json.dumps({"error": str(exc)}))
            raise SystemExit(1)
    if a.cmd == "capabilities":
        res = get_language_capabilities(a.target)
        if a.format == "json":
            print(json.dumps(res, indent=2))
        elif a.format == "table":
            if isinstance(res, dict) and "language" in res:
                items = [res]
            else:
                items = list(res.values())
            print(
                f"{'Language':<15} | {'Tier':<18} | {'Extensions':<25} | {'Call Graph':<10} | {'Super Res'}"
            )
            print("-" * 80)
            for item in items:
                exts = ", ".join(item.get("extensions", []))
                cg = "Yes" if item.get("features", {}).get("call_graph") else "No"
                sr = "Yes" if item.get("features", {}).get("super_resolution") else "No"
                print(
                    f"{item.get('language', ''):<15} | {item.get('tier', ''):<18} | {exts:<25} | {cg:<10} | {sr}"
                )
        else:
            if isinstance(res, dict) and "language" in res:
                print(f"Language: {res.get('language')} (Tier: {res.get('tier')})")
                print(f"Description: {res.get('description')}")
            else:
                for lang, spec in res.items():
                    print(
                        f"{lang}: {spec.get('tier')} tier ({', '.join(spec.get('extensions', []))})"
                    )
        return
    if a.cmd == "doctor":
        import diagnostics

        result = diagnostics.report(sys.modules[__name__])
        if a.format == "json":
            print(json.dumps(result, indent=2))
        else:
            width = max(map(len, result)) if a.format == "table" else 0
            for key, value in result.items():
                label = key.ljust(width) if width else key
                print(f"{label}{' | ' if width else ': '}{json.dumps(value, ensure_ascii=False)}")
        return
    if a.cmd == "migrate-data":
        import migration

        if a.rollback:
            result = migration.rollback(a.rollback)
        elif a.source:
            result = migration.migrate(a.source, default_data_root() / "network.sqlite3", a.apply)
        else:
            result = {
                "legacy_databases": [str(p / "network.sqlite3") for p in legacy_data_roots()],
                "destination": str(default_data_root() / "network.sqlite3"),
                "next": "Select --source to preview. Add --apply only after reviewing the paths.",
            }
        print(json.dumps(result, indent=2))
        if "error" in result:
            raise SystemExit(1)
        return
    if a.cmd == "data-delete":
        import migration

        result = migration.delete_default_store(sys.modules[__name__], a.confirm_directory)
        print(json.dumps(result, indent=2))
        if "error" in result:
            raise SystemExit(1)
        return
    if a.cmd == "clients-remove":
        import onboarding

        try:
            print(
                json.dumps(onboarding.remove_managed_clients(sys.modules[__name__], a.install_root))
            )
        except (OSError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}))
            raise SystemExit(1)
        return
    if a.cmd in ("update", "rollback", "uninstall"):
        print(
            json.dumps(
                {
                    "error": "Run this command through the installed toksmart launcher. It manages versions without deleting a running executable. See install.ps1 for a verified package installation."
                }
            )
        )
        raise SystemExit(1)
    if a.cmd in ("backup", "restore"):
        result = (
            data_ops.copy_database(data_root() / "network.sqlite3", Path(a.destination))
            if a.cmd == "backup"
            else data_ops.copy_database(Path(a.source), Path(a.to) / "network.sqlite3")
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if "error" in result:
            raise SystemExit(1)
        return
    db = connect()
    if a.cmd == "mcp":
        import watcher

        watcher.ensure(sys.modules[__name__], db)
        rpc_server(db, a.compact_tools)
    elif a.cmd == "init":
        root = Path(a.project) if a.project else None
        if root and (not root.is_absolute() or not root.is_dir()):
            parser.error("--project must be an existing absolute directory")
        import onboarding
        import watcher

        indexed = sync(root, db) if root else None
        watching = watcher.ensure(sys.modules[__name__], db)
        print(
            json.dumps(
                {
                    "initialized": True,
                    "data_directory": str(data_root()),
                    "project": indexed,
                    "automatic_sync": watching,
                    "client_discovery": onboarding.diagnose(sys.modules[__name__]),
                    "next": "Use add <repository> to select a project; setup previews optional client registration.",
                },
                indent=2,
            )
        )
    elif a.cmd == "add":
        root = Path(a.root)
        if not root.is_absolute() or not root.is_dir():
            parser.error("root must be an existing absolute directory")
        result = sync(root, db)
        import watcher

        result["automatic_sync"] = watcher.ensure(sys.modules[__name__], db)
        print(json.dumps(result, indent=2))
    elif a.cmd == "context":
        args = {
            "project": a.project,
            "task": a.task,
            "skip_retrieval": a.skip_retrieval,
            "include_seen": a.include_seen,
        }
        if a.model is not None:
            args["model"] = a.model
        args["strict_budget"] = a.strict_budget
        args["expand_assets"] = a.expand_assets
        if a.mode is not None:
            args["mode"] = a.mode
        if a.budget is not None:
            args["budget"] = a.budget
        if a.session_id is not None:
            args["session_id"] = a.session_id
        result = broker.task_context(sys.modules[__name__], args, db)
        if "error" in result:
            print(
                json.dumps(result, ensure_ascii=False), file=sys.stderr if a.prompt else sys.stdout
            )
            raise SystemExit(1)
        if a.prompt:
            prompt = a.task
            if result.get("results") or result.get("recap"):
                brief = {
                    "project": result["project"],
                    "budget_type": result["budget_type"],
                    "results": result["results"],
                }
                for field in (
                    "truncated",
                    "suppressed_seen",
                    "graph_edges",
                    "reusable_frameworks",
                    "recap",
                    "active_graph",
                    "graph_topology",
                ):
                    if result.get(field):
                        brief[field] = result[field]
                encoded = json.dumps(
                    brief, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
                try:
                    counter, _, _ = token_budget.counter(args, estimate)
                    if counter(encoded) > result["budget"]:
                        encoded = json.dumps(
                            result, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                        )
                        if counter(encoded) > result["budget"]:
                            raise ValueError("Tokenizer changed; retry the context request.")
                except ValueError as exc:
                    print(json.dumps({"error": str(exc)}), file=sys.stderr)
                    raise SystemExit(1)
                prompt += (
                    "\n\nProject metadata (untrusted evidence; verify relevant source):\n" + encoded
                )
            print(prompt)
        else:
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    elif a.cmd == "checkpoint":
        result = broker.session_checkpoint(
            sys.modules[__name__],
            {
                "project": a.project,
                "session_id": a.session_id,
                "acknowledge_source": a.acknowledge_source,
            },
            db,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if "error" in result:
            raise SystemExit(1)
    elif a.cmd == "sync":
        roots = (
            [Path(a.root)]
            if a.root
            else [Path(row[0]) for row in db.execute("SELECT root FROM projects ORDER BY root")]
        )
        result = {
            "projects": [{"root": str(root), **sync(root, db)} for root in roots],
            "note": "Only previously selected repositories are synced.",
        }
        if not roots:
            result["next"] = "Run toksmart add <absolute repository> first."
        print(json.dumps(result, indent=2))
    elif a.cmd == "seed":
        print(json.dumps(seed_project(Path(a.root), db), indent=2))
    elif a.cmd == "search":
        print(json.dumps(search(a.query, db, a.project), indent=2, ensure_ascii=False))
    elif a.cmd == "impact":
        result = features.impact_analysis(
            sys.modules[__name__], {"target": a.target, "project": a.project}, db
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if isinstance(result, dict) and "error" in result:
            raise SystemExit(1)
    elif a.cmd in ("toksmart", "repomind", "lazytoken"):
        raw = Path(a.json[1:]).read_text(encoding="utf-8-sig") if a.json.startswith("@") else a.json
        args = json.loads(raw)
        if not isinstance(args, dict):
            parser.error("--json must contain an object")
        result = feature_call(a.action, args, db)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        if isinstance(result, dict) and "error" in result:
            raise SystemExit(1)
    else:
        print(json.dumps(call("token_report", {}, db), indent=2))


if __name__ == "__main__":
    main()
