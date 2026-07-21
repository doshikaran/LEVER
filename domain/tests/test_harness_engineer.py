"""Deterministic coverage for Harness Engineer's symmetry and retry behavior."""

from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

import pytest

from domain.harness_engineer import (
    HarnessEngineer,
    UnsupportedTemplateProposal,
    VerifierFeedback,
    retry_plan,
    run_retry_loop,
)
from domain.entry_point_registry import get_entry_point_template
from domain.fidelity_verifier import _reference_program
from domain.schema import (
    AstNodeRef,
    ConfigBinding,
    CounterExtractor,
    DepEntry,
    DependencyLedger,
    DriverBinding,
    EntryPoint,
    Knob,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    ScopedChangeSet,
)
from infra.fakes.fake_sandbox import FakeSandboxRuntime


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero1"


def _normalize_harness_for_hashing(source: str) -> str:
    """Remove path-dependent content for stable cross-checkout hashing.

    Generated harnesses and reference programs embed absolute filesystem paths.
    To make hash assertions independent of checkout location, normalize these
    paths before computing the hash.
    """
    # Normalize MODULE_PATH assignments
    normalized = re.sub(
        r'MODULE_PATH\s*=\s*"[^"]*"',
        'MODULE_PATH = "<normalized>"',
        source
    )
    # Normalize spec_from_file_location paths
    normalized = re.sub(
        r'spec_from_file_location\([^,]+,\s*\'[^\']*\'',
        'spec_from_file_location("<normalized>", "<normalized>"',
        normalized
    )
    return normalized


def _hero_scope() -> ScopedChangeSet:
    """Return Hero 1's all-pure selected entry point and an innermost retry target."""
    return ScopedChangeSet(
        entry_point=EntryPoint(
            file=str(FIXTURE_DIR / "head.py"),
            fn="RateLimiter.admit",
            signature="RateLimiter.admit(self, tenant_id: str, now: float) -> bool",
        ),
        changed_nodes=[AstNodeRef(kind="function_definition", name="RateLimiter.admit", start_byte=0, end_byte=100)],
        dependency_ledger=DependencyLedger(),
    )


def _hero_spec() -> PartialInteractionSpec:
    """Return a parameterized Hero 1 rate-limiter workload specification."""
    return PartialInteractionSpec(
        thesis="Head adds a shared burst allowance to the per-tenant limiter.",
        domainPack="rate-limiter",
        knobs=[
            Knob(id="limit_per_sec", label="limit", binding=ConfigBinding(kind="config", path="limit_per_sec"), type="integer", domain=NumericDomain(min=1, max=100, step=1), default=5, scale="linear", unit="requests/s"),
            Knob(id="burst", label="burst", binding=ConfigBinding(kind="config", path="burst"), type="integer", domain=NumericDomain(min=0, max=50, step=1), default=2, scale="linear", unit="requests"),
            Knob(id="rps", label="rps", binding=DriverBinding(kind="driver", param="rps"), type="integer", domain=NumericDomain(min=1, max=100, step=1), default=3, scale="linear", unit="requests/s"),
            Knob(id="tenants", label="tenants", binding=DriverBinding(kind="driver", param="tenants"), type="integer", domain=NumericDomain(min=1, max=16, step=1), default=2, scale="linear", unit="tenants"),
        ],
        observables=[
            Observable(id="admitted", label="admitted", extractor=CounterExtractor(kind="counter", name="admitted"), render="timeseries", unit="requests", compareMode="overlay")
        ],
    )


def test_harness_engineer_generates_a_symmetric_zero_stub_hero1_pair() -> None:
    """Hero 1's pure ledger is a valid empty stub configuration, not a special failure."""
    pair = HarnessEngineer().generate(
        _hero_scope(),
        _hero_spec(),
        "/tmp/lever/base.py",
        "/tmp/lever/head.py",
    )

    assert pair.stub_config == ()
    assert pair.uncertainty_specs == ()
    assert pair.workload_driver.parameters == ("rps", "tenants")
    assert pair.harness_a.source.replace('"/tmp/lever/base.py"', '"MODULE"') == pair.harness_b.source.replace('"/tmp/lever/head.py"', '"MODULE"')


