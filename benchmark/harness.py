"""Validate and compare manually captured benchmark runs. Never executes coding tasks."""

from __future__ import annotations
import argparse
import csv
import json
import math
import re
import sys
import subprocess
from pathlib import Path

ARMS = {"baseline", "lazytoken_current", "lazytoken_improved", "ponytail", "combined"}
FIELDS = (
    "task_id",
    "pair_id",
    "arm",
    "source_snapshot",
    "agent",
    "model",
    "settings",
    "usage_source",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "reasoning_in_output",
    "cached_input_tokens",
    "retrieval_tokens",
    "tool_overhead_tokens",
    "context_duplicate_tokens",
    "indexing_tokens",
    "elapsed_seconds",
    "cost",
    "retries",
    "unnecessary_file_reads",
    "success",
    "tests_passed",
    "measurement_kind",
    "notes",
)
NUMBERS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
    "retrieval_tokens",
    "tool_overhead_tokens",
    "context_duplicate_tokens",
    "indexing_tokens",
    "elapsed_seconds",
    "cost",
    "retries",
    "unnecessary_file_reads",
)
COUNTS = set(NUMBERS) - {"elapsed_seconds", "cost"}


def load_corpus(path):
    corpus = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    tasks = corpus.get("tasks") if isinstance(corpus, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Corpus must contain a non-empty tasks array.")
    ids = set()
    for t in tasks:
        if not isinstance(t, dict) or not all(
            isinstance(t.get(k), str) and t[k].strip()
            for k in ("id", "project", "category", "prompt", "acceptance")
        ):
            raise ValueError("Every task needs id, project, category, prompt, and acceptance.")
        if t["id"] in ids:
            raise ValueError("Duplicate task id: " + t["id"])
        ids.add(t["id"])
    return corpus


def validate_runs(records, corpus):
    if not isinstance(records, list):
        raise ValueError("Runs must be a JSON array.")
    tasks = {t["id"] for t in corpus["tasks"]}
    seen = set()
    result = []
    for i, run in enumerate(records, 1):
        if not isinstance(run, dict):
            raise ValueError(f"Run {i}: expected an object.")
        unknown = set(run) - set(FIELDS)
        if unknown:
            raise ValueError(f"Run {i}: unknown fields: " + ", ".join(sorted(unknown)))
        for field in ("task_id", "pair_id", "arm", "source_snapshot", "agent", "model"):
            if not isinstance(run.get(field), str) or not run[field].strip():
                raise ValueError(f"Run {i}: {field} is required.")
        if run["task_id"] not in tasks:
            raise ValueError(f"Run {i}: unknown task_id.")
        if run["arm"] not in ARMS:
            raise ValueError(f"Run {i}: unknown arm.")
        if run.get("usage_source") not in ("provider", "estimate", "unknown"):
            raise ValueError(f"Run {i}: usage_source must be provider, estimate, or unknown.")
        if not isinstance(run.get("settings"), dict) or not run["settings"]:
            raise ValueError(f"Run {i}: settings must be a non-empty object.")
        key = (run["task_id"], run["pair_id"], run["arm"])
        if key in seen:
            raise ValueError(f"Run {i}: duplicate task, pair and arm.")
        seen.add(key)
        row = {k: run.get(k) for k in FIELDS}
        row["measurement_kind"] = run.get("measurement_kind", "unknown")
        if row["measurement_kind"] == "real" and not re.fullmatch(
            r"(?:git:[0-9a-f]{40,64}|sha256:[0-9a-f]{64})", row["source_snapshot"]
        ):
            raise ValueError("Real runs need a pinned git: or sha256: snapshot identifier.")
        if row["measurement_kind"] not in ("real", "synthetic", "unknown"):
            raise ValueError("measurement_kind must be real, synthetic, or unknown.")
        for field in NUMBERS:
            value = row[field]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or (field in COUNTS and int(value) != value)
            ):
                raise ValueError(f"Run {i}: {field} must be non-negative or null.")
        for field in ("success", "tests_passed", "reasoning_in_output"):
            if row[field] is not None and not isinstance(row[field], bool):
                raise ValueError(f"Run {i}: {field} must be boolean or null.")
        for field in ("notes",):
            if row[field] is not None and not isinstance(row[field], str):
                raise ValueError(f"Run {i}: {field} must be text or null.")
        if (
            row["cached_input_tokens"] is not None
            and row["input_tokens"] is not None
            and row["cached_input_tokens"] > row["input_tokens"]
        ):
            raise ValueError(f"Run {i}: cached input cannot exceed input tokens.")
        if (
            row["reasoning_in_output"] is True
            and row["reasoning_tokens"] is not None
            and row["output_tokens"] is not None
            and row["reasoning_tokens"] > row["output_tokens"]
        ):
            raise ValueError("Reasoning included in output cannot exceed output tokens.")
        # Count separately reported reasoning only when it is not already in output.
        uncertain_reasoning = (
            row["reasoning_tokens"] is not None and row["reasoning_in_output"] is None
        )
        total = (
            row["input_tokens"] + row["output_tokens"]
            if row["input_tokens"] is not None
            and row["output_tokens"] is not None
            and not uncertain_reasoning
            else None
        )
        if (
            total is not None
            and row["reasoning_tokens"] is not None
            and row["reasoning_in_output"] is False
        ):
            total += row["reasoning_tokens"]
        row["reported_total_tokens"] = total
        row["total_with_indexing"] = (
            total + row["indexing_tokens"]
            if total is not None and row["indexing_tokens"] is not None
            else None
        )
        result.append(row)
    return result


