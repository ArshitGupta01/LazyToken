import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import kn
import onboarding


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "Auth.py").write_text("class Auth: pass")
        self.profile = self.root / "profile"
        self.profile.mkdir()
        self.env = patch.dict(
            os.environ, {"KN_HOME": str(self.root / "data"), "LAZYTOKEN_DISABLE_AUTOWATCH": "1"}
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_preview_apply_preserves_unrelated_and_rollback_exact_bytes(self):
        config = self.profile / ".codex" / "config.toml"
        config.parent.mkdir()
        before = b'# preserved comment\nmodel = "fixture"\n[mcp_servers.other]\ncommand = "other"\n'
        config.write_bytes(before)
        plan = onboarding.preview(kn, str(self.project), ["codex", "antigravity"], self.profile)
        self.assertEqual(config.read_bytes(), before)
        self.assertFalse((self.root / "data").exists())
        result = onboarding.apply(kn, plan)
        parsed = tomllib.loads(config.read_text())
        self.assertEqual(parsed["model"], "fixture")
        self.assertIn("other", parsed["mcp_servers"])
        self.assertIn("lazytoken", parsed["mcp_servers"])
        self.assertTrue((self.root / "data/network.sqlite3").exists())
        restored = onboarding.rollback(result["receipt"])
        self.assertEqual(restored["restored"], 2)
        self.assertEqual(config.read_bytes(), before)
        self.assertFalse((self.profile / ".gemini/config/mcp_config.json").exists())

    def test_existing_entry_and_concurrent_edit_are_not_overwritten(self):
        config = self.profile / ".codex/config.toml"
        config.parent.mkdir()
        before = b'[mcp_servers.lazytoken]\ncommand = "custom"\n'
        config.write_bytes(before)
        plan = onboarding.preview(kn, str(self.project), ["codex"], self.profile)
        self.assertEqual(plan["changes"][0]["status"], "existing_entry_preserved")
        onboarding.apply(kn, plan)
        self.assertEqual(config.read_bytes(), before)
        plan = onboarding.preview(kn, str(self.project), ["antigravity"], self.profile)
        path = Path(plan["changes"][0]["path"])
        path.parent.mkdir(parents=True)
        path.write_text('{"other":true}')
        with self.assertRaises(ValueError):
            onboarding.apply(kn, plan)

    def test_rollback_refuses_newer_settings(self):
        result = onboarding.apply(
            kn, onboarding.preview(kn, str(self.project), ["codex"], self.profile)
        )
        config = self.profile / ".codex/config.toml"
        config.write_text(config.read_text() + "\n# newer edit\n")
        with self.assertRaises(ValueError):
            onboarding.rollback(result["receipt"])
        self.assertIn("newer edit", config.read_text())

    def test_real_local_handshake_uses_only_isolated_store(self):
        self.assertTrue(onboarding.connection_test(kn)["mcp_initialize"])

    def test_repeated_client_selection_is_idempotent_and_can_roll_back(self):
        plan = onboarding.preview(
            kn, str(self.project), ["codex", "codex", "antigravity", "antigravity"], self.profile
        )
        self.assertEqual(len(plan["changes"]), 2)
        result = onboarding.apply(kn, plan)
        self.assertEqual(onboarding.rollback(result["receipt"])["restored"], 2)

    def test_invalid_client_configuration_is_reported_instead_of_crashing(self):
        path = self.profile / ".gemini/config/mcp_config.json"
        path.parent.mkdir(parents=True)
        path.write_text("[]")
        with patch("onboarding.Path.home", return_value=self.profile):
            clients = onboarding.diagnose(kn)["clients"]
        self.assertFalse(
            next(client for client in clients if client["client"] == "antigravity")[
                "configuration_valid"
            ]
        )


if __name__ == "__main__":
    unittest.main()
