"""Availability and arity metadata for selectable Interaction Spec packs."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from domain.schema import DomainPackId


@dataclass(frozen=True)
class PackRegistration:
    """One pack's current availability and Delta Analyst arity contract."""

    enabled: bool
    arity_contract: str


PACK_REGISTRY: Mapping[DomainPackId, PackRegistration] = MappingProxyType(
    {
        DomainPackId.RATE_LIMITER: PackRegistration(
            enabled=True,
            arity_contract=(
                'at least one knob whose binding.kind is "driver"; exactly one '
                "timeseries observable; no knob may have axisRole."
            ),
        ),
        DomainPackId.PERMISSION: PackRegistration(
            enabled=True,
            arity_contract=(
                'at least two enum knobs; exactly one enum knob has axisRole "x" '
                'and exactly one enum knob has axisRole "y"; exactly one '
                "matrixCell observable."
            ),
        ),
        DomainPackId.STATE_MACHINE: PackRegistration(
            enabled=True,
            arity_contract=(
                "at least one enum knob (the event); exactly one nodeState "
                "observable; no knob may have axisRole."
            ),
        ),
        DomainPackId.NUMERIC_FN: PackRegistration(
            enabled=True,
            arity_contract=(
                'at least one scalar knob with axisRole "x"; exactly one scalar '
                "observable."
            ),
        ),
        DomainPackId.DECISION_TREE: PackRegistration(
            enabled=True,
            arity_contract=(
                "two to four knobs of any supported type; exactly one pathTrace "
                "observable; no knob may have axisRole."
            ),
        ),
    }
)


def enabled_arity_contracts() -> str:
    """Render only currently selectable packs for Delta Analyst's constrained prompt."""
    return "\n".join(
        f"{pack.value}: {registration.arity_contract}"
        for pack, registration in PACK_REGISTRY.items()
        if registration.enabled
    )


def disabled_pack_error(pack: DomainPackId) -> str | None:
    """Explain a C-6 rejection, including the actual selectable pack set."""
    registration = PACK_REGISTRY.get(pack)
    if registration is None:
        return f"Unsupported domain pack: {pack.value}."
    if registration.enabled:
        return None
    enabled = ", ".join(
        registered_pack.value
        for registered_pack, candidate in PACK_REGISTRY.items()
        if candidate.enabled
    )
    return f"{pack.value} is disabled and cannot be selected; enabled packs are: {enabled}."


__all__ = [
    "PACK_REGISTRY",
    "PackRegistration",
    "disabled_pack_error",
    "enabled_arity_contracts",
]
