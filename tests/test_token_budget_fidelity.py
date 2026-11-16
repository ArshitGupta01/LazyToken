"""tests/test_token_budget_fidelity.py
Comprehensive unit tests for Milestone 1: Model & Token Budget Fidelity (LT-P1-203).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kn
import broker
import token_budget
import mcp_schema


def expected_schema_tokens(compact):
    return len(json.dumps(mcp_schema.mcp_tools(compact=compact))) // 4


class TestMcpSchemaOverhead(unittest.TestCase):
    """Verifies MCP schema overhead token estimation."""

    def test_mcp_schema_overhead_full_default(self):
        """Full schema overhead reflects the current catalog."""
        val = token_budget.mcp_schema_overhead()
        self.assertIsInstance(val, int)
        expected = expected_schema_tokens(False)
        self.assertEqual(val, expected)

    def test_mcp_schema_overhead_full_explicit(self):
        """Full schema overhead with compact=False uses the current catalog."""
        self.assertEqual(
            token_budget.mcp_schema_overhead(compact=False), expected_schema_tokens(False)
        )

    def test_mcp_schema_overhead_compact(self):
        """Compact schema overhead reflects the current catalog."""
        val = token_budget.mcp_schema_overhead(compact=True)
        self.assertIsInstance(val, int)
        expected = expected_schema_tokens(True)
        self.assertEqual(val, expected)

    def test_mcp_schema_overhead_savings_ratio(self):
        """Compact mode saves at least 65% token overhead compared to full schema."""
        full = token_budget.mcp_schema_overhead(compact=False)
        compact = token_budget.mcp_schema_overhead(compact=True)
        savings = (full - compact) / full
        self.assertGreater(savings, 0.65)


class TestChatFramingOverhead(unittest.TestCase):
    """Verifies chat framing envelope overhead calculation."""

    def test_chat_framing_overhead_default_single_turn(self):
        """Default call returns 25 tokens for 1 turn."""
        val = token_budget.chat_framing_overhead()
        self.assertEqual(val, 25)

    def test_chat_framing_overhead_multi_turn(self):
        """Multi-turn calls scale linearly: N * 25 tokens."""
        self.assertEqual(token_budget.chat_framing_overhead(turns=1), 25)
        self.assertEqual(token_budget.chat_framing_overhead(turns=4), 100)
        self.assertEqual(token_budget.chat_framing_overhead(turns=10), 250)

    def test_chat_framing_overhead_zero_and_negative_turns(self):
        """Zero or negative turns clamp cleanly to 0."""
        self.assertEqual(token_budget.chat_framing_overhead(turns=0), 0)
        self.assertEqual(token_budget.chat_framing_overhead(turns=-5), 0)

    def test_chat_framing_overhead_extreme_turns(self):
        """Handles extreme turn counts without overflow."""
        self.assertEqual(token_budget.chat_framing_overhead(turns=10000), 250000)


class TestTokenAccounting(unittest.TestCase):
    """Verifies structured token accounting dictionary and arithmetic totals."""

    def test_token_accounting_required_fields_presence(self):
        """token_accounting returns all required fields."""
        acct = token_budget.token_accounting(payload_tokens=150, compact_mcp=False, is_approx=True)
        required_fields = {
            "payload_tokens",
            "mcp_schema_overhead_tokens",
            "chat_framing_overhead_tokens",
            "total_context_footprint_tokens",
            "is_approximate",
            "fidelity",
            "budget_scope",
            "estimation_note",
        }
        self.assertTrue(required_fields.issubset(acct.keys()))

    def test_token_accounting_arithmetic_full_mcp(self):
        """Arithmetic check with full MCP schema."""
        acct = token_budget.token_accounting(payload_tokens=200, compact_mcp=False, is_approx=True)
        self.assertEqual(acct["payload_tokens"], 200)
        self.assertEqual(acct["mcp_schema_overhead_tokens"], expected_schema_tokens(False))
        self.assertEqual(acct["chat_framing_overhead_tokens"], 25)
        self.assertEqual(
            acct["total_context_footprint_tokens"], 200 + expected_schema_tokens(False) + 25
        )
        self.assertTrue(acct["is_approximate"])
        self.assertEqual(acct["fidelity"], "approximate_chars_div_4")
        self.assertIn("approximate", acct["estimation_note"].lower())

    def test_token_accounting_arithmetic_compact_mcp(self):
        """Arithmetic check with compact MCP schema."""
        acct = token_budget.token_accounting(payload_tokens=100, compact_mcp=True, is_approx=True)
        self.assertEqual(acct["payload_tokens"], 100)
        self.assertEqual(acct["mcp_schema_overhead_tokens"], expected_schema_tokens(True))
        self.assertEqual(acct["chat_framing_overhead_tokens"], 25)
        self.assertEqual(
            acct["total_context_footprint_tokens"], 100 + expected_schema_tokens(True) + 25
        )

    def test_token_accounting_exact_tokenizer_mode(self):
        """Accounting reflects exact tokenizer fidelity when is_approx=False."""
        acct = token_budget.token_accounting(
            payload_tokens=350, compact_mcp=False, model="gpt-4o", is_approx=False
        )
        self.assertFalse(acct["is_approximate"])
        self.assertEqual(acct["fidelity"], "exact_offline_tokenizer")
        self.assertNotIn("chars/4", acct["estimation_note"])
        self.assertTrue(acct["total_is_approximate"])

    def test_token_accounting_zero_and_negative_clamp(self):
        """Negative payload and negative turns clamp cleanly to 0."""
        acct = token_budget.token_accounting(
            payload_tokens=-50, compact_mcp=True, is_approx=True, turns=-3
        )
        self.assertEqual(acct["payload_tokens"], 0)
        self.assertEqual(acct["chat_framing_overhead_tokens"], 0)
        self.assertEqual(acct["mcp_schema_overhead_tokens"], expected_schema_tokens(True))
        self.assertEqual(acct["total_context_footprint_tokens"], expected_schema_tokens(True))

    def test_token_accounting_huge_token_footprint(self):
        """Context footprint exceeding 1,000,000 tokens tracked without precision loss."""
        acct = token_budget.token_accounting(
            payload_tokens=1000000, compact_mcp=False, is_approx=True, turns=4
        )
        self.assertEqual(acct["payload_tokens"], 1000000)
        self.assertEqual(acct["mcp_schema_overhead_tokens"], expected_schema_tokens(False))
        self.assertEqual(acct["chat_framing_overhead_tokens"], 100)
        self.assertEqual(
            acct["total_context_footprint_tokens"], 1000000 + expected_schema_tokens(False) + 100
        )


class TestCounterBackwardsCompatibility(unittest.TestCase):
    """Verifies counter(...) backward compatibility and structured indicators."""

    def test_counter_default_fallback_3_tuple_unpacking(self):
        """counter returns a 3-element tuple unpacking cleanly."""
        res = token_budget.counter({}, kn.estimate)
        self.assertEqual(len(res), 3)
        count_fn, budget_type, fallback = res
        self.assertTrue(callable(count_fn))
        self.assertEqual(budget_type, "estimate: characters / 4; not a tokenizer")
        self.assertIsNone(fallback)

    def test_counter_structured_indicators(self):
        """counter exposes structured indicators (is_approximate, fidelity, note, indicators)."""
        res = token_budget.counter({}, kn.estimate)
        self.assertTrue(hasattr(res, "is_approximate"))
        self.assertTrue(res.is_approximate)
        self.assertEqual(res.fidelity, "approximate_chars_div_4")
        self.assertIn("approximate", res.note.lower())
        self.assertIsInstance(res.indicators, dict)
        self.assertTrue(res.indicators["is_approximate"])

    def test_counter_unsupported_model_fallback(self):
        """Unsupported model falls back with approximate indicators and reason."""
        res = token_budget.counter({"model": "unknown-model"}, kn.estimate)
        count_fn, budget_type, fallback = res
        self.assertEqual(budget_type, "estimate: characters / 4; not a tokenizer")
        self.assertIsNotNone(fallback)
        self.assertIn("No matching offline tokenizer configured", fallback)
        self.assertTrue(res.is_approximate)

    def test_counter_strict_budget_rejection(self):
        """Strict budget without configured tokenizer raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            token_budget.counter({"model": "gpt-4", "strict_budget": True}, kn.estimate)
        self.assertIn("Strict budget refused", str(ctx.exception))

    def test_counter_invalid_args_rejection(self):
        """Invalid model or strict_budget type raises ValueError."""
        with self.assertRaises(ValueError):
            token_budget.counter({"model": 123}, kn.estimate)
        with self.assertRaises(ValueError):
            token_budget.counter({"strict_budget": "yes"}, kn.estimate)


