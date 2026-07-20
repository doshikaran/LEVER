"""Symmetry-first fidelity verification against independent real-code execution."""

import ast
import hashlib
import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from scipy.stats import qmc

from domain.entry_point_registry import ReferenceProgramRequest, get_entry_point_template
from domain.harness_engineer import HarnessPair
from domain.line_attribution import trace_attribution
from domain.ports import SandboxRuntime
from domain.schema import (
    Agreement,
    Coverage,
    CvStabilityEstimate,
    FidelityReport,
    ExactTolerance,
    InstabilityStabilityEstimate,
    Knob,
    Observable,
    PartialInteractionSpec,
    RelativeTolerance,
    ScopedChangeSet,
    Stability,
    SymmetristSummary,
    TraceAttribution,
)
from domain.symmetrist import SymmetristResult, symmetrist_check


SOBOL_M = 7
SOBOL_POINT_COUNT = 2**SOBOL_M
ASSAYER_REPLICATES = 12
CV_MAX = 0.25
_NUMERIC_RENDERS = frozenset({"timeseries", "scalar", "histogram"})
_CATEGORICAL_RENDERS = frozenset({"matrixCell", "nodeState", "pathTrace"})

EvaluationRunner = Callable[[str, dict[str, Any], int | str], dict[str, Any]]


@dataclass(frozen=True)
class DifferentialMismatch:
    """One observable where a generated harness diverged from its real code path."""

    point: dict[str, Any]
    version: str
    observable_id: str
    harness_value: Any
    reference_value: Any


@dataclass(frozen=True)
class FidelityObservation:
    """One A/B harness observation already measured during differential testing."""

    point: dict[str, Any]
    base: dict[str, Any]
    head: dict[str, Any]
    trace: TraceAttribution | None = None


@dataclass(frozen=True)
class FidelityVerification:
    """A FidelityReport together with the raw differential evidence behind it."""

    report: FidelityReport
    mismatches: tuple[DifferentialMismatch, ...]
    observations: tuple[FidelityObservation, ...] = ()


