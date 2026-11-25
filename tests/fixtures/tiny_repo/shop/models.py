"""Domain objects."""
from shop.pricing import apply_discount


class Item:
    """A product line in an order."""

    def __init__(self, name: str, unit_price: float, qty: int = 1):
        self.name = name
        self.unit_price = unit_price
        self.qty = qty

    def price(self) -> float:
        """Total price for this line."""
        return self.unit_price * self.qty


class Order:
    """A collection of items."""

    def __init__(self):
        self.items: list[Item] = []

    def add(self, item: Item) -> None:
        self.items.append(item)

    def total(self) -> float:
        return sum(item.price() for item in self.items)


class DiscountedOrder(Order):
    """An order with a percentage discount."""

    def __init__(self, pct: float):
        super().__init__()
        self.pct = pct

    def total(self) -> float:
        return apply_discount(super().total(), self.pct)
