"""Phase B generative harness coverage for unregistered entry points."""

from pathlib import Path

from domain.harness_engineer import HarnessEngineer
from domain.harness_ir import build_harness_ir, render_reference_program
from domain.schema import (
    ArgumentBinding,
    DependencyLedger,
    EntryPoint,
    Knob,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    ReturnValueExtractor,
    ScopedChangeSet,
)
from domain.stubs import stub_plan
from infra.fakes.fake_sandbox import FakeSandboxRuntime


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "wild_synth"


def _wild_scope() -> ScopedChangeSet:
    return ScopedChangeSet(
        entry_point=EntryPoint(
            file=str(FIXTURE_DIR / "head.py"),
            fn="scale",
            signature="scale(value: float, factor: float = 2.0) -> float",
        ),
        dependency_ledger=DependencyLedger(),
    )


def _wild_spec() -> PartialInteractionSpec:
    return PartialInteractionSpec(
        thesis="Head adds a constant offset after scaling.",
        domainPack="numeric-fn",
        knobs=[
            Knob(
                id="value",
                label="value",
                binding=ArgumentBinding(kind="argument", fn="scale", argIndex=0),
                type="scalar",
                domain=NumericDomain(min=0, max=10, step=1),
                default=3,
                scale="linear",
                unit=None,
                axisRole="x",
            ),
            Knob(
                id="factor",
                label="factor",
                binding=ArgumentBinding(kind="argument", fn="scale", argIndex=1),
                type="scalar",
                domain=NumericDomain(min=1, max=5, step=1),
                default=2,
                scale="linear",
                unit=None,
            ),
        ],
        observables=[
            Observable(
                id="result",
                label="scaled result",
                extractor=ReturnValueExtractor(kind="returnValue", path="$"),
                render="scalar",
                unit=None,
                compareMode="delta",
            )
        ],
    )


def test_stub_plan_empty_for_pure_ledger() -> None:
    plan = stub_plan(DependencyLedger())
    assert plan.stubs == ()
    assert not plan.is_unharnessable


def test_generative_ir_builds_for_unregistered_scale() -> None:
    ir, plan = build_harness_ir(_wild_scope(), _wild_spec())
    assert ir.entryPoint == "scale"
    assert ir.invocation.kind == "direct"
    assert plan.stubs == ()


def test_harness_engineer_generates_unknown_shape_without_registry() -> None:
    pair = HarnessEngineer().generate(
        _wild_scope(),
        _wild_spec(),
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
    )
    assert pair.generative_ir is not None
    assert pair.harness_a.source.replace(
        str(FIXTURE_DIR / "base.py"), "MODULE"
    ) == pair.harness_b.source.replace(str(FIXTURE_DIR / "head.py"), "MODULE")


def test_generative_harness_and_reference_agree_locally() -> None:
    """Direct reference and harness must match on the wild_synth fixture."""
    scope = _wild_scope()
    spec = _wild_spec()
    pair = HarnessEngineer().generate(
        scope,
        spec,
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
    )
    assert pair.generative_ir is not None
    point = {"value": 3.0, "factor": 2.0}
    runtime = FakeSandboxRuntime()
    sandbox_id = runtime.create_sandbox("base")
    try:
        for version, module in (
            ("base", FIXTURE_DIR / "base.py"),
            ("head", FIXTURE_DIR / "head.py"),
        ):
            harness_source = (
                pair.harness_a.source if version == "base" else pair.harness_b.source
            )
            harness_path = f"/tmp/lever-wild-{version}.harness.py"
            # Execute harness locally via FakeSandbox by writing through run_code embedding.
            harness_cmd = (
                f"namespace={{}}\nexec({harness_source!r}, namespace)\n"
                f"print(__import__('json').dumps(namespace['run']({point!r}, 0), sort_keys=True))"
            )
            harness_result = runtime.run_code(sandbox_id, harness_cmd)
            assert harness_result["exit_code"] == 0, harness_result
            harness_obs = __import__("json").loads(harness_result["stdout"])["observations"]

            reference = render_reference_program(
                pair.generative_ir,
                module_path=str(module),
                knobs=spec.knobs,
                observables=spec.observables,
                point=point,
                seed=0,
            )
            ref_cmd = reference + "\nprint(__import__('json').dumps({'observations': OBSERVATIONS}, sort_keys=True))\n"
            ref_result = runtime.run_code(sandbox_id, ref_cmd)
            assert ref_result["exit_code"] == 0, ref_result
            ref_obs = __import__("json").loads(ref_result["stdout"])["observations"]
            assert harness_obs == ref_obs
            expected = 3.0 * 2.0 if version == "base" else 3.0 * 2.0 + 1.0
            assert harness_obs["result"] == expected
    finally:
        runtime.kill_sandbox(sandbox_id)
