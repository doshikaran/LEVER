"""Deterministic harness planning and templating for isolated real-code execution."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from domain.entry_point_registry import EntryPointTemplate, HarnessBodyRequest, get_entry_point_template
from domain.harness_ir import HarnessIR, render_harness_source
from domain.harness_proposer import HarnessProposer
from domain.line_attribution import UninstrumentableReferenceError, instrument_branch_source
from domain.ports import LLMClient, SandboxRuntime
from domain.schema import (
    DepEntry,
    DependencyLedger,
    DomainPackId,
    Knob,
    Observable,
    PartialInteractionSpec,
    ScopedChangeSet,
)
from domain.stubs import PlannedStub, stub_plan


_MINIMAL_STUB_KINDS = frozenset({"network", "db", "native"})
_LIVE_IDENTITY_MARKERS = frozenset({"auth0", "identity", "idp", "oauth", "saml"})
NO_HARNESS_TEMPLATE_REASON = "no harness template registered for this entry-point shape"
GENERATIVE_HARNESS_FAILED_REASON = "generative harness could not be built for this entry-point shape"


class NoHarnessTemplateRegistered(ValueError):
    """Legacy signal retained for callers that still special-case registry misses."""

    def __init__(self, entry_point_fn: str) -> None:
        super().__init__(f"{NO_HARNESS_TEMPLATE_REASON}: {entry_point_fn}")


class UnsupportedTemplateProposal(ValueError):
    """Raised when a registered template cannot faithfully consume a valid spec."""


class GenerativeHarnessError(ValueError):
    """Raised when generative IR construction fails for an unregistered shape."""


@dataclass(frozen=True)
class UncertaintySpec:
    """An Assayer perturbation declaration for one stubbed parameter."""

    default: Any
    distribution: str


@dataclass(frozen=True)
class DependencyStub:
    """One non-pure dependency's deterministic stub configuration contract."""

    dependency: str
    kind: str
    parameters: dict[str, UncertaintySpec]

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable configuration embedded in each harness."""
        return {
            "kind": self.kind,
            "parameters": {
                name: {
                    "default": spec.default,
                    "distribution": spec.distribution,
                }
                for name, spec in self.parameters.items()
            },
        }


@dataclass(frozen=True)
class WorkloadDriver:
    """The workload controls that call the selected entry point."""

    parameters: tuple[str, ...]
    knob_definitions: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class HarnessArtifact:
    """One rendered harness and the target module path it imports."""

    source: str
    entry_module: str
    instrumented_module_source: str | None = None


@dataclass(frozen=True)
class HarnessPair:
    """Symmetric base/head harnesses plus their stubbing and driver declarations."""

    harness_a: HarnessArtifact
    harness_b: HarnessArtifact
    stub_config: tuple[DependencyStub, ...]
    uncertainty_specs: tuple[DependencyStub, ...]
    workload_driver: WorkloadDriver
    generative_ir: HarnessIR | None = None


@dataclass(frozen=True)
class VerifierFeedback:
    """Feedback Fidelity Verifier may return into harness retries."""

    implicated_dependencies: tuple[str, ...] = ()
    divergence_summary: str | None = None


@dataclass(frozen=True)
class RetryAttempt:
    """One of Harness Engineer's mandated escalating retry configurations."""

    number: int
    stubbed_dependencies: tuple[str, ...]
    seed_clock: bool
    seed_random: bool
    scope_target: str
    tolerance: str


@dataclass(frozen=True)
class RetryOutcome:
    """The recorded state-machine path after running retry probes."""

    succeeded: bool
    attempts: tuple[RetryAttempt, ...]


