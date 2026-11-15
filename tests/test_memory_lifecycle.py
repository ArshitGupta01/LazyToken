"""Unit tests for Memory Quality Lifecycle & Governance (Milestone 5 / Feature 21)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import features
import kn


class TestMemoryLifecycleStateMachine(unittest.TestCase):
    """Unit tests for memory lifecycle state transitions (pending -> reviewed -> verified -> stale/superseded)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = kn.connect(Path(self.temp_dir.name) / "test.sqlite3")
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "storage.py").write_text("class Storage: pass\n", encoding="utf-8")
        kn.sync(self.repo, self.db)
        self.project = str(self.repo.resolve())

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_state_machine_transitions(self) -> None:
        # 1. Proposal starts in 'pending' state
        prop = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Storage Lock Policy",
                "summary": "Acquire lock before writing to storage",
                "task": "Concurrency safety",
                "evidence": "Observed write race",
                "paths": ["storage.py"],
            },
            self.db,
        )
        self.assertNotIn("error", prop)
        prop_id = prop["id"]
        self.assertEqual(prop.get("lifecycle_state"), "pending")

        h_pending = features.health(self.db, prop_id)
        self.assertEqual(h_pending["lifecycle_state"], "pending")

        # 2. Review and approve without verified flag -> 'reviewed'
        rev_reviewed = features.review(
            kn,
            {"project": self.project, "id": prop_id, "action": "approve", "verified": False},
            self.db,
        )
        self.assertEqual(rev_reviewed.get("lifecycle_state"), "reviewed")

        h_reviewed = features.health(self.db, prop_id)
        self.assertEqual(h_reviewed["lifecycle_state"], "reviewed")

        # 3. Create another proposal and approve with verified=True -> 'verified'
        prop2 = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Storage Flush Policy",
                "summary": "Flush buffer after every transaction",
                "task": "Data durability",
                "evidence": "Disk sync check",
                "paths": ["storage.py"],
            },
            self.db,
        )
        prop2_id = prop2["id"]
        rev_verified = features.review(
            kn,
            {"project": self.project, "id": prop2_id, "action": "approve", "verified": True},
            self.db,
        )
        self.assertEqual(rev_verified.get("lifecycle_state"), "verified")

        h_verified = features.health(self.db, prop2_id)
        self.assertEqual(h_verified["lifecycle_state"], "verified")

        # 4. Modifying evidence on disk makes health 'stale'
        (self.repo / "storage.py").write_text(
            "class Storage: def write(self): pass\n", encoding="utf-8"
        )
        kn.sync(self.repo, self.db)
        h_stale = features.health(self.db, prop2_id)
        self.assertEqual(h_stale["lifecycle_state"], "stale")

        # 5. Superseding transitions to 'superseded'
        rev_sup = features.review(
            kn,
            {"project": self.project, "id": prop_id, "action": "supersede"},
            self.db,
        )
        self.assertEqual(rev_sup.get("lifecycle_state"), "superseded")

        h_sup = features.health(self.db, prop_id)
        self.assertEqual(h_sup["lifecycle_state"], "superseded")

    def test_proposal_list_filter_by_lifecycle_state(self) -> None:
        p1 = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Lesson One",
                "summary": "Summary 1",
                "task": "Task 1",
                "evidence": "Evidence 1",
                "paths": ["storage.py"],
            },
            self.db,
        )
        p2 = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Lesson Two",
                "summary": "Summary 2",
                "task": "Task 2",
                "evidence": "Evidence 2",
                "paths": ["storage.py"],
            },
            self.db,
        )
        features.review(
            kn,
            {"project": self.project, "id": p1["id"], "action": "approve", "verified": True},
            self.db,
        )

        # Filter by verified
        res_v = features.proposal_list(
            kn, {"project": self.project, "lifecycle_state": "verified"}, self.db
        )
        ids_v = [p["id"] for p in res_v["proposals"]]
        self.assertIn(p1["id"], ids_v)
        self.assertNotIn(p2["id"], ids_v)

        # Filter by pending
        res_p = features.proposal_list(
            kn, {"project": self.project, "lifecycle_state": "pending"}, self.db
        )
        ids_p = [p["id"] for p in res_p["proposals"]]
        self.assertIn(p2["id"], ids_p)
        self.assertNotIn(p1["id"], ids_p)