class TestOfflineTokenizerVsFallback(unittest.TestCase):
    """Verifies offline tokenizer loading vs fallback behavior."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_offline_tokenizer_exact_loading(self):
        """Configured valid offline tokenizer returns exact indicators."""
        try:
            from tokenizers import Tokenizer, models, pre_tokenizers
        except ImportError:
            self.skipTest("tokenizers library not installed")

        tokenizer = Tokenizer(
            models.WordLevel({"[UNK]": 0, "hello": 1, "world": 2}, unk_token="[UNK]")
        )
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        path = self.root / "tok.json"
        tokenizer.save(str(path))

        with patch.dict(
            os.environ,
            {
                "LAZYTOKEN_TOKENIZER_MODEL": "test-tok",
                "LAZYTOKEN_TOKENIZER_FILE": str(path),
            },
        ):
            res = token_budget.counter({"model": "test-tok"}, kn.estimate)
            count_fn, budget_type, fallback = res
            self.assertEqual(budget_type, "tokenizer:test-tok")
            self.assertIsNone(fallback)
            self.assertFalse(res.is_approximate)
            self.assertEqual(res.fidelity, "exact_offline_tokenizer")
            self.assertEqual(count_fn("hello world"), 2)

    def test_offline_tokenizer_missing_file_falls_back(self):
        """Configured model with non-existent file path falls back to approximation."""
        with patch.dict(
            os.environ,
            {
                "LAZYTOKEN_TOKENIZER_MODEL": "test-tok",
                "LAZYTOKEN_TOKENIZER_FILE": str(self.root / "nonexistent.json"),
            },
        ):
            res = token_budget.counter({"model": "test-tok"}, kn.estimate)
            count_fn, budget_type, fallback = res
            self.assertEqual(budget_type, "estimate: characters / 4; not a tokenizer")
            self.assertIn("Offline tokenizer unavailable", fallback)
            self.assertTrue(res.is_approximate)


class TestBrokerTaskContextFidelityIntegration(unittest.TestCase):
    """Verifies broker.task_context integration with token accounting & approximation flags."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "repo"
        self.root.mkdir()
        (self.root / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        self.db = kn.connect(Path(self.temp_dir.name) / "store.sqlite3")
        kn.sync(self.root, self.db)
        self.project = str(self.root.resolve())

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_task_context_emits_fidelity_fields_and_preserves_existing(self):
        """task_context emits is_approximate and token_accounting while preserving all existing fields."""
        res = broker.task_context(
            kn,
            {"project": self.project, "task": "run app", "mode": "balanced", "budget": 600},
            self.db,
        )
        self.assertNotIn("error", res)
        # Existing fields
        self.assertEqual(res["project"], self.project)
        self.assertIn("budget_type", res)
        self.assertIn("estimated_tokens", res)
        self.assertIn("used_tokens", res)
        self.assertIn("budget_scope", res)
        self.assertIn("decision", res)
        self.assertIn("results", res)
        # New M1 fields
        self.assertIn("is_approximate", res)
        self.assertTrue(res["is_approximate"])
        self.assertIn("token_accounting", res)
        acct = res["token_accounting"]
        self.assertEqual(acct["payload_tokens"], res["used_tokens"])
        self.assertIsNone(acct["mcp_schema_overhead_tokens"])
        self.assertEqual(acct["chat_framing_overhead_tokens"], 25)
        self.assertIsNone(acct["total_context_footprint_tokens"])
        self.assertTrue(acct["total_is_approximate"])

    def test_task_context_compact_mcp_option(self):
        """compact_mcp: True uses the compact schema estimate."""
        res = broker.task_context(
            kn,
            {
                "project": self.project,
                "task": "run app",
                "mode": "balanced",
                "budget": 600,
                "compact_mcp": True,
            },
            self.db,
        )
        self.assertNotIn("error", res)
        acct = res["token_accounting"]
        self.assertEqual(acct["mcp_schema_overhead_tokens"], expected_schema_tokens(True))
        self.assertEqual(
            acct["total_context_footprint_tokens"],
            res["used_tokens"] + expected_schema_tokens(True) + 25,
        )

    def test_task_context_skip_includes_token_accounting(self):
        """Skip retrieval branch includes token_accounting and approximation flag."""
        res = broker.task_context(
            kn,
            {"project": self.project, "task": "run app", "skip_retrieval": True, "budget": 600},
            self.db,
        )
        self.assertEqual(res["decision"], "skip")
        self.assertTrue(res["is_approximate"])
        self.assertIn("token_accounting", res)
        self.assertEqual(res["token_accounting"]["payload_tokens"], res["used_tokens"])

    def test_task_context_abstain_includes_token_accounting(self):
        """Abstain branch includes token_accounting and approximation flag."""
        res = broker.task_context(
            kn, {"project": self.project, "task": "nonexistent xyz 999", "budget": 600}, self.db
        )
        self.assertEqual(res["decision"], "abstain")
        self.assertTrue(res["is_approximate"])
        self.assertIn("token_accounting", res)

    def test_task_context_legacy_patched_counter_compatibility(self):
        """task_context gracefully tolerates raw 3-tuple patches from legacy unit tests."""
        with patch(
            "token_budget.counter", return_value=(lambda text: 15, "mocked-tokenizer", None)
        ):
            res = broker.task_context(
                kn, {"project": self.project, "task": "run app", "budget": 600}, self.db
            )
            self.assertNotIn("error", res)
            self.assertEqual(res["budget_type"], "mocked-tokenizer")
            self.assertIn("is_approximate", res)
            self.assertIn("token_accounting", res)


if __name__ == "__main__":
    unittest.main()
