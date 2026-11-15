"""Task-aware, project-scoped metadata retrieval with optional session deduplication."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import posixpath
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
    repeat = args.get("include_seen", False)
    complete = args.get("context_is_complete", False)
    if not all(isinstance(x, bool) for x in (skip, repeat, complete)):
        return {"error": "skip_retrieval, include_seen and context_is_complete must be booleans."}
    explicit_text_task = (
        task.lstrip()
        .casefold()
        .startswith(
            ("rewrite this text", "format this text", "summarize this text", "summarise this text")
        )
    )
    skip = skip or (complete and explicit_text_task)
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
        count, budget_type, fallback = token_budget.counter(args, kn.estimate)
    except ValueError as exc:
        return {"error": str(exc)}

    def used(response):
        # Count the final compact payload, including the usage counters themselves.
        response["estimated_tokens"] = 0
        response["used_tokens"] = 0
        for _ in range(32):
            encoded = _encoded(response)
            estimated = kn.estimate(encoded)
            measured = count(encoded)
            if estimated <= response["estimated_tokens"] and measured <= response["used_tokens"]:
                return response["used_tokens"]
            response["estimated_tokens"] = max(response["estimated_tokens"], estimated)
            response["used_tokens"] = max(response["used_tokens"], measured)
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
        "decision": "skip" if skip else "retrieve",
        "reason": (
            (
                "Caller supplied complete context for a text-only task."
                if complete and explicit_text_task
                else "Caller explicitly requested no retrieval."
            )
            if skip
            else "Ranked project metadata."
        ),
        "results": [],
        "truncated": False,
        "suppressed_seen": 0,
    }
    if fallback:
        response["tokenizer_fallback"] = fallback
    response["budget_scope"] = (
        "compact sorted JSON payload; excludes MCP envelope and provider chat framing"
    )
    if skip:
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
        return (
            finish(response)
            if used(response) <= budget
            else {"error": "Budget is too small for response metadata."}
        )
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
        crumb = {
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
                crumb.pop("summary")
                response["truncated"] = True
            response["results"].pop()
        key = _key(crumb) + (":expanded" if expanded else "")
        fingerprint_data = {"crumb": crumb}
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
                    response["recap"] = [item["key"] for item in suppressed_items][:3]
                    response["active_context_summary"] = [item["key"] for item in suppressed_items][
                        :3
                    ]
                    if used(response) > budget:
                        response.pop("active_context_summary", None)
                        if used(response) > budget:
                            response["recap"] = [item["key"] for item in suppressed_items][:1]
                            if used(response) > budget:
                                response.pop("recap", None)
                                if used(response) > budget:
                                    return {
                                        "error": "Budget is too small for session recap metadata."
                                    }
        if "recap" not in response:
            return {"error": "Budget is too small for session recap metadata."}
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
    rows = conn.execute(
        "SELECT total.count, recent.item_key FROM "
        "(SELECT count(*) AS count FROM context_session_items WHERE project_id=? AND session_id=?) AS total "
        "LEFT JOIN (SELECT item_key,updated_at FROM context_session_items WHERE project_id=? AND session_id=? "
        "ORDER BY updated_at DESC, item_key LIMIT 30) AS recent ON 1=1 "
        "ORDER BY recent.updated_at DESC, recent.item_key",
        (project, session, project, session),
    ).fetchall()
    count = rows[0]["count"]
    recent_keys = [r["item_key"] for r in rows if r["item_key"] is not None]
    graph_info = build_session_graph(kn, conn, project, recent_keys)
    return {
        "project": project,
        "session_id": session,
        "supplied_items": count,
        "recent_keys": recent_keys,
        "truncated": count > 30,
        **graph_info,
        "note": "Reuse this project and session_id after compaction. Stored fingerprints suppress unchanged breadcrumbs; source contents are not stored.",
    }
