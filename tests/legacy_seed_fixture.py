from __future__ import annotations
from pathlib import Path
import time
from kn import link_assets

SEED_ASSETS = [
    (
        "framework",
        "Kotlin Multiplatform",
        "Shared Kotlin modules support Android and iOS clients in this repository.",
        "kotlin,multiplatform,mobile",
        "README.md#Stack",
    ),
    (
        "framework",
        "Ktor",
        "Ktor provides the shared backend API and native HTTP client stack.",
        "kotlin,backend,http",
        "README.md#Stack",
    ),
    (
        "library",
        "SQLDelight",
        "SQLDelight supplies typed SQLite persistence and schema migrations.",
        "kotlin,sqlite,database",
        "README.md#Stack",
    ),
    (
        "framework",
        "Vite + TypeScript",
        "The browser client is a Vite and TypeScript app in web/.",
        "web,typescript,frontend",
        "web/package.json",
    ),
    (
        "platform",
        "Supabase",
        "Supabase Auth and Postgres/RLS are integrated behind the Ktor backend.",
        "auth,postgres,rls",
        "README.md#Stack",
    ),
    (
        "pattern",
        "Clean Architecture + MVVM",
        "Module responsibilities and inward dependency boundaries are documented for the mixed Kotlin and web monorepo.",
        "architecture,mvvm,monorepo",
        "ARCHITECTURE.md",
    ),
]


def seed_fixture(root: Path, conn: sqlite3.Connection) -> dict[str, int]:
    project = str(root.resolve())
    if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project,)).fetchone():
        return {"seeded": 0, "linked": 0}
    if Path(project).name.casefold() != "theekhai":
        return {
            "seeded": 0,
            "linked": 0,
            "asset_edges": 0,
            "skipped": "TheekHai starter assets are only seeded into the TheekHai repository.",
        }
    seeded = linked = 0
    for kind, name, summary, tags, source in SEED_ASSETS:
        existing = conn.execute(
            "SELECT id FROM assets WHERE kind=? AND lower(name)=lower(?) AND scope='global' ORDER BY id LIMIT 1",
            (kind, name),
        ).fetchone()
        if existing:
            asset_id = existing[0]
        else:
            asset_id = conn.execute(
                "INSERT INTO assets(kind,name,summary,tags,source,created_at) VALUES(?,?,?,?,?,?)",
                (kind, name, summary, tags, source, int(time.time())),
            ).lastrowid
            seeded += 1
        linked += conn.execute(
            "INSERT OR IGNORE INTO asset_projects VALUES(?,?,?)", (asset_id, project, "used_in")
        ).rowcount
    edge_specs = [
        (
            "Kotlin Multiplatform",
            "SQLDelight",
            "uses_persistence",
            0.95,
            "ARCHITECTURE.md: SQLDelight persistence in shared data layer",
        ),
        (
            "Kotlin Multiplatform",
            "Ktor",
            "uses_http_client",
            0.90,
            "README.md: Ktor client and Kotlin Multiplatform stack",
        ),
        (
            "Ktor",
            "Supabase",
            "integrates_with",
            0.95,
            "README.md: Supabase Auth and Postgres behind Ktor",
        ),
        (
            "Vite + TypeScript",
            "Ktor",
            "calls_api",
            0.95,
            "ARCHITECTURE.md: web client consumes shared Ktor REST API",
        ),
        (
            "Clean Architecture + MVVM",
            "Kotlin Multiplatform",
            "organizes",
            0.90,
            "ARCHITECTURE.md: Clean Architecture across KMP modules",
        ),
        (
            "Clean Architecture + MVVM",
            "Ktor",
            "organizes",
            0.90,
            "ARCHITECTURE.md: server module boundaries",
        ),
    ]
    for source, target, relation, weight, evidence in edge_specs:
        link_assets(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "weight": weight,
                "evidence": evidence,
                "project": project,
            },
            conn,
        )
    conn.commit()
    return {"seeded": seeded, "linked": linked, "asset_edges": len(edge_specs)}
