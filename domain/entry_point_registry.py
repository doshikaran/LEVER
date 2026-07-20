"""Registered executable shapes shared by Harness Engineer and Fidelity Verifier.

Each entry-point shape owns both sides of its empirical contract: the isolated
harness body and the independent direct-real-code reference program.  Keeping
them together makes unsupported shapes an explicit, degradable condition rather
than an accidental hardcoded execution path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from domain.schema import (
    ArgumentBinding,
    DomainPackId,
    EnumDomain,
    Knob,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    ReturnValueExtractor,
)


@dataclass(frozen=True)
class HarnessBodyRequest:
    """All data an entry-point shape needs to render one harness source file."""

    module_path: str
    entry_point_fn: str
    default_config: dict[str, Any]
    config_knobs: list[dict[str, Any]]
    driver_knobs: tuple[dict[str, Any], ...]
    stub_config: dict[str, Any]
    observables: list[dict[str, Any]]


@dataclass(frozen=True)
class ReferenceProgramRequest:
    """All data an entry-point shape needs to run its module directly."""

    module_path: str
    knobs: list[Knob]
    observables: list[Observable]
    point: dict[str, Any]
    seed: int | str


HarnessBodyGenerator = Callable[[HarnessBodyRequest], str]
ReferenceProgramGenerator = Callable[[ReferenceProgramRequest], str]


@dataclass(frozen=True)
class ProposalShape:
    """The knob-binding shape an entry-point template can execute faithfully."""

    workload_description: str
    required_driver_params: tuple[str, ...]
    allowed_binding_kinds: frozenset[str]
    required_knobs: tuple["KnobRequirement", ...] = ()
    require_exact_knob_ids: bool = False
    required_observable_render: str | None = None
    expected_control_ids: tuple[str, ...] = ()
    numeric_fallback_requirements: tuple["KnobRequirement", ...] = ()
    numeric_fallback_render: str | None = None

    def prompt_contract(self, entry_point_fn: str) -> dict[str, Any]:
        """Describe the registered execution shape for Delta's provider-neutral prompt."""
        contract: dict[str, Any] = {
            "entryPoint": entry_point_fn,
            "workload": self.workload_description,
            "allowedBindingKinds": sorted(self.allowed_binding_kinds),
            "requiredKnobs": _requirements_prompt_contract(self.required_knobs),
            "requireExactKnobIds": self.require_exact_knob_ids,
            "requiredObservableRender": self.required_observable_render,
        }
        if self.numeric_fallback_requirements:
            contract["numericFallback"] = {
                "requiredKnobs": _requirements_prompt_contract(
                    self.numeric_fallback_requirements
                ),
                "requireExactKnobIds": True,
                "requiredObservableRender": self.numeric_fallback_render,
            }
        return contract

    def incompatibility_reason(
        self,
        entry_point_fn: str,
        knobs: list[Knob],
        observables: list[Observable],
    ) -> str | None:
        """Explain why a valid InteractionSpec cannot be served by this template."""
        if self.numeric_fallback_requirements and _proposal_matches_shape(
            knobs,
            observables,
            self.numeric_fallback_requirements,
            require_exact_knob_ids=True,
            required_observable_render=self.numeric_fallback_render,
        ):
            return None
        binding_kinds = {knob.binding.kind for knob in knobs}
        driver_params = {
            knob.binding.param
            for knob in knobs
            if knob.binding.kind == "driver"
        }
        missing_params = [
            parameter
            for parameter in self.required_driver_params
            if parameter not in driver_params
        ]
        unsupported_kinds = binding_kinds - self.allowed_binding_kinds
        knobs_by_id = {knob.id: knob for knob in knobs}
        requirement_failures = _requirement_failures(self.required_knobs, knobs_by_id)
        required_ids = {requirement.id for requirement in self.required_knobs}
        unexpected_ids = set(knobs_by_id) - required_ids
        wrong_knob_set = self.require_exact_knob_ids and bool(unexpected_ids)
        wrong_observable = self.required_observable_render is not None and (
            len(observables) != 1
            or observables[0].render != self.required_observable_render
        )
        if (
            not missing_params
            and not unsupported_kinds
            and not requirement_failures
            and not wrong_knob_set
            and not wrong_observable
        ):
            return None

        expected = "/".join(self.expected_control_ids or self.required_driver_params)
        proposed_shape = _proposed_shape_description(knobs)
        return (
            f"registered template for '{entry_point_fn}' expects "
            f"{self.workload_description} ({expected}); proposed spec is "
            f"{proposed_shape}, which this template does not support"
        )