class HarnessEngineer:
    """Generates symmetric Python harnesses via registry fast-path or generative IR."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._proposer = HarnessProposer(llm)

    def generate(
        self,
        scoped_change_set: ScopedChangeSet,
        partial_spec: PartialInteractionSpec,
        base_module_path: str,
        head_module_path: str,
        base_source: str | None = None,
        head_source: str | None = None,
        *,
        repair_feedback: str | None = None,
    ) -> HarnessPair:
        """Generate the base/head pair; registry match is preferred when compatible."""
        return build_harness_pair(
            scoped_change_set,
            partial_spec.knobs,
            partial_spec.observables,
            base_module_path,
            head_module_path,
            domain_pack=partial_spec.domainPack,
            base_source=base_source,
            head_source=head_source,
            partial_spec=partial_spec,
            proposer=self._proposer,
            repair_feedback=repair_feedback,
        )


def build_harness_pair(
    scoped_change_set: ScopedChangeSet,
    knobs: list[Knob],
    observables: list[Observable],
    base_module_path: str,
    head_module_path: str,
    domain_pack: DomainPackId | None = None,
    base_source: str | None = None,
    head_source: str | None = None,
    partial_spec: PartialInteractionSpec | None = None,
    proposer: HarnessProposer | None = None,
    repair_feedback: str | None = None,
) -> HarnessPair:
    """Build a symmetric pair from registry fast-path or generative HarnessIR."""
    entry_point = scoped_change_set.entry_point
    if entry_point is None:
        raise ValueError("Harness Engineer requires a scoped entry point")
    unstubbable = next(
        (
            entry.name
            for entry in scoped_change_set.dependency_ledger.entries
            if entry.kind == "network"
            and any(marker in entry.name.lower() for marker in _LIVE_IDENTITY_MARKERS)
        ),
        None,
    )
    if unstubbable is not None:
        raise ValueError(
            f"Cannot safely stub live identity-provider dependency `{unstubbable}`; "
            "the generated substitute would change authentication behavior"
        )

    template = get_entry_point_template(entry_point.fn)
    if template is not None:
        incompatibility = template.proposal_shape.incompatibility_reason(
            entry_point.fn, knobs, observables
        )
        if incompatibility is not None:
            raise UnsupportedTemplateProposal(incompatibility)
        return _build_from_registry(
            scoped_change_set,
            knobs,
            observables,
            base_module_path,
            head_module_path,
            domain_pack,
            base_source,
            head_source,
            template,
        )

    if partial_spec is None:
        if domain_pack is None:
            raise GenerativeHarnessError(
                f"{GENERATIVE_HARNESS_FAILED_REASON}: {entry_point.fn}"
            )
        partial_spec = PartialInteractionSpec(
            thesis="Generative harness",
            domainPack=domain_pack,
            knobs=knobs,
            observables=observables,
        )
    try:
        return _build_from_generative_ir(
            scoped_change_set,
            partial_spec,
            base_module_path,
            head_module_path,
            domain_pack,
            base_source,
            head_source,
            proposer or HarnessProposer(),
            repair_feedback,
        )
    except GenerativeHarnessError:
        raise
    except Exception as error:
        raise GenerativeHarnessError(
            f"{GENERATIVE_HARNESS_FAILED_REASON}: {entry_point.fn}: {error}"
        ) from error


def _build_from_registry(
    scoped_change_set: ScopedChangeSet,
    knobs: list[Knob],
    observables: list[Observable],
    base_module_path: str,
    head_module_path: str,
    domain_pack: DomainPackId | None,
    base_source: str | None,
    head_source: str | None,
    template: EntryPointTemplate,
) -> HarnessPair:
    """Preserve the v2 hero fast-path."""
    assert scoped_change_set.entry_point is not None
    stubs = tuple(
        _dependency_stub(entry)
        for entry in scoped_change_set.dependency_ledger.entries
        if (
            entry.kind != "pure"
            and entry.kind not in template.symmetrically_seeded_dependency_kinds
        )
    )
    driver = _workload_driver(knobs)
    config_knobs = _config_knobs(knobs)
    defaults = _default_config(knobs)
    shared_request = {
        "entry_point_fn": scoped_change_set.entry_point.fn,
        "default_config": defaults,
        "config_knobs": config_knobs,
        "driver_knobs": driver.knob_definitions,
        "stub_config": {stub.dependency: stub.as_dict() for stub in stubs},
        "observables": [observable.model_dump(mode="json") for observable in observables],
    }
    harness_a_source = template.harness_body(
        HarnessBodyRequest(module_path=base_module_path, **shared_request)
    )
    harness_b_source = template.harness_body(
        HarnessBodyRequest(module_path=head_module_path, **shared_request)
    )
    base_instrumented_source = None
    head_instrumented_source = None
    if domain_pack is DomainPackId.DECISION_TREE:
        base_instrumented_source = _instrumented_module_source(base_module_path, base_source)
        head_instrumented_source = _instrumented_module_source(head_module_path, head_source)
        harness_a_source = _with_branch_trace_adapter(harness_a_source)
        harness_b_source = _with_branch_trace_adapter(harness_b_source)
    _assert_module_path_is_only_difference(harness_a_source, harness_b_source)
    return HarnessPair(
        harness_a=HarnessArtifact(harness_a_source, base_module_path, base_instrumented_source),
        harness_b=HarnessArtifact(harness_b_source, head_module_path, head_instrumented_source),
        stub_config=stubs,
        uncertainty_specs=stubs,
        workload_driver=driver,
        generative_ir=None,
    )


def _build_from_generative_ir(
    scoped_change_set: ScopedChangeSet,
    partial_spec: PartialInteractionSpec,
    base_module_path: str,
    head_module_path: str,
    domain_pack: DomainPackId | None,
    base_source: str | None,
    head_source: str | None,
    proposer: HarnessProposer,
    repair_feedback: str | None,
) -> HarnessPair:
    """Render a pair from HarnessIR so unknown entry points remain verifiable."""
    ir, plan = proposer.propose(
        scoped_change_set, partial_spec, repair_feedback=repair_feedback
    )
    stubs = tuple(_planned_to_dependency_stub(stub) for stub in plan.stubs)
    driver = _workload_driver(partial_spec.knobs)
    harness_a_source = render_harness_source(
        ir,
        module_path=base_module_path,
        knobs=partial_spec.knobs,
        observables=partial_spec.observables,
        stubs=plan.stubs,
    )
    harness_b_source = render_harness_source(
        ir,
        module_path=head_module_path,
        knobs=partial_spec.knobs,
        observables=partial_spec.observables,
        stubs=plan.stubs,
    )
    base_instrumented_source = None
    head_instrumented_source = None
    if domain_pack is DomainPackId.DECISION_TREE:
        base_instrumented_source = _instrumented_module_source(base_module_path, base_source)
        head_instrumented_source = _instrumented_module_source(head_module_path, head_source)
        harness_a_source = _with_branch_trace_adapter(harness_a_source)
        harness_b_source = _with_branch_trace_adapter(harness_b_source)
    _assert_module_path_is_only_difference(harness_a_source, harness_b_source)
    return HarnessPair(
        harness_a=HarnessArtifact(harness_a_source, base_module_path, base_instrumented_source),
        harness_b=HarnessArtifact(harness_b_source, head_module_path, head_instrumented_source),
        stub_config=stubs,
        uncertainty_specs=stubs,
        workload_driver=driver,
        generative_ir=ir,
    )


def _planned_to_dependency_stub(stub: PlannedStub) -> DependencyStub:
    return DependencyStub(
        dependency=stub.dependency,
        kind=stub.kind,
        parameters={
            name: UncertaintySpec(spec.default, spec.distribution)
            for name, spec in stub.parameters.items()
        },
    )


def _instrumented_module_source(module_path: str, source: str | None) -> str:
    """Return source-transform output or a typed C-5 re-selection signal."""
    if source is None:
        try:
            source = Path(module_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise UninstrumentableReferenceError(
                f"reference path {module_path!r} cannot be read as Python source and "
                "cannot be branch-instrumented"
            ) from error
    return instrument_branch_source(source, module_path)


def _with_branch_trace_adapter(source: str) -> str:
    """Expose the transformed module's branch vector through the existing harness trace."""
    adapter = """

# C-5 adapter: expose the existing sys.settrace collector as the observable.
_lever_original_run = run

def run(config=None, seed=0):
    result = _lever_original_run(config, seed)
    branch_vector = list(result.get("trace", {}).get("branch_decisions", ()))
    for observable in OBSERVABLES:
        if observable["render"] == "pathTrace":
            result["observations"][observable["id"]] = branch_vector
    return result
"""
    line_hits = "    line_hits = {}\n"
    trace_hook = """
    branch_decisions = []
"""
    if line_hits not in source:
        raise UninstrumentableReferenceError(
            "generated harness does not expose the shared sys.settrace line collector"
        )
    source = source.replace(line_hits, line_hits + trace_hook, 1)
    trace_definition = "    def trace_lines(frame, event, _arg):\n"
    branch_capture = """\
        if event == "line" and frame.f_code.co_name == "__lever_branch__":
            tag = frame.f_locals.get("tag")
            outcome = frame.f_locals.get("outcome")
            if isinstance(tag, str) and isinstance(outcome, bool):
                branch_decisions.append({"tag": tag, "outcome": outcome})
"""
    if trace_definition not in source:
        raise UninstrumentableReferenceError(
            "generated harness does not expose the shared sys.settrace callback"
        )
    source = source.replace(trace_definition, trace_definition + branch_capture, 1)
    line_hit_field = '"line_hits": {str(line): line_hits[line] for line in sorted(line_hits)},'
    if line_hit_field not in source:
        raise UninstrumentableReferenceError(
            "generated harness does not expose a serializable execution trace"
        )
    source = source.replace(
        line_hit_field,
        line_hit_field + '\n            "branch_decisions": branch_decisions,',
        1,
    )
    main_guard = '\n\nif __name__ == "__main__":'
    if main_guard in source:
        return source.replace(main_guard, adapter + main_guard, 1)
    return source + adapter


