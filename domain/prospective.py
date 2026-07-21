"""One-candidate source generation spliced into prospective pipeline intake."""

from __future__ import annotations

import ast
import re

from pydantic import BaseModel, Field, PrivateAttr, ValidationError

from domain.ports import LLMClient


class GeneratedCandidate(BaseModel):
    """A real Python module proposed for one user-authored prospective hypothesis."""

    source: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=280)
    _hypothesis_caveat: str | None = PrivateAttr(default=None)

    @property
    def hypothesis_caveat(self) -> str | None:
        """A deterministic disclosure when this source lacks named hypothesis evidence."""
        return self._hypothesis_caveat


class CandidateGenerationError(ValueError):
    """A generated candidate that cannot become an executable reference path."""


def generate_candidate(
    llm: LLMClient,
    current_source: str,
    hypothesis: str,
) -> GeneratedCandidate:
    """Generate exactly one executable candidate while preserving the module API.

    This is an ingestion step, not a new analytical agent.  The existing
    Scout→Delta→Harness→Fidelity pipeline receives the candidate as its head
    source and independently verifies only that generated implementation.
    """
    if not hypothesis.strip():
        raise CandidateGenerationError("A prospective hypothesis cannot be empty.")
    response = llm.complete(
        _candidate_prompt(current_source, hypothesis),
        GeneratedCandidate.model_json_schema(),
    )
    try:
        candidate = GeneratedCandidate.model_validate(response)
    except ValidationError as error:
        raise CandidateGenerationError(f"Candidate response was schema-invalid: {error}") from error
    if candidate.source == current_source:
        raise CandidateGenerationError("Candidate generation returned the unchanged current source.")
    try:
        parsed_candidate = ast.parse(candidate.source, "prospective-candidate.py")
    except SyntaxError as error:
        raise CandidateGenerationError(f"Candidate source is not executable Python: {error}") from error
    candidate._hypothesis_caveat = _hypothesis_caveat(
        hypothesis,
        parsed_candidate,
    )
    return candidate


def generate_candidates(
    llm: LLMClient,
    current_source: str,
    hypothesis: str,
    count: int = 3,
) -> tuple[GeneratedCandidate, ...]:
    """Generate `count` independently-sampled candidates for one hypothesis.

    Spec §6.2 requires 3 LLM-generated candidates rendered together against the
    current baseline, not 1. Each call to generate_candidate() is independent;
    a model may legitimately return the same source twice for a simple
    hypothesis, and that is reported honestly rather than papered over with an
    artificial-diversity retry.
    """
    return tuple(generate_candidate(llm, current_source, hypothesis) for _ in range(count))


def _hypothesis_caveat(
    hypothesis: str,
    parsed_source: ast.AST,
) -> str | None:
    """Check only named, recognizable concepts; do not pretend to judge intent.

    This deliberately small guard catches a model dropping the very concept the
    person asked to vary.  It is a disclosure mechanism, not an LLM-based
    semantic verifier and it never requests a second candidate.
    """
    normalized_hypothesis = hypothesis.casefold()
    missing: list[str] = []
    if re.search(r"\bburst\b", normalized_hypothesis) and not _has_burst_identifier(parsed_source):
        missing.append("a burst-related identifier or parameter")
    if re.search(r"\bper[- ]tenant\b", normalized_hypothesis) and not _has_tenant_keyed_state(parsed_source):
        missing.append("tenant-keyed state")
    if not missing:
        return None
    details = " and ".join(missing)
    return (
        "This candidate may not fully reflect your hypothesis: it does not retain "
        f"{details}."
    )


def _has_burst_identifier(parsed_source: ast.AST) -> bool:
    """Recognize a parameter, field, or local whose identifier retains ``burst``."""
    for node in ast.walk(parsed_source):
        identifier = (
            node.id
            if isinstance(node, ast.Name)
            else node.attr
            if isinstance(node, ast.Attribute)
            else node.arg
            if isinstance(node, ast.arg)
            else ""
        )
        if "burst" in identifier.casefold():
            return True
    return False


def _has_tenant_keyed_state(parsed_source: ast.AST) -> bool:
    """Recognize common dict/defaultdict operations keyed by a tenant identifier."""
    for node in ast.walk(parsed_source):
        if isinstance(node, ast.Subscript) and _contains_tenant_name(node.slice):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "setdefault", "pop"}
            and node.args
            and _contains_tenant_name(node.args[0])
        ):
            return True
    return False


def _contains_tenant_name(node: ast.AST) -> bool:
    """Return whether an AST expression contains an identifier naming a tenant."""
    return any(
        isinstance(child, ast.Name) and "tenant" in child.id.casefold()
        for child in ast.walk(node)
    )


def _candidate_prompt(current_source: str, hypothesis: str) -> str:
    """Tell the constrained generator to return code rather than a prose suggestion."""
    return f"""\
You generate one prospective Python implementation for Lever. The user has not
written this code yet. Apply the hypothesis to the current module, preserving
the module's public callable names and compatible parameter signatures so the
existing executable harness can invoke it. Return a complete executable Python
module, not a patch, markdown fence, explanation, test, or pseudocode.

Hypothesis:
{hypothesis}

Current module:
```python
{current_source}
```

Return one JSON object matching the response schema. Its `source` must contain
only the candidate module source; `summary` must state the candidate change.
"""
