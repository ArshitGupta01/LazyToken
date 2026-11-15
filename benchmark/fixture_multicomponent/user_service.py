"""User account lifecycle, role management, and profile store."""


class UserService:
    """Manages user profiles, role assignments, and account status."""

    def __init__(self):
        self.profiles = {}

    def get_profile(self, user_id: str) -> dict | None:
        """Fetch user profile by user_id."""
        return self.profiles.get(user_id)

    def update_role(self, user_id: str, new_role: str) -> bool:
        """Update user role and account status."""
        if user_id in self.profiles:
            self.profiles[user_id]["role"] = new_role
            return True
        return False
