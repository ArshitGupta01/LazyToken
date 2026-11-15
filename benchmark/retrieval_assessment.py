"""Run labelled retrieval cases against isolated copies of the benchmark fixtures."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import broker
import kn
import retrieval_eval


def assess(corpus, k=5):
    predictions = []
    observations = []
    for case in corpus["cases"]:
        fixture = case["fixture"]
        if fixture not in {"fixture_sessions", "fixture_notebook"}:
            raise ValueError("Unknown fixture")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            shutil.copytree(
                ROOT / "benchmark" / fixture,
                root,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            conn = kn.connect(Path(temp) / "index.sqlite3")
            try:
                first_sync = kn.sync(root, conn)
                if first_sync.get("error") or first_sync.get("error_count"):
                    raise RuntimeError(f"Initial sync failed: {first_sync}")
                operation = case.get("operation")
                if operation == "change":
                    (root / "auth.py").write_text(
                        "def verify_credentials(store, token):\n    return store.get(token)\n",
                        encoding="utf-8",
                    )
                elif operation == "rename":
                    (root / "auth.py").rename(root / "identity.py")
                elif operation == "remove":
                    (root / "auth.py").unlink()
                elif operation is not None:
                    raise ValueError("Unknown operation")
                sync = kn.sync(root, conn) if operation else first_sync
                if sync.get("error") or sync.get("error_count"):
                    raise RuntimeError(f"Sync failed: {sync}")
                response = broker.task_context(
                    kn, {"project": str(root), "task": case["task"], "budget": 1200}, conn
                )
                if "error" in response:
                    raise RuntimeError(f"Retrieval failed: {response['error']}")
                paths = list(
                    dict.fromkeys(item["path"] for item in response["results"] if item.get("path"))
                )
                predicted = {
                    "id": case["id"],
                    "relevant": case["relevant"],
                    "predicted": paths,
                    "abstained": response["decision"] == "abstain",
                    "estimated_tokens": response["estimated_tokens"],
                }
                predictions.append(predicted)
                observations.append(
                    {
                        "id": case["id"],
                        "decision": response["decision"],
                        "predicted": paths,
                        "forbidden_returned": sorted(set(paths) & set(case.get("forbidden", []))),
                        "sync": {key: sync[key] for key in ("added", "changed", "removed")},
                    }
                )
            finally:
                conn.close()
    return {
        "label_provenance": corpus["label_provenance"],
        "metrics": retrieval_eval.evaluate(predictions, k),
        "observations": observations,
        "predictions": predictions,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    corpus = json.loads(
        (ROOT / "benchmark" / "retrieval_cases.json").read_text(encoding="utf-8-sig")
    )
    print(json.dumps(assess(corpus, args.k), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
