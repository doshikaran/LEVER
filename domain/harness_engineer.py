"""Deterministic harness planning and templating for isolated real-code execution."""

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from domain.ports import SandboxRuntime
from domain.schema import DepEntry, Knob, Observable, PartialInteractionSpec, ScopedChangeSet


_MINIMAL_STUB_KINDS = frozenset({"network", "db", "native"})
_HERO1_ENTRY_POINT = "RateLimiter.admit"
_LIVE_IDENTITY_MARKERS = frozenset({"auth0", "identity", "idp", "oauth", "saml"})

_HARNESS_TEMPLATE = """\
import importlib.util
import json
import random

MODULE_PATH = __MODULE_PATH__
ENTRY_POINT = __ENTRY_POINT__
DEFAULT_CONFIG = __DEFAULT_CONFIG__
CONFIG_KNOBS = __CONFIG_KNOBS__
DRIVER_KNOBS = __DRIVER_KNOBS__
STUB_CONFIG = __STUB_CONFIG__
OBSERVABLES = __OBSERVABLES__


def _load_module():
    spec = importlib.util.spec_from_file_location("lever_target", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import target module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _values(config, knobs):
    return {
        knob["param"]: config.get(knob["id"], config.get(knob["param"], knob["default"]))
        for knob in knobs
    }


def run(config=None, seed=0):
    config = dict(DEFAULT_CONFIG if config is None else config)
    random.seed(seed)
    driver = _values(config, DRIVER_KNOBS)
    config_values = _values(config, CONFIG_KNOBS)
    module = _load_module()
    limiter_class = module.RateLimiter
    limit = int(config_values.get("limit_per_sec", 100))
    burst = int(config_values.get("burst", 0))
    try:
        limiter = limiter_class(limit_per_sec=limit, burst=burst)
    except TypeError:
        limiter = limiter_class(limit_per_sec=limit)

    rps = max(1, int(driver.get("rps", driver.get("requests_per_tenant_per_sec", 1))))
    tenants = max(1, int(driver.get("tenants", driver.get("tenant_count", 1))))
    admitted = 0
    # Hero 1 accepts ``now`` as an argument. A fixed simulated epoch makes both
    # generated harnesses and the independent reference path deterministic.
    started_at = 0.0
    for request_index in range(rps):
        now = started_at + request_index / rps
        for tenant_index in range(tenants):
            admitted += limiter.admit(f"tenant-{tenant_index}", now)

    return {
        "entry_point": ENTRY_POINT,
        "driver": driver,
        "observations": {observable["id"]: admitted for observable in OBSERVABLES},
        "stub_config": STUB_CONFIG,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
"""


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


@dataclass(frozen=True)
class HarnessPair:
    """Symmetric base/head harnesses plus their stubbing and driver declarations."""

    harness_a: HarnessArtifact
    harness_b: HarnessArtifact
    stub_config: tuple[DependencyStub, ...]
    uncertainty_specs: tuple[DependencyStub, ...]
    workload_driver: WorkloadDriver


@dataclass(frozen=True)
class VerifierFeedback:
    """Placeholder input Fidelity Verifier will eventually return to retries."""

    implicated_dependencies: tuple[str, ...] = ()


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
    """Generates symmetric Python harnesses and the Phase 4 retry configuration."""

    def generate(
        self,
        scoped_change_set: ScopedChangeSet,
        partial_spec: PartialInteractionSpec,
        base_module_path: str,
        head_module_path: str,
    ) -> HarnessPair:
        """Generate the base/head pair from one template with import path as its sole delta."""
        return build_harness_pair(
            scoped_change_set,
            partial_spec.knobs,
            partial_spec.observables,
            base_module_path,
            head_module_path,
        )


def build_harness_pair(
    scoped_change_set: ScopedChangeSet,
    knobs: list[Knob],
    observables: list[Observable],
    base_module_path: str,
    head_module_path: str,
) -> HarnessPair:
    """Build a symmetric Hero 1 harness pair from one source template."""
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
    if entry_point.fn != _HERO1_ENTRY_POINT:
        raise NotImplementedError(
            f"No Python harness template is available for {entry_point.fn}; "
            "the current template supports Hero 1's RateLimiter.admit."
        )

    stubs = tuple(_dependency_stub(entry) for entry in scoped_change_set.dependency_ledger.entries if entry.kind != "pure")
    driver = _workload_driver(knobs)
    config_knobs = _config_knobs(knobs)
    defaults = _default_config(knobs)
    common_replacements = {
        "__ENTRY_POINT__": json.dumps(entry_point.fn),
        # These constants are embedded in *Python* source, rather than a JSON
        # document.  ``repr`` therefore preserves Python values such as None,
        # which an LLM is permitted to propose for optional schema fields.
        "__DEFAULT_CONFIG__": repr(defaults),
        "__CONFIG_KNOBS__": repr(config_knobs),
        "__DRIVER_KNOBS__": repr(driver.knob_definitions),
        "__STUB_CONFIG__": repr({stub.dependency: stub.as_dict() for stub in stubs}),
        "__OBSERVABLES__": repr(
            [observable.model_dump(mode="json") for observable in observables]
        ),
    }
    harness_a_source = _render_harness(base_module_path, common_replacements)
    harness_b_source = _render_harness(head_module_path, common_replacements)
    _assert_module_path_is_only_difference(harness_a_source, harness_b_source)
    return HarnessPair(
        harness_a=HarnessArtifact(harness_a_source, base_module_path),
        harness_b=HarnessArtifact(harness_b_source, head_module_path),
        stub_config=stubs,
        uncertainty_specs=stubs,
        workload_driver=driver,
    )


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
    # TODO(phase-4): Fidelity Verifier supplies only the deps implicated by its divergence report.
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
    """Execute retry stages until a probe succeeds; verifier feedback is a Phase 4 TODO."""
    attempted: list[RetryAttempt] = []
    for attempt in attempts:
        # TODO(phase-4): replace this exit-code gate with Fidelity Verifier feedback.
        result = runtime.run_code(sandbox_id, probe_code(attempt))
        attempted.append(attempt)
        if result["exit_code"] == 0:
            return RetryOutcome(True, tuple(attempted))
    return RetryOutcome(False, tuple(attempted))


def _dependency_stub(entry: DepEntry) -> DependencyStub:
    """Declare every relevant Assayer uncertainty parameter for one dependency type."""
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


def _render_harness(module_path: str, replacements: dict[str, str]) -> str:
    """Render one harness, varying only its target module path."""
    source = _HARNESS_TEMPLATE.replace("__MODULE_PATH__", json.dumps(module_path))
    for token, value in replacements.items():
        source = source.replace(token, value)
    return source


def _assert_module_path_is_only_difference(base_source: str, head_source: str) -> None:
    """Enforce structural symmetry before a pair can reach Fidelity Verifier."""
    normalised_base = _normalise_module_path(base_source)
    normalised_head = _normalise_module_path(head_source)
    if normalised_base != normalised_head:
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
        node for node in (*scoped_change_set.changed_nodes, *scoped_change_set.reachable_nodes) if node.name
    ]
    if not candidates:
        return fallback
    return min(candidates, key=lambda node: (node.end_byte - node.start_byte, -node.start_byte)).name or fallback
