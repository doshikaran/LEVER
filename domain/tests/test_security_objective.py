"""Local executable coverage for §6.4's boundary-weighted unsafe-state search."""

from __future__ import annotations

from typing import Any

from domain.adversary import Adversary, ObservationBundle
from domain.fidelity_verifier import FidelityVerification
from domain.harness_engineer import HarnessEngineer
from domain.schema import (
    Agreement,
    CvStabilityEstimate,
    ExactTolerance,
    FidelityReport,
    RelativeTolerance,
    Stability,
    SymmetristSummary,
    UnsafeKnobTarget,
    UnsafeLiteralTarget,
    UnsafePredicate,
)
from infra.fakes.fake_sandbox import FakeSandboxRuntime

from test_harness_engineer import FIXTURE_DIR as HERO1_DIR
from test_harness_engineer import _hero_scope, _hero_spec
from test_hero3_registry import FIXTURE_DIR as HERO3_DIR
from test_hero3_registry import _hero3_scope, _hero3_spec


def _empty_verified_fidelity(observable_id: str, *, categorical: bool) -> FidelityVerification:
    """Give Adversary a verified prerequisite without leaking plausible Sobol points."""
    tolerance = ExactTolerance(kind="exact") if categorical else RelativeTolerance(
        kind="relative", epsilon=0.01
    )
    return FidelityVerification(
        report=FidelityReport(
            verdict="verified",
            symmetrist=SymmetristSummary(
                passed=True, hashA="same", hashB="same", unjustifiedKeys=[]
            ),
            agreement=Agreement(samples=128, matched=128, rate=1.0, tolerance=tolerance),
            stability=Stability(
                replicates=12,
                perObservable={observable_id: CvStabilityEstimate(kind="cv", value=0.0)},
            ),
            coverage={"samples": 128, "strategy": "sobol"},
            confidence=1.0,
            band="high",
            degradeReason=None,
        ),
        mismatches=(),
    )


def _generated_runner(pair: Any):
    """Execute both real generated harness sources locally for each cached point."""
    base_namespace: dict[str, Any] = {"__name__": "lever_security_base"}
    head_namespace: dict[str, Any] = {"__name__": "lever_security_head"}
    exec(compile(pair.harness_a.source, "security-base-harness", "exec"), base_namespace)
    exec(compile(pair.harness_b.source, "security-head-harness", "exec"), head_namespace)

    def run(point: dict[str, Any]) -> ObservationBundle:
        return ObservationBundle(
            base=base_namespace["run"](point, 0)["observations"],
            head=head_namespace["run"](point, 0)["observations"],
        )

    return run


def test_hero1_unsafe_search_uses_a_negative_boundary_that_plausible_sobol_cannot_reach() -> None:
    """``admitted > limit`` is unreachable in-domain but reached at the malformed limit."""
    full_spec = _hero_spec()
    safe_defaults = {"limit_per_sec": 10, "burst": 0, "rps": 1, "tenants": 1}
    narrow_spec = full_spec.model_copy(
        update={
            "knobs": [
                knob.model_copy(
                    update={
                        "default": safe_defaults[knob.id],
                        "domain": knob.domain.model_copy(
                            update={
                                "min": safe_defaults[knob.id],
                                "max": safe_defaults[knob.id],
                            }
                        ),
                    }
                )
                for knob in full_spec.knobs
            ]
        }
    )
    pair = HarnessEngineer().generate(
        _hero_scope(), narrow_spec, str(HERO1_DIR / "base.py"), str(HERO1_DIR / "head.py")
    )
    predicate = UnsafePredicate(
        observableId="admitted",
        operator="gt",
        target=UnsafeKnobTarget(kind="knob", id="limit_per_sec"),
    )
    search = Adversary(FakeSandboxRuntime(), _generated_runner(pair))
    verification = _empty_verified_fidelity("admitted", categorical=False)

    plausible = search.search(
        "local", pair, narrow_spec, verification,
        objective="reach_unsafe_state", unsafe_predicate=predicate, sampler_prior="plausible",
    )
    boundary = search.search(
        "local", pair, narrow_spec, verification,
        objective="reach_unsafe_state", unsafe_predicate=predicate,
    )

    assert plausible.no_divergence
    assert not boundary.no_divergence
    assert boundary.surprise_marker is not None
    assert boundary.surprise_marker.position.root["limit_per_sec"] == -1
    assert "Unsafe state reached" in boundary.surprise_marker.caption


def test_hero3_unsafe_search_discovers_inherited_contract_audit_access_at_enum_boundaries() -> None:
    """Malformed enum candidates find a head-only allow absent from the plausible domain."""
    full_spec = _hero3_spec()
    narrow_spec = full_spec.model_copy(
        update={
            "knobs": [
                knob.model_copy(
                    update={
                        "domain": knob.domain.model_copy(
                            update={
                                "values": ["viewer"]
                                if knob.id == "role"
                                else ["billing"]
                                if knob.id == "resource"
                                else knob.domain.values
                            }
                        )
                    }
                )
                for knob in full_spec.knobs
            ]
        }
    )
    pair = HarnessEngineer().generate(
        _hero3_scope(), narrow_spec, str(HERO3_DIR / "base.py"), str(HERO3_DIR / "head.py")
    )
    predicate = UnsafePredicate(
        observableId="allow",
        operator="eq",
        target=UnsafeLiteralTarget(kind="literal", value=True),
    )
    search = Adversary(FakeSandboxRuntime(), _generated_runner(pair))
    verification = _empty_verified_fidelity("allow", categorical=True)

    plausible = search.search(
        "local", pair, narrow_spec, verification,
        objective="reach_unsafe_state", unsafe_predicate=predicate, sampler_prior="plausible",
    )
    boundary = search.search(
        "local", pair, narrow_spec, verification,
        objective="reach_unsafe_state", unsafe_predicate=predicate,
    )

    assert plausible.no_divergence
    assert not boundary.no_divergence
    assert boundary.surprise_marker is not None
    position = boundary.surprise_marker.position.root
    assert position["role"] == "contractor"
    assert position["resource"] == "audit-log"
    assert position["same_tenant"] is False
    assert "head: allow=True" in boundary.surprise_marker.caption
