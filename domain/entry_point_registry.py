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

from domain.schema import Knob, Observable


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

    def incompatibility_reason(
        self, entry_point_fn: str, knobs: list[Knob]
    ) -> str | None:
        """Explain why a valid InteractionSpec cannot be served by this template."""
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
        if not missing_params and not unsupported_kinds:
            return None

        expected = "/".join(self.required_driver_params)
        proposed_shape = _proposed_shape_description(knobs)
        return (
            f"registered template for '{entry_point_fn}' expects "
            f"{self.workload_description} ({expected}); proposed spec is "
            f"{proposed_shape}, which this template does not support"
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


ENTRY_POINT_REGISTRY: Mapping[str, EntryPointTemplate] = MappingProxyType(
    {
        "RateLimiter.admit": EntryPointTemplate(
            harness_body=_hero1_harness_body,
            reference_program=_hero1_reference_program,
            proposal_shape=ProposalShape(
                workload_description="a rate-limiter request workload",
                # The template defaults to one tenant when it is not exposed as
                # a control, so only rps is mandatory for a faithful invocation.
                required_driver_params=("rps",),
                allowed_binding_kinds=frozenset({"driver", "config"}),
            ),
        ),
        "next_delay": EntryPointTemplate(
            harness_body=_hero2_harness_body,
            reference_program=_hero2_reference_program,
            proposal_shape=ProposalShape(
                workload_description="a concurrent-retry workload",
                required_driver_params=("clients", "failureRate", "maxRetries"),
                allowed_binding_kinds=frozenset({"driver"}),
            ),
            symmetrically_seeded_dependency_kinds=frozenset({"random"}),
        ),
    }
)


def get_entry_point_template(entry_point_fn: str) -> EntryPointTemplate | None:
    """Look up an executable shape by Scout's stable EntryPoint.fn identifier."""
    return ENTRY_POINT_REGISTRY.get(entry_point_fn)


__all__ = [
    "ENTRY_POINT_REGISTRY",
    "EntryPointTemplate",
    "HarnessBodyRequest",
    "ProposalShape",
    "ReferenceProgramRequest",
    "get_entry_point_template",
]
