"""Standalone CLI runner for LazyToken E2E tests."""

from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))


def build_suite(tier: int | None = None, run_all: bool = False) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    tests_dir = Path(__file__).resolve().parent

    if tier is not None:
        pattern = f"test_tier{tier}_*.py"
        discovered = loader.discover(str(tests_dir), pattern=pattern, top_level_dir=str(ROOT_DIR))
        suite.addTests(discovered)
    elif run_all or tier is None:
        pattern = "test_tier*.py"
        discovered = loader.discover(str(tests_dir), pattern=pattern, top_level_dir=str(ROOT_DIR))
        suite.addTests(discovered)

    return suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LazyToken E2E Test Runner")
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        default=None,
        help="Run a specific test tier (1, 2, 3, or 4)",
    )
    parser.add_argument(
        "--all",
        dest="run_all",
        action="store_true",
        help="Run all E2E test tiers",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose test execution output",
    )
    parser.add_argument(
        "--json-report",
        type=str,
        default=None,
        help="Write a structured JSON test execution report to the given file path",
    )
    args = parser.parse_args(argv)

    suite = build_suite(tier=args.tier, run_all=args.run_all)
    verbosity = 2 if args.verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)

    start_time = time.perf_counter()
    result = runner.run(suite)
    duration = time.perf_counter() - start_time

    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failures - errors - skipped
    success = result.wasSuccessful()

    tier_label = f"Tier {args.tier}" if args.tier is not None else "All Tiers"
    print("\n" + "=" * 60)
    print(f"LazyToken E2E Test Suite Summary ({tier_label})")
    print("=" * 60)
    print(f"Total Tests:    {total}")
    print(f"Passed:         {passed}")
    print(f"Failed:         {failures}")
    print(f"Errors:         {errors}")
    print(f"Skipped:        {skipped}")
    print(f"Duration:       {duration:.3f}s")
    print(f"Status:         {'SUCCESS' if success else 'FAILURE'}")
    print("=" * 60)

    if args.json_report:
        report = {
            "tier": args.tier,
            "total": total,
            "passed": passed,
            "failed": failures,
            "errors": errors,
            "skipped": skipped,
            "duration_seconds": round(duration, 3),
            "success": success,
            "failures": [
                {"test": str(t), "traceback": tb} for t, tb in result.failures
            ],
            "errors": [
                {"test": str(t), "traceback": tb} for t, tb in result.errors
            ],
        }
        report_path = Path(args.json_report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report saved to: {report_path}")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