@dataclass(frozen=True)
class KnobRequirement:
    """One mechanically required control in a registered template's proposal shape."""

    id: str
    type: str | None = None
    axis_role: str | None = None
    binding_kind: str | None = None
    config_path: str | None = None

    def describe_failure(self, knob: Knob | None) -> str | None:
        """Return a concrete mismatch without forcing a template to consume it."""
        if knob is None:
            return f"missing knob {self.id}"
        if self.type is not None and knob.type != self.type:
            return f"knob {self.id} must be {self.type}"
        if self.axis_role != knob.axisRole:
            expected = self.axis_role if self.axis_role is not None else "no axisRole"
            return f"knob {self.id} must have {expected}"
        if self.binding_kind is not None and knob.binding.kind != self.binding_kind:
            return f"knob {self.id} must use a {self.binding_kind} binding"
        if (
            self.config_path is not None
            and knob.binding.kind == "config"
            and knob.binding.path != self.config_path
        ):
            return f"knob {self.id} must bind config path {self.config_path}"
        return None


def _requirements_prompt_contract(
    requirements: tuple[KnobRequirement, ...],
) -> list[dict[str, Any]]:
    """Serialize only the binding facts a registered template can actually consume."""
    serialized: list[dict[str, Any]] = []
    for requirement in requirements:
        item: dict[str, Any] = {"id": requirement.id}
        if requirement.type is not None:
            item["type"] = requirement.type
        if requirement.axis_role is not None:
            item["axisRole"] = requirement.axis_role
        if requirement.binding_kind is not None:
            binding: dict[str, str] = {"kind": requirement.binding_kind}
            if requirement.config_path is not None:
                binding["path"] = requirement.config_path
            item["binding"] = binding
        serialized.append(item)
    return serialized


def _requirement_failures(
    requirements: tuple[KnobRequirement, ...], knobs_by_id: dict[str, Knob]
) -> list[str]:
    """Collect each missing or wrongly typed/axis-bound required control."""
    failures = []
    for requirement in requirements:
        failure = requirement.describe_failure(knobs_by_id.get(requirement.id))
        if failure is not None:
            failures.append(failure)
    return failures


def _proposal_matches_shape(
    knobs: list[Knob],
    observables: list[Observable],
    requirements: tuple[KnobRequirement, ...],
    *,
    require_exact_knob_ids: bool,
    required_observable_render: str | None,
) -> bool:
    """Check an alternate template mode without weakening the primary contract."""
    knobs_by_id = {knob.id: knob for knob in knobs}
    if _requirement_failures(requirements, knobs_by_id):
        return False
    if require_exact_knob_ids and set(knobs_by_id) != {item.id for item in requirements}:
        return False
    return required_observable_render is None or (
        len(observables) == 1 and observables[0].render == required_observable_render
    )


def _proposed_shape_description(knobs: list[Knob]) -> str:
    """Name unsupported bindings without assuming a particular hero or pack."""
    if len(knobs) == 1 and knobs[0].binding.kind == "argument":
        return "a direct single-argument call"
    bindings = ", ".join(
        f"{knob.id}:{knob.binding.kind}" for knob in knobs
    ) or "no knobs"
    return f"knobs with bindings {bindings}"


@dataclass(frozen=True)
class EntryPointTemplate:
    """A paired harness/reference implementation for one stable entry-point ID."""

    harness_body: HarnessBodyGenerator
    reference_program: ReferenceProgramGenerator
    proposal_shape: ProposalShape
    symmetrically_seeded_dependency_kinds: frozenset[str] = frozenset()
    numeric_fallback: Callable[[], PartialInteractionSpec] | None = None


