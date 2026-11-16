"""Offline contract tests. Provider responses below are fixtures, not benchmark evidence."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark import prompt_modes as pm


class PromptModeTests(unittest.TestCase):
    def setUp(self):
        self.version, self.prompts = pm.load_prompts()
        self.case = pm.default_cases()[0]

    def response(self, text="Fixture response", usage=True, finish="stop"):
        result = {
            "model": "fixture-model",
            "choices": [{"message": {"content": text}, "finish_reason": finish}],
        }
        if usage:
            result["usage"] = {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 10},
            }
        return result

    def run_job(self, mode="lite", case=None, call=None, **extra):
        return pm.execute(
            {"case": case or self.case, "mode": mode, "trial": 1},
            experiment="fixture-experiment",
            model="fixture-model",
            settings={"temperature": 0.2},
            key="fixture-not-a-secret",
            version=self.version,
            prompts=self.prompts,
            call=call or (lambda *args: self.response()),
            **extra,
        )

    def test_corpus_has_three_cases_in_each_of_twelve_categories(self):
        cases = pm.validate_cases(pm.default_cases())
        categories = {case["category"] for case in cases}
        self.assertEqual(len(cases), 36)
        self.assertEqual(len(categories), 12)
        self.assertTrue(all(sum(c["category"] == cat for c in cases) == 3 for cat in categories))
        jobs = pm.plan(cases)
        self.assertEqual(len(jobs), 324)
        self.assertEqual(sum(1 + len(j["case"]["followups"]) for j in jobs), 342)

    def test_randomized_plan_is_reproducible_and_balanced(self):
        jobs = pm.plan([self.case], trials=3, seed=9)
        self.assertEqual(jobs, pm.plan([self.case], trials=3, seed=9))
        self.assertNotEqual(jobs, pm.plan([self.case], trials=3, seed=11))
        for trial in range(1, 4):
            self.assertEqual(
                {j["mode"] for j in jobs if j["trial"] == trial}, {"normal", "lite", "pro"}
            )
        self.assertEqual(len(pm.plan([self.case], include_coding=True)), 12)

    def test_exact_mobile_prompt_and_same_task_settings_in_all_modes(self):
        requests = []

        def call(model, messages, settings, key):
            requests.append((model, list(messages), settings))
            return self.response()

        for mode in ("normal", "lite", "pro", "coding"):
            row = self.run_job(mode=mode, call=call)
            self.assertEqual(row["instruction_prompt"], self.prompts[mode])
            self.assertEqual(row["total_tokens"], 120)
            self.assertEqual(row["usage_source"], "provider")
        self.assertEqual(len(requests[0][1]), 1)
        self.assertEqual(requests[1][1][0], {"role": "user", "content": self.prompts["lite"]})
        self.assertTrue(
            all(request[-2][-1]["content"] == self.case["task"] for request in requests)
        )
        self.assertTrue(
            all(
                request[0] == "fixture-model" and request[2] == {"temperature": 0.2}
                for request in requests
            )
        )

    def test_multi_turn_counts_repeated_history_and_cached_pricing(self):
        case = {**self.case, "followups": ["Yes, improve it."]}
        messages_seen = []

        def call(model, messages, settings, key):
            messages_seen.append(list(messages))
            return self.response()

        row = self.run_job(case=case, call=call, rates={"input": 2, "cached_input": 1, "output": 4})
        self.assertEqual(row["total_tokens"], 240)
        self.assertEqual(len(row["turns"]), 2)
        self.assertEqual(messages_seen[1][-2]["role"], "assistant")
        self.assertEqual(messages_seen[1][-1]["content"], "Yes, improve it.")
        self.assertAlmostEqual(row["cost"], (180 * 2 + 20 + 40 * 4) / 1_000_000)

    def test_missing_usage_is_unknown_and_truncation_is_not_success(self):
        row = self.run_job(call=lambda *args: self.response(usage=False))
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["usage_source"], "unknown")
        self.assertIsNone(row["total_tokens"])
        truncated = self.run_job(call=lambda *args: self.response(finish="length"))
        self.assertEqual(truncated["status"], "failed")
        self.assertIn("truncated", truncated["error"])

    def test_failure_preserves_partial_turn_evidence(self):
        calls = []

        def call(*args):
            calls.append(1)
            if len(calls) > 1:
                raise RuntimeError("Fixture network failure")
            return self.response()

        row = self.run_job(case={**self.case, "followups": ["Next"]}, call=call)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(len(row["turns"]), 1)
        self.assertIsNone(row["cost"])

    def test_persistence_exclusive_export_and_manual_score_history(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "test.sqlite3"
            row = self.run_job()
            conn = pm.connect(database)
            pm.save(conn, row)
            scores = {key: 8 for key in pm.CRITERIA}
            pm.evaluate(conn, row["run_id"], scores, "Fixture manual review")
            pm.evaluate(conn, row["run_id"], {**scores, "accuracy": 9}, "Correction")
            conn.close()
            conn = pm.connect(database)
            saved = pm.records(conn)
            self.assertEqual(len(saved[0]["evaluation_history"]), 2)
            self.assertEqual(saved[0]["evaluation"]["scores"]["accuracy"], 9)
            conn.close()
            target = str(Path(temp) / "export.json")
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(pm.main(["--db", str(database), "export", target]), 0)
                self.assertEqual(pm.main(["--db", str(database), "export", target]), 2)
            report = json.loads(Path(target).read_text())
            self.assertEqual(report["schema"], pm.SCHEMA)
            self.assertEqual(len(report["runs"]), 1)
            self.assertNotIn("fixture-not-a-secret", Path(target).read_text())

    def test_no_key_does_not_call_provider_or_create_database(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(pm.os.environ, {}, clear=True),
            patch.object(pm, "provider_call") as call,
        ):
            path = Path(temp) / "absent.sqlite3"
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                result = pm.main(
                    ["--db", str(path), "run", "--model", "fixture-model", "--confirm-calls", "342"]
                )
            self.assertEqual(result, 2)
            self.assertIn("No model calls", errors.getvalue())
            self.assertFalse(path.exists())
            call.assert_not_called()

    def test_run_requires_exact_planned_call_confirmation(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(pm.os.environ, {"OPENAI_API_KEY": "fixture"}),
            patch.object(pm, "provider_call") as call,
        ):
            path = Path(temp) / "absent.sqlite3"
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                result = pm.main(
                    ["--db", str(path), "run", "--model", "fixture-model", "--confirm-calls", "1"]
                )
            self.assertEqual(result, 2)
            self.assertIn("342 provider calls", errors.getvalue())
            self.assertFalse(path.exists())
            call.assert_not_called()

    def test_invalid_scores_and_custom_cases_rejected(self):
        for value in (True, float("nan"), -1, 11):
            with self.assertRaises(ValueError):
                pm.validate_scores({key: value for key in pm.CRITERIA})
        with self.assertRaises(ValueError):
            pm.validate_cases([self.case, self.case])
        with self.assertRaises(ValueError):
            pm.plan([], trials=3)

    def test_image_policy_requires_permission_in_pro_only(self):
        self.assertIn("Wait for permission", self.prompts["pro"])
        self.assertIn("If I decline", self.prompts["pro"])
        self.assertNotIn("Smart Image Prompt Builder", self.prompts["lite"])


if __name__ == "__main__":
    unittest.main()
