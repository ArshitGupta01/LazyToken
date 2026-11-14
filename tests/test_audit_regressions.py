import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import kn
import broker
import features


class AuditRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "app"
        self.root.mkdir()
        (self.root / "Auth.py").write_text("class Auth: pass", encoding="utf-8")
        self.db = kn.connect(Path(self.temp.name) / "audit.sqlite3")
        kn.sync(self.root, self.db)
        self.project = str(self.root.resolve())

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def proposal(self, **extra):
        return kn.feature_call(
            "propose",
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Auth fix",
                "summary": "Refresh the session before retrying the failed account request.",
                "task": "Fixture",
                "evidence": "Synthetic fixture",
                "paths": ["Auth.py"],
                **extra,
            },
            self.db,
        )

    def test_unicode_git_path_and_common_javascript_import_forms(self):
        subprocess.run(["git", "init", str(self.root)], check=True, capture_output=True)
        (self.root / "caf\u00e9.py").write_text("class Cafe: pass", encoding="utf-8")
        source = """// import fake from 'fake';
import { createClient } from '@supabase/supabase-js';
import React from 'react';
import type { Session } from './types';
import {
  thing
} from './multi';
import './side-effect';
const fs = require('fs');
const lazy = import('./lazy');
export { thing } from './export';
"""
        (self.root / "main.ts").write_text(source, encoding="utf-8")
        kn.sync(self.root, self.db)
        self.assertIn("caf\u00e9.py", kn.list_files(self.root))
        targets = {row[0] for row in self.db.execute("SELECT target FROM imports")}
        self.assertEqual(
            targets,
            {
                "@supabase/supabase-js",
                "react",
                "./types",
                "./multi",
                "./side-effect",
                "fs",
                "./lazy",
                "./export",
            },
        )

    def test_unchanged_files_reextract_after_extractor_upgrade(self):
        (self.root / "client.ts").write_text("import { x } from './real';", encoding="utf-8")
        kn.sync(self.root, self.db)
        self.db.execute("DELETE FROM imports")
        self.db.execute("DELETE FROM index_state")
        self.db.commit()
        kn.sync(self.root, self.db)
        self.assertEqual(self.db.execute("SELECT target FROM imports").fetchone()[0], "./real")

    def test_mcp_cannot_review_and_operator_refuses_unsynced_evidence(self):
        proposal = self.proposal()
        args = {
            "project": self.project,
            "id": proposal["id"],
            "action": "approve",
            "verified": True,
        }
        self.assertIn("error", kn.call("lazytoken", {"action": "review", "payload": args}, self.db))
        (self.root / "Auth.py").write_text("class Different: pass", encoding="utf-8")
        self.assertIn("error", kn.feature_call("review", args, self.db))
        self.assertEqual(self.db.execute("SELECT count(*) FROM assets").fetchone()[0], 0)

    def test_expansion_telemetry_and_session_cache(self):
        proposal = self.proposal()
        features.review(
            kn,
            {"project": self.project, "id": proposal["id"], "action": "approve", "verified": True},
            self.db,
        )
        args = {
            "project": self.project,
            "task": "auth fix",
            "session_id": "regression",
            "budget": 1500,
        }
        with patch("features.ranked_search", wraps=features.ranked_search) as search:
            first = broker.task_context(kn, args, self.db)
            second = broker.task_context(kn, args, self.db)
            self.assertEqual(search.call_count, 1)
            self.assertFalse(second["results"])
        expanded = broker.task_context(kn, {**args, "expand_assets": True}, self.db)
        self.assertTrue(any(r.get("summary") for r in expanded["results"] if r["type"] == "asset"))
        self.assertGreaterEqual(kn.call("token_report", {}, self.db)["retrieval_calls"], 3)
        self.assertIsNone(kn.call("token_report", {}, self.db)["measured_net_saved"])

    def test_failed_legacy_measurement_is_not_savings(self):
        for variant, tokens, success in [("baseline", 100, True), ("network", 10, False)]:
            features.benchmark(
                {
                    "task": "fixture",
                    "variant": variant,
                    "model": "fixture",
                    "settings": {},
                    "input_tokens": tokens,
                    "output_tokens": 0,
                    "indexing_tokens": 0,
                    "successful": success,
                },
                self.db,
            )
        comparison = features.benchmark_list(self.db)["comparisons"][0]
        self.assertIsNone(comparison["net_tokens_saved"])
        self.assertFalse(comparison["eligible_for_claim"])
        self.assertIn(
            "error",
            kn.measure_task(
                {"task": "fixture", "baseline_tokens": -1, "network_tokens": 2}, self.db
            ),
        )

    def test_canonical_records_share_harness_validation(self):
        base = {
            "task_id": "NB01",
            "pair_id": "fixture",
            "arm": "baseline",
            "source_snapshot": "synthetic-fixture",
            "agent": "fixture",
            "model": "fixture",
            "settings": {"temperature": 0},
            "usage_source": "provider",
            "measurement_kind": "synthetic",
            "input_tokens": 100,
            "output_tokens": 20,
            "indexing_tokens": 0,
            "success": True,
            "tests_passed": True,
        }
        for args in (base, {**base, "arm": "lazytoken_improved", "input_tokens": 40}):
            self.assertTrue(features.benchmark(args, self.db)["saved"])
        comparison = features.canonical_benchmarks(self.db)["comparisons"][0]
        self.assertEqual(comparison["tokens_saved"], 60)
        self.assertFalse(comparison["eligible_for_claim"])
        self.assertIn("error", features.benchmark(base, self.db))
        self.assertIn(
            "error",
            features.benchmark({**base, "pair_id": "real", "measurement_kind": "real"}, self.db),
        )

    def test_correction_remains_reviewable(self):
        original = "This application should always enable certificate verification for every outgoing HTTPS request in the production environment."
        self.proposal(summary=original)
        correction = self.proposal(
            name="Auth policy correction", summary=original.replace("enable", "disable")
        )
        self.assertEqual(correction["status"], "pending")
        self.assertTrue(correction["related_candidates"])

    def test_compact_tool_catalog_reduces_schema_without_trust_promotion(self):
        standard = json.dumps(kn.mcp_tools(), ensure_ascii=False)
        compact = json.dumps(kn.mcp_tools(True), ensure_ascii=False)
        self.assertLess(len(compact), len(standard))
        lazy = next(tool for tool in kn.mcp_tools(True) if tool["name"] == "lazytoken")
        self.assertNotIn("review", lazy["inputSchema"]["properties"]["action"]["enum"])
        self.assertTrue(any(tool["name"] == "get_task_context" for tool in kn.mcp_tools(True)))

    def test_bounded_read_and_explicit_index_errors(self):
        class Bounded(io.BytesIO):
            def read(self, size=-1):
                if size != 1_000_001:
                    raise AssertionError("Unbounded source read")
                return super().read(size)

        with patch.object(Path, "open", side_effect=lambda *a, **k: Bounded(b"class Auth: pass")):
            kn.sync(self.root, self.db)
        with patch.object(Path, "open", side_effect=PermissionError("synthetic")):
            result = kn.sync(self.root, self.db)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["unchanged"], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM index_errors").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
