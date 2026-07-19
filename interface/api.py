"""HTTP/WebSocket adapter for asynchronous analyses with a durable session ledger."""

import asyncio
import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from domain import orchestrator
from domain.adversary import AdversaryResult, CacheEntry
from domain.harness_engineer import HarnessEngineer
from domain.orchestrator import DegradeResult, GracefulDegradation
from domain.ports import LLMClient, Repository, SandboxRuntime
from domain.schema import InteractionSpec, KnobPosition, KnobValue, PartialInteractionSpec
from domain.scout import scout
from domain.synthesizer import synthesize
from infra.llm.openai_adapter import OpenAIAdapter
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser
from infra.persistence.sqlite_adapter import SQLiteRepository
from infra.sandbox.e2b_adapter import E2BSandboxRuntime


DEFAULT_MODEL = os.getenv("LEVER_MODEL", "gpt-5.6-sol")
DEFAULT_REASONING_EFFORT = os.getenv("LEVER_REASONING_EFFORT", "high")
DEFAULT_SESSION_DATABASE_PATH = Path(
    os.getenv("LEVER_SESSION_DATABASE", "data/lever-sessions.sqlite3")
)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
HERO_FIXTURES: dict[str, tuple[Path, Path]] = {
    "hero1": (
        _PROJECT_ROOT / "fixtures/hero1/base.py",
        _PROJECT_ROOT / "fixtures/hero1/head.py",
    ),
}

ProgressCallback = Callable[[str, str], None]
AdversaryCallback = Callable[[AdversaryResult], None]
PipelineRunner = Callable[
    [str, str, SandboxRuntime, LLMClient, str, str, ProgressCallback, AdversaryCallback],
    InteractionSpec | DegradeResult,
]
EvaluationRunner = Callable[
    [Path, Path, InteractionSpec, KnobPosition, SandboxRuntime], dict[str, dict[str, Any]],
]


class DiffRequest(BaseModel):
    """The two local source paths that identify one requested code diff."""

    base_file_path: str
    head_file_path: str
    reference_file_path: str | None = None


class RawDiffRequest(BaseModel):
    """A context-free raw diff that must degrade before static analysis begins."""

    diff: str = Field(min_length=1)


class DiffAccepted(BaseModel):
    """The immediate response returned before asynchronous analysis begins."""

    changeId: str


class EvaluationRequest(BaseModel):
    """A post-pipeline request for one exact, uncached knob position."""

    type: str
    requestId: str
    position: dict[str, KnobValue]


@dataclass
class _RunState:
    """One ephemeral run's replayable progress messages and terminal payload."""

    change_id: str
    base_path: Path
    head_path: Path
    events: list[dict[str, Any]] = field(default_factory=list)
    position_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    spec: InteractionSpec | None = None
    completed: bool = False
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None

    def add_progress(self, stage: str, message: str) -> None:
        """Append exactly one completed-stage message in pipeline order."""
        self.events.append({"type": "progress", "stage": stage, "message": message})
        self.wake.set()

    def set_adversary_result(self, result: AdversaryResult) -> None:
        """Store every retained KnobPosition → ObservationBundle for client lookup."""
        self.position_cache = _cache_from_adversary(result)

    def finish(self, payload: dict[str, Any]) -> None:
        """Record the one terminal message and wake every waiting websocket."""
        self.events.append(payload)
        self.completed = True
        self.wake.set()


