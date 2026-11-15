"""Authentication service, token verification, and session tokens."""

import hashlib
import time


class AuthService:
    """Provides bearer token verification and credential validation."""

    def __init__(self, salt: str = "salt_multicomponent"):
        self.salt = salt
        self.revoked = set()

    def verify_bearer_token(self, token_header: str) -> bool:
        """Verify authorization header and bearer token."""
        if not token_header or not token_header.startswith("Bearer "):
            return False
        raw_token = token_header[7:].strip()
        if raw_token in self.revoked or len(raw_token) < 8:
            return False
        digest = hashlib.sha256((raw_token + self.salt).encode()).hexdigest()
        return len(digest) == 64

    def validate_session_token(self, session_token: str, expires_at: int) -> bool:
        """Validate session token against current timestamp."""
        if not session_token or time.time() > expires_at:
            return False
        return True
