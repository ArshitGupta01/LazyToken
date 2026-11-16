import tempfile
import unittest
from pathlib import Path

import features
import kn


class MCPMemoryGuardTests(unittest.TestCase):
    def test_mcp_cannot_delete_memories_and_missing_delete_releases_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            (root / "code.py").write_text("def task(): pass\n", encoding="utf-8")
            db = kn.connect(Path(tmp) / "network.sqlite3")
            try:
                kn.sync(root, db)
                project = str(root.resolve())
                proposal = features.propose(
                    kn,
                    {
                        "project": project,
                        "kind": "lesson",
                        "name": "Remember task",
                        "summary": "Use task",
                        "task": "Find task",
                        "evidence": "Source",
                        "paths": ["code.py"],
                    },
                    db,
                )
                self.assertEqual(proposal["status"], "pending")
                db.execute(
                    "UPDATE memory_proposals SET status='rejected' WHERE id=?", (proposal["id"],)
                )
                db.commit()
                for action in ("delete_memory", "retention_memories"):
                    with self.subTest(action=action):
                        result = kn.call(
                            "lazytoken",
                            {
                                "action": action,
                                "payload": {"project": project, "id": proposal["id"]},
                            },
                            db,
                        )
                        self.assertIn("error", result)
                        self.assertEqual(
                            db.execute("SELECT count(*) FROM memory_proposals").fetchone()[0], 1
                        )
                self.assertIn(
                    "error", features.delete_memory(kn, {"project": project, "id": -1}, db)
                )
                self.assertFalse(db.in_transaction)
                self.assertTrue(
                    features.delete_memory(kn, {"project": project, "id": proposal["id"]}, db)[
                        "deleted"
                    ]
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
