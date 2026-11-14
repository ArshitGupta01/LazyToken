import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "benchmark" / "harness.py"
spec = importlib.util.spec_from_file_location("benchmark_harness", path)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class BenchmarkHarnessTests(unittest.TestCase):
    def setUp(self):
        self.corpus = harness.load_corpus(path.with_name("corpus.json"))
        self.base = {
            "task_id": "NB01",
            "pair_id": "pair-1",
            "arm": "baseline",
            "source_snapshot": "sha256:fixture",
            "agent": "agent",
            "model": "model",
            "settings": {"temperature": 0},
            "measurement_kind": "synthetic",
            "usage_source": "provider",
            "input_tokens": 100,
            "output_tokens": 30,
            "indexing_tokens": 0,
            "success": True,
            "tests_passed": True,
        }

    def test_corpus_covers_two_projects_and_multiple_task_categories(self):
        self.assertGreaterEqual(len(self.corpus["tasks"]), 20)
        self.assertEqual(
            {t["project"] for t in self.corpus["tasks"]},
            {"selected_repository", "fixture_notebook"},
        )
        self.assertTrue(
            {
                "bug_fix",
                "feature",
                "repeat_investigation",
                "continuation",
                "cross_project",
            }.issubset({t["category"] for t in self.corpus["tasks"]})
        )

    def test_provider_comparison_counts_indexing_and_reasoning_once(self):
        network = {
            **self.base,
            "arm": "lazytoken_improved",
            "input_tokens": 50,
            "output_tokens": 20,
            "reasoning_tokens": 5,
            "reasoning_in_output": False,
            "cached_input_tokens": 10,
            "indexing_tokens": 4,
        }
        result = harness.compare(harness.validate_runs([self.base, network], self.corpus))[0]
        self.assertTrue(result["comparable"])
        self.assertEqual(result["tokens_saved"], 51)

    def test_missing_data_failures_and_settings_block_comparison(self):
        candidate = {
            **self.base,
            "arm": "ponytail",
            "settings": {"temperature": 1},
            "success": False,
            "usage_source": "estimate",
            "input_tokens": None,
        }
        result = harness.compare(harness.validate_runs([self.base, candidate], self.corpus))[0]
        self.assertFalse(result["comparable"])
        self.assertIsNone(result["tokens_saved"])
        self.assertGreaterEqual(len(result["reasons"]), 3)

    def test_reasoning_inclusion_must_be_known(self):
        candidate = {**self.base, "arm": "lazytoken_current", "reasoning_tokens": 8}
        row = harness.validate_runs([candidate], self.corpus)[0]
        self.assertIsNone(row["reported_total_tokens"])

    def test_duplicate_and_invalid_runs_are_rejected(self):
        with self.assertRaises(ValueError):
            harness.validate_runs([self.base, self.base], self.corpus)
        with self.assertRaises(ValueError):
            harness.validate_runs([{**self.base, "cached_input_tokens": 101}], self.corpus)
        with self.assertRaises(ValueError):
            harness.validate_runs([{**self.base, "task_id": "missing"}], self.corpus)

    def test_exports_and_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "runs.json"
            source.write_text(json.dumps([self.base]), encoding="utf-8")
            output = Path(temp) / "export.csv"
            self.assertEqual(harness.main(["export-csv", str(source), str(output)]), 0)
            with output.open(encoding="utf-8", newline="") as file:
                self.assertEqual(next(csv.DictReader(file))["task_id"], "NB01")
            before = output.read_bytes()
            self.assertEqual(harness.main(["export-json", str(source), str(output)]), 2)
            self.assertEqual(output.read_bytes(), before)

    def test_csv_export_escapes_formula_text(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "runs.json"
            source.write_text(
                json.dumps([{**self.base, "notes": '=HYPERLINK("bad")'}]), encoding="utf-8"
            )
            output = Path(temp) / "export.csv"
            self.assertEqual(harness.main(["export-csv", str(source), str(output)]), 0)
            with output.open(encoding="utf-8", newline="") as file:
                self.assertTrue(next(csv.DictReader(file))["notes"].startswith("'="))

    def test_provenance_and_reasoning_consistency(self):
        candidate = {**self.base, "arm": "combined"}
        comparison = harness.compare(harness.validate_runs([self.base, candidate], self.corpus))[0]
        self.assertTrue(comparison["comparable"])
        self.assertFalse(comparison["eligible_for_claim"])
        unknown = {k: v for k, v in self.base.items() if k != "measurement_kind"}
        comparison = harness.compare(harness.validate_runs([unknown, candidate], self.corpus))[0]
        self.assertFalse(comparison["comparable"])
        with self.assertRaises(ValueError):
            harness.validate_runs(
                [{**self.base, "reasoning_tokens": 31, "reasoning_in_output": True}], self.corpus
            )

    def test_snapshot_refuses_dirty_reproducibility_without_mutation(self):
        import subprocess

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for args in (
                ["init"],
                ["config", "user.email", "fixture@example.invalid"],
                ["config", "user.name", "Fixture"],
            ):
                subprocess.run(["git", "-C", temp, *args], check=True, capture_output=True)
            (root / "fixture.txt").write_text("original")
            subprocess.run(["git", "-C", temp, "add", "."], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", temp, "commit", "-m", "fixture"], check=True, capture_output=True
            )
            clean = harness.snapshot(root)
            self.assertTrue(clean["clean"])
            self.assertTrue(clean["source_snapshot"].startswith("git:"))
            (root / "fixture.txt").write_text("changed")
            dirty = harness.snapshot(root)
            self.assertFalse(dirty["clean"])
            self.assertIsNone(dirty["source_snapshot"])
            self.assertEqual((root / "fixture.txt").read_text(), "changed")


if __name__ == "__main__":
    unittest.main()
