import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark import retrieval_assessment


class RetrievalAssessmentTests(unittest.TestCase):
    def test_real_index_refresh_and_labelled_predictions(self):
        corpus = json.loads(
            (retrieval_assessment.ROOT / "benchmark/retrieval_cases.json").read_text(
                encoding="utf-8-sig"
            )
        )
        result = retrieval_assessment.assess(corpus)
        rows = {item["id"]: item for item in result["observations"]}
        self.assertEqual(rows["changed-symbol"]["sync"]["changed"], 1)
        self.assertIn("auth.py", rows["changed-symbol"]["predicted"])
        self.assertEqual(rows["renamed-file"]["sync"]["removed"], 1)
        self.assertIn("identity.py", rows["renamed-file"]["predicted"])
        self.assertEqual(rows["removed-file"]["sync"]["removed"], 1)
        self.assertEqual(rows["removed-file"]["decision"], "abstain")
        self.assertTrue(all(not row["forbidden_returned"] for row in rows.values()))
        self.assertEqual(result["metrics"]["cases"], len(corpus["cases"]))

    def test_rejects_unknown_fixture(self):
        with self.assertRaises(ValueError):
            retrieval_assessment.assess(
                {"label_provenance": "test", "cases": [{"fixture": "../outside"}]}
            )


if __name__ == "__main__":
    unittest.main()
