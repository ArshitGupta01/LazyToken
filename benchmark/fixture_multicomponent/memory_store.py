"""Domain lesson store, memory proposal lifecycle, and verified assets."""


class MemoryStore:
    """Manages domain lessons, proposal review transitions, and supersession."""

    def __init__(self):
        self.proposals = {}
        self.verified_lessons = {}

    def get_verified_lesson(self, lesson_id: str) -> dict | None:
        """Retrieve verified domain lesson asset."""
        return self.verified_lessons.get(lesson_id)

    def review_proposal(self, proposal_id: str, action: str) -> dict:
        """Manage memory proposal review transitions."""
        prop = self.proposals.get(proposal_id)
        if not prop:
            return {"error": "Not found"}
        if action == "approve":
            prop["status"] = "verified"
            self.verified_lessons[proposal_id] = prop
        elif action == "reject":
            prop["status"] = "rejected"
        return prop

    def supersede_memory(self, old_id: str, new_proposal: dict) -> dict:
        """Supersede prior lesson with replaces_id."""
        new_proposal["replaces_id"] = old_id
        if old_id in self.verified_lessons:
            self.verified_lessons[old_id]["status"] = "superseded"
        return new_proposal
