"""Billing, invoicing, payment processing, and idempotency keys."""


class BillingService:
    """Processes customer invoices and financial transactions."""

    def __init__(self):
        self.transactions = {}
        self.processed_idempotency_keys = set()

    def process_payment(self, payload: dict) -> dict:
        """Process invoice payment and transaction."""
        key = payload.get("idempotency_key")
        if not key:
            return {"status": 400, "error": "Missing idempotency_key"}
        if key in self.processed_idempotency_keys:
            return {"status": 200, "duplicate": True, "message": "Already processed"}
        self.processed_idempotency_keys.add(key)
        tx_id = f"tx_{len(self.transactions) + 1}"
        self.transactions[tx_id] = payload
        return {"status": 200, "transaction_id": tx_id, "amount": payload.get("amount", 0)}
