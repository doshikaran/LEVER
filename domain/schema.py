"""Pydantic schemas shared by deterministic domain analysis components."""

from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, Field, RootModel


DependencyKind = Literal["pure", "io", "clock", "random", "network", "db", "native"]


class AstNodeRef(BaseModel):
    """Stable source location for a Tree-sitter node involved in a change."""

    kind: str
    start_byte: int
    end_byte: int
    name: str | None = None


class EntryPoint(BaseModel):
    """A plain-data callable selected as the scoped execution entry point."""

    file: str | None = None
    fn: str
    signature: str


class DepEntry(BaseModel):
    """A statically discovered dependency and its deterministic classification."""

    name: str
    kind: DependencyKind
    depth: int = Field(ge=1)


class DependencyLedger(BaseModel):
    """Dependencies reachable from the selected entry point."""

    entries: list[DepEntry] = Field(default_factory=list)


class ScopedChangeSet(BaseModel):
    """The bounded behavioral scope passed from Scout to later pipeline stages."""

    entry_point: EntryPoint | None = None
    changed_nodes: list[AstNodeRef] = Field(default_factory=list)
    reachable_nodes: list[AstNodeRef] = Field(default_factory=list)
    dependency_ledger: DependencyLedger = Field(default_factory=DependencyLedger)
    reach_depth: int = Field(default=0, ge=0, le=2)
    unscopable: bool = False
    reason: str | None = None


class DomainPackId(str, Enum):
    """Interaction-spec discriminator; each member documents its arity contract."""

    def __new__(cls, value: str, requirement: str):
        member = str.__new__(cls, value)
        member._value_ = value
        member.__doc__ = requirement
        return member

    RATE_LIMITER = (
        "rate-limiter",
        'Requires ≥1 knob with binding.kind === "driver"; exactly 1 "timeseries" observable.',
    )
    STATE_MACHINE = (
        "state-machine",
        'Requires ≥1 "enum" knob (the event); 1 "nodeState" observable.',
    )
    PERMISSION = (
        "permission",
        'Requires ≥2 "enum" knobs with axisRole set ("x" = subject, "y" = resource); '
        '1 "matrixCell" observable.',
    )
    DECISION_TREE = (
        "decision-tree",
        'Requires 2–4 knobs, any mix of types (enum/scalar/boolean); exactly 1 "pathTrace" observable.',
    )
    NUMERIC_FN = (
        "numeric-fn",
        'Requires ≥1 "scalar" knob (axisRole: "x"); 1 "scalar" observable.',
    )


class NumericDomain(BaseModel):
    """The numeric branch of Knob.domain."""

    min: float
    max: float
    step: float


class EnumDomain(BaseModel):
    """The enum-values branch of Knob.domain."""

    values: list[str]


class ArgumentBinding(BaseModel):
    """Binds a knob to a positional argument of the entry function."""

    kind: Literal["argument"]
    fn: str
    argIndex: int


class ConfigBinding(BaseModel):
    """Binds a knob to a dotted stub-config key or a direct constructor/argument field introduced or changed by the diff; Symmetrist enforces byte identity only for environmental fakes."""

    kind: Literal["config"]
    path: str


class DriverBinding(BaseModel):
    """Binds a knob to a workload-driver parameter."""

    kind: Literal["driver"]
    param: str


ParamBinding: TypeAlias = Annotated[
    ArgumentBinding | ConfigBinding | DriverBinding,
    Field(discriminator="kind"),
]


# Positions may deliberately include an adversarial ``null`` during a
# reach-unsafe-state search.  Normal UI controls still publish the concrete
# scalar/string/boolean values described by their domain.
KnobValue: TypeAlias = float | str | bool | None


class Knob(BaseModel):
    """A parameterized control that binds directly to a harness input."""

    id: str
    label: str
    binding: ParamBinding
    type: Literal["scalar", "integer", "enum", "boolean"]
    domain: NumericDomain | EnumDomain
    default: KnobValue
    scale: Literal["linear", "log"]
    unit: str | None
    axisRole: Literal["x", "y"] | None = None


