import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kn

try:
    from legacy_seed_fixture import seed_fixture
except ImportError:
    from tests.legacy_seed_fixture import seed_fixture


def legacy_asset(args, conn):
    project = args.get("project", "")
    scope = args.get("scope", "global")
    if project:
        project = kn.resolve_project(project, conn) or str(Path(project).resolve())
    cur = conn.execute(
        "INSERT INTO assets(kind,name,summary,tags,source,created_at,scope,project_id) VALUES(?,?,?,'','',0,?,?)",
        (args["kind"], args["name"], args["summary"], scope, project),
    )
    conn.commit()
    return {"saved": True, "id": cur.lastrowid}


class KnowledgeNetworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "TheekHai"
        self.root.mkdir()
        (self.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (self.root / "README.md").write_text("TheekHai project pilot\n", encoding="utf-8")
        (self.root / "src.kt").write_text(
            "package demo\nimport demo.core.Api\nclass AccountStore {\n fun lookupAccount(id: String) {}\n}\n",
            encoding="utf-8",
        )
        (self.root / ".env").write_text("API_KEY=do-not-index", encoding="utf-8")
        (self.root / "ignored.txt").write_text("ignored", encoding="utf-8")
        self.db_path = Path(self.tmp.name) / "graph.sqlite3"
        self.db = kn.connect(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_first_and_incremental_index(self):
        first = kn.sync(self.root, self.db)
        self.assertEqual(first["added"], 2)  # README and source; ignored and .env excluded
        second = kn.sync(self.root, self.db)
        self.assertEqual(second["added"] + second["changed"] + second["removed"], 0)
        self.assertEqual(second["unchanged"], 2)
        found = kn.search("lookupAccount", self.db)
        self.assertEqual(found["results"][0]["name"], "lookupAccount")
        self.assertNotIn("API_KEY", str(kn.context(str(self.root), self.db)))

    def test_updates_and_deletions_are_incremental(self):
        kn.sync(self.root, self.db)
        (self.root / "src.kt").write_text("class CaseStore {}\n", encoding="utf-8")
        (self.root / "gone.md").write_text("notes", encoding="utf-8")
        first = kn.sync(self.root, self.db)
        self.assertEqual((first["changed"], first["added"]), (1, 1))
        (self.root / "gone.md").unlink()
        second = kn.sync(self.root, self.db)
        self.assertEqual(second["removed"], 1)
        self.assertEqual(kn.search("CaseStore", self.db)["results"][0]["name"], "CaseStore")

    def test_discovery_access_failure_preserves_index_until_retry(self):
        import subprocess

        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        kn.sync(self.root, self.db)
        before = self.db.execute(
            "SELECT digest FROM files WHERE project_id=? AND path=?",
            (str(self.root.resolve()), "src.kt"),
        ).fetchone()[0]
        original_lstat = Path.lstat

        def denied(path, *args, **kwargs):
            if path.name == "src.kt":
                raise PermissionError("temporary discovery failure")
            return original_lstat(path, *args, **kwargs)

        with patch.object(Path, "lstat", denied):
            result = kn.sync(self.root, self.db)
        self.assertEqual(result["removed"], 0)
        self.assertIn("src.kt", result["error_paths"])
        self.assertEqual(
            self.db.execute(
                "SELECT digest FROM files WHERE project_id=? AND path=?",
                (str(self.root.resolve()), "src.kt"),
            ).fetchone()[0],
            before,
        )
        self.assertTrue(kn.search("lookupAccount", self.db)["results"])
        (self.root / "src.kt").unlink()
        self.assertEqual(kn.sync(self.root, self.db)["removed"], 1)

    def test_unreadable_ignore_file_does_not_erase_fallback_index(self):
        kn.sync(self.root, self.db)
        reader = kn.read_project_file

        def denied_ignore(root, relative, *args, **kwargs):
            if Path(relative).name == ".gitignore":
                raise PermissionError("temporary ignore read failure")
            return reader(root, relative, *args, **kwargs)

        with patch.object(kn, "read_project_file", side_effect=denied_ignore):
            result = kn.sync(self.root, self.db)
        self.assertEqual(result["removed"], 0)
        self.assertIn(".", result["error_paths"])
        self.assertTrue(kn.search("lookupAccount", self.db)["results"])

    def test_project_reader_limits_bytes_and_rejects_paths(self):
        self.assertEqual(kn.read_project_file(self.root, "src.kt", 7), b"package")
        for path in ("../outside.py", ".env", "missing.py"):
            with self.subTest(path=path), self.assertRaises(OSError):
                kn.read_project_file(self.root, path)

    def test_project_reader_rejects_symlink_replaced_after_discovery(self):
        outside = Path(self.tmp.name) / "outside.py"
        outside.write_text("secret", encoding="utf-8")
        target = self.root / "link.py"
        try:
            target.symlink_to(outside)
        except OSError:
            self.skipTest("Symlink creation requires privileges")
        with self.assertRaises(OSError):
            kn.read_project_file(self.root, "link.py")

    def test_project_reader_rejects_replaced_root(self):
        original = self.root
        displaced = Path(self.tmp.name) / "displaced"
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "src.kt").write_text("outside", encoding="utf-8")
        kn.sync(original, self.db)
        original.rename(displaced)
        try:
            try:
                original.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Symlink creation requires privileges")
            with self.assertRaises(OSError):
                kn.read_project_file(original, "src.kt")
            self.assertIn("error", kn.sync(original, self.db))
        finally:
            if original.is_symlink():
                original.unlink()
            displaced.rename(original)

    @unittest.skipIf(sys.platform == "win32", "Named pipes use a different API on Windows")
    def test_project_reader_rejects_fifo_without_blocking(self):
        import os

        os.mkfifo(self.root / "pipe.py")
        with self.assertRaises(OSError):
            kn.read_project_file(self.root, "pipe.py")

    @unittest.skipIf(sys.platform == "win32", "Named pipes use a different API on Windows")
    def test_ignore_rules_reject_fifo_without_blocking(self):
        import os

        (self.root / ".gitignore").unlink()
        os.mkfifo(self.root / ".gitignore")
        self.assertEqual(kn._ignore_rules(self.root, self.root), [(".", "*", False)])

    def test_concurrent_sync_cannot_overwrite_newer_index(self):
        import source_index

        path = self.root / "race.py"
        path.write_text("def original(): pass\n", encoding="utf-8")
        kn.sync(self.root, self.db)
        path.write_text("def old_staged(): pass\n", encoding="utf-8")
        extract = source_index.python_symbols
        interleaved = False

        def extract_with_concurrent_sync(body):
            nonlocal interleaved
            if "old_staged" in body and not interleaved:
                interleaved = True
                path.write_text("def newest(): pass\n", encoding="utf-8")
                other = kn.connect(self.db_path)
                try:
                    self.assertNotIn("error", kn.sync(self.root, other))
                finally:
                    other.close()
            return extract(body)

        with patch("source_index.python_symbols", side_effect=extract_with_concurrent_sync):
            result = kn.sync(self.root, self.db)
        self.assertTrue(interleaved)
        self.assertNotIn("error", result)
        names = {row[0] for row in self.db.execute("SELECT name FROM symbols WHERE path='race.py'")}
        self.assertIn("newest", names)
        self.assertNotIn("old_staged", names)

    def test_project_path_aliases_resolve_to_the_indexed_scope(self):
        kn.sync(self.root, self.db)
        canonical = str(self.root.resolve())
        variants = [str(self.root) + "/.", str(self.root).replace("\\", "/")]
        if sys.platform == "win32":
            import ctypes

            buffer = ctypes.create_unicode_buffer(32768)
            size = ctypes.windll.kernel32.GetShortPathNameW(str(self.root), buffer, len(buffer))
            if 0 < size < len(buffer):
                variants.append(buffer.value)
        for value in variants:
            with self.subTest(path=value):
                self.assertEqual(kn.resolve_project(value, self.db), canonical)
                result = kn.search("lookupAccount", self.db, value)
                self.assertTrue(result["results"])
                self.assertEqual(kn.context(value, self.db)["project"], self.root.name)
        self.assertEqual(kn.resolve_project(str(self.root.parent / "not-indexed"), self.db), "")

    def test_project_filter_isolation(self):
        kn.sync(self.root, self.db)
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        (other / "other.kt").write_text("class AccountStore {}\n", encoding="utf-8")
        kn.sync(other, self.db)
        scoped = kn.search("AccountStore", self.db, str(self.root))
        self.assertTrue(scoped["results"])
        self.assertTrue(all(row.get("project") == "TheekHai" for row in scoped["results"]))

    def test_symbol_search_uses_identifier_words_not_substrings(self):
        (self.root / "nav.kt").write_text(
            "class SidebarNavItem {}\nclass ViteServer {}\n", encoding="utf-8"
        )
        kn.sync(self.root, self.db)
        result = kn.search("Vite TypeScript", self.db, str(self.root))
        names = [r["name"] for r in result["results"] if r["type"] == "symbol"]
        self.assertIn("ViteServer", names)
        self.assertNotIn("SidebarNavItem", names)

    def test_assets_and_budget_estimate(self):
        saved = legacy_asset(
            {
                "kind": "pattern",
                "name": "small-context",
                "summary": "Retrieve only task-relevant context",
                "tags": "tokens",
            },
            self.db,
        )
        self.assertTrue(saved["saved"])
        result = kn.search("small-context", self.db)
        self.assertEqual(result["results"][0]["type"], "asset")
        self.assertGreaterEqual(result["estimated_tokens"], 1)

    def test_memory_search_matches_terms_in_any_order_and_ranks_full_match_first(self):
        legacy_asset(
            {"kind": "lesson", "name": "Session timeout", "summary": "Expire old sessions"},
            self.db,
        )
        legacy_asset(
            {"kind": "lesson", "name": "Session logging", "summary": "Record events"},
            self.db,
        )
        results = kn.search("timeout session", self.db)["results"]
        self.assertEqual(
            [item["name"] for item in results[:2]], ["Session timeout", "Session logging"]
        )
        self.assertGreater(results[0]["activation"], results[1]["activation"])
        self.assertEqual(kn.search("billing invoice", self.db)["results"], [])

    def test_bounded_graph_keeps_connected_nodes_before_isolated_nodes(self):
        for name in ("A isolated", "B isolated", "Y linked", "Z linked"):
            legacy_asset({"kind": "lesson", "name": name, "summary": ""}, self.db)
        linked = kn.link_assets(
            {
                "source": "Y linked",
                "target": "Z linked",
                "relation": "uses",
                "evidence": "Verified test relation",
                "project": "*",
            },
            self.db,
        )
        self.assertTrue(linked["linked"])
        graph = kn.get_master_graph(self.db, limit=2)
        self.assertEqual({node["name"] for node in graph["nodes"]}, {"Y linked", "Z linked"})
        self.assertEqual(graph["edge_count"], 1)

    def test_seeded_master_asset_links_to_project(self):
        kn.sync(self.root, self.db)
        seeded = seed_fixture(self.root, self.db)
        self.assertEqual(seeded["seeded"], 6)
        self.assertEqual(seeded["linked"], 6)
        result = kn.search("Ktor backend", self.db)
        self.assertEqual(result["results"][0]["name"], "Ktor")
        self.assertEqual(result["results"][0]["used_in"], [])
        self.assertEqual(kn.get_master_graph(self.db)["edge_count"], 0)
        graph = kn.get_master_graph(self.db, project=str(self.root))
        self.assertEqual(graph["node_count"], 6)
        self.assertEqual(graph["edge_count"], 6)
        self.assertTrue(
            all(
                isinstance(e["source_id"], int) and isinstance(e["target_id"], int)
                for e in graph["edges"]
            )
        )
        bounded = kn.get_master_graph(self.db, limit=3, project=str(self.root), edge_limit=1)
        self.assertEqual(
            (bounded["total_nodes"], bounded["node_count"], bounded["edge_count"]), (6, 3, 1)
        )
        self.assertTrue(bounded["nodes_truncated"])
        self.assertTrue(bounded["edges_truncated"])

    def test_search_spreads_activation_to_related_assets(self):
        kn.sync(self.root, self.db)
        seed_fixture(self.root, self.db)
        result = kn.search("Vite TypeScript", self.db, str(self.root))
        names = [r["name"] for r in result["results"] if r["type"] == "asset"]
        self.assertEqual(names[:2], ["Vite + TypeScript", "Ktor"])
        self.assertLess(result["results"][1]["activation"], 1.0)

    def test_new_project_does_not_inherit_theekhai_links_or_seed_assets(self):
        kn.sync(self.root, self.db)
        seed_fixture(self.root, self.db)
        other = Path(self.tmp.name) / "new-app"
        other.mkdir()
        (other / "README.md").write_text("New app", encoding="utf-8")
        kn.sync(other, self.db)
        seed = seed_fixture(other, self.db)
        self.assertEqual(seed["asset_edges"], 0)
        other_search = kn.search("Vite TypeScript", self.db, str(other))
        names = [r["name"] for r in other_search["results"] if r["type"] == "asset"]
        self.assertEqual(names, ["Vite + TypeScript"])
        other_graph = kn.get_master_graph(self.db, project=str(other))
        self.assertEqual(other_graph["edge_count"], 0)

    def test_project_scoped_lesson_stays_in_its_project(self):
        kn.sync(self.root, self.db)
        saved = legacy_asset(
            {
                "kind": "lesson",
                "name": "TheekHai-only",
                "summary": "Project-specific lesson",
                "scope": "project",
                "project": str(self.root),
            },
            self.db,
        )
        self.assertTrue(saved["saved"])
        self.assertIn("TheekHai-only", str(kn.search("TheekHai-only", self.db, str(self.root))))
        other = Path(self.tmp.name) / "second-app"
        other.mkdir()
        kn.sync(other, self.db)
        other_results = kn.search("TheekHai-only", self.db, str(other))
        self.assertEqual(other_results["results"], [])

    def test_graph_edges_identify_duplicate_names_by_id(self):
        kn.sync(self.root, self.db)
        shared = kn.add_asset(
            {"kind": "framework", "name": "Same name", "summary": "Shared asset"}, self.db
        )
        local = legacy_asset(
            {
                "kind": "lesson",
                "name": "Same name",
                "summary": "Project note",
                "scope": "project",
                "project": str(self.root),
            },
            self.db,
        )
        target = kn.add_asset(
            {"kind": "framework", "name": "Other asset", "summary": "Target"}, self.db
        )
        result = kn.link_assets(
            {
                "source": "Same name",
                "target": "Other asset",
                "relation": "relates",
                "weight": 0.7,
                "evidence": "Project evidence",
                "project": str(self.root),
            },
            self.db,
        )
        self.assertTrue(result["linked"])
        graph = kn.get_master_graph(self.db, project=str(self.root))
        self.assertEqual(graph["edges"][0]["source_id"], local["id"])
        self.assertEqual(graph["edges"][0]["target_id"], target["id"])
        self.assertNotEqual(shared["id"], local["id"])

    def test_old_unscoped_edges_migrate_to_their_shared_project(self):
        legacy = Path(self.tmp.name) / "legacy.sqlite3"
        import sqlite3

        old = sqlite3.connect(legacy)
        old.executescript(
            """
          CREATE TABLE projects(id TEXT PRIMARY KEY, root TEXT NOT NULL, updated_at INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE assets(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, summary TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
          CREATE TABLE asset_projects(asset_id INTEGER NOT NULL, project_id TEXT NOT NULL, relation TEXT NOT NULL DEFAULT 'used_in', PRIMARY KEY(asset_id,project_id,relation));
          CREATE TABLE asset_links(source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, relation TEXT NOT NULL, weight REAL NOT NULL, evidence TEXT NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY(source_id,target_id,relation));
          INSERT INTO projects VALUES('D:\\LegacyApp','D:\\LegacyApp',1);
          INSERT INTO assets VALUES(1,'framework','Framework A','A','a','README.md',1);
          INSERT INTO assets VALUES(2,'library','Library B','B','b','README.md',1);
          INSERT INTO asset_projects VALUES(1,'D:\\LegacyApp','used_in');
          INSERT INTO asset_projects VALUES(2,'D:\\LegacyApp','used_in');
          INSERT INTO asset_links VALUES(1,2,'uses',0.9,'README.md evidence',1);
        """
        )
        old.close()
        migrated = kn.connect(legacy)
        edge = migrated.execute("SELECT scope,evidence FROM asset_link_evidence").fetchone()
        self.assertEqual(edge["scope"], "D:\\LegacyApp")
        self.assertEqual(edge["evidence"], "README.md evidence")
        migrated.close()

    def test_measurement_uses_actual_inputs_and_reports_net_tokens(self):
        result = kn.measure_task(
            {
                "task": "same change",
                "baseline_tokens": 1200,
                "network_tokens": 700,
                "indexing_tokens": 100,
            },
            self.db,
        )
        self.assertEqual(result["recorded_difference"], 400)
        self.assertIsNone(result["net_tokens_saved"])
        self.assertIsNone(result["percent_saved"])


if __name__ == "__main__":
    unittest.main()
