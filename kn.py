"""Small, local, deterministic knowledge graph and stdio MCP server."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import features

VERSION = "0.3.0"
EXTENSIONS = {".kt", ".kts", ".java", ".swift", ".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".cs", ".sql", ".html", ".css", ".scss", ".json", ".yml", ".yaml", ".toml", ".gradle", ".md"}
DENY_NAMES = {".env", ".env.local", ".env.development", ".env.production", "local.properties", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
DENY_DIRS = {".git", ".gradle", ".idea", "build", "node_modules", "dist", "backups", "runtime", "models", "test-results", "playwright-report", "xcuserdata"}
SYMBOLS = re.compile(r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|open|override|suspend|async|export|default|data|sealed|inline|fun|class|object|interface|enum|type|function|const|let|var|def|func|struct|trait|impl)\s+){1,6}(?:fun\s+|function\s+|def\s+|func\s+|class\s+|interface\s+|object\s+|enum\s+|struct\s+|trait\s+|type\s+)?([A-Za-z_$][\w$]*)\s*(?:[<(=:{]|$)")
IMPORTS = re.compile(r"^\s*(?:import\s+(?:static\s+)?|from\s+)([\w.$/]+)")


def split_words(value:str)->list[str]:
    value=re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])"," ",value)
    value=re.sub(r"(?<=[a-z0-9])(?=[A-Z])"," ",value)
    return re.findall(r"[a-z0-9]+",value.casefold())


def search_words(value:str)->set[str]:
    return set(split_words(value))


def data_root() -> Path:
    configured = os.environ.get("KN_HOME")
    if configured: return Path(configured)
    legacy = Path.home() / ".theekhai-knowledge"
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data: return legacy
    local = Path(local_app_data) / "TheekHai" / "KnowledgeNetwork"
    if (local / "network.sqlite3").is_file(): return local
    if (legacy / "network.sqlite3").is_file(): return legacy
    return local


def db_path() -> Path:
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "network.sqlite3"


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
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
      CREATE INDEX IF NOT EXISTS symbol_name_idx ON symbols(name);
      CREATE INDEX IF NOT EXISTS asset_name_idx ON assets(name);
      CREATE INDEX IF NOT EXISTS asset_link_source_idx ON asset_links(source_id);
      CREATE INDEX IF NOT EXISTS asset_link_target_idx ON asset_links(target_id);
      CREATE INDEX IF NOT EXISTS asset_link_evidence_scope_idx ON asset_link_evidence(scope);
    """)
    cols={r["name"] for r in conn.execute("PRAGMA table_info(assets)")}
    if "scope" not in cols: conn.execute("ALTER TABLE assets ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'")
    if "project_id" not in cols: conn.execute("ALTER TABLE assets ADD COLUMN project_id TEXT NOT NULL DEFAULT ''")
    # Upgrade pre-scope links by attributing them to the project that uses both endpoints.
    conn.execute("""INSERT OR IGNORE INTO asset_link_evidence(source_id,target_id,relation,scope,weight,evidence,updated_at)
      SELECT l.source_id,l.target_id,l.relation,
        COALESCE((SELECT a.project_id FROM asset_projects a JOIN asset_projects b ON b.project_id=a.project_id
          WHERE a.asset_id=l.source_id AND b.asset_id=l.target_id ORDER BY a.project_id LIMIT 1),'*'),
        l.weight,l.evidence,l.updated_at FROM asset_links l""")
    conn.commit()
    features.migrate(conn)
    return conn


def resolve_project(value:str,conn:sqlite3.Connection)->str:
    if not value or value=="*": return value
    row=conn.execute("SELECT id FROM projects WHERE id=? OR root=?",(value,value)).fetchone()
    if row: return str(row[0])
    matches=[str(r[0]) for r in conn.execute("SELECT id FROM projects") if Path(str(r[0])).name.casefold()==value.casefold()]
    return matches[0] if len(matches)==1 else ""


def safe_relative(s: str) -> bool:
    p = Path(s)
    name = p.name.lower()
    return (p.suffix.lower() in EXTENSIONS and name not in DENY_NAMES and not name.startswith(".env")
            and not any(part.lower() in DENY_DIRS for part in p.parts)
            and not p.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pem", ".key"})


def list_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, timeout=30, check=True).stdout
        paths = out.splitlines()
    except (FileNotFoundError, subprocess.SubprocessError):
        paths = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    return sorted(p for p in paths if safe_relative(p) and (root / p).is_file() and not (root / p).is_symlink())


