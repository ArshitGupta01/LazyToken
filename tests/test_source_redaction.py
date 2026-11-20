import tempfile
import unittest
from pathlib import Path

import kn


class SourceRedactionTests(unittest.TestCase):
    def test_credential_urls_and_unquoted_secrets_are_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            (root / "config.yml").write_text(
                "database: postgresql://alice:fake%40password@db.example/app\n"
                "password: fake-plain-password\n"
                "url: https://example.com/docs\n",
                encoding="utf-8",
            )
            db = kn.connect(Path(temp) / "test.sqlite3")
            try:
                kn.sync(root, db)
                result = kn.call(
                    "inspect_source_range",
                    {"project": str(root), "path": "config.yml", "start_line": 1, "end_line": 3},
                    db,
                )
                self.assertEqual(result["lines"][0]["text"], "[redacted: possible credential]")
                self.assertEqual(result["lines"][1]["text"], "[redacted: possible credential]")
                self.assertEqual(result["lines"][2]["text"], "url: https://example.com/docs")
                self.assertNotIn("fake%40password", str(result))
                self.assertNotIn("fake-plain-password", str(result))
            finally:
                db.close()

    def test_temporary_aws_and_fine_grained_github_credential_patterns(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            aws_placeholder = "ASIA" + "0" * 16
            github_placeholder = "github_pat_" + "0" * 80
            (root / "sample.py").write_text(
                f'# {aws_placeholder}\n# {github_placeholder}\nprint("hello")\n',
                encoding="utf-8",
            )
            db = kn.connect(Path(temp) / "test.sqlite3")
            try:
                kn.sync(root, db)
                result = kn.call(
                    "inspect_source_range",
                    {"project": str(root), "path": "sample.py", "start_line": 1, "end_line": 3},
                    db,
                )
                self.assertEqual(
                    [line["text"] for line in result["lines"]],
                    [
                        "[redacted: possible credential]",
                        "[redacted: possible credential]",
                        'print("hello")',
                    ],
                )
            finally:
                db.close()