def create_app(
    *,
    runtime_factory: Callable[[], SandboxRuntime] | None = None,
    llm_factory: Callable[[str, str], LLMClient] | None = None,
    pipeline_runner: PipelineRunner | None = None,
    evaluation_runner: EvaluationRunner | None = None,
    repository: Repository | None = None,
    database_path: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> FastAPI:
    """Create an API app whose only retained state is the current process's runs."""
    runtime_factory = runtime_factory or E2BSandboxRuntime
    llm_factory = llm_factory or _openai_client
    pipeline_runner = pipeline_runner or _run_pipeline_with_callbacks
    evaluation_runner = evaluation_runner or _evaluate_position
    repository = repository or SQLiteRepository(database_path or DEFAULT_SESSION_DATABASE_PATH)
    app = FastAPI(title="Lever interface")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["POST"],
        allow_headers=["content-type"],
    )
    runs: dict[str, _RunState] = {}
    app.state.runs = runs
    app.state.repository = repository

    @app.post("/diffs", response_model=DiffAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def create_diff(request: DiffRequest) -> DiffAccepted:
        """Accept a diff and schedule the full blocking pipeline without delaying HTTP."""
        base_path, head_path = _validated_paths(request)
        change_id = _request_change_id(base_path, head_path)
        existing = runs.get(change_id)
        if existing is None:
            state = _RunState(
                change_id=change_id,
                base_path=base_path,
                head_path=head_path,
            )
            runs[change_id] = state
            if _executable_reference_path(request, base_path, head_path) is None:
                _persist_terminal(
                    state,
                    repository,
                    _terminal_payload(
                        change_id,
                        GracefulDegradation(
                            "No executable reference path or test suite was found; Lever "
                            "cannot independently compare harness output to real behavior.",
                            plain_explanation=(
                                "The repository has no executable reference for this behavior. "
                                "Manually test the changed path in its owning application before "
                                "trusting any comparison."
                            ),
                        ),
                        {},
                    ),
                )
            else:
                state.task = asyncio.create_task(
                    _run_in_background(
                        state,
                        base_path,
                        head_path,
                        runtime_factory,
                        llm_factory,
                        pipeline_runner,
                        repository,
                        model,
                        reasoning_effort,
                    ),
                    name=f"lever-pipeline-{change_id[:12]}",
                )
        return DiffAccepted(changeId=change_id)

    @app.post("/diffs/raw", response_model=DiffAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def create_raw_diff(request: RawDiffRequest) -> DiffAccepted:
        """Persist the required no-repository-context degradation without running a pipeline."""
        change_id = _raw_diff_change_id(request.diff)
        if change_id not in runs:
            state = _RunState(
                change_id=change_id,
                base_path=Path("<raw-diff>"),
                head_path=Path("<raw-diff>"),
            )
            runs[change_id] = state
            _persist_terminal(
                state,
                repository,
                _terminal_payload(
                    change_id,
                    GracefulDegradation(
                        "No repository context — cannot verify a raw diff against an executable "
                        "reference path.",
                        plain_explanation=(
                            "This diff may change runtime behavior, but without a repository Lever "
                            "cannot inspect dependencies or run the real code. Manually test the "
                            "changed branch in its application."
                        ),
                    ),
                    {},
                ),
            )
        return DiffAccepted(changeId=change_id)

    @app.get("/diffs/{change_id}")
    async def get_diff(change_id: str) -> dict[str, Any]:
        """Return one persisted terminal result without recreating its pipeline run."""
        persisted = repository.load(change_id)
        if persisted is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown changeId.")
        return persisted

    @app.post("/heroes/{hero_id}/run")
    async def run_hero(hero_id: str, force: bool = False) -> dict[str, Any]:
        """Return a frozen hero result, regenerating only for its first or forced run."""
        fixture_paths = HERO_FIXTURES.get(hero_id)
        if fixture_paths is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown heroId.")
        hero_key = f"hero:{hero_id}"
        if not force:
            frozen = repository.load(hero_key)
            if frozen is not None:
                return frozen

        payload = await asyncio.to_thread(
            _run_hero_pipeline,
            hero_key,
            fixture_paths,
            runtime_factory,
            llm_factory,
            pipeline_runner,
            model,
            reasoning_effort,
        )
        repository.save(hero_key, payload)
        return payload

    @app.websocket("/ws/{change_id}")
    async def diff_events(websocket: WebSocket, change_id: str) -> None:
        """Stream pipeline stages, then serve on-demand uncached-position evaluations."""
        await websocket.accept()
        state = runs.get(change_id)
        if state is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        cursor = 0
        try:
            while True:
                pending = state.events[cursor:]
                if pending:
                    cursor += len(pending)
                    for event in pending:
                        await websocket.send_json(event)
                    continue
                if state.completed:
                    await _serve_evaluations(websocket, state, runtime_factory, evaluation_runner)
                    return

                # Avoid missing an event that arrives between observing the
                # queue and awaiting the notification.
                state.wake.clear()
                if cursor < len(state.events) or state.completed:
                    continue
                await state.wake.wait()
        except WebSocketDisconnect:
            return

    return app


async def _run_in_background(
    state: _RunState,
    base_path: Path,
    head_path: Path,
    runtime_factory: Callable[[], SandboxRuntime],
    llm_factory: Callable[[str, str], LLMClient],
    pipeline_runner: PipelineRunner,
    repository: Repository,
    model: str,
    reasoning_effort: str,
) -> None:
    """Run blocking analysis off-loop while scheduling its callbacks onto this loop."""
    loop = asyncio.get_running_loop()

    def on_progress(stage: str, message: str) -> None:
        loop.call_soon_threadsafe(state.add_progress, stage, message)

    def on_adversary(result: AdversaryResult) -> None:
        loop.call_soon_threadsafe(state.set_adversary_result, result)

    def invoke() -> InteractionSpec | DegradeResult:
        return pipeline_runner(
            str(base_path),
            str(head_path),
            runtime_factory(),
            llm_factory(model, reasoning_effort),
            model,
            reasoning_effort,
            on_progress,
            on_adversary,
        )

    try:
        result = await asyncio.to_thread(invoke)
    except Exception as error:
        _persist_terminal(
            state,
            repository,
            {
                "type": "error",
                "changeId": state.change_id,
                "error": f"{type(error).__name__}: {error}",
            },
        )
        return

    if isinstance(result, InteractionSpec):
        state.spec = result
        _persist_terminal(
            state,
            repository,
            _terminal_payload(state.change_id, result, state.position_cache),
        )
        return

    _persist_terminal(
        state,
        repository,
        _terminal_payload(state.change_id, result, state.position_cache),
    )


def _persist_terminal(
    state: _RunState, repository: Repository, payload: dict[str, Any]
) -> None:
    """Durably write the permalink payload before reporting it to websocket clients."""
    repository.save(state.change_id, payload)
    state.finish(payload)


def _terminal_payload(
    change_id: str,
    result: InteractionSpec | DegradeResult,
    position_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Serialize every terminal state into one persistence and presentation payload."""
    if isinstance(result, InteractionSpec):
        return {
            "type": "complete",
            "changeId": change_id,
            "widgetConfig": synthesize(result).model_dump(mode="json"),
            "positionCache": position_cache,
            "interactionSpec": result.model_dump(mode="json"),
        }
    return {
        "type": result.kind,
        "changeId": change_id,
        "degradeReason": result.reason,
        "plainExplanation": result.plain_explanation or _default_plain_explanation(result),
        "divergenceReport": list(result.divergence_report),
        "outcome": asdict(result),
        "positionCache": position_cache,
    }


def _default_plain_explanation(result: DegradeResult) -> str:
    """Supply an honest fallback when an early deterministic gate has no Delta thesis."""
    if result.kind == "unscopable":
        return "This change needs a live framework object, so manually test it through that framework boundary."
    if result.kind == "skipped":
        return "Lever found no modeled runtime behavior to simulate; review the source change directly."
    if result.kind == "inert":
        return "The modeled inputs did not reveal a behavioral difference; manually test the boundary case you care about."
    return "Lever could not make a faithful model, so manually test the changed path in the real application."


def _cache_from_adversary(result: AdversaryResult) -> dict[str, dict[str, Any]]:
    """Convert the retained search cache into the JSON payload served to clients."""
    return {
        _position_key(entry): {
            "base": entry.observations.base,
            "head": entry.observations.head,
        }
        for entry in result.cache
    }


def _run_hero_pipeline(
    hero_key: str,
    fixture_paths: tuple[Path, Path],
    runtime_factory: Callable[[], SandboxRuntime],
    llm_factory: Callable[[str, str], LLMClient],
    pipeline_runner: PipelineRunner,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    """Run one pinned hero synchronously so its first response is the frozen artifact."""
    position_cache: dict[str, dict[str, Any]] = {}

    def collect_adversary(result: AdversaryResult) -> None:
        position_cache.update(_cache_from_adversary(result))

    result = pipeline_runner(
        str(fixture_paths[0]),
        str(fixture_paths[1]),
        runtime_factory(),
        llm_factory(model, reasoning_effort),
        model,
        reasoning_effort,
        lambda _stage, _message: None,
        collect_adversary,
    )
    return _terminal_payload(hero_key, result, position_cache)


async def _serve_evaluations(
    websocket: WebSocket,
    state: _RunState,
    runtime_factory: Callable[[], SandboxRuntime],
    evaluation_runner: EvaluationRunner,
) -> None:
    """Keep a completed run's socket open for explicit cache-miss evaluations."""
    while True:
        try:
            raw_request = await websocket.receive_json()
            request = EvaluationRequest.model_validate(raw_request)
        except WebSocketDisconnect:
            return
        except Exception as error:
            await websocket.send_json({"type": "evaluation_error", "error": str(error)})
            continue

        if request.type != "evaluate":
            await websocket.send_json(
                {
                    "type": "evaluation_error",
                    "requestId": request.requestId,
                    "error": "Unsupported WebSocket message type.",
                }
            )
            continue

        try:
            position = _validated_position(state.spec, request.position)
            key = _position_key(position)
            observations = state.position_cache.get(key)
            source = "cache"
            if observations is None:
                if state.spec is None:
                    raise ValueError("The completed run has no InteractionSpec to evaluate.")
                observations = await asyncio.to_thread(
                    evaluation_runner,
                    state.base_path,
                    state.head_path,
                    state.spec,
                    position,
                    runtime_factory(),
                )
                state.position_cache[key] = observations
                source = "fresh"
            await websocket.send_json(
                {
                    "type": "evaluation",
                    "requestId": request.requestId,
                    "positionKey": key,
                    "observations": observations,
                    "source": source,
                }
            )
        except Exception as error:
            await websocket.send_json(
                {
                    "type": "evaluation_error",
                    "requestId": request.requestId,
                    "error": f"{type(error).__name__}: {error}",
                }
            )


def _run_pipeline_with_callbacks(
    base_file_path: str,
    head_file_path: str,
    sandbox: SandboxRuntime,
    llm: LLMClient,
    model: str,
    reasoning_effort: str,
    progress_callback: ProgressCallback,
    adversary_callback: AdversaryCallback,
) -> InteractionSpec | DegradeResult:
    """Adapt the public orchestrator to the interface runner's callback shape."""
    return orchestrator.run_pipeline(
        base_file_path,
        head_file_path,
        sandbox,
        llm,
        model,
        reasoning_effort,
        progress_callback=progress_callback,
        adversary_callback=adversary_callback,
    )


def _openai_client(model: str, reasoning_effort: str) -> LLMClient:
    """Construct the production LLM adapter only inside the background worker."""
    return OpenAIAdapter(model=model, reasoning_effort=reasoning_effort)


def _evaluate_position(
    base_path: Path,
    head_path: Path,
    spec: InteractionSpec,
    position: KnobPosition,
    runtime: SandboxRuntime,
) -> dict[str, dict[str, Any]]:
    """Evaluate both generated harnesses at one new position in a fresh real sandbox."""
    base_source = base_path.read_text()
    head_source = head_path.read_text()
    parser = TreeSitterPythonParser()
    scoped_change_set = scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
        str(base_path),
        str(head_path),
    )
    if scoped_change_set.entry_point is None:
        raise ValueError(scoped_change_set.reason or "Scout found no runnable entry point.")
    partial_spec = PartialInteractionSpec(
        thesis=spec.thesis,
        domainPack=spec.domainPack,
        knobs=spec.knobs,
        observables=spec.observables,
    )
    sandbox_id = runtime.create_sandbox("base")
    try:
        base_module = "/tmp/lever-interaction/base.py"
        head_module = "/tmp/lever-interaction/head.py"
        harness_pair = HarnessEngineer().generate(
            scoped_change_set,
            partial_spec,
            base_module,
            head_module,
        )
        _stage_source(runtime, sandbox_id, base_module, base_source)
        _stage_source(runtime, sandbox_id, head_module, head_source)
        _stage_source(runtime, sandbox_id, f"{base_module}.harness.py", harness_pair.harness_a.source)
        _stage_source(runtime, sandbox_id, f"{head_module}.harness.py", harness_pair.harness_b.source)
        return {
            "base": _run_harness(runtime, sandbox_id, f"{base_module}.harness.py", position.root),
            "head": _run_harness(runtime, sandbox_id, f"{head_module}.harness.py", position.root),
        }
    finally:
        runtime.kill_sandbox(sandbox_id)


def _stage_source(runtime: SandboxRuntime, sandbox_id: str, path: str, source: str) -> None:
    """Write one module or generated harness into the interaction sandbox."""
    code = (
        "from pathlib import Path\n"
        f"path = Path({path!r})\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        f"path.write_text({source!r})\n"
    )
    result = runtime.run_code(sandbox_id, code)
    if result["exit_code"] != 0:
        raise RuntimeError(f"Could not stage {path}: {result['stderr']}")


def _run_harness(
    runtime: SandboxRuntime,
    sandbox_id: str,
    harness_path: str,
    position: dict[str, KnobValue],
) -> dict[str, Any]:
    """Execute one generated harness and return only its observation bundle."""
    code = (
        "import json, runpy\n"
        f"namespace = runpy.run_path({harness_path!r})\n"
        f"position = json.loads({json.dumps(json.dumps(position))})\n"
        "print(json.dumps(namespace['run'](position, 0)['observations'], sort_keys=True))\n"
    )
    result = runtime.run_code(sandbox_id, code)
    if result["exit_code"] != 0:
        raise RuntimeError(f"Harness execution failed: {result['stderr']}")
    return json.loads(result["stdout"])


def _validated_paths(request: DiffRequest) -> tuple[Path, Path]:
    """Require two readable local files before admitting a background job."""
    base_path = Path(request.base_file_path).expanduser().resolve()
    head_path = Path(request.head_file_path).expanduser().resolve()
    missing = [str(path) for path in (base_path, head_path) if not path.is_file()]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"missingFilePaths": missing},
        )
    return base_path, head_path


