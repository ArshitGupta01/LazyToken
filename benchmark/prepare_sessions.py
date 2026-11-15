"""Prepare isolated session fixtures and optional reviewed knowledge for future trials."""

import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import kn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path, help="New empty directory for one arm")
    parser.add_argument("--follow-up", action="store_true")
    parser.add_argument("--memory", choices=("none", "current", "stale"), default="none")
    args = parser.parse_args()
    if args.memory != "none" and not args.follow_up:
        parser.error("memory variants require --follow-up")
    destination = args.destination.resolve()
    if destination.exists():
        parser.error("destination already exists; choose a new directory")
    destination.mkdir(parents=True)
    project = destination / "project"
    shutil.copytree(ROOT / "benchmark" / "fixture_sessions", project)
    if args.follow_up:
        auth = project / "auth.py"
        text = auth.read_text(encoding="utf-8")
        text = text.replace(
            "    return session\n",
            "    if session.get('expires_at') is not None and session['expires_at'] <= now:\n        return None\n    return session\n",
        )
        auth.write_text(text, encoding="utf-8")
    db = kn.connect(destination / "network.sqlite3")
    try:
        kn.sync(project, db)
        if args.memory != "none":
            project_id = str(project.resolve())
            proposal = kn.feature_call(
                "propose",
                {
                    "project": project_id,
                    "kind": "lesson",
                    "name": "Session expiry",
                    "summary": "UTC sessions expire at or before now; reuse authenticate for handlers.",
                    "task": "Reject expired sessions",
                    "evidence": "Reviewed fixture authentication and storage",
                    "paths": ["auth.py", "store.py"],
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
                with (project / "store.py").open("a", encoding="utf-8") as out:
                    out.write("\n# Fixture evidence changed after review.\n")
                kn.sync(project, db)
    finally:
        db.close()
    print(f"Prepared {project}; database: {destination / 'network.sqlite3'}")


if __name__ == "__main__":
    main()