_HERO1_HARNESS_TEMPLATE = """\
import importlib.util
import json
import os
import random
import sys

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
    entry_callable = module
    for part in ENTRY_POINT.split("."):
        entry_callable = getattr(entry_callable, part)
    entry_code = getattr(entry_callable, "__code__", None)
    target_module_path = os.path.abspath(MODULE_PATH)
    executed_lines = set()
    entry_lines = set()
    line_hits = {}

    def trace_lines(frame, event, _arg):
        if event == "line" and os.path.abspath(frame.f_code.co_filename) == target_module_path:
            executed_lines.add(frame.f_lineno)
            line_hits[frame.f_lineno] = line_hits.get(frame.f_lineno, 0) + 1
            if entry_code is not None and frame.f_code is entry_code:
                entry_lines.add(frame.f_lineno)
        return trace_lines

    previous_trace = sys.gettrace()
    sys.settrace(trace_lines)
    limit = int(config_values.get("limit_per_sec", 100))
    burst = int(config_values.get("burst", 0))
    try:
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
    finally:
        sys.settrace(previous_trace)

    return {
        "entry_point": ENTRY_POINT,
        "driver": driver,
        "observations": {observable["id"]: admitted for observable in OBSERVABLES},
        "stub_config": STUB_CONFIG,
        "trace": {
            "file": MODULE_PATH,
            "executed_lines": sorted(executed_lines),
            "entry_lines": sorted(entry_lines),
            "line_hits": {str(line): line_hits[line] for line in sorted(line_hits)},
        },
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
"""


def _hero1_harness_body(request: HarnessBodyRequest) -> str:
    """Render Hero 1's original RateLimiter.admit harness without changing its bytes."""
    replacements = {
        "__ENTRY_POINT__": json.dumps(request.entry_point_fn),
        # These constants are embedded in *Python* source, rather than a JSON
        # document. ``repr`` therefore preserves Python values such as None.
        "__DEFAULT_CONFIG__": repr(request.default_config),
        "__CONFIG_KNOBS__": repr(request.config_knobs),
        "__DRIVER_KNOBS__": repr(request.driver_knobs),
        "__STUB_CONFIG__": repr(request.stub_config),
        "__OBSERVABLES__": repr(request.observables),
    }
    source = _HERO1_HARNESS_TEMPLATE.replace("__MODULE_PATH__", json.dumps(request.module_path))
    for token, value in replacements.items():
        source = source.replace(token, value)
    return source


def _hero1_reference_program(request: ReferenceProgramRequest) -> str:
    """Run Hero 1's RateLimiter.admit module directly, independently of its harness."""
    config_knobs = [
        {"id": knob.id, "param": knob.binding.path, "default": knob.default}
        for knob in request.knobs
        if knob.binding.kind == "config"
    ]
    driver_knobs = [
        {"id": knob.id, "param": knob.binding.param, "default": knob.default}
        for knob in request.knobs
        if knob.binding.kind == "driver"
    ]
    observable_ids = [observable.id for observable in request.observables]
    return f"""\
import importlib.util
import json
import random

config = json.loads({json.dumps(json.dumps(request.point))})
random.seed({request.seed})
config_knobs = json.loads({json.dumps(json.dumps(config_knobs))})
driver_knobs = json.loads({json.dumps(json.dumps(driver_knobs))})
observable_ids = json.loads({json.dumps(json.dumps(observable_ids))})
spec = importlib.util.spec_from_file_location("lever_reference", {request.module_path!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def values(knobs):
    return {{item["param"]: config.get(item["id"], config.get(item["param"], item["default"])) for item in knobs}}

config_values = values(config_knobs)
driver = values(driver_knobs)
limit = int(config_values.get("limit_per_sec", 100))
burst = int(config_values.get("burst", 0))
try:
    limiter = module.RateLimiter(limit_per_sec=limit, burst=burst)
except TypeError:
    limiter = module.RateLimiter(limit_per_sec=limit)
rps = max(1, int(driver.get("rps", driver.get("requests_per_tenant_per_sec", 1))))
tenants = max(1, int(driver.get("tenants", driver.get("tenant_count", 1))))
admitted = 0
started_at = 0.0
for request_index in range(rps):
    now = started_at + request_index / rps
    for tenant_index in range(tenants):
        admitted += limiter.admit(f"tenant-{{tenant_index}}", now)
OBSERVATIONS = {{observable_id: admitted for observable_id in observable_ids}}
"""


