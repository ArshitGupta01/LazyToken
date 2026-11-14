"""Derive project/framework links from eligible manifest and import metadata."""

import configparser
import hashlib
import json
from pathlib import Path
import re
import time
import tomllib

DEPENDENCIES = {
    "three": ("library", "Three.js"),
    "gsap": ("library", "GSAP"),
    "framer-motion": ("library", "Motion"),
    "motion": ("library", "Motion"),
    "@react-three/fiber": ("framework", "React Three Fiber"),
    "@react-three/drei": ("library", "Drei"),
    "@tanstack/react-query": ("library", "TanStack Query"),
    "zod": ("library", "Zod"),
    "prisma": ("library", "Prisma"),
    "uvicorn": ("library", "Uvicorn"),
    "langchain": ("framework", "LangChain"),
    "langgraph": ("framework", "LangGraph"),
    "react": ("framework", "React"),
    "react-native": ("framework", "React Native"),
    "next": ("framework", "Next.js"),
    "vue": ("framework", "Vue"),
    "nuxt": ("framework", "Nuxt"),
    "svelte": ("framework", "Svelte"),
    "@sveltejs/kit": ("framework", "SvelteKit"),
    "@angular/core": ("framework", "Angular"),
    "astro": ("framework", "Astro"),
    "vite": ("framework", "Vite"),
    "express": ("framework", "Express"),
    "fastify": ("framework", "Fastify"),
    "@nestjs/core": ("framework", "NestJS"),
    "electron": ("framework", "Electron"),
    "tailwindcss": ("framework", "Tailwind CSS"),
    "@supabase/supabase-js": ("library", "Supabase JS"),
    "django": ("framework", "Django"),
    "flask": ("framework", "Flask"),
    "fastapi": ("framework", "FastAPI"),
    "streamlit": ("framework", "Streamlit"),
    "gradio": ("framework", "Gradio"),
    "sqlalchemy": ("library", "SQLAlchemy"),
    "pydantic": ("library", "Pydantic"),
    "torch": ("framework", "PyTorch"),
    "tensorflow": ("framework", "TensorFlow"),
    "transformers": ("library", "Transformers"),
    "tokenizers": ("library", "Tokenizers"),
    "sqlite3": ("library", "SQLite"),
    "pytest": ("library", "pytest"),
    "playwright": ("library", "Playwright"),
}


def declarations(name, text):
    dependencies = []
    extra = []
    if name == "package.json":
        data = json.loads(text)
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            if isinstance(data.get(section), dict):
                dependencies.extend(data[section])
    elif name == "pyproject.toml":
        data = tomllib.loads(text)
        project = data.get("project", {})
        dependencies.extend(project.get("dependencies", []))
        for group in project.get("optional-dependencies", {}).values():
            dependencies.extend(group)
        dependencies.extend(data.get("tool", {}).get("poetry", {}).get("dependencies", {}))
    elif name.startswith("requirements") and name.endswith(".txt"):
        dependencies.extend(
            line
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "-"))
        )
    elif name == "setup.cfg":
        config = configparser.ConfigParser()
        config.read_string(text)
        dependencies.extend(config.get("options", "install_requires", fallback="").splitlines())
    elif name.endswith((".gradle", ".gradle.kts")) or name == "libs.versions.toml":
        plain = re.sub(r"/\*[\s\S]*?\*/|(?m:^\s*//[^\n]*)", "", text)
        for pattern, label in (
            (r"io[.:]ktor", "Ktor"),
            (r"org\.jetbrains\.compose", "Compose Multiplatform"),
            (r"com\.android\.(?:application|library)", "Android"),
            (
                r'kotlin\(["\']multiplatform|org\.jetbrains\.kotlin\.multiplatform',
                "Kotlin Multiplatform",
            ),
        ):
            if re.search(pattern, plain):
                extra.append(("framework", label))
    elif name == "pubspec.yaml" and re.search(r"(?m)^\s*flutter\s*:", text):
        extra.append(("framework", "Flutter"))
    results = set(extra)
    for value in dependencies:
        if not isinstance(value, str):
            continue
        match = re.match(r"\s*([A-Za-z0-9_@./-]+)", value)
        key = match.group(1).lower().replace("_", "-") if match else ""
        if key in DEPENDENCIES:
            results.add(DEPENDENCIES[key])
    return results


