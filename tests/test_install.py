import os
import json
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "manage_install.ps1"


@unittest.skipUnless(os.name == "nt", "Windows installation helper")
class InstallLifecycleTests(unittest.TestCase):
    def run_install(self, *args):
        if "-Source" in args:
            source = Path(args[args.index("-Source") + 1])
            files = {
                p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in source.rglob("*")
                if p.is_file() and p.name != "release-manifest.json"
            }
            (source / "release-manifest.json").write_text(
                json.dumps({"format": "lazytoken-files-v1", "files": files})
            )
        return subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                *map(str, args),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_install_upgrade_rollback_uninstall_preserves_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "LazyToken.exe").write_bytes(b"v1")
            target = root / "installed"
            data = root / "network.sqlite3"
            data.write_bytes(b"keep")
            first = self.run_install(
                "-Action", "install", "-InstallRoot", target, "-Source", source
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            version1 = (target / "current.txt").read_text()
            (source / "LazyToken.exe").write_bytes(b"v2")
            upgrade = self.run_install(
                "-Action", "upgrade", "-InstallRoot", target, "-Source", source
            )
            self.assertEqual(upgrade.returncode, 0, upgrade.stderr)
            version2 = (target / "current.txt").read_text()
            self.assertNotEqual(version1, version2)
            rollback = self.run_install("-Action", "rollback", "-InstallRoot", target)
            self.assertEqual(rollback.returncode, 0, rollback.stderr)
            self.assertEqual((target / "current.txt").read_text(), version1)
            denied = self.run_install("-Action", "uninstall", "-InstallRoot", target)
            self.assertNotEqual(denied.returncode, 0)
            self.assertTrue(target.exists())
            remove = self.run_install(
                "-Action", "uninstall", "-InstallRoot", target, "-ConfirmUninstall"
            )
            self.assertEqual(remove.returncode, 0, remove.stderr)
            self.assertFalse(target.exists())
            self.assertEqual(data.read_bytes(), b"keep")

    def test_refuses_unmanaged_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "LazyToken.exe").write_bytes(b"v1")
            target = root / "unmanaged"
            target.mkdir()
            (target / "keep.txt").write_text("keep")
            result = self.run_install(
                "-Action", "install", "-InstallRoot", target, "-Source", source
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((target / "keep.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