class FidelityVerifier:
    """Runs Symmetrist, differential testing, Assayer, then confidence in that order."""

    def __init__(
        self,
        runtime: SandboxRuntime,
        evaluation_runner: EvaluationRunner | None = None,
    ) -> None:
        self._runtime = runtime
        self._evaluation_runner = evaluation_runner

    def verify(
        self,
        sandbox_id: str,
        harness_pair: HarnessPair,
        scoped_change_set: ScopedChangeSet,
        partial_spec: PartialInteractionSpec,
        base_source: str,
        head_source: str,
        diff_new_deps: set[str] | None = None,
        diff_removed_deps: set[str] | None = None,
    ) -> FidelityVerification:
        """Verify a pair against real modules, returning concrete mismatch evidence."""
        tolerance = _report_tolerance(partial_spec.observables)
        symmetry = symmetrist_check(
            _harness_stub_config(harness_pair.harness_a.source, harness_pair),
            _harness_stub_config(harness_pair.harness_b.source, harness_pair),
            diff_new_deps=diff_new_deps or set(),
            diff_removed_deps=diff_removed_deps or set(),
        )
        if not symmetry.passed:
            return FidelityVerification(
                _failed_symmetrist_report(symmetry, tolerance),
                (),
            )

        runner = self._evaluation_runner
        if runner is None:
            runner = self._sandbox_runner(
                sandbox_id,
                harness_pair,
                scoped_change_set,
                partial_spec,
                base_source,
                head_source,
            )

        points = sobol_points(partial_spec.knobs)
        point_indices = {
            json.dumps(point, sort_keys=True, separators=(",", ":")): index
            for index, point in enumerate(points)
        }
        mismatches: list[DifferentialMismatch] = []
        evaluated_observations: list[FidelityObservation] = []
        agreeing_points: list[dict[str, Any]] = []
        trace_for = getattr(runner, "trace_for", None)
        for point in points:
            point_matches = True
            harness_by_version: dict[str, dict[str, Any]] = {}
            for version in ("base", "head"):
                harness_observations = runner(f"harness_{version}", point, 0)
                harness_by_version[version] = harness_observations
                reference_observations = runner(f"reference_{version}", point, 0)
                point_mismatches = _compare_observations(
                    point,
                    version,
                    partial_spec.observables,
                    harness_observations,
                    reference_observations,
                    tolerance,
                )
                if point_mismatches:
                    point_matches = False
                    mismatches.extend(point_mismatches)
            if point_matches:
                agreeing_points.append(point)
            evaluated_observations.append(
                FidelityObservation(
                    point=dict(point),
                    base=harness_by_version["base"],
                    head=harness_by_version["head"],
                    trace=trace_for(point) if trace_for is not None else None,
                )
            )

        prepare_assay = getattr(runner, "prepare_assay", None)
        if prepare_assay is not None:
            prepare_assay(agreeing_points)
        stability, stability_factor = self._assay(
            runner,
            partial_spec.observables,
            agreeing_points,
            harness_pair,
            point_indices,
        )
        agreement_rate = len(agreeing_points) / len(points)
        coverage_factor = min(1.0, math.log1p(len(points)) / math.log1p(256))
        confidence = agreement_rate * stability_factor * coverage_factor
        band = _confidence_band(confidence)
        report = FidelityReport(
            verdict="verified" if agreement_rate >= 0.85 and confidence >= 0.60 else "degraded",
            symmetrist=_symmetrist_summary(symmetry),
            agreement=Agreement(
                samples=len(points),
                matched=len(agreeing_points),
                rate=agreement_rate,
                tolerance=tolerance,
            ),
            stability=stability,
            coverage=Coverage(samples=len(points), strategy="sobol"),
            confidence=confidence,
            band=band,
            degradeReason=_degrade_reason(agreement_rate, confidence),
        )
        return FidelityVerification(
            report,
            tuple(mismatches),
            tuple(evaluated_observations),
        )

    def _assay(
        self,
        runner: EvaluationRunner,
        observables: list[Observable],
        agreeing_points: list[dict[str, Any]],
        harness_pair: HarnessPair,
        point_indices: dict[str, int],
    ) -> tuple[Stability, float]:
        """Run twelve paired replicates only for already-agreeing differential points."""
        estimates: dict[str, list[float]] = {observable.id: [] for observable in observables}
        for point in agreeing_points:
            point_index = point_indices[
                json.dumps(point, sort_keys=True, separators=(",", ":"))
            ]
            values = {
                observable.id: {"base": [], "head": []} for observable in observables
            }
            for replicate in range(ASSAYER_REPLICATES):
                seed = _replicate_seed(point_index, replicate)
                for version in ("base", "head"):
                    observations = runner(f"harness_{version}", point, seed)
                    for observable in observables:
                        values[observable.id][version].append(
                            observations[observable.id]
                        )
            for observable in observables:
                for version in ("base", "head"):
                    estimates[observable.id].append(
                        _stability_estimate(observable, values[observable.id][version])
                    )

        per_observable = {}
        for observable in observables:
            maximum = max(estimates[observable.id], default=0.0)
            if observable.render in _NUMERIC_RENDERS:
                per_observable[observable.id] = CvStabilityEstimate(kind="cv", value=maximum)
            else:
                per_observable[observable.id] = InstabilityStabilityEstimate(
                    kind="instability", value=maximum
                )

        # An empty uncertainty set has no perturbation dimensions: stability is exactly zero.
        if not harness_pair.uncertainty_specs:
            return Stability(replicates=ASSAYER_REPLICATES, perObservable=per_observable), 1.0
        maximum_instability = max(
            (max(estimates[observable.id], default=0.0) for observable in observables),
            default=0.0,
        )
        return (
            Stability(replicates=ASSAYER_REPLICATES, perObservable=per_observable),
            max(0.0, min(1.0, 1.0 - maximum_instability / CV_MAX)),
        )

    def _sandbox_runner(
        self,
        sandbox_id: str,
        harness_pair: HarnessPair,
        scoped_change_set: ScopedChangeSet,
        partial_spec: PartialInteractionSpec,
        base_source: str,
        head_source: str,
    ) -> EvaluationRunner:
        """Stage artifacts once, then execute generated and independent paths in one sandbox."""
        base_harness_path = f"{harness_pair.harness_a.entry_module}.harness.py"
        head_harness_path = f"{harness_pair.harness_b.entry_module}.harness.py"
        _write_source(self._runtime, sandbox_id, harness_pair.harness_a.entry_module, base_source)
        _write_source(self._runtime, sandbox_id, harness_pair.harness_b.entry_module, head_source)
        _write_source(self._runtime, sandbox_id, base_harness_path, harness_pair.harness_a.source)
        _write_source(self._runtime, sandbox_id, head_harness_path, harness_pair.harness_b.source)

        paths = {
            "harness_base": base_harness_path,
            "harness_head": head_harness_path,
            "reference_base": harness_pair.harness_a.entry_module,
            "reference_head": harness_pair.harness_b.entry_module,
        }

        all_points = sobol_points(partial_spec.knobs)
        all_point_indices = {
            json.dumps(point, sort_keys=True, separators=(",", ":")): index
            for index, point in enumerate(all_points)
        }
        differential_cache: dict[str, dict[str, dict[str, Any]]] = {}
        replicate_cache: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        assay_points: list[dict[str, Any]] = []
        assay_seed_table: list[list[str]] = []
        assay_prepared = False

        def prepare_assay(agreeing_points: list[dict[str, Any]]) -> None:
            """Tell the transport runner which faithful points Assayer may replicate."""
            nonlocal assay_prepared
            assay_points[:] = agreeing_points
            assay_seed_table[:] = [
                [
                    _replicate_seed(all_point_indices[
                        json.dumps(point, sort_keys=True, separators=(",", ":"))
                    ], replicate)
                    for replicate in range(ASSAYER_REPLICATES)
                ]
                for point in agreeing_points
            ]
            assay_prepared = True

        def trace_for(point: dict[str, Any]) -> TraceAttribution | None:
            """Return this point's driver-collected paired trace after the suite has run."""
            point_key = json.dumps(point, sort_keys=True, separators=(",", ":"))
            item = differential_cache.get(point_key)
            if item is None:
                return None
            return trace_attribution(
                item.get("trace_base"),
                item.get("trace_head"),
                base_source,
                head_source,
            )

        def run(kind: str, point: dict[str, Any], seed: int | str) -> dict[str, Any]:
            """Amortize transport while preserving every logical invocation."""
            point_key = json.dumps(point, sort_keys=True, separators=(",", ":"))
            if not differential_cache:
                suite = _run_bundle(
                    self._runtime,
                    sandbox_id,
                    _differential_suite_command(
                        paths,
                        all_points,
                        partial_spec.knobs,
                        partial_spec.observables,
                        scoped_change_set,
                    ),
                    "differential suite",
                )
                differential_cache.update(
                    {
                        json.dumps(item.pop("point"), sort_keys=True, separators=(",", ":")): item
                        for item in suite["points"]
                    }
                )

            # A categorical Sobol design can contain duplicate positions.  Phase
            # selection must therefore be driven by Verifier's explicit
            # ``prepare_assay`` boundary, never by whether a position happened
            # to be seen earlier in the differential loop.
            if not assay_prepared or kind.startswith("reference_"):
                return differential_cache[point_key][kind]

            seed_text = str(seed)
            if not replicate_cache:
                suite = _run_bundle(
                    self._runtime,
                    sandbox_id,
                    _assayer_suite_command(paths, assay_points, assay_seed_table),
                    "Assayer replicate suite",
                )
                replicate_cache.update(
                    {
                        json.dumps(item.pop("point"), sort_keys=True, separators=(",", ":")): item[
                            "replicates"
                        ]
                        for item in suite["points"]
                    }
                )
            return replicate_cache[point_key][seed_text][kind]

        setattr(run, "prepare_assay", prepare_assay)
        setattr(run, "trace_for", trace_for)
        return run


