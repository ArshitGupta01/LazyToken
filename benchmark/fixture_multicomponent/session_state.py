"""Persistent task-session state tracking, breadcrumbs, and recovery."""


class SessionStateManager:
    """Persists task session state, recovery breadcrumbs, and active goals."""

    def __init__(self):
        self.sessions = {}

    def save_checkpoint(self, session_id: str, goal: str, breadcrumbs: list[str]) -> dict:
        """Persist task session checkpoint state."""
        checkpoint = {
            "session_id": session_id,
            "goal": goal,
            "breadcrumbs": list(breadcrumbs),
            "status": "active",
        }
        self.sessions[session_id] = checkpoint
        return checkpoint

    def recover_breadcrumbs(self, session_id: str) -> list[str]:
        """Recover session breadcrumbs and blockers."""
        sess = self.sessions.get(session_id)
        if not sess:
            return []
        return sess.get("breadcrumbs", [])