_HERO2_SIMULATION = """\
def _p99(values):
    values = sorted(values)
    return values[max(0, math.ceil(0.99 * len(values)) - 1)]


def _simulate(entry_callable, config, seed):
    clients = max(1, int(config.get("clients", 100)))
    failure_rate = min(1.0, max(0.0, float(config.get("failureRate", 0.5))))
    max_retries = max(1, int(config.get("maxRetries", 5)))
    # Keep failure outcomes separate from full-jitter draws: both versions see
    # the same retry outcomes, while only head consumes the jitter stream.
    failure_rng = random.Random(f"{seed}:failure-outcomes")
    failures = [
        [failure_rng.random() < failure_rate for _ in range(max_retries)]
        for _ in range(clients)
    ]
    # The module's random stream is the only source used by full jitter, and
    # starts from the same seed in both A and B. Time is entirely simulated.
    random.seed(seed)
    events = [(0.0, client, 0) for client in range(clients)]
    heapq.heapify(events)
    completion_times = []
    while events:
        scheduled_at = events[0][0]
        batch = []
        while events and events[0][0] == scheduled_at:
            batch.append(heapq.heappop(events))
        for _, client, attempt in batch:
            # Initial requests are not retries. Later simultaneous retries pay
            # one deterministic simulated service slot per peer: the bounded
            # contention model that makes the fixed-backoff herd observable.
            contention = 0.0 if attempt == 0 else float(len(batch) - 1)
            now = scheduled_at + contention
            if failures[client][attempt] and attempt + 1 < max_retries:
                heapq.heappush(events, (now + entry_callable(attempt), client, attempt + 1))
            else:
                completion_times.append(now)
    return _p99(completion_times)
"""


_HERO2_HARNESS_TEMPLATE = """\
import heapq
import importlib.util
import json
import math
import os
import random
import sys

MODULE_PATH = __MODULE_PATH__
ENTRY_POINT = __ENTRY_POINT__
DEFAULT_CONFIG = __DEFAULT_CONFIG__
STUB_CONFIG = __STUB_CONFIG__
OBSERVABLES = __OBSERVABLES__


def _load_module():
    spec = importlib.util.spec_from_file_location("lever_target", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import target module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


__SIMULATION__


def run(config=None, seed=0):
    config = dict(DEFAULT_CONFIG if config is None else config)
    module = _load_module()
    entry_callable = module
    for part in ENTRY_POINT.split("."):
        entry_callable = getattr(entry_callable, part)
    entry_code = getattr(entry_callable, "__code__", None)
    target_module_path = os.path.abspath(MODULE_PATH)
    executed_lines = set()
    entry_lines = set()
    line_hits = {}

    def trace_lines(frame, event, _arg):
        if event == "line" and os.path.abspath(frame.f_code.co_filename) == target_module_path:
            executed_lines.add(frame.f_lineno)
            line_hits[frame.f_lineno] = line_hits.get(frame.f_lineno, 0) + 1
            if entry_code is not None and frame.f_code is entry_code:
                entry_lines.add(frame.f_lineno)
        return trace_lines

    previous_trace = sys.gettrace()
    sys.settrace(trace_lines)
    try:
        p99_completion_time = _simulate(entry_callable, config, seed)
    finally:
        sys.settrace(previous_trace)

    return {
        "entry_point": ENTRY_POINT,
        "driver": {key: config[key] for key in sorted(config)},
        "observations": {
            observable["id"]: p99_completion_time for observable in OBSERVABLES
        },
        "stub_config": STUB_CONFIG,
        "trace": {
            "file": MODULE_PATH,
            "executed_lines": sorted(executed_lines),
            "entry_lines": sorted(entry_lines),
            "line_hits": {str(line): line_hits[line] for line in sorted(line_hits)},
        },
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
"""


