"""Executable reference tests for the flat Hero 4 pricing policy."""

from datetime import datetime
from decimal import Decimal

from fixtures.hero4.base import Cart, DISCOUNT, NO_DISCOUNT, User, should_apply_discount


NOW = datetime(2026, 6, 15)


def test_beta_customer_gets_the_independent_date_window_discount() -> None:
    assert should_apply_discount(User("beta", "canary"), Cart(Decimal("200")), NOW) == DISCOUNT


def test_large_cart_independently_gets_the_discount_outside_the_window() -> None:
    assert (
        should_apply_discount(
            User("control", "off"), Cart(Decimal("500")), datetime(2026, 8, 1)
        )
        == DISCOUNT
    )


def test_ineligible_customer_outside_the_window_gets_no_discount() -> None:
    assert (
        should_apply_discount(
            User("control", "off"), Cart(Decimal("25")), datetime(2026, 8, 1)
        )
        == NO_DISCOUNT
    )
