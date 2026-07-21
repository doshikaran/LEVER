"""Mechanical domain-pack translation from InteractionSpec to frontend widget data."""

from typing import Any, Iterable, Literal

from pydantic import BaseModel

from domain.schema import (
    DomainPackId,
    InteractionSpec,
    KnobPosition,
    NamedPosition,
    SurpriseMarker,
)
from domain.world_director import WorldSpec, build_world_spec


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
    render: Literal["timeseries", "matrixCell", "scalar", "nodeState"]
    compareMode: Literal["overlay", "delta", "ratio"]
    unit: str | None
    yAxisZeroAnchored: Literal[True] = True


class UnionTreeNode(BaseModel):
    """One empirically observed source-tagged predicate in a single union tree."""

    tag: str
    baseOutcomes: list[bool]
    headOutcomes: list[bool]
    positions: list[KnobPosition]
    baseTouched: bool
    headTouched: bool


class UnionTreeDescriptor(BaseModel):
    """A cache-derived, shared-input path view; never two independently aligned trees."""

    observableId: str
    label: str
    render: Literal["unionTree"] = "unionTree"
    nodes: list[UnionTreeNode]
    forkTag: str | None


class WidgetConfig(BaseModel):
    """Plain serializable data the frontend needs to render an honest widget."""

    domainPack: Literal[
        "rate-limiter", "permission", "numeric-fn", "decision-tree", "state-machine"
    ]
    thesis: str
    controls: list[ControlDescriptor]
    charts: list[ChartDescriptor]
    unionTree: UnionTreeDescriptor | None = None
    worldSpec: WorldSpec
    initialPosition: KnobPosition
    surpriseMarker: SurpriseMarker | None
    presets: list[NamedPosition]
    fidelityBand: Literal["high", "medium", "low"]
    fidelityConfidence: float
    # This is a rendering-mode discriminator, not a cosmetic flag.  The
    # frontend must route it to the prospective-only component tree.
    speculative: bool = False
    # A deterministic, named-concept caveat about generated source fidelity.
    hypothesisCaveat: str | None = None


def synthesize(
    spec: InteractionSpec,
    cached_positions: Iterable[Any] = (),
) -> WidgetConfig:
    """Mechanically generate a widget; decision trees use only measured cached paths."""
    supported_packs = {
        DomainPackId.RATE_LIMITER,
        DomainPackId.PERMISSION,
        DomainPackId.NUMERIC_FN,
        DomainPackId.DECISION_TREE,
        DomainPackId.STATE_MACHINE,
    }
    if spec.domainPack not in supported_packs:
        raise NotImplementedError(
            f"Synthesizer does not implement {spec.domainPack.value!r} yet"
        )
    if len(spec.observables) != 1:
        raise ValueError(f"{spec.domainPack.value} requires exactly one observable")
    observable = spec.observables[0]
    _validate_supported_pack(spec, observable.render, observable.compareMode)

    union_tree = (
        _union_tree(observable.id, observable.label, spec.initialPosition, cached_positions)
        if spec.domainPack is DomainPackId.DECISION_TREE
        else None
    )
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
        charts=([] if union_tree is not None else [
            ChartDescriptor(
                observableId=observable.id,
                label=observable.label,
                render=observable.render,
                compareMode=observable.compareMode,
                unit=observable.unit,
            )
        ]),
        unionTree=union_tree,
        worldSpec=build_world_spec(spec),
        initialPosition=spec.initialPosition,
        surpriseMarker=spec.surpriseMarker,
        presets=list(spec.presets or []),
        fidelityBand=spec.fidelity.band,
        fidelityConfidence=spec.fidelity.confidence,
        speculative=spec.provenance.speculative,
        hypothesisCaveat=spec.provenance.hypothesisCaveat,
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
    if spec.domainPack is DomainPackId.DECISION_TREE and render != "pathTrace":
        raise ValueError("decision-tree requires a pathTrace observable")
    if spec.domainPack is DomainPackId.STATE_MACHINE and render != "nodeState":
        raise ValueError("state-machine requires a nodeState observable")

def _union_tree(
    observable_id: str,
    label: str,
    initial_position: KnobPosition,
    cached_positions: Iterable[Any],
) -> UnionTreeDescriptor:
    """Reconstruct a union of observed paths from Adversary's cache, with no CFG inference."""
    nodes: dict[str, dict[str, Any]] = {}
    initial_base: list[Any] = []
    initial_head: list[Any] = []
    for entry in cached_positions:
        position, observations = _cache_entry(entry)
        if position is None or observations is None:
            continue
        base_path = _path_for(observations, "base", observable_id)
        head_path = _path_for(observations, "head", observable_id)
        if position == initial_position:
            initial_base, initial_head = base_path, head_path
        for version, path in (("base", base_path), ("head", head_path)):
            for decision in path:
                tag, outcome = _decision(decision)
                if tag is None or outcome is None:
                    continue
                node = nodes.setdefault(
                    tag,
                    {
                        "tag": tag,
                        "baseOutcomes": [],
                        "headOutcomes": [],
                        "positions": [],
                        "baseTouched": False,
                        "headTouched": False,
                    },
                )
                node[f"{version}Touched"] = True
                if outcome not in node[f"{version}Outcomes"]:
                    node[f"{version}Outcomes"].append(outcome)
                if position not in node["positions"]:
                    node["positions"].append(position)
    return UnionTreeDescriptor(
        observableId=observable_id,
        label=label,
        nodes=[UnionTreeNode.model_validate(node) for node in nodes.values()],
        forkTag=_first_fork_tag(initial_base, initial_head),
    )


def _cache_entry(entry: Any) -> tuple[KnobPosition | None, Any | None]:
    """Accept domain cache objects and serialized cache entries without importing Adversary."""
    position = getattr(entry, "position", None)
    observations = getattr(entry, "observations", None)
    if position is None and isinstance(entry, dict):
        position = entry.get("position")
        observations = entry.get("observations")
    if isinstance(position, dict):
        position = KnobPosition(position)
    return (position if isinstance(position, KnobPosition) else None, observations)


def _path_for(observations: Any, version: str, observable_id: str) -> list[Any]:
    """Read one path vector from a cache observation without converting it to a CFG."""
    values = getattr(observations, version, None)
    if values is None and isinstance(observations, dict):
        values = observations.get(version)
    path = values.get(observable_id) if isinstance(values, dict) else None
    return path if isinstance(path, list) else []


def _decision(value: Any) -> tuple[str | None, bool | None]:
    """Extract one source tag/outcome pair from JSON or the Pydantic trace model."""
    if isinstance(value, dict):
        tag, outcome = value.get("tag"), value.get("outcome")
    else:
        tag, outcome = getattr(value, "tag", None), getattr(value, "outcome", None)
    return (tag if isinstance(tag, str) else None, outcome if isinstance(outcome, bool) else None)


def _first_fork_tag(base_path: list[Any], head_path: list[Any]) -> str | None:
    """Locate the first empirically observed decision-vector mismatch at the shared input."""
    width = max(len(base_path), len(head_path))
    for index in range(width):
        base = base_path[index] if index < len(base_path) else None
        head = head_path[index] if index < len(head_path) else None
        if base != head:
            base_tag, _ = _decision(base)
            head_tag, _ = _decision(head)
            return head_tag or base_tag
    return None


__all__ = [
    "ChartDescriptor",
    "ControlDescriptor",
    "UnionTreeDescriptor",
    "UnionTreeNode",
    "WidgetConfig",
    "WorldSpec",
    "synthesize",
]