def _hero2_harness_body(request: HarnessBodyRequest) -> str:
    """Render the seeded concurrent-retry driver for module-level ``next_delay``."""
    replacements = {
        "__ENTRY_POINT__": json.dumps(request.entry_point_fn),
        "__DEFAULT_CONFIG__": repr(request.default_config),
        "__STUB_CONFIG__": repr(request.stub_config),
        "__OBSERVABLES__": repr(request.observables),
        "__SIMULATION__": _HERO2_SIMULATION,
    }
    source = _HERO2_HARNESS_TEMPLATE.replace("__MODULE_PATH__", json.dumps(request.module_path))
    for token, value in replacements.items():
        source = source.replace(token, value)
    return source


def _hero2_reference_program(request: ReferenceProgramRequest) -> str:
    """Run Hero 2's module-level ``next_delay`` directly with the same seeded driver."""
    defaults = {knob.id: knob.default for knob in request.knobs}
    observable_ids = [observable.id for observable in request.observables]
    return f"""\
import heapq
import importlib.util
import json
import math
import random

config = dict({defaults!r})
config.update(json.loads({json.dumps(json.dumps(request.point))}))
observable_ids = json.loads({json.dumps(json.dumps(observable_ids))})
spec = importlib.util.spec_from_file_location("lever_reference", {request.module_path!r})
if spec is None or spec.loader is None:
    raise ImportError("Cannot import reference module")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

{_HERO2_SIMULATION}

p99_completion_time = _simulate(module.next_delay, config, {json.dumps(request.seed)})
OBSERVATIONS = {{observable_id: p99_completion_time for observable_id in observable_ids}}
"""


_HERO3_HARNESS_TEMPLATE = """\
import importlib.util
import json
import os
import sys

MODULE_PATH = __MODULE_PATH__
ENTRY_POINT = __ENTRY_POINT__
DEFAULT_CONFIG = __DEFAULT_CONFIG__
STUB_CONFIG = __STUB_CONFIG__
OBSERVABLES = __OBSERVABLES__


def _load_module():
    spec = importlib.util.spec_from_file_location("lever_target", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import target module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(config=None, seed=0):
    config = dict(DEFAULT_CONFIG if config is None else config)
    module = _load_module()
    entry_callable = module
    for part in ENTRY_POINT.split("."):
        entry_callable = getattr(entry_callable, part)
    entry_code = getattr(entry_callable, "__code__", None)
    target_module_path = os.path.abspath(MODULE_PATH)
    executed_lines = set()
    entry_lines = set()
    line_hits = {}

    def trace_lines(frame, event, _arg):
        if event == "line" and os.path.abspath(frame.f_code.co_filename) == target_module_path:
            executed_lines.add(frame.f_lineno)
            line_hits[frame.f_lineno] = line_hits.get(frame.f_lineno, 0) + 1
            if entry_code is not None and frame.f_code is entry_code:
                entry_lines.add(frame.f_lineno)
        return trace_lines

    role = str(config.get("role", "viewer"))
    resource = str(config.get("resource", "doc"))
    same_tenant = bool(config.get("same_tenant", True))
    previous_trace = sys.gettrace()
    sys.settrace(trace_lines)
    try:
        allowed = bool(entry_callable(role, "read", resource, same_tenant))
    finally:
        sys.settrace(previous_trace)

    return {
        "entry_point": ENTRY_POINT,
        "inputs": {
            "role": role,
            "action": "read",
            "resource": resource,
            "same_tenant": same_tenant,
        },
        "observations": {
            observable["id"]: int(allowed)
            if observable["render"] == "scalar"
            else allowed
            for observable in OBSERVABLES
        },
        "stub_config": STUB_CONFIG,
        "trace": {
            "file": MODULE_PATH,
            "executed_lines": sorted(executed_lines),
            "entry_lines": sorted(entry_lines),
            "line_hits": {str(line): line_hits[line] for line in sorted(line_hits)},
        },
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
"""