def retry_plan(
    scoped_change_set: ScopedChangeSet,
    verifier_feedback: VerifierFeedback | None = None,
) -> tuple[RetryAttempt, RetryAttempt, RetryAttempt]:
    """Return Harness Engineer's fixed three-attempt escalation sequence."""
    entry_point = scoped_change_set.entry_point
    if entry_point is None:
        raise ValueError("Harness retry planning requires a scoped entry point")
    dependencies = tuple(
        entry.name for entry in scoped_change_set.dependency_ledger.entries if entry.kind != "pure"
    )
    minimal = tuple(
        entry.name
        for entry in scoped_change_set.dependency_ledger.entries
        if entry.kind in _MINIMAL_STUB_KINDS
    )
    feedback = verifier_feedback or VerifierFeedback()
    expanded = tuple(dict.fromkeys((*minimal, *feedback.implicated_dependencies)))
    innermost = _innermost_target(scoped_change_set, entry_point.fn)
    return (
        RetryAttempt(1, minimal, False, False, entry_point.fn, "relative ε=0.01"),
        RetryAttempt(2, expanded, True, True, entry_point.fn, "relative ε=0.01"),
        RetryAttempt(3, dependencies, True, True, innermost, "relative ε=0.05"),
    )


def run_retry_loop(
    runtime: SandboxRuntime,
    sandbox_id: str,
    attempts: Iterable[RetryAttempt],
    probe_code: Callable[[RetryAttempt], str],
) -> RetryOutcome:
    """Execute retry stages until a probe succeeds."""
    attempted: list[RetryAttempt] = []
    for attempt in attempts:
        result = runtime.run_code(sandbox_id, probe_code(attempt))
        attempted.append(attempt)
        if result["exit_code"] == 0:
            return RetryOutcome(True, tuple(attempted))
    return RetryOutcome(False, tuple(attempted))


