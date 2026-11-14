"""Task-aware, project-scoped metadata retrieval with optional session deduplication."""

from __future__ import annotations
import hashlib
import json
import time
import features
import token_budget
from collections import OrderedDict

_SEARCH_CACHE = OrderedDict()


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

    def finish(response, shown=()):
        before = _revision(conn)
        if session and shown:
            conn.executemany(
                "INSERT INTO context_session_items VALUES(?,?,?,?,?) ON CONFLICT(project_id,session_id,item_key) DO UPDATE SET fingerprint=excluded.fingerprint,updated_at=excluded.updated_at",
                shown,
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
            else "Search project metadata for task-relevant breadcrumbs."
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
        used(response)
        if used(response) > budget:
            return {"error": "Budget is too small for response metadata."}
        return finish(response)
    ranked = _search(kn, project, task, conn)
    if "error" in ranked:
        return ranked
    results = ranked["results"]
    # Graph-only associations are not sufficient to assert relevance.
    if not any(item.get("via") != "graph" and item.get("score", 0) >= 2 for item in results):
        response["decision"] = "abstain"
        response["reason"] = "No confident metadata match; inspect the project or refine the task."
        used(response)
        return (
            finish(response)
            if used(response) <= budget
            else {"error": "Budget is too small for response metadata."}
        )
    shown = []
    for raw in results:
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
                "confidence",
                "via",
            )
            if k in raw
        }
        if expand and raw["type"] == "asset":
            crumb.update(
                {
                    key: raw[key]
                    for key in ("summary", "source", "verification_state", "confidence_reasons")
                    if key in raw
                }
            )
        crumb["why"] = raw.get("why", "Metadata match.")
        key = _key(crumb) + (":expanded" if expand and raw["type"] == "asset" else "")
        fingerprint_data = {"crumb": crumb}
        if raw.get("path"):
            indexed = conn.execute(
                "SELECT digest FROM files WHERE project_id=? AND path=?", (project, raw["path"])
            ).fetchone()
            fingerprint_data["file_digest"] = indexed["digest"] if indexed else None
        if raw["type"] == "asset":
            fingerprint_data.update({k: raw.get(k) for k in ("summary", "tags", "source")})
        fingerprint = hashlib.sha256(_encoded(fingerprint_data).encode("utf-8")).hexdigest()
        if session and not repeat:
            seen = conn.execute(
                "SELECT fingerprint FROM context_session_items WHERE project_id=? AND session_id=? AND item_key=?",
                (project, session, key),
            ).fetchone()
            if seen and seen["fingerprint"] == fingerprint:
                response["suppressed_seen"] += 1
                continue
        response["results"].append(crumb)
        if used(response) > budget:
            response["results"].pop()
            response["truncated"] = True
            break
        shown.append((project, session, key, fingerprint, int(time.time())))
    if not response["results"] and response["suppressed_seen"]:
        response["reason"] = "All matching breadcrumbs were already supplied in this session."
    used(response)
    if used(response) > budget:
        return {"error": "Budget is too small for response metadata."}
    return finish(response, shown)


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


def session_checkpoint(kn, args, conn):
    project = features.project_id(kn, conn, args.get("project"))
    session = args.get("session_id")
    if not project or not isinstance(session, str) or not session.strip() or len(session) > 120:
        return {"error": "An indexed project and session_id are required."}
    rows = conn.execute(
        "SELECT item_key,updated_at FROM context_session_items WHERE project_id=? AND session_id=? ORDER BY item_key",
        (project, session),
    ).fetchall()
    return {
        "project": project,
        "session_id": session,
        "supplied_items": len(rows),
        "recent_keys": [r["item_key"] for r in rows[:30]],
        "truncated": len(rows) > 30,
        "note": "Reuse this project and session_id after compaction. Stored fingerprints suppress unchanged breadcrumbs; source contents are not stored.",
    }