def sync(root: Path, conn: sqlite3.Connection) -> dict[str, int]:
    root = root.resolve()
    project = str(root)
    conn.execute("INSERT INTO projects(id,root,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET root=excluded.root", (project, project, int(time.time())))
    present: set[str] = set()
    added = changed = removed = 0
    for rel in list_files(root):
        path = root / rel
        try:
            raw = path.read_bytes()
            if len(raw) > 1_000_000 or b"\x00" in raw:
                continue
            digest = hashlib.sha256(raw).hexdigest()
            present.add(rel)
            old = conn.execute("SELECT digest FROM files WHERE project_id=? AND path=?", (project, rel)).fetchone()
            if old and old[0] == digest:
                continue
            if old: changed += 1
            else: added += 1
            body = raw.decode("utf-8", errors="replace")
            conn.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)", (project, rel, digest, len(raw)))
            conn.execute("DELETE FROM symbols WHERE project_id=? AND path=?", (project, rel))
            conn.execute("DELETE FROM imports WHERE project_id=? AND source=?", (project, rel))
            for n, line in enumerate(body.splitlines(), 1):
                m = SYMBOLS.match(line)
                if m:
                    conn.execute("INSERT OR IGNORE INTO symbols VALUES(?,?,?,?)", (project, rel, m.group(1), n))
                imp = IMPORTS.match(line)
                if imp:
                    conn.execute("INSERT OR IGNORE INTO imports VALUES(?,?,?)", (project, rel, imp.group(1)))
        except OSError:
            present.discard(rel)
            continue
    for row in conn.execute("SELECT path FROM files WHERE project_id=?", (project,)).fetchall():
        if row[0] not in present:
            conn.execute("DELETE FROM files WHERE project_id=? AND path=?", (project, row[0]))
            conn.execute("DELETE FROM symbols WHERE project_id=? AND path=?", (project, row[0]))
            conn.execute("DELETE FROM imports WHERE project_id=? AND source=?", (project, row[0]))
            removed += 1
    conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (int(time.time()), project))
    conn.commit()
    return {"added": added, "changed": changed, "removed": removed, "unchanged": max(0, len(present)-added-changed), "files": len(present)}