def sobol_points(knobs: list[Knob], m: int = SOBOL_M) -> list[dict[str, Any]]:
    """Generate a power-of-two Sobol design across all PartialInteractionSpec knobs."""
    samples = qmc.Sobol(d=len(knobs), scramble=False).random_base2(m=m)
    return [
        {knob.id: _scale_sample(knob, sample[dimension]) for dimension, knob in enumerate(knobs)}
        for sample in samples
    ]


def _scale_sample(knob: Knob, sample: float) -> Any:
    """Map a unit Sobol coordinate into one knob's declared domain and type."""
    if knob.type == "enum":
        values = knob.domain.values
        return values[min(len(values) - 1, int(sample * len(values)))]
    if knob.type == "boolean":
        return bool(int(sample * 2))

    minimum = knob.domain.min
    maximum = knob.domain.max
    if knob.scale == "log":
        value = 10 ** (math.log10(minimum) + sample * math.log10(maximum / minimum))
    else:
        value = minimum + sample * (maximum - minimum)
    value = round((value - minimum) / knob.domain.step) * knob.domain.step + minimum
    if knob.type == "integer":
        return int(round(value))
    return float(value)


def _compare_observations(
    point: dict[str, Any],
    version: str,
    observables: list[Observable],
    harness_observations: dict[str, Any],
    reference_observations: dict[str, Any],
    tolerance: RelativeTolerance | ExactTolerance,
) -> list[DifferentialMismatch]:
    """Compare numeric outputs relatively and categorical outputs exactly."""
    mismatches = []
    for observable in observables:
        harness_value = harness_observations[observable.id]
        reference_value = reference_observations[observable.id]
        if observable.render in _NUMERIC_RENDERS:
            assert isinstance(tolerance, RelativeTolerance)
            denominator = max(abs(harness_value), abs(reference_value))
            relative_error = (
                0.0
                if denominator == 0
                else abs(harness_value - reference_value) / denominator
            )
            matches = relative_error <= tolerance.epsilon
        elif observable.render in _CATEGORICAL_RENDERS:
            # C-4: a route/cell/state has no meaningful numeric distance. It
            # agrees only when its complete categorical value is identical.
            matches = harness_value == reference_value
        else:  # pragma: no cover - Observable.render is schema-constrained.
            raise ValueError(f"Unsupported observable render type: {observable.render}")
        if not matches:
            mismatches.append(
                DifferentialMismatch(
                    point=point,
                    version=version,
                    observable_id=observable.id,
                    harness_value=harness_value,
                    reference_value=reference_value,
                )
            )
    return mismatches


