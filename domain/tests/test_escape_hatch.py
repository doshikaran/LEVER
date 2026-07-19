"""Empirical execution-trace coverage for the §1.8 source escape hatch."""

from domain.adversary import Adversary, CacheEntry
from domain.harness_engineer import HarnessEngineer
from domain.schema import KnobPosition
from infra.fakes.fake_sandbox import FakeSandboxRuntime

from test_harness_engineer import FIXTURE_DIR, _hero_scope, _hero_spec

def _hero_bundle(point: dict[str, int]):
    """Run the complete generated-driver trace path at one real Hero 1 position."""
    base_source = (FIXTURE_DIR / "base.py").read_text()
    head_source = (FIXTURE_DIR / "head.py").read_text()
    pair = HarnessEngineer().generate(
        _hero_scope(),
        _hero_spec(),
        "/tmp/lever-escape-hatch/base.py",
        "/tmp/lever-escape-hatch/head.py",
    )
    runtime = FakeSandboxRuntime()
    sandbox_id = runtime.create_sandbox("base")
    try:
        return Adversary(runtime)._sandbox_runner(
            sandbox_id,
            pair,
            base_source,
            head_source,
        )(point)
    finally:
        runtime.kill_sandbox(sandbox_id)


def test_hero1_surprise_position_is_attributed_to_the_executed_tenant_admission_branch() -> None:
    """Branch-body hit counts make the limit check win over the unconditional lookup."""
    point = {"rps": 81, "tenants": 20, "limit_per_sec": 50, "burst": 10}
    bundle = _hero_bundle(point)

    attribution = bundle.trace
    assert bundle.base == {"admitted": 50}
    assert bundle.head == {"admitted": 1010}
    assert attribution is not None
    assert attribution.base.entryLines == [11, 14, 15, 16, 17]
    assert attribution.head.entryLines[:2] == [16, 17]
    assert attribution.responsibleLine is not None
    assert attribution.responsibleLine.version == "head"
    assert attribution.responsibleLine.file == "/tmp/lever-escape-hatch/head.py"
    assert attribution.responsibleLine.line == 19
    assert attribution.responsibleLine.code == "if len(w) < self.limit:"

    # Adversary's cache keeps the entire evidence bundle with its exact position.
    cached = CacheEntry(
        position=KnobPosition(point),
        observations=bundle,
    )
    assert cached.position.root == point
    assert cached.observations.trace == attribution


def test_burst_dominant_position_is_attributed_to_the_shared_burst_branch() -> None:
    """Two tenants expose 52 shared burst admissions versus 48 isolation admissions."""
    point = {"rps": 100, "tenants": 2, "limit_per_sec": 48, "burst": 52}
    bundle = _hero_bundle(point)

    assert bundle.base == {"admitted": 48}
    assert bundle.head == {"admitted": 148}
    assert bundle.trace is not None
    assert bundle.trace.responsibleLine is not None
    assert bundle.trace.responsibleLine.version == "head"
    assert bundle.trace.responsibleLine.line == 22
    assert bundle.trace.responsibleLine.code == "if self.burst_used < self.burst:"