def test_rate_limiter_contract_rejects_the_live_rps_only_proposal() -> None:
    """A one-dimensional rate sweep cannot hide tenant/burst behavior any longer."""
    full_spec = _hero_spec()
    rps_only = full_spec.model_copy(update={"knobs": [full_spec.knobs[2]]})

    with pytest.raises(UnsupportedTemplateProposal) as error:
        HarnessEngineer().generate(
            _hero_scope(), rps_only, "/tmp/lever/base.py", "/tmp/lever/head.py"
        )

    assert str(error.value) == (
        "registered template for 'RateLimiter.admit' expects a rate-limiter request "
        "workload (limit_per_sec/burst/rps/tenants); proposed spec is knobs with "
        "bindings rps:driver, which this template does not support"
    )


def test_harness_retry_state_machine_advances_after_a_scripted_failure() -> None:
    """Attempt one fails, attempt two seeds clock/random and succeeds, so attempt three is unused."""
    scope = _hero_scope()
    attempts = retry_plan(
        scope,
        VerifierFeedback(implicated_dependencies=("requests.get",)),
    )
    runtime = FakeSandboxRuntime(
        scripted_results=[
            {"stdout": "", "stderr": "first failed", "exit_code": 1},
            {"stdout": "ok\n", "stderr": "", "exit_code": 0},
        ]
    )
    sandbox_id = runtime.create_sandbox("base")

    outcome = run_retry_loop(
        runtime,
        sandbox_id,
        attempts,
        lambda attempt: f"print('attempt {attempt.number}')",
    )

    assert outcome.succeeded
    assert [attempt.number for attempt in outcome.attempts] == [1, 2]
    assert outcome.attempts[0].stubbed_dependencies == ()
    assert outcome.attempts[1].seed_clock
    assert outcome.attempts[1].seed_random
    assert outcome.attempts[1].stubbed_dependencies == ("requests.get",)
    runtime.kill_sandbox(sandbox_id)


def test_harness_engineer_declares_uncertainty_for_each_non_pure_dependency() -> None:
    """Every non-pure kind receives the relevant Assayer uncertainty declaration."""
    scope = _hero_scope().model_copy(
        update={
            "dependency_ledger": DependencyLedger(
                entries=[
                    DepEntry(name="open", kind="io", depth=1),
                    DepEntry(name="time.time", kind="clock", depth=1),
                    DepEntry(name="random.random", kind="random", depth=1),
                    DepEntry(name="requests.get", kind="network", depth=1),
                    DepEntry(name="sqlite3.connect", kind="db", depth=1),
                    DepEntry(name="ctypes.CDLL", kind="native", depth=1),
                ]
            )
        }
    )

    pair = HarnessEngineer().generate(
        scope, _hero_spec(), "/tmp/lever/base.py", "/tmp/lever/head.py"
    )
    parameters = {stub.dependency: stub.parameters for stub in pair.stub_config}

    assert set(parameters) == {
        "open",
        "time.time",
        "random.random",
        "requests.get",
        "sqlite3.connect",
        "ctypes.CDLL",
    }
    assert "latency_ms" in parameters["open"]
    assert "cold_cache_probability" in parameters["requests.get"]
    assert "resolution_ms" in parameters["time.time"]
    assert "seed" in parameters["random.random"]
    assert "default_return" in parameters["sqlite3.connect"]
    assert "gc_pause_ms_per_100_ops" in parameters["ctypes.CDLL"]


def _scope_with_escalatable_dependencies() -> ScopedChangeSet:
    """RateLimiter.admit (no symmetric-seeding template exclusions) with a network
    dependency in the minimal set plus clock/random deps only attempt two forces in.

    Neither `_hero_scope()` (an intentionally-empty pure ledger) nor Hero 2's real
    Scout-derived ledger (a single `random`-kind entry that `next_delay`'s template
    always symmetrically seeds, so it can never appear in `stub_config` regardless
    of retry attempt) can exercise this escalation, so this follows the existing
    `test_harness_engineer_declares_uncertainty_for_each_non_pure_dependency`
    pattern of building a synthetic ledger on top of `_hero_scope()` instead.
    """
    return _hero_scope().model_copy(
        update={
            "dependency_ledger": DependencyLedger(
                entries=[
                    DepEntry(name="requests.get", kind="network", depth=1),
                    DepEntry(name="time.time", kind="clock", depth=1),
                    DepEntry(name="random.random", kind="random", depth=1),
                ]
            )
        }
    )


