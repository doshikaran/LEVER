"""Deterministic cached search for the most behaviorally divergent knob position."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from domain.fidelity_verifier import FidelityVerification, sobol_points
from domain.harness_engineer import HarnessPair
from domain.ports import SandboxRuntime
from domain.schema import (
    InteractionSpec,
    Knob,
    KnobPosition,
    NamedPosition,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    SurpriseMarker,
)


EXPLORE_M = 6
EXPLORE_POINTS = 2**EXPLORE_M
TOP_SEEDS = 8
EXPLOIT_EVALUATIONS_PER_SEED = 8
MAX_EVALUATIONS = EXPLORE_POINTS + TOP_SEEDS * EXPLOIT_EVALUATIONS_PER_SEED
NO_DIVERGENCE_EPSILON = 0.02

EvaluationRunner = Callable[[dict[str, Any]], "ObservationBundle"]
BatchEvaluationRunner = Callable[[list[dict[str, Any]]], list["ObservationBundle"]]


@dataclass(frozen=True)
class ObservationBundle:
    """The A/B observable values for one concrete knob position."""

    base: dict[str, Any]
    head: dict[str, Any]


@dataclass(frozen=True)
class CacheEntry:
    """One retained knob position and its reusable A/B observation bundle."""

    position: KnobPosition
    observations: ObservationBundle


@dataclass(frozen=True)
class TracePoint:
    """A cached search point with its final range-normalized divergence."""

    position: KnobPosition
    divergence: float


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
    ) -> AdversaryResult:
        """Find and retain the strongest A/B divergence after successful fidelity."""
        if fidelity.report.verdict != "verified":
            raise ValueError("Adversary requires a verified FidelityReport")

        runner = self._evaluation_runner
        if runner is None:
            if base_source is None or head_source is None:
                raise ValueError("Sandbox search requires the independently checked base/head source")
            runner = self._sandbox_runner(
                sandbox_id, harness_pair, base_source, head_source
            )

        explore_points = sobol_points(partial_spec.knobs, m=EXPLORE_M)
        explore_keys = {_point_key(point) for point in explore_points}
        cache: dict[str, CacheEntry] = {}
        for observation in fidelity.observations:
            if _point_key(observation.point) in explore_keys:
                self._store(
                    cache,
                    observation.point,
                    ObservationBundle(observation.base, observation.head),
                )

        missing_explore_points = [
            point for point in explore_points if _point_key(point) not in cache
        ]
        # These calls are independent; reuse eliminates them for the normal verified path.
        with ThreadPoolExecutor(max_workers=min(32, len(missing_explore_points) or 1)) as pool:
            evaluated = zip(missing_explore_points, pool.map(runner, missing_explore_points))
            for point, observations in evaluated:
                self._store(cache, point, observations)

        explore_keys = {_point_key(point) for point in explore_points}
        exploit_attempted = 0
        exploit_executed_new = 0
        exploit_collisions_with_explore = 0
        exploit_collisions_with_exploit = 0

        divergences = _divergences(cache, partial_spec.observables)
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
                explore_keys,
                batch_runner,
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
                    runner,
                    explore_keys,
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

        divergences = _divergences(cache, partial_spec.observables)
        trace = tuple(
            TracePoint(entry.position, divergences[key])
            for key, entry in cache.items()
        )
        best_key = max(divergences, key=divergences.get)
        best = cache[best_key]
        best_divergence = divergences[best_key]
        if best_divergence < NO_DIVERGENCE_EPSILON:
            return AdversaryResult(
                initial_position=None,
                surprise_marker=None,
                presets=(),
                search_trace=trace,
                cache=tuple(cache.values()),
                no_divergence=True,
                reason=(
                    "No normalized divergence reached 0.02 after varying "
                    + _varied_knobs(partial_spec.knobs)
                    + "."
                ),
                accounting=search_accounting,
            )

        position = best.position
        marker = SurpriseMarker(
            position=position,
            divergence=min(1.0, best_divergence),
            caption=_caption(best.observations, partial_spec.observables),
        )
        presets = tuple(
            _preset(cache[key], divergences[key])
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
        )

    def _coordinate_ascent(
        self,
        cache: dict[str, CacheEntry],
        seed: dict[str, Any],
        knobs: list[Knob],
        observables: list[Observable],
        runner: EvaluationRunner,
        explore_keys: set[str],
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
            self._evaluate(cache, candidate, runner)
            divergences = _divergences(cache, observables)
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
        explore_keys: set[str],
        evaluate_many: BatchEvaluationRunner,
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

            divergences = _divergences(cache, observables)
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
    ) -> ObservationBundle:
        """Retain every actual evaluation and never rerun an already cached position."""
        key = _point_key(point)
        if key not in cache:
            if len(cache) >= MAX_EVALUATIONS:
                raise RuntimeError("Adversary exceeded its 128-evaluation hard cap")
            self._store(cache, point, runner(point))
        return cache[key].observations

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
        _write_source(self._runtime, sandbox_id, harness_pair.harness_a.entry_module, base_source)
        _write_source(self._runtime, sandbox_id, harness_pair.harness_b.entry_module, head_source)
        _write_source(self._runtime, sandbox_id, base_harness_path, harness_pair.harness_a.source)
        _write_source(self._runtime, sandbox_id, head_harness_path, harness_pair.harness_b.source)

        def run(point: dict[str, Any]) -> ObservationBundle:
            code = f"""\