def _hero3_harness_body(request: HarnessBodyRequest) -> str:
    """Render Hero 3's data-only permission-matrix invocation."""
    replacements = {
        "__ENTRY_POINT__": json.dumps(request.entry_point_fn),
        "__DEFAULT_CONFIG__": repr(request.default_config),
        "__STUB_CONFIG__": repr(request.stub_config),
        "__OBSERVABLES__": repr(request.observables),
    }
    source = _HERO3_HARNESS_TEMPLATE.replace("__MODULE_PATH__", json.dumps(request.module_path))
    for token, value in replacements.items():
        source = source.replace(token, value)
    return source


def _hero3_reference_program(request: ReferenceProgramRequest) -> str:
    """Invoke Hero 3's real ``can`` function directly, independent of the harness."""
    defaults = {knob.id: knob.default for knob in request.knobs}
    observable_specs = [
        {"id": observable.id, "render": observable.render}
        for observable in request.observables
    ]
    return f"""\
import importlib.util
import json

config = dict({defaults!r})
config.update(json.loads({json.dumps(json.dumps(request.point))}))
spec = importlib.util.spec_from_file_location("lever_reference", {request.module_path!r})
if spec is None or spec.loader is None:
    raise ImportError("Cannot import reference module")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

role = str(config.get("role", "viewer"))
resource = str(config.get("resource", "doc"))
same_tenant = bool(config.get("same_tenant", True))
allowed = bool(module.can(role, "read", resource, same_tenant))
OBSERVATIONS = {{
    observable["id"]: int(allowed)
    if observable["render"] == "scalar"
    else allowed
    for observable in {observable_specs!r}
}}
"""


def _hero3_numeric_fn_fallback() -> PartialInteractionSpec:
    """Offer an honest scalar view when the permission-matrix shape is unservable."""
    return PartialInteractionSpec(
        thesis="Cross-tenant group inheritance changes the permission decision.",
        domainPack=DomainPackId.NUMERIC_FN,
        knobs=[
            Knob(
                id="role",
                label="role",
                binding=ArgumentBinding(kind="argument", fn="can", argIndex=0),
                type="enum",
                domain=EnumDomain(values=["contractor"]),
                default="contractor",
                scale="linear",
                unit=None,
            ),
            Knob(
                id="resource",
                label="resource",
                binding=ArgumentBinding(kind="argument", fn="can", argIndex=2),
                type="enum",
                domain=EnumDomain(values=["audit-log"]),
                default="audit-log",
                scale="linear",
                unit=None,
            ),
            Knob(
                id="same_tenant",
                label="same tenant (1=yes, 0=no)",
                binding=ArgumentBinding(kind="argument", fn="can", argIndex=3),
                type="scalar",
                domain=NumericDomain(min=0, max=1, step=1),
                default=1,
                scale="linear",
                unit=None,
                axisRole="x",
            ),
        ],
        observables=[
            Observable(
                id="allow",
                label="permission granted",
                extractor=ReturnValueExtractor(kind="returnValue", path="$"),
                render="scalar",
                unit=None,
                compareMode="delta",
            )
        ],
    )


