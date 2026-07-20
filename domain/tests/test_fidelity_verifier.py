"""Fake-runtime confidence coverage for Symmetrist-first fidelity verification."""

import json
import math

from domain.fidelity_verifier import (
    FidelityVerifier,
    SOBOL_POINT_COUNT,
    _compare_observations,
    _report_tolerance,
)
from domain.harness_engineer import (
    DependencyStub,
    HarnessArtifact,
    HarnessEngineer,
    HarnessPair,
    UncertaintySpec,
    WorkloadDriver,
)
from domain.schema import (
    ArgumentBinding,
    DomainPackId,
    ExactTolerance,
    Knob,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    PathExtractor,
)
from infra.fakes.fake_sandbox import FakeSandboxRuntime

from test_harness_engineer import _hero_scope, _hero_spec


def _categorical_observable() -> Observable:
    """Return a synthetic path value so C-4 is tested apart from any Hero."""
    return Observable(
        id="route",
        label="selected route",
        extractor=PathExtractor(kind="path", instrumentation="branch"),
        render="pathTrace",
        unit=None,
        compareMode="overlay",
    )


def _categorical_spec() -> PartialInteractionSpec:
    """Provide the minimum synthetic input needed to exercise Assayer end to end."""
    return PartialInteractionSpec(
        thesis="A synthetic route may wobble under stub uncertainty.",
        domainPack=DomainPackId.DECISION_TREE,
        knobs=[
            Knob(
                id="input",
                label="input",
                binding=ArgumentBinding(kind="argument", fn="choose", argIndex=0),
                type="integer",
                domain=NumericDomain(min=0, max=1, step=1),
                default=0,
                scale="linear",
                unit=None,
            )
        ],
        observables=[_categorical_observable()],
    )


def _uncertain_categorical_pair() -> HarnessPair:
    """Mark one guessed stub so Assayer must use its measured stability factor."""
    stub = DependencyStub(
        dependency="db.query",
        kind="db",
        parameters={"latency": UncertaintySpec(default=5, distribution="uniform")},
    )
    artifact = HarnessArtifact(source="STUB_CONFIG = {}\n", entry_module="/tmp/module.py")
    return HarnessPair(
        harness_a=artifact,
        harness_b=artifact,
        stub_config=(stub,),
        uncertainty_specs=(stub,),
        workload_driver=WorkloadDriver(parameters=(), knob_definitions=()),
    )


def test_fidelity_confidence_uses_agreement_stability_and_coverage_with_fake_runtime() -> None:
    """Half of the Sobol points agreeing produces the exact low-band product with no stubs."""
    scripted_results = []
    for point_index in range(SOBOL_POINT_COUNT):
        matching = point_index >= SOBOL_POINT_COUNT // 2
        base_reference = {"admitted": 1 if matching else 2}
        for observations in (
            {"admitted": 1},
            base_reference,
            {"admitted": 1},
            {"admitted": 1},
        ):
            scripted_results.append(
                {"stdout": json.dumps(observations), "stderr": "", "exit_code": 0}
            )
    for _ in range(SOBOL_POINT_COUNT // 2 * 12 * 2):
        scripted_results.append(
            {"stdout": json.dumps({"admitted": 1}), "stderr": "", "exit_code": 0}
        )
    runtime = FakeSandboxRuntime(scripted_results=scripted_results)
    sandbox_id = runtime.create_sandbox("base")

    def scripted_runner(kind: str, point: dict, seed: int) -> dict:
        result = runtime.run_code(sandbox_id, "print('scripted')")
        return json.loads(result["stdout"])

    pair = HarnessEngineer().generate(
        _hero_scope(), _hero_spec(), "/tmp/base.py", "/tmp/head.py"
    )
    verification = FidelityVerifier(runtime, scripted_runner).verify(
        sandbox_id,
        pair,
        _hero_scope(),
        _hero_spec(),
        "base source is unused by the injected fake runner",
        "head source is unused by the injected fake runner",
    )

    expected_coverage = math.log1p(SOBOL_POINT_COUNT) / math.log1p(256)
    assert verification.report.agreement.samples == SOBOL_POINT_COUNT
    assert verification.report.agreement.matched == SOBOL_POINT_COUNT // 2
    assert verification.report.agreement.rate == 0.5
    assert verification.report.stability.perObservable["admitted"].value == 0.0
    # Hero 1 has no uncertainty dimensions: the Assayer therefore contributes 1.
    assert verification.report.confidence == 0.5 * expected_coverage
    assert verification.report.band == "low"
    assert len(verification.mismatches) == SOBOL_POINT_COUNT // 2
    runtime.kill_sandbox(sandbox_id)


def test_categorical_values_compare_exactly_and_stable_replicates_have_zero_instability() -> None:
    """C-4 never applies relative numeric tolerance to a categorical route."""
    observable = _categorical_observable()
    tolerance = _report_tolerance([observable])

    assert isinstance(tolerance, ExactTolerance)
    assert not _compare_observations(
        {"input": 0}, "base", [observable], {"route": ["left", "allow"]},
        {"route": ["left", "allow"]}, tolerance,
    )
    mismatches = _compare_observations(
        {"input": 0}, "base", [observable], {"route": ["left", "allow"]},
        {"route": ["right", "deny"]}, tolerance,
    )
    assert len(mismatches) == 1

    def stable_runner(_kind: str, _point: dict, _seed: int | str) -> dict:
        return {"route": ["left", "allow"]}

    verifier = FidelityVerifier(FakeSandboxRuntime(), stable_runner)
    stability, stability_factor = verifier._assay(
        stable_runner,
        [observable],
        [{"input": 0}],
        _uncertain_categorical_pair(),
        {'{"input":0}': 0},
    )

    estimate = stability.perObservable["route"]
    assert estimate.kind == "instability"
    assert estimate.value == 0.0
    assert stability_factor == 1.0


def test_categorical_three_of_twelve_flips_zeroes_stability_and_degrades() -> None:
    """The C-4 worked example collapses confidence instead of averaging route flips away."""
    spec = _categorical_spec()
    pair = _uncertain_categorical_pair()
    assay_calls: dict[tuple[str, str], int] = {}

    def flipping_runner(kind: str, point: dict, seed: int | str) -> dict:
        if seed == 0:
            # Differential testing agrees exactly for every Sobol point.
            return {"route": ["left", "allow"]}
        key = (json.dumps(point, sort_keys=True), kind)
        replicate_index = assay_calls.get(key, 0)
        assay_calls[key] = replicate_index + 1
        return {
            "route": ["right", "deny"]
            if replicate_index < 3
            else ["left", "allow"]
        }

    verification = FidelityVerifier(FakeSandboxRuntime(), flipping_runner).verify(
        "unused",
        pair,
        _hero_scope(),
        spec,
        "synthetic base source",
        "synthetic head source",
    )

    estimate = verification.report.stability.perObservable["route"]
    assert verification.report.agreement.rate == 1.0
    assert estimate.kind == "instability"
    assert estimate.value == 0.25
    assert verification.report.confidence == 0.0
    assert verification.report.band == "low"
    assert verification.report.verdict == "degraded"
