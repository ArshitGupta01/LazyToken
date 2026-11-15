import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DiagnosticsCliTests(unittest.TestCase):
    def test_doctor_formats_preserve_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {**os.environ, "KN_HOME": temp, "LAZYTOKEN_DISABLE_AUTOWATCH": "1"}
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / "kn.py"), "doctor"]
            default = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
            data = json.loads(default.stdout)
            explicit = subprocess.run(
                [*command, "--format", "json"], env=env, capture_output=True, text=True, check=True
            )
            self.assertEqual(
                json.loads(explicit.stdout)["database_exists"], data["database_exists"]
            )
            for output_format in ("text", "table"):
                result = subprocess.run(
                    [*command, "--format", output_format],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertIn("database_exists", result.stdout)
                self.assertIn("false", result.stdout)
                self.assertIn("repairs", result.stdout)


if __name__ == "__main__":
    unittest.main()