import json
import runpy

point = json.loads({json.dumps(json.dumps(point))})
base = runpy.run_path({base_harness_path!r})["run"](point, 0)["observations"]
head = runpy.run_path({head_harness_path!r})["run"](point, 0)["observations"]
print(json.dumps({{"base": base, "head": head}}, sort_keys=True))
"""
            result = self._runtime.run_code(sandbox_id, code)
            if result["exit_code"] != 0:
                raise RuntimeError(f"Adversary harness execution failed: {result['stderr']}")
            payload = json.loads(result["stdout"])
            return ObservationBundle(base=payload["base"], head=payload["head"])

        def run_many(points: list[dict[str, Any]]) -> list[ObservationBundle]:
            """Execute a complete ascent round inside the already-running sandbox."""
            code = f"""\
import json
import runpy

points = json.loads({json.dumps(json.dumps(points))})

def observations(path, point):
    return runpy.run_path(path)["run"](point, 0)["observations"]

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
                raise RuntimeError(f"Adversary harness batch failed: {result['stderr']}")
            payload = json.loads(result["stdout"])
            return [
                ObservationBundle(base=item["base"], head=item["head"])
                for item in payload
            ]

        setattr(run, "evaluate_many", run_many)
        return run


def _divergences(
    cache: dict[str, CacheEntry], observables: list[Observable]
) -> dict[str, float]:
    """Compute D(x) as mean per-observable distance normalized by observed range."""
    if not cache:
        return {}
    if not observables:
        # Coordinate ascent compares cached raw differences while preserving its caller's ranges.
        return {
            key: _raw_distance(entry.observations)
            for key, entry in cache.items()
        }
    ranges = {
        observable.id: _observed_range(cache.values(), observable.id)
        for observable in observables
    }
    return {
        key: sum(
            _observable_distance(entry.observations, observable.id) / ranges[observable.id]
            if ranges[observable.id] > 0
            else 0.0
            for observable in observables
        )
        / len(observables)
        for key, entry in cache.items()
    }


def _observed_range(entries: Any, observable_id: str) -> float:
    """Measure a numeric observable's range across all cached base/head values."""
    values = []
    for entry in entries:
        for version in (entry.observations.base, entry.observations.head):
            value = version[observable_id]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
    return max(values) - min(values) if values else 0.0


def _observable_distance(bundle: ObservationBundle, observable_id: str) -> float:
    """Return numeric absolute distance or categorical equality distance."""
    base = bundle.base[observable_id]
    head = bundle.head[observable_id]
    if isinstance(base, (int, float)) and isinstance(head, (int, float)):
        return abs(float(head) - float(base))
    return 0.0 if base == head else 1.0


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
        value = float(point[knob.id]) + direction * float(step)
        value = min(knob.domain.max, max(knob.domain.min, value))
        value = round((value - knob.domain.min) / knob.domain.step) * knob.domain.step + knob.domain.min
        candidate[knob.id] = int(round(value)) if knob.type == "integer" else float(value)
        return candidate
    if knob.type == "boolean":
        candidate[knob.id] = not bool(point[knob.id])
        return candidate
    values = knob.domain.values
    index = values.index(str(point[knob.id]))
    candidate[knob.id] = values[(index + direction) % len(values)]
    return candidate


def _caption(bundle: ObservationBundle, observables: list[Observable]) -> str:
    """Describe the measured maximum plainly, without asserting a real-world story."""
    observable = observables[0]
    base = bundle.base[observable.id]
    head = bundle.head[observable.id]
    if isinstance(base, (int, float)) and isinstance(head, (int, float)):
        if base == 0:
            return f"Head admits {head:g} more requests than base ({head:g} vs 0)."
        return f"Head admits {head / base:.1f}× as many requests ({head:g} vs {base:g})."
    return f"{observable.label}: base={base!r}, head={head!r}."


def _preset(entry: CacheEntry, divergence: float) -> NamedPosition:
    """Create a measured-only cached preset label required by the spec."""
    values = ", ".join(f"{key}={value}" for key, value in entry.position.root.items())
    return NamedPosition(
        position=entry.position,
        label=f"{values} — {divergence:.2f} normalized divergence",
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
        raise RuntimeError(f"Could not stage {path}: {result['stderr']}")


__all__ = [
    "Adversary",
    "AdversaryResult",
    "CacheEntry",
    "EXPLORE_POINTS",
    "MAX_EVALUATIONS",
    "NO_DIVERGENCE_EPSILON",
    "ObservationBundle",
    "SearchAccounting",
    "TracePoint",
]
