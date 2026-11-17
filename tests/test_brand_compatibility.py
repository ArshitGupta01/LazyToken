"""Keep the TokSmart branding migration inventory structured and reviewable."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "docs" / "BRAND_COMPATIBILITY.json"
VALID_CATEGORIES = {"compatibility-only", "migration-contract", "user-facing-bug"}


class BrandCompatibilityInventoryTests(unittest.TestCase):
    def test_inventory_has_a_canonical_identity_and_complete_categories(self):
        data = json.loads(INVENTORY.read_text(encoding="utf-8"))

        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["canonical_product"]["display_name"], "TokSmart")
        self.assertEqual(data["canonical_product"]["cli"], "toksmart")

        entries = data["legacy_identifiers"]
        self.assertEqual({entry["id"] for entry in entries}, {
            "lazytoken-cli-and-mcp",
            "repomind-cli-and-browser",
            "lazytoken-storage-and-artifact-format",
            "repomind-storage",
            "theekhai-knowledge-network-storage",
            "public-branding-leaks",
        })
        for entry in entries:
            self.assertIn(entry["category"], VALID_CATEGORIES)
            self.assertTrue(entry["identifier"])
            self.assertTrue(entry["reason"])
            self.assertEqual(entry["preferred_replacement"], "TokSmart")
            self.assertTrue(entry["removal_requires"])

    def test_each_compatibility_or_migration_contract_has_boundaries(self):
        data = json.loads(INVENTORY.read_text(encoding="utf-8"))
        protected = [
            entry
            for entry in data["legacy_identifiers"]
            if entry["category"] in {"compatibility-only", "migration-contract"}
        ]
        self.assertTrue(protected)
        for entry in protected:
            self.assertTrue(entry.get("allowed_surfaces"))
            self.assertIn("migration", entry["removal_requires"].lower())

    def test_test_matrix_covers_identity_commands_storage_and_release_artifacts(self):
        data = json.loads(INVENTORY.read_text(encoding="utf-8"))
        matrix = {item["id"]: item for item in data["test_matrix"]}
        self.assertEqual(
            set(matrix),
            {
                "canonical-identity",
                "legacy-cli-compatibility",
                "legacy-storage-safety",
                "release-artifact-safety",
            },
        )
        for item in matrix.values():
            self.assertTrue(item["assertion"])
            self.assertTrue(item["verification"])


if __name__ == "__main__":
    unittest.main()