def search(query: str, conn: sqlite3.Connection, project: str = "", limit: int = 8) -> dict[str, Any]:
    query_parts=[x for x in re.findall(r"[\w.$/-]+",query) if len(x)>1]
    terms=split_words(query_parts[0]) if len(query_parts)==1 else [x.casefold() for x in query_parts]
    terms=list(dict.fromkeys(terms))[:8]
    if not terms:
        return {"query": query, "results": []}
    like = "%" + "%".join(terms[:3]) + "%"
    requested_project=project
    project = resolve_project(project,conn) if project else ""
    if requested_project and not project:
        return {"error":"Unknown project. Run sync_project with its absolute path first."}
    rows: list[dict[str, Any]] = []
    term_sql=" OR ".join("lower(name) LIKE ? OR lower(path) LIKE ?" for _ in terms)
    params=tuple(pattern for t in terms for pattern in ("%"+t+"%","%"+t+"%"))
    where=" AND project_id=?" if project else ""
    if project: params=(*params,project)
    symbols=conn.execute(f"SELECT project_id,path,name,line FROM symbols WHERE ({term_sql}){where} LIMIT 300",params).fetchall()
    scored=[]
    for row in symbols:
        name_words=search_words(row["name"]); path_words=search_words(row["path"])
        name_hits=sum(1 for t in terms if t in name_words); path_hits=sum(1 for t in terms if t in path_words)
        score=(2*name_hits+path_hits)/len(terms)
        if score>0: scored.append((score,row))
    scored.sort(key=lambda x:(-x[0],x[1]["name"].casefold(),x[1]["path"]))
    for score,row in scored[:limit]:
        rows.append({"type":"symbol", "project":Path(row["project_id"]).name, "path":row["path"], "name":row["name"], "line":row["line"], "activation":1.0,"match_score":round(score,2)})
    if project:
        arows = conn.execute("SELECT id,kind,name,summary,tags,source FROM assets WHERE (scope='global' OR (scope='project' AND project_id=?)) AND lower(name||' '||summary||' '||tags) LIKE ? ORDER BY name LIMIT ?", (project,like,limit)).fetchall()
        edge_scope="(scope='*' OR scope=?)"; edge_args=(project,)
    else:
        arows = conn.execute("SELECT id,kind,name,summary,tags,source FROM assets WHERE scope='global' AND lower(name||' '||summary||' '||tags) LIKE ? ORDER BY name LIMIT ?", (like,limit)).fetchall()
        edge_scope="scope='*'"; edge_args=()
    activation: dict[int,float] = {int(r["id"]):1.0 for r in arows}
    frontier = dict(activation)
    # Two-hop weighted spreading activation; it is deterministic graph traversal, not ML inference.
    for _ in range(2):
        following: dict[int,float] = {}
        for node_id, score in frontier.items():
            for edge in conn.execute(f"SELECT source_id,target_id,weight FROM asset_link_evidence WHERE {edge_scope} AND (source_id=? OR target_id=?)",(*edge_args,node_id,node_id)):
                neighbor=int(edge["target_id"] if edge["source_id"]==node_id else edge["source_id"])
                visible=conn.execute("SELECT 1 FROM assets WHERE id=? AND (scope='global' OR (scope='project' AND project_id=?))",(neighbor,project)).fetchone() if project else conn.execute("SELECT 1 FROM assets WHERE id=? AND scope='global'",(neighbor,)).fetchone()
                if not visible: continue
                candidate=score*float(edge["weight"])*0.7
                if candidate>activation.get(neighbor,0) and candidate>following.get(neighbor,0): following[neighbor]=candidate
        activation.update(following)
        frontier=following
    asset_ids=sorted(activation,key=lambda k:(-activation[k],k))[:limit]
    for asset_id in asset_ids:
        r=conn.execute("SELECT id,kind,name,summary,tags,source FROM assets WHERE id=?",(asset_id,)).fetchone()
        if not r: continue
        used=[Path(x[0]).name for x in conn.execute("SELECT project_id FROM asset_projects WHERE asset_id=?",(asset_id,))]
        item={"type":"asset", "kind":r["kind"], "name":r["name"], "summary":r["summary"], "tags":r["tags"], "source":r["source"], "used_in":used, "activation":round(activation[asset_id],3)}
        memory=conn.execute("SELECT id FROM memory_proposals WHERE asset_id=?",(asset_id,)).fetchone()
        if memory:
            item.update(features.health(conn,memory["id"]))
            item["activation"]=round(item["activation"]*(.5+.5*item["confidence"]),3)
            if item["freshness"] == "stale": item["activation"]=round(item["activation"]*.3,3)
        rows.append(item)
    rows.sort(key=lambda r:(-r["activation"],-r.get("match_score",0),0 if r["type"]=="symbol" else 1,r["name"]))
    rows = rows[:limit]
    out = json.dumps({"query":query,"results":rows}, ensure_ascii=False, separators=(",",":"))
    conn.execute("INSERT INTO retrievals VALUES(?,?,?,?,?)", (int(time.time()), project, len(query), len(out), estimate(out)))
    conn.commit()
    return {"query":query,"results":rows,"estimated_tokens":estimate(out)}


def estimate(text: str) -> int:
    # Planning estimate only; real model token counts vary by tokenizer.
    return (len(text) + 3) // 4


def context(project: str, conn: sqlite3.Connection, limit: int = 30) -> dict[str, Any]:
    resolved=resolve_project(project,conn)
    row=conn.execute("SELECT id,root,updated_at FROM projects WHERE id=?",(resolved,)).fetchone() if resolved else None
    if not row:
        return {"error":"Project is not indexed. Run sync_project with its absolute path."}
    files = conn.execute("SELECT path,bytes FROM files WHERE project_id=? ORDER BY path LIMIT 10", (row["id"],)).fetchall()
    syms = conn.execute("SELECT path,name,line FROM symbols WHERE project_id=? ORDER BY path,line LIMIT 12", (row["id"],)).fetchall()
    imports = conn.execute("SELECT source,target FROM imports WHERE project_id=? ORDER BY source,target LIMIT 8", (row["id"],)).fetchall()
    result = {"project":Path(row["root"]).name,"files":[dict(r) for r in files],"symbols":[dict(r) for r in syms],"imports":[dict(r) for r in imports]}
    result["estimated_tokens"] = estimate(json.dumps(result, separators=(",",":")))
    encoded=json.dumps(result,ensure_ascii=False,separators=(",",":"))
    conn.execute("INSERT INTO retrievals VALUES(?,?,?,?,?)",(int(time.time()),row["id"],0,len(encoded),result["estimated_tokens"]))
    conn.commit()
    return result


