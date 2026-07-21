"""Part 5 orchestration that composes Lever's independent domain agents."""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

from domain.adversary import Adversary, AdversaryResult, TracePoint
from domain.delta_analyst import DeltaAnalyst, numeric_fn_fallback
from domain.entry_point_registry import get_entry_point_template
from domain.fidelity_verifier import FidelityVerification, FidelityVerifier
from domain.harness_engineer import (
    HarnessEngineer,
    NO_HARNESS_TEMPLATE_REASON,
    GenerativeHarnessError,
    GENERATIVE_HARNESS_FAILED_REASON,
    NoHarnessTemplateRegistered,
    UnsupportedTemplateProposal,
)
from domain.line_attribution import UninstrumentableReferenceError
from domain.ports import LLMClient, SandboxRuntime
from domain.intake import CheckoutHandle
from domain.schema import InteractionSpec, Provenance
from domain.scout import scout
from domain.synthesizer import synthesize
from domain.triager import triage
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser


MAX_LOOP_A_ATTEMPTS = 3
MAX_LOOP_B_KICKBACKS = 1
MAX_PROPOSAL_RESELECTION_KICKBACKS = 1
_SANDBOX_BASE_MODULE = "/tmp/lever-pipeline/base.py"
_SANDBOX_HEAD_MODULE = "/tmp/lever-pipeline/head.py"


@dataclass(frozen=True)
class RepoProvenance:
    """Optional hosting-provider facts when intake already resolved a PR."""

    repo_url: str
    base_sha: str
    head_sha: str


@dataclass(frozen=True)
class DegradeResult:
    """A typed terminal pipeline outcome with a user-facing explanation."""

    reason: str
    plain_explanation: str | None = None
    divergence_report: tuple[dict[str, Any], ...] = ()
    # Keep each validated Delta draft in order when a later pipeline stage
    # cannot execute it.  This is durable diagnostic evidence, not an inferred
    # explanation of the failure.
    proposedSpecs: tuple[dict[str, Any], ...] = ()
    registryCompatibilityKickbacks: int = 0
    kind: str = field(init=False, default="degraded")


@dataclass(frozen=True)
class GracefulDegradation(DegradeResult):
    """A harness, reference, or confidence failure routed to Part 5 step 47."""

    loop_a_attempts: int = 0
    kind: Literal["degraded"] = field(init=False, default="degraded")


@dataclass(frozen=True)
class UnscopableResult(DegradeResult):
    """A Scout terminal result with the plain-data entry-point blocker preserved."""

    kind: Literal["unscopable"] = field(init=False, default="unscopable")


@dataclass(frozen=True)
class InertResult(DegradeResult):
    """A successful-but-inert outcome after the single permitted Loop B kickback."""

    kind: Literal["inert"] = field(init=False, default="inert")


@dataclass(frozen=True)
class SkippedResult(DegradeResult):
    """A Triager skip awaiting an explicit user force-proceed action outside this port."""

    kind: Literal["skipped"] = field(init=False, default="skipped")


def run_pipeline_from_checkout(
    checkout: CheckoutHandle,
    sandbox: SandboxRuntime,
    llm: LLMClient,
    model: str,
    reasoning_effort: str,
    progress_callback: Callable[[str, str], None] | None = None,
    adversary_callback: Callable[[AdversaryResult], None] | None = None,
    search_trace_callback: Callable[[TracePoint], None] | None = None,
    speculative: bool = False,
) -> InteractionSpec | DegradeResult:
    """Run the existing single-pair pipeline against a Phase A dual checkout."""
    resolved = checkout.resolved
    _emit_progress(
        progress_callback,
        "intake",
        f"Checked out {resolved.owner}/{resolved.repo}#{resolved.number} — "
        f"{len(resolved.changed_files)} changed files.",
    )
    if checkout.primary_base_file is None or checkout.primary_head_file is None:
        return GracefulDegradation(
            checkout.selection_reason
            or "No shared Python module was available on both base and head.",
            plain_explanation=(
                f"{resolved.title} changed files, but Lever Phase A needs one shared "
                "Python module present on both sides of the PR before it can verify."
            ),
        )
    if checkout.selection_reason:
        _emit_progress(progress_callback, "primary_pair", checkout.selection_reason)
    return run_pipeline(
        str(checkout.primary_base_file),
        str(checkout.primary_head_file),
        sandbox,
        llm,
        model,
        reasoning_effort,
        progress_callback=progress_callback,
        adversary_callback=adversary_callback,
        search_trace_callback=search_trace_callback,
        speculative=speculative,
        repo_provenance=RepoProvenance(
            repo_url=resolved.repo_url,
            base_sha=resolved.base_sha,
            head_sha=resolved.head_sha,
        ),
        files_touched_count=max(1, len(resolved.changed_files)),
    )


