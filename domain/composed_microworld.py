"""Local, empirical 2×2 construction for two related changes in one subsystem.

The composition engine deliberately does not attempt a textual merge.  Its
caller supplies four checked-out module paths: base, each individual change,
and the checkout where both changes are applied.  That makes the AB corner a
real execution rather than an arithmetic guess.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from domain.harness_engineer import HarnessArtifact, HarnessEngineer, HarnessPair
from domain.ports import SandboxRuntime
from domain.schema import (
    BehavioralMergeConflict,
    ComposedCell,
    ComposedWidgetConfig,
    KnobPosition,
    PartialInteractionSpec,
    ScopedChangeSet,
)
from domain.symmetrist import (
    DependencyChangeSet,
    FourWaySymmetristResult,
    four_way_symmetrist_check,
)


VARIANTS = ("base", "A", "B", "AB")


@dataclass(frozen=True)
class CompositionCheckout:
    """The four actual source checkouts required for a trustworthy composition."""

    base_module_path: str
    a_module_path: str
    b_module_path: str
    ab_module_path: str
    base_source: str | None = None
    a_source: str | None = None
    b_source: str | None = None
    ab_source: str | None = None


@dataclass(frozen=True)
class ComposedHarnessSet:
    """Four generated harnesses and their complete four-way symmetry evidence."""

    artifacts: Mapping[str, HarnessArtifact]
    symmetrist: FourWaySymmetristResult


@dataclass(frozen=True)
class InteractionEffect:
    """The measured two-by-two interaction for one numeric observable."""

    observable_id: str
    base: float
    a: float
    b: float
    ab: float
    additive_expectation: float
    deviation: float
    tolerance: float
    detected: bool


@dataclass(frozen=True)
class ComposedEvaluation:
    """Raw harness observations and the interaction calculation at one position."""

    observations: Mapping[str, dict[str, Any]]
    effect: InteractionEffect


def build_composed_harnesses(
    scoped_change_set: ScopedChangeSet,
    partial_spec: PartialInteractionSpec,
    checkout: CompositionCheckout,
    *,
    diff_a_dependencies: DependencyChangeSet | None = None,
    diff_b_dependencies: DependencyChangeSet | None = None,
) -> ComposedHarnessSet:
    """Generate base/A and B/AB with the unchanged registered harness machinery."""
    engineer = HarnessEngineer()
    base_a = engineer.generate(
        scoped_change_set,
        partial_spec,
        checkout.base_module_path,
        checkout.a_module_path,
        checkout.base_source,
        checkout.a_source,
    )
    b_ab = engineer.generate(
        scoped_change_set,
        partial_spec,
        checkout.b_module_path,
        checkout.ab_module_path,
        checkout.b_source,
        checkout.ab_source,
    )
    artifacts = {
        "base": base_a.harness_a,
        "A": base_a.harness_b,
        "B": b_ab.harness_a,
        "AB": b_ab.harness_b,
    }
    configs = {
        "base": _stub_config(base_a),
        "A": _stub_config(base_a),
        "B": _stub_config(b_ab),
        "AB": _stub_config(b_ab),
    }
    symmetry = four_way_symmetrist_check(
        configs,
        diff_a=diff_a_dependencies,
        diff_b=diff_b_dependencies,
    )
    source_mismatches = _harness_source_mismatches(artifacts)
    if source_mismatches:
        symmetry = replace(
            symmetry,
            passed=False,
            harness_source_mismatches=source_mismatches,
        )
    return ComposedHarnessSet(artifacts=artifacts, symmetrist=symmetry)


def evaluate_composed_position(
    runtime: SandboxRuntime,
    sandbox_id: str,
    harnesses: ComposedHarnessSet,
    position: KnobPosition,
    observable_id: str,
    tolerance: float,
    *,
    seed: int = 0,
) -> ComposedEvaluation:
    """Execute every 2×2 corner, then measure its observed non-additivity."""
    if not harnesses.symmetrist.passed:
        details = [*harnesses.symmetrist.unjustified_keys, *harnesses.symmetrist.harness_source_mismatches]
        raise ValueError("Composed execution requires four-way Symmetrist pass: " + "; ".join(details))
    if tolerance < 0:
        raise ValueError("interaction tolerance must be non-negative")

    observations: dict[str, dict[str, Any]] = {}
    for variant in VARIANTS:
        artifact = harnesses.artifacts[variant]
        # Stage the target module into the sandbox. FakeSandbox can import host
        # fixture paths directly; E2B cannot — without this write the harness
        # dies with FileNotFoundError on MODULE_PATH.
        module_source = artifact.instrumented_module_source
        if module_source is None:
            module_source = Path(artifact.entry_module).read_text(encoding="utf-8")
        _stage_source(runtime, sandbox_id, artifact.entry_module, module_source)
        result = runtime.run_code(
            sandbox_id,
            _run_program(artifact.source, position.root, seed),
        )
        if result["exit_code"] != 0:
            raise RuntimeError(
                f"{variant} composed harness failed: {result['stderr'].strip() or result['stdout'].strip()}"
            )
        observations[variant] = _last_json_result(result["stdout"], variant)

    values = {
        variant: _numeric_observation(observations[variant], observable_id, variant)
        for variant in VARIANTS
    }
    return ComposedEvaluation(
        observations=observations,
        effect=detect_interaction_effect(values, observable_id, tolerance),
    )


def detect_interaction_effect(
    observations: Mapping[str, float], observable_id: str, tolerance: float
) -> InteractionEffect:
    """Implement §6.3's strict deviation-from-additivity condition exactly."""
    missing = sorted(set(VARIANTS) - set(observations))
    if missing:
        raise ValueError("interaction detection requires observations for " + ", ".join(missing))
    if tolerance < 0:
        raise ValueError("interaction tolerance must be non-negative")
    base, a, b, ab = (float(observations[variant]) for variant in VARIANTS)
    additive_expectation = a + b - base
    deviation = abs(ab - additive_expectation)
    return InteractionEffect(
        observable_id=observable_id,
        base=base,
        a=a,
        b=b,
        ab=ab,
        additive_expectation=additive_expectation,
        deviation=deviation,
        tolerance=tolerance,
        detected=deviation > tolerance,
    )


