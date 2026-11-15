"""Notification dispatcher, email alerts, and audit messaging."""


class NotificationService:
    """Dispatches asynchronous alerts and operational notifications."""

    def __init__(self):
        self.sent_alerts = []

    def send_email_alert(self, recipient: str, subject: str, body: str) -> bool:
        """Dispatch email notification alert."""
        if not recipient or "@" not in recipient:
            return False
        self.sent_alerts.append({"recipient": recipient, "subject": subject, "body": body})
        return True