class ReturnValueExtractor(BaseModel):
    """Extracts an observable via a JSONPath into the return value."""

    kind: Literal["returnValue"]
    path: str


class CounterExtractor(BaseModel):
    """Extracts an instrumented counter observable."""

    kind: Literal["counter"]
    name: str


class TraceExtractor(BaseModel):
    """Aggregates a named instrumentation trace event."""

    kind: Literal["trace"]
    event: str
    agg: Literal["count", "p50", "p95", "p99", "max"]


class PathExtractor(BaseModel):
    """Extracts a branch-decision vector."""

    kind: Literal["path"]
    instrumentation: Literal["branch"]


ObservableExtractor: TypeAlias = Annotated[
    ReturnValueExtractor | CounterExtractor | TraceExtractor | PathExtractor,
    Field(discriminator="kind"),
]


class Observable(BaseModel):
    """A measured output rendered by the selected domain-pack template."""

    id: str
    label: str
    extractor: ObservableExtractor
    render: Literal[
        "timeseries",
        "scalar",
        "histogram",
        "matrixCell",
        "nodeState",
        "pathTrace",
    ]
    unit: str | None
    compareMode: Literal["overlay", "delta", "ratio"]


class KnobPosition(RootModel[dict[str, KnobValue]]):
    """A mapping from stable knob IDs to their scalar, enum, or boolean values."""


AdversaryObjective: TypeAlias = Literal[
    "max_divergence", "max_path_divergence", "reach_unsafe_state"
]


class UnsafeLiteralTarget(BaseModel):
    """Compares an observable with one explicit, JSON-serializable value."""

    kind: Literal["literal"]
    value: KnobValue


class UnsafeKnobTarget(BaseModel):
    """Compares an observable with the value of the named knob at each point."""

    kind: Literal["knob"]
    id: str = Field(min_length=1)


UnsafePredicateTarget: TypeAlias = Annotated[
    UnsafeLiteralTarget | UnsafeKnobTarget,
    Field(discriminator="kind"),
]


class UnsafePredicate(BaseModel):
    """A user-declared observable condition that makes a search position unsafe."""

    observableId: str = Field(min_length=1)
    operator: Literal["gt", "gte", "lt", "lte", "eq", "neq"]
    target: UnsafePredicateTarget
    versions: Literal["either", "base", "head"] = "either"


class BranchDecision(BaseModel):
    """One empirically observed conditional outcome, tagged at its source location."""

    tag: str
    outcome: bool


class VersionExecutionTrace(BaseModel):
    """Source lines empirically executed by one target module for one knob position."""

    file: str
    executedLines: list[int]
    entryLines: list[int]
    lineHits: dict[int, int] = Field(default_factory=dict)
    branchDecisions: list[BranchDecision] = Field(default_factory=list)


class ResponsibleLine(BaseModel):
    """One empirically exclusive executed source line that explains an A/B divergence."""

    version: Literal["base", "head"]
    file: str
    line: int = Field(ge=1)
    code: str


class TraceAttribution(BaseModel):
    """Paired execution traces and the deterministic escape-hatch source location."""

    base: VersionExecutionTrace
    head: VersionExecutionTrace
    responsibleLine: ResponsibleLine | None = None


class NamedPosition(BaseModel):
    """A measured cached position with a label that makes no worldly interpretation."""

    position: KnobPosition
    label: str
    divergence: float


class SurpriseMarker(BaseModel):
    """The measured position at which the two versions visibly diverge."""

    position: KnobPosition
    divergence: float = Field(ge=0, le=1)
    caption: str


class SymmetristSummary(BaseModel):
    """The Fidelity Report's Symmetrist result."""

    passed: bool
    hashA: str
    hashB: str
    unjustifiedKeys: list[str]


class RelativeTolerance(BaseModel):
    """Relative differential-test tolerance."""

    kind: Literal["relative"]
    epsilon: float


