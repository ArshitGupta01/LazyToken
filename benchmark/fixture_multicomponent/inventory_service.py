"""Stock management, item reservation, and catalog inventory tracking."""


class InventoryService:
    """Manages product catalog and warehouse stock allocations."""

    def __init__(self):
        self.catalog = {}
        self.stock = {}

    def reserve_stock(self, item_id: str, quantity: int) -> bool:
        """Reserve catalog item stock quantity."""
        current = self.stock.get(item_id, 0)
        if current < quantity:
            return False
        self.stock[item_id] = current - quantity
        return True

    def check_catalog(self, query: str) -> list[dict]:
        """Search catalog inventory items query."""
        return [
            item for item in self.catalog.values() if query.lower() in item.get("name", "").lower()
        ]
