"""Executable reference checks for Hero 2's fixed-backoff baseline."""

import importlib.util
from pathlib import Path


BASE_PATH = Path(__file__).resolve().parents[1] / "base.py"


def _load_base():
    spec = importlib.util.spec_from_file_location("hero2_base", BASE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_next_delay_doubles_for_each_attempt() -> None:
    """The old retry policy always schedules at the exponential ceiling."""
    base = _load_base()
    assert [base.next_delay(attempt) for attempt in range(5)] == [1.0, 2.0, 4.0, 8.0, 16.0]