def _stability_estimate(observable: Observable, values: list[Any]) -> float:
    """Compute CV for numeric observables and modal instability for categorical ones."""
    if observable.render in _NUMERIC_RENDERS:
        numeric_values = [float(value) for value in values]
        mean = statistics.fmean(numeric_values)
        deviation = statistics.pstdev(numeric_values)
        # The schema does not yet carry a numeric unit scale; use one declared unit.
        return deviation / max(abs(mean), 1.0)
    if observable.render in _CATEGORICAL_RENDERS:
        # C-4: categorical wobble is the fraction of replicates that differ
        # from the modal route/cell/state, not a coefficient of variation.
        encoded = [json.dumps(value, sort_keys=True) for value in values]
        return 1.0 - max(Counter(encoded).values()) / len(encoded)
    raise ValueError(f"Unsupported observable render type: {observable.render}")


def _harness_command(harness_path: str, point: dict[str, Any], seed: int | str) -> str:
    """Execute a staged generated harness with one point and replicate seed."""
    return (
        "import json, runpy\n"
        f"namespace = runpy.run_path({harness_path!r})\n"
        f"config = json.loads({json.dumps(json.dumps(point))})\n"
        f"print(json.dumps(namespace['run'](config, {seed}), sort_keys=True))"
    )


def _reference_command(
    module_path: str,
    knobs: list[Knob],
    observables: list[Observable],
    scoped_change_set: ScopedChangeSet,
    point: dict[str, Any],
    seed: int | str,
) -> str:
    """Run the real module directly with duplicated driver logic, never a harness import."""
    return _reference_program(module_path, knobs, observables, scoped_change_set, point, seed) + (
        "\nprint(json.dumps({\"observations\": OBSERVATIONS}, sort_keys=True))\n"
    )


