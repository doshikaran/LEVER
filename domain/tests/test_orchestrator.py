"""Part 5 loop wiring using real static agents and scripted downstream outcomes."""

from pathlib import Path

import domain.orchestrator as orchestrator
from domain.adversary import AdversaryResult
from domain.fidelity_verifier import FidelityVerification
from domain.harness_engineer import HarnessEngineer as RealHarnessEngineer
from domain.schema import (
    Agreement,
    Coverage,
    CvStabilityEstimate,
    FidelityReport,
    KnobPosition,
    RelativeTolerance,
    Stability,
    SurpriseMarker,
    SymmetristSummary,
)
from infra.fakes.fake_llm import FakeLLMClient
from infra.fakes.fake_sandbox import FakeSandboxRuntime


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero1"


def _valid_response() -> dict:
    """Return the valid rate-limiter proposal consumed by real Delta Analyst."""
    return {
        "thesis": "Tenant load changes admitted requests in the new limiter.",
        "domainPack": "rate-limiter",
        "knobs": [
            {
                "id": "rps",
                "label": "requests per second",
                "binding": {"kind": "driver", "param": "rps"},
                "type": "integer",
                "domain": {"min": 1, "max": 100, "step": 1},
                "default": 3,
                "scale": "linear",
                "unit": "requests / sec",
            }
        ],
        "observables": [
            {
                "id": "admitted",
                "label": "admitted requests",
                "extractor": {"kind": "counter", "name": "admitted"},
                "render": "timeseries",
                "unit": "requests",
                "compareMode": "overlay",
            }
        ],
    }


def _fidelity(passed: bool) -> FidelityVerification:
    """Build either a Loop-A retryable failure or a verified Fidelity result."""
    return FidelityVerification(
        FidelityReport(
            verdict="verified" if passed else "degraded",
            symmetrist=SymmetristSummary(
                passed=passed,
                hashA="same" if passed else "",
                hashB="same" if passed else "",
                unjustifiedKeys=[] if passed else ["clock"],
            ),
            agreement=Agreement(
                samples=128 if passed else 0,
                matched=128 if passed else 0,
                rate=1.0 if passed else 0.0,
                tolerance=RelativeTolerance(kind="relative", epsilon=0.01),
            ),
            stability=Stability(
                replicates=12 if passed else 0,
                perObservable={"admitted": CvStabilityEstimate(kind="cv", value=0.0)},
            ),
            coverage=Coverage(samples=128 if passed else 0, strategy="sobol"),
            confidence=0.9 if passed else 0.0,
            band="high" if passed else "low",
            degradeReason=None if passed else "Symmetrist failed for keys: clock",
        ),
        (),
    )


def _divergent_result() -> AdversaryResult:
    """Return a measured search result the real Synthesizer can consume."""
    position = KnobPosition({"rps": 100})
    return AdversaryResult(
        initial_position=position,
        surprise_marker=SurpriseMarker(
            position=position,
            divergence=0.5,
            caption="Head admits 2.0× as many requests (10 vs 5).",
        ),
        presets=(),
        search_trace=(),
        cache=(),
        no_divergence=False,
    )


def _inert_result() -> AdversaryResult:
    """Return the Loop-B kickback signal rather than throwing an exception."""
    return AdversaryResult(
        initial_position=None,
        surprise_marker=None,
        presets=(),
        search_trace=(),
        cache=(),
        no_divergence=True,
        reason="No normalized divergence reached 0.02 after varying requests per second.",
    )


def _counting_harness(monkeypatch) -> list[int]:
    """Patch only construction so tests prove actual Part 5 re-entry count."""
    calls: list[int] = []

    class CountingHarnessEngineer:
        def generate(self, *args, **kwargs):
            calls.append(1)
            return RealHarnessEngineer().generate(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "HarnessEngineer", CountingHarnessEngineer)
    return calls


def test_loop_a_reenters_harness_engineer_after_one_scripted_fidelity_failure(monkeypatch) -> None:
    """A Symmetrist failure sends the flow to HE attempt two, then it succeeds."""
    harness_calls = _counting_harness(monkeypatch)
    fidelity_results = [_fidelity(False), _fidelity(True)]

    class ScriptedVerifier:
        def __init__(self, runtime):
            pass

        def verify(self, *args, **kwargs):
            return fidelity_results.pop(0)

    class DivergentAdversary:
        def __init__(self, runtime):
            pass

        def search(self, *args, **kwargs):
            return _divergent_result()

    monkeypatch.setattr(orchestrator, "FidelityVerifier", ScriptedVerifier)
    monkeypatch.setattr(orchestrator, "Adversary", DivergentAdversary)
    progress: list[tuple[str, str]] = []
    result = orchestrator.run_pipeline(
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
        FakeSandboxRuntime(),
        FakeLLMClient([_valid_response()]),
        "fake-model",
        "low",
        progress_callback=lambda stage, message: progress.append((stage, message)),
    )

    assert result.domainPack.value == "rate-limiter"
    assert len(harness_calls) == 2
    assert not fidelity_results
    assert [stage for stage, _ in progress] == [
        "files_touched",
        "behavior_identified",
        "old_vs_new",
        "building",
    ]


def test_loop_b_kicks_back_to_delta_analyst_once_then_recovers(monkeypatch) -> None:
    """An inert search re-enters Delta Analyst exactly once and then finds divergence."""
    harness_calls = _counting_harness(monkeypatch)

    class VerifiedVerifier:
        def __init__(self, runtime):
            pass

        def verify(self, *args, **kwargs):
            return _fidelity(True)

    adversary_results = [_inert_result(), _divergent_result()]

    class ScriptedAdversary:
        def __init__(self, runtime):
            pass

        def search(self, *args, **kwargs):
            return adversary_results.pop(0)

    fake_llm = FakeLLMClient([_valid_response(), _valid_response()])
    monkeypatch.setattr(orchestrator, "FidelityVerifier", VerifiedVerifier)
    monkeypatch.setattr(orchestrator, "Adversary", ScriptedAdversary)
    result = orchestrator.run_pipeline(
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
        FakeSandboxRuntime(),
        fake_llm,
        "fake-model",
        "low",
    )

    assert result.domainPack.value == "rate-limiter"
    assert len(harness_calls) == 2
    assert len(fake_llm.prompts) == 2
    assert not adversary_results