def run_pipeline(
    base_file_path: str,
    head_file_path: str,
    sandbox: SandboxRuntime,
    llm: LLMClient,
    model: str,
    reasoning_effort: str,
    progress_callback: Callable[[str, str], None] | None = None,
    adversary_callback: Callable[[AdversaryResult], None] | None = None,
    search_trace_callback: Callable[[TracePoint], None] | None = None,
    speculative: bool = False,
    repo_provenance: RepoProvenance | None = None,
    files_touched_count: int = 1,
) -> InteractionSpec | DegradeResult:
    """Execute Part 5 and optionally publish real-time search evidence."""
    base_path = Path(base_file_path)
    head_path = Path(head_file_path)
    base_source = base_path.read_text()
    head_source = head_path.read_text()
    emitted_progress: set[str] = set()

    def emit_progress(stage: str, message: str) -> None:
        """Keep Part 1.3's progressive disclosure to one ordered line per stage."""
        if stage in emitted_progress:
            return
        emitted_progress.add(stage)
        _emit_progress(progress_callback, stage, message)

    triage_verdict = triage(base_source, head_source, [head_path.name])
    if not triage_verdict.proceed:
        return SkippedResult(triage_verdict.reason or "Triager skipped this change.")
    touched = max(1, files_touched_count)
    emit_progress(
        "files_touched",
        f"{touched} file{'s' if touched != 1 else ''} touched.",
    )

    parser = TreeSitterPythonParser()
    scoped_change_set = scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
        str(base_path),
        str(head_path),
    )
    if scoped_change_set.unscopable:
        return UnscopableResult(
            scoped_change_set.reason or "Scout could not select a plain-data entry point."
        )
    if scoped_change_set.entry_point is None:
        return UnscopableResult("Scout returned no entry point.")
    emit_progress(
        "behavior_identified",
        f"One behavior changed: {scoped_change_set.entry_point.fn}.",
    )

    sandbox_id = sandbox.create_sandbox("base")
    try:
        loop_b_kickbacks = 0
        # Registry incompatibility and unavailable decision-tree instrumentation
        # are both failures of the same Delta proposal.  Part 5 permits one
        # re-selection total, not one fresh prompt per failure subtype.
        registryCompatibilityKickbacks = 0
        compatibility_feedback: str | None = None
        proposed_specs: list[dict[str, Any]] = []
        while True:
            if compatibility_feedback is None:
                partial_spec = DeltaAnalyst(llm).analyze(
                    scoped_change_set, base_source, head_source
                )
            else:
                partial_spec = DeltaAnalyst(llm).analyze(
                    scoped_change_set,
                    base_source,
                    head_source,
                    compatibility_feedback=compatibility_feedback,
                )
                compatibility_feedback = None
            # Snapshot the validated JSON immediately.  A later kickback may
            # replace ``partial_spec``, but the Session Ledger must retain both
            # drafts that led to a terminal degradation.
            proposed_specs.append(partial_spec.model_dump(mode="json"))
            emit_progress(
                "old_vs_new",
                f"Old vs. new: {partial_spec.thesis}",
            )

            fidelity = None
            for loop_a_attempt in range(1, MAX_LOOP_A_ATTEMPTS + 1):
                try:
                    harness_pair = HarnessEngineer().generate(
                        scoped_change_set,
                        partial_spec,
                        _SANDBOX_BASE_MODULE,
                        _SANDBOX_HEAD_MODULE,
                        base_source,
                        head_source,
                    )
                except UninstrumentableReferenceError as error:
                    if registryCompatibilityKickbacks < MAX_PROPOSAL_RESELECTION_KICKBACKS:
                        registryCompatibilityKickbacks += 1
                        compatibility_feedback = str(error)
                        break
                    return GracefulDegradation(
                        "The reference path could not be branch-instrumented after "
                        "one Delta Analyst re-selection: " + str(error),
                        plain_explanation=_plain_explanation(
                            partial_spec.thesis,
                            "an instrumentable source-level reference implementation",
                        ),
                        loop_a_attempts=loop_a_attempt,
                        proposedSpecs=tuple(proposed_specs),
                        registryCompatibilityKickbacks=registryCompatibilityKickbacks,
                    )
                except GenerativeHarnessError as error:
                    if loop_a_attempt < MAX_LOOP_A_ATTEMPTS:
                        continue
                    return GracefulDegradation(
                        str(error),
                        plain_explanation=_plain_explanation(
                            partial_spec.thesis,
                            f"{scoped_change_set.entry_point.fn} with plain-data inputs",
                        ),
                        loop_a_attempts=loop_a_attempt,
                        proposedSpecs=tuple(proposed_specs),
                        registryCompatibilityKickbacks=registryCompatibilityKickbacks,
                    )
                except NoHarnessTemplateRegistered:
                    # Phase B: registry miss should already fall through to generative.
                    # Keep this branch for unexpected raise sites.
                    return GracefulDegradation(
                        NO_HARNESS_TEMPLATE_REASON,
                        plain_explanation=(
                            f"Lever has no isolated harness/reference implementation for "
                            f"{scoped_change_set.entry_point.fn} yet."
                        ),
                        loop_a_attempts=loop_a_attempt,
                        proposedSpecs=tuple(proposed_specs),
                        registryCompatibilityKickbacks=registryCompatibilityKickbacks,
                    )
                except UnsupportedTemplateProposal as error:
                    if registryCompatibilityKickbacks < MAX_PROPOSAL_RESELECTION_KICKBACKS:
                        registryCompatibilityKickbacks += 1
                        compatibility_feedback = str(error)
                        # Registry feedback is a one-shot re-selection, like the
                        # Adversary kickback: it changes the proposed spec, never
                        # the verified source or registered template.
                        break
                    template = get_entry_point_template(scoped_change_set.entry_point.fn)
                    fallback_spec = (
                        template.numeric_fallback()
                        if template is not None and template.numeric_fallback is not None
                        else numeric_fn_fallback(scoped_change_set)
                    )
                    try:
                        harness_pair = HarnessEngineer().generate(
                            scoped_change_set,
                            fallback_spec,
                            _SANDBOX_BASE_MODULE,
                            _SANDBOX_HEAD_MODULE,
                            base_source,
                            head_source,
                        )
                    except (NoHarnessTemplateRegistered, UnsupportedTemplateProposal, GenerativeHarnessError, ValueError) as fallback_error:
                        return GracefulDegradation(
                            "Registered-template compatibility failed after one "
                            "Delta Analyst kickback, and the numeric-fn fallback "
                            f"is not executable for this entry point: {fallback_error}",
                            plain_explanation=_plain_explanation(
                                partial_spec.thesis,
                                f"the registered {scoped_change_set.entry_point.fn} workload shape",
                            ),
                            loop_a_attempts=loop_a_attempt,
                            proposedSpecs=tuple(proposed_specs),
                            registryCompatibilityKickbacks=registryCompatibilityKickbacks,
                        )
                    partial_spec = fallback_spec
                except (NotImplementedError, ValueError) as error:
                    if loop_a_attempt < MAX_LOOP_A_ATTEMPTS:
                        continue
                    return GracefulDegradation(
                        "Harness Engineer could not produce an executable pair after "
                        f"{MAX_LOOP_A_ATTEMPTS} attempts: {error}",
                        plain_explanation=_plain_explanation(
                            partial_spec.thesis,
                            "the dependency boundary with a real service or a focused integration test",
                        ),
                        loop_a_attempts=loop_a_attempt,
                        proposedSpecs=tuple(proposed_specs),
                        registryCompatibilityKickbacks=registryCompatibilityKickbacks,
                    )
                emit_progress(
                    "building",
                    "Building you something to pull on…",
                )

                fidelity = FidelityVerifier(sandbox).verify(
                    sandbox_id,
                    harness_pair,
                    scoped_change_set,
                    partial_spec,
                    base_source,
                    head_source,
                )
                report = fidelity.report
                if not report.symmetrist.passed or report.agreement.rate < 0.85:
                    # LOOP A: the next iteration re-enters precisely at Harness Engineer.
                    continue
                if report.band == "low" or report.verdict != "verified":
                    return GracefulDegradation(
                        report.degradeReason
                        or "Fidelity confidence is too low to render a microworld.",
                        plain_explanation=_plain_explanation(
                            partial_spec.thesis,
                            f"{scoped_change_set.entry_point.fn} with production-like dependency values",
                        ),
                        divergence_report=_divergence_report(fidelity),
                        loop_a_attempts=loop_a_attempt,
                        proposedSpecs=tuple(proposed_specs),
                        registryCompatibilityKickbacks=registryCompatibilityKickbacks,
                    )
                break
            else:
                return GracefulDegradation(
                    "Fidelity agreement stayed below 0.85 after all three Harness Engineer attempts.",
                    plain_explanation=_plain_explanation(
                        partial_spec.thesis,
                        f"{scoped_change_set.entry_point.fn} at the sampled inputs below",
                    ),
                    divergence_report=_divergence_report(fidelity),
                    loop_a_attempts=MAX_LOOP_A_ATTEMPTS,
                    proposedSpecs=tuple(proposed_specs),
                    registryCompatibilityKickbacks=registryCompatibilityKickbacks,
                )

            if compatibility_feedback is not None:
                continue

            assert fidelity is not None
            adversary_result = Adversary(sandbox).search(
                sandbox_id,
                harness_pair,
                partial_spec,
                fidelity,
                base_source,
                head_source,
                trace_callback=search_trace_callback,
            )
            if adversary_callback is not None:
                adversary_callback(adversary_result)
            if adversary_result.no_divergence:
                if loop_b_kickbacks >= MAX_LOOP_B_KICKBACKS:
                    return InertResult(
                        adversary_result.reason
                        or "This change is behaviorally inert under the inputs I could model.",
                        plain_explanation=_plain_explanation(
                            partial_spec.thesis,
                            f"{scoped_change_set.entry_point.fn} at the boundary condition you care about",
                        ),
                        # An inert result is still downstream of Delta Analyst.
                        # Retaining both Loop-B drafts makes the Session Ledger
                        # explain which modeled inputs were actually varied.
                        proposedSpecs=tuple(proposed_specs),
                        registryCompatibilityKickbacks=registryCompatibilityKickbacks,
                    )
                # LOOP B: re-enter Delta Analyst, then re-run downstream work with its new spec.
                loop_b_kickbacks += 1
                continue

            if adversary_result.initial_position is None:
                return InertResult(
                    "Adversary found no usable initial position.",
                    plain_explanation=_plain_explanation(
                        partial_spec.thesis,
                        f"{scoped_change_set.entry_point.fn} with a representative production input",
                    ),
                    proposedSpecs=tuple(proposed_specs),
                    registryCompatibilityKickbacks=registryCompatibilityKickbacks,
                )
            interaction_spec = InteractionSpec(
                specVersion="2.0",
                changeId=_change_id(base_source, head_source, scoped_change_set.entry_point.fn),
                thesis=partial_spec.thesis,
                domainPack=partial_spec.domainPack,
                knobs=partial_spec.knobs,
                observables=partial_spec.observables,
                initialPosition=adversary_result.initial_position,
                surpriseMarker=adversary_result.surprise_marker,
                presets=list(adversary_result.presets),
                fidelity=fidelity.report,
                provenance=_provenance(
                    base_path,
                    head_path,
                    base_source,
                    head_source,
                    sandbox_id,
                    model,
                    reasoning_effort,
                    registryCompatibilityKickbacks,
                    speculative,
                    repo_provenance,
                ),
            )
            # Step 40: Synthesizer validates/mechanically materializes the complete spec.
            # Decision trees are reconstructed only from Adversary's existing
            # empirical cache; Synthesizer may not invent a static CFG.
            synthesize(interaction_spec, adversary_result.cache)
            return interaction_spec
    finally:
        sandbox.kill_sandbox(sandbox_id)