def add_asset(args: dict[str, Any], conn: sqlite3.Connection) -> dict[str, Any]:
    kind, name, summary = (str(args.get(k, "")).strip() for k in ("kind", "name", "summary"))
    if kind not in {"library", "package", "framework", "skill", "plugin", "mcp", "component", "decision", "lesson", "pattern"}:
        return {"error":"Unsupported asset kind."}
    if not name or not summary or len(name) > 160 or len(summary) > 1200:
        return {"error":"Name and summary are required (summary max 1200 characters)."}
    project=str(args.get("project","")); project_id=resolve_project(project,conn) if project else ""
    scope=str(args.get("scope","project" if kind in {"decision","lesson"} and project else "global"))
    if scope not in {"global","project"}: return {"error":"scope must be global or project."}
    if project and not project_id: return {"error":"The linked project must already be indexed; pass its full root path."}
    if scope=="project" and not project_id: return {"error":"Project-scoped assets require an indexed project path."}
    scope_project=project_id if scope=="project" else ""
    old=conn.execute("SELECT id FROM assets WHERE kind=? AND lower(name)=lower(?) AND scope=? AND project_id=? ORDER BY id LIMIT 1",(kind,name,scope,scope_project)).fetchone()
    if old:
        conn.execute("UPDATE assets SET summary=?,tags=?,source=? WHERE id=?",(summary,str(args.get("tags",""))[:300],str(args.get("source",""))[:500],old[0])); asset_id=old[0]
    else:
        cur = conn.execute("INSERT INTO assets(kind,name,summary,tags,source,created_at,scope,project_id) VALUES(?,?,?,?,?,?,?,?)", (kind,name,summary,str(args.get("tags",""))[:300],str(args.get("source",""))[:500],int(time.time()),scope,scope_project))
        asset_id=cur.lastrowid
    linked=False
    if project:
        conn.execute("INSERT OR IGNORE INTO asset_projects VALUES(?,?,?)",(asset_id,project_id,str(args.get("relation","used_in"))[:40]))
        linked=True
    conn.commit()
    return {"saved":True,"id":asset_id,"linked_project":linked}


def link_assets(args: dict[str,Any], conn: sqlite3.Connection) -> dict[str,Any]:
    source=str(args.get("source","")).strip(); target=str(args.get("target"," ")).strip()
    relation=str(args.get("relation","related_to")).strip()[:60]
    evidence=str(args.get("evidence"," ")).strip()[:500]
    requested_scope=str(args.get("project","")).strip()
    scope=resolve_project(requested_scope,conn) if requested_scope and requested_scope!="*" else requested_scope
    try: weight=float(args.get("weight",0.8))
    except (TypeError,ValueError): return {"error":"weight must be between 0.05 and 1.0"}
    if not source or not target or source.casefold()==target.casefold() or not relation or not evidence or not 0.05<=weight<=1.0 or not requested_scope:
        return {"error":"Provide distinct assets, relation, evidence, weight 0.05-1.0, and project scope (or '*' for a global fact)."}
    if requested_scope!="*" and not scope: return {"error":"Project scope must identify an indexed project; use '*' only for a genuinely global relation."}
    if scope!="*":
        a=conn.execute("SELECT id FROM assets WHERE lower(name)=lower(?) AND (scope='global' OR (scope='project' AND project_id=?)) ORDER BY CASE scope WHEN 'project' THEN 0 ELSE 1 END LIMIT 1",(source,scope)).fetchone()
        b=conn.execute("SELECT id FROM assets WHERE lower(name)=lower(?) AND (scope='global' OR (scope='project' AND project_id=?)) ORDER BY CASE scope WHEN 'project' THEN 0 ELSE 1 END LIMIT 1",(target,scope)).fetchone()
    else:
        a=conn.execute("SELECT id FROM assets WHERE lower(name)=lower(?) AND scope='global' ORDER BY id LIMIT 1",(source,)).fetchone()
        b=conn.execute("SELECT id FROM assets WHERE lower(name)=lower(?) AND scope='global' ORDER BY id LIMIT 1",(target,)).fetchone()
    if not a or not b: return {"error":"Both assets must already exist in the selected graph scope."}
    conn.execute("INSERT OR IGNORE INTO asset_links VALUES(?,?,?,?,?,?)",(a[0],b[0],relation,weight,evidence,int(time.time())))
    conn.execute("INSERT INTO asset_link_evidence VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id,target_id,relation,scope) DO UPDATE SET weight=excluded.weight,evidence=excluded.evidence,updated_at=excluded.updated_at",(a[0],b[0],relation,scope,weight,evidence,int(time.time())))
    conn.commit()
    return {"linked":True,"source":source,"target":target,"relation":relation,"weight":weight,"scope":scope}


