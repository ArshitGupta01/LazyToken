"""Unit tests for Cost-Aware Retrieval Policy & Utility Ranking (Milestone 2 / Feature 18)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import broker
import kn


class TestCostAwareTaskClassifier(unittest.TestCase):
    """Unit tests for conservative task classification (skip, abstain, retrieve)."""

    def test_classify_explicit_skip_retrieval(self) -> None:
        decision, reason = broker.classify_retrieval_need(
            "Refactor auth logic", skip_retrieval=True
        )
        self.assertEqual(decision, "skip")
        self.assertIn("explicitly requested", reason)

    def test_classify_context_is_complete(self) -> None:
        decision, reason = broker.classify_retrieval_need(
            "Fix typo in variable name", context_is_complete=True
        )
        self.assertEqual(decision, "skip")
        self.assertIn("complete", reason.lower())

    def test_classify_empty_or_whitespace_task_abstains(self) -> None:
        for empty_val in ("", "   ", "\t\n"):
            decision, reason = broker.classify_retrieval_need(empty_val)
            self.assertEqual(decision, "abstain")
            self.assertIn("empty", reason.lower())

    def test_classify_conversational_greetings_skip(self) -> None:
        greetings = ["Hello", "hi there", "Good morning", "howdy", "Hey!"]
        for g in greetings:
            decision, reason = broker.classify_retrieval_need(g)
            self.assertEqual(decision, "skip", f"Greeting '{g}' should be skipped")
            self.assertIn("greeting", reason.lower())

    def test_classify_self_contained_utility_tasks_skip(self) -> None:
        self_contained = [
            "format json string",
            "prettify json payload",
            "fix indentation in this block",
            "convert snake_case to camelCase",
            "write a regex for email validation",
            "calculate factorial of n",
            "reverse a string",
        ]
        for t in self_contained:
            decision, reason = broker.classify_retrieval_need(t)
            self.assertEqual(decision, "skip", f"Task '{t}' should be skipped")
            self.assertIn("self-contained", reason.lower())

    def test_classify_repo_code_tasks_retrieve(self) -> None:
        code_tasks = [
            "Refactor TokenStore.validate method signature",
            "Find callers of session_checkpoint in broker",
            "Fix payment deadlock in transaction processor",
            "Investigate import loop between auth and user services",
            "Fix indentation in dashboard.py",
        ]
        for t in code_tasks:
            decision, reason = broker.classify_retrieval_need(t)
            self.assertEqual(decision, "retrieve", f"Task '{t}' should trigger retrieval")
            self.assertIn("retriev", reason.lower())


class TestExpectedUtilityRanking(unittest.TestCase):
    """Unit tests for utility-per-token ranking formula."""

    def test_utility_formula_calculation(self) -> None:
        # (relevance * freshness * verification) / tokens
        # (10.0 * 1.0 * 1.0) / 100 = 0.1
        u1 = broker.utility_per_token(
            relevance=10.0, freshness=1.0, verification=1.0, estimated_tokens=100
        )
        self.assertAlmostEqual(u1, 0.1, places=4)

        # Verified lesson gets verification boost: (10.0 * 1.0 * 1.2) / 50 = 0.24
        u2 = broker.utility_per_token(
            relevance=10.0, freshness=1.0, verification=1.2, estimated_tokens=50
        )
        self.assertAlmostEqual(u2, 0.24, places=4)

        # Stale evidence: (10.0 * 0.5 * 1.0) / 100 = 0.05
        u3 = broker.utility_per_token(
            relevance=10.0, freshness=0.5, verification=1.0, estimated_tokens=100
        )
        self.assertAlmostEqual(u3, 0.05, places=4)

    def test_utility_zero_and_negative_tokens_clamped(self) -> None:
        # Tokens <= 0 must be clamped to 1 to avoid ZeroDivisionError
        u_zero = broker.utility_per_token(relevance=5.0, estimated_tokens=0)
        self.assertEqual(u_zero, 5.0)

        u_neg = broker.utility_per_token(relevance=5.0, estimated_tokens=-10)
        self.assertEqual(u_neg, 5.0)

    def test_utility_ranking_preference_order(self) -> None:
        # Candidate A: high relevance, small footprint (high utility)
        util_a = broker.utility_per_token(
            relevance=8.0, freshness=1.0, verification=1.0, estimated_tokens=40
        )
        # Candidate B: high relevance, huge token footprint (low utility)
        util_b = broker.utility_per_token(
            relevance=8.0, freshness=1.0, verification=1.0, estimated_tokens=800
        )
        # Candidate C: lower relevance, but very compact and verified
        util_c = broker.utility_per_token(
            relevance=4.0, freshness=1.0, verification=1.2, estimated_tokens=20
        )

        self.assertGreater(util_a, util_b)
        self.assertGreater(util_c, util_b)


class TestProgressiveContextExpansionAndWhy(unittest.TestCase):
    """Unit tests for progressive context expansion and why_this_context output."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = kn.connect(Path(self.temp_dir.name) / "test.sqlite3")
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "service.py").write_text(
            "class AuthService:\n    def validate_token(self, token: str) -> bool: return True\n",
            encoding="utf-8",
        )
        (self.repo / "controller.py").write_text(
            "from service import AuthService\ndef handle_login(req): return AuthService().validate_token(req.token)\n",
            encoding="utf-8",
        )
        kn.sync(self.repo, self.db)
        self.project_id = str(self.repo.resolve())

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_progressive_expansion_flags(self) -> None:
        # Default mode (compact) without expand_context -> progressive_expansion is False
        res1 = broker.task_context(
            kn,
            {"project": self.project_id, "task": "validate_token", "mode": "compact"},
            self.db,
        )
        self.assertFalse(res1.get("progressive_expansion", False))

        # Explicit expand_context=True -> progressive_expansion is True
        res2 = broker.task_context(
            kn,
            {"project": self.project_id, "task": "validate_token", "expand_context": True},
            self.db,
        )
        self.assertTrue(res2.get("progressive_expansion", False))

        # Deep mode -> progressive_expansion is True
        res3 = broker.task_context(
            kn,
            {"project": self.project_id, "task": "validate_token", "mode": "deep"},
            self.db,
        )
        self.assertTrue(res3.get("progressive_expansion", False))

    def test_why_this_context_and_backward_compatibility(self) -> None:
        res = broker.task_context(
            kn,
            {
                "project": self.project_id,
                "task": "AuthService validate_token",
                "why_this_context": True,
            },
            self.db,
        )
        self.assertIn("results", res)
        self.assertGreater(len(res["results"]), 0)
        for crumb in res["results"]:
            self.assertIn("why_this_context", crumb)
            self.assertIn("why", crumb)
            self.assertEqual(crumb["why_this_context"], crumb["why"])
            self.assertIsInstance(crumb["why_this_context"], str)
            self.assertGreater(len(crumb["why_this_context"]), 0)


if __name__ == "__main__":
    unittest.main()
