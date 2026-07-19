"""Coverage for durable, harness-backed pinned regression tests."""

import subprocess
import sys
from pathlib import Path

from domain.harness_engineer import HarnessEngineer
from domain.line_attribution import trace_attribution
from domain.pin_as_test import write_pinned_head_test
from domain.schema import KnobPosition

from test_harness_engineer import FIXTURE_DIR, _hero_scope, _hero_spec
from test_synthesizer import _real_hero1_interaction_spec


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_harness(source: str, point: dict[str, int]) -> dict:
    """Invoke the generated driver, retaining the same observation used for the pin."""
    namespace: dict[str, object] = {"__name__": "pin_test_driver"}
    exec(compile(source, "pin-test-harness", "exec"), namespace)
    return namespace["run"](point, 0)  # type: ignore[operator]


def test_pin_writes_a_harness_backed_pytest_with_the_responsible_line_comment(tmp_path) -> None:
    """The written test is runnable and guards the measured head behavior, not a copy of the driver."""
    point = {"limit_per_sec": 50, "burst": 10, "rps": 81, "tenants": 20}
    pair = HarnessEngineer().generate(
        _hero_scope(),
        _hero_spec(),
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
    )
    base = _run_harness(pair.harness_a.source, point)
    head = _run_harness(pair.harness_b.source, point)
    attribution = trace_attribution(
        base["trace"],
        head["trace"],
        (FIXTURE_DIR / "base.py").read_text(),
        (FIXTURE_DIR / "head.py").read_text(),
    )

    pinned = write_pinned_head_test(
        tmp_path / "pinned_tests",
        FIXTURE_DIR / "base.py",
        FIXTURE_DIR / "head.py",
        _real_hero1_interaction_spec(),
        KnobPosition(point),
        head["observations"],
        attribution.responsibleLine if attribution is not None else None,
    )
    source = pinned.read_text()

    assert "HarnessEngineer().generate" in source
    assert "do not duplicate its workload driver" in source
    assert (
        f"# Lever trace attribution: {FIXTURE_DIR / 'head.py'}:19 — if len(w) < self.limit:"
        in source
    )
    assert write_pinned_head_test(
        tmp_path / "pinned_tests",
        FIXTURE_DIR / "base.py",
        FIXTURE_DIR / "head.py",
        _real_hero1_interaction_spec(),
        KnobPosition(point),
        head["observations"],
        attribution.responsibleLine if attribution is not None else None,
    ) == pinned

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(pinned)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
