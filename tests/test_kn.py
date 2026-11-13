import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kn


class KnowledgeNetworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "TheekHai"
        self.root.mkdir()
        (self.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (self.root / "README.md").write_text("TheekHai project pilot\n", encoding="utf-8")
        (self.root / "src.kt").write_text("package demo\nimport demo.core.Api\nclass AccountStore {\n fun lookupAccount(id: String) {}\n}\n", encoding="utf-8")
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
        (self.root/"nav.kt").write_text("class SidebarNavItem {}\nclass ViteServer {}\n",encoding="utf-8")
        kn.sync(self.root,self.db)
        result=kn.search("Vite TypeScript",self.db,str(self.root))
        names=[r["name"] for r in result["results"] if r["type"]=="symbol"]
        self.assertIn("ViteServer",names)
        self.assertNotIn("SidebarNavItem",names)

    def test_assets_and_budget_estimate(self):
        saved = kn.add_asset({"kind":"pattern","name":"small-context","summary":"Retrieve only task-relevant context","tags":"tokens"}, self.db)
        self.assertTrue(saved["saved"])
        result = kn.search("small-context", self.db)
        self.assertEqual(result["results"][0]["type"], "asset")
        self.assertGreaterEqual(result["estimated_tokens"], 1)

    def test_seeded_master_asset_links_to_project(self):
        kn.sync(self.root, self.db)
        seeded = kn.seed_project(self.root, self.db)
        self.assertEqual(seeded["seeded"], 6)
        self.assertEqual(seeded["linked"], 6)
        result = kn.search("Ktor backend", self.db)
        self.assertEqual(result["results"][0]["name"], "Ktor")
        self.assertEqual(result["results"][0]["used_in"], ["TheekHai"])
        graph=kn.get_master_graph(self.db)
        self.assertEqual(graph["node_count"],6)
        self.assertEqual(graph["edge_count"],6)

    def test_search_spreads_activation_to_related_assets(self):
        kn.sync(self.root, self.db)
        kn.seed_project(self.root, self.db)
        result=kn.search("Vite TypeScript",self.db,str(self.root))
        names=[r["name"] for r in result["results"] if r["type"]=="asset"]
        self.assertEqual(names[:2],["Vite + TypeScript","Ktor"])
        self.assertLess(result["results"][1]["activation"],1.0)

    def test_new_project_does_not_inherit_theekhai_links_or_seed_assets(self):
        kn.sync(self.root,self.db)
        kn.seed_project(self.root,self.db)
        other=Path(self.tmp.name)/"new-app"
        other.mkdir()
        (other/"README.md").write_text("New app",encoding="utf-8")
        kn.sync(other,self.db)
        seed=kn.seed_project(other,self.db)
        self.assertEqual(seed["asset_edges"],0)
        other_search=kn.search("Vite TypeScript",self.db,str(other))
        names=[r["name"] for r in other_search["results"] if r["type"]=="asset"]
        self.assertEqual(names,["Vite + TypeScript"])
        other_graph=kn.get_master_graph(self.db,project=str(other))
        self.assertEqual(other_graph["edge_count"],0)

    def test_project_scoped_lesson_stays_in_its_project(self):
        kn.sync(self.root,self.db)
        saved=kn.add_asset({"kind":"lesson","name":"TheekHai-only","summary":"Project-specific lesson","scope":"project","project":str(self.root)},self.db)
        self.assertTrue(saved["saved"])
        self.assertIn("TheekHai-only",str(kn.search("TheekHai-only",self.db,str(self.root))))
        other=Path(self.tmp.name)/"second-app"
        other.mkdir()
        kn.sync(other,self.db)
        other_results=kn.search("TheekHai-only",self.db,str(other))
        self.assertEqual(other_results["results"],[])

    def test_old_unscoped_edges_migrate_to_their_shared_project(self):
        legacy=Path(self.tmp.name)/"legacy.sqlite3"
        import sqlite3
        old=sqlite3.connect(legacy)
        old.executescript("""
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
        """)
        old.close()
        migrated=kn.connect(legacy)
        edge=migrated.execute("SELECT scope,evidence FROM asset_link_evidence").fetchone()
        self.assertEqual(edge["scope"],"D:\\LegacyApp")
        self.assertEqual(edge["evidence"],"README.md evidence")
        migrated.close()

    def test_measurement_uses_actual_inputs_and_reports_net_tokens(self):
        result = kn.measure_task({"task":"same change","baseline_tokens":1200,"network_tokens":700,"indexing_tokens":100}, self.db)
        self.assertEqual(result["net_tokens_saved"], 400)
        self.assertEqual(result["percent_saved"], 33.3)


if __name__ == "__main__":
    unittest.main()
