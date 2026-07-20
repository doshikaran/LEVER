"""Synthetic C-5 coverage for dual harness/reference branch instrumentation."""

import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

import domain.entry_point_registry as entry_point_registry
import domain.orchestrator as orchestrator
from domain.adversary import AdversaryResult, _normalized_hamming_distance, _objective_for
from domain.entry_point_registry import (
    EntryPointTemplate,
    HarnessBodyRequest,
    ProposalShape,
    ReferenceProgramRequest,
)
from domain.fidelity_verifier import FidelityVerification, FidelityVerifier, sobol_points
from domain.harness_engineer import (
    HarnessEngineer,
    UninstrumentableReferenceError,
    UnsupportedTemplateProposal,
)
from domain.schema import (
    Agreement,
    ArgumentBinding,
    Coverage,
    DependencyLedger,
    DomainPackId,
    EntryPoint,
    ExactTolerance,
    FidelityReport,
    InstabilityStabilityEstimate,
    Knob,
    KnobPosition,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    PathExtractor,
    ScopedChangeSet,
    Stability,
    SurpriseMarker,
    SymmetristSummary,
)
from infra.fakes.fake_llm import FakeLLMClient
from infra.fakes.fake_sandbox import FakeSandboxRuntime


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_tree"


def _scope() -> ScopedChangeSet:
    """Provide the synthetic module-level entry point without involving Delta selection."""
    return ScopedChangeSet(
        entry_point=EntryPoint(
            file=str(FIXTURE_DIR / "head.py"),
            fn="choose",
            signature="choose(value: int, enabled: bool) -> int",
        ),
        dependency_ledger=DependencyLedger(),
    )


def _decision_spec() -> PartialInteractionSpec:
    """Use the disabled pack directly to test its infrastructure before Hero 4 enables it."""
    return PartialInteractionSpec(
        thesis="The zero boundary follows a different branch.",
        domainPack=DomainPackId.DECISION_TREE,
        knobs=[
            Knob(
                id="value",
                label="value",
                binding=ArgumentBinding(kind="argument", fn="choose", argIndex=0),
                type="integer",
                domain=NumericDomain(min=-1, max=1, step=1),
                default=1,
                scale="linear",
                unit=None,
            ),
            Knob(
                id="enabled",
                label="enabled",
                binding=ArgumentBinding(kind="argument", fn="choose", argIndex=1),
                type="boolean",
                domain=entry_point_registry.EnumDomain(values=["false", "true"]),
                default=True,
                scale="linear",
                unit=None,
            ),
        ],
        observables=[
            Observable(
                id="path",
                label="branch path",
                extractor=PathExtractor(kind="path", instrumentation="branch"),
                render="pathTrace",
                unit=None,
                compareMode="overlay",
            )
        ],
    )


def _harness_body(request: HarnessBodyRequest) -> str:
    """Render a small ordinary harness; Harness Engineer adds C-5's generic adapter."""
    return f'''\
import importlib.util
import json
import os
import sys

MODULE_PATH = {request.module_path!r}
OBSERVABLES = {request.observables!r}
DEFAULT_CONFIG = {request.default_config!r}

def _load_module():
    spec = importlib.util.spec_from_file_location("synthetic_target", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module

def run(config=None, seed=0):
    config = dict(DEFAULT_CONFIG if config is None else config)
    module = _load_module()
    entry_code = module.choose.__code__
    target_module_path = os.path.abspath(MODULE_PATH)
    executed_lines = set()
    entry_lines = set()
    line_hits = {{}}
    def trace_lines(frame, event, _arg):
        if event == "line" and os.path.abspath(frame.f_code.co_filename) == target_module_path:
            executed_lines.add(frame.f_lineno)
            line_hits[frame.f_lineno] = line_hits.get(frame.f_lineno, 0) + 1
            if frame.f_code is entry_code:
                entry_lines.add(frame.f_lineno)
        return trace_lines
    previous_trace = sys.gettrace()
    sys.settrace(trace_lines)
    try:
        value = module.choose(int(config["value"]), bool(config["enabled"]))
    finally:
        sys.settrace(previous_trace)
    return {{
        "observations": {{observable["id"]: value for observable in OBSERVABLES}},
        "trace": {{
            "file": MODULE_PATH,
            "executed_lines": sorted(executed_lines),
            "entry_lines": sorted(entry_lines),
            "line_hits": {{str(line): line_hits[line] for line in sorted(line_hits)}},
        }},
    }}
'''


def _reference_program(request: ReferenceProgramRequest) -> str:
    """Use a separate direct import/program rather than the generated harness."""
    defaults = {knob.id: knob.default for knob in request.knobs}
    observable_ids = [observable.id for observable in request.observables]
    return f'''\
import importlib.util
import json

config = dict({defaults!r})
config.update(json.loads({json.dumps(json.dumps(request.point))}))
spec = importlib.util.spec_from_file_location("synthetic_reference", {request.module_path!r})
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)
value = module.choose(int(config["value"]), bool(config["enabled"]))
OBSERVATIONS = {{observable_id: value for observable_id in {observable_ids!r}}}
'''


