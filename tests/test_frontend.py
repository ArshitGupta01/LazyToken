"""Exercise dashboard races with Node's built-in runner; no browser dependencies."""

import os
from pathlib import Path
import shutil
import subprocess
import unittest


class FrontendTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("node"), "Node is optional; needed only for dashboard development tests"
    )
    def test_workspace_requests(self):
        result = subprocess.run(
            [shutil.which("node"), "--test", str(Path(__file__).with_name("workspace.test.cjs"))],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
