"""Deterministic coverage for Harness Engineer's symmetry and retry behavior."""

from pathlib import Path
import json
import subprocess
import sys

from domain.harness_engineer import (
    HarnessEngineer,
    VerifierFeedback,
    retry_plan,
    run_retry_loop,
)
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


def test_generated_hero1_harnesses_execute_the_real_fixture_modules() -> None:
    """One template imports each real version and reports their distinct admissions."""
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
