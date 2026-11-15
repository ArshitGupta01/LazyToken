import unittest
from gateway import ApiGateway
from auth_service import AuthService
from billing_service import BillingService


class MultiComponentTests(unittest.TestCase):
    def test_gateway_routing(self):
        gw = ApiGateway()
        res = gw.route_request("/unauthenticated", {}, {})
        self.assertEqual(res["status"], 401)

    def test_billing_idempotency(self):
        billing = BillingService()
        p1 = billing.process_payment({"idempotency_key": "k1", "amount": 100})
        self.assertEqual(p1["status"], 200)
        p2 = billing.process_payment({"idempotency_key": "k1", "amount": 100})
        self.assertTrue(p2.get("duplicate"))


if __name__ == "__main__":
    unittest.main()