def _executable_reference_path(
    request: DiffRequest, base_path: Path, head_path: Path
) -> Path | None:
    """Find an explicit or conventional executable test/reference path for the diff."""
    if request.reference_file_path is not None:
        candidate = Path(request.reference_file_path).expanduser().resolve()
        return candidate if candidate.is_file() else None

    test_directories = {
        base_path.parent / "tests",
        base_path.parent.parent / "tests",
        head_path.parent / "tests",
        head_path.parent.parent / "tests",
    }
    for directory in sorted(test_directories):
        # A repository may name its executable reference freely; a conventional
        # ``tests/`` directory containing Python code is enough to establish a
        # runnable independent path, rather than requiring a test_ prefix.
        if directory.is_dir() and any(directory.glob("*.py")):
            return directory
    return None


def _request_change_id(base_path: Path, head_path: Path) -> str:
    """Give the HTTP client a stable ID before Scout computes the scoped spec ID."""
    material = (
        str(base_path).encode("utf-8")
        + b"\0"
        + base_path.read_bytes()
        + b"\0"
        + str(head_path).encode("utf-8")
        + b"\0"
        + head_path.read_bytes()
    )
    return hashlib.sha256(material).hexdigest()


def _raw_diff_change_id(raw_diff: str) -> str:
    """Give a context-free raw diff a stable permalink ID without pretending it is runnable."""
    return hashlib.sha256(f"raw-diff\0{raw_diff}".encode("utf-8")).hexdigest()