def _reference_program(
    module_path: str,
    knobs: list[Knob],
    observables: list[Observable],
    scoped_change_set: ScopedChangeSet,
    point: dict[str, Any],
    seed: int | str,
) -> str:
    """Return the direct-real-code program with its observation kept in memory."""
    entry_point = scoped_change_set.entry_point
    if entry_point is None:
        raise ValueError("Independent reference execution requires a scoped entry point")
    template = get_entry_point_template(entry_point.fn)
    if template is None:
        raise ValueError(
            f"no harness template registered for this entry-point shape: {entry_point.fn}"
        )
    return template.reference_program(
        ReferenceProgramRequest(
            module_path=module_path,
            knobs=knobs,
            observables=observables,
            point=point,
            seed=seed,
        )
    )


def _differential_bundle_command(
    paths: dict[str, str],
    point: dict[str, Any],
    knobs: list[Knob],
    observables: list[Observable],
    scoped_change_set: ScopedChangeSet,
) -> str:
    """Evaluate all four independent differential paths in one sandbox command."""
    reference_programs = {
        "reference_base": _reference_program(
            paths["reference_base"], knobs, observables, scoped_change_set, point, 0
        ),
        "reference_head": _reference_program(
            paths["reference_head"], knobs, observables, scoped_change_set, point, 0
        ),
    }
    return _bundle_program(
        harness_paths={
            "harness_base": paths["harness_base"],
            "harness_head": paths["harness_head"],
        },
        reference_programs=reference_programs,
        point=point,
        seeds=[0],
        include_seed_in_result=False,
    )


def _differential_suite_command(
    paths: dict[str, str],
    points: list[dict[str, Any]],
    knobs: list[Knob],
    observables: list[Observable],
    scoped_change_set: ScopedChangeSet,
) -> str:
    """Run all 128 four-way comparisons in one already-warm sandbox command."""
    reference_programs = [
        {
            "base": _reference_program(
                paths["reference_base"], knobs, observables, scoped_change_set, point, 0
            ),
            "head": _reference_program(
                paths["reference_head"], knobs, observables, scoped_change_set, point, 0
            ),
        }
        for point in points
    ]
    return _suite_program(
        paths,
        points,
        mode="differential",
        reference_programs=reference_programs,
    )


def _replicate_bundle_command(
    paths: dict[str, str], point: dict[str, Any], seeds: list[str]
) -> str:
    """Evaluate both harnesses for all twelve Assayer seeds in one sandbox command."""
    return _bundle_program(
        harness_paths={
            "harness_base": paths["harness_base"],
            "harness_head": paths["harness_head"],
        },
        reference_programs={},
        point=point,
        seeds=seeds,
        include_seed_in_result=True,
    )


def _assayer_suite_command(
    paths: dict[str, str], points: list[dict[str, Any]], seed_table: list[list[str]]
) -> str:
    """Run every required 12-replicate A/B pair in one warmed sandbox command."""
    # The direct reference path is unnecessary here: Assayer runs only harness replicas.
    return _suite_program(
        paths,
        points,
        mode="assayer",
        seed_table=seed_table,
    )


