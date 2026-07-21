"""Versioned stub catalog and Assayer uncertainty plans for generative harnesses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from domain.schema import DepEntry, DependencyLedger


_LIVE_IDENTITY_MARKERS = frozenset({"auth0", "identity", "idp", "oauth", "saml"})


@dataclass(frozen=True)
class UncertaintySpec:
    """One Assayer perturbation declaration for a stubbed parameter."""

    default: Any
    distribution: str


@dataclass(frozen=True)
class StubParameter:
    """A named uncertainty parameter belonging to one stubbed dependency."""

    name: str
    spec: UncertaintySpec


@dataclass(frozen=True)
class StubRecipe:
    """How one dependency kind is stubbed and measured."""

    kind: str
    parameters: tuple[StubParameter, ...]
    install_hint: str


@dataclass(frozen=True)
class PlannedStub:
    """One concrete dependency stub selected for a harness pair."""

    dependency: str
    kind: str
    parameters: Mapping[str, UncertaintySpec]

    def as_dict(self) -> dict[str, Any]:
        """JSON form embedded identically in both A/B harness sources."""
        return {
            "kind": self.kind,
            "parameters": {
                name: {"default": spec.default, "distribution": spec.distribution}
                for name, spec in self.parameters.items()
            },
        }


@dataclass(frozen=True)
class StubPlan:
    """The full stub set for one scoped change, or an unharnessable refusal."""

    stubs: tuple[PlannedStub, ...]
    unharnessable_dependency: str | None = None
    unharnessable_reason: str | None = None

    @property
    def is_unharnessable(self) -> bool:
        return self.unharnessable_dependency is not None


_IO_PARAMETERS = (
    StubParameter("latency_ms", UncertaintySpec(5, "log-uniform [2 ms, 20 ms]")),
    StubParameter(
        "cold_cache_probability", UncertaintySpec(0.0, "uniform [0.0, 0.3]")
    ),
    StubParameter(
        "default_return",
        UncertaintySpec("type zero-value", "{zero-value, empty, plausible-nonempty}"),
    ),
    StubParameter(
        "gc_pause_ms_per_100_ops",
        UncertaintySpec(0, "uniform [0, 5] ms per 100 ops"),
    ),
)

STUB_CATALOG: Mapping[str, StubRecipe] = {
    "clock": StubRecipe(
        kind="clock",
        parameters=(
            StubParameter(
                "resolution_ms", UncertaintySpec(1, "discrete {0.1, 1, 10} ms")
            ),
        ),
        install_hint="Replace wall-clock reads with a seeded monotonic simulator.",
    ),
    "random": StubRecipe(
        kind="random",
        parameters=(StubParameter("seed", UncertaintySpec("fixed", "H(baseSeed, i)")),),
        install_hint="Seed random streams identically for A and B within each replicate.",
    ),
    "network": StubRecipe(
        kind="network",
        parameters=_IO_PARAMETERS,
        install_hint="Return canned HTTP payloads with declared latency uncertainty.",
    ),
    "db": StubRecipe(
        kind="db",
        parameters=_IO_PARAMETERS,
        install_hint="Serve an in-memory table with declared latency uncertainty.",
    ),
    "io": StubRecipe(
        kind="io",
        parameters=_IO_PARAMETERS,
        install_hint="Redirect filesystem IO into the sandbox temp tree.",
    ),
    "native": StubRecipe(
        kind="native",
        parameters=_IO_PARAMETERS,
        install_hint="Refuse unless allowlisted; native extensions are unharnessable by default.",
    ),
}


def stub_catalog_prompt() -> str:
    """Describe the stub library for LLM harness proposers."""
    lines = []
    for kind, recipe in STUB_CATALOG.items():
        params = ", ".join(
            f"{item.name}={item.spec.default!r} ({item.spec.distribution})"
            for item in recipe.parameters
        )
        lines.append(f"- {kind}: {recipe.install_hint} Parameters: {params}")
    return "\n".join(lines)


def stub_plan(
    ledger: DependencyLedger,
    *,
    skip_kinds: frozenset[str] | set[str] | None = None,
) -> StubPlan:
    """Build a pair-symmetric stub plan from Scout's dependency ledger."""
    skipped = frozenset(skip_kinds or ())
    planned: list[PlannedStub] = []
    for entry in ledger.entries:
        if entry.kind == "pure" or entry.kind in skipped:
            continue
        blocked = _unharnessable_reason(entry)
        if blocked is not None:
            return StubPlan(
                stubs=(),
                unharnessable_dependency=entry.name,
                unharnessable_reason=blocked,
            )
        recipe = STUB_CATALOG.get(entry.kind)
        if recipe is None:
            return StubPlan(
                stubs=(),
                unharnessable_dependency=entry.name,
                unharnessable_reason=(
                    f"No stub recipe is registered for dependency kind `{entry.kind}` "
                    f"({entry.name})."
                ),
            )
        planned.append(
            PlannedStub(
                dependency=entry.name,
                kind=entry.kind,
                parameters={item.name: item.spec for item in recipe.parameters},
            )
        )
    return StubPlan(stubs=tuple(planned))


def _unharnessable_reason(entry: DepEntry) -> str | None:
    """Refuse live identity providers and native extensions by default."""
    lowered = entry.name.lower()
    if entry.kind == "network" and any(marker in lowered for marker in _LIVE_IDENTITY_MARKERS):
        return (
            f"Cannot safely stub live identity-provider dependency `{entry.name}`; "
            "the generated substitute would change authentication behavior"
        )
    if entry.kind == "native":
        return (
            f"Cannot safely stub native dependency `{entry.name}` without an allowlisted "
            "replacement that preserves observable semantics"
        )
    return None


__all__ = [
    "PlannedStub",
    "STUB_CATALOG",
    "StubParameter",
    "StubPlan",
    "StubRecipe",
    "UncertaintySpec",
    "stub_catalog_prompt",
    "stub_plan",
]
