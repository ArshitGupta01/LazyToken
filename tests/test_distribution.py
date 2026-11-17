import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import kn
import migration

ROOT = Path(kn.__file__).parent


class StorageAndCommands(unittest.TestCase):
    def test_fresh_default_and_explicit_migration_preserve_source(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"LOCALAPPDATA": temp, "KN_HOME": ""}),
        ):
            legacy = Path(temp) / "TheekHai/KnowledgeNetwork"
            legacy.mkdir(parents=True)
            source = legacy / "network.sqlite3"
            db = sqlite3.connect(source)
            db.execute("CREATE TABLE evidence(project TEXT, fact TEXT)")
            db.execute("INSERT INTO evidence VALUES('project-a','fixture')")
            db.commit()
            db.close()
            before = source.read_bytes()
            destination = Path(temp) / "TokSmart/network.sqlite3"
            self.assertEqual(kn.data_root(), destination.parent)
            self.assertIn(legacy, kn.legacy_data_roots())
            self.assertTrue(migration.migrate(source, destination)["preview"])
            self.assertFalse(destination.exists())
            result = migration.migrate(source, destination, True)
            self.assertTrue(result["migrated"])
            self.assertEqual(source.read_bytes(), before)
            db = sqlite3.connect(destination)
            self.assertEqual(db.execute("SELECT project FROM evidence").fetchone()[0], "project-a")
            db.close()
            self.assertIn("error", migration.migrate(source, destination, True))
            self.assertTrue(migration.rollback(result["receipt"])["rolled_back"])
            self.assertFalse(destination.exists())
            self.assertTrue(Path(result["backup"]).exists())

    def test_migration_refuses_to_rollback_newer_data(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "old.sqlite3"
            db = sqlite3.connect(source)
            db.execute("CREATE TABLE marker(value TEXT)")
            db.commit()
            db.close()
            destination = Path(temp) / "new/network.sqlite3"
            result = migration.migrate(source, destination, True)
            db = sqlite3.connect(destination)
            db.execute("INSERT INTO marker VALUES('new')")
            db.commit()
            db.close()
            self.assertIn("error", migration.rollback(result["receipt"]))
            self.assertTrue(destination.exists())

    def test_explicit_data_deletion_is_default_only_and_preserves_neighbors(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"LOCALAPPDATA": temp, "KN_HOME": ""}),
        ):
            db = kn.connect()
            db.close()
            root = kn.default_data_root()
            neighbor = root / "keep.txt"
            neighbor.write_text("keep")
            self.assertIn("error", migration.delete_default_store(kn, str(Path(temp) / "other")))
            wal = Path(str(root / "network.sqlite3") + "-wal")
            wal.touch()
            self.assertIn("error", migration.delete_default_store(kn, str(root)))
            wal.unlink()
            self.assertIn("deleted", migration.delete_default_store(kn, str(root)))
            self.assertEqual(neighbor.read_text(), "keep")

    def test_explicit_data_deletion_refuses_legacy_default(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"LOCALAPPDATA": temp, "KN_HOME": ""}),
        ):
            legacy = Path(temp) / "LazyToken"
            legacy.mkdir()
            connection = sqlite3.connect(legacy / "network.sqlite3")
            connection.execute("CREATE TABLE lazytoken_migrations(version INTEGER)")
            connection.commit()
            connection.close()
            self.assertEqual(kn.default_data_root(), legacy)
            self.assertIn("error", migration.delete_default_store(kn, str(legacy)))
            self.assertTrue((legacy / "network.sqlite3").is_file())

    def test_init_reruns_without_seeds_and_sync_selected_only(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {
                **os.environ,
                "LOCALAPPDATA": temp,
                "KN_HOME": "",
                "LAZYTOKEN_DISABLE_AUTOWATCH": "1",
            }

            def run(*args):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "kn.py"), *args],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            for _ in range(2):
                self.assertTrue(run("init")["initialized"])
            db = sqlite3.connect(Path(temp) / "TokSmart/network.sqlite3")
            self.assertEqual(db.execute("SELECT count(*) FROM projects").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM assets").fetchone()[0], 0)
            db.close()
            project = Path(temp) / "selected"
            project.mkdir()
            (project / "a.py").write_text("class A: pass")
            run("add", str(project))
            self.assertEqual(len(run("sync")["projects"]), 1)
            self.assertEqual(run("seed", str(project))["seeded"], 0)
            self.assertIn("installation_integrity", run("doctor"))
            self.assertFalse(run("setup", "--project", str(project))["clients"])


@unittest.skipUnless(os.name == "nt", "Windows release installation")
class InstallerSecurity(unittest.TestCase):
    def test_release_build_rejects_unsupported_openssl(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "python.cmd").write_text(
                '@if exist "%~dp0first" exit /b 1\r\n@type nul > "%~dp0first"\r\n@exit /b 0\r\n',
                encoding="ascii",
            )
            output = root / "package"
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"]}
            shell = (
                Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            )
            result = subprocess.run(
                [
                    str(shell),
                    "-NoProfile",
                    "-File",
                    str(ROOT / "build_release.ps1"),
                    "-Output",
                    str(output),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires OpenSSL 3.5.9", result.stderr)
            self.assertFalse(output.exists())

    def test_release_build_rejects_unsupported_python_before_writing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "python.cmd").write_text("@exit /b 1\r\n", encoding="ascii")
            output = root / "package"
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"]}
            shell = (
                Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            )
            result = subprocess.run(
                [
                    str(shell),
                    "-NoProfile",
                    "-File",
                    str(ROOT / "build_release.ps1"),
                    "-Output",
                    str(output),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("64-bit Windows Python 3.14.10", result.stderr)
            self.assertFalse(output.exists())

    def command(self, script, *args):
        return subprocess.run(
            ["powershell", "-NoProfile", "-File", str(ROOT / script), *map(str, args)],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def fixture(self, root):
        source = root / "source"
        source.mkdir()
        (source / "LazyToken.exe").write_bytes(b"fixture-only")
        self.manifest(source)
        return source

    def manifest(self, source):
        files = {
            p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source.rglob("*")
            if p.is_file() and p.name != "release-manifest.json"
        }
        (source / "release-manifest.json").write_text(
            json.dumps({"format": "lazytoken-files-v1", "files": files})
        )

    def test_checksum_and_archive_traversal_refused_before_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "unsafe.zip"
            target = root / "install"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("../escaped.txt", "fixture")
            bad = self.command(
                "install.ps1",
                "-PackagePath",
                archive,
                "-ExpectedSha256",
                "0" * 64,
                "-InstallRoot",
                target,
                "-NoPathRegistration",
            )
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("SHA-256", bad.stderr)
            self.assertFalse(target.exists())
            trusted = hashlib.sha256(archive.read_bytes()).hexdigest()
            unsafe = self.command(
                "install.ps1",
                "-PackagePath",
                archive,
                "-ExpectedSha256",
                trusted,
                "-InstallRoot",
                target,
                "-NoPathRegistration",
            )
            self.assertNotEqual(unsafe.returncode, 0)
            self.assertIn("Unsafe archive", unsafe.stderr)
            self.assertFalse((root / "escaped.txt").exists())

    def test_publisher_pin_refuses_unsigned_package_before_helper_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "unsigned.zip"
            target = root / "installed"
            with zipfile.ZipFile(archive, "w") as z:
                for name in (
                    "install.ps1",
                    "LazyToken/release-manifest.json",
                    "LazyToken/LazyToken.exe",
                    "LazyToken/_internal/python311.dll",
                    "LazyToken/_internal/index.html",
                    "LazyToken/_internal/vendor/three.module.js",
                ):
                    z.writestr(name, "fixture only")
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            result = self.command(
                "install.ps1",
                "-PackagePath",
                archive,
                "-ExpectedSha256",
                checksum,
                "-PublisherThumbprint",
                "0" * 40,
                "-InstallRoot",
                target,
                "-NoPathRegistration",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(target.exists())
            self.assertTrue(
                "signature" in result.stderr.lower() or "authenticode" in result.stderr.lower(),
                result.stderr,
            )

    def test_retry_after_interrupted_new_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.fixture(root)
            target = root / "installed"
            target.mkdir()
            (target / ".lazytoken-install").write_text("LazyToken-managed-install-v1")
            partial = target / "versions" / ("a" * 32)
            partial.mkdir(parents=True)
            (partial / "incomplete.txt").write_text("fixture")
            result = self.command("manage_install.ps1", "-Source", source, "-InstallRoot", target)
            self.assertEqual(result.returncode, 0, result.stderr)
            current = (target / "current.txt").read_text()
            self.assertNotEqual(current, "a" * 32)
            self.assertTrue((target / "versions" / current / "LazyToken.exe").exists())

    def test_path_ownership_and_failed_upgrade_preserve_prior_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.fixture(root)
            target = root / "installed"
            pathfile = root / "user-path.txt"
            pathfile.write_text("C:\\Other;%USERPROFILE%\\bin")
            installed = self.command(
                "manage_install.ps1",
                "-Source",
                source,
                "-InstallRoot",
                target,
                "-RegisterPath",
                "-PathStateFile",
                pathfile,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            version = (target / "current.txt").read_text()
            self.assertIn(str((target / "bin").resolve()), pathfile.read_text())
            (source / "LazyToken.exe").write_bytes(b"tampered")
            denied = self.command(
                "manage_install.ps1",
                "-Action",
                "upgrade",
                "-Source",
                source,
                "-InstallRoot",
                target,
            )
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual((target / "current.txt").read_text(), version)
            pathfile.write_text(pathfile.read_text() + ";C:\\New")
            removed = self.command(
                "manage_install.ps1",
                "-Action",
                "uninstall",
                "-InstallRoot",
                target,
                "-ConfirmUninstall",
            )
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertEqual(pathfile.read_text(), "C:\\Other;%USERPROFILE%\\bin;C:\\New")


if __name__ == "__main__":
    unittest.main()
