"""Deterministic cached-search coverage for the Adversary."""

from __future__ import annotations

from domain.adversary import (
    Adversary,
    EXPLORE_POINTS,
    MAX_EVALUATIONS,
    ObservationBundle,
    TracePoint,
)
from domain.fidelity_verifier import FidelityObservation, FidelityVerification, sobol_points
from domain.harness_engineer import HarnessEngineer
from domain.schema import (
    Agreement,
    Coverage,
    CvStabilityEstimate,
    FidelityReport,
    RelativeTolerance,
    Stability,
    SymmetristSummary,
)
from infra.fakes.fake_sandbox import FakeSandboxRuntime

from test_harness_engineer import _hero_scope, _hero_spec


def _verified_fidelity(observations: tuple[FidelityObservation, ...]) -> FidelityVerification:
    """Build the verified prerequisite that Adversary is allowed to consume."""
    return FidelityVerification(
        report=FidelityReport(
            verdict="verified",
            symmetrist=SymmetristSummary(
                passed=True, hashA="a", hashB="a", unjustifiedKeys=[]
            ),
            agreement=Agreement(
                samples=128,
                matched=128,
                rate=1.0,
                tolerance=RelativeTolerance(kind="relative", epsilon=0.01),
            ),
            stability=Stability(
                replicates=12,
                perObservable={"admitted": CvStabilityEstimate(kind="cv", value=0.0)},
            ),
            coverage=Coverage(samples=128, strategy="sobol"),
            confidence=1.0,
            band="high",
            degradeReason=None,
        ),
        mismatches=(),
        observations=observations,
    )


def _scripted_landscape(point: dict[str, float]) -> ObservationBundle:
    """A legible deterministic divergence surface whose peak is at high load/tenancy."""
    limit = int(point["limit_per_sec"])
    burst = int(point["burst"])
    rps = int(point["rps"])
    tenants = int(point["tenants"])
    base = min(limit, rps * tenants)
    head = min(limit + burst, rps) * tenants
    return ObservationBundle(base={"admitted": base}, head={"admitted": head})


def test_adversary_reuses_fidelity_explore_points_and_caches_the_search() -> None:
    """The first 64 fidelity points cost no reruns; exploit spends at most 64 new probes."""
    spec = _hero_spec()
    explore_points = sobol_points(spec.knobs, m=6)
    fidelity_points = sobol_points(spec.knobs)
    fidelity = _verified_fidelity(
        tuple(
            FidelityObservation(point, bundle.base, bundle.head)
            for point in fidelity_points
            for bundle in (_scripted_landscape(point),)
        )
    )
    calls: list[dict[str, float]] = []
    runtime = FakeSandboxRuntime(
        scripted_results=[
            {"stdout": "{}", "stderr": "", "exit_code": 0}
            for _ in range(MAX_EVALUATIONS - EXPLORE_POINTS)
        ]
    )
    sandbox_id = runtime.create_sandbox("base")

    def runner(point: dict[str, float]) -> ObservationBundle:
        runtime.run_code(sandbox_id, "print('scripted landscape')")
        calls.append(point)
        return _scripted_landscape(point)

    pair = HarnessEngineer().generate(
        _hero_scope(), _hero_spec(), "/tmp/base.py", "/tmp/head.py"
    )
    streamed: list[TracePoint] = []
    result = Adversary(runtime, runner).search(
        sandbox_id, pair, spec, fidelity, trace_callback=streamed.append
    )

    assert not result.no_divergence
    assert result.initial_position is not None
    assert result.surprise_marker is not None
    assert result.surprise_marker.caption.startswith("Head admits")
    assert len(calls) == len(result.cache) - EXPLORE_POINTS
    assert len(calls) <= MAX_EVALUATIONS - EXPLORE_POINTS
    assert len(result.cache) <= MAX_EVALUATIONS
    assert result.accounting is not None
    # The trace preserves all 64 Sobol samples even when a discrete/log domain
    # quantizes two samples to the same memoized KnobPosition.
    assert len(result.search_trace) == (
        EXPLORE_POINTS + result.accounting.exploit_executed_new
    )
    assert streamed == list(result.search_trace)
    assert len(streamed[:EXPLORE_POINTS]) == EXPLORE_POINTS
    assert all(point.phase == "explore" for point in streamed[:EXPLORE_POINTS])
    assert all(point.phase == "exploit" for point in streamed[EXPLORE_POINTS:])
    assert result.accounting.explore_reused_from_fidelity == EXPLORE_POINTS
    assert result.accounting.exploit_attempted == MAX_EVALUATIONS - EXPLORE_POINTS
    assert result.accounting.exploit_unattempted == 0
    assert (
        result.accounting.exploit_executed_new
        + result.accounting.exploit_collisions_with_explore
        + result.accounting.exploit_collisions_with_exploit
        == result.accounting.exploit_attempted
    )
    runtime.kill_sandbox(sandbox_id)


def test_adversary_returns_no_divergence_as_a_finding() -> None:
    """Dead knobs are a bounded analytical result, not a search exception."""
    spec = _hero_spec()
    explore_points = sobol_points(spec.knobs, m=6)
    inert = ObservationBundle(base={"admitted": 5}, head={"admitted": 5})
    fidelity = _verified_fidelity(
        tuple(FidelityObservation(point, inert.base, inert.head) for point in explore_points)
    )
    runtime = FakeSandboxRuntime()
    sandbox_id = runtime.create_sandbox("base")
    pair = HarnessEngineer().generate(
        _hero_scope(), _hero_spec(), "/tmp/base.py", "/tmp/head.py"
    )
    result = Adversary(runtime, lambda point: inert).search(
        sandbox_id, pair, spec, fidelity
    )

    assert result.no_divergence
    assert result.initial_position is None
    assert result.surprise_marker is None
    assert result.reason is not None
    assert "rps" in result.reason
    runtime.kill_sandbox(sandbox_id)
