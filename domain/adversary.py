"""Deterministic cached search for the most behaviorally divergent knob position."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Literal

from scipy.stats import qmc

from domain.fidelity_verifier import FidelityVerification, sobol_points
from domain.harness_engineer import HarnessPair
from domain.line_attribution import trace_attribution
from domain.ports import SandboxExecutionError, SandboxRuntime
from domain.schema import (
    InteractionSpec,
    AdversaryObjective,
    DomainPackId,
    Knob,
    KnobPosition,
    NamedPosition,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    SurpriseMarker,
    TraceAttribution,
    UnsafePredicate,
    UnsafeLiteralTarget,
    UnsafeKnobTarget,
)


EXPLORE_M = 6
EXPLORE_POINTS = 2**EXPLORE_M
TOP_SEEDS = 8
EXPLOIT_EVALUATIONS_PER_SEED = 8
MAX_EVALUATIONS = EXPLORE_POINTS + TOP_SEEDS * EXPLOIT_EVALUATIONS_PER_SEED
NO_DIVERGENCE_EPSILON = 0.02
_NUMERIC_RENDERS = frozenset({"timeseries", "scalar", "histogram"})
SearchObjective = AdversaryObjective
SamplerPrior = Literal["plausible", "boundary"]

EvaluationRunner = Callable[[dict[str, Any]], "ObservationBundle"]
BatchEvaluationRunner = Callable[[list[dict[str, Any]]], list["ObservationBundle"]]


@dataclass(frozen=True)
class ObservationBundle:
    """The A/B observable values for one concrete knob position."""

    base: dict[str, Any]
    head: dict[str, Any]
    trace: TraceAttribution | None = None


@dataclass(frozen=True)
class CacheEntry:
    """One retained knob position and its reusable A/B observation bundle."""

    position: KnobPosition
    observations: ObservationBundle


@dataclass(frozen=True)
class TracePoint:
    """One empirical point emitted as the bounded search reaches it."""

    position: KnobPosition
    divergence: float
    # Keeping the phase on the evidence lets presentation distinguish the
    # evenly spread Sobol exploration from the ascent probes without guessing
    # from arrival order.
    phase: Literal["explore", "exploit"] = "explore"


@dataclass(frozen=True)
class SearchAccounting:
    """Auditable phase counts separating reused positions from actual probe execution."""

    explore_attempted: int
    explore_reused_from_fidelity: int
    exploit_attempted: int
    exploit_executed_new: int
    exploit_collisions_with_explore: int
    exploit_collisions_with_exploit: int
    exploit_unattempted: int


@dataclass(frozen=True)
class AdversaryResult:
    """Search output for Synthesizer or a bounded no-divergence kickback."""

    initial_position: KnobPosition | None
    surprise_marker: SurpriseMarker | None
    presets: tuple[NamedPosition, ...]
    search_trace: tuple[TracePoint, ...]
    cache: tuple[CacheEntry, ...]
    no_divergence: bool
    reason: str | None = None
    accounting: SearchAccounting | None = None
    objective: SearchObjective = "max_divergence"
    unsafe_predicate: UnsafePredicate | None = None

    def apply_to_spec(self, spec: InteractionSpec) -> InteractionSpec:
        """Write Adversary-owned fields into a completed InteractionSpec copy."""
        if self.no_divergence or self.initial_position is None:
            return spec
        return spec.model_copy(
            update={
                "initialPosition": self.initial_position,
                "surpriseMarker": self.surprise_marker,
                "presets": list(self.presets),
            }
        )


class Adversary:
    """Runs the spec's 64-point Sobol explore plus capped coordinate-ascent exploit."""

    def __init__(
        self,
        runtime: SandboxRuntime,
        evaluation_runner: EvaluationRunner | None = None,
    ) -> None:
        self._runtime = runtime
        self._evaluation_runner = evaluation_runner

    def search(
        self,
        sandbox_id: str,
        harness_pair: HarnessPair,
        partial_spec: PartialInteractionSpec,
        fidelity: FidelityVerification,
        base_source: str | None = None,
        head_source: str | None = None,
        trace_callback: Callable[[TracePoint], None] | None = None,
        objective: SearchObjective | None = None,
        unsafe_predicate: UnsafePredicate | None = None,
        sampler_prior: SamplerPrior | None = None,
    ) -> AdversaryResult:
        """Search the selected empirical objective and emit every point immediately.

        ``reach_unsafe_state`` intentionally uses a different *prior*, not a
        different search engine: boundary-oriented Sobol probes expose malformed
        inputs before the same capped coordinate-ascent pass ranks them.
        ``sampler_prior`` exists for deterministic tests and defaults from the
        selected objective; callers should not need to set it in production.
        """
        if fidelity.report.verdict != "verified":
            raise ValueError("Adversary requires a verified FidelityReport")

        runner = self._evaluation_runner
        if runner is None:
            if base_source is None or head_source is None:
                raise ValueError("Sandbox search requires the independently checked base/head source")
            runner = self._sandbox_runner(
                sandbox_id, harness_pair, base_source, head_source
            )

        objective = _objective_for(partial_spec.domainPack, objective)
        if objective == "reach_unsafe_state" and unsafe_predicate is None:
            raise ValueError("reach_unsafe_state requires an UnsafePredicate")
        prior = sampler_prior or (
            "boundary" if objective == "reach_unsafe_state" else "plausible"
        )
        explore_points = (
            boundary_weighted_sobol_points(partial_spec.knobs, m=EXPLORE_M)
            if prior == "boundary"
            else sobol_points(partial_spec.knobs, m=EXPLORE_M)
        )
        explore_keys = {_point_key(point) for point in explore_points}
        cache: dict[str, CacheEntry] = {}
        trace_points: list[TracePoint] = []
        traced_keys: set[str] = set()

        def record_trace(point: dict[str, Any], phase: Literal["explore", "exploit"]) -> None:
            """Publish an actual cached result at the moment this search adopts it."""
            key = _point_key(point)
            # Phase 1 is always the 64-point Sobol design.  Integer/log domains
            # can quantize two design samples to one cached position, but both
            # samples still belong in the visible exploration trace.  Exploit
            # collisions, by contrast, are not new probes and are omitted.
            if phase == "exploit" and key in traced_keys:
                return
            divergence = _divergences(
                cache, partial_spec.observables, objective, unsafe_predicate
            )[key]
            trace_point = TracePoint(cache[key].position, divergence, phase)
            trace_points.append(trace_point)
            traced_keys.add(key)
            _emit_trace(trace_callback, trace_point)

        # Fidelity's Sobol points are already real executions.  Insert and emit
        # them in the deterministic Phase 1 sequence, so reuse avoids spend
        # without turning the Search Trace into a completion-only artifact.
        fidelity_by_key = {
            _point_key(observation.point): observation for observation in fidelity.observations
        }
        for point in explore_points:
            observation = fidelity_by_key.get(_point_key(point))
            if observation is None:
                continue
            self._store(
                cache,
                point,
                ObservationBundle(
                    observation.base,
                    observation.head,
                    observation.trace,
                ),
            )

        missing_explore_points = [
            point for point in explore_points if _point_key(point) not in cache
        ]
        # These calls are independent; reuse eliminates them for the normal verified path.
        with ThreadPoolExecutor(max_workers=min(32, len(missing_explore_points) or 1)) as pool:
            evaluated = zip(missing_explore_points, pool.map(runner, missing_explore_points))
            for point, observations in evaluated:
                self._store(cache, point, observations)

        # A numeric objective is normalized across the explored value range.
        # Publish Phase 1 once all 64 real/reused Sobol observations are in the
        # cache so a dot's live color is its actual search objective, not a
        # provisional range from an earlier insertion.
        for point in explore_points:
            record_trace(point, "explore")

        explore_keys = {_point_key(point) for point in explore_points}
        exploit_attempted = 0
        exploit_executed_new = 0
        exploit_collisions_with_explore = 0
        exploit_collisions_with_exploit = 0

        divergences = _divergences(
            cache, partial_spec.observables, objective, unsafe_predicate
        )
        ranked = sorted(
            explore_points,
            key=lambda point: divergences[_point_key(point)],
            reverse=True,
        )
        batch_runner = getattr(runner, "evaluate_many", None)
        if batch_runner is not None:
            accounting = self._batched_coordinate_ascent(
                cache,
                ranked[:TOP_SEEDS],
                partial_spec.knobs,
                partial_spec.observables,
                objective,
                unsafe_predicate,
                explore_keys,
                batch_runner,
                record_trace,
            )
            exploit_attempted += accounting[0]
            exploit_executed_new += accounting[1]
            exploit_collisions_with_explore += accounting[2]
            exploit_collisions_with_exploit += accounting[3]
        else:
            for seed in ranked[:TOP_SEEDS]:
                accounting = self._coordinate_ascent(
                    cache,
                    seed,
                    partial_spec.knobs,
                    partial_spec.observables,
                    objective,
                    unsafe_predicate,
                    runner,
                    explore_keys,
                    record_trace,
                )
                exploit_attempted += accounting[0]
                exploit_executed_new += accounting[1]
                exploit_collisions_with_explore += accounting[2]
                exploit_collisions_with_exploit += accounting[3]

        search_accounting = SearchAccounting(
            explore_attempted=EXPLORE_POINTS,
            explore_reused_from_fidelity=EXPLORE_POINTS - len(missing_explore_points),
            exploit_attempted=exploit_attempted,
            exploit_executed_new=exploit_executed_new,
            exploit_collisions_with_explore=exploit_collisions_with_explore,
            exploit_collisions_with_exploit=exploit_collisions_with_exploit,
            exploit_unattempted=(
                TOP_SEEDS * EXPLOIT_EVALUATIONS_PER_SEED - exploit_attempted
            ),
        )

        divergences = _divergences(
            cache, partial_spec.observables, objective, unsafe_predicate
        )
        trace = tuple(trace_points)
        best_key = max(divergences, key=divergences.get)
        best = cache[best_key]
        best_divergence = divergences[best_key]
        no_result = (
            best_divergence < 1.0
            if objective == "reach_unsafe_state"
            else best_divergence < NO_DIVERGENCE_EPSILON
        )
        if no_result:
            reason = (
                "No unsafe state "
                + _unsafe_predicate_description(unsafe_predicate)
                + " was reached after boundary-weighted exploration of "
                + _varied_knobs(partial_spec.knobs)
                + "."
                if objective == "reach_unsafe_state"
                else (
                    "No normalized divergence reached 0.02 after varying "
                    + _varied_knobs(partial_spec.knobs)
                    + "."
                )
            )
            return AdversaryResult(
                initial_position=None,
                surprise_marker=None,
                presets=(),
                search_trace=trace,
                cache=tuple(cache.values()),
                no_divergence=True,
                reason=reason,
                accounting=search_accounting,
                objective=objective,
                unsafe_predicate=unsafe_predicate,
            )

        position = best.position
        marker = SurpriseMarker(
            position=position,
            divergence=min(1.0, best_divergence),
            caption=(
                _unsafe_caption(best.observations, best.position.root, unsafe_predicate)
                if objective == "reach_unsafe_state"
                else _caption(best.observations, partial_spec.observables)
            ),
        )
        presets = tuple(
            _preset(cache[key], divergences[key], objective)
            for key in sorted(divergences, key=divergences.get, reverse=True)[:3]
        )
        return AdversaryResult(
            initial_position=position,
            surprise_marker=marker,
            presets=presets,
            search_trace=trace,
            cache=tuple(cache.values()),
            no_divergence=False,
            accounting=search_accounting,
            objective=objective,
            unsafe_predicate=unsafe_predicate,
        )

    def _coordinate_ascent(
        self,
        cache: dict[str, CacheEntry],
        seed: dict[str, Any],
        knobs: list[Knob],
        observables: list[Observable],
        objective: SearchObjective,
        unsafe_predicate: UnsafePredicate | None,
        runner: EvaluationRunner,
        explore_keys: set[str],
        record_trace: Callable[[dict[str, Any], Literal["explore", "exploit"]], None],
    ) -> tuple[int, int, int, int]:
        """Use eight bounded neighbor probes, halving numeric steps after misses."""
        current = dict(seed)
        step_sizes = {knob.id: _initial_step(knob) for knob in knobs}
        misses = {knob.id: 0 for knob in knobs}
        executed_new = 0
        collisions_with_explore = 0
        collisions_with_exploit = 0
        for attempt in range(EXPLOIT_EVALUATIONS_PER_SEED):
            knob = knobs[(attempt // 2) % len(knobs)]
            direction = 1 if attempt % 2 == 0 else -1
            candidate = _neighbor(current, knob, direction, step_sizes[knob.id])
            candidate_key = _point_key(candidate)
            if candidate_key in cache:
                if candidate_key in explore_keys:
                    collisions_with_explore += 1
                else:
                    collisions_with_exploit += 1
            else:
                executed_new += 1
            _, added = self._evaluate(cache, candidate, runner)
            if added:
                record_trace(candidate, "exploit")
            divergences = _divergences(cache, observables, objective, unsafe_predicate)
            if divergences[_point_key(candidate)] > divergences[_point_key(current)]:
                current = candidate
                misses[knob.id] = 0
            else:
                misses[knob.id] += 1
                if misses[knob.id] >= 2:
                    step_sizes[knob.id] = _halve_step(knob, step_sizes[knob.id])
                    misses[knob.id] = 0
        return (
            EXPLOIT_EVALUATIONS_PER_SEED,
            executed_new,
            collisions_with_explore,
            collisions_with_exploit,
        )

    def _batched_coordinate_ascent(
        self,
        cache: dict[str, CacheEntry],
        seeds: list[dict[str, Any]],
        knobs: list[Knob],
        observables: list[Observable],
        objective: SearchObjective,
        unsafe_predicate: UnsafePredicate | None,
        explore_keys: set[str],
        evaluate_many: BatchEvaluationRunner,
        record_trace: Callable[[dict[str, Any], Literal["explore", "exploit"]], None],
    ) -> tuple[int, int, int, int]:
        """Run one ascent round for every seed per warm-sandbox transport call."""
        states = [
            {
                "current": dict(seed),
                "steps": {knob.id: _initial_step(knob) for knob in knobs},
                "misses": {knob.id: 0 for knob in knobs},
            }
            for seed in seeds
        ]
        executed_new = 0
        collisions_with_explore = 0
        collisions_with_exploit = 0

        for attempt in range(EXPLOIT_EVALUATIONS_PER_SEED):
            knob = knobs[(attempt // 2) % len(knobs)]
            direction = 1 if attempt % 2 == 0 else -1
            candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
            missing: dict[str, dict[str, Any]] = {}
            for state in states:
                candidate = _neighbor(
                    state["current"], knob, direction, state["steps"][knob.id]
                )
                candidate_key = _point_key(candidate)
                candidates.append((state, candidate))
                if candidate_key in cache:
                    if candidate_key in explore_keys:
                        collisions_with_explore += 1
                    else:
                        collisions_with_exploit += 1
                elif candidate_key in missing:
                    # Another seed in this same round already owns the one real probe.
                    collisions_with_exploit += 1
                else:
                    missing[candidate_key] = candidate
                    executed_new += 1

            if missing:
                fresh_points = list(missing.values())
                fresh_observations = evaluate_many(fresh_points)
                for point, observations in zip(fresh_points, fresh_observations, strict=True):
                    self._store(cache, point, observations)
                    record_trace(point, "exploit")

            divergences = _divergences(cache, observables, objective, unsafe_predicate)
            for state, candidate in candidates:
                if divergences[_point_key(candidate)] > divergences[_point_key(state["current"])]:
                    state["current"] = candidate
                    state["misses"][knob.id] = 0
                else:
                    state["misses"][knob.id] += 1
                    if state["misses"][knob.id] >= 2:
                        state["steps"][knob.id] = _halve_step(
                            knob, state["steps"][knob.id]
                        )
                        state["misses"][knob.id] = 0

        return (
            len(seeds) * EXPLOIT_EVALUATIONS_PER_SEED,
            executed_new,
            collisions_with_explore,
            collisions_with_exploit,
        )

    def _evaluate(
        self,
        cache: dict[str, CacheEntry],
        point: dict[str, Any],
        runner: EvaluationRunner,
    ) -> tuple[ObservationBundle, bool]:
        """Retain every actual evaluation and never rerun an already cached position."""
        key = _point_key(point)
        added = False
        if key not in cache:
            if len(cache) >= MAX_EVALUATIONS:
                raise RuntimeError("Adversary exceeded its 128-evaluation hard cap")
            self._store(cache, point, runner(point))
            added = True
        return cache[key].observations, added

    @staticmethod
    def _store(
        cache: dict[str, CacheEntry], point: dict[str, Any], observations: ObservationBundle
    ) -> None:
        cache[_point_key(point)] = CacheEntry(
            position=KnobPosition(dict(point)), observations=observations
        )

    def _sandbox_runner(
        self,
        sandbox_id: str,
        harness_pair: HarnessPair,
        base_source: str,
        head_source: str,
    ) -> EvaluationRunner:
        """Stage both harnesses once and execute their A/B observations per search point."""
        base_harness_path = f"{harness_pair.harness_a.entry_module}.harness.py"
        head_harness_path = f"{harness_pair.harness_b.entry_module}.harness.py"
        _write_source(
            self._runtime,
            sandbox_id,
            harness_pair.harness_a.entry_module,
            harness_pair.harness_a.instrumented_module_source or base_source,
        )
        _write_source(
            self._runtime,
            sandbox_id,
            harness_pair.harness_b.entry_module,
            harness_pair.harness_b.instrumented_module_source or head_source,
        )
        _write_source(self._runtime, sandbox_id, base_harness_path, harness_pair.harness_a.source)
        _write_source(self._runtime, sandbox_id, head_harness_path, harness_pair.harness_b.source)
        trace_base_source = harness_pair.harness_a.instrumented_module_source or base_source
        trace_head_source = harness_pair.harness_b.instrumented_module_source or head_source

        def run(point: dict[str, Any]) -> ObservationBundle:
            code = f"""\
import json
import runpy

point = json.loads({json.dumps(json.dumps(point))})
base = runpy.run_path({base_harness_path!r})["run"](point, 0)
head = runpy.run_path({head_harness_path!r})["run"](point, 0)
print(json.dumps({{"base": base, "head": head}}, sort_keys=True))
"""
            result = self._runtime.run_code(sandbox_id, code)
            if result["exit_code"] != 0:
                raise SandboxExecutionError(f"Adversary harness execution failed: {result['stderr']}")
            payload = json.loads(result["stdout"])
            return ObservationBundle(
                base=payload["base"]["observations"],
                head=payload["head"]["observations"],
                trace=trace_attribution(
                    payload["base"].get("trace"),
                    payload["head"].get("trace"),
                    trace_base_source,
                    trace_head_source,
                ),
            )

        def run_many(points: list[dict[str, Any]]) -> list[ObservationBundle]:
            """Execute a complete ascent round inside the already-running sandbox."""
            code = f"""\
import json
import runpy

points = json.loads({json.dumps(json.dumps(points))})

def observations(path, point):
    return runpy.run_path(path)["run"](point, 0)

output = [
    {{
        "base": observations({base_harness_path!r}, point),
        "head": observations({head_harness_path!r}, point),
    }}
    for point in points
]
print(json.dumps(output, sort_keys=True))
"""
            result = self._runtime.run_code(sandbox_id, code)
            if result["exit_code"] != 0:
                raise SandboxExecutionError(f"Adversary harness batch failed: {result['stderr']}")
            payload = json.loads(result["stdout"])
            return [
                ObservationBundle(
                    base=item["base"]["observations"],
                    head=item["head"]["observations"],
                    trace=trace_attribution(
                        item["base"].get("trace"),
                        item["head"].get("trace"),
                        trace_base_source,
                        trace_head_source,
                    ),
                )
                for item in payload
            ]

        setattr(run, "evaluate_many", run_many)
        return run


def _objective_for(
    domain_pack: DomainPackId,
    requested: SearchObjective | None = None,
) -> SearchObjective:
    """Select the pack default unless the user has deliberately chosen an objective."""
    if requested is not None:
        return requested
    if domain_pack is DomainPackId.DECISION_TREE:
        return "max_path_divergence"
    return "max_divergence"


def boundary_weighted_sobol_points(knobs: list[Knob], m: int = EXPLORE_M) -> list[dict[str, Any]]:
    """Generate a power-of-two Sobol design transformed toward adversarial boundaries.

    The unit-cube Sobol design remains deterministic and evenly covers every
    coordinate.  Only the inverse mapping changes: numeric controls favor
    below-minimum/minimum/maximum/max-int values, and enum controls also see
    null, empty and Unicode strings.  Driver numeric values deliberately use
    their declared maximum instead of ``sys.maxsize``: an unbounded request
    count could turn a safety probe into an unbounded workload.
    """
    if not knobs:
        return [{} for _ in range(2**m)]
    samples = qmc.Sobol(d=len(knobs), scramble=False).random_base2(m)
    return [
        {
            knob.id: _boundary_scale_sample(float(sample[index]), knob)
            for index, knob in enumerate(knobs)
        }
        for sample in samples
    ]


def _boundary_scale_sample(sample: float, knob: Knob) -> Any:
    """Map one Sobol coordinate to a safe-but-adversarial value for a knob."""
    if isinstance(knob.domain, NumericDomain):
        maximum: float | int = (
            knob.domain.max if knob.binding.kind == "driver" else sys.maxsize
        )
        values: list[float | int] = [-1, knob.domain.min, knob.domain.max, maximum]
        value = values[min(int(sample * len(values)), len(values) - 1)]
        return int(value) if knob.type == "integer" else float(value)
    if knob.type == "boolean":
        return bool(min(int(sample * 2), 1))

    # These are values that commonly expose missing validation or unexpected
    # lookup fall-through.  Declared values remain in the prior as well, so the
    # search is adversarially broad rather than merely malformed.
    candidates: list[Any] = [None, "", "⚠️", "contractor", "__proto__", "audit-log"]
    candidates.extend(knob.domain.values)
    values = list(dict.fromkeys(candidates))
    return values[min(int(sample * len(values)), len(values) - 1)]


def _emit_trace(
    callback: Callable[[TracePoint], None] | None,
    trace_point: TracePoint,
) -> None:
    """Deliver evidence to a presentation adapter without changing the search result."""
    if callback is None:
        return
    try:
        callback(trace_point)
    except Exception:
        # A dropped WebSocket must never alter the bounded empirical search.
        return


def _divergences(
    cache: dict[str, CacheEntry],
    observables: list[Observable],
    objective: SearchObjective = "max_divergence",
    unsafe_predicate: UnsafePredicate | None = None,
) -> dict[str, float]:
    """Score cached points for numeric/path divergence or unsafe reachability."""
    if not cache:
        return {}
    if objective == "reach_unsafe_state":
        if unsafe_predicate is None:
            raise ValueError("reach_unsafe_state requires an UnsafePredicate")
        return {
            key: float(
                _unsafe_matches(entry.observations, entry.position.root, unsafe_predicate)
            )
            for key, entry in cache.items()
        }
    if not observables:
        # Coordinate ascent compares cached raw differences while preserving its caller's ranges.
        return {
            key: _raw_distance(entry.observations)
            for key, entry in cache.items()
        }
    if objective == "max_path_divergence":
        path_observables = [
            observable for observable in observables if observable.render == "pathTrace"
        ]
        return {
            key: max(
                (
                    _normalized_observable_distance(
                        entry.observations, observable, cache.values()
                    )
                    for observable in path_observables
                ),
                default=0.0,
            )
            for key, entry in cache.items()
        }
    return {
        key: sum(
            _normalized_observable_distance(entry.observations, observable, cache.values())
            for observable in observables
        )
        / len(observables)
        for key, entry in cache.items()
    }


def _unsafe_matches(
    bundle: ObservationBundle,
    point: dict[str, Any],
    predicate: UnsafePredicate,
) -> bool:
    """Return whether a declared observable condition holds in either chosen version."""
    if isinstance(predicate.target, UnsafeKnobTarget):
        if predicate.target.id not in point:
            return False
        target: Any = point[predicate.target.id]
    else:
        assert isinstance(predicate.target, UnsafeLiteralTarget)
        target = predicate.target.value

    versions = (
        (predicate.versions,)
        if predicate.versions in {"base", "head"}
        else ("base", "head")
    )
    for version in versions:
        observations = bundle.base if version == "base" else bundle.head
        if predicate.observableId not in observations:
            continue
        if _compare_unsafe_value(observations[predicate.observableId], predicate.operator, target):
            return True
    return False


def _compare_unsafe_value(value: Any, operator: str, target: Any) -> bool:
    """Evaluate a total, non-throwing comparison for user-supplied predicate data."""
    try:
        if operator == "gt":
            return value > target
        if operator == "gte":
            return value >= target
        if operator == "lt":
            return value < target
        if operator == "lte":
            return value <= target
        if operator == "eq":
            return value == target
        if operator == "neq":
            return value != target
    except TypeError:
        return False
    raise ValueError(f"Unsupported unsafe-predicate operator: {operator}")


def _normalized_observable_distance(
    bundle: ObservationBundle, observable: Observable, entries: Any
) -> float:
    """Normalize numeric values only; categorical cell/route flips are unit distance."""
    distance = _observable_distance(bundle, observable.id, observable.render)
    if observable.render not in _NUMERIC_RENDERS:
        return distance
    observed_range = _observed_range(entries, observable.id)
    return distance / observed_range if observed_range > 0 else 0.0


def _observed_range(entries: Any, observable_id: str) -> float:
    """Measure a numeric observable's range across all cached base/head values."""
    values = []
    for entry in entries:
        for version in (entry.observations.base, entry.observations.head):
            value = version[observable_id]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
    return max(values) - min(values) if values else 0.0


def _observable_distance(
    bundle: ObservationBundle, observable_id: str, render: str | None = None
) -> float:
    """Return numeric distance, categorical equality, or normalized path Hamming distance."""
    base = bundle.base[observable_id]
    head = bundle.head[observable_id]
    if render == "pathTrace":
        return _normalized_hamming_distance(base, head)
    if (
        isinstance(base, (int, float))
        and not isinstance(base, bool)
        and isinstance(head, (int, float))
        and not isinstance(head, bool)
    ):
        return abs(float(head) - float(base))
    return 0.0 if base == head else 1.0


def _normalized_hamming_distance(base: Any, head: Any) -> float:
    """Compare ordered source-tagged branch vectors, including path-length forks."""
    if not isinstance(base, list) or not isinstance(head, list):
        return 0.0 if base == head else 1.0
    width = max(len(base), len(head))
    if width == 0:
        return 0.0
    mismatches = sum(
        1
        for index in range(width)
        if (base[index] if index < len(base) else None)
        != (head[index] if index < len(head) else None)
    )
    return mismatches / width


def _raw_distance(bundle: ObservationBundle) -> float:
    """Provide a deterministic temporary ranking while coordinate ascent is in flight."""
    observable_ids = set(bundle.base) & set(bundle.head)
    return sum(_observable_distance(bundle, observable_id) for observable_id in observable_ids)


def _point_key(point: dict[str, Any]) -> str:
    """Canonical cache identity for a typed knob position."""
    return json.dumps(point, sort_keys=True, separators=(",", ":"))


def _initial_step(knob: Knob) -> float | int:
    """Choose a bounded first coordinate step, then let misses halve it."""
    if isinstance(knob.domain, NumericDomain):
        return max(knob.domain.step, (knob.domain.max - knob.domain.min) / 4)
    return 1


def _halve_step(knob: Knob, step: float | int) -> float | int:
    """Halve a numeric ascent step without falling below the declared resolution."""
    if isinstance(knob.domain, NumericDomain):
        return max(knob.domain.step, step / 2)
    return step


def _neighbor(point: dict[str, Any], knob: Knob, direction: int, step: float | int) -> dict[str, Any]:
    """Move one coordinate while respecting scalar, enum, integer, and boolean domains."""
    candidate = dict(point)
    if isinstance(knob.domain, NumericDomain):
        try:
            current = float(point[knob.id])
        except (TypeError, ValueError):
            current = knob.domain.min if direction > 0 else knob.domain.max
        value = current + direction * float(step)
        value = min(knob.domain.max, max(knob.domain.min, value))
        value = round((value - knob.domain.min) / knob.domain.step) * knob.domain.step + knob.domain.min
        candidate[knob.id] = int(round(value)) if knob.type == "integer" else float(value)
        return candidate
    if knob.type == "boolean":
        candidate[knob.id] = not bool(point[knob.id])
        return candidate
    values = knob.domain.values
    try:
        index = values.index(str(point[knob.id]))
    except ValueError:
        # A malformed Phase-1 enum/null sample reaches the nearest declared
        # value before ascent continues; it must not crash the bounded search.
        index = -1 if direction > 0 else 0
    candidate[knob.id] = values[(index + direction) % len(values)]
    return candidate


def _caption(bundle: ObservationBundle, observables: list[Observable]) -> str:
    """Describe the measured maximum plainly, without asserting a real-world story."""
    observable = observables[0]
    base = bundle.base[observable.id]
    head = bundle.head[observable.id]
    if observable.render not in _NUMERIC_RENDERS:
        return f"{observable.label}: base={base!r}, head={head!r}."
    if isinstance(base, (int, float)) and isinstance(head, (int, float)):
        if observable.id == "admitted":
            if base == 0:
                return f"Head admits {head:g} more requests than base ({head:g} vs 0)."
            return f"Head admits {head / base:.1f}× as many requests ({head:g} vs {base:g})."
        if base == 0:
            return f"Head {observable.label}: {head:g} versus base 0."
        if head == 0:
            return f"Base {observable.label}: {base:g} versus head 0."
        if base > head:
            return f"Base {observable.label} is {base / head:.1f}× head ({base:g} vs {head:g})."
        return f"Head {observable.label} is {head / base:.1f}× base ({head:g} vs {base:g})."
    return f"{observable.label}: base={base!r}, head={head!r}."


def _unsafe_predicate_description(predicate: UnsafePredicate | None) -> str:
    """Render the declared condition exactly enough for an honest no-result finding."""
    if predicate is None:
        return "(missing predicate)"
    target = (
        predicate.target.id
        if isinstance(predicate.target, UnsafeKnobTarget)
        else repr(predicate.target.value)
    )
    symbols = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "==", "neq": "!="}
    return f"{predicate.observableId} {symbols[predicate.operator]} {target}"


def _unsafe_caption(
    bundle: ObservationBundle,
    point: dict[str, Any],
    predicate: UnsafePredicate | None,
) -> str:
    """State the reached condition and version without recasting it as a divergence."""
    if predicate is None:
        return "An unsafe state was reached."
    target = (
        point.get(predicate.target.id)
        if isinstance(predicate.target, UnsafeKnobTarget)
        else predicate.target.value
    )
    symbols = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "==", "neq": "!="}
    versions = (
        (predicate.versions,)
        if predicate.versions in {"base", "head"}
        else ("base", "head")
    )
    for version in versions:
        observations = bundle.base if version == "base" else bundle.head
        value = observations.get(predicate.observableId)
        if _compare_unsafe_value(value, predicate.operator, target):
            return (
                f"Unsafe state reached in {version}: {predicate.observableId}={value!r} "
                f"{symbols[predicate.operator]} {target!r}."
            )
    return "An unsafe state was reached."


def _preset(
    entry: CacheEntry,
    divergence: float,
    objective: SearchObjective = "max_divergence",
) -> NamedPosition:
    """Create a measured-only cached preset label required by the spec."""
    values = ", ".join(f"{key}={value}" for key, value in entry.position.root.items())
    return NamedPosition(
        position=entry.position,
        label=(
            f"{values} — unsafe state reached"
            if objective == "reach_unsafe_state" and divergence >= 1.0
            else f"{values} — {divergence:.2f} normalized divergence"
        ),
        divergence=min(1.0, divergence),
    )


def _varied_knobs(knobs: list[Knob]) -> str:
    """Name the explored controls in the no-divergence finding."""
    return ", ".join(knob.label for knob in knobs)


def _write_source(runtime: SandboxRuntime, sandbox_id: str, path: str, source: str) -> None:
    """Stage an independently supplied source or generated harness through the port."""
    code = (
        "from pathlib import Path\n"
        f"target = Path({path!r})\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        f"target.write_text({source!r})"
    )
    result = runtime.run_code(sandbox_id, code)
    if result["exit_code"] != 0:
        raise SandboxExecutionError(f"Could not stage {path}: {result['stderr']}")


__all__ = [
    "Adversary",
    "AdversaryResult",
    "CacheEntry",
    "EXPLORE_POINTS",
    "MAX_EVALUATIONS",
    "NO_DIVERGENCE_EPSILON",
    "ObservationBundle",
    "SearchObjective",
    "SearchAccounting",
    "SamplerPrior",
    "TracePoint",
    "boundary_weighted_sobol_points",
]