_HERO4_HARNESS_TEMPLATE = """\\
import importlib.util
import json
import os
import sys
from datetime import datetime
from decimal import Decimal

MODULE_PATH = __MODULE_PATH__
ENTRY_POINT = __ENTRY_POINT__
DEFAULT_CONFIG = __DEFAULT_CONFIG__
STUB_CONFIG = __STUB_CONFIG__
OBSERVABLES = __OBSERVABLES__


def _load_module():
    spec = importlib.util.spec_from_file_location("lever_target", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import target module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(config=None, seed=0):
    config = dict(DEFAULT_CONFIG if config is None else config)
    module = _load_module()
    entry_callable = module
    for part in ENTRY_POINT.split("."):
        entry_callable = getattr(entry_callable, part)
    entry_code = getattr(entry_callable, "__code__", None)
    target_module_path = os.path.abspath(MODULE_PATH)
    executed_lines = set()
    entry_lines = set()
    line_hits = {}

    def trace_lines(frame, event, _arg):
        if event == "line" and os.path.abspath(frame.f_code.co_filename) == target_module_path:
            executed_lines.add(frame.f_lineno)
            line_hits[frame.f_lineno] = line_hits.get(frame.f_lineno, 0) + 1
            if entry_code is not None and frame.f_code is entry_code:
                entry_lines.add(frame.f_lineno)
        return trace_lines

    cohort = str(config.get("cohort", "control"))
    flag_state = str(config.get("flagState", "off"))
    cart_value = Decimal(str(config.get("cartValue", "0")))
    # ``now`` is a genuine data argument, supplied at one shared fixed instant.
    now = datetime(2026, 6, 15)
    previous_trace = sys.gettrace()
    sys.settrace(trace_lines)
    try:
        discount = entry_callable(
            module.User(cohort=cohort, flag_state=flag_state),
            module.Cart(cart_value=cart_value),
            now,
        )
    finally:
        sys.settrace(previous_trace)

    return {
        "entry_point": ENTRY_POINT,
        "inputs": {
            "cohort": cohort,
            "flagState": flag_state,
            "cartValue": str(cart_value),
        },
        "observations": {observable["id"]: str(discount) for observable in OBSERVABLES},
        "stub_config": STUB_CONFIG,
        "trace": {
            "file": MODULE_PATH,
            "executed_lines": sorted(executed_lines),
            "entry_lines": sorted(entry_lines),
            "line_hits": {str(line): line_hits[line] for line in sorted(line_hits)},
        },
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
"""


def _hero4_harness_body(request: HarnessBodyRequest) -> str:
    """Render the direct-data feature-flag invocation for ``should_apply_discount``."""
    replacements = {
        "__ENTRY_POINT__": json.dumps(request.entry_point_fn),
        "__DEFAULT_CONFIG__": repr(request.default_config),
        "__STUB_CONFIG__": repr(request.stub_config),
        "__OBSERVABLES__": repr(request.observables),
    }
    source = _HERO4_HARNESS_TEMPLATE.replace("__MODULE_PATH__", json.dumps(request.module_path))
    for token, value in replacements.items():
        source = source.replace(token, value)
    return source


def _hero4_reference_program(request: ReferenceProgramRequest) -> str:
    """Invoke Hero 4's real pricing function directly, without importing a harness."""
    defaults = {knob.id: knob.default for knob in request.knobs}
    observable_ids = [observable.id for observable in request.observables]
    return f"""\\
import importlib.util
import json
from datetime import datetime
from decimal import Decimal

config = dict({defaults!r})
config.update(json.loads({json.dumps(json.dumps(request.point))}))
spec = importlib.util.spec_from_file_location("lever_reference", {request.module_path!r})
if spec is None or spec.loader is None:
    raise ImportError("Cannot import reference module")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

discount = module.should_apply_discount(
    module.User(
        cohort=str(config.get("cohort", "control")),
        flag_state=str(config.get("flagState", "off")),
    ),
    module.Cart(cart_value=Decimal(str(config.get("cartValue", "0")))),
    datetime(2026, 6, 15),
)
OBSERVATIONS = {{observable_id: str(discount) for observable_id in {observable_ids!r}}}
"""


