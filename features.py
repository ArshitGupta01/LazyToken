"""Local review, measurements and metadata retrieval for LazyToken."""

from __future__ import annotations
import json
import hashlib
import math
import sqlite3
import re
import time
from pathlib import Path


def migrate(conn):
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS lazytoken_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS benchmark_runs(id INTEGER PRIMARY KEY, task TEXT NOT NULL, variant TEXT NOT NULL, model TEXT, settings TEXT, input_tokens INTEGER, output_tokens INTEGER, elapsed_seconds REAL, successful INTEGER, unnecessary_file_reads INTEGER, indexing_tokens INTEGER, recorded_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS memory_proposals(id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, summary TEXT NOT NULL, task TEXT NOT NULL, evidence TEXT NOT NULL, commit_ref TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', asset_id INTEGER, created_at INTEGER NOT NULL, reviewed_at INTEGER);
    CREATE TABLE IF NOT EXISTS memory_evidence(proposal_id INTEGER NOT NULL, path TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(proposal_id,path));
    CREATE TABLE IF NOT EXISTS context_session_items(project_id TEXT NOT NULL, session_id TEXT NOT NULL, item_key TEXT NOT NULL, fingerprint TEXT NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY(project_id,session_id,item_key));
    CREATE TABLE IF NOT EXISTS fts_project_state(project_id TEXT PRIMARY KEY, complete INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS context_session_lookup_idx ON context_session_items(project_id, session_id, updated_at DESC, item_key);
    CREATE INDEX IF NOT EXISTS memory_proposals_asset_idx ON memory_proposals(asset_id, status);
    CREATE INDEX IF NOT EXISTS memory_proposals_proj_kind_idx ON memory_proposals(project_id, kind, status);
    INSERT OR IGNORE INTO lazytoken_migrations VALUES(1, strftime('%s','now'));
    INSERT OR IGNORE INTO lazytoken_migrations VALUES(2, strftime('%s','now'));
    """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory_proposals)")}
    for name, definition in (
        ("problem", "TEXT NOT NULL DEFAULT ''"),
        ("attempts", "TEXT NOT NULL DEFAULT ''"),
        ("resolution", "TEXT NOT NULL DEFAULT ''"),
        ("verification_state", "TEXT NOT NULL DEFAULT 'hypothesis'"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE memory_proposals ADD COLUMN {name} {definition}")
    conn.execute("INSERT OR IGNORE INTO lazytoken_migrations VALUES(3, strftime('%s','now'))")
    fts_existed = conn.execute("SELECT 1 FROM sqlite_master WHERE name='lazytoken_fts'").fetchone()
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS lazytoken_fts USING fts5(project_id UNINDEXED,kind UNINDEXED,path,name,tokenize='unicode61')"
        )
        if not fts_existed:
            conn.execute("DELETE FROM fts_project_state")
    except sqlite3.OperationalError:
        pass  # FTS5 is optional; deterministic lexical search remains available.
    conn.execute("INSERT OR IGNORE INTO lazytoken_migrations VALUES(4, strftime('%s','now'))")
    conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS index_state(project_id TEXT PRIMARY KEY, extractor_version INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS index_errors(project_id TEXT NOT NULL,path TEXT NOT NULL,PRIMARY KEY(project_id,path));
    CREATE TABLE IF NOT EXISTS benchmark_records(task_id TEXT NOT NULL,pair_id TEXT NOT NULL,arm TEXT NOT NULL,record_json TEXT NOT NULL,recorded_at INTEGER NOT NULL,PRIMARY KEY(task_id,pair_id,arm));
    INSERT OR IGNORE INTO lazytoken_migrations VALUES(5,strftime('%s','now'));
    """
    )
    conn.commit()


def refresh_fts(conn, project, changed_paths, removed_paths):
    """Build once, then update changed metadata only; never index source bodies."""
    conn.execute("SAVEPOINT fts_update")
    try:
        conn.execute("SELECT 1 FROM lazytoken_fts LIMIT 1").fetchone()
        complete = conn.execute(
            "SELECT complete FROM fts_project_state WHERE project_id=?", (project,)
        ).fetchone()
        if not complete or not complete["complete"]:
            conn.execute("DELETE FROM lazytoken_fts WHERE project_id=?", (project,))
            conn.execute(
                "INSERT INTO lazytoken_fts(project_id,kind,path,name) SELECT project_id,'file',path,path FROM files WHERE project_id=?",
                (project,),
            )
            conn.execute(
                "INSERT INTO lazytoken_fts(project_id,kind,path,name) SELECT project_id,'symbol',path,name FROM symbols WHERE project_id=?",
                (project,),
            )
            conn.execute(
                "INSERT INTO lazytoken_fts(project_id,kind,path,name) SELECT project_id,'import',source,target FROM imports WHERE project_id=?",
                (project,),
            )
            conn.execute("INSERT OR REPLACE INTO fts_project_state VALUES(?,1)", (project,))
        else:
            for path in set(changed_paths) | set(removed_paths):
                conn.execute(
                    "DELETE FROM lazytoken_fts WHERE project_id=? AND path=?", (project, path)
                )
                conn.execute(
                    "INSERT INTO lazytoken_fts(project_id,kind,path,name) SELECT project_id,'file',path,path FROM files WHERE project_id=? AND path=?",
                    (project, path),
                )
                conn.execute(
                    "INSERT INTO lazytoken_fts(project_id,kind,path,name) SELECT project_id,'symbol',path,name FROM symbols WHERE project_id=? AND path=?",
                    (project, path),
                )
                conn.execute(
                    "INSERT INTO lazytoken_fts(project_id,kind,path,name) SELECT project_id,'import',source,target FROM imports WHERE project_id=? AND source=?",
                    (project, path),
                )
        conn.execute("RELEASE fts_update")
        return True
    except sqlite3.OperationalError:
        conn.execute("ROLLBACK TO fts_update")
        conn.execute("RELEASE fts_update")
        conn.execute("INSERT OR REPLACE INTO fts_project_state VALUES(?,0)", (project,))
        return False


def project_id(kn, conn, value):
    value = str(value or "").strip()
    resolved = kn.resolve_project(value, conn) if value and value != "*" else ""
    return (
        resolved
        if resolved and conn.execute("SELECT 1 FROM projects WHERE id=?", (resolved,)).fetchone()
        else ""
    )


def log_retrieval(kn, conn, project, query, response, commit=True):
    encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    conn.execute(
        "INSERT INTO retrievals VALUES(?,?,?,?,?)",
        (int(time.time()), project, len(query), len(encoded), kn.estimate(encoded)),
    )
    if commit:
        conn.commit()


def canonical_benchmark_record(args, conn):
    from benchmark import harness

    try:
        corpus = harness.load_corpus(Path(__file__).parent / "benchmark" / "corpus.json")
        row = harness.validate_runs([args], corpus)[0]
        payload = {key: row[key] for key in harness.FIELDS}
        conn.execute(
            "INSERT INTO benchmark_records VALUES(?,?,?,?,?)",
            (
                row["task_id"],
                row["pair_id"],
                row["arm"],
                json.dumps(payload, sort_keys=True),
                int(time.time()),
            ),
        )
        conn.commit()
        return {
            "saved": True,
            "measurement_kind": row["measurement_kind"],
            "note": "Recorded only; no agent task executed.",
        }
    except (ValueError, sqlite3.IntegrityError) as exc:
        conn.rollback()
        return {"error": str(exc)}


def canonical_benchmarks(conn):
    from benchmark import harness

    corpus = harness.load_corpus(Path(__file__).parent / "benchmark" / "corpus.json")
    records = [
        json.loads(row[0])
        for row in conn.execute(
            "SELECT record_json FROM benchmark_records ORDER BY task_id,pair_id,arm"
        )
    ]
    rows = harness.validate_runs(records, corpus)
    return {"runs": rows, "comparisons": harness.compare(rows)}


def benchmark(args, conn):
    if "task_id" in args:
        return canonical_benchmark_record(args, conn)
    task = str(args.get("task", "")).strip()[:240]
    variant = args.get("variant")
    if not task or variant not in ("baseline", "network"):
        return {"error": "Provide a task and variant baseline or network."}
    values = []
    for field in (
        "input_tokens",
        "output_tokens",
        "elapsed_seconds",
        "unnecessary_file_reads",
        "indexing_tokens",
    ):
        v = args.get(field)
        if v is not None:
            if (
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                or v < 0
                or (field != "elapsed_seconds" and int(v) != v)
            ):
                return {"error": field + " must be a non-negative number or null."}
        values.append(v)
    success = args.get("successful")
    if success is not None and not isinstance(success, bool):
        return {"error": "successful must be a boolean or null."}
    settings = args.get("settings")
    if settings is not None and not isinstance(settings, (str, dict)):
        return {"error": "settings must be text or an object."}
    serialized = (
        json.dumps(settings, ensure_ascii=False, sort_keys=True) if settings is not None else None
    )
    if serialized is not None and len(serialized) > 4000:
        return {"error": "settings must be at most 4000 characters."}
    cur = conn.execute(
        "INSERT INTO benchmark_runs(task,variant,model,settings,input_tokens,output_tokens,elapsed_seconds,successful,unnecessary_file_reads,indexing_tokens,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            task,
            variant,
            str(args["model"])[:200] if args.get("model") is not None else None,
            serialized,
            *values[:3],
            int(success) if success is not None else None,
            *values[3:],
            int(time.time()),
        ),
    )
    conn.commit()
    return {"saved": True, "id": cur.lastrowid}


def benchmark_list(conn):
    rows = [
        dict(r) for r in conn.execute("SELECT * FROM benchmark_runs ORDER BY id DESC LIMIT 200")
    ]
    for r in rows:
        r["successful"] = bool(r["successful"]) if r["successful"] is not None else None
        r["total_tokens"] = (
            r["input_tokens"] + r["output_tokens"]
            if r["input_tokens"] is not None and r["output_tokens"] is not None
            else None
        )
    groups = {}
    for r in rows:
        key = (r["task"], r["model"], r["settings"])
        group = groups.setdefault(
            key,
            {
                "task": r["task"],
                "model": r["model"],
                "settings": r["settings"],
                "baseline": None,
                "network": None,
                "net_tokens_saved": None,
            },
        )
        if group[r["variant"]] is None:
            group[r["variant"]] = r
    for group in groups.values():
        base, network = group["baseline"], group["network"]
        group["eligible_for_claim"] = False
        group["measurement_kind"] = "legacy_unverified"
        if (
            group["model"]
            and group["settings"] is not None
            and base
            and network
            and base["successful"] is True
            and network["successful"] is True
            and base["total_tokens"] is not None
            and network["total_tokens"] is not None
            and network["indexing_tokens"] is not None
        ):
            group["recorded_difference"] = (
                base["total_tokens"] - network["total_tokens"] - network["indexing_tokens"]
            )
    return {
        "runs": rows,
        "comparisons": list(groups.values()),
        "canonical": canonical_benchmarks(conn),
        "note": "Latest runs grouped by task, model and settings; confirm they were matched. Missing values are unknown.",
    }


def propose(kn, args, conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        return _propose(kn, args, conn)
    finally:
        if conn.in_transaction:
            conn.rollback()


def _propose(kn, args, conn):
    project = project_id(kn, conn, args.get("project"))
    kind = str(args.get("kind", "")).strip()
    name = str(args.get("name", "")).strip()
    summary = str(args.get("summary", "")).strip()
    task = str(args.get("task", "")).strip()
    evidence = str(args.get("evidence", "")).strip()
    paths = args.get("paths", [])
    if not project:
        return {"error": "An indexed project is required."}
    if (
        kind not in ("lesson", "decision", "pattern", "component")
        or not name
        or len(name) > 160
        or not summary
        or len(summary) > 1200
        or not task
        or not evidence
        or not isinstance(paths, list)
        or len(paths) > 30
    ):
        return {
            "error": "Provide kind, name, summary, task, evidence, and up to 30 indexed evidence paths."
        }
    for field in ("problem", "attempts", "resolution"):
        if not isinstance(args.get(field, ""), str) or len(args.get(field, "")) > 3000:
            return {"error": field + " must be text of at most 3000 characters."}
    duplicate = conn.execute(
        "SELECT id FROM memory_proposals WHERE project_id=? AND kind=? AND lower(trim(name))=lower(trim(?)) AND status IN ('pending','approved') ORDER BY id LIMIT 1",
        (project, kind, name),
    ).fetchone()
    if duplicate:
        return {
            "error": "A pending or approved memory with this name already exists in this project.",
            "existing_id": duplicate["id"],
        }
    # Project-scoped near-duplicate detection never reads other projects' lessons.
    words = lambda text: set(kn.split_words(text))
    incoming = words(summary)
    related = []
    for candidate in conn.execute(
        "SELECT id,name,summary FROM memory_proposals WHERE project_id=? AND kind=? AND status IN ('pending','approved') ORDER BY id DESC LIMIT 200",
        (project, kind),
    ):
        existing = words(candidate["summary"])
        similarity = len(incoming & existing) / max(1, len(incoming | existing))
        if summary.strip().casefold() == candidate["summary"].strip().casefold():
            return {
                "error": "A similar pending or approved memory already exists in this project.",
                "existing_id": candidate["id"],
                "similarity": round(similarity, 3),
            }
        a, b = words(name), words(candidate["name"])
        if similarity >= 0.65 or len(a & b) / max(1, len(a | b)) >= 0.6:
            related.append(candidate["id"])
    evidence_rows = []
    for path in paths:
        if not isinstance(path, str):
            return {"error": "Evidence paths must be strings."}
        row = conn.execute(
            "SELECT digest FROM files WHERE project_id=? AND path=?", (project, path)
        ).fetchone()
        if not row:
            return {"error": "Every evidence path must be an indexed file in the selected project."}
        evidence_rows.append((path, row["digest"]))
    cur = conn.execute(
        "INSERT INTO memory_proposals(project_id,kind,name,summary,task,evidence,commit_ref,created_at,problem,attempts,resolution) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            project,
            kind,
            name,
            summary,
            task[:2000],
            evidence[:2000],
            str(args.get("commit_ref", ""))[:200],
            int(time.time()),
            args.get("problem", ""),
            args.get("attempts", ""),
            args.get("resolution", ""),
        ),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO memory_evidence VALUES(?,?,?)",
        [(cur.lastrowid, p, d) for p, d in evidence_rows],
    )
    conn.commit()
    return {
        "saved": True,
        "status": "pending",
        "id": cur.lastrowid,
        "related_candidates": related,
        "review_note": (
            "Related names may contain conflicting advice; human review is required."
            if related
            else None
        ),
    }


def proposal_list(kn, args, conn):
    project = project_id(kn, conn, args.get("project"))
    if not project:
        return {"error": "An indexed project is required."}
    status = args.get("status", "all")
    if status not in ("all", "pending", "approved", "rejected", "superseded"):
        return {"error": "Invalid status."}
    rows = conn.execute(
        "SELECT * FROM memory_proposals WHERE project_id=? AND (?='all' OR status=?) ORDER BY id DESC LIMIT 200",
        (project, status, status),
    )
    result = []
    for row in rows:
        r = dict(row)
        r["paths"] = [
            dict(x)
            for x in conn.execute(
                "SELECT path,digest FROM memory_evidence WHERE proposal_id=?", (r["id"],)
            )
        ]
        r.update(health(conn, r["id"]))
        result.append(r)
    return {"proposals": result}


def health(conn, proposal_id):
    row = conn.execute(
        "SELECT project_id,status,commit_ref,verification_state FROM memory_proposals WHERE id=?",
        (proposal_id,),
    ).fetchone()
    if not row:
        return {"error": "Unknown proposal."}
    evidence = list(
        conn.execute(
            "SELECT e.path,e.digest,f.digest current_digest FROM memory_evidence e LEFT JOIN files f ON f.project_id=? AND f.path=e.path WHERE e.proposal_id=?",
            (row["project_id"], proposal_id),
        )
    )
    changed = [e["path"] for e in evidence if e["digest"] != e["current_digest"]]
    unavailable = [
        e["path"]
        for e in evidence
        if conn.execute(
            "SELECT 1 FROM index_errors WHERE project_id=? AND path=?",
            (row["project_id"], e["path"]),
        ).fetchone()
    ]
    state = (
        "unverified"
        if unavailable
        else ("stale" if changed else ("current" if evidence else "unverified"))
    )
    reasons = [
        (
            "human verified"
            if row["verification_state"] == "verified"
            else "hypothesis or not verified"
        ),
        "indexed file evidence" if evidence else "no indexed file evidence",
        state,
        "project scoped",
        "commit reference provided" if row["commit_ref"] else "no commit reference",
    ]
    score = (
        (0.35 if row["status"] == "approved" and row["verification_state"] == "verified" else 0)
        + (0.25 if evidence else 0)
        + (0.2 if state == "current" else 0)
        + (0.1 if row["commit_ref"] else 0)
        + 0.1
    )
    return {
        "freshness": state,
        "freshness_basis": "indexed hashes; approval also validates live files",
        "verification_state": row["verification_state"],
        "changed_paths": changed,
        "unavailable_paths": unavailable,
        "confidence": round(score, 2),
        "confidence_reasons": reasons,
    }


def review(kn, args, conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        return _review(kn, args, conn)
    finally:
        if conn.in_transaction:
            conn.rollback()


def live_evidence_error(kn, conn, proposal, project):
    root_row = conn.execute("SELECT root FROM projects WHERE id=?", (project,)).fetchone()
    rows = conn.execute(
        "SELECT e.path,e.digest,f.digest indexed_digest FROM memory_evidence e LEFT JOIN files f ON f.project_id=? AND f.path=e.path WHERE e.proposal_id=?",
        (project, proposal),
    ).fetchall()
    if not rows:
        return "Review requires indexed evidence paths."
    root = Path(root_row["root"])
    eligible = set(kn.list_files(root))
    for row in rows:
        if not kn.safe_file(root, row["path"]) or row["path"] not in eligible:
            return "Evidence is missing or no longer eligible; sync before review."
        try:
            with (root / row["path"]).open("rb") as source:
                raw = source.read(1_000_001)
        except OSError:
            return "Evidence cannot be read; review refused."
        if len(raw) > 1_000_000 or hashlib.sha256(raw).hexdigest() != row["indexed_digest"]:
            return "Evidence changed on disk; sync before review."
    return None


def _review(kn, args, conn):
    project = project_id(kn, conn, args.get("project"))
    if not project:
        return {"error": "An indexed project is required."}
    try:
        pid = int(args.get("id", 0))
    except (ValueError, TypeError):
        return {"error": "Invalid proposal id."}
    row = conn.execute(
        "SELECT * FROM memory_proposals WHERE id=? AND project_id=?", (pid, project)
    ).fetchone()
    if not row:
        return {"error": "Proposal not found in this project."}
    action = args.get("action")
    if action in ("approve", "revalidate"):
        error = live_evidence_error(kn, conn, pid, project)
        if error:
            return {"error": error}
    if action == "supersede":
        if row["status"] != "approved":
            return {"error": "Only approved memories can be superseded."}
        conn.execute(
            "UPDATE memory_proposals SET status='superseded',reviewed_at=? WHERE id=?",
            (int(time.time()), pid),
        )
        conn.commit()
        return {"saved": True, "status": "superseded", "asset_id": row["asset_id"]}
    if action == "revalidate":
        if row["status"] != "approved":
            return {"error": "Only approved memories can be revalidated."}
        paths = list(
            conn.execute(
                "SELECT e.path,f.digest FROM memory_evidence e LEFT JOIN files f ON f.project_id=? AND f.path=e.path WHERE e.proposal_id=?",
                (project, pid),
            )
        )
        if not paths or any(not p["digest"] for p in paths):
            return {"error": "All evidence files must be indexed before revalidation."}
        conn.executemany(
            "UPDATE memory_evidence SET digest=? WHERE proposal_id=? AND path=?",
            [(p["digest"], pid, p["path"]) for p in paths],
        )
        conn.execute(
            "UPDATE memory_proposals SET reviewed_at=? WHERE id=?", (int(time.time()), pid)
        )
        conn.commit()
        return {"saved": True, "status": "approved", **health(conn, pid)}
    if row["status"] != "pending":
        return {"error": "Only pending proposals can be reviewed."}
    if action == "edit":
        name = str(args.get("name", row["name"])).strip()
        summary = str(args.get("summary", row["summary"])).strip()
        evidence = str(args.get("evidence", row["evidence"])).strip()
        if not name or len(name) > 160 or not summary or len(summary) > 1200 or not evidence:
            return {"error": "Invalid name, summary or evidence."}
        duplicate = conn.execute(
            "SELECT id FROM memory_proposals WHERE project_id=? AND kind=? AND lower(trim(name))=lower(trim(?)) AND status IN ('pending','approved') AND id<>?",
            (project, row["kind"], name, pid),
        ).fetchone()
        if duplicate:
            return {
                "error": "A memory with this name already exists in this project.",
                "existing_id": duplicate["id"],
            }
        changed = conn.execute(
            "UPDATE memory_proposals SET name=?,summary=?,evidence=? WHERE id=? AND status='pending'",
            (name, summary, evidence[:2000], pid),
        ).rowcount
        conn.commit()
        return (
            {"saved": True, "status": "pending"}
            if changed
            else {"error": "Proposal was already reviewed."}
        )
    if action not in ("approve", "reject"):
        return {"error": "action must be edit, approve, or reject."}
    if action == "approve":
        if health(conn, pid)["freshness"] == "stale":
            return {
                "error": "Evidence changed since submission; submit a fresh proposal before approval."
            }
        verified = args.get("verified", False)
        if not isinstance(verified, bool):
            return {"error": "verified must be a boolean."}
        if verified and health(conn, pid)["freshness"] != "current":
            return {"error": "Verification requires current indexed file evidence."}
    status = "approved" if action == "approve" else "rejected"
    changed = conn.execute(
        "UPDATE memory_proposals SET status=?,reviewed_at=? WHERE id=? AND status='pending'",
        (status, int(time.time()), pid),
    ).rowcount
    if not changed:
        conn.rollback()
        return {"error": "Proposal was already reviewed."}
    if action == "approve":
        # Create a distinct project-scoped asset; never overwrite existing trusted knowledge.
        cur = conn.execute(
            "INSERT INTO assets(kind,name,summary,tags,source,created_at,scope,project_id) VALUES(?,?,?,?,?,?,?,?)",
            (
                row["kind"],
                row["name"],
                row["summary"],
                "",
                row["evidence"][:500],
                int(time.time()),
                "project",
                project,
            ),
        )
        aid = cur.lastrowid
        conn.execute("INSERT INTO asset_projects VALUES(?,?,?)", (aid, project, "used_in"))
    else:
        aid = None
    conn.execute(
        "UPDATE memory_proposals SET asset_id=?,verification_state=? WHERE id=?",
        (aid, "verified" if action == "approve" and verified else "hypothesis", pid),
    )
    conn.commit()
    return {"saved": True, "status": status, "asset_id": aid}


def ranked_search(kn, args, conn):
    try:
        limit = int(args.get("limit", 20))
    except (ValueError, TypeError, OverflowError):
        return {"error": "limit must be an integer."}
    if isinstance(args.get("limit"), bool) or isinstance(args.get("limit"), float):
        return {"error": "limit must be an integer."}
    limit = max(1, min(100, limit))
    project = project_id(kn, conn, args.get("project"))
    if not project:
        return {"error": "An indexed project is required."}
    query = str(args.get("query", ""))[:1000]
    words = [t for t in kn.split_words(query) if len(t) > 1]
    # Keep the limited search budget for meaningful terms in natural-language tasks.
    stop_words = set(
        "the and for with that this from while into where which what when how does its "
        "is are was were to of in on at an or as by".split()
    )
    terms = list(dict.fromkeys(t for t in words if t not in stop_words))[:12]
    if not terms:
        terms = list(dict.fromkeys(words))[:12]
    aliases = {
        "authentication": ["auth", "login", "signin", "session"],
        "auth": ["authentication", "login", "session"],
        "user": ["account", "profile"],
        "login": ["auth", "signin", "session"],
        "approval": ["approve", "review"],
        "approved": ["approve", "review"],
        "proposal": ["propose"],
    }
    terms = list(dict.fromkeys(terms + [alias for t in terms for alias in aliases.get(t, [])]))
    if not terms:
        return {"query": query, "project": project, "results": []}
    fts_hits = set()
    try:
        state = conn.execute(
            "SELECT complete FROM fts_project_state WHERE project_id=?", (project,)
        ).fetchone()
        if state and state["complete"]:
            match = " OR ".join('"' + term + '"*' for term in terms)
            fts_hits = {
                (r["kind"], r["path"], r["name"])
                for r in conn.execute(
                    "SELECT kind,path,name FROM lazytoken_fts WHERE lazytoken_fts MATCH ? AND project_id=? LIMIT 300",
                    (match, project),
                )
            }
    except sqlite3.OperationalError:
        pass  # FTS5 is unavailable or an index is not ready.

    def score(text):
        words = kn.search_words(text)
        return sum(1 for t in terms if t in words)

    rows = []

    def candidates(table, columns, fields):
        # SQL prefilter preserves every lexical match while avoiding Python work on unrelated rows.
        clause = " OR ".join("lower(" + fields + ") LIKE ?" for _ in terms)
        return conn.execute(
            "SELECT " + columns + " FROM " + table + " WHERE project_id=? AND (" + clause + ")",
            (project, *("%" + term + "%" for term in terms)),
        )

    for r in candidates("files", "path", "path"):
        n = score(r["path"]) + (1 if ("file", r["path"], r["path"]) in fts_hits else 0)
        if n:
            rows.append(
                {
                    "type": "file",
                    "path": r["path"],
                    "name": Path(r["path"]).name,
                    "score": n * 2,
                    "why": "Path match.",
                }
            )
    for r in candidates("symbols", "path,name,line", "name||' '||path"):
        n = (
            score(r["name"]) * 4
            + score(r["path"]) * 2
            + (1 if ("symbol", r["path"], r["name"]) in fts_hits else 0)
        )
        if n:
            rows.append(
                {
                    "type": "symbol",
                    **dict(r),
                    "score": n,
                    "why": "Symbol/path match.",
                }
            )
    for r in candidates("imports", "source,target", "target"):
        target_score = score(r["target"]) + (
            1 if ("import", r["source"], r["target"]) in fts_hits else 0
        )
        if target_score:
            rows.append(
                {
                    "type": "import",
                    "path": r["source"],
                    "name": r["target"],
                    "score": target_score * 3 + score(r["source"]),
                    "why": "Import match.",
                }
            )

    def add_asset(entry):
        memory = conn.execute(
            "SELECT id FROM memory_proposals WHERE asset_id=?", (entry["id"],)
        ).fetchone()
        if memory:
            entry["match_score"] = entry["score"]
            entry.update(health(conn, memory["id"]))
            entry["score"] *= 0.5 + 0.5 * entry["confidence"]
            if entry["freshness"] in ("stale", "unverified"):
                entry["score"] *= 0.3
        rows.append(entry)

    for r in conn.execute(
        "SELECT id,kind,name,summary,tags,source FROM assets WHERE scope='global' OR (scope='project' AND project_id=?)",
        (project,),
    ):
        if conn.execute(
            "SELECT 1 FROM memory_proposals WHERE asset_id=? AND status='superseded'", (r["id"],)
        ).fetchone():
            continue
        n = score(r["name"]) * 4 + score(r["summary"]) * 2 + score(r["tags"])
        if n:
            entry = {
                "type": "asset",
                **dict(r),
                "score": n,
                "why": "Task terms matched this asset name, summary, or tags.",
            }
            add_asset(entry)
    # Include scoped neighbors of directly matched assets, without crossing project boundaries.
    matched = {r["id"] for r in rows if r["type"] == "asset"}
    graph_links = {}
    for asset in sorted(matched):
        for e in conn.execute(
            "SELECT source_id,target_id,relation,scope,weight FROM asset_link_evidence WHERE (scope='*' OR scope=?) AND (source_id=? OR target_id=?)",
            (project, asset, asset),
        ):
            neighbor = e["target_id"] if e["source_id"] == asset else e["source_id"]
            if neighbor in matched:
                continue
            previous = graph_links.get(neighbor)
            if previous is None or e["weight"] > previous[1]["weight"]:
                graph_links[neighbor] = (asset, e)
    for neighbor, (asset, e) in graph_links.items():
        r = conn.execute(
            "SELECT id,kind,name,summary,tags,source FROM assets WHERE id=? AND (scope='global' OR (scope='project' AND project_id=?))",
            (neighbor, project),
        ).fetchone()
        if r:
            if conn.execute(
                "SELECT 1 FROM memory_proposals WHERE asset_id=? AND status='superseded'",
                (neighbor,),
            ).fetchone():
                continue
            origin = conn.execute("SELECT name FROM assets WHERE id=?", (asset,)).fetchone()
            entry = {
                "type": "asset",
                **dict(r),
                "score": round(float(e["weight"]), 2),
                "via": "graph",
                "why": f"Connected to {origin['name']} by {e['relation']} (weight {float(e['weight']):.2f}; {'global' if e['scope']=='*' else 'project'}).",
            }
            add_asset(entry)
    wants_tests = bool({"test", "tests", "testing"} & set(terms))
    for row in rows:
        path = row.get("path", "").replace("\\", "/").casefold()
        parts = path.split("/")
        if "vendor" in parts and "vendor" not in terms:
            row["score"] *= 0.25
        elif ("tests" in parts or parts[-1].startswith("test_")) and not wants_tests:
            row["score"] *= 0.65
    rows.sort(key=lambda r: (-r["score"], str(r.get("name", "")).casefold(), r.get("path", "")))
    return {"query": query, "project": project, "results": rows[:limit]}


def bounded_context(kn, args, conn):
    project = project_id(kn, conn, args.get("project"))
    if not project:
        return {"error": "An indexed project is required."}
    try:
        budget = int(args.get("budget", 1000))
    except (ValueError, TypeError):
        return {"error": "budget must be an integer."}
    if not 100 <= budget <= 16000:
        return {"error": "budget must be between 100 and 16000 estimated tokens."}
    query = str(args.get("query", ""))[:1000]
    omit = args.get("exclude_paths", [])
    omit_assets = args.get("exclude_asset_ids", [])
    if not isinstance(omit, list) or any(not isinstance(p, str) for p in omit):
        return {"error": "exclude_paths must be a list of paths."}
    if not isinstance(omit_assets, list) or any(
        isinstance(i, bool) or not isinstance(i, int) for i in omit_assets
    ):
        return {"error": "exclude_asset_ids must be a list of integer asset IDs."}
    result = {
        "project": project,
        "budget": budget,
        "budget_type": "estimated characters / 4; not a model tokenizer",
        "map": [],
        "results": [],
        "truncated": False,
    }
    for r in conn.execute(
        "SELECT path FROM files WHERE project_id=? ORDER BY path LIMIT 10", (project,)
    ):
        if r["path"] not in omit:
            result["map"].append(r["path"])
    candidates = (
        ranked_search(kn, {"project": project, "query": query, "limit": 100}, conn)["results"]
        if query
        else []
    )
    for item in candidates:
        if item.get("path") in omit or (
            item.get("type") == "asset" and item.get("id") in omit_assets
        ):
            continue
        result["results"].append(item)
        if kn.estimate(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > budget - 20:
            result["results"].pop()
            result["truncated"] = True
            break
    while (
        result["map"]
        and kn.estimate(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > budget - 20
    ):
        result["map"].pop()
        result["truncated"] = True
    if kn.estimate(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > budget - 20:
        return {"error": "Budget is too small for the project metadata."}
    result["estimated_tokens"] = kn.estimate(
        json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    )
    log_retrieval(kn, conn, project, query, result)
    return result


def dependencies(kn, args, conn):
    project = project_id(kn, conn, args.get("project"))
    if not project:
        return {"error": "An indexed project is required."}
    items = []
    by_name = {}
    for symbol in conn.execute("SELECT path,name,line FROM symbols WHERE project_id=?", (project,)):
        by_name.setdefault(symbol["name"], []).append(symbol)
    for imp in conn.execute(
        "SELECT source,target FROM imports WHERE project_id=? ORDER BY source,target LIMIT 500",
        (project,),
    ):
        leaf = imp["target"].replace("/", ".").split(".")[-1]
        matches = [s for s in by_name.get(leaf, ()) if s["path"] != imp["source"]]
        items.append(
            {
                "source": imp["source"],
                "import": imp["target"],
                "candidates": [dict(s) for s in matches[:10]],
                "status": "provisional" if matches else "unresolved",
            }
        )
    return {"dependencies": items, "note": "Name-based candidates are not compiler-resolved."}


def inspect_source(kn, args, conn):
    """Explicit, bounded source inspection for an eligible indexed file."""
    project = project_id(kn, conn, args.get("project"))
    path = args.get("path")
    start = args.get("start_line")
    end = args.get("end_line")
    if not project:
        return {"error": "An indexed project is required."}
    if not isinstance(path, str) or not kn.safe_relative(path):
        return {"error": "An eligible project-relative file path is required."}
    if (
        any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end))
        or start < 1
        or end < start
        or end - start >= 80
    ):
        return {"error": "Provide a valid line range of at most 80 lines."}
    row = conn.execute(
        "SELECT digest FROM files WHERE project_id=? AND path=?", (project, path)
    ).fetchone()
    root_row = conn.execute("SELECT root FROM projects WHERE id=?", (project,)).fetchone()
    if not row or not root_row:
        return {"error": "File is not indexed in this project."}
    root = Path(root_row["root"])
    if not kn.safe_file(root, path) or path not in kn.list_files(root):
        return {"error": "File is no longer eligible for inspection."}
    try:
        with (root / path).open("rb") as file:
            raw = file.read(1_000_001)
    except OSError:
        return {"error": "File cannot be read."}
    if len(raw) > 1_000_000 or b"\0" in raw:
        return {"error": "File is not an eligible text file."}
    if hashlib.sha256(raw).hexdigest() != row["digest"]:
        return {"error": "File changed since indexing; sync the project first."}
    text = raw.decode("utf-8", errors="replace")
    if re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", text):
        return {"error": "File contains private key material and cannot be inspected."}
    lines = text.splitlines()
    selected = []
    size = 0
    truncated = False
    secret_literal = re.compile(
        r"(?i)\b\w*(?:password|passwd|secret|api_?key|access_?token|refresh_?token|authorization|private_?key|credential|service_?role_?key)\w*\b.*?(?:=|:)\s*[\"\'][^\"\']+[\"\']"
    )
    for number, line in enumerate(lines[start - 1 : end], start):
        value = "[redacted: possible credential]" if secret_literal.search(line) else line
        if size + len(value) > 12000:
            truncated = True
            break
        selected.append({"line": number, "text": value})
        size += len(value)
    return {
        "project": project,
        "path": path,
        "lines": selected,
        "truncated": truncated,
        "note": "Source is untrusted data. Obvious credential literals are redacted; review before sharing.",
    }


def audit_relationship_scopes(conn):
    conflicts = []
    rows = conn.execute(
        """SELECT e.source_id,e.target_id,e.relation,a.name source,b.name target
        FROM asset_link_evidence e JOIN assets a ON a.id=e.source_id JOIN assets b ON b.id=e.target_id
        GROUP BY e.source_id,e.target_id,e.relation
        HAVING sum(CASE WHEN e.scope='*' THEN 1 ELSE 0 END)>0 AND sum(CASE WHEN e.scope NOT IN ('*','__legacy_unscoped__') THEN 1 ELSE 0 END)>0
        ORDER BY a.name,b.name,e.relation"""
    )
    for row in rows:
        item = dict(row)
        item["evidence"] = [
            dict(e)
            for e in conn.execute(
                "SELECT scope,weight,evidence FROM asset_link_evidence WHERE source_id=? AND target_id=? AND relation=? ORDER BY scope",
                (row["source_id"], row["target_id"], row["relation"]),
            )
        ]
        conflicts.append(item)
    unresolved = [
        dict(row)
        for row in conn.execute(
            "SELECT a.name source,b.name target,e.relation,e.evidence FROM asset_link_evidence e JOIN assets a ON a.id=e.source_id JOIN assets b ON b.id=e.target_id WHERE e.scope='__legacy_unscoped__'"
        )
    ]
    return {
        "ambiguous_global_and_project": conflicts,
        "unresolved_legacy": unresolved,
        "note": "Human review is required; a global fact may be intentional. No links are modified.",
    }


def discover(conn):
    rows = conn.execute(
        "SELECT a.id,a.kind,a.name,a.summary,count(DISTINCT ap.project_id) projects FROM assets a JOIN asset_projects ap ON ap.asset_id=a.id WHERE a.scope='global' GROUP BY a.id HAVING count(DISTINCT ap.project_id)>1 ORDER BY projects DESC,a.name LIMIT 100"
    )
    candidates = [dict(r) for r in rows]
    for candidate in candidates:
        candidate["evidence"] = [
            dict(r)
            for r in conn.execute(
                "SELECT project_id,relation FROM asset_projects WHERE asset_id=? ORDER BY project_id",
                (candidate["id"],),
            )
        ]
    scoped = conn.execute(
        "SELECT lower(trim(name)) normalized,kind,count(DISTINCT project_id) projects FROM assets WHERE scope='project' AND kind IN ('pattern','lesson','decision','component') AND NOT EXISTS (SELECT 1 FROM memory_proposals m WHERE m.asset_id=assets.id AND m.status='superseded') GROUP BY normalized,kind HAVING count(DISTINCT project_id)>1 ORDER BY projects DESC,normalized LIMIT 100"
    )
    for group in scoped:
        evidence = [
            dict(r)
            for r in conn.execute(
                "SELECT id,name,summary,project_id FROM assets WHERE scope='project' AND lower(trim(name))=? AND kind=? AND NOT EXISTS (SELECT 1 FROM memory_proposals m WHERE m.asset_id=assets.id AND m.status='superseded') ORDER BY project_id",
                (group["normalized"], group["kind"]),
            )
        ]
        candidates.append(
            {
                "name": evidence[0]["name"],
                "kind": group["kind"],
                "projects": group["projects"],
                "summary": "Similar names occur in separate projects; review each source before drawing conclusions.",
                "evidence": evidence,
            }
        )
    return {
        "candidates": candidates,
        "note": "Name matches and shared asset associations are candidates for human review, not evidence that project-specific behavior is global.",
    }
