"""Part 5 orchestration that composes Lever's independent domain agents."""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

from domain.adversary import Adversary, AdversaryResult
from domain.delta_analyst import DeltaAnalyst
from domain.fidelity_verifier import FidelityVerification, FidelityVerifier
from domain.harness_engineer import (
    HarnessEngineer,
    NO_HARNESS_TEMPLATE_REASON,
    NoHarnessTemplateRegistered,
)
from domain.ports import LLMClient, SandboxRuntime
from domain.schema import InteractionSpec, Provenance
from domain.scout import scout
from domain.synthesizer import synthesize
from domain.triager import triage
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser


MAX_LOOP_A_ATTEMPTS = 3
MAX_LOOP_B_KICKBACKS = 1
_SANDBOX_BASE_MODULE = "/tmp/lever-pipeline/base.py"
_SANDBOX_HEAD_MODULE = "/tmp/lever-pipeline/head.py"


@dataclass(frozen=True)
class DegradeResult:
    """A typed terminal pipeline outcome with a user-facing explanation."""

    reason: str
    plain_explanation: str | None = None
    divergence_report: tuple[dict[str, Any], ...] = ()
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


def run_pipeline(
    base_file_path: str,
    head_file_path: str,
    sandbox: SandboxRuntime,
    llm: LLMClient,
    model: str,
    reasoning_effort: str,
    progress_callback: Callable[[str, str], None] | None = None,
    adversary_callback: Callable[[AdversaryResult], None] | None = None,
) -> InteractionSpec | DegradeResult:
    """Execute Part 5 and optionally report completed stages and search artifacts."""
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
    emit_progress(
        "files_touched",
        "1 file touched.",
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
        while True:
            partial_spec = DeltaAnalyst(llm).analyze(
                scoped_change_set, base_source, head_source
            )
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
                    )
                except NoHarnessTemplateRegistered:
                    return GracefulDegradation(
                        NO_HARNESS_TEMPLATE_REASON,
                        plain_explanation=(
                            f"Lever has no isolated harness/reference implementation for "
                            f"{scoped_change_set.entry_point.fn} yet."
                        ),
                        loop_a_attempts=loop_a_attempt,
                    )
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
                )

            assert fidelity is not None
            adversary_result = Adversary(sandbox).search(
                sandbox_id,
                harness_pair,
                partial_spec,
                fidelity,
                base_source,
                head_source,
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
                ),
            )
            # Step 40: Synthesizer validates/mechanically materializes the complete spec.
            synthesize(interaction_spec)
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
) -> Provenance:
    """Populate Orchestrator-owned provenance facts before the completed spec returns."""
    return Provenance(
        baseSha=hashlib.sha256(base_source.encode("utf-8")).hexdigest(),
        headSha=hashlib.sha256(head_source.encode("utf-8")).hexdigest(),
        repoUrl=f"file://{head_path.parent}",
        generatedAt=datetime.now(UTC).isoformat(),
        modelIds={"delta-analyst": f"{model}; reasoning={reasoning_effort}"},
        harnessSourceUri=f"sandbox://{sandbox_id}/lever-pipeline",
    )


__all__ = [
    "DegradeResult",
    "GracefulDegradation",
    "InertResult",
    "SkippedResult",
    "UnscopableResult",
    "run_pipeline",
]
