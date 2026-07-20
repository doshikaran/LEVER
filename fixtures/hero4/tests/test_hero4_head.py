"""Executable reference tests for the nested Hero 4 pricing policy."""

from datetime import datetime
from decimal import Decimal

from fixtures.hero4.head import Cart, DISCOUNT, NO_DISCOUNT, User, should_apply_discount


NOW = datetime(2026, 6, 15)


def test_canary_beta_customer_is_stopped_at_the_rollout_gate() -> None:
    assert should_apply_discount(User("beta", "canary"), Cart(Decimal("200")), NOW) == NO_DISCOUNT


def test_on_flag_runs_the_nested_date_window_rule() -> None:
    assert should_apply_discount(User("beta", "on"), Cart(Decimal("200")), NOW) == DISCOUNT


def test_off_flag_disables_an_otherwise_eligible_large_cart() -> None:
    assert should_apply_discount(User("control", "off"), Cart(Decimal("500")), NOW) == NO_DISCOUNT
