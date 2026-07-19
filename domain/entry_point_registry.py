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
class EntryPointTemplate:
    """A paired harness/reference implementation for one stable entry-point ID."""

    harness_body: HarnessBodyGenerator
    reference_program: ReferenceProgramGenerator


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


ENTRY_POINT_REGISTRY: Mapping[str, EntryPointTemplate] = MappingProxyType(
    {
        "RateLimiter.admit": EntryPointTemplate(
            harness_body=_hero1_harness_body,
            reference_program=_hero1_reference_program,
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
    "ReferenceProgramRequest",
    "get_entry_point_template",
]
