"""Head: same entry shape, different scaling behavior."""


def scale(value: float, factor: float = 2.0) -> float:
    """Scale a numeric input and add a constant offset introduced by the diff."""
    return value * factor + 1.0
