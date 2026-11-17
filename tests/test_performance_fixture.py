"""Contract checks for the offline generated performance probe."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from benchmark import performance_fixture


class PerformanceFixtureTests(unittest.TestCase):
    def test_generated_corpus_is_path_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "first"
            second = Path(temp) / "second"
            first.mkdir()
            second.mkdir()
            self.assertEqual(
                performance_fixture.generate_corpus(first, 4),
                performance_fixture.generate_corpus(second, 4),
            )

    def test_cold_warm_and_retrieval_report_validates(self):
        report = performance_fixture.measure(files=4, repeats=2)
        performance_fixture.validate_report(json.loads(json.dumps(report)))
        self.assertEqual(report["fixture"]["files"], 4)
        self.assertEqual(report["index"]["cold"]["added"], 4)
        self.assertEqual(report["index"]["warm_unchanged"]["unchanged"], 4)
        self.assertEqual(report["indexed_counts"]["files"], 4)
        self.assertEqual(len(report["retrieval"]["warm_ms"]), 2)
        self.assertNotIn("project_id", report)

        damaged = copy.deepcopy(report)
        damaged["index"]["cold"]["added"] = 3
        with self.assertRaises(ValueError):
            performance_fixture.validate_report(damaged)
        damaged = copy.deepcopy(report)
        damaged["retrieval"]["warm_p95_ms"] = -1
        with self.assertRaises(ValueError):
            performance_fixture.validate_report(damaged)
        damaged = copy.deepcopy(report)
        damaged["retrieval"]["warm_ms"] = [float("nan")]
        with self.assertRaises(ValueError):
            performance_fixture.validate_report(damaged)

    def test_bounded_parameters(self):
        with self.assertRaises(ValueError):
            performance_fixture.measure(files=0)
        with self.assertRaises(ValueError):
            performance_fixture.measure(repeats=101)
