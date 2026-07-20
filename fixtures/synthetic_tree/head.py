"""Synthetic branch fixture with one deliberately divergent predicate."""


def choose(value: int, enabled: bool) -> int:
    """Select one of three simple routes."""
    if value <= 0:
        return -1
    if enabled:
        return value * 2
    return value