def _suite_program(
    paths: dict[str, str],
    points: list[dict[str, Any]],
    mode: str,
    seed_table: list[list[str]] | None = None,
    reference_programs: list[dict[str, str]] | None = None,
) -> str:
    """Build a transport-efficient suite while keeping each logical call isolated."""
    if mode == "differential" and reference_programs is None:
        raise ValueError("Differential suite requires registered reference programs")
    if seed_table is None:
        seed_table = [
            [_replicate_seed(point_index, replicate) for replicate in range(ASSAYER_REPLICATES)]
            for point_index in range(len(points))
        ]
    return f"""\
import json
import runpy

POINTS = json.loads({json.dumps(json.dumps(points))})
PATHS = json.loads({json.dumps(json.dumps(paths, sort_keys=True))})
REFERENCE_PROGRAMS = json.loads({json.dumps(json.dumps(reference_programs or []))})
SEED_TABLE = json.loads({json.dumps(json.dumps(seed_table))})

def run_harness(path, point, seed):
    namespace = runpy.run_path(path)
    return namespace["run"](point, seed)

def run_reference(program):
    namespace = {{}}
    exec(program, namespace)
    return namespace["OBSERVATIONS"]

if {mode!r} == "differential":
    output = {{"points": []}}
    for point, references in zip(POINTS, REFERENCE_PROGRAMS, strict=True):
        harness_base = run_harness(PATHS["harness_base"], point, 0)
        harness_head = run_harness(PATHS["harness_head"], point, 0)
        output["points"].append({{
            "point": point,
            "harness_base": harness_base["observations"],
            "trace_base": harness_base.get("trace"),
            "reference_base": run_reference(references["base"]),
            "harness_head": harness_head["observations"],
            "trace_head": harness_head.get("trace"),
            "reference_head": run_reference(references["head"]),
        }})
else:
    output = {{"points": []}}
    for point, seeds in zip(POINTS, SEED_TABLE):
        output["points"].append({{
            "point": point,
            "replicates": {{
                str(seed): {{
                    "harness_base": run_harness(PATHS["harness_base"], point, seed)["observations"],
                    "harness_head": run_harness(PATHS["harness_head"], point, seed)["observations"],
                }}
                for seed in seeds
            }},
        }})
print(json.dumps(output, sort_keys=True))
"""


def _bundle_program(
    harness_paths: dict[str, str],
    reference_programs: dict[str, str],
    point: dict[str, Any],
    seeds: list[int | str],
    include_seed_in_result: bool,
) -> str:
    """Build one Python program that executes isolated invocations without shell hops."""
    return f"""\
import json
import runpy

POINT = json.loads({json.dumps(json.dumps(point))})
HARNESS_PATHS = json.loads({json.dumps(json.dumps(harness_paths, sort_keys=True))})
REFERENCE_PROGRAMS = json.loads({json.dumps(json.dumps(reference_programs, sort_keys=True))})
SEEDS = json.loads({json.dumps(json.dumps(seeds))})

def run_harness(path, seed):
    namespace = runpy.run_path(path)
    return namespace["run"](POINT, seed)

def run_reference(program):
    namespace = {{}}
    exec(program, namespace)
    return namespace["OBSERVATIONS"]

if {include_seed_in_result!r}:
    output = {{
        str(seed): {{
            kind: run_harness(path, seed)["observations"]
            for kind, path in HARNESS_PATHS.items()
        }}
        for seed in SEEDS
    }}
else:
    harness_output = {{kind: run_harness(path, 0) for kind, path in HARNESS_PATHS.items()}}
    output = {{kind: value["observations"] for kind, value in harness_output.items()}}
    output.update({{
        f"trace_{{kind.removeprefix('harness_')}}": value.get("trace")
        for kind, value in harness_output.items()
    }})
    output.update({{kind: run_reference(program) for kind, program in REFERENCE_PROGRAMS.items()}})
print(json.dumps(output, sort_keys=True))
"""


