"""Mechanical domain-pack translation from InteractionSpec to frontend widget data."""

from typing import Any, Literal

from pydantic import BaseModel

from domain.schema import (
    DomainPackId,
    InteractionSpec,
    KnobPosition,
    NamedPosition,
    SurpriseMarker,
)


class ControlDescriptor(BaseModel):
    """One frontend control faithfully derived from a spec knob."""

    id: str
    label: str
    binding: dict[str, Any]
    type: Literal["scalar", "integer", "enum", "boolean"]
    domain: dict[str, Any]
    default: float | str | bool
    scale: Literal["linear", "log"]
    unit: str | None
    axisRole: Literal["x", "y"] | None


class ChartDescriptor(BaseModel):
    """A rate-limiter overlay chart with rendering-fidelity invariants embedded."""

    observableId: str
    label: str
    render: Literal["timeseries"]
    compareMode: Literal["overlay"]
    unit: str | None
    yAxisZeroAnchored: Literal[True] = True


class WidgetConfig(BaseModel):
    """Plain serializable data the frontend needs to render a verified widget."""

    domainPack: Literal["rate-limiter"]
    thesis: str
    controls: list[ControlDescriptor]
    charts: list[ChartDescriptor]
    initialPosition: KnobPosition
    surpriseMarker: SurpriseMarker | None
    presets: list[NamedPosition]
    fidelityBand: Literal["high", "medium", "low"]
    fidelityConfidence: float


def synthesize(spec: InteractionSpec) -> WidgetConfig:
    """Mechanically generate the rate-limiter widget contract from a complete spec."""
    if spec.domainPack is not DomainPackId.RATE_LIMITER:
        raise NotImplementedError(
            f"Synthesizer currently implements the rate-limiter pack, not {spec.domainPack.value!r}"
        )
    if len(spec.observables) != 1:
        raise ValueError("rate-limiter requires exactly one observable")
    observable = spec.observables[0]
    if observable.render != "timeseries" or observable.compareMode != "overlay":
        raise ValueError("rate-limiter requires a timeseries observable in overlay mode")
    if not any(knob.binding.kind == "driver" for knob in spec.knobs):
        raise ValueError("rate-limiter requires at least one driver-bound knob")

    return WidgetConfig(
        domainPack="rate-limiter",
        thesis=spec.thesis,
        controls=[
            ControlDescriptor(
                id=knob.id,
                label=knob.label,
                binding=knob.binding.model_dump(mode="json"),
                type=knob.type,
                domain=knob.domain.model_dump(mode="json"),
                default=knob.default,
                scale=knob.scale,
                unit=knob.unit,
                axisRole=knob.axisRole,
            )
            for knob in spec.knobs
        ],
        charts=[
            ChartDescriptor(
                observableId=observable.id,
                label=observable.label,
                render="timeseries",
                compareMode="overlay",
                unit=observable.unit,
            )
        ],
        initialPosition=spec.initialPosition,
        surpriseMarker=spec.surpriseMarker,
        presets=list(spec.presets or []),
        fidelityBand=spec.fidelity.band,
        fidelityConfidence=spec.fidelity.confidence,
    )


__all__ = ["ChartDescriptor", "ControlDescriptor", "WidgetConfig", "synthesize"]
