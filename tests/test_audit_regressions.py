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

    def test_reuse_guidance_is_sent_at_initialization_in_both_catalog_modes(self):
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            },
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "get_task_context",
                    "arguments": {"project": self.project, "task": "auth", "budget": 600},
                },
            },
        ]
        for compact in (False, True):
            with self.subTest(compact=compact):
                output = io.StringIO()
                with (
                    patch("sys.stdin", io.StringIO("\n".join(json.dumps(row) for row in requests))),
                    patch("sys.stdout", output),
                ):
                    kn.rpc_server(self.db, compact=compact)
                replies = [json.loads(row) for row in output.getvalue().splitlines()]
                self.assertEqual(len(replies), 3)
                instructions = replies[0]["result"]["instructions"]
                self.assertIn("get_task_context", instructions)
                self.assertIn("session_id", instructions)
                self.assertIn("human review", instructions)
                self.assertIn("untrusted evidence", instructions)
                self.assertLess(len(instructions), 1000)
                tools = replies[1]["result"]["tools"]
                self.assertTrue(any(tool["name"] == "get_task_context" for tool in tools))
                self.assertNotIn("instructions", replies[1]["result"])
                result = json.loads(replies[2]["result"]["content"][0]["text"])
                self.assertNotIn("error", result)
                self.assertNotIn("instructions", result)
                self.assertNotIn(instructions, json.dumps(replies[1:]))

    def test_mcp_negotiates_versions_and_never_executes_notifications(self):
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {"protocolVersion": "2099-01-01"},
            },
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "sync_project", "arguments": {}},
            },
            {"jsonrpc": "2.0", "id": None, "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        ]
        output = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO("\n".join(json.dumps(row) for row in requests))),
            patch("sys.stdout", output),
            patch("kn.call") as call,
        ):
            kn.rpc_server(self.db)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(replies[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(replies[2]["error"]["code"], -32600)
        self.assertEqual(replies[3]["id"], 3)
        call.assert_not_called()

    def test_graph_reuse_flow_keeps_trust_labels_deduplication_and_review_boundary(self):
        proposal = self.proposal(
            name="Auth reuse", summary="Reuse the existing Auth class for authentication."
        )
        approved = kn.feature_call(
            "review",
            {"project": self.project, "id": proposal["id"], "action": "approve", "verified": True},
            self.db,
        )
        self.assertTrue(approved["saved"])
        hypothesis = self.proposal(
            name="Auth hypothesis", summary="Authentication retry remains an unverified hypothesis."
        )
        unverified = kn.feature_call(
            "review",
            {
                "project": self.project,
                "id": hypothesis["id"],
                "action": "approve",
                "verified": False,
            },
            self.db,
        )
        args = {
            "project": self.project,
            "task": "Auth reuse authentication",
            "budget": 1200,
            "session_id": "reuse-flow",
        }
        first = kn.call("get_task_context", args, self.db)
        memory = next(item for item in first["results"] if item.get("id") == approved["asset_id"])
        self.assertEqual(memory["verification_state"], "verified")
        self.assertEqual(memory["freshness"], "current")
        self.assertIn("Current as indexed", memory["why"])
        self.assertEqual(memory["evidence_paths"], ["Auth.py"])
        hypothesis_crumb = next(
            item for item in first["results"] if item.get("id") == unverified["asset_id"]
        )
        self.assertEqual(hypothesis_crumb["verification_state"], "hypothesis")
        self.assertIn("Reuse the existing Auth class", memory["summary"])
        self.assertTrue(any(item.get("path") == "Auth.py" for item in first["results"]))
        inspected = kn.call(
            "inspect_source_range",
            {"project": self.project, "path": "Auth.py", "start_line": 1, "end_line": 1},
            self.db,
        )
        self.assertIn("class Auth", inspected["lines"][0]["text"])
        repeated = kn.call("get_task_context", args, self.db)
        self.assertEqual(repeated["results"], [])
        self.assertGreater(repeated["suppressed_seen"], 0)
        (self.root / "Auth.py").write_text("class Auth:\n    def retry(self): pass\n")
        kn.sync(self.root, self.db)
        changed = kn.call("get_task_context", args, self.db)
        stale = next(item for item in changed["results"] if item.get("id") == approved["asset_id"])
        self.assertEqual(stale["freshness"], "stale")
        self.assertNotIn("summary", stale)
        self.assertEqual(stale["evidence_paths"], ["Auth.py"])
        self.assertIn("revalidate", stale["why"])
        before = self.db.execute("SELECT count(*) FROM assets").fetchone()[0]
        checkpoint = kn.call(
            "lazytoken",
            {
                "action": "complete_task",
                "payload": {
                    "project": self.project,
                    "task": "Add retry behavior",
                    "outcome": "success",
                    "resolution": "Use Auth.retry to centralize retry behavior.",
                    "evidence": "Synthetic updated implementation",
                    "paths": ["Auth.py"],
                },
            },
            self.db,
        )
        self.assertEqual(checkpoint["status"], "pending")
        self.assertTrue(checkpoint["review_required"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM assets").fetchone()[0], before)

    def test_unavailable_memory_is_deprioritized_and_clearly_marked(self):
        (self.root / "Offline.py").write_text("class Offline: pass", encoding="utf-8")
        kn.sync(self.root, self.db)
        current = self.proposal(name="Auth current", summary="Authentication primary solution")
        offline = self.proposal(
            name="Auth unavailable",
            summary="Authentication secondary approach",
            paths=["Offline.py"],
        )
        for proposal in (current, offline):
            self.assertTrue(
                kn.feature_call(
                    "review",
                    {
                        "project": self.project,
                        "id": proposal["id"],
                        "action": "approve",
                        "verified": True,
                    },
                    self.db,
                )["saved"]
            )
        self.db.execute("INSERT INTO index_errors VALUES(?,?)", (self.project, "Offline.py"))
        self.db.commit()
        ranked = features.ranked_search(
            kn, {"project": self.project, "query": "auth", "limit": 100}, self.db
        )
        scores = {r["name"]: r["score"] for r in ranked["results"] if r["type"] == "asset"}
        self.assertGreater(scores["Auth current"], scores["Auth unavailable"])
        result = kn.call(
            "get_task_context", {"project": self.project, "task": "auth", "budget": 1200}, self.db
        )
        memory = next(r for r in result["results"] if r.get("name") == "Auth unavailable")
        self.assertEqual(memory["freshness"], "unverified")
        self.assertIn("verify before reuse", memory["why"])

    def test_compact_context_includes_current_verified_lesson_when_it_fits(self):
        proposal = self.proposal(summary="Reuse Auth for account login.")
        approved = kn.feature_call(
            "review",
            {"project": self.project, "id": proposal["id"], "action": "approve", "verified": True},
            self.db,
        )
        result = kn.call(
            "get_task_context",
            {"project": self.project, "task": "Auth account login", "budget": 250},
            self.db,
        )
        memory = next(item for item in result["results"] if item.get("id") == approved["asset_id"])
        self.assertEqual(memory["summary"], "Reuse Auth for account login.")
        self.assertLessEqual(result["used_tokens"], 250)

    def test_direct_stale_memory_is_not_hidden_by_confidence_penalty(self):
        proposal = self.proposal(name="AmberGiraffe", summary="AmberGiraffe lesson")
        approved = kn.feature_call(
            "review",
            {"project": self.project, "id": proposal["id"], "action": "approve", "verified": True},
            self.db,
        )
        (self.root / "Auth.py").write_text("class Changed: pass", encoding="utf-8")
        kn.sync(self.root, self.db)
        result = kn.call(
            "get_task_context",
            {"project": self.project, "task": "AmberGiraffe", "budget": 600},
            self.db,
        )
        memory = next(r for r in result["results"] if r.get("id") == approved["asset_id"])
        self.assertEqual(memory["freshness"], "stale")
        self.assertIn("revalidate", memory["why"])
        self.db.execute(
            "UPDATE assets SET tags=? WHERE id=?", ("amberweakmatch", approved["asset_id"])
        )
        self.db.commit()
        weak = kn.call(
            "get_task_context",
            {"project": self.project, "task": "amberweakmatch", "budget": 600},
            self.db,
        )
        self.assertEqual(weak["decision"], "abstain")

    def test_oversized_expanded_memory_falls_back_and_can_expand_later(self):
        proposal = self.proposal(name="Auth reusable lesson", summary="auth " + "detail " * 150)
        approved = kn.feature_call(
            "review",
            {"project": self.project, "id": proposal["id"], "action": "approve", "verified": True},
            self.db,
        )
        args = {
            "project": self.project,
            "task": "auth reusable lesson",
            "budget": 350,
            "session_id": "progressive-memory",
            "expand_assets": True,
        }
        small = kn.call("get_task_context", args, self.db)
        memory = next(item for item in small["results"] if item.get("id") == approved["asset_id"])
        self.assertNotIn("summary", memory)
        self.assertTrue(small["truncated"])
        self.assertLessEqual(small["used_tokens"], 350)
        large = kn.call("get_task_context", {**args, "budget": 1200}, self.db)
        expanded = next(item for item in large["results"] if item.get("id") == approved["asset_id"])
        self.assertTrue(expanded["summary"].startswith("auth detail"))

    def test_expanded_memory_suppresses_compact_repeat_but_changed_evidence_returns(self):
        proposal = self.proposal(
            name="Auth reuse", summary="Reuse authentication " + "detail " * 150
        )
        approved = kn.feature_call(
            "review",
            {"project": self.project, "id": proposal["id"], "action": "approve", "verified": True},
            self.db,
        )
        args = {
            "project": self.project,
            "task": "auth reuse",
            "budget": 1200,
            "session_id": "expanded-first",
        }
        first = kn.call("get_task_context", {**args, "expand_assets": True}, self.db)
        memory = next(r for r in first["results"] if r.get("id") == approved["asset_id"])
        self.assertIn("summary", memory)
        repeated = kn.call("get_task_context", args, self.db)
        self.assertFalse(any(r.get("id") == approved["asset_id"] for r in repeated["results"]))
        self.assertGreater(repeated["suppressed_seen"], 0)
        fallback = kn.call(
            "get_task_context", {**args, "budget": 350, "expand_assets": True}, self.db
        )
        self.assertTrue(fallback["truncated"])
        self.assertFalse(any(r.get("id") == approved["asset_id"] for r in fallback["results"]))
        override = kn.call("get_task_context", {**args, "include_seen": True}, self.db)
        self.assertTrue(any(r.get("id") == approved["asset_id"] for r in override["results"]))
        (self.root / "Auth.py").write_text("class Changed: pass", encoding="utf-8")
        kn.sync(self.root, self.db)
        changed = kn.call("get_task_context", args, self.db)
        memory = next(r for r in changed["results"] if r.get("id") == approved["asset_id"])
        self.assertEqual(memory["freshness"], "stale")

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

        original_read = kn.read_project_file

        def bounded_read(root, path, limit=1_000_001, **kwargs):
            if path.endswith(".py"):
                return Bounded(b"class Auth: pass").read(limit)
            return original_read(root, path, limit, **kwargs)

        with patch.object(kn, "read_project_file", side_effect=bounded_read):
            kn.sync(self.root, self.db)

        def unreadable(root, path, limit=1_000_001, **kwargs):
            if path.endswith(".py"):
                raise PermissionError("synthetic")
            return original_read(root, path, limit, **kwargs)

        with patch.object(kn, "read_project_file", side_effect=unreadable):
            result = kn.sync(self.root, self.db)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["unchanged"], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM index_errors").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