ENTRY_POINT_REGISTRY: Mapping[str, EntryPointTemplate] = MappingProxyType(
    {
        "RateLimiter.admit": EntryPointTemplate(
            harness_body=_hero1_harness_body,
            reference_program=_hero1_reference_program,
            proposal_shape=ProposalShape(
                workload_description="a rate-limiter request workload",
                # These controls expose the behavioral dimension of this diff:
                # shared-vs-tenant-scoped admission plus the shared burst pool.
                # Letting the template silently supply tenants=1 or burst=0
                # creates a mechanically runnable but behaviorally degenerate
                # microworld, so all four constructor/workload controls are
                # required just as strictly as the later hero contracts.
                required_driver_params=("rps", "tenants"),
                allowed_binding_kinds=frozenset({"driver", "config"}),
                required_knobs=(
                    KnobRequirement(
                        "limit_per_sec",
                        type="integer",
                        binding_kind="config",
                        config_path="limit_per_sec",
                    ),
                    KnobRequirement(
                        "burst",
                        type="integer",
                        binding_kind="config",
                        config_path="burst",
                    ),
                    KnobRequirement("rps", type="integer", binding_kind="driver"),
                    KnobRequirement("tenants", type="integer", binding_kind="driver"),
                ),
                require_exact_knob_ids=True,
                expected_control_ids=("limit_per_sec", "burst", "rps", "tenants"),
            ),
        ),
        "next_delay": EntryPointTemplate(
            harness_body=_hero2_harness_body,
            reference_program=_hero2_reference_program,
            proposal_shape=ProposalShape(
                workload_description="a concurrent-retry workload",
                required_driver_params=("clients", "failureRate", "maxRetries"),
                allowed_binding_kinds=frozenset({"driver"}),
                required_knobs=(
                    KnobRequirement("clients", type="integer", binding_kind="driver"),
                    KnobRequirement("failureRate", type="scalar", binding_kind="driver"),
                    KnobRequirement("maxRetries", type="integer", binding_kind="driver"),
                ),
                require_exact_knob_ids=True,
            ),
            symmetrically_seeded_dependency_kinds=frozenset({"random"}),
        ),
        "can": EntryPointTemplate(
            harness_body=_hero3_harness_body,
            reference_program=_hero3_reference_program,
            proposal_shape=ProposalShape(
                workload_description="a permission matrix",
                required_driver_params=(),
                allowed_binding_kinds=frozenset({"argument", "config"}),
                required_knobs=(
                    KnobRequirement("role", type="enum", axis_role="x"),
                    KnobRequirement("resource", type="enum", axis_role="y"),
                    KnobRequirement("same_tenant", type="boolean", binding_kind="argument"),
                ),
                require_exact_knob_ids=True,
                required_observable_render="matrixCell",
                expected_control_ids=("role", "resource", "same_tenant"),
                numeric_fallback_requirements=(
                    KnobRequirement("role", type="enum"),
                    KnobRequirement("resource", type="enum"),
                    KnobRequirement(
                        "same_tenant",
                        type="scalar",
                        axis_role="x",
                        binding_kind="argument",
                    ),
                ),
                numeric_fallback_render="scalar",
            ),
            numeric_fallback=_hero3_numeric_fn_fallback,
        ),
        "should_apply_discount": EntryPointTemplate(
            harness_body=_hero4_harness_body,
            reference_program=_hero4_reference_program,
            proposal_shape=ProposalShape(
                workload_description="a feature-flag branch-trace workload",
                required_driver_params=(),
                allowed_binding_kinds=frozenset({"config"}),
                required_knobs=(
                    KnobRequirement(
                        "cohort",
                        type="enum",
                        binding_kind="config",
                        config_path="user.cohort",
                    ),
                    KnobRequirement(
                        "flagState",
                        type="enum",
                        binding_kind="config",
                        config_path="user.flag_state",
                    ),
                    KnobRequirement(
                        "cartValue",
                        type="scalar",
                        binding_kind="config",
                        config_path="cart.cart_value",
                    ),
                ),
                require_exact_knob_ids=True,
                required_observable_render="pathTrace",
                expected_control_ids=("cohort", "flagState", "cartValue"),
            ),
        ),
    }
)


def get_entry_point_template(entry_point_fn: str) -> EntryPointTemplate | None:
    """Look up an executable shape by Scout's stable EntryPoint.fn identifier."""
    return ENTRY_POINT_REGISTRY.get(entry_point_fn)


def entry_point_prompt_contract(entry_point_fn: str) -> dict[str, Any] | None:
    """Return the executable proposal contract for a registered entry point, if any."""
    template = get_entry_point_template(entry_point_fn)
    if template is None:
        return None
    return template.proposal_shape.prompt_contract(entry_point_fn)


__all__ = [
    "ENTRY_POINT_REGISTRY",
    "EntryPointTemplate",
    "HarnessBodyRequest",
    "KnobRequirement",
    "ProposalShape",
    "ReferenceProgramRequest",
    "entry_point_prompt_contract",
    "get_entry_point_template",
]
