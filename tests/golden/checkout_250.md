# Context for shop.checkout.checkout

12 symbols (1 full, 11 signatures), 250 of 250 tokens. Symbols ending in `...` are signatures only; their bodies are left out.

## shop/checkout.py

```python
# shop.checkout L1-25
"""Checkout flow."""

# shop.checkout.checkout L10-14
def checkout(items: list[Item], discount: float = 0.0) -> float:
    order = DiscountedOrder(discount)
    for it in items:
        order.add(it)
    return util.round_money(with_tax(order.total()))
```

## shop/models.py

```python
# shop.models L1-39
"""Domain objects."""

# shop.models.Item L5-15
class Item:
    """A product line in an order."""
    ...

# shop.models.Order L18-28
class Order:
    """A collection of items."""
    ...

# shop.models.Order.add L24-25
def add(self, item: Item) -> None: ...

# shop.models.Order.total L27-28
def total(self) -> float: ...

# shop.models.DiscountedOrder L31-39
class DiscountedOrder(Order):
    """An order with a percentage discount."""
    ...

# shop.models.DiscountedOrder.__init__ L34-36
def __init__(self, pct: float): ...

# shop.models.DiscountedOrder.total L38-39
def total(self) -> float: ...
```

## shop/pricing.py

```python
# shop.pricing.with_tax L11-12
def with_tax(amount: float) -> float: ...
```

## shop/util.py

```python
# shop.util.round_money L4-5
def round_money(x: float) -> float: ...
```