def update(connection, project):
    root = Path(project)
    found = {}
    incomplete = False
    for row in connection.execute(
        "SELECT path,digest FROM files WHERE project_id=?", (project,)
    ).fetchall():
        relative = row["path"]
        name = Path(relative).name
        if not (
            name
            in {"package.json", "pyproject.toml", "setup.cfg", "pubspec.yaml", "libs.versions.toml"}
            or name.startswith("requirements")
            or name.endswith((".gradle", ".gradle.kts"))
        ):
            continue
        try:
            from onboarding import regular_path

            regular_path(root / relative)
            if not (root / relative).resolve().is_relative_to(root.resolve()):
                raise ValueError("Outside project")
            with (root / relative).open("rb") as source:
                raw = source.read(262145)
            if len(raw) > 262144 or hashlib.sha256(raw).hexdigest() != row["digest"]:
                incomplete = True
                continue
            for kind, label in declarations(name, raw.decode("utf-8-sig")):
                found.setdefault((kind, label), []).append(relative)
        except (OSError, ValueError, TypeError, AttributeError, configparser.Error):
            incomplete = True
            continue
    for row in connection.execute(
        "SELECT source,target FROM imports WHERE project_id=?", (project,)
    ):
        key = row["target"].split(".")[0].lower()
        if key in DEPENDENCIES:
            found.setdefault(DEPENDENCIES[key], []).append(row["source"])
    anchor = connection.execute(
        "SELECT id FROM assets WHERE kind='project' AND scope='project' AND project_id=?",
        (project,),
    ).fetchone()
    if not found and not anchor:
        return
    if anchor:
        anchor = anchor[0]
    else:
        anchor = connection.execute(
            "INSERT INTO assets(kind,name,summary,tags,source,created_at,scope,project_id) VALUES('project',?,?,?, ?,?,'project',?)",
            (
                root.name,
                "Indexed local codebase; framework declarations are linked with source evidence.",
                "codebase",
                project,
                int(time.time()),
                project,
            ),
        ).lastrowid
    targets = []
    for (kind, label), paths in sorted(found.items()):
        row = connection.execute(
            "SELECT id FROM assets WHERE kind=? AND lower(name)=lower(?) AND scope='global' ORDER BY id LIMIT 1",
            (kind, label),
        ).fetchone()
        target = (
            row[0]
            if row
            else connection.execute(
                "INSERT INTO assets(kind,name,summary,tags,source,created_at,scope,project_id) VALUES(?,?,?,?,?,?,'global','')",
                (
                    kind,
                    label,
                    label
                    + " detected in declared dependency or source-import metadata; usage is project-scoped.",
                    "detected",
                    "See project-scoped evidence",
                    int(time.time()),
                ),
            ).lastrowid
        )
        evidence = "Declared/imported in " + ", ".join(sorted(set(paths))[:8])
        connection.execute(
            "INSERT INTO asset_link_evidence VALUES(?,?,'declares_framework',?,1.0,?,?) ON CONFLICT(source_id,target_id,relation,scope) DO UPDATE SET evidence=excluded.evidence,updated_at=excluded.updated_at WHERE evidence<>excluded.evidence",
            (anchor, target, project, evidence[:500], int(time.time())),
        )
        connection.execute(
            "INSERT OR IGNORE INTO asset_projects VALUES(?,?,'manifest_declared')",
            (target, project),
        )
        targets.append(target)
    previous = connection.execute(
        "SELECT target_id,evidence FROM asset_link_evidence WHERE source_id=? AND scope=? AND relation='declares_framework'",
        (anchor, project),
    ).fetchall()
    for row in previous:
        if incomplete and row[0] not in targets:
            evidence = row["evidence"]
            if not evidence.startswith("Needs recheck:"):
                connection.execute(
                    "UPDATE asset_link_evidence SET evidence=? WHERE source_id=? AND target_id=? AND scope=? AND relation='declares_framework'",
                    (
                        "Needs recheck: manifest unavailable or invalid. " + evidence,
                        anchor,
                        row[0],
                        project,
                    ),
                )
            continue
        if row[0] not in targets:
            connection.execute(
                "DELETE FROM asset_link_evidence WHERE source_id=? AND target_id=? AND scope=? AND relation='declares_framework'",
                (anchor, row[0], project),
            )
            connection.execute(
                "DELETE FROM asset_projects WHERE asset_id=? AND project_id=? AND relation='manifest_declared'",
                (row[0], project),
            )
