"""Offline, generated-corpus performance probe; never measures model tokens or quality."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import broker
import kn

SCHEMA = "toksmart-performance-v1"
DEFAULT_OUTPUT = ROOT / "benchmark" / "results" / "performance_report.json"


def generate_corpus(root: Path, count: int) -> dict:
    """Make identical source bytes regardless of the temporary directory name."""
    digest = hashlib.sha256()
    total_bytes = 0
    for index in range(count):
        name = f"module_{index:04d}.py"
        previous = f"from module_{index - 1:04d} import Service{index - 1:04d}\n" if index else ""
        content = (
            f'"""Generated fixture module {index:04d}."""\n'
            + previous
            + f"class Service{index:04d}:\n"
            + f"    def handle_{index:04d}(self, value: int) -> int:\n"
            + f"        return value + {index}\n"
        ).encode("utf-8")
        (root / name).write_bytes(content)
        digest.update(name.encode("utf-8") + b"\0" + content + b"\0")
        total_bytes += len(content)
    return {
        "kind": "generated-python-v1",
        "files": count,
        "source_bytes": total_bytes,
        "sha256": digest.hexdigest(),
    }


def timed(operation):
    tracemalloc.start()
    start = time.perf_counter_ns()
    try:
        result = operation()
    finally:
        elapsed_ns = time.perf_counter_ns() - start
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    return result, round(elapsed_ns / 1_000_000, 3), peak_bytes


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    rank = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[rank]


def measure(files: int = 200, repeats: int = 5) -> dict:
    if not 1 <= files <= 1000 or not 1 <= repeats <= 100:
        raise ValueError("files must be 1..1000 and repeats must be 1..100")
    with tempfile.TemporaryDirectory(prefix="toksmart-performance-") as temp:
        root = Path(temp)
        project = root / "project"
        project.mkdir()
        fixture = generate_corpus(project, files)
        conn = kn.connect(root / "network.sqlite3")
        try:
            cold, cold_ms, cold_peak = timed(lambda: kn.sync(project, conn))
            warm, warm_ms, warm_peak = timed(lambda: kn.sync(project, conn))
            for label, result in (("cold", cold), ("warm", warm)):
                if result.get("error") or result.get("error_count") or result.get("skipped_count"):
                    raise RuntimeError(f"{label} sync was incomplete: {result}")
            if cold["added"] != files or warm["unchanged"] != files:
                raise RuntimeError("fixture did not exercise cold and unchanged warm indexing")
            indexed_counts = {
                table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("files", "symbols", "imports")
            }
            if indexed_counts["files"] != files:
                raise RuntimeError("indexed file count differs from fixture")
            task = "Find handle_0000"

            def retrieve():
                return broker.task_context(
                    kn, {"project": str(project), "task": task, "budget": 600}, conn
                )

            first, first_ms, first_peak = timed(retrieve)
            if first.get("error") or first["decision"] != "retrieve" or not first["results"]:
                raise RuntimeError("fixture retrieval did not return indexed code")
            warm_samples = []
            for _ in range(repeats):
                result, elapsed_ms, _ = timed(retrieve)
                if result.get("error") or result["decision"] != "retrieve":
                    raise RuntimeError("warm retrieval failed")
                warm_samples.append(elapsed_ms)
            report = {
                "schema": SCHEMA,
                "environment": {
                    "system": platform.system(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                    "toksmart_version": kn.VERSION,
                },
                "fixture": fixture,
                "indexed_counts": indexed_counts,
                "index": {
                    "cold": {
                        "elapsed_ms": cold_ms,
                        "python_peak_bytes": cold_peak,
                        "added": cold["added"],
                    },
                    "warm_unchanged": {
                        "elapsed_ms": warm_ms,
                        "python_peak_bytes": warm_peak,
                        "unchanged": warm["unchanged"],
                    },
                },
                "retrieval": {
                    "operation": "broker.task_context",
                    "query": task,
                    "budget": 600,
                    "first_ms": first_ms,
                    "first_python_peak_bytes": first_peak,
                    "warm_ms": warm_samples,
                    "warm_median_ms": round(statistics.median(warm_samples), 3),
                    "warm_p95_ms": percentile(warm_samples, 0.95),
                    "result_count": len(first["results"]),
                },
                "limitations": [
                    "Generated Python fixture is not a representative user repository.",
                    "tracemalloc measures Python allocations, not SQLite/native or total process RSS.",
                    "Measurements include tracemalloc overhead and local machine variability.",
                    "Retrieval latency and result count do not measure correctness or token savings.",
                    "Warm retrieval repeats the same task and may use an in-process cache.",
                ],
            }
            validate_report(report)
            return report
        finally:
            conn.close()


def validate_report(report: dict) -> None:
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ValueError("unknown performance report schema")
    fixture = report.get("fixture", {})
    if (
        fixture.get("kind") != "generated-python-v1"
        or not isinstance(fixture.get("sha256"), str)
        or len(fixture["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in fixture["sha256"])
    ):
        raise ValueError("invalid fixture identity")
    for field in ("files", "source_bytes"):
        value = fixture.get(field)
        if type(value) is not int or value <= 0:
            raise ValueError(f"invalid fixture {field}")
    counts = report.get("indexed_counts", {})
    for field in ("files", "symbols", "imports"):
        value = counts.get(field)
        if type(value) is not int or value < 0:
            raise ValueError(f"invalid indexed {field} count")
    if counts["files"] != fixture["files"]:
        raise ValueError("indexed file count differs from fixture")
    index = report.get("index", {})
    for phase, count_field in (("cold", "added"), ("warm_unchanged", "unchanged")):
        item = index.get(phase, {})
        if item.get(count_field) != fixture["files"]:
            raise ValueError(f"invalid {phase} count")
        for field in ("elapsed_ms", "python_peak_bytes"):
            value = item.get(field)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {phase} {field}")
    retrieval = report.get("retrieval", {})
    samples = retrieval.get("warm_ms")
    if (
        retrieval.get("operation") != "broker.task_context"
        or not isinstance(samples, list)
        or not samples
    ):
        raise ValueError("invalid retrieval operation or samples")
    for value in [
        retrieval.get("first_ms"),
        retrieval.get("first_python_peak_bytes"),
        *samples,
        retrieval.get("warm_median_ms"),
        retrieval.get("warm_p95_ms"),
    ]:
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid retrieval timing or memory")
    if type(retrieval.get("result_count")) is not int or retrieval["result_count"] <= 0:
        raise ValueError("invalid retrieval result count")
    if retrieval.get("query") != "Find handle_0000" or retrieval.get("budget") != 600:
        raise ValueError("invalid retrieval task")
    if abs(retrieval["warm_median_ms"] - statistics.median(samples)) > 0.001 or retrieval[
        "warm_p95_ms"
    ] != percentile(samples, 0.95):
        raise ValueError("retrieval summary differs from samples")
    if not isinstance(report.get("environment"), dict) or not isinstance(
        report.get("limitations"), list
    ):
        raise ValueError("missing environment or limitations")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--validate", type=Path, help="Validate an existing JSON report instead of measuring"
    )
    args = parser.parse_args()
    if args.validate:
        validate_report(json.loads(args.validate.read_text(encoding="utf-8")))
        print("Performance report valid")
        return
    report = measure(args.files, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output} ({report['fixture']['files']} files; generated fixture)")


if __name__ == "__main__":
    main()
