"""No-network coverage for Delta Analyst proposal validation and fallback."""

from pathlib import Path

import pytest

from domain.delta_analyst import analyze_delta
from domain.pack_registry import PACK_REGISTRY
from domain.ports import LLMClient
from domain.schema import DependencyLedger, DomainPackId, EntryPoint, ScopedChangeSet
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
    assert "Enabled domain-pack arity contracts (only these packs are selectable)" in fake.prompts[0]
    contracts = fake.prompts[0].split("Enabled domain-pack arity contracts", 1)[1]
    assert "decision-tree:" not in contracts


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


def test_disabled_decision_tree_proposal_is_rejected_then_falls_back_to_numeric_fn(
    hero_scope: ScopedChangeSet, hero_sources: tuple[str, str]
) -> None:
    """C-6 makes an enum value for an unbuilt pack unselectable before templating."""
    decision_tree = {
        "thesis": "A branch changes which route is selected.",
        "domainPack": "decision-tree",
        "knobs": [
            {
                "id": "input",
                "label": "input",
                "binding": {
                    "kind": "argument",
                    "fn": "RateLimiter.admit",
                    "argIndex": 0,
                },
                "type": "integer",
                "domain": {"min": 0, "max": 1, "step": 1},
                "default": 0,
                "scale": "linear",
                "unit": None,
            },
            {
                "id": "enabled",
                "label": "enabled",
                "binding": {
                    "kind": "argument",
                    "fn": "RateLimiter.admit",
                    "argIndex": 1,
                },
                "type": "boolean",
                "domain": {"values": ["false", "true"]},
                "default": False,
                "scale": "linear",
                "unit": None,
            },
        ],
        "observables": [
            {
                "id": "path",
                "label": "path",
                "extractor": {"kind": "path", "instrumentation": "branch"},
                "render": "pathTrace",
                "compareMode": "overlay",
                "unit": None,
            }
        ],
    }
    fake = FakeLLMClient([decision_tree, decision_tree])

    result = analyze_delta(fake, hero_scope, *hero_sources)

    assert PACK_REGISTRY[DomainPackId.DECISION_TREE].enabled is False
    assert result.domainPack.value == "numeric-fn"
    assert PACK_REGISTRY[result.domainPack].enabled is True
    assert len(fake.prompts) == 2
    assert "decision-tree is disabled and cannot be selected" in fake.prompts[1]