@pytest.fixture
def registered_template(monkeypatch):
    """Install a synthetic executable shape without pretending it is a real Hero registry entry."""
    template = EntryPointTemplate(
        harness_body=_harness_body,
        reference_program=_reference_program,
        proposal_shape=ProposalShape(
            workload_description="a two-argument branch function",
            required_driver_params=(),
            allowed_binding_kinds=frozenset({"argument"}),
            required_observable_render="pathTrace",
        ),
    )
    monkeypatch.setattr(
        entry_point_registry,
        "ENTRY_POINT_REGISTRY",
        MappingProxyType({**entry_point_registry.ENTRY_POINT_REGISTRY, "choose": template}),
    )
    return template


def _pair(registered_template):
    """Generate the transformed pair from the two checked-out synthetic modules."""
    base_path = FIXTURE_DIR / "base.py"
    head_path = FIXTURE_DIR / "head.py"
    return HarnessEngineer().generate(
        _scope(),
        _decision_spec(),
        "/tmp/lever-c5/base.py",
        "/tmp/lever-c5/head.py",
        base_path.read_text(),
        head_path.read_text(),
    )


def test_dual_path_branch_vectors_match_reference_for_identical_path(registered_template) -> None:
    """Both C-5 paths emit the same ordered vector for an identical-path input."""
    pair = _pair(registered_template)
    spec = _decision_spec()
    base_source = (FIXTURE_DIR / "base.py").read_text()
    head_source = (FIXTURE_DIR / "head.py").read_text()
    assert pair.harness_a.instrumented_module_source is not None
    assert pair.harness_b.instrumented_module_source is not None

    runtime = FakeSandboxRuntime()
    sandbox_id = runtime.create_sandbox("base")
    try:
        verifier = FidelityVerifier(runtime)
        runner = verifier._sandbox_runner(sandbox_id, pair, _scope(), spec, base_source, head_source)
        points = sobol_points(spec.knobs)
        identical = next(point for point in points if point == {"value": 1, "enabled": True})

        for version in ("base", "head"):
            assert runner(f"harness_{version}", identical, 0)["path"] == runner(
                f"reference_{version}", identical, 0
            )["path"]

        trace = runner.trace_for(identical)
        assert trace is not None
        assert len(trace.base.branchDecisions) == len(trace.head.branchDecisions) == 2
        assert [item.outcome for item in trace.base.branchDecisions] == [False, True]
        assert [item.outcome for item in trace.head.branchDecisions] == [False, True]

        verification = verifier.verify(
            sandbox_id, pair, _scope(), spec, base_source, head_source
        )
    finally:
        runtime.kill_sandbox(sandbox_id)

    assert verification.report.agreement.tolerance.kind == "exact"
    assert verification.report.agreement.rate == 1.0
    assert not verification.mismatches


def test_branch_vector_hamming_distance_detects_a_real_fork(registered_template) -> None:
    """The complete vectors, not one responsible line, detect the changed predicate."""
    pair = _pair(registered_template)
    spec = _decision_spec()
    base_source = (FIXTURE_DIR / "base.py").read_text()
    head_source = (FIXTURE_DIR / "head.py").read_text()
    runtime = FakeSandboxRuntime()
    sandbox_id = runtime.create_sandbox("base")
    try:
        runner = FidelityVerifier(runtime)._sandbox_runner(
            sandbox_id, pair, _scope(), spec, base_source, head_source
        )
        fork = next(
            point
            for point in sobol_points(spec.knobs)
            if point == {"value": 0, "enabled": True}
        )
        base_path = runner("harness_base", fork, 0)["path"]
        head_path = runner("harness_head", fork, 0)["path"]
    finally:
        runtime.kill_sandbox(sandbox_id)

    assert _normalized_hamming_distance(base_path, head_path) > 0.0
    assert _objective_for(DomainPackId.DECISION_TREE) == "max_path_divergence"


