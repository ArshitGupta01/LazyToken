import json
import io
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kn


class ContextBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "AuthService.py").write_text(
            "class AuthService:\n    pass\n", encoding="utf-8"
        )
        self.db = kn.connect(Path(self.temp.name) / "store.sqlite3")
        kn.sync(self.root, self.db)
        self.project = str(self.root.resolve())

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def call(self, **args):
        return kn.call(
            "get_task_context",
            {"project": self.project, "task": "authentication auth", **args},
            self.db,
        )

    def test_budget_explanation_and_session_dedup(self):
        first = self.call(session_id="session-1", budget=500)
        self.assertEqual(first["decision"], "retrieve")
        self.assertTrue(first["results"])
        self.assertLessEqual(first["estimated_tokens"], 500)
        self.assertTrue(all("why" in x for x in first["results"]))
        second = self.call(session_id="session-1", budget=500)
        self.assertEqual(second["results"], [])
        self.assertGreater(second["suppressed_seen"], 0)
        checkpoint = kn.feature_call(
            "checkpoint", {"project": self.project, "session_id": "session-1"}, self.db
        )
        self.assertGreater(checkpoint["supplied_items"], 0)
        self.assertNotIn("class AuthService", str(checkpoint))
        self.assertTrue(self.call(session_id="session-1", budget=500, include_seen=True)["results"])
        self.assertGreater(
            kn.call(
                "clear_context_session",
                {"project": self.project, "session_id": "session-1"},
                self.db,
            )["cleared"],
            0,
        )
        self.assertTrue(self.call(session_id="session-1", budget=500)["results"])

    def test_prompt_output_includes_context_only_when_useful_and_errors_are_not_prompt_text(self):
        data = Path(self.temp.name) / "cli-data"
        data.mkdir()
        db = kn.connect(data / "network.sqlite3")
        kn.sync(self.root, db)
        db.close()
        env = {**os.environ, "KN_HOME": str(data), "LAZYTOKEN_DISABLE_AUTOWATCH": "1"}
        base = [
            sys.executable,
            str(Path(kn.__file__)),
            "context",
            "--project",
            self.project,
            "--prompt",
        ]

        def run(task, *extra):
            return subprocess.run(
                base + ["--task", task, *extra], capture_output=True, text=True, env=env
            )

        found = run("Find AuthService")
        self.assertEqual(found.returncode, 0)
        self.assertIn("untrusted evidence", found.stdout)
        self.assertIn("AuthService.py", found.stdout)
        self.assertNotIn("class AuthService:", found.stdout)
        metadata = found.stdout.split("verify relevant source):\n", 1)[1]
        brief = json.loads(metadata)
        self.assertEqual(brief["project"], self.project)
        self.assertNotIn("budget_scope", brief)
        full = subprocess.run(
            base[:-1] + ["--task", "Find AuthService"], capture_output=True, text=True, env=env
        )
        self.assertEqual(full.returncode, 0)
        self.assertIn("budget_scope", json.loads(full.stdout))
        self.assertLess(len(metadata), len(full.stdout))
        missing = run("zebra quantum nonexistent")
        self.assertEqual(missing.returncode, 0)
        self.assertEqual(missing.stdout.strip(), "zebra quantum nonexistent")
        invalid = run("Find AuthService", "--budget", "5")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(invalid.stdout, "")
        self.assertIn("error", invalid.stderr)

    def test_prompt_falls_back_when_compact_json_has_more_tokenizer_tokens(self):
        def counter(text):
            return 1 if '"budget":' in text else 1000

        output = io.StringIO()
        arguments = [
            "kn.py",
            "context",
            "--project",
            self.project,
            "--task",
            "auth",
            "--budget",
            "300",
            "--prompt",
        ]
        with (
            patch("sys.argv", arguments),
            patch("sys.stdout", output),
            patch("kn.connect", return_value=self.db),
            patch("token_budget.counter", return_value=(counter, "test", None)),
        ):
            kn.main()
        metadata = output.getvalue().split("verify relevant source):\n", 1)[1]
        self.assertEqual(json.loads(metadata)["budget"], 300)
        self.assertLessEqual(counter(metadata), 300)

    def test_prompt_refuses_to_print_if_tokenizer_changes_between_counts(self):
        output, errors = io.StringIO(), io.StringIO()
        arguments = [
            "kn.py",
            "context",
            "--project",
            self.project,
            "--task",
            "auth",
            "--budget",
            "300",
            "--prompt",
        ]
        counters = [
            (lambda text: 1, "test", None),
            (lambda text: 1000, "test", None),
        ]
        with (
            patch("sys.argv", arguments),
            patch("sys.stdout", output),
            patch("sys.stderr", errors),
            patch("kn.connect", return_value=self.db),
            patch("token_budget.counter", side_effect=counters),
            self.assertRaises(SystemExit),
        ):
            kn.main()
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Tokenizer changed", errors.getvalue())

    def test_oversized_result_does_not_hide_smaller_matches(self):
        rows = [
            {"type": "file", "path": "x" * 2000, "score": 10, "why": "match"},
            {"type": "file", "path": "auth.py", "score": 3, "why": "match"},
        ]
        with patch("features.ranked_search", return_value={"results": rows}):
            result = self.call(budget=250)
        self.assertTrue(result["truncated"])
        self.assertEqual([item["path"] for item in result["results"]], ["auth.py"])
        self.assertLessEqual(result["used_tokens"], 250)

    def test_file_breadcrumb_is_omitted_when_a_symbol_already_supplies_the_path(self):
        rows = [
            {
                "type": "symbol",
                "name": "AuthService",
                "path": "AuthService.py",
                "line": 1,
                "score": 6,
                "why": "match",
            },
            {
                "type": "file",
                "name": "AuthService.py",
                "path": "AuthService.py",
                "score": 5,
                "why": "match",
            },
            {"type": "file", "name": "other.py", "path": "other.py", "score": 4, "why": "match"},
        ]
        with patch("features.ranked_search", return_value={"results": rows}):
            first = self.call(budget=400, session_id="dedup-path")
            second = self.call(budget=400, session_id="dedup-path")
        self.assertEqual(
            [(r["type"], r["path"]) for r in first["results"]],
            [("symbol", "AuthService.py"), ("file", "other.py")],
        )
        self.assertEqual(second["results"], [])

    def test_file_breadcrumb_remains_when_symbol_cannot_fit(self):
        rows = [
            {
                "type": "symbol",
                "name": "x" * 2000,
                "path": "AuthService.py",
                "score": 6,
                "why": "match",
            },
            {
                "type": "file",
                "name": "AuthService.py",
                "path": "AuthService.py",
                "score": 5,
                "why": "match",
            },
        ]
        with patch("features.ranked_search", return_value={"results": rows}):
            result = self.call(budget=250)
        self.assertTrue(result["truncated"])
        self.assertEqual(
            [(r["type"], r["path"]) for r in result["results"]], [("file", "AuthService.py")]
        )

    def test_changed_file_is_resent_and_project_sessions_are_isolated(self):
        self.call(session_id="one", budget=500)
        (self.root / "AuthService.py").write_text(
            "class AuthService:\n    value = 1\n", encoding="utf-8"
        )
        kn.sync(self.root, self.db)
        self.assertTrue(self.call(session_id="one", budget=500)["results"])
        other = Path(self.temp.name) / "other"
        other.mkdir()
        (other / "AuthService.py").write_text("class AuthService: pass", encoding="utf-8")
        kn.sync(other, self.db)
        result = kn.call(
            "get_task_context",
            {"project": str(other.resolve()), "task": "auth", "session_id": "one"},
            self.db,
        )
        self.assertTrue(result["results"])
        self.assertTrue(all("project" not in x for x in result["results"]))

    def test_checkpoint_returns_most_recent_keys_with_scoped_total(self):
        rows = [(self.project, "long", f"entry{i:02}", "hash", i) for i in range(35)]
        rows.append((self.project, "another", "not-in-session", "hash", 1000))
        rows.append(("other-project", "long", "not-in-project", "hash", 1000))
        rows.extend((self.project, "tie", key, "hash", 1) for key in ("z", "a"))
        self.db.executemany("INSERT INTO context_session_items VALUES(?,?,?,?,?)", rows)
        self.db.commit()
        result = kn.feature_call(
            "checkpoint", {"project": self.project, "session_id": "long"}, self.db
        )
        self.assertEqual(result["supplied_items"], 35)
        self.assertEqual(result["recent_keys"], [f"entry{i:02}" for i in range(34, 4, -1)])
        self.assertTrue(result["truncated"])
        tie = kn.feature_call("checkpoint", {"project": self.project, "session_id": "tie"}, self.db)
        self.assertEqual(tie["recent_keys"], ["a", "z"])
        empty = kn.feature_call(
            "checkpoint", {"project": self.project, "session_id": "empty"}, self.db
        )
        self.assertEqual(
            (empty["supplied_items"], empty["recent_keys"], empty["truncated"]), (0, [], False)
        )

    def test_skip_abstain_and_invalid_budget(self):
        self.assertEqual(self.call(skip_retrieval=True)["decision"], "skip")
        self.assertEqual(
            kn.call(
                "get_task_context",
                {"project": self.project, "task": "zebra quantum nonexistent"},
                self.db,
            )["decision"],
            "abstain",
        )
        self.assertIn("error", self.call(budget=5))

    def test_directory_traversal_and_symlink_escape_are_excluded(self):
        self.assertFalse(kn.safe_relative("../secret.py"))
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text("secret", encoding="utf-8")
        link = self.root / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Creating directory symlinks requires privileges on this platform")
        self.assertFalse(kn.safe_file(self.root, "linked/secret.py"))

    def test_fallback_indexing_respects_gitignore_without_git(self):
        (self.root / ".gitignore").write_text(
            "private/\n*.secret.py\n!safe.secret.py\n", encoding="utf-8"
        )
        (self.root / "private").mkdir()
        (self.root / "private" / "notes.py").write_text("class Private: pass")
        (self.root / "safe.secret.py").write_text("class ShouldStayExcluded: pass")
        nested = self.root / "nested"
        nested.mkdir()
        (nested / ".gitignore").write_text("ignored.py\n")
        (nested / "ignored.py").write_text("class Ignored: pass")
        (nested / "allowed.py").write_text("class Allowed: pass")
        with patch("kn.subprocess.run", side_effect=FileNotFoundError):
            files = kn.list_files(self.root)
        self.assertIn("nested/allowed.py", files)
        self.assertNotIn("private/notes.py", files)
        self.assertNotIn("safe.secret.py", files)
        self.assertNotIn("nested/ignored.py", files)
        self.assertFalse(kn.safe_relative("config/service-account.json"))
        self.assertFalse(kn.safe_relative(".env.local/data.py"))

    def test_cache_reused_and_invalidated_after_own_and_external_writes(self):
        import features

        with patch("features.ranked_search", wraps=features.ranked_search) as search:
            self.call(budget=600)
            self.call(budget=600)
            self.assertEqual(search.call_count, 1)
            (self.root / "AuthService.py").write_text("class AuthService: value = 3")
            kn.sync(self.root, self.db)
            self.call(budget=600)
            self.assertEqual(search.call_count, 2)
            other = kn.connect(Path(self.temp.name) / "store.sqlite3")
            other.execute(
                "UPDATE files SET digest='new-digest' WHERE project_id=?", (self.project,)
            )
            other.commit()
            other.close()
            self.call(budget=600)
            self.assertEqual(search.call_count, 3)

    def test_offline_strict_budget_and_explicit_fallback(self):
        import os

        with patch.dict(
            os.environ, {"LAZYTOKEN_TOKENIZER_MODEL": "", "LAZYTOKEN_TOKENIZER_FILE": ""}
        ):
            self.assertIn("error", self.call(model="unsupported", strict_budget=True, budget=600))
            fallback = self.call(model="unsupported", budget=600)
            self.assertIn("estimate", fallback["budget_type"])
            self.assertIn("tokenizer_fallback", fallback)
        # A deterministic injected counter verifies full-payload enforcement without downloading a model.
        with patch(
            "token_budget.counter",
            return_value=(lambda text: len(text.encode("utf-8")), "test-byte-tokenizer", None),
        ):
            result = self.call(budget=1400)
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            self.assertLessEqual(len(encoded.encode("utf-8")), 1400)
            self.assertGreaterEqual(result["used_tokens"], len(encoded.encode("utf-8")))
            self.assertIn("error", self.call(budget=100))

    def test_complete_text_skip_avoids_search_and_progressive_expansion(self):
        with patch("features.ranked_search", side_effect=AssertionError("must not retrieve")):
            result = self.call(
                task="rewrite this text: supplied text", context_is_complete=True, budget=600
            )
            self.assertEqual(result["decision"], "skip")
        first = self.call(session_id="expand", budget=600)
        following = self.call(session_id="expand", mode="deep", budget=1200)
        prior = {(x["type"], x.get("path"), x.get("name")) for x in first["results"]}
        self.assertFalse(
            prior & {(x["type"], x.get("path"), x.get("name")) for x in following["results"]}
        )

    def test_local_tokenizer_disables_saved_padding_and_truncation(self):
        import os

        try:
            from tokenizers import Tokenizer, models, pre_tokenizers
        except ImportError:
            self.skipTest("Optional offline tokenizers adapter is not installed")
        tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer.enable_truncation(1)
        tokenizer.enable_padding(length=2000)
        path = Path(self.temp.name) / "tokenizer.json"
        tokenizer.save(str(path))
        with patch.dict(
            os.environ,
            {"LAZYTOKEN_TOKENIZER_MODEL": "fixture-words", "LAZYTOKEN_TOKENIZER_FILE": str(path)},
        ):
            import token_budget

            count, kind, fallback = token_budget.counter(
                {"model": "fixture-words", "strict_budget": True}, kn.estimate
            )
            self.assertEqual(count("one two three"), 3)
            self.assertIsNone(fallback)
            result = self.call(model="fixture-words", strict_budget=True, budget=600)
            self.assertNotIn("error", result)
            self.assertLessEqual(
                count(
                    json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                ),
                600,
            )
            self.assertEqual(result["budget_type"], "tokenizer:fixture-words")

    def test_session_checkpoint_active_graph_and_midway_recall(self):
        (self.root / "helper.py").write_text("def assist():\n    return 42\n", encoding="utf-8")
        (self.root / "service.py").write_text("import helper\ndef run():\n    return helper.assist()\n", encoding="utf-8")
        kn.sync(self.root, self.db)

        # 1. First task context retrieval
        ret = kn.call(
            "get_task_context",
            {"project": self.project, "task": "run helper assist service", "session_id": "midway-session", "budget": 800},
            self.db,
        )
        self.assertNotIn("error", ret)
        self.assertTrue(ret["results"])
        self.assertIn("graph_edges", ret)
        self.assertTrue(any(e["source"] == "service.py" and e["target"] == "helper.py" for e in ret["graph_edges"]))

        # 2. Mid-way recall via checkpoint
        cp = kn.call(
            "checkpoint",
            {"project": self.project, "session_id": "midway-session"},
            self.db,
        )
        self.assertNotIn("error", cp)
        self.assertIn("active_graph", cp)
        self.assertIn("service.py", cp["active_graph"]["files"])
        self.assertIn("helper.py", cp["active_graph"]["files"])
        self.assertTrue(any(e["source"] == "service.py" and e["target"] == "helper.py" for e in cp["active_graph"]["edges"]))
        self.assertIn("graph_topology", cp)
        self.assertTrue(any("service.py --(imports)--> helper.py" in t for t in cp["graph_topology"]))


if __name__ == "__main__":
    unittest.main()
