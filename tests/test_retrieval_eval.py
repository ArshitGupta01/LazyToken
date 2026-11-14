import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import retrieval_eval


class RetrievalMetricsTests(unittest.TestCase):
    def test_known_metrics_and_abstention(self):
        cases = [
            {
                "id": "one",
                "relevant": ["a", "b"],
                "predicted": ["x", "a", "b"],
                "estimated_tokens": 120,
            },
            {"id": "two", "relevant": [], "predicted": [], "abstained": True},
        ]
        result = retrieval_eval.evaluate(cases, k=2)
        self.assertEqual(result["details"][0]["precision_at_k"], 0.5)
        self.assertEqual(result["details"][0]["recall_at_k"], 0.5)
        self.assertEqual(result["details"][0]["reciprocal_rank"], 0.5)
        self.assertEqual(result["abstention_accuracy"], 1.0)
        self.assertEqual(result["estimated_tokens_mean"], 120)

    def test_invalid_rankings_are_rejected(self):
        with self.assertRaises(ValueError):
            retrieval_eval.evaluate([{"id": "x", "relevant": ["a"], "predicted": ["a", "a"]}])
        with self.assertRaises(ValueError):
            retrieval_eval.evaluate(
                [{"id": "x", "relevant": ["a"], "predicted": ["a"], "abstained": True}]
            )

    def test_methods_can_compare_the_same_labelled_case(self):
        cases = [
            {"id": "q1", "method": "lexical", "relevant": ["a"], "predicted": ["x", "a"]},
            {"id": "q1", "method": "hybrid", "relevant": ["a"], "predicted": ["a"]},
        ]
        result = retrieval_eval.evaluate(cases, k=2)
        self.assertEqual(result["methods"]["lexical"]["mrr_at_k"], 0.5)
        self.assertEqual(result["methods"]["hybrid"]["mrr_at_k"], 1.0)
        with self.assertRaises(ValueError):
            retrieval_eval.evaluate([cases[0], {**cases[1], "relevant": ["b"]}], k=2)


if __name__ == "__main__":
    unittest.main()
