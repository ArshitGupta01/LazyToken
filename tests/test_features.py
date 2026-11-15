import json
import os
import subprocess
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kn


class LazyTokenFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "AccountService.kt").write_text(
            "import demo.AuthClient\nclass AccountService {}\n", encoding="utf-8"
        )
        (self.root / "AuthClient.kt").write_text("class AuthClient {}\n", encoding="utf-8")
        self.db = kn.connect(Path(self.temp.name) / "test.sqlite3")
        kn.sync(self.root, self.db)
        self.project = str(self.root.resolve())

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def run_action(self, operation, **args):
        return kn.feature_call(operation, args, self.db)

    def test_empty_searches_keep_project_and_log_successfully(self):
        for query in ("", "!", "a"):
            with self.subTest(query=query):
                result = self.run_action("search", project=self.project, query=query)
                self.assertEqual(result, {"query": query, "project": self.project, "results": []})
        rows = self.db.execute("SELECT project_id FROM retrievals").fetchall()
        self.assertEqual([row[0] for row in rows], [self.project] * 3)

    def test_natural_language_query_keeps_late_meaningful_terms(self):
        result = self.run_action(
            "search",
            project=self.project,
            query="where is the code in the project and how does the service handle authentication",
        )
        self.assertTrue(any(item.get("name") == "AuthClient" for item in result["results"]))

    def test_search_prioritizes_project_code_but_keeps_tests_and_vendor_searchable(self):
        (self.root / "vendor").mkdir()
        (self.root / "vendor" / "auth.py").write_text("class AuthClient: pass\n")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_auth.py").write_text("class AuthClient: pass\n")
        kn.sync(self.root, self.db)
        result = self.run_action("search", project=self.project, query="AuthClient", limit=100)
        matches = [r["path"] for r in result["results"] if r.get("name") == "AuthClient"]
        self.assertEqual(matches[0], "AuthClient.kt")
        self.assertIn("vendor/auth.py", matches)
        self.assertIn("tests/test_auth.py", matches)
        explicit = self.run_action(
            "search", project=self.project, query="vendor AuthClient", limit=100
        )
        self.assertTrue(any(r.get("path") == "vendor/auth.py" for r in explicit["results"]))

    def test_approval_question_finds_review_and_proposal_symbols(self):
        (self.root / "memory.py").write_text("def review(): pass\ndef propose(): pass\n")
        kn.sync(self.root, self.db)
        result = self.run_action(
            "search", project=self.project, query="Where is a memory proposal approved?"
        )
        names = {r.get("name") for r in result["results"] if r.get("path") == "memory.py"}
        self.assertTrue({"review", "propose"} <= names)

    def test_graph_neighbor_uses_strongest_in_scope_edge_without_extra_hops(self):
        ids = {}
        for name, summary in [
            ("Auth A", "authentication"),
            ("Auth B", "authentication"),
            ("Connection", "dependency"),
            ("Second hop", "dependency"),
        ]:
            ids[name] = kn.add_asset(
                {"kind": "library", "name": name, "summary": summary}, self.db
            )["id"]
        other = self.root.parent / "other"
        other.mkdir()
        kn.sync(other, self.db)

        def link(source, target, weight, project=self.project):
            return kn.link_assets(
                {
                    "source": source,
                    "target": target,
                    "relation": "uses",
                    "weight": weight,
                    "project": project,
                    "evidence": "Synthetic graph fixture",
                },
                self.db,
            )

        link("Auth A", "Connection", 1, str(other.resolve()))
        link("Connection", "Second hop", 1)
        for a, b, origin in [(0.05, 0.9, "Auth B"), (0.95, 0.1, "Auth A")]:
            with self.subTest(a=a, b=b):
                link("Auth A", "Connection", a)
                link("Auth B", "Connection", b)
                result = self.run_action(
                    "search", project=self.project, query="authentication", limit=100
                )
                neighbors = [
                    item for item in result["results"] if item.get("id") == ids["Connection"]
                ]
                self.assertEqual(len(neighbors), 1)
                self.assertEqual(neighbors[0]["score"], max(a, b))
                self.assertIn("Connected to " + origin, neighbors[0]["why"])
                self.assertFalse(
                    any(item.get("id") == ids["Second hop"] for item in result["results"])
                )

    def test_migration_is_idempotent_and_preserves_assets(self):
        kn.add_asset({"kind": "lesson", "name": "old", "summary": "existing"}, self.db)
        self.db.close()
        self.db = kn.connect(Path(self.temp.name) / "test.sqlite3")
        self.assertGreaterEqual(
            self.db.execute("SELECT count(*) FROM lazytoken_migrations").fetchone()[0], 5
        )
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM assets WHERE name='old'").fetchone()[0], 1
        )

    def test_new_default_and_detected_legacy_stores_remain_separate(self):
        local = Path(self.temp.name) / "local"
        home = Path(self.temp.name) / "home"
        legacy = home / ".theekhai-knowledge"
        legacy.mkdir(parents=True)
        (legacy / "network.sqlite3").touch()
        with (
            patch.dict(os.environ, {"LOCALAPPDATA": str(local)}, clear=True),
            patch.object(Path, "home", return_value=home),
        ):
            self.assertEqual(kn.data_root(), local / "LazyToken")
            self.assertIn(legacy, kn.legacy_data_roots())
            preferred = local / "TheekHai" / "KnowledgeNetwork"
            preferred.mkdir(parents=True)
            (preferred / "network.sqlite3").touch()
            self.assertEqual(kn.data_root(), local / "LazyToken")
            self.assertIn(preferred, kn.legacy_data_roots())

    def test_existing_database_gets_backup_before_migration(self):
        path = Path(self.temp.name) / "legacy.sqlite3"
        old = sqlite3.connect(path)
        old.execute("CREATE TABLE legacy_marker(value TEXT)")
        old.execute("INSERT INTO legacy_marker VALUES('preserved')")
        old.commit()
        old.close()
        upgraded = kn.connect(path)
        upgraded.close()
        backups = list(Path(self.temp.name).glob("legacy.sqlite3.pre-v*-*.sqlite3"))
        self.assertEqual(len(backups), 1)
        copy = sqlite3.connect(backups[0])
        self.assertEqual(copy.execute("SELECT value FROM legacy_marker").fetchone()[0], "preserved")
        copy.close()

    def test_future_schema_is_not_modified(self):
        path = Path(self.temp.name) / "future.sqlite3"
        db = sqlite3.connect(path)
        db.execute(
            "CREATE TABLE lazytoken_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
        )
        db.execute("INSERT INTO lazytoken_migrations VALUES(99,1)")
        db.commit()
        db.close()
        with self.assertRaises(RuntimeError):
            kn.connect(path)
        db = sqlite3.connect(path)
        self.assertEqual(db.execute("SELECT version FROM lazytoken_migrations").fetchone()[0], 99)
        db.close()

    def test_proposal_review_freshness_and_isolation(self):
        proposal = self.run_action(
            "propose",
            project=self.project,
            kind="lesson",
            name="Session fix",
            summary="Use the session service",
            task="Fix login",
            evidence="Verified by tests",
            paths=["AccountService.kt"],
        )
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM assets WHERE name='Session fix'").fetchone()[0], 0
        )
        other = Path(self.temp.name) / "other"
        other.mkdir()
        kn.sync(other, self.db)
        self.assertIn(
            "error",
            self.run_action("review", project=str(other), id=proposal["id"], action="approve"),
        )
        result = self.run_action(
            "review", project=self.project, id=proposal["id"], action="approve"
        )
        self.assertEqual(result["status"], "approved")
        self.assertEqual(
            self.run_action("proposals", project=self.project)["proposals"][0]["freshness"],
            "current",
        )
        (self.root / "AccountService.kt").write_text("class ChangedAccount {}\n", encoding="utf-8")
        kn.sync(self.root, self.db)
        self.assertEqual(
            self.run_action("proposals", project=self.project)["proposals"][0]["freshness"], "stale"
        )
        found = self.run_action("search", project=self.project, query="Session fix")["results"]
        self.assertEqual(
            next(r for r in found if r.get("name") == "Session fix")["freshness"], "stale"
        )
        self.assertNotIn(
            "Session fix",
            str(self.run_action("search", project=str(other), query="Session fix")["results"]),
        )
        self.assertEqual(
            self.run_action("review", project=self.project, id=proposal["id"], action="revalidate")[
                "freshness"
            ],
            "current",
        )
        (self.root / "AccountService.kt").unlink()
        kn.sync(self.root, self.db)
        self.assertEqual(
            self.run_action("proposals", project=self.project)["proposals"][0]["freshness"], "stale"
        )
        self.assertIn(
            "error",
            self.run_action("review", project=self.project, id=proposal["id"], action="revalidate"),
        )

    def test_rejected_and_stale_proposals_do_not_create_assets(self):
        p = self.run_action(
            "propose",
            project=self.project,
            kind="decision",
            name="Decision",
            summary="Summary",
            task="Task",
            evidence="Evidence",
            paths=["AuthClient.kt"],
        )
        (self.root / "AuthClient.kt").write_text("class NewClient {}", encoding="utf-8")
        kn.sync(self.root, self.db)
        self.assertIn(
            "error", self.run_action("review", project=self.project, id=p["id"], action="approve")
        )
        self.assertEqual(
            self.run_action("review", project=self.project, id=p["id"], action="reject")["status"],
            "rejected",
        )
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM assets WHERE name='Decision'").fetchone()[0], 0
        )

    def test_reopening_does_not_promote_project_relationship_to_global(self):
        kn.add_asset({"kind": "framework", "name": "Source", "summary": "Source"}, self.db)
        kn.add_asset({"kind": "framework", "name": "Target", "summary": "Target"}, self.db)
        kn.link_assets(
            {
                "source": "Source",
                "target": "Target",
                "relation": "uses",
                "weight": 0.8,
                "evidence": "Project-only evidence",
                "project": self.project,
            },
            self.db,
        )
        self.db.close()
        self.db = kn.connect(Path(self.temp.name) / "test.sqlite3")
        scopes = [
            r[0]
            for r in self.db.execute("SELECT scope FROM asset_link_evidence WHERE relation='uses'")
        ]
        self.assertEqual(scopes, [self.project])
        ranked = self.run_action("search", project=self.project, query="Source")["results"]
        self.assertTrue(
            any(
                item.get("name") == "Target" and "project" in item.get("why", "") for item in ranked
            )
        )
        other = Path(self.temp.name) / "unrelated"
        other.mkdir()
        kn.sync(other, self.db)
        self.assertEqual(kn.get_master_graph(self.db, project=str(other))["edge_count"], 0)
        self.assertNotIn(
            "Target", str(self.run_action("search", project=str(other), query="Source")["results"])
        )
        kn.link_assets(
            {
                "source": "Source",
                "target": "Target",
                "relation": "uses",
                "weight": 0.8,
                "evidence": "Separately declared global evidence",
                "project": "*",
            },
            self.db,
        )
        audit = self.run_action("audit_scopes")
        self.assertEqual(len(audit["ambiguous_global_and_project"]), 1)
        self.assertEqual(len(audit["ambiguous_global_and_project"][0]["evidence"]), 2)

    def test_memory_outcome_dedup_verification_and_supersession(self):
        args = {
            "project": self.project,
            "kind": "lesson",
            "name": "Session recovery",
            "summary": "Use refresh",
            "task": "Fix login",
            "problem": "Expired session",
            "attempts": "Retry once",
            "resolution": "Refresh token",
            "evidence": "Reviewed source",
            "paths": ["AuthClient.kt"],
        }
        proposal = self.run_action("propose", **args)
        duplicate = self.run_action("propose", **args)
        self.assertEqual(duplicate["existing_id"], proposal["id"])
        result = self.run_action(
            "review", project=self.project, id=proposal["id"], action="approve", verified=True
        )
        self.assertEqual(result["status"], "approved")
        memory = self.run_action("proposals", project=self.project)["proposals"][0]
        self.assertEqual(
            (
                memory["problem"],
                memory["attempts"],
                memory["resolution"],
                memory["verification_state"],
            ),
            ("Expired session", "Retry once", "Refresh token", "verified"),
        )
        self.assertEqual(
            self.run_action("review", project=self.project, id=proposal["id"], action="supersede")[
                "status"
            ],
            "superseded",
        )
        self.assertNotIn(
            "Session recovery",
            str(
                self.run_action("search", project=self.project, query="Session recovery")["results"]
            ),
        )
        self.assertNotIn(
            "Session recovery", str(kn.get_master_graph(self.db, project=self.project)["nodes"])
        )

    def test_mcp_direct_memory_write_requires_proposal(self):
        result = kn.call(
            "record_asset",
            {
                "kind": "lesson",
                "name": "Unreviewed",
                "summary": "Not yet reviewed",
                "project": self.project,
            },
            self.db,
        )
        self.assertIn("error", result)
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM assets WHERE name='Unreviewed'").fetchone()[0], 0
        )

    def test_metadata_search_budget_and_dependencies(self):
        results = self.run_action(
            "search", project=self.project, query="Where is user authentication handled?"
        )["results"]
        self.assertTrue(any("Account" in str(r) or "Auth" in str(r) for r in results))
        context = self.run_action(
            "context",
            project=self.project,
            query="authentication",
            budget=100,
            exclude_paths=["AuthClient.kt"],
        )
        self.assertLessEqual(context["estimated_tokens"], 100)
        self.assertNotIn("AuthClient.kt", str(context))
        deps = self.run_action("dependencies", project=self.project)["dependencies"]
        self.assertEqual(deps[0]["status"], "provisional")
        self.assertEqual(deps[0]["candidates"][0]["name"], "AuthClient")

    def test_optional_fts_is_scoped_and_updates_after_changes(self):
        try:
            self.db.execute("SELECT 1 FROM lazytoken_fts LIMIT 1")
        except sqlite3.OperationalError:
            self.skipTest("SQLite build has no FTS5")
        file = self.root / "ProfileRegistry.py"
        file.write_text("class ProfileRegistry: pass", encoding="utf-8")
        kn.sync(self.root, self.db)
        result = self.run_action("search", project=self.project, query="profil")["results"]
        self.assertTrue(any(r.get("name") == "ProfileRegistry" for r in result))
        other = Path(self.temp.name) / "other-fts"
        other.mkdir()
        kn.sync(other, self.db)
        self.assertFalse(self.run_action("search", project=str(other), query="profil")["results"])
        file.unlink()
        kn.sync(self.root, self.db)
        self.assertFalse(
            any(
                r.get("name") == "ProfileRegistry"
                for r in self.run_action("search", project=self.project, query="profil")["results"]
            )
        )

    def test_fts_absence_keeps_lexical_search_working(self):
        try:
            self.db.execute("DROP TABLE lazytoken_fts")
            self.db.commit()
        except sqlite3.OperationalError:
            pass
        kn.sync(self.root, self.db)
        self.assertTrue(self.run_action("search", project=self.project, query="auth")["results"])

    def test_source_range_is_explicit_bounded_and_project_scoped(self):
        source = self.root / "example.py"
        source.write_text(
            'class Example:\n    password = "pretend-value"\n    MY_SECRET = "another-pretend-value"\n',
            encoding="utf-8",
        )
        kn.sync(self.root, self.db)
        result = kn.call(
            "inspect_source_range",
            {"project": self.project, "path": "example.py", "start_line": 1, "end_line": 3},
            self.db,
        )
        self.assertEqual(result["lines"][1]["text"], "[redacted: possible credential]")
        self.assertNotIn("pretend-value", str(result))
        self.assertEqual(result["lines"][2]["text"], "[redacted: possible credential]")
        self.assertIn(
            "error",
            kn.call(
                "inspect_source_range",
                {"project": self.project, "path": "../example.py", "start_line": 1, "end_line": 3},
                self.db,
            ),
        )
        self.assertIn(
            "error",
            kn.call(
                "inspect_source_range",
                {"project": self.project, "path": "example.py", "start_line": 1, "end_line": 81},
                self.db,
            ),
        )
        source.write_text("class Changed: pass", encoding="utf-8")
        self.assertIn(
            "error",
            kn.call(
                "inspect_source_range",
                {"project": self.project, "path": "example.py", "start_line": 1, "end_line": 1},
                self.db,
            ),
        )

    def test_benchmark_missing_values_and_pairing(self):
        self.run_action(
            "benchmark_record",
            task="Synthetic task",
            variant="baseline",
            model="model",
            settings={"temperature": 0},
            input_tokens=40,
            output_tokens=10,
        )
        self.run_action(
            "benchmark_record",
            task="Synthetic task",
            variant="network",
            model="model",
            settings={"temperature": 0},
            input_tokens=20,
            output_tokens=5,
        )
        group = self.run_action("benchmark_list")["comparisons"][0]
        self.assertIsNone(group["net_tokens_saved"])
        self.run_action(
            "benchmark_record",
            task="Synthetic task",
            variant="network",
            model="model",
            settings={"temperature": 0},
            input_tokens=20,
            output_tokens=5,
            indexing_tokens=2,
        )
        self.assertIsNone(self.run_action("benchmark_list")["comparisons"][0]["net_tokens_saved"])
        self.assertFalse(self.run_action("benchmark_list")["comparisons"][0]["eligible_for_claim"])
        self.assertIsNone(group["network"]["elapsed_seconds"])

    def test_cli_and_mcp_expose_bounded_context(self):
        env = os.environ.copy()
        env["KN_HOME"] = self.temp.name
        env["LAZYTOKEN_DISABLE_AUTOWATCH"] = "1"
        result = subprocess.run(
            [sys.executable, str(Path(kn.__file__)), "lazytoken", "benchmark_list"],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout)["runs"], [])
        value = kn.call(
            "search_knowledge", {"project": self.project, "query": "auth", "budget": 120}, self.db
        )
        self.assertLessEqual(value["estimated_tokens"], 120)
        self.assertIn("not a model tokenizer", value["budget_type"])

    def test_completion_checkpoint_requires_evidence_and_remains_pending(self):
        args = {
            "project": self.project,
            "task": "Repair account recovery",
            "outcome": "success",
            "resolution": "Refresh the session before retrying the account request.",
            "evidence": "AccountService.kt and passing targeted tests",
            "paths": ["AccountService.kt"],
        }
        before = self.db.execute("SELECT count(*) FROM assets").fetchone()[0]
        result = self.run_action("complete_task", **args)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(result["review_required"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM assets").fetchone()[0], before)
        duplicate = self.run_action(
            "complete_task", **{**args, "task": "Different title for same lesson"}
        )
        self.assertEqual(duplicate["existing_id"], result["id"])
        self.assertIn("error", self.run_action("complete_task", **{**args, "paths": []}))
        self.assertIn(
            "error", self.run_action("complete_task", **{**args, "paths": ["../outside.kt"]})
        )
        other = Path(self.temp.name) / "other"
        other.mkdir()
        (other / "AccountService.kt").write_text("class Other {}")
        kn.sync(other, self.db)
        separate = self.run_action("complete_task", **{**args, "project": str(other.resolve())})
        self.assertEqual(separate["status"], "pending")


if __name__ == "__main__":
    unittest.main()
