"""API Gateway routing, rate-limiting, and microservice dispatch."""

from auth_service import AuthService
from billing_service import BillingService
from user_service import UserService


class ApiGateway:
    """Dispatches HTTP requests to downstream microservices."""

    def __init__(self):
        self.auth = AuthService()
        self.billing = BillingService()
        self.users = UserService()

    def route_request(self, path: str, headers: dict, payload: dict) -> dict:
        """Route incoming request payload to target service."""
        token = headers.get("Authorization", "")
        if not self.auth.verify_bearer_token(token):
            return {"status": 401, "error": "Unauthorized"}
        if path.startswith("/billing"):
            return self.billing.process_payment(payload)
        if path.startswith("/user"):
            return self.users.get_profile(payload.get("user_id"))
        return {"status": 200, "message": "routed", "path": path}
