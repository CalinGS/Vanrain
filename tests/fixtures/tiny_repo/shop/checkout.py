"""Checkout flow."""
from shop import Order
from shop import util
from shop.models import DiscountedOrder, Item
from shop.pricing import with_tax

HANDLERS = {"round": util.round_money}


def checkout(items: list[Item], discount: float = 0.0) -> float:
    order = DiscountedOrder(discount)
    for it in items:
        order.add(it)
    return util.round_money(with_tax(order.total()))


def is_order(obj: object) -> bool:
    return isinstance(obj, Order)


def outer() -> float:
    def inner() -> float:
        return util.round_money(1.005)

    return inner()