class TestLegitimateCorrectionsWithReplacesId(unittest.TestCase):
    """Unit tests for replaces_id bypassing duplicate checks and superseding prior memory."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = kn.connect(Path(self.temp_dir.name) / "test.sqlite3")
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "net.py").write_text("def ping(): pass\n", encoding="utf-8")
        kn.sync(self.repo, self.db)
        self.project = str(self.repo.resolve())

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_replaces_id_bypasses_duplicate_and_supersedes_on_approval(self) -> None:
        # Original lesson
        orig = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Timeout Retry Policy",
                "summary": "Retry 3 times with exponential backoff",
                "task": "Network resilience",
                "evidence": "Dropped packets observed",
                "paths": ["net.py"],
            },
            self.db,
        )
        orig_id = orig["id"]
        features.review(
            kn,
            {"project": self.project, "id": orig_id, "action": "approve", "verified": True},
            self.db,
        )

        # Attempting to propose same name without replaces_id fails
        dup_attempt = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Timeout Retry Policy",
                "summary": "Retry 5 times with jitter",
                "task": "Network resilience updated",
                "evidence": "Dropped packets observed",
                "paths": ["net.py"],
            },
            self.db,
        )
        self.assertIn("error", dup_attempt)
        self.assertIn("already exists", dup_attempt["error"])

        # Proposing with replaces_id succeeds!
        corrective = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Timeout Retry Policy",
                "summary": "Retry 5 times with full jitter and decorrelated backoff",
                "task": "Network resilience updated",
                "evidence": "Avoid thundering herd",
                "paths": ["net.py"],
                "replaces_id": orig_id,
            },
            self.db,
        )
        self.assertNotIn("error", corrective)
        corr_id = corrective["id"]
        self.assertEqual(corrective["replaces_id"], orig_id)

        # On approving corrective lesson, original is automatically superseded
        rev = features.review(
            kn,
            {"project": self.project, "id": corr_id, "action": "approve", "verified": True},
            self.db,
        )
        self.assertEqual(rev.get("lifecycle_state"), "verified")

        # Check original memory status
        orig_health = features.health(self.db, orig_id)
        self.assertEqual(orig_health["lifecycle_state"], "superseded")


class TestEvidenceLinking(unittest.TestCase):
    """Unit tests for linking proposals to test execution evidence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = kn.connect(Path(self.temp_dir.name) / "test.sqlite3")
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "math_util.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
        kn.sync(self.repo, self.db)
        self.project = str(self.repo.resolve())

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_test_evidence_inserted_and_linked(self) -> None:
        prop = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Add Function Correctness",
                "summary": "Add returns correct arithmetic sum",
                "task": "Math correctness",
                "evidence": "Automated unit test passed",
                "paths": ["math_util.py"],
                "tests": [
                    {
                        "test_file": "test_math.py",
                        "test_command": "pytest test_math.py::test_add",
                        "exit_code": 0,
                        "digest": "abc123sha",
                        "output_snippet": "PASSED test_math.py::test_add",
                    }
                ],
            },
            self.db,
        )
        prop_id = prop["id"]
        rows = self.db.execute(
            "SELECT * FROM memory_test_evidence WHERE proposal_id=?", (prop_id,)
        ).fetchall()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["test_file"], "test_math.py")
        self.assertEqual(r["test_command"], "pytest test_math.py::test_add")
        self.assertEqual(r["exit_code"], 0)
        self.assertEqual(r["digest"], "abc123sha")
        self.assertIn("PASSED", r["output_snippet"])


