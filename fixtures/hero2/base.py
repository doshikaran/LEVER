"""Fixed exponential retry backoff — the old version."""

BASE_DELAY = 1.0


def next_delay(attempt: int) -> float:
    """Return the deterministic exponential wait before retry ``attempt``."""
    return BASE_DELAY * 2**attempt
