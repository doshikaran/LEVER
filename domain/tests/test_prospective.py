"""Prospective ingestion creates an executable source candidate through the LLM port."""

import pytest

from domain.prospective import CandidateGenerationError, generate_candidate, generate_candidates
from infra.fakes.fake_llm import FakeLLMClient


def test_generation_returns_one_real_candidate_module() -> None:
    """The generated source is compiled before any downstream pipeline work begins."""
    current = "def delay(attempt: int) -> int:\n    return 1\n"
    candidate = "def delay(attempt: int) -> int:\n    return 2 ** attempt\n"
    llm = FakeLLMClient([{"source": candidate, "summary": "Uses exponential delay."}])

    result = generate_candidate(llm, current, "what if retry delay were exponential?")

    assert result.source == candidate
    assert result.summary == "Uses exponential delay."
    assert len(llm.prompts) == 1
    assert "what if retry delay were exponential?" in llm.prompts[0]


def test_generation_rejects_non_executable_source() -> None:
    """A malformed candidate degrades instead of reaching the harness as fake code."""
    llm = FakeLLMClient([{"source": "def nope(:\n", "summary": "Broken."}])

    with pytest.raises(CandidateGenerationError, match="not executable Python"):
        generate_candidate(llm, "def current(): pass\n", "change it")


def test_generation_discloses_when_named_burst_evidence_is_missing() -> None:
    """One candidate remains one candidate, but cannot overclaim a burst hypothesis."""
    source_without_burst = """\
class RateLimiter:
    def __init__(self, limit_per_sec: int):
        self.limit = limit_per_sec
        self.windows = {}

    def admit(self, tenant_id: str, now: float) -> bool:
        count = self.windows.get(tenant_id, 0)
        self.windows[tenant_id] = count + 1
        return count < self.limit
"""
    llm = FakeLLMClient([{"source": source_without_burst, "summary": "Tenant scoped."}])

    result = generate_candidate(
        llm,
        "class RateLimiter:\n    pass\n",
        "what if the burst allowance were per-tenant instead of shared?",
    )

    assert result.hypothesis_caveat == (
        "This candidate may not fully reflect your hypothesis: it does not retain "
        "a burst-related identifier or parameter."
    )
    assert len(llm.prompts) == 1


def test_generation_accepts_named_burst_and_tenant_keyed_state() -> None:
    """The lightweight structural guard does not caveat the expected evidence."""
    source_with_burst = """\
class RateLimiter:
    def __init__(self, limit_per_sec: int, burst: int = 0):
        self.limit = limit_per_sec
        self.burst = burst
        self.burst_by_tenant = {}

    def admit(self, tenant_id: str, now: float) -> bool:
        used = self.burst_by_tenant.get(tenant_id, 0)
        self.burst_by_tenant[tenant_id] = used + 1
        return used < self.burst
"""
    llm = FakeLLMClient([{"source": source_with_burst, "summary": "Tenant burst."}])

    result = generate_candidate(
        llm,
        "class RateLimiter:\n    pass\n",
        "what if the burst allowance were per-tenant instead of shared?",
    )

    assert result.hypothesis_caveat is None


def test_generate_candidates_returns_exactly_three() -> None:
    """Spec §6.2 requires 3 independently-sampled candidates rendered together."""
    llm = FakeLLMClient(responses=[
        {"source": "def f(): return 1", "summary": "s1"},
        {"source": "def f(): return 2", "summary": "s2"},
        {"source": "def f(): return 3", "summary": "s3"},
    ])
    candidates = generate_candidates(llm, "def f(): return 0", "make it return something else")
    assert len(candidates) == 3
    assert len({candidate.source for candidate in candidates}) == 3  # genuinely distinct


def test_generate_candidates_calls_generate_candidate_count_times() -> None:
    """Each candidate is one independent LLM completion, not one call fanned out."""
    llm = FakeLLMClient(responses=[
        {"source": "def f(): return 1", "summary": "s1"},
        {"source": "def f(): return 2", "summary": "s2"},
    ])
    candidates = generate_candidates(llm, "def f(): return 0", "vary it", count=2)
    assert len(candidates) == 2
    assert len(llm.prompts) == 2
