"""Price arithmetic. Imports nothing from the package."""

TAX_RATE = 0.2


def apply_discount(amount: float, pct: float) -> float:
    """Reduce an amount by a fraction between 0 and 1."""
    return amount * (1 - pct)


def with_tax(amount: float) -> float:
    return amount * (1 + TAX_RATE)
