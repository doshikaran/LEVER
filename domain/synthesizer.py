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
    """One observable view with its rendering-fidelity invariant embedded."""

    observableId: str
    label: str
    render: Literal["timeseries", "matrixCell", "scalar"]
    compareMode: Literal["overlay", "delta", "ratio"]
    unit: str | None
    yAxisZeroAnchored: Literal[True] = True


class WidgetConfig(BaseModel):
    """Plain serializable data the frontend needs to render a verified widget."""

    domainPack: Literal["rate-limiter", "permission", "numeric-fn"]
    thesis: str
    controls: list[ControlDescriptor]
    charts: list[ChartDescriptor]
    initialPosition: KnobPosition
    surpriseMarker: SurpriseMarker | None
    presets: list[NamedPosition]
    fidelityBand: Literal["high", "medium", "low"]
    fidelityConfidence: float


def synthesize(spec: InteractionSpec) -> WidgetConfig:
    """Mechanically generate a supported, verified frontend widget contract."""
    supported_packs = {
        DomainPackId.RATE_LIMITER,
        DomainPackId.PERMISSION,
        DomainPackId.NUMERIC_FN,
    }
    if spec.domainPack not in supported_packs:
        raise NotImplementedError(
            f"Synthesizer does not implement {spec.domainPack.value!r} yet"
        )
    if len(spec.observables) != 1:
        raise ValueError(f"{spec.domainPack.value} requires exactly one observable")
    observable = spec.observables[0]
    _validate_supported_pack(spec, observable.render, observable.compareMode)

    return WidgetConfig(
        domainPack=spec.domainPack.value,
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
                render=observable.render,
                compareMode=observable.compareMode,
                unit=observable.unit,
            )
        ],
        initialPosition=spec.initialPosition,
        surpriseMarker=spec.surpriseMarker,
        presets=list(spec.presets or []),
        fidelityBand=spec.fidelity.band,
        fidelityConfidence=spec.fidelity.confidence,
    )


def _validate_supported_pack(
    spec: InteractionSpec,
    render: str,
    compare_mode: str,
) -> None:
    """Keep the small set of executable fallback views faithful to their pack contracts."""
    if spec.domainPack is DomainPackId.RATE_LIMITER:
        if render != "timeseries" or compare_mode != "overlay":
            raise ValueError("rate-limiter requires a timeseries observable in overlay mode")
        if not any(knob.binding.kind == "driver" for knob in spec.knobs):
            raise ValueError("rate-limiter requires at least one driver-bound knob")
        return
    if spec.domainPack is DomainPackId.PERMISSION:
        if render != "matrixCell":
            raise ValueError("permission requires a matrixCell observable")
        return
    if spec.domainPack is DomainPackId.NUMERIC_FN and render != "scalar":
        raise ValueError("numeric-fn requires a scalar observable")


__all__ = ["ChartDescriptor", "ControlDescriptor", "WidgetConfig", "synthesize"]