def _dependency_stub(entry: DepEntry) -> DependencyStub:
    """Declare Assayer uncertainty parameters for one dependency type."""
    plan = stub_plan(DependencyLedger(entries=[entry]))
    if plan.stubs:
        return _planned_to_dependency_stub(plan.stubs[0])
    io_parameters = {
        "latency_ms": UncertaintySpec(5, "log-uniform [2 ms, 20 ms]"),
        "cold_cache_probability": UncertaintySpec(0.0, "uniform [0.0, 0.3]"),
        "default_return": UncertaintySpec(
            "type zero-value", "{zero-value, empty, plausible-nonempty}"
        ),
        "gc_pause_ms_per_100_ops": UncertaintySpec(0, "uniform [0, 5] ms per 100 ops"),
    }
    if entry.kind in {"io", "network", "db", "native"}:
        return DependencyStub(entry.name, entry.kind, io_parameters)
    if entry.kind == "clock":
        return DependencyStub(
            entry.name,
            entry.kind,
            {"resolution_ms": UncertaintySpec(1, "discrete {0.1, 1, 10} ms")},
        )
    if entry.kind == "random":
        return DependencyStub(
            entry.name,
            entry.kind,
            {"seed": UncertaintySpec("fixed", "H(baseSeed, i)")},
        )
    raise ValueError(f"Cannot build a stub for dependency kind {entry.kind!r}")


def _workload_driver(knobs: list[Knob]) -> WorkloadDriver:
    """Expose every driver-bound knob to the template's workload invocation."""
    definitions = tuple(
        {"id": knob.id, "param": knob.binding.param, "default": knob.default}
        for knob in knobs
        if knob.binding.kind == "driver"
    )
    return WorkloadDriver(
        parameters=tuple(item["param"] for item in definitions),
        knob_definitions=definitions,
    )


def _config_knobs(knobs: list[Knob]) -> list[dict[str, Any]]:
    """Expose every config-bound knob to the common harness configuration."""
    return [
        {"id": knob.id, "param": knob.binding.path, "default": knob.default}
        for knob in knobs
        if knob.binding.kind == "config"
    ]


def _default_config(knobs: list[Knob]) -> dict[str, Any]:
    """Create the default runtime config by stable knob ID."""
    return {knob.id: knob.default for knob in knobs}


def _assert_module_path_is_only_difference(base_source: str, head_source: str) -> None:
    """Enforce structural symmetry before a pair can reach Fidelity Verifier."""
    if _normalise_module_path(base_source) != _normalise_module_path(head_source):
        raise AssertionError("Harnesses differ in more than their imported module path")


def _normalise_module_path(source: str) -> str:
    """Replace the one sanctioned module-path line with a stable sentinel."""
    lines = source.splitlines(keepends=True)
    return "".join(
        "MODULE_PATH = __MODULE_PATH__\n" if line.startswith("MODULE_PATH = ") else line
        for line in lines
    )


def _innermost_target(scoped_change_set: ScopedChangeSet, fallback: str) -> str:
    """Choose Scout's deepest named changed/reachable node for retry attempt three."""
    candidates = [
        node
        for node in (*scoped_change_set.changed_nodes, *scoped_change_set.reachable_nodes)
        if node.name
    ]
    if not candidates:
        return fallback
    return min(
        candidates, key=lambda node: (node.end_byte - node.start_byte, -node.start_byte)
    ).name or fallback
