"""Executable reference checks for Hero 2's full-jitter head version."""

import importlib.util
import random
from pathlib import Path


HEAD_PATH = Path(__file__).resolve().parents[1] / "head.py"


def _load_head():
    spec = importlib.util.spec_from_file_location("hero2_head", HEAD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_next_delay_stays_within_the_exponential_ceiling() -> None:
    """Full jitter never returns a negative or over-ceiling retry delay."""
    head = _load_head()
    random.seed(17)
    delays = [head.next_delay(attempt) for attempt in range(5)]
    assert all(0.0 <= delay <= 2**attempt for attempt, delay in enumerate(delays))


def test_next_delay_is_reproducible_when_the_harness_seeds_random() -> None:
    """Symmetric seeding yields the same jitter sequence in every repeat."""
    head = _load_head()
    random.seed(29)
    first = [head.next_delay(attempt) for attempt in range(4)]
    random.seed(29)
    second = [head.next_delay(attempt) for attempt in range(4)]
    assert first == second
