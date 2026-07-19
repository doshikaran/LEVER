"""End-to-end local coverage for Hero 2's module-function registry shape."""

import json
import subprocess
import sys
from pathlib import Path

from domain.fidelity_verifier import FidelityVerifier
from domain.delta_analyst import analyze_delta
from domain.harness_engineer import HarnessEngineer
from domain.schema import (
    DriverBinding,
    Knob,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    TraceExtractor,
)
from domain.scout import scout
from infra.fakes.fake_sandbox import FakeSandboxRuntime
from infra.fakes.fake_llm import FakeLLMClient
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero2"


def _hero2_scope():
    """Scope Hero 2 through Scout instead of constructing a class-shaped stand-in."""
    base_path = FIXTURE_DIR / "base.py"
    head_path = FIXTURE_DIR / "head.py"
    base_source = base_path.read_text(encoding="utf-8")
    head_source = head_path.read_text(encoding="utf-8")
    parser = TreeSitterPythonParser()
    return scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
        str(base_path),
        str(head_path),
    )


def _hero2_spec() -> PartialInteractionSpec:
    """The three concurrent-retry controls and p99 trace observable required by Hero 2."""
    return PartialInteractionSpec(
        thesis="Full jitter desynchronizes concurrent exponential retries.",
        domainPack="rate-limiter",
        knobs=[
            Knob(
                id="clients",
                label="clients",
                binding=DriverBinding(kind="driver", param="clients"),
                type="integer",
                domain=NumericDomain(min=1, max=200, step=1),
                default=100,
                scale="linear",
                unit="clients",
            ),
            Knob(
                id="failureRate",
                label="failure rate",
                binding=DriverBinding(kind="driver", param="failureRate"),
                type="scalar",
                domain=NumericDomain(min=0, max=1, step=0.01),
                default=0.7,
                scale="linear",
                unit=None,
            ),
            Knob(
                id="maxRetries",
                label="max retries",
                binding=DriverBinding(kind="driver", param="maxRetries"),
                type="integer",
                domain=NumericDomain(min=1, max=10, step=1),
                default=6,
                scale="linear",
                unit="attempts",
            ),
        ],
        observables=[
            Observable(
                id="p99_completion_time",
                label="p99 completion time",
                extractor=TraceExtractor(
                    kind="trace", event="completion_time", agg="p99"
                ),
                render="timeseries",
                unit="seconds",
                compareMode="overlay",
            )
        ],
    )


def _run_harness(source: str, point: dict[str, float | int], seed: int = 0) -> dict:
    """Execute one generated artifact locally, preserving its public ``run`` contract."""
    process = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, check=False, text=True
    )
    assert process.returncode == 0, process.stderr
    namespace: dict[str, object] = {}
    exec(compile(source, "hero2-generated-harness", "exec"), namespace)
    return namespace["run"](point, seed)  # type: ignore[operator]


def test_module_level_entry_point_generates_seeded_herd_workload() -> None:
    """Hero 2 proves registry dispatch and Scout do not assume a class method."""
    scope = _hero2_scope()
    assert not scope.unscopable
    assert scope.entry_point is not None
    assert scope.entry_point.fn == "next_delay"
    assert [entry.kind for entry in scope.dependency_ledger.entries] == ["random"]

    pair = HarnessEngineer().generate(
        scope,
        _hero2_spec(),
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
    )
    assert pair.stub_config == ()
    assert pair.uncertainty_specs == ()
    assert pair.workload_driver.parameters == ("clients", "failureRate", "maxRetries")

    point = {"clients": 100, "failureRate": 1.0, "maxRetries": 7}
    base = _run_harness(pair.harness_a.source, point)
    head = _run_harness(pair.harness_b.source, point)
    base_p99 = base["observations"]["p99_completion_time"]
    head_p99 = head["observations"]["p99_completion_time"]
    assert base_p99 > head_p99 * 8
    assert _run_harness(pair.harness_b.source, point)["observations"] == head["observations"]


def test_delta_prompt_and_validation_preserve_hero2s_driver_contract() -> None:
    """The live analyst receives the module-function workload requirements verbatim."""
    spec = _hero2_spec()
    response = {
        "thesis": spec.thesis,
        "domainPack": spec.domainPack.value,
        "knobs": [knob.model_dump(mode="json") for knob in spec.knobs],
        "observables": [observable.model_dump(mode="json") for observable in spec.observables],
    }
    fake = FakeLLMClient([response])
    result = analyze_delta(
        fake,
        _hero2_scope(),
        (FIXTURE_DIR / "base.py").read_text(encoding="utf-8"),
        (FIXTURE_DIR / "head.py").read_text(encoding="utf-8"),
    )

    assert [knob.id for knob in result.knobs] == ["clients", "failureRate", "maxRetries"]
    assert all(knob.binding.kind == "driver" for knob in result.knobs)
    assert result.observables[0].extractor.kind == "trace"
    assert result.observables[0].extractor.agg == "p99"
    assert "Hero 2 execution constraint" in fake.prompts[0]


def test_hero2_harness_matches_direct_reference_over_the_full_sobol_design(tmp_path) -> None:
    """The module-function driver has high-confidence fidelity without real services."""
    scope = _hero2_scope()
    spec = _hero2_spec()
    pair = HarnessEngineer().generate(
        scope,
        spec,
        str(tmp_path / "base.py"),
        str(tmp_path / "head.py"),
    )
    runtime = FakeSandboxRuntime()
    sandbox_id = runtime.create_sandbox("base")
    try:
        verification = FidelityVerifier(runtime).verify(
            sandbox_id,
            pair,
            scope,
            spec,
            (FIXTURE_DIR / "base.py").read_text(encoding="utf-8"),
            (FIXTURE_DIR / "head.py").read_text(encoding="utf-8"),
        )
    finally:
        runtime.kill_sandbox(sandbox_id)

    assert verification.report.agreement.rate == 1.0
    assert verification.report.band == "high"
    assert verification.report.confidence >= 0.85
    assert not verification.mismatches