def _emit_progress(
    callback: Callable[[str, str], None] | None,
    stage: str,
    message: str,
) -> None:
    """Notify a presentation adapter without making its failure affect analysis."""
    if callback is None:
        return
    try:
        callback(stage, message)
    except Exception:
        # Progress delivery must never fabricate or abort the verified pipeline.
        return


def _plain_explanation(thesis: str, manual_input: str) -> str:
    """Turn the scoped Delta Analyst thesis into the honest no-toy fallback copy."""
    return (
        f"{thesis} Rather than render a model that could mislead you, manually test "
        f"{manual_input}."
    )


def _divergence_report(verification: FidelityVerification | None) -> tuple[dict[str, Any], ...]:
    """Expose the concrete sampled harness/reference disagreements for the fallback UI."""
    if verification is None:
        return ()
    return tuple(
        {
            "position": mismatch.point,
            "version": mismatch.version,
            "observable": mismatch.observable_id,
            "harness": mismatch.harness_value,
            "reference": mismatch.reference_value,
        }
        for mismatch in verification.mismatches
    )


def _change_id(base_source: str, head_source: str, scope_id: str) -> str:
    """Match Part 5's stable change identifier construction without an external repo port."""
    material = (
        hashlib.sha256(base_source.encode("utf-8")).hexdigest()
        + hashlib.sha256(head_source.encode("utf-8")).hexdigest()
        + scope_id
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _provenance(
    base_path: Path,
    head_path: Path,
    base_source: str,
    head_source: str,
    sandbox_id: str,
    model: str,
    reasoning_effort: str,
    registryCompatibilityKickbacks: int,
    speculative: bool = False,
    repo_provenance: RepoProvenance | None = None,
) -> Provenance:
    """Populate Orchestrator-owned provenance facts before the completed spec returns."""
    if repo_provenance is not None:
        base_sha = repo_provenance.base_sha
        head_sha = repo_provenance.head_sha
        repo_url = repo_provenance.repo_url
    else:
        base_sha = hashlib.sha256(base_source.encode("utf-8")).hexdigest()
        head_sha = hashlib.sha256(head_source.encode("utf-8")).hexdigest()
        repo_url = f"file://{head_path.parent}"
    return Provenance(
        baseSha=base_sha,
        headSha=head_sha,
        repoUrl=repo_url,
        generatedAt=datetime.now(UTC).isoformat(),
        modelIds={"delta-analyst": f"{model}; reasoning={reasoning_effort}"},
        harnessSourceUri=f"sandbox://{sandbox_id}/lever-pipeline",
        speculative=speculative,
        registryCompatibilityKickbacks=registryCompatibilityKickbacks,
    )


__all__ = [
    "DegradeResult",
    "GracefulDegradation",
    "InertResult",
    "RepoProvenance",
    "SkippedResult",
    "UnscopableResult",
    "run_pipeline",
    "run_pipeline_from_checkout",
]
