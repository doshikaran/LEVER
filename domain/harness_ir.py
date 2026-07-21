"""Structured harness intermediate representation and deterministic Python renderer."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from domain.schema import (
    ArgumentBinding,
    ConfigBinding,
    DriverBinding,
    Knob,
    Observable,
    PartialInteractionSpec,
    ScopedChangeSet,
)
from domain.stubs import PlannedStub, StubPlan, stub_plan


class InvocationArg(BaseModel):
    """One positional or keyword argument drawn from a knob at runtime."""

    knobId: str
    asKeyword: str | None = None


class DirectInvocation(BaseModel):
    """Call a module-level function with plain-data arguments."""

    kind: Literal["direct"] = "direct"
    args: list[InvocationArg] = Field(default_factory=list)


class ConstructThenCall(BaseModel):
    """Construct a class, then call a method (e.g. ``Widget.process``)."""

    kind: Literal["construct_then_call"] = "construct_then_call"
    className: str
    constructorArgs: list[InvocationArg] = Field(default_factory=list)
    methodName: str
    callArgs: list[InvocationArg] = Field(default_factory=list)


Invocation = DirectInvocation | ConstructThenCall


class DriverLoop(BaseModel):
    """Optional synthetic workload loop parameterized by driver knobs."""

    kind: Literal["none", "counted_calls"] = "none"
    countKnobId: str | None = None
    repeatKnobId: str | None = None


class HarnessIR(BaseModel):
    """LLM-safe plan that renders to a byte-symmetric harness pair."""

    entryPoint: str
    invocation: Invocation
    driver: DriverLoop = Field(default_factory=DriverLoop)
    stubDependencies: list[str] = Field(default_factory=list)
    seedRandom: bool = True
    observationMode: Literal["return_value", "call_count"] = "return_value"


def build_harness_ir(
    scoped_change_set: ScopedChangeSet,
    partial_spec: PartialInteractionSpec,
    plan: StubPlan | None = None,
) -> tuple[HarnessIR, StubPlan]:
    """Derive a generative IR from Scout + Delta without requiring an LLM."""
    entry = scoped_change_set.entry_point
    if entry is None:
        raise ValueError("Harness IR requires a scoped entry point")
    plan = plan if plan is not None else stub_plan(scoped_change_set.dependency_ledger)
    if plan.is_unharnessable:
        raise ValueError(plan.unharnessable_reason or "Change is unharnessable")

    knobs = {knob.id: knob for knob in partial_spec.knobs}
    driver = _driver_from_knobs(partial_spec.knobs)
    consumed_ids = {driver.countKnobId, driver.repeatKnobId} - {None}
    invocation = _invocation_from_entry_and_knobs(
        entry.fn,
        partial_spec.knobs,
        signature=entry.signature,
        consumed_ids=consumed_ids,
    )
    observation_mode: Literal["return_value", "call_count"] = (
        "call_count" if driver.kind == "counted_calls" else "return_value"
    )
    ir = HarnessIR(
        entryPoint=entry.fn,
        invocation=invocation,
        driver=driver,
        stubDependencies=[stub.dependency for stub in plan.stubs],
        seedRandom=True,
        observationMode=observation_mode,
    )
    _validate_ir(ir, knobs, partial_spec.observables)
    return ir, plan


def render_harness_source(
    ir: HarnessIR,
    *,
    module_path: str,
    knobs: list[Knob],
    observables: list[Observable],
    stubs: tuple[PlannedStub, ...] | list[PlannedStub],
) -> str:
    """Render one harness file; only ``MODULE_PATH`` may differ between A and B."""
    defaults = {knob.id: knob.default for knob in knobs}
    stub_config = {stub.dependency: stub.as_dict() for stub in stubs}
    observable_specs = [
        {"id": observable.id, "render": observable.render}
        for observable in observables
    ]
    parts = [
        "import importlib.util",
        "import json",
        "import os",
        "import random",
        "import sys",
        "",
        f"MODULE_PATH = {json.dumps(module_path)}",
        f"ENTRY_POINT = {json.dumps(ir.entryPoint)}",
        f"DEFAULT_CONFIG = {repr(defaults)}",
        f"STUB_CONFIG = {repr(stub_config)}",
        f"OBSERVABLES = {repr(observable_specs)}",
        f"IR = json.loads({json.dumps(json.dumps(ir.model_dump(mode='json'), sort_keys=True))})",
        "",
        _GENERIC_RUNTIME_HELPERS.strip(),
        "",
        _HARNESS_RUN_BODY.strip(),
        "",
    ]
    return "\n".join(parts) + "\n"


def render_reference_program(
    ir: HarnessIR,
    *,
    module_path: str,
    knobs: list[Knob],
    observables: list[Observable],
    point: dict[str, Any],
    seed: int | str,
) -> str:
    """Independent direct-module program used by Fidelity Verifier (no harness import)."""
    defaults = {knob.id: knob.default for knob in knobs}
    observable_ids = [observable.id for observable in observables]
    return (
        "import importlib.util\n"
        "import json\n"
        "import random\n"
        "\n"
        f"config = dict({defaults!r})\n"
        f"config.update(json.loads({json.dumps(json.dumps(point))}))\n"
        f"random.seed({json.dumps(seed)})\n"
        f"ir = json.loads({json.dumps(json.dumps(ir.model_dump(mode='json'), sort_keys=True))})\n"
        f"observable_ids = json.loads({json.dumps(json.dumps(observable_ids))})\n"
        f"spec = importlib.util.spec_from_file_location('lever_reference', {module_path!r})\n"
        "if spec is None or spec.loader is None:\n"
        "    raise ImportError('Cannot import reference module')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "\n"
        f"{_GENERIC_RUNTIME_HELPERS}\n"
        "value = _lever_execute(module, ir, config)\n"
        "OBSERVATIONS = {observable_id: value for observable_id in observable_ids}\n"
    )


def _validate_ir(ir: HarnessIR, knobs: dict[str, Knob], observables: list[Observable]) -> None:
    """Reject IR that references unknown knobs or leaves observables undefined."""
    if not observables:
        raise ValueError("Harness IR requires at least one observable")
    referenced: set[str] = set()
    if isinstance(ir.invocation, DirectInvocation):
        referenced.update(arg.knobId for arg in ir.invocation.args)
    else:
        referenced.update(arg.knobId for arg in ir.invocation.constructorArgs)
        referenced.update(arg.knobId for arg in ir.invocation.callArgs)
    if ir.driver.countKnobId:
        referenced.add(ir.driver.countKnobId)
    if ir.driver.repeatKnobId:
        referenced.add(ir.driver.repeatKnobId)
    missing = sorted(referenced - set(knobs))
    if missing:
        raise ValueError(f"Harness IR references unknown knobs: {missing}")


def _method_param_names(signature: str | None) -> set[str]:
    """Caller-supplied parameter names from a signature, minus ``self``/``cls``."""
    if not signature:
        return set()
    open_paren = signature.find("(")
    close_paren = signature.rfind(")")
    if open_paren == -1 or close_paren <= open_paren:
        return set()
    names: set[str] = set()
    for parameter in signature[open_paren + 1 : close_paren].split(","):
        name = parameter.strip().lstrip("*").split(":", 1)[0].split("=", 1)[0].strip()
        if name and name not in {"self", "cls"}:
            names.add(name)
    return names


def _invocation_from_entry_and_knobs(
    entry_fn: str,
    knobs: list[Knob],
    *,
    signature: str | None = None,
    consumed_ids: set[str] | frozenset[str] = frozenset(),
) -> Invocation:
    """Map ParamBindings onto a direct call or construct-then-call shape.

    Driver-bound knobs that a counted-calls loop does *not* consume as a numeric
    count are categorical inputs (e.g. a state-machine ``start``/``event``). They
    must still be passed to the target, routed to the constructor or the method by
    matching the driver's ``param`` name against the method signature — otherwise a
    generic loop would try ``int('draft')`` and the whole change degrades.
    """
    parts = [part for part in entry_fn.split(".") if part]
    argument_knobs = [knob for knob in knobs if isinstance(knob.binding, ArgumentBinding)]
    config_knobs = [knob for knob in knobs if isinstance(knob.binding, ConfigBinding)]
    value_driver_knobs = [
        knob
        for knob in knobs
        if isinstance(knob.binding, DriverBinding) and knob.id not in consumed_ids
    ]
    method_params = _method_param_names(signature)

    def _sorted_arguments() -> list[InvocationArg]:
        return [
            InvocationArg(knobId=knob.id)
            for knob in sorted(
                argument_knobs,
                key=lambda item: item.binding.argIndex
                if isinstance(item.binding, ArgumentBinding)
                else 0,
            )
        ]

    # ``Class.method`` — construct then call. Bare ``function`` — direct call.
    if len(parts) >= 2 and parts[-1][:1].islower() and parts[-2][:1].isupper():
        constructor_args = [
            InvocationArg(knobId=knob.id, asKeyword=_keyword_for_config(knob))
            for knob in config_knobs
        ]
        call_args = _sorted_arguments()
        for knob in value_driver_knobs:
            assert isinstance(knob.binding, DriverBinding)
            arg = InvocationArg(knobId=knob.id, asKeyword=knob.binding.param)
            if knob.binding.param in method_params or not method_params:
                call_args.append(arg)
            else:
                constructor_args.append(arg)
        if not call_args and not constructor_args:
            call_args = [
                InvocationArg(knobId=knob.id)
                for knob in knobs
                if knob.binding.kind != "driver"
            ]
        return ConstructThenCall(
            className=parts[-2],
            constructorArgs=constructor_args,
            methodName=parts[-1],
            callArgs=call_args,
        )

    args: list[InvocationArg] = _sorted_arguments()
    for knob in config_knobs:
        args.append(InvocationArg(knobId=knob.id, asKeyword=_keyword_for_config(knob)))
    for knob in value_driver_knobs:
        assert isinstance(knob.binding, DriverBinding)
        args.append(InvocationArg(knobId=knob.id, asKeyword=knob.binding.param))
    if not args:
        args = [
            InvocationArg(knobId=knob.id)
            for knob in knobs
            if not isinstance(knob.binding, DriverBinding)
        ]
    return DirectInvocation(args=args)


def _keyword_for_config(knob: Knob) -> str:
    if isinstance(knob.binding, ConfigBinding):
        return knob.binding.path.split(".")[-1]
    return knob.id


def _driver_from_knobs(knobs: list[Knob]) -> DriverLoop:
    # Only a numeric driver knob can be a synthetic call *count*. A categorical
    # driver knob (enum/boolean) is a value input — e.g. a state-machine event —
    # and is bound as an argument by ``_invocation_from_entry_and_knobs`` instead.
    numeric_drivers = [
        knob
        for knob in knobs
        if isinstance(knob.binding, DriverBinding) and knob.type in {"scalar", "integer"}
    ]
    if not numeric_drivers:
        return DriverLoop(kind="none")
    primary = next(
        (
            knob
            for knob in numeric_drivers
            if (
                isinstance(knob.binding, DriverBinding)
                and knob.binding.param in {"rps", "clients", "n", "requests"}
            )
            or knob.id in {"rps", "clients", "n", "requests"}
        ),
        numeric_drivers[0],
    )
    secondary = next((knob for knob in numeric_drivers if knob.id != primary.id), None)
    return DriverLoop(
        kind="counted_calls",
        countKnobId=primary.id,
        repeatKnobId=secondary.id if secondary is not None else None,
    )


_GENERIC_RUNTIME_HELPERS = '''
def _lever_value(config, knob_id):
    return config[knob_id]


def _lever_bind(config, args):
    positional = []
    keywords = {}
    for item in args:
        value = _lever_value(config, item["knobId"])
        keyword = item.get("asKeyword")
        if keyword:
            keywords[keyword] = value
        else:
            positional.append(value)
    return positional, keywords


def _lever_resolve(module, entry_point):
    target = module
    for part in entry_point.split("."):
        target = getattr(target, part)
    return target


def _lever_execute(module, ir, config):
    invocation = ir["invocation"]
    if invocation["kind"] == "direct":
        target = _lever_resolve(module, ir["entryPoint"])
        positional, keywords = _lever_bind(config, invocation.get("args", []))
        driver = ir.get("driver") or {"kind": "none"}
        if driver.get("kind") == "counted_calls":
            count = max(1, int(_lever_value(config, driver["countKnobId"])))
            repeats = 1
            if driver.get("repeatKnobId"):
                repeats = max(1, int(_lever_value(config, driver["repeatKnobId"])))
            total = 0
            for _ in range(count):
                for _repeat in range(repeats):
                    result = target(*positional, **keywords)
                    if isinstance(result, bool):
                        total += int(result)
                    elif isinstance(result, (int, float)):
                        total += int(result)
                    else:
                        total += 1
            return total
        return target(*positional, **keywords)

    class_obj = getattr(module, invocation["className"])
    ctor_pos, ctor_kw = _lever_bind(config, invocation.get("constructorArgs", []))
    try:
        instance = class_obj(*ctor_pos, **ctor_kw)
    except TypeError:
        instance = class_obj(*ctor_pos)
    method = getattr(instance, invocation["methodName"])
    call_pos, call_kw = _lever_bind(config, invocation.get("callArgs", []))
    driver = ir.get("driver") or {"kind": "none"}
    if driver.get("kind") == "counted_calls":
        count = max(1, int(_lever_value(config, driver["countKnobId"])))
        repeats = 1
        if driver.get("repeatKnobId"):
            repeats = max(1, int(_lever_value(config, driver["repeatKnobId"])))
        total = 0
        for index in range(count):
            now = float(index) / float(count)
            for repeat_index in range(repeats):
                args = list(call_pos)
                if len(args) == 0 and not call_kw:
                    args = [f"tenant-{repeat_index}", now]
                elif len(args) == 1 and not call_kw:
                    args = [args[0], now]
                result = method(*args, **call_kw)
                if isinstance(result, bool):
                    total += int(result)
                elif isinstance(result, (int, float)):
                    total += int(result)
                else:
                    total += 1
        return total
    return method(*call_pos, **call_kw)
'''


_HARNESS_RUN_BODY = '''
def _load_module():
    spec = importlib.util.spec_from_file_location("lever_target", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import target module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(config=None, seed=0):
    config = dict(DEFAULT_CONFIG if config is None else config)
    random.seed(seed)
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
        value = _lever_execute(module, IR, config)
    finally:
        sys.settrace(previous_trace)

    return {
        "entry_point": ENTRY_POINT,
        "inputs": {key: config[key] for key in sorted(config)},
        "observations": {observable["id"]: value for observable in OBSERVABLES},
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
'''


__all__ = [
    "ConstructThenCall",
    "DirectInvocation",
    "DriverLoop",
    "HarnessIR",
    "InvocationArg",
    "build_harness_ir",
    "render_harness_source",
    "render_reference_program",
]
