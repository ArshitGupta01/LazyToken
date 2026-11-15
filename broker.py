"""Task-aware, project-scoped metadata retrieval with optional session deduplication."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import posixpath
import sqlite3
import sys
import time
import features
import token_budget
from collections import OrderedDict

_SEARCH_CACHE = OrderedDict()

_PYTHON_STDLIB = getattr(
    sys,
    "stdlib_module_names",
    frozenset(
        {
            "abc",
            "argparse",
            "array",
            "ast",
            "asyncio",
            "base64",
            "binascii",
            "bisect",
            "builtins",
            "bz2",
            "calendar",
            "cmath",
            "cmd",
            "code",
            "codecs",
            "collections",
            "colorsys",
            "compileall",
            "concurrent",
            "configparser",
            "contextlib",
            "contextvars",
            "copy",
            "copyreg",
            "csv",
            "ctypes",
            "curses",
            "dataclasses",
            "datetime",
            "dbm",
            "decimal",
            "difflib",
            "dis",
            "doctest",
            "email",
            "encodings",
            "ensurepip",
            "enum",
            "errno",
            "faulthandler",
            "fcntl",
            "filecmp",
            "fileinput",
            "fnmatch",
            "fractions",
            "ftplib",
            "functools",
            "gc",
            "getopt",
            "getpass",
            "gettext",
            "glob",
            "graphlib",
            "gzip",
            "hashlib",
            "heapq",
            "hmac",
            "html",
            "http",
            "idlelib",
            "imaplib",
            "imghdr",
            "importlib",
            "inspect",
            "io",
            "ipaddress",
            "itertools",
            "json",
            "keyword",
            "linecache",
            "locale",
            "logging",
            "lzma",
            "mailbox",
            "mailcap",
            "marshal",
            "math",
            "mimetypes",
            "mmap",
            "modulefinder",
            "msilib",
            "msvcrt",
            "multiprocessing",
            "netrc",
            "nntplib",
            "numbers",
            "operator",
            "optparse",
            "os",
            "ossaudiodev",
            "pathlib",
            "pdb",
            "pickle",
            "pickletools",
            "pipes",
            "pkgutil",
            "platform",
            "plistlib",
            "poplib",
            "posix",
            "posixpath",
            "pprint",
            "profile",
            "pstats",
            "pty",
            "pwd",
            "py_compile",
            "pyclbr",
            "pydoc",
            "queue",
            "quopri",
            "random",
            "re",
            "readline",
            "reprlib",
            "resource",
            "rlcompleter",
            "runpy",
            "sched",
            "secrets",
            "select",
            "selectors",
            "shelve",
            "shlex",
            "shutil",
            "signal",
            "site",
            "smtpd",
            "smtplib",
            "sndhdr",
            "socket",
            "socketserver",
            "spwd",
            "sqlite3",
            "ssl",
            "stat",
            "statistics",
            "string",
            "stringprep",
            "struct",
            "subprocess",
            "sunau",
            "symtable",
            "sys",
            "sysconfig",
            "syslog",
            "tabnanny",
            "tarfile",
            "telnetlib",
            "tempfile",
            "termios",
            "textwrap",
            "threading",
            "time",
            "timeit",
            "tkinter",
            "token",
            "tokenize",
            "tomllib",
            "trace",
            "traceback",
            "tracemalloc",
            "tty",
            "turtle",
            "turtledemo",
            "types",
            "typing",
            "unicodedata",
            "unittest",
            "urllib",
            "uu",
            "uuid",
            "venv",
            "warnings",
            "wave",
            "weakref",
            "webbrowser",
            "winreg",
            "winsound",
            "wsgiref",
            "xdrlib",
            "xml",
            "xmlrpc",
            "zipapp",
            "zipfile",
            "zipimport",
            "zlib",
            "zoneinfo",
        }
    ),
)


class ContextCrumb(dict):
    """Context item dictionary supporting both 'why' and 'why_this_context' seamlessly."""

    def __getitem__(self, key):
        if key == "why_this_context" and not super().__contains__(key):
            return super().get("why", "Metadata match.")
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key == "why_this_context" and not super().__contains__(key):
            return super().get("why", default)
        return super().get(key, default)

    def __contains__(self, key):
        return super().__contains__(key) or (
            key == "why_this_context" and super().__contains__("why")
        )


def _resolve_import_target(source: str, target: str, active_files: set[str]) -> str | None:
    norm_source = source.replace("\\", "/")
    target = target.strip().replace("\\", "/")
    if not target or not active_files:
        return None

    # Guard self-import: a module importing its own stem should not resolve to another file
    if (
        target == Path(norm_source).stem
        or target == Path(norm_source).name
        or target == norm_source
    ):
        return None

    candidates = {f.replace("\\", "/") for f in active_files if f.replace("\\", "/") != norm_source}
    if not candidates:
        return None

    # JS/TS Relative import
    if target.startswith("./") or target.startswith("../"):
        source_dir = posixpath.dirname(norm_source)
        resolved_rel = posixpath.normpath(posixpath.join(source_dir, target))
        for ext in (
            "",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".d.ts",
            ".vue",
            ".svelte",
            "/index.js",
            "/index.ts",
            "/index.jsx",
            "/index.tsx",
            "/index.d.ts",
        ):
            cand = resolved_rel + ext
            if cand in candidates:
                return cand
            if cand.startswith("./") and cand[2:] in candidates:
                return cand[2:]
        return None

    # Python Relative import
    if target.startswith("."):
        leading_dots = len(target) - len(target.lstrip("."))
        remainder = target.lstrip(".")
        source_dir = posixpath.dirname(norm_source)
        dir_parts = [p for p in source_dir.split("/") if p]
        up_levels = leading_dots - 1
        if up_levels > len(dir_parts):
            return None
        if up_levels > 0:
            dir_parts = dir_parts[:-up_levels]
        base_dir = "/".join(dir_parts)
        rel_path = remainder.replace(".", "/")
        if base_dir and rel_path:
            full_cand = f"{base_dir}/{rel_path}"
        elif base_dir:
            full_cand = base_dir
        else:
            full_cand = rel_path

        for cand in (
            f"{full_cand}.py",
            f"{full_cand}/__init__.py",
            full_cand,
        ):
            if cand in candidates:
                return cand
        return None

    # Standard library filter: ignore standard library imports unless an exact file exists
    top_mod = target.split(".")[0]
    if top_mod in _PYTHON_STDLIB:
        source_dir = posixpath.dirname(norm_source)
        for f in candidates:
            if (
                f == f"{target}.py"
                or f == target
                or (source_dir and posixpath.dirname(f) == source_dir and Path(f).stem == target)
            ):
                return f
        return None

    # Exact path or filename match
    if target in candidates:
        return target
    if f"{target}.py" in candidates:
        return f"{target}.py"

    target_path = target.replace(".", "/")

    # Check same directory as source
    source_dir = posixpath.dirname(norm_source)
    if source_dir:
        same_dir = posixpath.normpath(posixpath.join(source_dir, target_path + ".py"))
        if same_dir in candidates:
            return same_dir
        same_dir_init = posixpath.normpath(posixpath.join(source_dir, target_path, "__init__.py"))
        if same_dir_init in candidates:
            return same_dir_init

    # Check from project root
    if f"{target_path}.py" in candidates:
        return f"{target_path}.py"
    if f"{target_path}/__init__.py" in candidates:
        return f"{target_path}/__init__.py"

    # Segment-aligned suffix match (never substring)
    is_bare = not "." in target and not "/" in target
    for f in candidates:
        if is_bare:
            if source_dir and posixpath.dirname(f) == source_dir and Path(f).stem == target:
                return f
        else:
            if (
                f.endswith("/" + target_path + ".py")
                or f.endswith("/" + target_path)
                or f.endswith("/" + target)
            ):
                return f

    return None


def _revision(conn):
    return (conn.total_changes, conn.execute("PRAGMA data_version").fetchone()[0])


def _carry_internal_writes(conn, before):
    after = _revision(conn)
    # Re-key only our known telemetry/session writes, never concurrent content commits.
    if before[1] != after[1]:
        return
    for key, value in list(_SEARCH_CACHE.items()):
        if key[0] is conn and key[3] == before:
            del _SEARCH_CACHE[key]
            _SEARCH_CACHE[(conn, key[1], key[2], after)] = value


def _search(kn, project, task, conn):
    # Conservative invalidation: includes own writes and commits by other connections.
    revision = _revision(conn)
    key = (conn, project, task, revision)
    now = time.monotonic()
    cached = _SEARCH_CACHE.get(key)
    if cached and now - cached[0] < 30:
        _SEARCH_CACHE.move_to_end(key)
        return cached[1]
    result = features.ranked_search(kn, {"project": project, "query": task, "limit": 100}, conn)
    if "error" not in result:
        _SEARCH_CACHE[key] = (now, result)
        while len(_SEARCH_CACHE) > 16:
            _SEARCH_CACHE.popitem(last=False)
    return result


MODES = {"compact": 250, "balanced": 600, "deep": 1200}


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _key(item):
    kind = item["type"]
    if kind == "asset":
        return "asset:" + str(item["id"])
    return ":".join(str(item.get(k, "")) for k in ("type", "path", "name", "line"))


def classify_retrieval_need(
    task: str,
    context_is_complete: bool = False,
    skip_retrieval: bool = False,
) -> tuple[str, str]:
    if skip_retrieval:
        return ("skip", "Caller explicitly requested no retrieval.")
    if not isinstance(task, str) or not task.strip():
        return ("abstain", "Task description is empty.")
    if context_is_complete:
        return ("skip", "Caller supplied complete context for a text-only task.")

    t = task.strip().lower()
    greeting_phrases = ("hello", "hi", "hey", "good morning", "good evening", "howdy", "greetings")
    words = [w.strip("!?,.") for w in t.split()]
    is_greeting = any(t.startswith(g) for g in greeting_phrases) or any(
        w in ("hello", "hi", "hey", "howdy", "greetings") for w in words
    )
    if (
        len(words) <= 3
        and is_greeting
        and not any(k in t for k in ("code", "file", "func", "class", "bug", "test", "repo"))
    ):
        return ("skip", "Task is conversational greeting; retrieval skipped.")

    formatting_patterns = (
        "format json",
        "prettify json",
        "format this json",
        "format markdown",
        "fix indentation",
        "convert snake_case to camelcase",
        "convert camelcase to snake_case",
        "write a regex",
        "regex for email",
        "calculate factorial",
        "fibonacci function",
        "reverse a string",
        "rewrite this text",
        "format this text",
        "summarize this text",
        "summarise this text",
    )
    if any(p in t for p in formatting_patterns) and not any(
        k in t for k in ("in repo", "in file", "in project", "across", "caller", "import")
    ):
        return (
            "skip",
            f"Task is self-contained utility/formatting ({task.strip()[:40]}); retrieval skipped.",
        )

    return ("retrieve", "Task requires repository context retrieval.")


def utility_per_token(
    relevance: float,
    freshness: float = 1.0,
    verification: float = 1.0,
    estimated_tokens: int = 1,
) -> float:
    tokens = max(1, int(estimated_tokens))
    return round((float(relevance) * float(freshness) * float(verification)) / tokens, 6)


def task_context(kn, args, conn):
    project = features.project_id(kn, conn, args.get("project"))
    if not project:
        return {"error": "An indexed project is required."}
    task = args.get("task")
    if not isinstance(task, str) or not task.strip() or len(task) > 2000:
        return {"error": "task must be non-empty text up to 2000 characters."}
    inferred_complex = len(kn.split_words(task)) > 24 or any(
        term in task.casefold()
        for term in ("architecture", "migration", "cross-project", "across projects")
    )
    mode = args.get("mode", "balanced" if inferred_complex else "compact")
    if not isinstance(mode, str) or mode not in MODES:
        return {"error": "mode must be compact, balanced, or deep."}
    skip = args.get("skip_retrieval", False)
    rehydrate = args.get("rehydrate", False)
    repeat = args.get("include_seen", False) or rehydrate
    complete = args.get("context_is_complete", False)
    if not all(isinstance(x, bool) for x in (skip, repeat, complete, rehydrate)):
        return {
            "error": "skip_retrieval, include_seen, rehydrate and context_is_complete must be booleans."
        }
    clf_decision, clf_reason = classify_retrieval_need(
        task, context_is_complete=complete, skip_retrieval=skip
    )
    if clf_decision == "skip":
        skip = True
    expand = args.get("expand_assets", False)
    if not isinstance(expand, bool):
        return {"error": "expand_assets must be boolean."}
    session = args.get("session_id")
    if session is not None and (
        not isinstance(session, str) or not session.strip() or len(session) > 120
    ):
        return {"error": "session_id must be non-empty text up to 120 characters."}
    budget = args.get("budget", MODES[mode])
    if isinstance(budget, bool) or not isinstance(budget, int) or not 100 <= budget <= 16000:
        return {"error": "budget must be an integer from 100 to 16000 estimated tokens."}
    try:
        counter_result = token_budget.counter(args, kn.estimate)
        count, budget_type, fallback = counter_result
    except ValueError as exc:
        return {"error": str(exc)}
    is_approx = getattr(
        counter_result, "is_approximate", not str(budget_type).startswith("tokenizer:")
    )
    compact_mcp = (mode == "compact") or bool(args.get("compact_mcp", False))

    def used(response):
        # Count the final compact payload, including the usage counters themselves.
        response["estimated_tokens"] = 0
        response["used_tokens"] = 0
        for _ in range(32):
            encoded = _encoded(response)
            estimated = kn.estimate(encoded)
            measured = count(encoded)
            if estimated <= response["estimated_tokens"] and measured <= response["used_tokens"]:
                if "token_accounting" in response:
                    response["token_accounting"]["payload_tokens"] = response["used_tokens"]
                    response["token_accounting"]["total_context_footprint_tokens"] = (
                        response["used_tokens"]
                        + response["token_accounting"]["mcp_schema_overhead_tokens"]
                        + response["token_accounting"]["chat_framing_overhead_tokens"]
                    )
                return response["used_tokens"]
            response["estimated_tokens"] = max(response["estimated_tokens"], estimated)
            response["used_tokens"] = max(response["used_tokens"], measured)
            if "token_accounting" in response:
                response["token_accounting"]["payload_tokens"] = response["used_tokens"]
                response["token_accounting"]["total_context_footprint_tokens"] = (
                    response["used_tokens"]
                    + response["token_accounting"]["mcp_schema_overhead_tokens"]
                    + response["token_accounting"]["chat_framing_overhead_tokens"]
                )
        raise ValueError("Unable to stabilize payload accounting.")

    def finish(response, shown=(), touched=()):
        before = _revision(conn)
        now = int(time.time())
        if session:
            max_ts_row = conn.execute(
                "SELECT MAX(updated_at) FROM context_session_items WHERE project_id=? AND session_id=?",
                (project, session),
            ).fetchone()
            if max_ts_row and max_ts_row[0] is not None and max_ts_row[0] >= now:
                now = max_ts_row[0] + 1
        if session and touched:
            conn.executemany(
                "UPDATE context_session_items SET updated_at=? WHERE project_id=? AND session_id=? AND item_key=?",
                [(now, project, session, k) for k in touched],
            )
        if session and shown:
            conn.executemany(
                "INSERT INTO context_session_items VALUES(?,?,?,?,?) ON CONFLICT(project_id,session_id,item_key) DO UPDATE SET fingerprint=excluded.fingerprint,updated_at=excluded.updated_at",
                [(p, s, k, f, now) for (p, s, k, f, _) in shown],
            )
        features.log_retrieval(kn, conn, project, task, response, commit=False)
        conn.commit()
        _carry_internal_writes(conn, before)
        return response

    response = {
        "project": project,
        "mode": mode,
        "budget": budget,
        "budget_type": budget_type,
        "is_approximate": is_approx,
        "progressive_expansion": bool(args.get("expand_context", False)) or (mode == "deep"),
        "decision": "skip" if skip else "retrieve",
        "reason": (clf_reason if skip else "Ranked project metadata."),
        "results": [],
        "truncated": False,
        "suppressed_seen": 0,
    }
    if rehydrate:
        response["rehydrated"] = True
    if fallback:
        response["tokenizer_fallback"] = fallback
    response["budget_scope"] = (
        "compact sorted JSON payload; excludes MCP envelope and provider chat framing"
    )
    response["token_accounting"] = token_budget.token_accounting(
        payload_tokens=0,
        compact_mcp=compact_mcp,
        model=args.get("model"),
        is_approx=is_approx,
    )
    if skip:
        if used(response) > budget:
            response.pop("budget_scope", None)
            if used(response) > budget:
                response.pop("token_accounting", None)
                if used(response) > budget:
                    response.pop("progressive_expansion", None)
                    if used(response) > budget:
                        response.pop("is_approximate", None)
                        if used(response) > budget:
                            return {"error": "Budget is too small for response metadata."}
        return finish(response)
    ranked = _search(kn, project, task, conn)
    if "error" in ranked:
        return ranked
    results = ranked["results"]
    # Graph-only associations are not sufficient to assert relevance.
    if not any(
        item.get("via") != "graph"
        and (
            item.get("score", 0) >= 2
            or (
                item.get("type") == "asset"
                and item.get("freshness") in ("stale", "unverified")
                and item.get("match_score", 0) >= 2
            )
        )
        for item in results
    ):
        response["decision"] = "abstain"
        response["reason"] = "No confident metadata match; inspect the project or refine the task."
        if used(response) > budget:
            response.pop("budget_scope", None)
            if used(response) > budget:
                response.pop("token_accounting", None)
                if used(response) > budget:
                    response.pop("progressive_expansion", None)
                    if used(response) > budget:
                        response.pop("is_approximate", None)
                        if used(response) > budget:
                            return {"error": "Budget is too small for response metadata."}
        return finish(response)
    shown = []
    covered_paths = set()
    touched_suppressed = []
    suppressed_items = []

    # Batch prefetch to eliminate N+1 queries
    asset_ids = [raw["id"] for raw in results if raw.get("type") == "asset" and "id" in raw]
    evidence_by_asset: dict[int, list[str]] = {}
    if asset_ids:
        placeholders = ",".join("?" for _ in asset_ids)
        for row in conn.execute(
            f"SELECT m.asset_id, e.path FROM memory_evidence e JOIN memory_proposals m ON m.id=e.proposal_id "
            f"WHERE m.project_id=? AND m.status='approved' AND m.asset_id IN ({placeholders}) "
            f"ORDER BY m.asset_id, e.path",
            (project, *asset_ids),
        ):
            evidence_by_asset.setdefault(row["asset_id"], []).append(row["path"])

    candidate_paths = {raw["path"] for raw in results if raw.get("path")}
    digests_by_path: dict[str, str] = {}
    if candidate_paths:
        placeholders = ",".join("?" for _ in candidate_paths)
        for row in conn.execute(
            f"SELECT path, digest FROM files WHERE project_id=? AND path IN ({placeholders})",
            (project, *candidate_paths),
        ):
            digests_by_path[row["path"]] = row["digest"]

    session_items: dict[str, str] = {}
    session_files: set[str] = set()
    if session:
        for row in conn.execute(
            "SELECT item_key, fingerprint FROM context_session_items WHERE project_id=? AND session_id=?",
            (project, session),
        ):
            session_items[row["item_key"]] = row["fingerprint"]
            parts = row["item_key"].split(":")
            if parts and parts[0] in ("file", "symbol", "import") and len(parts) >= 2:
                session_files.add(parts[1])

    for raw in results:
        if raw["type"] == "file" and raw.get("path") in covered_paths:
            continue
        crumb = ContextCrumb(
            {
                k: raw[k]
                for k in (
                    "type",
                    "name",
                    "path",
                    "line",
                    "id",
                    "kind",
                    "freshness",
                    "verification_state",
                    "confidence",
                    "via",
                )
                if k in raw
            }
        )
        if raw["type"] == "asset":
            paths = evidence_by_asset.get(raw["id"], [])[:3]
            if paths:
                crumb["evidence_paths"] = paths
        expanded = expand and raw["type"] == "asset"
        if expanded:
            crumb.update(
                {
                    key: raw[key]
                    for key in ("summary", "source", "verification_state", "confidence_reasons")
                    if key in raw
                }
            )
        crumb["why"] = raw.get("why", "Metadata match.")
        if raw.get("freshness") == "stale":
            crumb["why"] += " Stale evidence; revalidate before reuse."
        elif raw.get("freshness") == "unverified":
            crumb["why"] += " Evidence unavailable or unverified; verify before reuse."
        elif raw.get("freshness") == "current":
            crumb["why"] += " Current as indexed; verify source."
        if mode != "compact" or args.get("why_this_context"):
            crumb["why_this_context"] = crumb["why"]
        if expanded:
            response["results"].append(crumb)
            too_large = used(response) > budget
            response["results"].pop()
            if too_large:
                for field in ("summary", "source", "confidence_reasons"):
                    crumb.pop(field, None)
                response["truncated"] = True
                expanded = False
        if (
            not expanded
            and raw["type"] == "asset"
            and raw.get("verification_state") == "verified"
            and raw.get("freshness") == "current"
        ):
            crumb["summary"] = raw["summary"]
            response["results"].append(crumb)
            if used(response) > budget:
                response.pop("budget_scope", None)
                if used(response) > budget:
                    response.pop("token_accounting", None)
            if used(response) > budget:
                crumb.pop("summary")
                response["truncated"] = True
            response["results"].pop()
        key = _key(crumb) + (":expanded" if expanded else "")
        crumb_hash = {k: v for k, v in crumb.items() if k != "why_this_context"}
        fingerprint_data = {"crumb": crumb_hash}
        if raw.get("path"):
            fingerprint_data["file_digest"] = digests_by_path.get(raw["path"])
        if raw["type"] == "asset":
            fingerprint_data.update({k: raw.get(k) for k in ("summary", "tags", "source")})
        fingerprint = hashlib.sha256(_encoded(fingerprint_data).encode("utf-8")).hexdigest()
        if session and not repeat:
            expanded_key = key + ":expanded" if raw["type"] == "asset" and not expanded else key
            seen = session_items
            if seen.get(key) == fingerprint:
                response["suppressed_seen"] += 1
                touched_suppressed.append(key)
                suppressed_items.append(
                    {
                        "key": key,
                        "type": raw.get("type"),
                        "path": raw.get("path"),
                        "name": raw.get("name"),
                    }
                )
                if raw["type"] in ("symbol", "import") and raw.get("path"):
                    covered_paths.add(raw["path"])
                continue
            if raw["type"] == "asset" and not expanded:
                full = dict(crumb)
                full.update(
                    {
                        field: raw[field]
                        for field in (
                            "summary",
                            "source",
                            "verification_state",
                            "confidence_reasons",
                        )
                        if field in raw
                    }
                )
                expanded_data = {**fingerprint_data, "crumb": full}
                expanded_fingerprint = hashlib.sha256(
                    _encoded(expanded_data).encode("utf-8")
                ).hexdigest()
                if seen.get(expanded_key) == expanded_fingerprint:
                    response["suppressed_seen"] += 1
                    touched_suppressed.append(expanded_key)
                    suppressed_items.append(
                        {"key": expanded_key, "type": "asset", "name": raw.get("name")}
                    )
                    continue
        response["results"].append(crumb)
        if used(response) > budget:
            response.pop("budget_scope", None)
            if used(response) > budget:
                response.pop("token_accounting", None)
        if used(response) > budget:
            response["results"].pop()
            response["truncated"] = True
            continue
        shown.append((project, session, key, fingerprint, int(time.time())))
        if raw["type"] in ("symbol", "import") and raw.get("path"):
            covered_paths.add(raw["path"])
    if not response["results"] and response["suppressed_seen"]:
        if session and touched_suppressed:
            now = int(time.time())
            max_ts_row = conn.execute(
                "SELECT MAX(updated_at) FROM context_session_items WHERE project_id=? AND session_id=?",
                (project, session),
            ).fetchone()
            if max_ts_row and max_ts_row[0] is not None and max_ts_row[0] >= now:
                now = max_ts_row[0] + 1
            conn.executemany(
                "UPDATE context_session_items SET updated_at=? WHERE project_id=? AND session_id=? AND item_key=?",
                [(now, project, session, k) for k in touched_suppressed],
            )
        response["reason"] = "Results already supplied in this session."
        recap_items = [
            {
                "key": item["key"],
                "type": item.get("type"),
                "path": item.get("path"),
                "name": item.get("name"),
            }
            for item in suppressed_items
        ]
        response["recap"] = recap_items
        response["active_context_summary"] = [item["key"] for item in suppressed_items]
        if session:
            recent_rows = conn.execute(
                "SELECT item_key FROM context_session_items WHERE project_id=? AND session_id=? "
                "ORDER BY updated_at DESC, item_key LIMIT 30",
                (project, session),
            ).fetchall()
            recent_keys = [r["item_key"] for r in recent_rows]
            graph_info = build_session_graph(kn, conn, project, recent_keys)
            response["active_graph"] = graph_info["active_graph"]
            response["graph_topology"] = graph_info["graph_topology"]
        if used(response) > budget:
            response.pop("active_graph", None)
            if used(response) > budget:
                response.pop("graph_topology", None)
                if used(response) > budget:
                    response.pop("budget_scope", None)
                    response.pop("token_accounting", None)
                    response.pop("progressive_expansion", None)
                    response["recap"] = [item["key"] for item in suppressed_items][:3]
                    response["active_context_summary"] = [item["key"] for item in suppressed_items][
                        :3
                    ]
                    if used(response) > budget:
                        response.pop("active_context_summary", None)
                        if used(response) > budget:
                            response["recap"] = [item["key"] for item in suppressed_items][:1]
                            if used(response) > budget:
                                response["recap"] = [
                                    item.get("name") or item["key"].split(":")[-2]
                                    for item in suppressed_items
                                ][:1]
                                if used(response) > budget:
                                    response.pop("is_approximate", None)
                                if used(response) > budget:
                                    response.pop("recap", None)
                                    if used(response) > budget:
                                        return {
                                            "error": "Budget is too small for session recap metadata."
                                        }
        if "recap" not in response:
            return {"error": "Budget is too small for session recap metadata."}
        if used(response) > budget:
            response.pop("budget_scope", None)
            response.pop("token_accounting", None)
            response.pop("progressive_expansion", None)
            if used(response) > budget:
                response.pop("is_approximate", None)
            if used(response) > budget:
                return {"error": "Budget is too small for response metadata."}
    if response["results"]:
        result_files = {c.get("path") for c in response["results"] if c.get("path")}
        combined_files = result_files | session_files
        if len(combined_files) > 1 and result_files:
            graph_edges = []
            placeholders = ",".join("?" for _ in combined_files)
            for imp in conn.execute(
                f"SELECT source, target FROM imports WHERE project_id=? AND source IN ({placeholders})",
                (project, *combined_files),
            ):
                target_file = _resolve_import_target(imp["source"], imp["target"], combined_files)
                if target_file and (imp["source"] in result_files or target_file in result_files):
                    if not any(
                        e["source"] == imp["source"] and e["target"] == target_file
                        for e in graph_edges
                    ):
                        graph_edges.append(
                            {"source": imp["source"], "target": target_file, "relation": "imports"}
                        )
            if graph_edges:
                response["graph_edges"] = graph_edges[:6]
                if used(response) > budget:
                    del response["graph_edges"]

        framework_rows = conn.execute(
            "SELECT a.name FROM assets a JOIN asset_projects p ON p.asset_id=a.id "
            "WHERE p.project_id=? AND a.kind IN ('framework', 'library') ORDER BY a.name LIMIT 6",
            (project,),
        ).fetchall()
        if framework_rows:
            response["reusable_frameworks"] = [r["name"] for r in framework_rows]
            if used(response) > budget:
                del response["reusable_frameworks"]

    if used(response) > budget:
        response.pop("budget_scope", None)
    if used(response) > budget:
        response.pop("token_accounting", None)
    if used(response) > budget:
        response.pop("progressive_expansion", None)
    if used(response) > budget:
        response.pop("is_approximate", None)
    if used(response) > budget:
        return {"error": "Budget is too small for response metadata."}
    return finish(response, shown, touched_suppressed)


def clear_session(kn, args, conn):
    project = features.project_id(kn, conn, args.get("project"))
    session = args.get("session_id")
    if not project or not isinstance(session, str) or not session.strip() or len(session) > 120:
        return {"error": "An indexed project and session_id are required."}
    count = conn.execute(
        "DELETE FROM context_session_items WHERE project_id=? AND session_id=?", (project, session)
    ).rowcount
    conn.commit()
    return {"cleared": count}


def build_session_graph(kn, conn, project, recent_keys):
    active_files = set()
    active_symbols = []
    active_asset_ids = set()

    for key in recent_keys:
        if key.startswith("file:"):
            rest = key[5:]
            p = rest.split(":", 1)[0]
            if p:
                active_files.add(p)
        elif key.startswith("symbol:"):
            rest = key[7:]
            rparts = rest.rsplit(":", 2)
            if len(rparts) == 3:
                p, name, line_str = rparts
                if p:
                    active_files.add(p)
                active_symbols.append(
                    {
                        "path": p,
                        "name": name,
                        "line": int(line_str) if line_str.isdigit() else 1,
                    }
                )
        elif key.startswith("import:"):
            rest = key[7:]
            p = rest.split(":", 1)[0]
            if p:
                active_files.add(p)
        elif key.startswith("asset:"):
            parts = key.split(":")
            if len(parts) >= 2 and parts[1].isdigit():
                active_asset_ids.add(int(parts[1]))

    seen_symbols = set()
    deduped_symbols = []
    for s in active_symbols:
        sym_key = (s["path"], s["name"], s["line"])
        if sym_key not in seen_symbols:
            seen_symbols.add(sym_key)
            deduped_symbols.append(s)
    active_symbols = deduped_symbols

    edges = []
    if active_files and conn:
        placeholders = ",".join("?" for _ in active_files)
        for imp in conn.execute(
            f"SELECT source, target FROM imports WHERE project_id=? AND source IN ({placeholders})",
            (project, *active_files),
        ):
            target_file = _resolve_import_target(imp["source"], imp["target"], active_files)
            if target_file and not any(
                e["source"] == imp["source"] and e["target"] == target_file for e in edges
            ):
                edges.append(
                    {"source": imp["source"], "target": target_file, "relation": "imports"}
                )

    active_lessons = []
    if active_asset_ids and conn:
        placeholders = ",".join("?" for _ in active_asset_ids)
        for row in conn.execute(
            f"SELECT id, name, summary FROM assets WHERE id IN ({placeholders}) "
            "AND (scope='global' OR (scope='project' AND project_id=?)) "
            "AND NOT EXISTS (SELECT 1 FROM memory_proposals m WHERE m.asset_id=assets.id AND m.status='superseded')",
            (*active_asset_ids, project),
        ):
            active_lessons.append({"id": row["id"], "name": row["name"], "summary": row["summary"]})
            for ev in conn.execute(
                "SELECT e.path FROM memory_evidence e JOIN memory_proposals m ON m.id=e.proposal_id WHERE m.asset_id=? AND m.project_id=?",
                (row["id"], project),
            ):
                if ev["path"] in active_files:
                    edges.append(
                        {"source": row["name"], "target": ev["path"], "relation": "guides"}
                    )

    reusable_frameworks = []
    if conn:
        framework_rows = conn.execute(
            "SELECT a.name FROM assets a JOIN asset_projects p ON p.asset_id=a.id "
            "WHERE p.project_id=? AND a.kind IN ('framework', 'library') ORDER BY a.name LIMIT 8",
            (project,),
        ).fetchall()
        reusable_frameworks = [r["name"] for r in framework_rows]

    topology = []
    for edge in edges[:10]:
        topology.append(f"{edge['source']} --({edge['relation']})--> {edge['target']}")
    for sym in active_symbols[:8]:
        topology.append(f"{sym['path']}:{sym['line']} defines {sym['name']}")
    for les in active_lessons[:4]:
        topology.append(f"Lesson: {les['name']} - {les['summary'][:100]}")

    return {
        "active_graph": {
            "files": sorted(active_files),
            "symbols": active_symbols[:15],
            "edges": edges[:15],
            "lessons": active_lessons,
            "reusable_frameworks": reusable_frameworks,
        },
        "graph_topology": topology,
    }


def session_checkpoint(kn, args, conn):
    project = features.project_id(kn, conn, args.get("project"))
    session = args.get("session_id")
    if not project or not isinstance(session, str) or not session.strip() or len(session) > 120:
        return {"error": "An indexed project and session_id are required."}
    now = int(time.time())

    # Ensure task_sessions record exists
    sess_row = conn.execute("SELECT * FROM task_sessions WHERE session_id=?", (session,)).fetchone()

    file_rows = conn.execute(
        "SELECT path, digest FROM files WHERE project_id=? ORDER BY path", (project,)
    ).fetchall()
    current_source_digest = hashlib.sha256(
        "".join(f"{r['path']}:{r['digest']};" for r in file_rows).encode("utf-8")
    ).hexdigest()

    goal = str(
        args.get("goal") or (dict(sess_row).get("goal", "") if sess_row else "") or ""
    ).strip()

    stored_source_digest = (
        dict(sess_row).get("source_digest") or current_source_digest
        if sess_row
        else current_source_digest
    )
    try:
        if sess_row is None:
            conn.execute(
                "INSERT INTO task_sessions(session_id, project_id, goal, status, source_digest, created_at, updated_at) VALUES(?, ?, ?, 'active', ?, ?, ?)",
                (session, project, goal, current_source_digest, now, now),
            )
            stored_source_digest = current_source_digest
        else:
            sess_dict = dict(sess_row)
            stored_source_digest = sess_dict.get("source_digest") or current_source_digest
            if goal and goal != sess_dict.get("goal", ""):
                conn.execute(
                    "UPDATE task_sessions SET goal=?, updated_at=? WHERE session_id=?",
                    (goal, now, session),
                )

        # Persist new decisions idempotently
        decisions_input = args.get("decisions", [])
        if isinstance(decisions_input, list):
            for d in decisions_input:
                if isinstance(d, str):
                    d_text, d_rat = d.strip(), ""
                elif isinstance(d, dict):
                    d_text = str(d.get("decision", "")).strip()
                    d_rat = str(d.get("rationale", "")).strip()
                else:
                    continue
                if d_text:
                    exists = conn.execute(
                        "SELECT 1 FROM session_decisions WHERE session_id=? AND decision=?",
                        (session, d_text),
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            "INSERT INTO session_decisions(session_id, decision, rationale, recorded_at) VALUES(?, ?, ?, ?)",
                            (session, d_text, d_rat, now),
                        )

        # Persist new blockers idempotently
        blockers_input = args.get("blockers", [])
        if isinstance(blockers_input, list):
            for b in blockers_input:
                if isinstance(b, str):
                    b_text, b_stat = b.strip(), "open"
                elif isinstance(b, dict):
                    b_text = str(b.get("blocker", "")).strip()
                    b_stat = str(b.get("status", "open")).strip()
                else:
                    continue
                if b_text:
                    exists = conn.execute(
                        "SELECT 1 FROM session_blockers WHERE session_id=? AND blocker=?",
                        (session, b_text),
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            "INSERT INTO session_blockers(session_id, blocker, status, recorded_at) VALUES(?, ?, ?, ?)",
                            (session, b_text, b_stat, now),
                        )

        # Persist new test outcomes idempotently
        test_outcomes_input = args.get("test_outcomes", [])
        if isinstance(test_outcomes_input, list):
            for t in test_outcomes_input:
                if isinstance(t, dict):
                    t_name = str(t.get("test_name", "")).strip()
                    t_outcome = str(t.get("outcome", "")).strip()
                    t_exit = int(t.get("exit_code", 0))
                    t_dur = float(t.get("duration_ms", 0.0))
                    if t_name:
                        exists = conn.execute(
                            "SELECT 1 FROM session_test_outcomes WHERE session_id=? AND test_name=? AND outcome=?",
                            (session, t_name, t_outcome),
                        ).fetchone()
                        if not exists:
                            conn.execute(
                                "INSERT INTO session_test_outcomes(session_id, test_name, outcome, exit_code, duration_ms, recorded_at) VALUES(?, ?, ?, ?, ?, ?)",
                                (session, t_name, t_outcome, t_exit, t_dur, now),
                            )

        # Persist breadcrumbs idempotently
        breadcrumbs_input = args.get("breadcrumbs", [])
        if isinstance(breadcrumbs_input, list):
            for c in breadcrumbs_input:
                if isinstance(c, str):
                    c_type, c_payload = "note", c.strip()
                elif isinstance(c, dict):
                    c_type = str(c.get("crumb_type", "note")).strip()
                    c_payload = json.dumps(c.get("payload", c))
                else:
                    continue
                if c_payload:
                    exists = conn.execute(
                        "SELECT 1 FROM session_breadcrumbs WHERE session_id=? AND payload=?",
                        (session, c_payload),
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            "INSERT INTO session_breadcrumbs(session_id, crumb_type, payload, recorded_at) VALUES(?, ?, ?, ?)",
                            (session, c_type, c_payload, now),
                        )
        conn.commit()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass

    # Detect source invalidation
    changed_files = []
    deleted_files = []
    root_row = conn.execute("SELECT root FROM projects WHERE id=?", (project,)).fetchone()
    if root_row and root_row["root"]:
        root_path = Path(root_row["root"])
        for r in file_rows:
            fpath = root_path / r["path"]
            if not fpath.exists():
                deleted_files.append(r["path"])
            else:
                try:
                    disk_digest = hashlib.sha256(fpath.read_bytes()).hexdigest()
                    if disk_digest != r["digest"]:
                        changed_files.append(r["path"])
                except OSError:
                    changed_files.append(r["path"])

    invalidated = bool(
        changed_files or deleted_files or (stored_source_digest != current_source_digest)
    )
    source_invalidation = {
        "invalidated": invalidated,
        "changed_files": changed_files,
        "deleted_files": deleted_files,
        "reason": (
            f"Source modified ({len(changed_files)} changed, {len(deleted_files)} deleted)."
            if invalidated
            else "Source code matches session checkpoint digest."
        ),
    }

    # Query context session items
    rows = conn.execute(
        "SELECT total.count, recent.item_key FROM "
        "(SELECT count(*) AS count FROM context_session_items WHERE project_id=? AND session_id=?) AS total "
        "LEFT JOIN (SELECT item_key,updated_at FROM context_session_items WHERE project_id=? AND session_id=? "
        "ORDER BY updated_at DESC, item_key LIMIT 30) AS recent ON 1=1 "
        "ORDER BY recent.updated_at DESC, recent.item_key",
        (project, session, project, session),
    ).fetchall()
    count = rows[0]["count"] if rows else 0
    recent_keys = [r["item_key"] for r in rows if r["item_key"] is not None]
    graph_info = build_session_graph(kn, conn, project, recent_keys)

    # Observed state
    observed_files = list(
        {k.split(":")[1] for k in recent_keys if ":" in k}
        | {
            f if isinstance(f, str) else str(f.get("path", f))
            for f in graph_info["active_graph"].get("files", [])
        }
    )
    observed_symbols = [
        s.get("name", str(s)) if isinstance(s, dict) else str(s)
        for s in graph_info["active_graph"].get("symbols", [])
    ]
    observed_state = {
        "files": observed_files,
        "symbols": observed_symbols,
        "active_graph": graph_info["active_graph"],
        "graph_topology": graph_info["graph_topology"],
    }

    # Asserted state
    saved_decisions = [
        {"decision": r["decision"], "rationale": r["rationale"], "recorded_at": r["recorded_at"]}
        for r in conn.execute(
            "SELECT decision, rationale, recorded_at FROM session_decisions WHERE session_id=? ORDER BY id",
            (session,),
        ).fetchall()
    ]
    saved_blockers = [
        {"blocker": r["blocker"], "status": r["status"], "recorded_at": r["recorded_at"]}
        for r in conn.execute(
            "SELECT blocker, status, recorded_at FROM session_blockers WHERE session_id=? ORDER BY id",
            (session,),
        ).fetchall()
    ]
    asserted_state = {
        "goal": goal,
        "decisions": saved_decisions,
        "blockers": saved_blockers,
    }

    # Verified state
    saved_tests = [
        {
            "test_name": r["test_name"],
            "outcome": r["outcome"],
            "exit_code": r["exit_code"],
            "duration_ms": r["duration_ms"],
            "recorded_at": r["recorded_at"],
        }
        for r in conn.execute(
            "SELECT test_name, outcome, exit_code, duration_ms, recorded_at FROM session_test_outcomes WHERE session_id=? ORDER BY id",
            (session,),
        ).fetchall()
    ]
    verified_lessons = [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, summary, lifecycle_state FROM memory_proposals WHERE project_id=? AND (lifecycle_state='verified' OR (status='approved' AND verification_state='verified'))",
            (project,),
        ).fetchall()
    ]
    verified_state = {
        "test_outcomes": saved_tests,
        "verified_lessons": verified_lessons,
    }

    recovery_breadcrumbs = [
        {"crumb_type": r["crumb_type"], "payload": r["payload"], "recorded_at": r["recorded_at"]}
        for r in conn.execute(
            "SELECT crumb_type, payload, recorded_at FROM session_breadcrumbs WHERE session_id=? ORDER BY id",
            (session,),
        ).fetchall()
    ]

    return {
        "project": project,
        "session_id": session,
        "goal": goal,
        "supplied_items": count,
        "recent_keys": recent_keys,
        "observed_state": observed_state,
        "asserted_state": asserted_state,
        "verified_state": verified_state,
        "source_invalidation": source_invalidation,
        "recovery_breadcrumbs": recovery_breadcrumbs,
        "active_graph": graph_info["active_graph"],
        "graph_topology": graph_info["graph_topology"],
        "truncated": count > 30,
        "note": "Reuse this project and session_id after compaction. Stored fingerprints suppress unchanged breadcrumbs; source contents are not stored.",
    }
