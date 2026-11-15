import unittest
from datetime import datetime, timezone
from handlers import primary, secondary
from store import SessionStore


class SessionTests(unittest.TestCase):
    def test_known_and_unknown(self):
        store = SessionStore({"abc": {"user": "Ada"}})
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for handler in (primary, secondary):
            self.assertEqual(handler(store, "abc", now), (200, "Ada"))
            self.assertEqual(handler(store, "missing", now), (401, "unauthorized"))


if __name__ == "__main__":
    unittest.main()
