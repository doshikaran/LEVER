"""Local proof that composed microworlds execute all four empirical corners."""

import difflib
from pathlib import Path

from domain.composed_microworld import (
    CompositionCheckout,
    apply_unified_patch,
    build_composed_harnesses,
    compose_widget_config,
    detect_interaction_effect,
    evaluate_composed_position,
    unified_diff,
)
from domain.schema import (
    AstNodeRef,
    ConfigBinding,
    CounterExtractor,
    DependencyLedger,
    DriverBinding,
    EntryPoint,
    Knob,
    KnobPosition,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    ScopedChangeSet,
)
from infra.fakes.fake_sandbox import FakeSandboxRuntime


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero1"


def _hero1_scope() -> ScopedChangeSet:
    return ScopedChangeSet(
        entry_point=EntryPoint(
            file=str(FIXTURE_DIR / "head.py"),
            fn="RateLimiter.admit",
            signature="RateLimiter.admit(self, tenant_id: str, now: float) -> bool",
        ),
        changed_nodes=[
            AstNodeRef(
                kind="function_definition",
                name="RateLimiter.admit",
                start_byte=0,
                end_byte=100,
            )
        ],
        dependency_ledger=DependencyLedger(),
    )


def _hero1_spec() -> PartialInteractionSpec:
    return PartialInteractionSpec(
        thesis="Compare the independent limit and tenant-window changes together.",
        domainPack="rate-limiter",
        knobs=[
            Knob(id="limit_per_sec", label="limit", binding=ConfigBinding(kind="config", path="limit_per_sec"), type="integer", domain=NumericDomain(min=1, max=100, step=1), default=5, scale="linear", unit="requests/s"),
            Knob(id="burst", label="burst", binding=ConfigBinding(kind="config", path="burst"), type="integer", domain=NumericDomain(min=0, max=50, step=1), default=0, scale="linear", unit="requests"),
            Knob(id="rps", label="rps", binding=DriverBinding(kind="driver", param="rps"), type="integer", domain=NumericDomain(min=1, max=100, step=1), default=6, scale="linear", unit="requests/s"),
            Knob(id="tenants", label="tenants", binding=DriverBinding(kind="driver", param="tenants"), type="integer", domain=NumericDomain(min=1, max=16, step=1), default=2, scale="linear", unit="tenants"),
        ],
        observables=[
            Observable(id="admitted", label="admitted", extractor=CounterExtractor(kind="counter", name="admitted"), render="timeseries", unit="requests", compareMode="overlay")
        ],
    )


def _hero1_composition_checkout() -> CompositionCheckout:
    return CompositionCheckout(
        base_module_path=str(FIXTURE_DIR / "base.py"),
        a_module_path=str(FIXTURE_DIR / "head.py"),
        b_module_path=str(FIXTURE_DIR / "limit_head.py"),
        ab_module_path=str(FIXTURE_DIR / "combined.py"),
    )


def test_hero1_combined_is_the_actual_b_patch_applied_to_a() -> None:
    """AB is byte-derived from A plus B's patch, rather than hand-approximated."""
    base = (FIXTURE_DIR / "base.py").read_text(encoding="utf-8")
    a = (FIXTURE_DIR / "head.py").read_text(encoding="utf-8")
    b = (FIXTURE_DIR / "limit_head.py").read_text(encoding="utf-8")
    combined = (FIXTURE_DIR / "combined.py").read_text(encoding="utf-8")

    patch = unified_diff(base, b, fromfile="base.py", tofile="limit_head.py")
    assert patch == (FIXTURE_DIR / "limit_multiplier.patch").read_text(encoding="utf-8")
    assert apply_unified_patch(a, patch) == combined
    assert list(
        difflib.unified_diff(a.splitlines(keepends=True), combined.splitlines(keepends=True), n=3)
    ) == [
        "--- \n",
        "+++ \n",
        "@@ -7,7 +7,7 @@\n",
        " \n",
        " class RateLimiter:\n",
        "     def __init__(self, limit_per_sec: int, burst: int = 0):\n",
        "-        self.limit = limit_per_sec\n",
        "+        self.limit = limit_per_sec * 2\n",
        "         self.burst = burst\n",
        "         self.windows = defaultdict(deque)\n",
        "         self.burst_used = 0  # BUG: shared, should be per-tenant\n",
    ]


def test_hero1_composition_generates_and_executes_all_four_harnesses_locally() -> None:
    """AB is a fourth real module execution, never a value inferred from A and B."""
    spec = _hero1_spec()
    harnesses = build_composed_harnesses(_hero1_scope(), spec, _hero1_composition_checkout())

    assert set(harnesses.artifacts) == {"base", "A", "B", "AB"}
    assert harnesses.symmetrist.passed
    assert len(harnesses.symmetrist.comparisons) == 6
    assert harnesses.symmetrist.harness_source_mismatches == []

    runtime = FakeSandboxRuntime()
    sandbox_id = runtime.create_sandbox("base")
    point = KnobPosition(
        {"limit_per_sec": 5, "burst": 0, "rps": 6, "tenants": 2}
    )
    evaluated = evaluate_composed_position(
        runtime, sandbox_id, harnesses, point, "admitted", tolerance=0.01
    )
    runtime.kill_sandbox(sandbox_id)

    assert len(runtime.run_calls) == 4
    assert {name: payload["observations"]["admitted"] for name, payload in evaluated.observations.items()} == {
        "base": 5,
        "A": 10,
        "B": 10,
        "AB": 12,
    }
    assert evaluated.effect.additive_expectation == 15
    assert evaluated.effect.deviation == 3
    assert evaluated.effect.detected

    widget = compose_widget_config("hero1-tenant-windows", "hero1-raised-limit", spec, point, evaluated.effect)
    assert [cell.variant for cell in widget.cells] == ["base", "A", "B", "AB"]
    assert [cell.observation for cell in widget.cells] == [5, 10, 10, 12]
    assert widget.interaction.detected
    assert widget.interaction.caption is not None
    assert "do not combine additively" in widget.interaction.caption


def test_additivity_formula_does_not_report_a_conflict_at_or_below_tolerance() -> None:
    """The detector uses the strict greater-than relation from §6.3."""
    effect = detect_interaction_effect(
        {"base": 10, "A": 12, "B": 13, "AB": 15.01}, "admitted", tolerance=0.01
    )

    assert effect.additive_expectation == 15
    assert effect.deviation < 0.01
    assert not effect.detected
