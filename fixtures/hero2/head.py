"""Full-jitter exponential retry backoff — the new version."""

import random


BASE_DELAY = 1.0


def next_delay(attempt: int) -> float:
    """Return a uniformly jittered wait bounded by the exponential ceiling."""
    return random.uniform(0.0, BASE_DELAY * 2**attempt)
