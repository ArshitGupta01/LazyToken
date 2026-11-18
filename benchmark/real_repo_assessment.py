"""Evaluate labelled retrieval on a pinned local repository without model or network calls."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import broker
import kn
import retrieval_eval

DEFAULT_CASES = ROOT / "benchmark" / "real_repo_cases.json"
DEFAULT_OUTPUT = ROOT / "benchmark" / "results" / "real_repo_assessment.json"


def revision_of(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return result.stdout.strip()


def validate_cases(corpus: dict, root: Path) -> None:
    if corpus.get("schema") != "toksmart-real-repo-cases-v1":
        raise ValueError("unknown real-repository case schema")
    if corpus.get("revision") != revision_of(root):
        raise ValueError("repository revision differs from labelled snapshot")
    worktree_changes = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    if worktree_changes.stdout.strip():
        raise ValueError("labelled snapshot has uncommitted or untracked files")
    if (
        not isinstance(corpus.get("label_provenance"), str)
        or not corpus["label_provenance"].strip()
    ):
        raise ValueError("label provenance is required")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("at least one labelled case is required")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
            raise ValueError("each case needs an id")
        if case["id"] in seen:
            raise ValueError("duplicate case id")
        seen.add(case["id"])
        if not isinstance(case.get("task"), str) or not case["task"].strip():
            raise ValueError("each case needs a task")
        relevant = case.get("relevant")
        forbidden = case.get("forbidden", [])
        if not isinstance(relevant, list) or not isinstance(forbidden, list):
            raise ValueError("relevance labels must be lists")
        if type(case.get("expected_abstention")) is not bool or case["expected_abstention"] != (
            not bool(relevant)
        ):
            raise ValueError("expected abstention must agree with relevance labels")
        if any(not isinstance(path, str) or not path for path in relevant + forbidden):
            raise ValueError("path labels must be non-empty strings")
        if len(set(relevant)) != len(relevant) or len(set(forbidden)) != len(forbidden):
            raise ValueError("duplicate path label")
        if set(relevant) & set(forbidden):
            raise ValueError("relevant and forbidden paths overlap")
        for path in relevant + forbidden:
            candidate = Path(path)
            if (
                candidate.is_absolute()
                or ".." in candidate.parts
                or not (root / candidate).resolve().is_relative_to(root)
                or not (root / candidate).is_file()
            ):
                raise ValueError(f"label path is not a file in the snapshot: {path}")
        if not isinstance(case.get("rationale"), str) or not case["rationale"].strip():
            raise ValueError("each case needs a reviewable rationale")


def assess(root: Path, corpus: dict, k: int = 5, budget: int = 600) -> dict:
    root = root.resolve()
    validate_cases(corpus, root)
    if not 100 <= budget <= 4000:
        raise ValueError("budget must be 100..4000")
    with tempfile.TemporaryDirectory(prefix="toksmart-real-repo-") as temp:
        conn = kn.connect(Path(temp) / "index.sqlite3")
        try:
            sync = kn.sync(root, conn)
            if sync.get("error") or sync.get("error_count") or not sync.get("files"):
                raise RuntimeError(f"repository indexing incomplete: {sync}")
            predictions = []
            observations = []
            for case in corpus["cases"]:
                start = time.perf_counter_ns()
                response = broker.task_context(
                    kn, {"project": str(root), "task": case["task"], "budget": budget}, conn
                )
                elapsed_ms = round((time.perf_counter_ns() - start) / 1_000_000, 3)
                if response.get("error"):
                    raise RuntimeError(f"retrieval failed for {case['id']}: {response['error']}")
                paths = list(
                    dict.fromkeys(item["path"] for item in response["results"] if item.get("path"))
                )
                predictions.append(
                    {
                        "id": case["id"],
                        "relevant": case["relevant"],
                        "predicted": paths,
                        "abstained": response["decision"] == "abstain",
                        "estimated_tokens": response.get("estimated_tokens"),
                    }
                )
                observations.append(
                    {
                        "id": case["id"],
                        "task": case["task"],
                        "rationale": case["rationale"],
                        "expected_abstention": case["expected_abstention"],
                        "latency_ms": elapsed_ms,
                        "decision": response["decision"],
                        "predicted": paths,
                        "forbidden_returned": sorted(set(paths) & set(case.get("forbidden", []))),
                        "estimated_tokens": response.get("estimated_tokens"),
                    }
                )
            return {
                "schema": "toksmart-real-repo-assessment-v1",
                "revision": corpus["revision"],
                "label_provenance": corpus["label_provenance"],
                "review_status": corpus.get("review_status", "unreviewed"),
                "indexed_files": sync["files"],
                "budget": budget,
                "metrics": retrieval_eval.evaluate(predictions, k),
                "observations": observations,
                "limitations": [
                    "Agent-authored labels require independent human review; relevance may be incomplete.",
                    "Estimated response tokens are not provider usage or token savings.",
                    "Retrieval latency is local and does not measure coding-task success.",
                    "No baseline method, agent run, or model call is included.",
                ],
            }
        finally:
            conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, required=True, help="local checkout at the labelled commit"
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--budget", type=int, default=600)
    args = parser.parse_args()
    corpus = json.loads(args.cases.read_text(encoding="utf-8"))
    report = assess(args.repo, corpus, args.k, args.budget)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {args.output} ({report['indexed_files']} indexed files; {len(report['observations'])} cases)"
    )


if __name__ == "__main__":
    main()