def get_master_graph(conn:sqlite3.Connection,limit:int=50,project:str="")->dict[str,Any]:
    project_id=resolve_project(project,conn) if project else ""
    if project and not project_id:return {"error":"Unknown project. Run sync_project with its absolute path first."}
    if project_id:
        nodes=conn.execute("SELECT id,kind,name,summary,tags,source,scope,project_id FROM assets WHERE scope='global' OR (scope='project' AND project_id=?) ORDER BY kind,name LIMIT ?",(project_id,limit)).fetchall()
    else:
        nodes=conn.execute("SELECT id,kind,name,summary,tags,source,scope,project_id FROM assets WHERE scope='global' ORDER BY kind,name LIMIT ?",(limit,)).fetchall()
    ids={int(n["id"]) for n in nodes}
    edges=[]
    if project_id:
        edge_rows=conn.execute("SELECT e.source_id,e.target_id,e.relation,e.scope,e.weight,e.evidence,a.name source_name,b.name target_name FROM asset_link_evidence e JOIN assets a ON a.id=e.source_id JOIN assets b ON b.id=e.target_id WHERE e.scope='*' OR e.scope=? ORDER BY a.name,b.name,e.relation",(project_id,))
    else:
        edge_rows=conn.execute("SELECT e.source_id,e.target_id,e.relation,e.scope,e.weight,e.evidence,a.name source_name,b.name target_name FROM asset_link_evidence e JOIN assets a ON a.id=e.source_id JOIN assets b ON b.id=e.target_id ORDER BY a.name,b.name,e.scope,e.relation")
    for edge in edge_rows:
        if edge["source_id"] in ids and edge["target_id"] in ids:
            edges.append({"source":edge["source_name"],"target":edge["target_name"],"relation":edge["relation"],"weight":edge["weight"],"scope":edge["scope"],"evidence":edge["evidence"]})
    return {"nodes":[dict(n) for n in nodes],"edges":edges,"node_count":len(nodes),"edge_count":len(edges),"note":"Weights express evidence strength for deterministic spreading activation; they are not trained neural parameters."}


SEED_ASSETS = [
    ("framework","Kotlin Multiplatform","Shared Kotlin modules support Android and iOS clients in this repository.","kotlin,multiplatform,mobile","README.md#Stack"),
    ("framework","Ktor","Ktor provides the shared backend API and native HTTP client stack.","kotlin,backend,http","README.md#Stack"),
    ("library","SQLDelight","SQLDelight supplies typed SQLite persistence and schema migrations.","kotlin,sqlite,database","README.md#Stack"),
    ("framework","Vite + TypeScript","The browser client is a Vite and TypeScript app in web/.","web,typescript,frontend","web/package.json"),
    ("platform","Supabase","Supabase Auth and Postgres/RLS are integrated behind the Ktor backend.","auth,postgres,rls","README.md#Stack"),
    ("pattern","Clean Architecture + MVVM","Module responsibilities and inward dependency boundaries are documented for the mixed Kotlin and web monorepo.","architecture,mvvm,monorepo","ARCHITECTURE.md"),
]


def seed_project(root: Path, conn: sqlite3.Connection) -> dict[str, int]:
    project=str(root.resolve())
    if not conn.execute("SELECT 1 FROM projects WHERE id=?",(project,)).fetchone(): return {"seeded":0,"linked":0}
    if Path(project).name.casefold()!="theekhai": return {"seeded":0,"linked":0,"asset_edges":0,"skipped":"TheekHai starter assets are only seeded into the TheekHai repository."}
    seeded=linked=0
    for kind,name,summary,tags,source in SEED_ASSETS:
        existing=conn.execute("SELECT id FROM assets WHERE kind=? AND lower(name)=lower(?) AND scope='global' ORDER BY id LIMIT 1",(kind,name)).fetchone()
        if existing: asset_id=existing[0]
        else:
            asset_id=conn.execute("INSERT INTO assets(kind,name,summary,tags,source,created_at) VALUES(?,?,?,?,?,?)",(kind,name,summary,tags,source,int(time.time()))).lastrowid
            seeded+=1
        linked+=conn.execute("INSERT OR IGNORE INTO asset_projects VALUES(?,?,?)",(asset_id,project,"used_in" )).rowcount
    edge_specs=[
        ("Kotlin Multiplatform","SQLDelight","uses_persistence",0.95,"ARCHITECTURE.md: SQLDelight persistence in shared data layer"),
        ("Kotlin Multiplatform","Ktor","uses_http_client",0.90,"README.md: Ktor client and Kotlin Multiplatform stack"),
        ("Ktor","Supabase","integrates_with",0.95,"README.md: Supabase Auth and Postgres behind Ktor"),
        ("Vite + TypeScript","Ktor","calls_api",0.95,"ARCHITECTURE.md: web client consumes shared Ktor REST API"),
        ("Clean Architecture + MVVM","Kotlin Multiplatform","organizes",0.90,"ARCHITECTURE.md: Clean Architecture across KMP modules"),
        ("Clean Architecture + MVVM","Ktor","organizes",0.90,"ARCHITECTURE.md: server module boundaries"),
    ]
    for source,target,relation,weight,evidence in edge_specs:
        link_assets({"source":source,"target":target,"relation":relation,"weight":weight,"evidence":evidence,"project":project},conn)
    conn.commit()
    return {"seeded":seeded,"linked":linked,"asset_edges":len(edge_specs)}