def _validated_position(
    spec: InteractionSpec | None, raw_position: dict[str, KnobValue]
) -> KnobPosition:
    """Require exactly the completed spec's knob IDs before executing a request."""
    if spec is None:
        raise ValueError("This run did not produce an interactive spec.")
    expected_ids = {knob.id for knob in spec.knobs}
    actual_ids = set(raw_position)
    if actual_ids != expected_ids:
        raise ValueError(
            f"Position must contain exactly {sorted(expected_ids)}, got {sorted(actual_ids)}."
        )
    return KnobPosition(raw_position)


def _position_key(position: CacheEntry | KnobPosition) -> str:
    """SHA-256 hash the cross-language canonical form of a knob position."""
    raw_position = position.position.root if isinstance(position, CacheEntry) else position.root
    return hashlib.sha256(_canonical_position(raw_position).encode("utf-8")).hexdigest()


def _canonical_position(position: dict[str, KnobValue]) -> str:
    """Normalize scalar values identically to the browser before hashing a position."""
    def encode_value(value: KnobValue) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)):
                raise ValueError("Knob positions must contain finite numeric values.")
            return format(float(value), ".15g")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    return "{" + ",".join(
        f"{json.dumps(key, ensure_ascii=False)}:{encode_value(position[key])}"
        for key in sorted(position)
    ) + "}"


app = create_app()


__all__ = ["app", "create_app"]
