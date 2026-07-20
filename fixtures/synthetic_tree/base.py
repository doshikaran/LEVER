"""Synthetic branch fixture used to verify C-5 before Hero 4 exists."""


def choose(value: int, enabled: bool) -> int:
    """Select one of three simple routes."""
    if value < 0:
        return -1
    if enabled:
        return value * 2
    return value