def test_uninstrumentable_reference_signals_one_orchestrator_reselection(
    registered_template, monkeypatch
) -> None:
    """A non-source reference causes a bounded Delta re-selection rather than an exception."""
    spec = _decision_spec()
    with pytest.raises(UninstrumentableReferenceError, match="cannot be branch-instrumented"):
        HarnessEngineer().generate(
            _scope(), spec, "/tmp/compiled-reference.so", "/tmp/head.py"
        )

    feedback: list[str | None] = []
    harness_calls = 0

    class ScriptedAnalyst:
        def __init__(self, _llm):
            pass

        def analyze(self, *_args, compatibility_feedback=None):
            feedback.append(compatibility_feedback)
            return spec

    class FailingThenWorkingHarnessEngineer:
        def generate(self, *args, **kwargs):
            nonlocal harness_calls
            harness_calls += 1
            if harness_calls == 1:
                raise UninstrumentableReferenceError(
                    "reference path 'compiled-extension.so' cannot be branch-instrumented"
                )
            return HarnessEngineer().generate(*args, **kwargs)

    report = FidelityReport(
        verdict="verified",
        symmetrist=SymmetristSummary(passed=True, hashA="a", hashB="a", unjustifiedKeys=[]),
        agreement=Agreement(samples=128, matched=128, rate=1.0, tolerance=ExactTolerance(kind="exact")),
        stability=Stability(
            replicates=12,
            perObservable={"path": InstabilityStabilityEstimate(kind="instability", value=0.0)},
        ),
        coverage=Coverage(samples=128, strategy="sobol"),
        confidence=0.9,
        band="high",
        degradeReason=None,
    )

    class VerifiedFidelity:
        def __init__(self, _runtime):
            pass

        def verify(self, *_args, **_kwargs):
            return FidelityVerification(report, ())

    class DivergentAdversary:
        def __init__(self, _runtime):
            pass

        def search(self, *_args, **_kwargs):
            position = KnobPosition({"value": 0, "enabled": True})
            return AdversaryResult(
                initial_position=position,
                surprise_marker=SurpriseMarker(
                    position=position, divergence=1.0, caption="paths diverge"
                ),
                presets=(),
                search_trace=(),
                cache=(),
                no_divergence=False,
            )

    monkeypatch.setattr(orchestrator, "scout", lambda *_args: _scope())
    monkeypatch.setattr(orchestrator, "DeltaAnalyst", ScriptedAnalyst)
    monkeypatch.setattr(orchestrator, "HarnessEngineer", FailingThenWorkingHarnessEngineer)
    monkeypatch.setattr(orchestrator, "FidelityVerifier", VerifiedFidelity)
    monkeypatch.setattr(orchestrator, "Adversary", DivergentAdversary)
    monkeypatch.setattr(orchestrator, "synthesize", lambda *_args: None)

    result = orchestrator.run_pipeline(
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
        FakeSandboxRuntime(),
        FakeLLMClient([]),
        "fake-model",
        "low",
    )

    assert result.domainPack is DomainPackId.DECISION_TREE
    assert feedback == [None, "reference path 'compiled-extension.so' cannot be branch-instrumented"]
    assert harness_calls == 2
    assert result.provenance.registryCompatibilityKickbacks == 1


def test_reference_and_registry_failures_share_one_pipeline_reselection_budget(
    registered_template, monkeypatch
) -> None:
    """A second proposal failure uses fallback; it may not buy a third Delta call."""
    spec = _decision_spec()
    feedback: list[str | None] = []
    harness_calls = 0

    class ScriptedAnalyst:
        def __init__(self, _llm):
            pass

        def analyze(self, *_args, compatibility_feedback=None):
            feedback.append(compatibility_feedback)
            return spec

    class ReferenceThenRegistryFailure:
        def generate(self, *_args, **_kwargs):
            nonlocal harness_calls
            harness_calls += 1
            if harness_calls == 1:
                raise UninstrumentableReferenceError("reference cannot be branch-instrumented")
            if harness_calls == 2:
                raise UnsupportedTemplateProposal("registered template rejects the retry")
            return object()

    report = FidelityReport(
        verdict="verified",
        symmetrist=SymmetristSummary(passed=True, hashA="a", hashB="a", unjustifiedKeys=[]),
        agreement=Agreement(samples=128, matched=128, rate=1.0, tolerance=ExactTolerance(kind="exact")),
        stability=Stability(
            replicates=12,
            perObservable={"path": InstabilityStabilityEstimate(kind="instability", value=0.0)},
        ),
        coverage=Coverage(samples=128, strategy="sobol"),
        confidence=0.9,
        band="high",
        degradeReason=None,
    )

    class VerifiedFidelity:
        def __init__(self, _runtime):
            pass

        def verify(self, *_args, **_kwargs):
            return FidelityVerification(report, ())

    class DivergentAdversary:
        def __init__(self, _runtime):
            pass

        def search(self, *_args, **_kwargs):
            position = KnobPosition({"value": 0, "enabled": True})
            return AdversaryResult(
                initial_position=position,
                surprise_marker=SurpriseMarker(
                    position=position, divergence=1.0, caption="paths diverge"
                ),
                presets=(),
                search_trace=(),
                cache=(),
                no_divergence=False,
            )

    monkeypatch.setattr(orchestrator, "scout", lambda *_args: _scope())
    monkeypatch.setattr(orchestrator, "DeltaAnalyst", ScriptedAnalyst)
    monkeypatch.setattr(orchestrator, "HarnessEngineer", ReferenceThenRegistryFailure)
    monkeypatch.setattr(orchestrator, "FidelityVerifier", VerifiedFidelity)
    monkeypatch.setattr(orchestrator, "Adversary", DivergentAdversary)
    monkeypatch.setattr(orchestrator, "synthesize", lambda *_args: None)

    result = orchestrator.run_pipeline(
        str(FIXTURE_DIR / "base.py"),
        str(FIXTURE_DIR / "head.py"),
        FakeSandboxRuntime(),
        FakeLLMClient([]),
        "fake-model",
        "low",
    )

    assert result.provenance.registryCompatibilityKickbacks == 1
    assert feedback == [None, "reference cannot be branch-instrumented"]
    assert harness_calls == 3  # initial, one retry, then numeric-fn fallback
