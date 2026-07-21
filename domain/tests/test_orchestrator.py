"""Part 5 loop wiring using real static agents and scripted downstream outcomes."""

from pathlib import Path

import domain.orchestrator as orchestrator
from domain.adversary import AdversaryResult
from domain.fidelity_verifier import FidelityVerification
from domain.harness_engineer import HarnessEngineer as RealHarnessEngineer
from domain.line_attribution import UninstrumentableReferenceError
from domain.schema import (
    Agreement,
    Coverage,
    CvStabilityEstimate,
    DependencyLedger,
    EntryPoint,
    FidelityReport,
    KnobPosition,
    RelativeTolerance,
    Stability,
    SurpriseMarker,
    SymmetristSummary,
    ScopedChangeSet,
)
from infra.fakes.fake_llm import FakeLLMClient
from infra.fakes.fake_sandbox import FakeSandboxRuntime


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero1"
HERO2_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero2"
HERO3_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero3"


def _valid_response() -> dict:
    """Return the valid rate-limiter proposal consumed by real Delta Analyst."""
    return {
        "thesis": "Tenant load changes admitted requests in the new limiter.",
        "domainPack": "rate-limiter",
        "knobs": [
            {
                "id": "limit_per_sec",
                "label": "per-tenant limit",
                "binding": {"kind": "config", "path": "limit_per_sec"},
                "type": "integer",
                "domain": {"min": 1, "max": 200, "step": 1},
                "default": 50,
                "scale": "linear",
                "unit": "requests / sec",
            },
            {
                "id": "burst",
                "label": "burst allowance",
                "binding": {"kind": "config", "path": "burst"},
                "type": "integer",
                "domain": {"min": 0, "max": 100, "step": 1},
                "default": 10,
                "scale": "linear",
                "unit": "requests",
            },
            {
                "id": "rps",
                "label": "requests per second",
                "binding": {"kind": "driver", "param": "rps"},
                "type": "integer",
                "domain": {"min": 1, "max": 100, "step": 1},
                "default": 3,
                "scale": "linear",
                "unit": "requests / sec",
            },
            {
                "id": "tenants",
                "label": "tenant count",
                "binding": {"kind": "driver", "param": "tenants"},
                "type": "integer",
                "domain": {"min": 1, "max": 32, "step": 1},
                "default": 2,
                "scale": "linear",
                "unit": "tenants",
            },
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


def _live_hero2_numeric_fn_response() -> dict:
    """Exact one-knob proposal recorded from tonight's generic live GPT run."""
    return {
        "thesis": (
            "Retry delay changes from deterministic exponential backoff to a uniform "
            "random value from zero to the same exponential ceiling."
        ),
        "domainPack": "numeric-fn",
        "knobs": [
            {
                "id": "attempt",
                "label": "Retry attempt",
                "binding": {"kind": "argument", "fn": "next_delay", "argIndex": 0},
                "type": "scalar",
                "domain": {"min": 0, "max": 10, "step": 1},
                "default": 0,
                "scale": "linear",
                "unit": None,
                "axisRole": "x",
            }
        ],
        "observables": [
            {
                "id": "delay",
                "label": "Retry delay",
                "extractor": {"kind": "returnValue", "path": "$"},
                "render": "scalar",
                "compareMode": "overlay",
                "unit": "seconds",
            }
        ],
    }


def _incompatible_permission_response() -> dict:
    """A valid permission-pack draft that a no-driver matrix template must reject."""
    return {
        "thesis": "The permission check changes for inherited groups.",
        "domainPack": "permission",
        "knobs": [
            {
                "id": "role",
                "label": "role",
                "binding": {"kind": "driver", "param": "role"},
                "type": "enum",
                "domain": {"values": ["viewer", "contractor"]},
                "default": "contractor",
                "scale": "linear",
                "unit": None,
                "axisRole": "x",
            },
            {
                "id": "resource",
                "label": "resource",
                "binding": {"kind": "argument", "fn": "can", "argIndex": 2},
                "type": "enum",
                "domain": {"values": ["doc", "audit-log"]},
                "default": "audit-log",
                "scale": "linear",
                "unit": None,
                "axisRole": "y",
            },
        ],
        "observables": [
            {
                "id": "allow",
                "label": "allow",
                "extractor": {"kind": "returnValue", "path": "$"},
                "render": "matrixCell",
                "compareMode": "delta",
                "unit": None,
            }
        ],
    }


def _compatible_permission_response() -> dict:
    """The corresponding role/resource/same_tenant matrix proposal after feedback."""
    response = _incompatible_permission_response()
    response["knobs"][0]["binding"] = {"kind": "argument", "fn": "can", "argIndex": 0}
    response["knobs"].append(
        {
            "id": "same_tenant",
            "label": "same tenant",
            "binding": {"kind": "argument", "fn": "can", "argIndex": 3},
            "type": "boolean",
            "domain": {"values": ["false", "true"]},
            "default": True,
            "scale": "linear",
            "unit": None,
        }
    )
    return response


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
    assert result.provenance.registryCompatibilityKickbacks == 0
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
    assert result.provenance.registryCompatibilityKickbacks == 0
    assert len(harness_calls) == 2
    assert len(fake_llm.prompts) == 2
    assert not adversary_results


def test_loop_b_terminal_inert_retains_each_delta_proposal(monkeypatch) -> None:
    """The persisted inert finding exposes both drafts that exhausted Loop B."""
    class VerifiedVerifier:
        def __init__(self, runtime):
            pass

        def verify(self, *args, **kwargs):
            return _fidelity(True)

    class InertAdversary:
        def __init__(self, runtime):
            pass

        def search(self, *args, **kwargs):
            return _inert_result()

    first = _valid_response()
    second = _valid_response()
    second["thesis"] = "A second proposed workload remained inert."
    monkeypatch.setattr(orchestrator, "FidelityVerifier", VerifiedVerifier)
    monkeypatch.setattr(orchestrator, "Adversary", InertAdversary)

    result = orchestrator.run_pipeline(
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
        FakeSandboxRuntime(),
        FakeLLMClient([first, second]),
        "fake-model",
        "low",
    )

    assert isinstance(result, orchestrator.InertResult)
    assert [proposal["thesis"] for proposal in result.proposedSpecs] == [
        first["thesis"],
        second["thesis"],
    ]


def test_unregistered_entry_point_uses_generative_path_instead_of_registry_hard_gate(
    monkeypatch,
) -> None:
    """Unknown shapes attempt generative IR; registry miss is no longer a hard stop."""
    unregistered_scope = ScopedChangeSet(
        entry_point=EntryPoint(
            file=str(FIXTURE_DIR / "head.py"),
            fn="FutureLimiter.evaluate",
            signature="FutureLimiter.evaluate(self, value: int) -> int",
        ),
        dependency_ledger=DependencyLedger(),
    )
    runtime = FakeSandboxRuntime()
    llm = FakeLLMClient([_valid_response()])
    monkeypatch.setattr(orchestrator, "scout", lambda *args: unregistered_scope)
    attempts: list[int] = []

    class GenerativeFailingHarnessEngineer:
        def generate(self, *_args, **_kwargs):
            attempts.append(1)
            raise orchestrator.GenerativeHarnessError(
                "generative harness could not be built for this entry-point shape: "
                "FutureLimiter.evaluate: unsupported dependency surface"
            )

    monkeypatch.setattr(orchestrator, "HarnessEngineer", GenerativeFailingHarnessEngineer)

    result = orchestrator.run_pipeline(
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
        runtime,
        llm,
        "fake-model",
        "low",
    )

    assert isinstance(result, orchestrator.GracefulDegradation)
    assert "generative harness could not be built" in result.reason
    assert result.reason != "no harness template registered for this entry-point shape"
    assert len(attempts) == 3
    assert runtime.created_templates == ["base"]
    assert not runtime.run_calls


def test_live_hero2_numeric_fn_proposal_kicks_back_then_degrades_without_execution() -> None:
    """An unservable direct call gets one re-selection before an honest degradation."""
    runtime = FakeSandboxRuntime()
    first_proposal = _live_hero2_numeric_fn_response()
    second_proposal = _live_hero2_numeric_fn_response()
    second_proposal["thesis"] = "The retry proposal after registry compatibility feedback."
    llm = FakeLLMClient([first_proposal, second_proposal])
    result = orchestrator.run_pipeline(
        str(HERO2_FIXTURE_DIR / "base.py"),
        str(HERO2_FIXTURE_DIR / "head.py"),
        runtime,
        llm,
        "fake-model",
        "low",
    )

    assert isinstance(result, orchestrator.GracefulDegradation)
    assert result.reason.startswith(
        "Registered-template compatibility failed after one Delta Analyst kickback, "
        "and the numeric-fn fallback is not executable for this entry point: "
    )
    assert result.loop_a_attempts == 1
    assert result.registryCompatibilityKickbacks == 1
    assert runtime.created_templates == ["base"]
    assert not runtime.run_calls
    assert len(llm.prompts) == 2
    assert "registered template for 'next_delay' expects a concurrent-retry workload" in llm.prompts[1]
    assert [proposal["thesis"] for proposal in result.proposedSpecs] == [
        first_proposal["thesis"],
        second_proposal["thesis"],
    ]
    assert [knob["binding"] for knob in result.proposedSpecs[0]["knobs"]] == [
        knob["binding"] for knob in first_proposal["knobs"]
    ]
    assert [knob["binding"] for knob in result.proposedSpecs[1]["knobs"]] == [
        knob["binding"] for knob in second_proposal["knobs"]
    ]


def test_uninstrumentable_reference_degradation_retains_both_delta_drafts(monkeypatch) -> None:
    """Both attempts survive the bounded instrumentation kickback in the terminal result."""
    first_proposal = _valid_response()
    second_proposal = _valid_response()
    second_proposal["thesis"] = "The repaired proposal after reference instrumentation feedback."

    class AlwaysUninstrumentableHarnessEngineer:
        def generate(self, *_args, **_kwargs):
            raise UninstrumentableReferenceError(
                "reference path 'extension.so' cannot be branch-instrumented"
            )

    monkeypatch.setattr(orchestrator, "HarnessEngineer", AlwaysUninstrumentableHarnessEngineer)
    result = orchestrator.run_pipeline(
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
        FakeSandboxRuntime(),
        FakeLLMClient([first_proposal, second_proposal]),
        "fake-model",
        "low",
    )

    assert isinstance(result, orchestrator.GracefulDegradation)
    assert result.registryCompatibilityKickbacks == 1
    assert [proposal["thesis"] for proposal in result.proposedSpecs] == [
        first_proposal["thesis"],
        second_proposal["thesis"],
    ]
    assert [knob["binding"] for knob in result.proposedSpecs[0]["knobs"]] == [
        knob["binding"] for knob in first_proposal["knobs"]
    ]
    assert [knob["binding"] for knob in result.proposedSpecs[1]["knobs"]] == [
        knob["binding"] for knob in second_proposal["knobs"]
    ]


def test_registry_incompatibility_kicks_back_to_delta_analyst_once(monkeypatch) -> None:
    """A schema-valid but unservable proposal gets one reason-only reselection pass."""
    class ScriptedVerifier:
        def __init__(self, runtime):
            pass

        def verify(self, *args, **kwargs):
            return _fidelity(False)

    monkeypatch.setattr(orchestrator, "FidelityVerifier", ScriptedVerifier)
    llm = FakeLLMClient([
        _incompatible_permission_response(),
        _compatible_permission_response(),
    ])
    result = orchestrator.run_pipeline(
        str(HERO3_FIXTURE_DIR / "base.py"),
        str(HERO3_FIXTURE_DIR / "head.py"),
        FakeSandboxRuntime(),
        llm,
        "fake-model",
        "low",
    )

    assert isinstance(result, orchestrator.GracefulDegradation)
    assert result.registryCompatibilityKickbacks == 1
    assert len(llm.prompts) == 2
    assert "registered template for 'can' expects a permission matrix" in llm.prompts[1]
    assert "A previous proposal was schema-valid but Lever could not execute it" in llm.prompts[1]
