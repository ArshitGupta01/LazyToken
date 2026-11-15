"""Prepare isolated notebook fixtures and optional reviewed knowledge for benchmark trials."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import kn


def main():
    parser = argparse.ArgumentParser(
        description="Prepare isolated notebook fixture with optional reviewed lesson."
    )
    parser.add_argument("destination", type=Path, help="New empty directory for one arm")
    parser.add_argument("--memory", choices=("none", "current", "stale"), default="none")
    args = parser.parse_args()

    destination = args.destination.resolve()
    if destination.exists():
        parser.error("destination already exists; choose a new directory")
    destination.mkdir(parents=True)
    project = destination / "project"
    shutil.copytree(ROOT / "benchmark" / "fixture_notebook", project)
    if shutil.which("git"):
        subprocess.run(["git", "init", "--quiet", str(project)], check=True)

    db = kn.connect(destination / "network.sqlite3")
    try:
        indexed = kn.sync(project, db)
        if indexed.get("error") or indexed.get("error_count") or not indexed.get("files"):
            raise RuntimeError(f"Fixture indexing failed: {indexed}")
        if args.memory != "none":
            project_id = str(project.resolve())
            proposal = kn.feature_call(
                "propose",
                {
                    "project": project_id,
                    "kind": "lesson",
                    "name": "Notebook tag filtering",
                    "summary": (
                        "Notebook.find(term, tag=None) matches term as case-insensitive substring "
                        "in title/body; tag filtering matches tag exactly (case-insensitive) in tags."
                    ),
                    "task": "Add case-insensitive tag filtering to the notebook",
                    "evidence": "Reviewed notebook.py and test_notebook.py",
                    "paths": ["notebook.py", "test_notebook.py"],
                },
                db,
            )
            if "error" in proposal:
                raise RuntimeError(proposal["error"])
            reviewed = kn.feature_call(
                "review",
                {
                    "project": project_id,
                    "id": proposal["id"],
                    "action": "approve",
                    "verified": True,
                },
                db,
            )
            if not reviewed.get("saved"):
                raise RuntimeError(str(reviewed))
            if args.memory == "stale":
                with (project / "notebook.py").open("a", encoding="utf-8") as out:
                    out.write("\n# Fixture evidence changed after review.\n")
                kn.sync(project, db)
    finally:
        db.close()
    print(f"Prepared {project}; database: {destination / 'network.sqlite3'}")


if __name__ == "__main__":
    main()
