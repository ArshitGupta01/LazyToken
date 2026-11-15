"""Independent acceptance checks: invoke from outside an agent's fixture copy."""

import argparse
import copy
from datetime import datetime, timedelta, timezone
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture")
    parser.add_argument("--follow-up", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, args.fixture)
    from handlers import primary, secondary
    from store import SessionStore

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sessions = {
        "expired": {"user": "Ada", "expires_at": now - timedelta(seconds=1)},
        "boundary": {"user": "Ada", "expires_at": now},
        "valid": {"user": "Ada", "expires_at": now + timedelta(seconds=1)},
        "unlimited": {"user": "Ada"},
    }
    before = copy.deepcopy(sessions)
    store = SessionStore(sessions)
    for handler in (primary, secondary) if args.follow_up else (primary,):
        for token in ("expired", "boundary", "missing"):
            assert handler(store, token, now) == (401, "unauthorized"), token
        for token in ("valid", "unlimited"):
            assert handler(store, token, now) == (200, "Ada"), token
    assert sessions == before, "authentication modified the store"
    print("Session acceptance passed")


if __name__ == "__main__":
    main()