def compose_widget_config(
    change_a_id: str,
    change_b_id: str,
    partial_spec: PartialInteractionSpec,
    position: KnobPosition,
    effect: InteractionEffect,
) -> ComposedWidgetConfig:
    """Produce frontend data for an observed 2×2, including an honest conflict card."""
    observable = next(
        (item for item in partial_spec.observables if item.id == effect.observable_id), None
    )
    if observable is None:
        raise ValueError(f"observable {effect.observable_id!r} is absent from the partial spec")
    caption = None
    if effect.detected:
        caption = (
            "The individually executed changes do not combine additively at this input: "
            f"AB observed {effect.ab:g}, versus additive expectation "
            f"{effect.additive_expectation:g} (deviation {effect.deviation:g} > "
            f"tolerance {effect.tolerance:g})."
        )
    return ComposedWidgetConfig(
        changeAId=change_a_id,
        changeBId=change_b_id,
        observableId=observable.id,
        observableLabel=observable.label,
        unit=observable.unit,
        position=position,
        cells=[
            ComposedCell(variant="base", observation=effect.base),
            ComposedCell(variant="A", observation=effect.a),
            ComposedCell(variant="B", observation=effect.b),
            ComposedCell(variant="AB", observation=effect.ab),
        ],
        interaction=BehavioralMergeConflict(
            detected=effect.detected,
            additiveExpectation=effect.additive_expectation,
            observedAB=effect.ab,
            deviation=effect.deviation,
            tolerance=effect.tolerance,
            caption=caption,
        ),
    )


def _stub_config(pair: HarnessPair) -> dict[str, Any]:
    """Reconstruct the exact serializable stub configuration embedded in a pair."""
    return {stub.dependency: stub.as_dict() for stub in pair.stub_config}


def unified_diff(base_source: str, changed_source: str, *, fromfile: str, tofile: str) -> str:
    """Generate a zero-context unified patch for one independent source diff."""
    return "".join(
        difflib.unified_diff(
            base_source.splitlines(keepends=True),
            changed_source.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            n=0,
        )
    )


