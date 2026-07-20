"""End-to-end local coverage for Hero 3's categorical permission-matrix shape."""

import subprocess
import sys
from pathlib import Path

import pytest

from domain.adversary import Adversary, ObservationBundle
from domain.entry_point_registry import get_entry_point_template
from domain.fidelity_verifier import FidelityVerifier
from domain.harness_engineer import HarnessEngineer, UnsupportedTemplateProposal
from domain.schema import (
    ArgumentBinding,
    DomainPackId,
    DriverBinding,
    EnumDomain,
    Knob,
    Observable,
    PartialInteractionSpec,
    ReturnValueExtractor,
)
from domain.scout import scout
from infra.fakes.fake_sandbox import FakeSandboxRuntime
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero3"


def _hero3_scope():
    """Obtain the public module-level ``can`` entry point from the real diff."""
    base_path = FIXTURE_DIR / "base.py"
    head_path = FIXTURE_DIR / "head.py"
    base_source = base_path.read_text(encoding="utf-8")
    head_source = head_path.read_text(encoding="utf-8")
    parser = TreeSitterPythonParser()
    return scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
        str(base_path),
        str(head_path),
    )


def _hero3_spec() -> PartialInteractionSpec:
    """The permission-pack controls and categorical cell observable for Hero 3."""
    return PartialInteractionSpec(
        thesis="Group inheritance grants contractors cross-tenant audit-log access.",
        domainPack=DomainPackId.PERMISSION,
        knobs=[
            Knob(
                id="role",
                label="role",
                binding=ArgumentBinding(kind="argument", fn="can", argIndex=0),
                type="enum",
                domain=EnumDomain(values=["viewer", "editor", "admin", "contractor"]),
                default="viewer",
                scale="linear",
                unit=None,
                axisRole="x",
            ),
            Knob(
                id="resource",
                label="resource",
                binding=ArgumentBinding(kind="argument", fn="can", argIndex=2),
                type="enum",
                domain=EnumDomain(values=["doc", "billing", "audit-log", "settings"]),
                default="doc",
                scale="linear",
                unit=None,
                axisRole="y",
            ),
            Knob(
                id="same_tenant",
                label="same tenant",
                binding=ArgumentBinding(kind="argument", fn="can", argIndex=3),
                type="boolean",
                domain=EnumDomain(values=["false", "true"]),
                default=True,
                scale="linear",
                unit=None,
            ),
        ],
        observables=[
            Observable(
                id="allow",
                label="allow/deny",
                extractor=ReturnValueExtractor(kind="returnValue", path="$"),
                render="matrixCell",
                unit=None,
                compareMode="delta",
            )
        ],
    )


def _run_harness(source: str, point: dict[str, object]) -> dict:
    """Execute a generated permission harness locally through its public API."""
    process = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, check=False, text=True
    )
    assert process.returncode == 0, process.stderr
    namespace: dict[str, object] = {}
    exec(compile(source, "hero3-generated-harness", "exec"), namespace)
    return namespace["run"](point, 0)  # type: ignore[operator]


def test_permission_template_requires_axis_enums_boolean_and_matrix_cell() -> None:
    """The compatibility contract is materially different from both timeseries heroes."""
    scope = _hero3_scope()
    spec = _hero3_spec()
    assert not scope.unscopable
    assert scope.entry_point is not None
    assert scope.entry_point.fn == "can"
    assert all(entry.kind == "pure" for entry in scope.dependency_ledger.entries)

    template = get_entry_point_template("can")
    assert template is not None
    assert template.proposal_shape.incompatibility_reason("can", spec.knobs, spec.observables) is None

    pair = HarnessEngineer().generate(
        scope, spec, str(FIXTURE_DIR / "base.py"), str(FIXTURE_DIR / "head.py")
    )
    assert pair.workload_driver.parameters == ()
    assert pair.stub_config == ()
    assert pair.uncertainty_specs == ()

    marker_point = {"role": "contractor", "resource": "audit-log", "same_tenant": False}
    assert _run_harness(pair.harness_a.source, marker_point)["observations"] == {"allow": False}
    assert _run_harness(pair.harness_b.source, marker_point)["observations"] == {"allow": True}

    incompatible = spec.model_copy(
        update={
            "knobs": [
                spec.knobs[0].model_copy(
                    update={"binding": DriverBinding(kind="driver", param="role")}
                ),
                *spec.knobs[1:],
            ]
        }
    )
    with pytest.raises(
        UnsupportedTemplateProposal,
        match=r"permission matrix \(role/resource/same_tenant\)",
    ):
        HarnessEngineer().generate(
            scope, incompatible, "/tmp/base.py", "/tmp/head.py"
        )


