import importlib.util
import json
import os
import sys

MODULE_PATH = "/Users/karandoshi/Desktop/Karan Doshi/Projects/OpenAI Hackathon/lever/fixtures/hero3/base.py"
ENTRY_POINT = "can"
DEFAULT_CONFIG = {'role': 'contractor', 'resource': 'audit-log', 'same_tenant': 1.0}
STUB_CONFIG = {}
OBSERVABLES = [{'id': 'allow', 'label': 'permission granted', 'extractor': {'kind': 'returnValue', 'path': '$'}, 'render': 'scalar', 'unit': None, 'compareMode': 'delta'}]


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