class TestGovernanceControls(unittest.TestCase):
    """Unit tests for memory export, retention pruning, and granular deletion."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = kn.connect(Path(self.temp_dir.name) / "test.sqlite3")
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "api.py").write_text("def handle(): pass\n", encoding="utf-8")
        kn.sync(self.repo, self.db)
        self.project = str(self.repo.resolve())

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_export_memories(self) -> None:
        prop = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "API Rate Limit",
                "summary": "Enforce 100 req/min per IP",
                "task": "Rate limiting",
                "evidence": "API gateway logs",
                "paths": ["api.py"],
            },
            self.db,
        )
        exp = features.export_memories(kn, {"project": self.project}, self.db)
        self.assertEqual(exp["project"], self.project)
        self.assertGreaterEqual(exp["count"], 1)
        self.assertIsInstance(exp["json"], list)
        self.assertIn("API Rate Limit", exp["markdown"])

    def test_retention_memories_prunes_rejected_and_superseded_only(self) -> None:
        # Create 1 approved, 1 rejected, 1 superseded
        p1 = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Preserved Lesson",
                "summary": "Keep",
                "task": "T",
                "evidence": "E",
                "paths": ["api.py"],
            },
            self.db,
        )
        features.review(
            kn,
            {"project": self.project, "id": p1["id"], "action": "approve", "verified": True},
            self.db,
        )

        p2 = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Rejected Lesson",
                "summary": "Drop",
                "task": "T",
                "evidence": "E",
                "paths": ["api.py"],
            },
            self.db,
        )
        features.review(kn, {"project": self.project, "id": p2["id"], "action": "reject"}, self.db)

        p3 = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "Superseded Lesson",
                "summary": "Drop",
                "task": "T",
                "evidence": "E",
                "paths": ["api.py"],
            },
            self.db,
        )
        features.review(kn, {"project": self.project, "id": p3["id"], "action": "approve"}, self.db)
        features.review(
            kn, {"project": self.project, "id": p3["id"], "action": "supersede"}, self.db
        )

        ret_res = features.retention_memories(kn, {"project": self.project}, self.db)
        self.assertTrue(ret_res["preserved_approved"])
        self.assertEqual(ret_res["pruned_count"], 2)

        remaining_ids = [
            r[0]
            for r in self.db.execute(
                "SELECT id FROM memory_proposals WHERE project_id=?", (self.project,)
            ).fetchall()
        ]
        self.assertIn(p1["id"], remaining_ids)
        self.assertNotIn(p2["id"], remaining_ids)
        self.assertNotIn(p3["id"], remaining_ids)

    def test_delete_memory_never_deletes_source_files(self) -> None:
        p = features.propose(
            kn,
            {
                "project": self.project,
                "kind": "lesson",
                "name": "To Delete",
                "summary": "Del",
                "task": "T",
                "evidence": "E",
                "paths": ["api.py"],
            },
            self.db,
        )
        features.delete_memory(kn, {"project": self.project, "id": p["id"]}, self.db)

        # Memory record deleted
        row = self.db.execute("SELECT 1 FROM memory_proposals WHERE id=?", (p["id"],)).fetchone()
        self.assertIsNone(row)

        # Source code file MUST remain untouched!
        self.assertTrue(
            (self.repo / "api.py").exists(), "delete_memory must never touch user source files"
        )


class TestHumanReviewPolicyGuard(unittest.TestCase):
    """Unit tests ensuring agent/MCP callers cannot bypass human review."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = kn.connect(Path(self.temp_dir.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_mcp_tool_review_action_rejected(self) -> None:
        # kn.call simulates MCP tool dispatch
        res = kn.call("lazytoken", {"action": "review", "id": 1, "action_type": "approve"}, self.db)
        self.assertIn("error", res)
        self.assertIn("dashboard", res["error"].lower())


if __name__ == "__main__":
    unittest.main()