class AbsoluteTolerance(BaseModel):
    """Absolute differential-test tolerance."""

    kind: Literal["absolute"]
    epsilon: float


class ExactTolerance(BaseModel):
    """Exact differential-test tolerance for categorical outputs."""

    kind: Literal["exact"]


Tolerance: TypeAlias = Annotated[
    RelativeTolerance | AbsoluteTolerance | ExactTolerance,
    Field(discriminator="kind"),
]


class Agreement(BaseModel):
    """Sampled differential-test agreement."""

    samples: int
    matched: int
    rate: float
    tolerance: Tolerance


class CvStabilityEstimate(BaseModel):
    """Coefficient-of-variation stability estimate for a numeric observable."""

    kind: Literal["cv"]
    value: float


class InstabilityStabilityEstimate(BaseModel):
    """Modal-deviation stability estimate for a categorical observable."""

    kind: Literal["instability"]
    value: float


StabilityEstimate: TypeAlias = Annotated[
    CvStabilityEstimate | InstabilityStabilityEstimate,
    Field(discriminator="kind"),
]


class Stability(BaseModel):
    """Per-observable stability across Assayer replicates."""

    replicates: int
    perObservable: dict[str, StabilityEstimate]


class Coverage(BaseModel):
    """The strategy and count used to cover the input space."""

    samples: int
    strategy: Literal["sobol", "grid", "random"]


class FidelityReport(BaseModel):
    """Verification, stability, coverage, and confidence measurements."""

    verdict: Literal["verified", "degraded"]
    symmetrist: SymmetristSummary
    agreement: Agreement
    stability: Stability
    coverage: Coverage
    confidence: float = Field(ge=0, le=1)
    band: Literal["high", "medium", "low"]
    degradeReason: str | None


class Provenance(BaseModel):
    """Ingestion and harness-origin facts attached to an Interaction Spec."""

    baseSha: str
    headSha: str
    repoUrl: str
    generatedAt: str
    modelIds: dict[str, str]
    harnessSourceUri: str
    forced: bool | None = None
    speculative: bool = False
    hypothesisCaveat: str | None = None
    registryCompatibilityKickbacks: int = Field(
        default=0,
        ge=0,
        le=1,
        description=(
            "The one pipeline-wide Delta Analyst re-selection used for either a "
            "registered-template incompatibility or unavailable reference instrumentation."
        ),
    )


class InteractionSpec(BaseModel):
    """The complete document that flows through Lever's pipeline."""

    specVersion: Literal["2.0"]
    changeId: str
    thesis: str = Field(max_length=140)
    domainPack: DomainPackId
    knobs: list[Knob] = Field(min_length=1, max_length=4)
    observables: list[Observable] = Field(min_length=1, max_length=2)
    initialPosition: KnobPosition
    surpriseMarker: SurpriseMarker | None
    presets: list[NamedPosition] | None = None
    fidelity: FidelityReport
    provenance: Provenance


class PartialInteractionSpec(BaseModel):
    """The Delta Analyst-owned subset of an Interaction Spec."""

    thesis: str = Field(max_length=140)
    domainPack: DomainPackId
    knobs: list[Knob] = Field(min_length=1, max_length=4)
    observables: list[Observable] = Field(min_length=1, max_length=2)


class ComposedCell(BaseModel):
    """One empirically executed corner of a composed two-diff microworld."""

    variant: Literal["base", "A", "B", "AB"]
    observation: float


class BehavioralMergeConflict(BaseModel):
    """Measured deviation from the additive two-by-two factorial expectation."""

    detected: bool
    additiveExpectation: float
    observedAB: float
    deviation: float = Field(ge=0)
    tolerance: float = Field(ge=0)
    caption: str | None = None


class ComposedWidgetConfig(BaseModel):
    """Serializable 2×2 composition view; each cell is an executed harness result."""

    changeAId: str
    changeBId: str
    observableId: str
    observableLabel: str
    unit: str | None
    position: KnobPosition
    cells: list[ComposedCell] = Field(min_length=4, max_length=4)
    interaction: BehavioralMergeConflict
