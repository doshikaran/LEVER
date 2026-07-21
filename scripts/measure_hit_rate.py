"""Runs every fixture pair through the real pipeline against fakes (no live e2b/LLM
spend) and reports which terminal outcome each one reached, as an honest proxy for
the arbitrary-diff hit rate SPEC.md requires in the README.

Adaptation note (Task 12): the plan's illustrative call used a bare
``FakeLLMClient()``.  The real ``infra.fakes.fake_llm.FakeLLMClient`` (used
throughout ``domain/tests/``) instead requires a ``responses: list[dict]``
constructor argument — one canned Delta Analyst proposal per LLM call it will
serve.  There is no single canned response that is domain-appropriate for all
six fixtures (a rate-limiter proposal is nonsensical for the permission or
decision-tree fixtures and would trivially fail registry compatibility).  So
this script feeds each fixture the same domain-matched, already
hand-verified proposal that its own dedicated test file uses to reach a
verified widget (``domain/tests/test_orchestrator.py``,
``test_hero2_registry.py``, ``test_hero3_registry.py``, ``test_hero4.py``,
``test_branch_instrumentation.py``, ``test_synthesizer.py``).

This measures whether the deterministic downstream pipeline (Harness
Engineer -> Fidelity Verifier -> Adversary -> Synthesizer) can turn a
*correctly shaped* Delta Analyst proposal into a verified widget for each
fixture's domain pack.  It is a mechanics hit-rate, not a measurement of
Delta Analyst's real-world domain-classification accuracy on a fresh
arbitrary diff -- that would require live LLM calls, which is explicitly out
of scope (no live e2b/LLM spend).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.orchestrator import run_pipeline
from infra.fakes.fake_llm import FakeLLMClient
from infra.fakes.fake_sandbox import FakeSandboxRuntime

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures"


# Hero 1 -- rate-limiter, from domain/tests/test_orchestrator.py::_valid_response
_HERO1_PROPOSAL = {
    "thesis": "Tenant load changes admitted requests in the new limiter.",
    "domainPack": "rate-limiter",
    "knobs": [
        {
            "id": "limit_per_sec",
            "label": "per-tenant limit",
            "binding": {"kind": "config", "path": "limit_per_sec"},
            "type": "integer",
            "domain": {"min": 1, "max": 200, "step": 1},
            "default": 50,
            "scale": "linear",
            "unit": "requests / sec",
        },
        {
            "id": "burst",
            "label": "burst allowance",
            "binding": {"kind": "config", "path": "burst"},
            "type": "integer",
            "domain": {"min": 0, "max": 100, "step": 1},
            "default": 10,
            "scale": "linear",
            "unit": "requests",
        },
        {
            "id": "rps",
            "label": "requests per second",
            "binding": {"kind": "driver", "param": "rps"},
            "type": "integer",
            "domain": {"min": 1, "max": 100, "step": 1},
            "default": 3,
            "scale": "linear",
            "unit": "requests / sec",
        },
        {
            "id": "tenants",
            "label": "tenant count",
            "binding": {"kind": "driver", "param": "tenants"},
            "type": "integer",
            "domain": {"min": 1, "max": 32, "step": 1},
            "default": 2,
            "scale": "linear",
            "unit": "tenants",
        },
    ],
    "observables": [
        {
            "id": "admitted",
            "label": "admitted requests",
            "extractor": {"kind": "counter", "name": "admitted"},
            "render": "timeseries",
            "unit": "requests",
            "compareMode": "overlay",
        }
    ],
}

# Hero 2 -- rate-limiter, from domain/tests/test_hero2_registry.py::_hero2_spec
_HERO2_PROPOSAL = {
    "thesis": "Full jitter desynchronizes concurrent exponential retries.",
    "domainPack": "rate-limiter",
    "knobs": [
        {
            "id": "clients",
            "label": "clients",
            "binding": {"kind": "driver", "param": "clients"},
            "type": "integer",
            "domain": {"min": 1, "max": 200, "step": 1},
            "default": 100,
            "scale": "linear",
            "unit": "clients",
        },
        {
            "id": "failureRate",
            "label": "failure rate",
            "binding": {"kind": "driver", "param": "failureRate"},
            "type": "scalar",
            "domain": {"min": 0, "max": 1, "step": 0.01},
            "default": 0.7,
            "scale": "linear",
            "unit": None,
        },
        {
            "id": "maxRetries",
            "label": "max retries",
            "binding": {"kind": "driver", "param": "maxRetries"},
            "type": "integer",
            "domain": {"min": 1, "max": 10, "step": 1},
            "default": 6,
            "scale": "linear",
            "unit": "attempts",
        },
    ],
    "observables": [
        {
            "id": "p99_completion_time",
            "label": "p99 completion time",
            "extractor": {"kind": "trace", "event": "completion_time", "agg": "p99"},
            "render": "timeseries",
            "unit": "seconds",
            "compareMode": "overlay",
        }
    ],
}

# Hero 3 -- permission, from domain/tests/test_hero3_registry.py::_hero3_spec
_HERO3_PROPOSAL = {
    "thesis": "Group inheritance grants contractors cross-tenant audit-log access.",
    "domainPack": "permission",
    "knobs": [
        {
            "id": "role",
            "label": "role",
            "binding": {"kind": "argument", "fn": "can", "argIndex": 0},
            "type": "enum",
            "domain": {"values": ["viewer", "editor", "admin", "contractor"]},
            "default": "viewer",
            "scale": "linear",
            "unit": None,
            "axisRole": "x",
        },
        {
            "id": "resource",
            "label": "resource",
            "binding": {"kind": "argument", "fn": "can", "argIndex": 2},
            "type": "enum",
            "domain": {"values": ["doc", "billing", "audit-log", "settings"]},
            "default": "doc",
            "scale": "linear",
            "unit": None,
            "axisRole": "y",
        },
        {
            "id": "same_tenant",
            "label": "same tenant",
            "binding": {"kind": "argument", "fn": "can", "argIndex": 3},
            "type": "boolean",
            "domain": {"values": ["false", "true"]},
            "default": True,
            "scale": "linear",
            "unit": None,
        },
    ],
    "observables": [
        {
            "id": "allow",
            "label": "allow/deny",
            "extractor": {"kind": "returnValue", "path": "$"},
            "render": "matrixCell",
            "unit": None,
            "compareMode": "delta",
        }
    ],
}

# Hero 4 -- decision-tree, from domain/tests/test_hero4.py::_spec
_HERO4_PROPOSAL = {
    "thesis": "The rollout gate changes which pricing predicates execute.",
    "domainPack": "decision-tree",
    "knobs": [
        {
            "id": "cohort",
            "label": "cohort",
            "binding": {"kind": "config", "path": "user.cohort"},
            "type": "enum",
            "domain": {"values": ["control", "beta", "internal"]},
            "default": "beta",
            "scale": "linear",
            "unit": None,
        },
        {
            "id": "flagState",
            "label": "flag state",
            "binding": {"kind": "config", "path": "user.flag_state"},
            "type": "enum",
            "domain": {"values": ["off", "canary", "on"]},
            "default": "canary",
            "scale": "linear",
            "unit": None,
        },
        {
            "id": "cartValue",
            "label": "cart value",
            "binding": {"kind": "config", "path": "cart.cart_value"},
            "type": "scalar",
            "domain": {"min": 0, "max": 500, "step": 1},
            "default": 200,
            "scale": "linear",
            "unit": "USD",
        },
    ],
    "observables": [
        {
            "id": "path",
            "label": "executed pricing path",
            "extractor": {"kind": "path", "instrumentation": "branch"},
            "render": "pathTrace",
            "unit": None,
            "compareMode": "overlay",
        }
    ],
}

# synthetic_state_machine -- state-machine, from domain/tests/test_synthesizer.py::_state_machine_spec
_SYNTHETIC_STATE_MACHINE_PROPOSAL = {
    "thesis": "A pedestrian request changes which state the signal transitions to.",
    "domainPack": "state-machine",
    "knobs": [
        {
            "id": "current_state",
            "label": "current state",
            "binding": {"kind": "config", "path": "current_state"},
            "type": "enum",
            "domain": {"values": ["red", "green", "yellow"]},
            "default": "green",
            "scale": "linear",
            "unit": None,
        },
        {
            "id": "event",
            "label": "event",
            "binding": {"kind": "driver", "param": "event"},
            "type": "enum",
            "domain": {"values": ["timer", "pedestrian_request"]},
            "default": "timer",
            "scale": "linear",
            "unit": None,
        },
    ],
    "observables": [
        {
            "id": "current_state",
            "label": "current state",
            "extractor": {"kind": "returnValue", "path": "$"},
            "render": "nodeState",
            "unit": None,
            "compareMode": "delta",
        }
    ],
}

# synthetic_tree -- decision-tree, from domain/tests/test_branch_instrumentation.py::_decision_spec
_SYNTHETIC_TREE_PROPOSAL = {
    "thesis": "The zero boundary follows a different branch.",
    "domainPack": "decision-tree",
    "knobs": [
        {
            "id": "value",
            "label": "value",
            "binding": {"kind": "argument", "fn": "choose", "argIndex": 0},
            "type": "integer",
            "domain": {"min": -1, "max": 1, "step": 1},
            "default": 1,
            "scale": "linear",
            "unit": None,
        },
        {
            "id": "enabled",
            "label": "enabled",
            "binding": {"kind": "argument", "fn": "choose", "argIndex": 1},
            "type": "boolean",
            "domain": {"values": ["false", "true"]},
            "default": True,
            "scale": "linear",
            "unit": None,
        },
    ],
    "observables": [
        {
            "id": "path",
            "label": "branch path",
            "extractor": {"kind": "path", "instrumentation": "branch"},
            "render": "pathTrace",
            "unit": None,
            "compareMode": "overlay",
        }
    ],
}

PROPOSALS: dict[str, dict] = {
    "hero1": _HERO1_PROPOSAL,
    "hero2": _HERO2_PROPOSAL,
    "hero3": _HERO3_PROPOSAL,
    "hero4": _HERO4_PROPOSAL,
    "synthetic_state_machine": _SYNTHETIC_STATE_MACHINE_PROPOSAL,
    "synthetic_tree": _SYNTHETIC_TREE_PROPOSAL,
}


def main() -> None:
    results: dict[str, str] = {}
    for fixture_dir in sorted(p for p in FIXTURE_ROOT.iterdir() if p.is_dir()):
        base = fixture_dir / "base.py"
        head = fixture_dir / "head.py"
        if not (base.exists() and head.exists()):
            continue
        proposal = PROPOSALS.get(fixture_dir.name)
        if proposal is None:
            results[fixture_dir.name] = "SKIPPED (no domain-matched proposal available)"
            continue
        # A single re-selection kickback is permitted by Loop A/registry
        # compatibility; feed the same proposal twice so a kickback still
        # has a (repeated) response to consume rather than raising
        # AssertionError("received more completions than configured").
        outcome = run_pipeline(
            str(base), str(head),
            sandbox=FakeSandboxRuntime(),
            llm=FakeLLMClient([proposal, proposal]),
            model="fake", reasoning_effort="fake",
        )
        results[fixture_dir.name] = type(outcome).__name__
    total = len(results)
    verified = sum(1 for kind in results.values() if kind == "InteractionSpec")
    print(f"{verified}/{total} fixtures reached a verified widget:")
    for name, kind in results.items():
        print(f"  {name}: {kind}")


if __name__ == "__main__":
    main()