def test_retry_attempt_restricts_stubbed_dependencies_to_the_named_set() -> None:
    """Attempt 1 must not stub a dependency outside its minimal (network/db/native) set."""
    scope = _scope_with_escalatable_dependencies()
    spec = _hero_spec()
    attempts = retry_plan(scope)
    pair = HarnessEngineer().generate(
        scope, spec, str(FIXTURE_DIR / "base.py"), str(FIXTURE_DIR / "head.py"),
        retry_attempt=attempts[0],
    )
    stubbed_kinds = {stub.kind for stub in pair.stub_config}
    assert "clock" not in stubbed_kinds
    assert "random" not in stubbed_kinds
    assert "network" in stubbed_kinds


def test_retry_attempt_two_forces_clock_and_random_stubs() -> None:
    """Attempt 2 must widen the stub set to include forced clock/random seeding."""
    scope = _scope_with_escalatable_dependencies()
    spec = _hero_spec()
    attempts = retry_plan(scope)
    pair = HarnessEngineer().generate(
        scope, spec, str(FIXTURE_DIR / "base.py"), str(FIXTURE_DIR / "head.py"),
        retry_attempt=attempts[1],
    )
    stubbed_kinds = {stub.kind for stub in pair.stub_config}
    assert {"clock", "random"} <= stubbed_kinds


def test_generated_hero1_harnesses_execute_the_real_fixture_modules() -> None:
    """The registry preserves Hero 1's source bytes and real-module admissions."""
    pair = HarnessEngineer().generate(
        _hero_scope(),
        _hero_spec(),
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
    )

    base = subprocess.run(
        [sys.executable, "-c", pair.harness_a.source],
        capture_output=True,
        check=False,
        text=True,
    )
    head = subprocess.run(
        [sys.executable, "-c", pair.harness_b.source],
        capture_output=True,
        check=False,
        text=True,
    )

    assert base.returncode == head.returncode == 0
    assert json.loads(base.stdout)["observations"] == {"admitted": 5}
    assert json.loads(head.stdout)["observations"] == {"admitted": 6}
    assert get_entry_point_template("RateLimiter.admit") is not None
    assert hashlib.sha256(_normalize_harness_for_hashing(pair.harness_a.source).encode()).hexdigest() == (
        "84235b90d5514a630a3c3cfce787932fecc02e7b3f5f59850b2214a1f7634cd4"
    )
    assert hashlib.sha256(_normalize_harness_for_hashing(pair.harness_b.source).encode()).hexdigest() == (
        "84235b90d5514a630a3c3cfce787932fecc02e7b3f5f59850b2214a1f7634cd4"
    )
    reference = _reference_program(
        str(FIXTURE_DIR / "head.py"),
        _hero_spec().knobs,
        _hero_spec().observables,
        _hero_scope(),
        {"limit_per_sec": 5, "burst": 2, "rps": 3, "tenants": 2},
        0,
    )
    assert hashlib.sha256(_normalize_harness_for_hashing(reference).encode()).hexdigest() == (
        "d9bf0d0eeeb5cde6ca28c53aa1da210e9fc7ec65dc4094eb7efe686c2961bf78"
    )


def test_generated_harness_embeds_optional_schema_values_as_python_literals() -> None:
    """An LLM-proposed null unit stays valid Python and preserves its observable ID."""
    spec = _hero_spec().model_copy(
        update={
            "observables": [
                Observable(
                    id="admission_decision",
                    label="admission decision",
                    extractor=CounterExtractor(kind="counter", name="admitted"),
                    render="timeseries",
                    unit=None,
                    compareMode="overlay",
                )
            ]
        }
    )
    pair = HarnessEngineer().generate(
        _hero_scope(), spec, str(FIXTURE_DIR / "base.py"), str(FIXTURE_DIR / "head.py")
    )

    assert "null" not in pair.harness_a.source
    compile(pair.harness_a.source, "generated-harness", "exec")
    result = subprocess.run(
        [sys.executable, "-c", pair.harness_a.source], capture_output=True, check=False, text=True
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["observations"] == {"admission_decision": 5}
