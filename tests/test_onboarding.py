import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import kn
import onboarding


class SetupTests(unittest.TestCase):
    def test_managed_root_recognizes_new_and_legacy_markers(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        executable = root / "versions" / "v1" / "TokSmart.exe"
        executable.parent.mkdir(parents=True)
        with (
            patch.object(onboarding.sys, "frozen", True, create=True),
            patch.object(onboarding.sys, "executable", str(executable)),
        ):
            self.assertIsNone(onboarding.managed_root())
            for marker in (".toksmart-install", ".lazytoken-install"):
                path = root / marker
                path.touch()
                self.assertEqual(onboarding.managed_root(), root.resolve())
                path.unlink()

    def test_client_cleanup_recognizes_new_and_legacy_markers(self):
        root = self.root / "managed"
        root.mkdir()
        with self.assertRaises(ValueError):
            onboarding.remove_managed_clients(kn, root)
        for marker in (".toksmart-install", ".lazytoken-install"):
            path = root / marker
            path.touch()
            self.assertEqual(
                onboarding.remove_managed_clients(kn, root)["removed_managed_entries"], 0
            )
            path.unlink()

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
        self.assertIn("toksmart", parsed["mcp_servers"])
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
        result = onboarding.connection_test(kn)
        self.assertTrue(result["mcp_initialize"])
        self.assertGreater(result["tools_available"], 0)

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
    def test_codex_cli_reads_generated_registration_in_isolated_profile(self):
        plan = onboarding.preview(kn, str(self.project), ["codex"], self.profile)
        onboarding.apply(kn, plan)
        env = {**os.environ, "CODEX_HOME": str(self.profile / ".codex")}
        result = subprocess.run(
            ["codex", "mcp", "get", "--json", "toksmart"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        transport = json.loads(result.stdout)["transport"]
        self.assertEqual(transport["command"], plan["server"]["command"])
        self.assertEqual(transport["args"], plan["server"]["args"])
        self.assertEqual(transport["env"]["KN_HOME"], plan["server"]["env"]["KN_HOME"])

    def test_connection_test_reports_missing_launcher(self):
        with patch(
            "onboarding.entry",
            return_value={"command": "missing-lazytoken-executable", "args": [], "env": {}},
        ):
            result = onboarding.connection_test(kn)
        self.assertFalse(result["mcp_initialize"])
        self.assertIn("error", result)

    def test_edit_during_indexing_is_not_overwritten(self):
        path = self.profile / ".codex/config.toml"
        path.parent.mkdir()
        path.write_text('model = "fixture"\n')
        plan = onboarding.preview(kn, str(self.project), ["codex"], self.profile)
        original_sync = kn.sync
        edited = b'model = "updated-during-indexing"\n'

        def sync_and_edit(*args, **kwargs):
            result = original_sync(*args, **kwargs)
            path.write_bytes(edited)
            return result

        with patch("kn.sync", side_effect=sync_and_edit):
            with self.assertRaisesRegex(ValueError, "changed during setup"):
                onboarding.apply(kn, plan)
        self.assertEqual(path.read_bytes(), edited)
        self.assertFalse(list(path.parent.glob("*.bak")))

    def test_edit_to_later_client_preserves_edit_and_reverts_earlier_write(self):
        plan = onboarding.preview(kn, str(self.project), ["codex", "antigravity"], self.profile)
        first, second = [Path(change["path"]) for change in plan["changes"]]
        original_write = onboarding.atomic_write
        edited = b'{"newPreference": true}'

        def write_and_edit(path, data):
            original_write(path, data)
            if Path(path) == first:
                second.parent.mkdir(parents=True, exist_ok=True)
                second.write_bytes(edited)

        with patch("onboarding.atomic_write", side_effect=write_and_edit):
            with self.assertRaisesRegex(ValueError, "changed during setup"):
                onboarding.apply(kn, plan)
        self.assertFalse(first.exists())
        self.assertEqual(second.read_bytes(), edited)

    def test_failed_receipt_restores_existing_bytes_and_original_file_absence(self):
        first = self.profile / ".codex/config.toml"
        first.parent.mkdir()
        before = b'# original\nmodel = "fixture"\n'
        first.write_bytes(before)
        plan = onboarding.preview(kn, str(self.project), ["codex", "antigravity"], self.profile)
        original_write = onboarding.atomic_write

        def fail_receipt(path, data):
            if Path(path).name.startswith("setup-"):
                raise OSError("synthetic receipt failure")
            original_write(path, data)

        with patch("onboarding.atomic_write", side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, "synthetic receipt failure"):
                onboarding.apply(kn, plan)
        self.assertEqual(first.read_bytes(), before)
        self.assertFalse(Path(plan["changes"][1]["path"]).exists())
        self.assertFalse(list(kn.data_root().glob("setup-*.json")))

    def test_nested_client_configuration_shape_is_validated_in_preview_and_doctor(self):
        cases = {
            "codex": [
                'mcp_servers = "lazytoken"',
                "mcp_servers = []",
                '[mcp_servers]\nlazytoken = "invalid"',
            ],
            "antigravity": [
                '{"mcpServers":"lazytoken"}',
                '{"mcpServers":[]}',
                '{"mcpServers":null}',
                '{"mcpServers":{"lazytoken":null}}',
                '{"mcpServers":{"lazytoken":[]}}',
            ],
        }
        for client, contents in cases.items():
            path = onboarding.configuration_path(client, self.profile)
            path.parent.mkdir(parents=True, exist_ok=True)
            for text in contents:
                with self.subTest(client=client, contents=text):
                    path.write_text(text)
                    with self.assertRaises(ValueError):
                        onboarding.preview(kn, str(self.project), [client], self.profile)
                    with patch("onboarding.Path.home", return_value=self.profile):
                        status = next(
                            item
                            for item in onboarding.diagnose(kn)["clients"]
                            if item["client"] == client
                        )
                    self.assertFalse(status["registered"])
                    self.assertFalse(status["configuration_valid"])
                    self.assertEqual(path.read_text(), text)

    def test_existing_remote_registration_is_preserved_and_reported(self):
        path = onboarding.configuration_path("antigravity", self.profile)
        path.parent.mkdir(parents=True)
        before = b'{"mcpServers":{"lazytoken":{"url":"http://localhost:12345/mcp"}}}'
        path.write_bytes(before)
        plan = onboarding.preview(kn, str(self.project), ["antigravity"], self.profile)
        self.assertEqual(plan["changes"][0]["status"], "existing_entry_preserved")
        self.assertFalse(plan["changes"][0]["matches_suggested_entry"])
        with patch("onboarding.Path.home", return_value=self.profile):
            status = next(
                item
                for item in onboarding.diagnose(kn)["clients"]
                if item["client"] == "antigravity"
            )
        self.assertTrue(status["registered"])
        self.assertTrue(status["configuration_valid"])
        self.assertEqual(path.read_bytes(), before)

    def test_preview_reports_whether_existing_entry_matches_suggested_setup(self):
        path = onboarding.configuration_path("antigravity", self.profile)
        path.parent.mkdir(parents=True)
        original = json.dumps({"mcpServers": {"lazytoken": onboarding.entry(kn)}}).encode()
        path.write_bytes(original)
        plan = onboarding.preview(kn, str(self.project), ["antigravity", "codex"], self.profile)
        self.assertTrue(plan["changes"][0]["matches_suggested_entry"])
        self.assertIsNone(plan["changes"][1]["matches_suggested_entry"])
        self.assertEqual(path.read_bytes(), original)

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