def measure_task(args: dict[str, Any], conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        baseline=max(0,int(args["baseline_tokens"])); network=max(0,int(args["network_tokens"])); indexing=max(0,int(args.get("indexing_tokens",0)))
    except (KeyError,ValueError,TypeError): return {"error":"Provide integer baseline_tokens and network_tokens."}
    task=str(args.get("task",""))[:240]
    if not task: return {"error":"task is required."}
    net=baseline-network-indexing
    conn.execute("INSERT INTO task_measurements(task,baseline_tokens,network_tokens,indexing_tokens,measured_at) VALUES(?,?,?,?,?)",(task,baseline,network,indexing,int(time.time())))
    conn.commit()
    return {"saved":True,"net_tokens_saved":net,"percent_saved":round(100*net/baseline,1) if baseline else None,"note":"Use provider-reported usage for both paths; include one-time indexing tokens only once or amortize them across measured reuses."}


TOOLS = [
 {"name":"search_knowledge","description":"Search shared assets and project-scoped notes/symbols, then spread activation over only global or selected-project edges. Deterministic; no LLM call.","inputSchema":{"type":"object","properties":{"query":{"type":"string"},"project":{"type":"string","description":"Optional absolute project path or unique indexed project name."},"limit":{"type":"integer","minimum":1,"maximum":12}},"required":["query"]}},
 {"name":"get_master_graph","description":"Show shared asset nodes and evidence-scoped relationship edges. Optional project filters links to that project and global facts; code symbols are excluded.","inputSchema":{"type":"object","properties":{"limit":{"type":"integer","minimum":1,"maximum":50},"project":{"type":"string","description":"Optional indexed project path/name."}}}},
 {"name":"link_assets","description":"Add/update an evidence-backed relationship between existing assets. Scope it to an indexed project, or use '*' only for a globally valid fact.","inputSchema":{"type":"object","properties":{"source":{"type":"string"},"target":{"type":"string"},"relation":{"type":"string"},"weight":{"type":"number","minimum":0.05,"maximum":1.0},"evidence":{"type":"string"},"project":{"type":"string","description":"Indexed project root/name or '*' for a global relationship."}},"required":["source","target","relation","weight","evidence","project"]}},
 {"name":"get_project_context","description":"Return a compact project file/symbol/import map, bounded to 30 entries; no source contents.","inputSchema":{"type":"object","properties":{"project":{"type":"string"}},"required":["project"]}},
 {"name":"sync_project","description":"Incrementally index eligible source and documentation files from one local repository; excludes secrets, build output and ignored files.","inputSchema":{"type":"object","properties":{"root":{"type":"string"}},"required":["root"]}},
 {"name":"record_asset","description":"Store a reusable global asset or a project-scoped decision/lesson; optionally associate an indexed project.","inputSchema":{"type":"object","properties":{"kind":{"type":"string"},"name":{"type":"string"},"summary":{"type":"string"},"tags":{"type":"string"},"source":{"type":"string"},"scope":{"type":"string","enum":["global","project"]},"project":{"type":"string","description":"Optional indexed project name or absolute path; required for project scope."},"relation":{"type":"string"}},"required":["kind","name","summary"]}},
 {"name":"token_report","description":"Report approximate retrieval token totals and indexed project sizes; estimate is characters divided by four, not provider billing data.","inputSchema":{"type":"object","properties":{}}},
 {"name":"record_task_measurement","description":"Record actual provider-reported token totals for a baseline task and a task using this network; optionally allocate indexing tokens.","inputSchema":{"type":"object","properties":{"task":{"type":"string"},"baseline_tokens":{"type":"integer"},"network_tokens":{"type":"integer"},"indexing_tokens":{"type":"integer"}},"required":["task","baseline_tokens","network_tokens"]}},
]

TOOLS.append({"name":"lazytoken", "description":"Local metadata search, estimated-budget context, benchmark records, memory proposals/review, freshness, provisional dependencies, and pattern candidates. Actions: search, context, benchmark_record, benchmark_list, propose, proposals, review, dependencies, discover.", "inputSchema":{"type":"object","properties":{"action":{"type":"string","enum":["search","context","benchmark_record","benchmark_list","propose","proposals","review","dependencies","discover"]},"payload":{"type":"object","description":"Action arguments. Search: project, query, limit. Context: project, query, budget, exclude_paths. Benchmark: task, variant and optional measured fields. Proposal: project, kind, name, summary, task, evidence, paths, commit_ref. Review: project, id, action, optional edits."}},"required":["action","payload"]}})
TOOLS[-1]["inputSchema"]["properties"]["payload"]["properties"]={
    "project":{"type":"string"}, "query":{"type":"string"}, "limit":{"type":"integer"},
    "budget":{"type":"integer"}, "exclude_paths":{"type":"array","items":{"type":"string"}}, "exclude_asset_ids":{"type":"array","items":{"type":"integer"}},
    "task":{"type":"string"}, "variant":{"type":"string","enum":["baseline","network"]},
    "model":{"type":"string"}, "settings":{"anyOf":[{"type":"string"},{"type":"object"}],"description":"Model and agent settings as text or an object."},
    "input_tokens":{"type":"integer"}, "output_tokens":{"type":"integer"}, "indexing_tokens":{"type":"integer"},
    "elapsed_seconds":{"type":"number"}, "successful":{"type":"boolean"}, "unnecessary_file_reads":{"type":"integer"},
    "kind":{"type":"string","enum":["lesson","decision","pattern","component"]}, "name":{"type":"string"},
    "summary":{"type":"string"}, "evidence":{"type":"string"}, "paths":{"type":"array","items":{"type":"string"}},
    "commit_ref":{"type":"string"}, "status":{"type":"string","enum":["all","pending","approved","rejected"]},
    "id":{"type":"integer"}, "action":{"type":"string","enum":["edit","approve","reject","revalidate"]},
}

for tool in TOOLS:
    if tool["name"] in {"search_knowledge", "get_project_context"}:
        tool["inputSchema"]["properties"]["budget"]={"type":"integer","minimum":100,"maximum":16000,"description":"Optional estimated character-based token budget. Requires a project; returns a bounded metadata map and ranked results."}

def feature_call(action: str, args: dict[str, Any], conn: sqlite3.Connection) -> Any:
    if action == "search": return features.ranked_search(sys.modules[__name__],args,conn)
    if action == "context": return features.bounded_context(sys.modules[__name__],args,conn)
    if action == "benchmark_record": return features.benchmark(args,conn)
    if action == "benchmark_list": return features.benchmark_list(conn)
    if action == "propose": return features.propose(sys.modules[__name__],args,conn)
    if action == "proposals": return features.proposal_list(sys.modules[__name__],args,conn)
    if action == "review": return features.review(sys.modules[__name__],args,conn)
    if action == "dependencies": return features.dependencies(sys.modules[__name__],args,conn)
    if action == "discover": return features.discover(conn)
    return {"error":"Unknown LazyToken action."}


def call(name: str, args: dict[str, Any], conn: sqlite3.Connection) -> Any:
    if name == "lazytoken":
        payload=args.get("payload",{})
        return feature_call(str(args.get("action","")),payload,conn) if isinstance(payload,dict) else {"error":"payload must be an object."}
    if name == "search_knowledge":
        if "budget" in args: return features.bounded_context(sys.modules[__name__],args,conn)
        return search(str(args.get("query",""))[:1000],conn,str(args.get("project","")),max(1,min(12,int(args.get("limit",8)))))
    if name == "get_master_graph": return get_master_graph(conn,max(1,min(50,int(args.get("limit",50)))),str(args.get("project","")))
    if name == "link_assets": return link_assets(args,conn)
    if name == "get_project_context":
        if "budget" in args: return features.bounded_context(sys.modules[__name__],args,conn)
        return context(str(args["project"]),conn)
    if name == "sync_project":
        root=Path(str(args["root"]))
        if not root.is_absolute() or not root.is_dir(): return {"error":"root must be an existing absolute directory."}
        return sync(root,conn)
    if name == "record_asset": return add_asset(args,conn)
    if name == "seed_project": return seed_project(Path(str(args["root"])),conn)
    if name == "record_task_measurement": return measure_task(args,conn)
    if name == "token_report":
        totals=conn.execute("SELECT count(*),coalesce(sum(estimated_tokens),0),coalesce(sum(query_chars),0) FROM retrievals").fetchone()
        projects=[dict(r) for r in conn.execute("SELECT p.root,count(f.path) files,coalesce(sum(f.bytes),0) indexed_bytes FROM projects p LEFT JOIN files f ON f.project_id=p.id GROUP BY p.id ORDER BY p.root")]
        measured=conn.execute("SELECT count(*),coalesce(sum(baseline_tokens),0),coalesce(sum(network_tokens),0),coalesce(sum(indexing_tokens),0) FROM task_measurements").fetchone()
        return {"retrieval_calls":totals[0],"retrieved_estimated_tokens":totals[1],"query_characters":totals[2],"measured_tasks":measured[0],"baseline_tokens":measured[1],"network_tokens":measured[2],"allocated_indexing_tokens":measured[3],"measured_net_saved":measured[1]-measured[2]-measured[3],"projects":projects,"caveat":"Retrieval estimate is approximate text size, not model tokenizer or API billing. Savings use provider-reported counts entered per task."}
    return {"error":"Unknown tool."}


def rpc_server(conn: sqlite3.Connection) -> None:
    for raw in sys.stdin:
        try:
            req=json.loads(raw); method=req.get("method"); rid=req.get("id")
            if method == "notifications/initialized" or method == "notifications/cancelled": continue
            if method == "initialize": result={"protocolVersion":req.get("params",{}).get("protocolVersion","2024-11-05"),"capabilities":{"tools":{}},"serverInfo":{"name":"lazytoken-knowledge-network","version":VERSION}}
            elif method == "ping": result={}
            elif method == "tools/list": result={"tools":TOOLS}
            elif method == "tools/call":
                p=req.get("params",{}); value=call(p.get("name",""),p.get("arguments",{}),conn)
                result={"content":[{"type":"text","text":json.dumps(value,ensure_ascii=False,separators=(",",":"))}],"isError":bool(isinstance(value,dict) and "error" in value)}
            else:
                if rid is None: continue
                reply={"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"Method not found"}}
                sys.stdout.write(json.dumps(reply,separators=(",",":"))+"\n");sys.stdout.flush();continue
            if rid is not None:
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":result},separators=(",",":"))+"\n");sys.stdout.flush()
        except Exception as e:
            # Never log inputs or source content to stderr; keep MCP stdout protocol-clean.
            if 'rid' in locals() and rid is not None:
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"error":{"code":-32603,"message":type(e).__name__}},separators=(",",":"))+"\n");sys.stdout.flush()