def _run_bundle(
    runtime: SandboxRuntime, sandbox_id: str, code: str, description: str
) -> dict[str, Any]:
    """Execute and parse a bundled program, surfacing a useful port-level error."""
    result = runtime.run_code(sandbox_id, code)
    if result["exit_code"] != 0:
        raise RuntimeError(f"{description} failed: {result['stderr']}")
    parsed = json.loads(result["stdout"])
    if not isinstance(parsed, dict):
        raise TypeError(f"{description} did not return a JSON object")
    return parsed


def _replicate_seed(point_index: int, replicate: int) -> str:
    """Derive the spec's H(baseSeed, i) seed used identically for each A/B pair."""
    material = f"lever-assayer-base-seed:{point_index}:{replicate}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _write_source(runtime: SandboxRuntime, sandbox_id: str, path: str, source: str) -> None:
    """Stage one source artifact through the port without importing infrastructure SDKs."""
    code = (
        "from pathlib import Path\n"
        f"target = Path({path!r})\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        f"target.write_text({source!r})"
    )
    result = runtime.run_code(sandbox_id, code)
    if result["exit_code"] != 0:
        raise RuntimeError(f"Could not stage {path}: {result['stderr']}")


def _harness_stub_config(source: str, pair: HarnessPair) -> dict[str, Any]:
    """Read the actual STUB_CONFIG embedded in a generated harness source file."""
    parsed = ast.parse(source)
    for statement in parsed.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "STUB_CONFIG"
        ):
            value = ast.literal_eval(statement.value)
            if not isinstance(value, dict):
                raise TypeError("Generated STUB_CONFIG must be a dictionary")
            return value
    # Retain a deterministic fallback for a future non-template HarnessPair.
    return {stub.dependency: stub.as_dict() for stub in pair.stub_config}


def _report_tolerance(
    observables: list[Observable],
) -> RelativeTolerance | ExactTolerance:
    """Choose the specification-mandated comparator for the current observation set."""
    if all(observable.render not in _NUMERIC_RENDERS for observable in observables):
        return ExactTolerance(kind="exact")
    return RelativeTolerance(kind="relative", epsilon=0.01)


def _symmetrist_summary(result: SymmetristResult) -> SymmetristSummary:
    """Adapt the deterministic Symmetrist result to the persisted report schema."""
    return SymmetristSummary(
        passed=result.passed,
        hashA=result.hash_a or "",
        hashB=result.hash_b or "",
        unjustifiedKeys=result.unjustified_keys,
    )


def _failed_symmetrist_report(
    result: SymmetristResult, tolerance: RelativeTolerance | ExactTolerance
) -> FidelityReport:
    """Return a fail-fast degraded report without executing any harness code."""
    return FidelityReport(
        verdict="degraded",
        symmetrist=_symmetrist_summary(result),
        agreement=Agreement(samples=0, matched=0, rate=0.0, tolerance=tolerance),
        stability=Stability(replicates=0, perObservable={}),
        coverage=Coverage(samples=0, strategy="sobol"),
        confidence=0.0,
        band="low",
        degradeReason=f"Symmetrist failed for keys: {', '.join(result.unjustified_keys)}",
    )


def _confidence_band(confidence: float) -> str:
    """Map the measured product to the immutable high/medium/low thresholds."""
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.60:
        return "medium"
    return "low"


def _degrade_reason(agreement_rate: float, confidence: float) -> str | None:
    """Give the spec-required human reason when verification cannot proceed."""
    if agreement_rate < 0.85:
        return "Harness agreement rate is below the required 0.85."
    if confidence < 0.60:
        return "Harness uncertainty makes confidence lower than 0.60."
    return None