def test_permission_matrix_harness_matches_real_code_and_categorical_search_finds_flip() -> None:
    """Pure categorical Hero 3 reaches high fidelity and a real deny-to-allow cell flip."""
    scope = _hero3_scope()
    spec = _hero3_spec()
    base_source = (FIXTURE_DIR / "base.py").read_text(encoding="utf-8")
    head_source = (FIXTURE_DIR / "head.py").read_text(encoding="utf-8")
    pair = HarnessEngineer().generate(
        scope, spec, str(FIXTURE_DIR / "base.py"), str(FIXTURE_DIR / "head.py")
    )
    runtime = FakeSandboxRuntime()
    sandbox_id = runtime.create_sandbox("base")
    try:
        verification = FidelityVerifier(runtime).verify(
            sandbox_id, pair, scope, spec, base_source, head_source
        )
    finally:
        runtime.kill_sandbox(sandbox_id)

    assert verification.report.agreement.rate == 1.0
    assert verification.report.agreement.tolerance.kind == "exact"
    assert verification.report.stability.perObservable["allow"].kind == "instability"
    assert verification.report.stability.perObservable["allow"].value == 0.0
    assert verification.report.band == "high"

    def run(point: dict[str, object]) -> ObservationBundle:
        cross_tenant_contract_audit = (
            point["role"] == "contractor"
            and point["resource"] == "audit-log"
            and point["same_tenant"] is False
        )
        return ObservationBundle(
            base={"allow": False}, head={"allow": cross_tenant_contract_audit}
        )

    adversary = Adversary(FakeSandboxRuntime(), run)
    result = adversary.search("unused", pair, spec, verification)
    assert not result.no_divergence
    assert result.surprise_marker is not None
    assert result.surprise_marker.position.root == {
        "role": "contractor",
        "resource": "audit-log",
        "same_tenant": False,
    }
    assert "base=False, head=True" in result.surprise_marker.caption


def test_permission_registry_numeric_fallback_remains_an_executable_real_code_view() -> None:
    """A second incompatible proposal can fall back without inventing a permission result."""
    scope = _hero3_scope()
    template = get_entry_point_template("can")
    assert template is not None and template.numeric_fallback is not None
    fallback = template.numeric_fallback()
    assert fallback.domainPack is DomainPackId.NUMERIC_FN

    pair = HarnessEngineer().generate(
        scope, fallback, str(FIXTURE_DIR / "base.py"), str(FIXTURE_DIR / "head.py")
    )
    point = {"role": "contractor", "resource": "audit-log", "same_tenant": 0}
    assert _run_harness(pair.harness_a.source, point)["observations"] == {"allow": 0}
    assert _run_harness(pair.harness_b.source, point)["observations"] == {"allow": 1}

    runtime = FakeSandboxRuntime()
    sandbox_id = runtime.create_sandbox("base")
    try:
        verification = FidelityVerifier(runtime).verify(
            sandbox_id,
            pair,
            scope,
            fallback,
            (FIXTURE_DIR / "base.py").read_text(encoding="utf-8"),
            (FIXTURE_DIR / "head.py").read_text(encoding="utf-8"),
        )
    finally:
        runtime.kill_sandbox(sandbox_id)

    assert verification.report.agreement.rate == 1.0
    assert verification.report.band == "high"