def main() -> None:
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="cmd",required=True)
    ix=sub.add_parser("sync"); ix.add_argument("root")
    sd=sub.add_parser("seed"); sd.add_argument("root")
    sub.add_parser("mcp")
    sr=sub.add_parser("search"); sr.add_argument("query"); sr.add_argument("--project",default="")
    lt=sub.add_parser("lazytoken",help="Run a LazyToken action with JSON arguments"); lt.add_argument("action",choices=["search","context","benchmark_record","benchmark_list","propose","proposals","review","dependencies","discover"]); lt.add_argument("--json",default="{}",help="JSON object, or @path to a UTF-8 JSON file")
    sub.add_parser("report")
    a=parser.parse_args(); db=connect()
    if a.cmd=="mcp": rpc_server(db)
    elif a.cmd=="sync": print(json.dumps(sync(Path(a.root),db),indent=2))
    elif a.cmd=="seed": print(json.dumps(seed_project(Path(a.root),db),indent=2))
    elif a.cmd=="search": print(json.dumps(search(a.query,db,a.project),indent=2,ensure_ascii=False))
    elif a.cmd=="lazytoken":
        raw=Path(a.json[1:]).read_text(encoding="utf-8-sig") if a.json.startswith("@") else a.json
        args=json.loads(raw)
        if not isinstance(args,dict): parser.error("--json must contain an object")
        print(json.dumps(feature_call(a.action,args,db),indent=2,ensure_ascii=False))
    else: print(json.dumps(call("token_report",{},db),indent=2))

if __name__=="__main__": main()