def apply_unified_patch(source: str, patch: str) -> str:
    """Apply unified-diff hunks by asserted source text, never by inference.

    Patch line numbers belong to the base checkout. Composition instead finds
    every old hunk exactly once in A's independently evolved checkout; a
    missing or ambiguous hunk is a merge failure, never a guessed AB source.
    """
    lines = source.splitlines(keepends=True)
    hunks = _parse_unified_hunks(patch)
    if not hunks:
        raise ValueError("unified patch has no hunks")
    for old_lines, new_lines in hunks:
        matches = [
            index
            for index in range(len(lines) - len(old_lines) + 1)
            if lines[index:index + len(old_lines)] == old_lines
        ]
        if len(matches) != 1:
            raise ValueError(
                "unified patch hunk must match the composition source exactly once; "
                f"found {len(matches)} matches"
            )
        index = matches[0]
        lines[index:index + len(old_lines)] = new_lines
    return "".join(lines)


def _parse_unified_hunks(patch: str) -> list[tuple[list[str], list[str]]]:
    """Read standard unified-diff body lines while preserving exact source bytes."""
    parsed: list[tuple[list[str], list[str]]] = []
    old_lines: list[str] | None = None
    new_lines: list[str] | None = None
    for line in patch.splitlines(keepends=True):
        if line.startswith(("--- ", "+++ ")):
            continue
        if line.startswith("@@ "):
            if old_lines is not None and new_lines is not None:
                parsed.append((old_lines, new_lines))
            old_lines, new_lines = [], []
            continue
        if old_lines is None or new_lines is None:
            continue
        if line.startswith("-"):
            old_lines.append(line[1:])
        elif line.startswith("+"):
            new_lines.append(line[1:])
        elif line.startswith(" "):
            old_lines.append(line[1:])
            new_lines.append(line[1:])
        elif line.startswith("\\ No newline at end of file"):
            continue
        else:
            raise ValueError("unsupported unified patch line")
    if old_lines is not None and new_lines is not None:
        parsed.append((old_lines, new_lines))
    return parsed


def _harness_source_mismatches(artifacts: Mapping[str, HarnessArtifact]) -> list[str]:
    """Verify that every rendered artifact has exactly the same template skeleton."""
    baseline = _normalise_module_path(artifacts["base"].source)
    return [
        variant
        for variant in ("A", "B", "AB")
        if _normalise_module_path(artifacts[variant].source) != baseline
    ]


def _normalise_module_path(source: str) -> str:
    return "".join(
        "MODULE_PATH = __MODULE_PATH__\n" if line.startswith("MODULE_PATH = ") else line
        for line in source.splitlines(keepends=True)
    )


def _stage_source(runtime: SandboxRuntime, sandbox_id: str, path: str, source: str) -> None:
    """Write one module into the sandbox so MODULE_PATH imports succeed remotely."""
    code = (
        "from pathlib import Path\n"
        f"target = Path({path!r})\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        f"target.write_text({source!r})"
    )
    result = runtime.run_code(sandbox_id, code)
    if result["exit_code"] != 0:
        raise RuntimeError(f"Could not stage {path}: {result['stderr']}")


def _run_program(source: str, position: dict[str, Any], seed: int) -> str:
    """Append an explicit run call; the final JSON line is the requested point."""
    return source + "\nprint(json.dumps(run(" + repr(position) + ", " + repr(seed) + "), sort_keys=True))\n"


def _last_json_result(stdout: str, variant: str) -> dict[str, Any]:
    """Read the appended point result even when a harness main guard printed defaults."""
    for line in reversed(stdout.splitlines()):
        if not line.strip():
            continue
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"{variant} composed harness emitted non-JSON output") from error
        if not isinstance(decoded, dict):
            raise RuntimeError(f"{variant} composed harness result was not a JSON object")
        return decoded
    raise RuntimeError(f"{variant} composed harness emitted no result")


def _numeric_observation(payload: Mapping[str, Any], observable_id: str, variant: str) -> float:
    """Composition's additive estimator is defined only for numeric observations."""
    try:
        value = payload["observations"][observable_id]
    except (KeyError, TypeError) as error:
        raise RuntimeError(f"{variant} composed harness omitted observable {observable_id!r}") from error
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"interaction additivity requires a numeric observable; {observable_id!r} was {type(value).__name__}"
        )
    return float(value)