def compare(runs):
    grouped = {}
    for run in runs:
        grouped.setdefault((run["task_id"], run["pair_id"]), {})[run["arm"]] = run
    comparisons = []
    for (task, pair), arms in sorted(grouped.items()):
        base = arms.get("baseline")
        for arm, candidate in sorted(arms.items()):
            if arm == "baseline":
                continue
            reasons = []
            if base is None:
                reasons.append("baseline missing")
            else:
                if (
                    base.get("measurement_kind", "unknown")
                    != candidate.get("measurement_kind", "unknown")
                    or base.get("measurement_kind", "unknown") == "unknown"
                ):
                    reasons.append("measurement provenance differs or is unknown")
                for field in ("source_snapshot", "agent", "model", "settings"):
                    if base[field] != candidate[field]:
                        reasons.append(field + " differs")
                if base["success"] is not True or candidate["success"] is not True:
                    reasons.append("both tasks must succeed")
                if base["tests_passed"] is not True or candidate["tests_passed"] is not True:
                    reasons.append("both test outcomes must pass")
                if base["usage_source"] != "provider" or candidate["usage_source"] != "provider":
                    reasons.append("both runs need provider-reported usage")
                if base["total_with_indexing"] is None or candidate["total_with_indexing"] is None:
                    reasons.append("provider totals or allocated indexing missing")
            saved = (
                base["total_with_indexing"] - candidate["total_with_indexing"]
                if not reasons
                else None
            )
            comparisons.append(
                {
                    "task_id": task,
                    "pair_id": pair,
                    "arm": arm,
                    "comparable": not reasons,
                    "measurement_kind": candidate.get("measurement_kind", "unknown"),
                    "eligible_for_claim": not reasons
                    and candidate.get("measurement_kind") == "real",
                    "tokens_saved": saved,
                    "reasons": reasons,
                }
            )
    return comparisons


def snapshot(root):
    """Read a clean Git revision; never checks out, resets, or runs a task."""
    root = Path(root).resolve(strict=True)

    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15
        )
        if result.returncode:
            raise ValueError("Unable to inspect Git snapshot.")
        return result.stdout.strip()

    top = Path(git("rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise ValueError("Provide the repository root.")
    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=normal"))
    return {
        "commit": commit,
        "source_snapshot": "git:" + commit if not dirty else None,
        "clean": not dirty,
        "note": "Prepare independent checkouts at this revision; dirty worktrees are not reproducible snapshots.",
    }


def csv_safe(value):
    """Keep user-supplied text from becoming a spreadsheet formula."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(Path(__file__).with_name("corpus.json")))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("corpus")
    snap = sub.add_parser("snapshot")
    snap.add_argument("root")
    for name in ("validate", "export-json", "export-csv"):
        p = sub.add_parser(name)
        p.add_argument("runs", help="JSON array of manually captured runs")
        if name.startswith("export"):
            p.add_argument("output", help="New output file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            print(json.dumps(snapshot(args.root), indent=2))
            return 0
        corpus = load_corpus(args.corpus)
        if args.command == "corpus":
            print(json.dumps(corpus, ensure_ascii=False, indent=2))
            return 0
        rows = validate_runs(json.loads(Path(args.runs).read_text(encoding="utf-8-sig")), corpus)
        comparisons = compare(rows)
        if args.command == "validate":
            print(
                json.dumps(
                    {"valid": True, "runs": len(rows), "comparisons": comparisons},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        # Exclusive creation prevents accidental replacement of user data.
        with open(args.output, "x", encoding="utf-8", newline="") as f:
            if args.command == "export-json":
                json.dump(
                    {"runs": rows, "comparisons": comparisons}, f, ensure_ascii=False, indent=2
                )
            else:
                writer = csv.DictWriter(
                    f, fieldnames=list(FIELDS) + ["reported_total_tokens", "total_with_indexing"]
                )
                writer.writeheader()
                for row in rows:
                    safe = {key: csv_safe(value) for key, value in row.items()}
                    safe["settings"] = json.dumps(
                        row["settings"], sort_keys=True, ensure_ascii=False
                    )
                    writer.writerow(safe)
        print("Exported " + args.output)
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
