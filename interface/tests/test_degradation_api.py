"""End-to-end HTTP/WebSocket coverage for every §1.10 degradation trigger."""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import domain.orchestrator as orchestrator
from domain.fidelity_verifier import DifferentialMismatch, FidelityVerification
from domain.harness_engineer import HarnessEngineer as RealHarnessEngineer
from domain.schema import (
    Agreement,
    Coverage,
    CvStabilityEstimate,
    FidelityReport,
    RelativeTolerance,
    Stability,
    SymmetristSummary,
)
from infra.fakes.fake_llm import FakeLLMClient
from infra.fakes.fake_sandbox import FakeSandboxRuntime
from infra.persistence.sqlite_adapter import SQLiteRepository
from interface.api import create_app


FIXTURES = Path(__file__).parent / "fixtures" / "degradation"


def _rate_limiter_response() -> dict:
    """Use a valid partial spec; the fixture controls only the terminal gate."""
    return {
        "thesis": "The limiter changes admissions under the sampled workload.",
        "domainPack": "rate-limiter",
        "knobs": [
            {
                "id": "limit_per_sec",
                "label": "per-tenant limit",
                "binding": {"kind": "config", "path": "limit_per_sec"},
                "type": "integer",
                "domain": {"min": 1, "max": 100, "step": 1},
                "default": 50,
                "scale": "linear",
                "unit": "requests / sec",
            },
            {
                "id": "burst",
                "label": "burst allowance",
                "binding": {"kind": "config", "path": "burst"},
                "type": "integer",
                "domain": {"min": 0, "max": 50, "step": 1},
                "default": 10,
                "scale": "linear",
                "unit": "requests",
            },
            {
                "id": "rps",
                "label": "requests per second",
                "binding": {"kind": "driver", "param": "rps"},
                "type": "integer",
                "domain": {"min": 1, "max": 10, "step": 1},
                "default": 2,
                "scale": "linear",
                "unit": "requests / sec",
            },
            {
                "id": "tenants",
                "label": "tenant count",
                "binding": {"kind": "driver", "param": "tenants"},
                "type": "integer",
                "domain": {"min": 1, "max": 16, "step": 1},
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


def _fidelity(*, agreement_rate: float, confidence: float, reason: str) -> FidelityVerification:
    """Construct a real report shape while making its intended gateway explicit."""
    matched = int(128 * agreement_rate)
    mismatch = DifferentialMismatch(
        point={"rps": 7},
        version="head",
        observable_id="admitted",
        harness_value=1,
        reference_value=7,
    )
    return FidelityVerification(
        FidelityReport(
            verdict="verified" if agreement_rate >= 0.85 and confidence >= 0.60 else "degraded",
            symmetrist=SymmetristSummary(
                passed=True, hashA="same", hashB="same", unjustifiedKeys=[]
            ),
            agreement=Agreement(
                samples=128,
                matched=matched,
                rate=agreement_rate,
                tolerance=RelativeTolerance(kind="relative", epsilon=0.01),
            ),
            stability=Stability(
                replicates=12,
                perObservable={"admitted": CvStabilityEstimate(kind="cv", value=0.0)},
            ),
            coverage=Coverage(samples=128, strategy="sobol"),
            confidence=confidence,
            band="low" if confidence < 0.60 else "high",
            degradeReason=reason,
        ),
        (mismatch,),
    )


def _app(
    tmp_path: Path,
    *,
    llm: FakeLLMClient | None = None,
    runtime: FakeSandboxRuntime | None = None,
):
    """Create the actual ASGI adapter with only external providers replaced."""
    return create_app(
        repository=SQLiteRepository(tmp_path / "sessions.sqlite3"),
        runtime_factory=(lambda: runtime) if runtime is not None else FakeSandboxRuntime,
        llm_factory=lambda _model, _effort: llm or FakeLLMClient([]),
        model="fake-model",
        reasoning_effort="low",
    )


def _submit_and_receive(client: TestClient, folder: str) -> dict:
    """Exercise POST /diffs then consume progress through its real WS terminal."""
    fixture = FIXTURES / folder
    accepted = client.post(
        "/diffs",
        json={
            "base_file_path": str(fixture / "base.py"),
            "head_file_path": str(fixture / "head.py"),
        },
    )
    assert accepted.status_code == 202
    with client.websocket_connect(f"/ws/{accepted.json()['changeId']}") as websocket:
        while True:
            event = websocket.receive_json()
            if event["type"] != "progress":
                return event


def _assert_degraded_payload(payload: dict, *, kind: str, reason_fragment: str) -> None:
    """Assert the WS payload is a distinct no-widget terminal, not generic error data."""
    assert payload["type"] == kind
    assert reason_fragment.lower() in payload["degradeReason"].lower()
    assert payload["plainExplanation"]
    assert "widgetConfig" not in payload


def _count_harness_attempts(monkeypatch) -> list[int]:
    """Spy on the real Harness Engineer while retaining its real generation behavior."""
    attempts: list[int] = []

    class CountingHarnessEngineer:
        def generate(self, *args, **kwargs):
            attempts.append(1)
            return RealHarnessEngineer().generate(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "HarnessEngineer", CountingHarnessEngineer)
    return attempts


def test_unscopable_fixture_reaches_distinct_api_terminal(tmp_path) -> None:
    """A Flask-style request signature refuses before any model or widget exists."""
    app = _app(tmp_path)
    with TestClient(app) as client:
        terminal = _submit_and_receive(client, "unscopable")

    _assert_degraded_payload(terminal, kind="unscopable", reason_fragment="request")


def test_live_identity_dependency_is_unharnessable_after_three_attempts(tmp_path, monkeypatch) -> None:
    """The actual API retries Harness Engineer three times then names the IdP boundary."""
    harness_attempts = _count_harness_attempts(monkeypatch)
    llm = FakeLLMClient([_rate_limiter_response()])
    runtime = FakeSandboxRuntime(scripted_results=[])
    app = _app(tmp_path, llm=llm, runtime=runtime)
    with TestClient(app) as client:
        terminal = _submit_and_receive(client, "unharnessable")

    _assert_degraded_payload(terminal, kind="degraded", reason_fragment="identity-provider")
    assert "3 attempts" in terminal["degradeReason"]
    assert len(harness_attempts) == 3
    assert terminal["outcome"]["loop_a_attempts"] == 3
    assert len(llm.prompts) == 1
    assert runtime.created_templates == ["base"]
    assert runtime.run_calls == []
    assert len(runtime.killed_sandbox_ids) == 1


def _scripted_verifier(monkeypatch, verification: FidelityVerification) -> list[int]:
    """Install a deterministic verifier outcome and expose every invocation."""
    verifier_calls: list[int] = []

    class ScriptedVerifier:
        def __init__(self, _runtime) -> None:
            pass

        def verify(self, *_args, **_kwargs) -> FidelityVerification:
            verifier_calls.append(1)
            return verification

    monkeypatch.setattr(orchestrator, "FidelityVerifier", ScriptedVerifier)
    return verifier_calls


def _assert_divergence_report(terminal: dict) -> None:
    """Verify the exact sampled input and both values reach the API client."""
    assert terminal["divergenceReport"] == [
        {
            "position": {"rps": 7},
            "version": "head",
            "observable": "admitted",
            "harness": 1,
            "reference": 7,
        }
    ]


def test_agreement_below_threshold_retries_harness_three_times(tmp_path, monkeypatch) -> None:
    """Fixture 3: agreement < .85 exhausts Loop A rather than taking a terminal shortcut."""
    harness_attempts = _count_harness_attempts(monkeypatch)
    verifier_calls = _scripted_verifier(
        monkeypatch,
        _fidelity(
            agreement_rate=0.5,
            confidence=0.5,
            reason="Harness and real code disagree on sampled inputs.",
        ),
    )
    llm = FakeLLMClient([_rate_limiter_response()])
    runtime = FakeSandboxRuntime(scripted_results=[])
    app = _app(tmp_path, llm=llm, runtime=runtime)
    with TestClient(app) as client:
        terminal = _submit_and_receive(client, "agreement")

    _assert_degraded_payload(terminal, kind="degraded", reason_fragment="agreement stayed below 0.85")
    _assert_divergence_report(terminal)
    assert len(harness_attempts) == 3
    assert len(verifier_calls) == 3
    assert terminal["outcome"]["loop_a_attempts"] == 3
    assert len(llm.prompts) == 1
    assert runtime.created_templates == ["base"]
    assert runtime.run_calls == []
    assert len(runtime.killed_sandbox_ids) == 1


def test_low_confidence_degrades_without_any_loop_a_retry(tmp_path, monkeypatch) -> None:
    """Fixture 4: verified agreement + low confidence exits immediately under §2.4."""
    harness_attempts = _count_harness_attempts(monkeypatch)
    verifier_calls = _scripted_verifier(
        monkeypatch,
        _fidelity(
            agreement_rate=1.0,
            confidence=0.5,
            reason="I can build a model, but it depends too heavily on values I had to guess.",
        ),
    )
    llm = FakeLLMClient([_rate_limiter_response()])
    runtime = FakeSandboxRuntime(scripted_results=[])
    app = _app(tmp_path, llm=llm, runtime=runtime)
    with TestClient(app) as client:
        terminal = _submit_and_receive(client, "confidence")

    _assert_degraded_payload(terminal, kind="degraded", reason_fragment="depends too heavily")
    _assert_divergence_report(terminal)
    assert len(harness_attempts) == 1
    assert len(verifier_calls) == 1
    assert terminal["outcome"]["loop_a_attempts"] == 1
    assert len(llm.prompts) == 1
    assert runtime.created_templates == ["base"]
    assert runtime.run_calls == []
    assert len(runtime.killed_sandbox_ids) == 1


def test_raw_diff_without_repository_context_never_starts_pipeline(tmp_path) -> None:
    """The explicit raw intake terminal is delivered over the same WS adapter."""
    invoked = False

    def never_run(*_args) -> None:
        nonlocal invoked
        invoked = True
        raise AssertionError("raw diff must not call run_pipeline")

    app = create_app(
        repository=SQLiteRepository(tmp_path / "raw.sqlite3"),
        runtime_factory=FakeSandboxRuntime,
        llm_factory=lambda _model, _effort: FakeLLMClient([]),
        pipeline_runner=never_run,
    )
    raw_diff = (FIXTURES / "raw.diff").read_text()
    with TestClient(app) as client:
        accepted = client.post("/diffs/raw", json={"diff": raw_diff})
        with client.websocket_connect(f"/ws/{accepted.json()['changeId']}") as websocket:
            terminal = websocket.receive_json()

    _assert_degraded_payload(terminal, kind="degraded", reason_fragment="no repository context")
    assert invoked is False


def test_no_executable_reference_fixture_never_starts_pipeline(tmp_path) -> None:
    """A repository without a test/reference path exits at the verifier precondition."""
    invoked = False

    def never_run(*_args) -> None:
        nonlocal invoked
        invoked = True
        raise AssertionError("missing reference must not call run_pipeline")

    app = create_app(
        repository=SQLiteRepository(tmp_path / "reference.sqlite3"),
        runtime_factory=FakeSandboxRuntime,
        llm_factory=lambda _model, _effort: FakeLLMClient([]),
        pipeline_runner=never_run,
    )
    with TestClient(app) as client:
        terminal = _submit_and_receive(client, "no_reference")

    _assert_degraded_payload(terminal, kind="degraded", reason_fragment="no executable reference")
    assert invoked is False
