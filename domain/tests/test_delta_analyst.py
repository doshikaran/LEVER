"""No-network coverage for Delta Analyst proposal validation and fallback."""

from pathlib import Path

import pytest

from domain.delta_analyst import analyze_delta
from domain.ports import LLMClient
from domain.schema import DependencyLedger, EntryPoint, ScopedChangeSet
from infra.fakes.fake_llm import FakeLLMClient


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero1"


@pytest.fixture
def hero_scope() -> ScopedChangeSet:
    """A representative scoped Hero 1 entry point for Delta Analyst input."""
    return ScopedChangeSet(
        entry_point=EntryPoint(
            file=str(FIXTURE_DIR / "head.py"),
            fn="RateLimiter.admit",
            signature="RateLimiter.admit(self, tenant_id: str, now: float) -> bool",
        ),
        dependency_ledger=DependencyLedger(),
    )


@pytest.fixture
def hero_sources() -> tuple[str, str]:
    """The two scoped source versions supplied to the LLM-backed analyst."""
    return (
        (FIXTURE_DIR / "base.py").read_text(encoding="utf-8"),
        (FIXTURE_DIR / "head.py").read_text(encoding="utf-8"),
    )


def test_delta_analyst_accepts_valid_rate_limiter_response(
    hero_scope: ScopedChangeSet, hero_sources: tuple[str, str]
) -> None:
    """The valid canned proposal needs one LLM call and retains its pack."""
    fake = FakeLLMClient.valid_rate_limiter()
    assert isinstance(fake, LLMClient)

    result = analyze_delta(fake, hero_scope, *hero_sources)

    assert result.domainPack.value == "rate-limiter"
    assert result.knobs[0].binding.kind == "driver"
    assert result.observables[0].render == "timeseries"
    assert len(fake.prompts) == 1
    assert "Full InteractionSpec JSON Schema" in fake.prompts[0]
    assert "Scoped base source" in fake.prompts[0]
    assert "All five enabled domain-pack arity contracts" in fake.prompts[0]


def test_delta_analyst_reprompts_once_with_arity_error_then_corrects(
    hero_scope: ScopedChangeSet, hero_sources: tuple[str, str]
) -> None:
    """The specific contract error is supplied to exactly one retry prompt."""
    fake = FakeLLMClient.arity_then_correct()

    result = analyze_delta(fake, hero_scope, *hero_sources)

    assert result.domainPack.value == "rate-limiter"
    assert len(result.knobs) == 1
    assert len(result.observables) == 1
    assert len(fake.prompts) == 2
    assert "rate-limiter requires at least one knob with binding.kind 'driver'." in fake.prompts[1]


def test_delta_analyst_exhausts_one_retry_then_uses_numeric_fallback(
    hero_scope: ScopedChangeSet, hero_sources: tuple[str, str]
) -> None:
    """Two cap violations consume the retry and produce the mandated fallback."""
    fake = FakeLLMClient.exhaust_retries()

    result = analyze_delta(fake, hero_scope, *hero_sources)

    assert result.domainPack.value == "numeric-fn"
    assert len(result.knobs) == 1
    assert result.knobs[0].type == "scalar"
    assert result.knobs[0].axisRole == "x"
    assert result.knobs[0].binding.model_dump() == {
        "kind": "argument",
        "fn": "RateLimiter.admit",
        "argIndex": 0,
    }
    assert len(result.observables) == 1
    assert result.observables[0].render == "scalar"
    assert len(fake.prompts) == 2
    assert (
        "you proposed 5 knobs, the maximum is 4 — "
        "select only the most behaviorally relevant."
    ) in fake.prompts[1]
