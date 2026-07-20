"""Feature-pricing policy before the feature-flag nesting change."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


DISCOUNT = Decimal("0.10")
NO_DISCOUNT = Decimal("0")
PROMOTION_START = datetime(2026, 6, 1)
PROMOTION_END = datetime(2026, 7, 1)


@dataclass(frozen=True)
class User:
    """Plain request data with directly bindable cohort and flag-state fields."""

    cohort: str
    flag_state: str


@dataclass(frozen=True)
class Cart:
    """Plain request data with a directly bindable cart-value field."""

    cart_value: Decimal


def should_apply_discount(user: User, cart: Cart, now) -> Decimal:
    """Grant the promotion when any independently eligible flat rule matches."""
    if user.cohort == "internal":
        return DISCOUNT
    if cart.cart_value >= Decimal("500"):
        return DISCOUNT
    if PROMOTION_START <= now < PROMOTION_END:
        return DISCOUNT
    return NO_DISCOUNT
