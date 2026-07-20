"""Local executable coverage for Hero 4's decision-tree workload shape."""

from pathlib import Path

from domain.adversary import Adversary, _objective_for
from domain.fidelity_verifier import FidelityVerifier
from domain.harness_engineer import HarnessEngineer
from domain.orchestrator import run_pipeline
from domain.schema import (
    ConfigBinding,
    DomainPackId,
    EnumDomain,
    Knob,
    InteractionSpec,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    PathExtractor,
    Provenance,
)
from domain.scout import scout
from domain.synthesizer import synthesize
from infra.fakes.fake_sandbox import FakeSandboxRuntime
from infra.fakes.fake_llm import FakeLLMClient
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero4"


def _sources() -> tuple[str, str]:
    """Read the actual two executable Hero 4 policy files."""
    return (
        (FIXTURE_DIR / "base.py").read_text(encoding="utf-8"),
        (FIXTURE_DIR / "head.py").read_text(encoding="utf-8"),
    )


def _scope():
    """Run Scout over the real Hero 4 source, rather than hand-writing an entry point."""
    base, head = _sources()
    parser = TreeSitterPythonParser()
    return scout(
        base,
        head,
        parser.parse(base, "python"),
        parser.parse(head, "python"),
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
    )


def _spec() -> PartialInteractionSpec:
    """The registered mixed config-binding shape Delta must eventually propose."""
    return PartialInteractionSpec(
        thesis="The rollout gate changes which pricing predicates execute.",
        domainPack=DomainPackId.DECISION_TREE,
        knobs=[
            Knob(
                id="cohort",
                label="cohort",
                binding=ConfigBinding(kind="config", path="user.cohort"),
                type="enum",
                domain=EnumDomain(values=["control", "beta", "internal"]),
                default="beta",
                scale="linear",
                unit=None,
            ),
            Knob(
                id="flagState",
                label="flag state",
                binding=ConfigBinding(kind="config", path="user.flag_state"),
                type="enum",
                domain=EnumDomain(values=["off", "canary", "on"]),
                default="canary",
                scale="linear",
                unit=None,
            ),
            Knob(
                id="cartValue",
                label="cart value",
                binding=ConfigBinding(kind="config", path="cart.cart_value"),
                type="scalar",
                domain=NumericDomain(min=0, max=500, step=1),
                default=200,
                scale="linear",
                unit="USD",
            ),
        ],
        observables=[
            Observable(
                id="path",
                label="executed pricing path",
                extractor=PathExtractor(kind="path", instrumentation="branch"),
                render="pathTrace",
                unit=None,
                compareMode="overlay",
            )
        ],
    )


def test_hero4_scout_selects_plain_dataclass_entry_point_with_pure_ledger() -> None:
    """The data fields are visible enough for Scout without a Hero-specific heuristic."""
    scoped = _scope()

    assert scoped.entry_point is not None
    assert scoped.entry_point.fn == "should_apply_discount"
    assert scoped.entry_point.signature == "should_apply_discount(user: User, cart: Cart, now) -> Decimal"
    assert not scoped.unscopable
    assert all(entry.kind == "pure" for entry in scoped.dependency_ledger.entries)


def test_hero4_registered_template_runs_dual_path_fidelity_and_path_objective() -> None:
    """C-5's transformed harness and reference both exactly reproduce their real paths."""
    scoped = _scope()
    base, head = _sources()
    pair = HarnessEngineer().generate(
        scoped,
        _spec(),
        "/tmp/lever-hero4/base.py",
        "/tmp/lever-hero4/head.py",
        base,
        head,
    )
    assert pair.harness_a.instrumented_module_source is not None
    assert pair.harness_b.instrumented_module_source is not None
    assert pair.stub_config == ()
    assert _objective_for(DomainPackId.DECISION_TREE) == "max_path_divergence"

    runtime = FakeSandboxRuntime()
    sandbox_id = runtime.create_sandbox("base")
    try:
        verification = FidelityVerifier(runtime).verify(
            sandbox_id, pair, scoped, _spec(), base, head
        )
        adversary = Adversary(runtime).search(
            sandbox_id, pair, _spec(), verification, base, head
        )
    finally:
        runtime.kill_sandbox(sandbox_id)

    assert verification.report.agreement.tolerance.kind == "exact"
    assert verification.report.agreement.rate == 1.0
    assert verification.report.stability.perObservable["path"].kind == "instability"
    assert verification.report.band == "high"
    assert not adversary.no_divergence
    assert adversary.surprise_marker is not None
    assert adversary.surprise_marker.divergence > 0

    widget = synthesize(
        InteractionSpec(
            specVersion="2.0",
            changeId="hero4-local",
            thesis=_spec().thesis,
            domainPack=DomainPackId.DECISION_TREE,
            knobs=_spec().knobs,
            observables=_spec().observables,
            initialPosition=adversary.initial_position,
            surpriseMarker=adversary.surprise_marker,
            presets=list(adversary.presets),
            fidelity=verification.report,
            provenance=Provenance(
                baseSha="base",
                headSha="head",
                repoUrl="local://hero4",
                generatedAt="1970-01-01T00:00:00Z",
                modelIds={"delta-analyst": "local"},
                harnessSourceUri="sandbox://hero4",
            ),
        ),
        adversary.cache,
    )
    assert widget.domainPack == "decision-tree"
    assert widget.charts == []
    assert widget.unionTree is not None
    assert widget.unionTree.nodes
    assert widget.unionTree.forkTag is not None


def test_hero4_exact_config_binding_shape_completes_the_local_fake_pipeline() -> None:
    """The visible local dataclass fields map to config construction, not fake positional args."""
    proposal = _spec().model_dump(mode="json")
    result = run_pipeline(
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
        FakeSandboxRuntime(),
        FakeLLMClient([proposal]),
        "fake-model",
        "low",
    )

    assert isinstance(result, InteractionSpec)
    assert result.domainPack is DomainPackId.DECISION_TREE
    assert result.fidelity.band == "high"
    assert result.provenance.registryCompatibilityKickbacks == 0
    assert [knob.binding.model_dump(mode="json") for knob in result.knobs] == [
        {"kind": "config", "path": "user.cohort"},
        {"kind": "config", "path": "user.flag_state"},
        {"kind": "config", "path": "cart.cart_value"},
    ]
