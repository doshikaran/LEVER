"""HTTP/WebSocket adapter for asynchronous analyses with a durable session ledger."""

import asyncio
import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from domain import orchestrator
from domain.adversary import Adversary, AdversaryResult, CacheEntry, TracePoint
from domain.fidelity_verifier import FidelityVerification
from domain.harness_engineer import HarnessEngineer
from domain.intake import CheckoutHandle, InvalidPullRequestUrl, ResolvedPullRequest
from domain.line_attribution import trace_attribution
from domain.orchestrator import DegradeResult, GracefulDegradation
from domain.ports import DualCheckout, LLMClient, PullRequestResolver, Repository, SandboxRuntime
from domain.pin_as_test import write_pinned_head_test
from domain.prospective import CandidateGenerationError, generate_candidate
from domain.schema import (
    InteractionSpec,
    AdversaryObjective,
    KnobPosition,
    KnobValue,
    PartialInteractionSpec,
    TraceAttribution,
    UnsafePredicate,
)
from domain.scout import scout
from domain.synthesizer import synthesize
from infra.checkout.dual_checkout import DualCheckoutError, GitDualCheckout
from infra.github.pr_resolver import GitHubPullRequestResolver, PullRequestResolveError
from infra.llm.openai_adapter import OpenAIAdapter
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser
from infra.persistence.sqlite_adapter import SQLiteRepository
from infra.sandbox.e2b_adapter import E2BSandboxRuntime


DEFAULT_MODEL = os.getenv("LEVER_MODEL", "gpt-5.6-sol")
DEFAULT_REASONING_EFFORT = os.getenv("LEVER_REASONING_EFFORT", "high")
DEFAULT_SESSION_DATABASE_PATH = Path(
    os.getenv("LEVER_SESSION_DATABASE", "data/lever-sessions.sqlite3")
)
DEFAULT_PROSPECTIVE_CANDIDATE_DIRECTORY = Path(
    os.getenv("LEVER_PROSPECTIVE_CANDIDATES", "data/prospective-candidates")
)
DEFAULT_CHECKOUT_ROOT = Path(
    os.getenv("LEVER_CHECKOUT_ROOT", "data/checkouts")
)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
HERO_FIXTURES: dict[str, tuple[Path, Path]] = {
    "hero1": (
        _PROJECT_ROOT / "fixtures/hero1/base.py",
        _PROJECT_ROOT / "fixtures/hero1/head.py",
    ),
    "hero2": (
        _PROJECT_ROOT / "fixtures/hero2/base.py",
        _PROJECT_ROOT / "fixtures/hero2/head.py",
    ),
    "hero3": (
        _PROJECT_ROOT / "fixtures/hero3/base.py",
        _PROJECT_ROOT / "fixtures/hero3/head.py",
    ),
    "hero4": (
        _PROJECT_ROOT / "fixtures/hero4/base.py",
        _PROJECT_ROOT / "fixtures/hero4/head.py",
    ),
    "state-workflow": (
        _PROJECT_ROOT / "fixtures/state_workflow/base.py",
        _PROJECT_ROOT / "fixtures/state_workflow/head.py",
    ),
    "wild-synth": (
        _PROJECT_ROOT / "fixtures/wild_synth/base.py",
        _PROJECT_ROOT / "fixtures/wild_synth/head.py",
    ),
}
DEMO_CATALOG: tuple[dict[str, str], ...] = (
    {
        "id": "hero1",
        "label": "Hero 1 · Rate limiter",
        "description": "Fixed window → sliding window with per-tenant burst.",
    },
    {
        "id": "hero2",
        "label": "Hero 2 · Retry jitter",
        "description": "Exponential backoff → full jitter (thundering herd).",
    },
    {
        "id": "hero3",
        "label": "Hero 3 · Permissions",
        "description": "Role table → attribute inheritance matrix.",
    },
    {
        "id": "hero4",
        "label": "Hero 4 · Decision tree",
        "description": "Flat discount checks → nested feature-flag paths.",
    },
    {
        "id": "state-workflow",
        "label": "State workflow",
        "description": "Order machine with a resubmit recovery path.",
    },
    {
        "id": "wild-synth",
        "label": "Wild synth",
        "description": "Unregistered plain callable — generative harness path.",
    },
    {
        "id": "compose-hero1",
        "label": "Compose 2×2",
        "description": "Hero 1 A×B composition with measured AB corner.",
    },
)

ProgressCallback = Callable[[str, str], None]
AdversaryCallback = Callable[[AdversaryResult], None]
SearchTraceCallback = Callable[[TracePoint], None]
PipelineRunner = Callable[
    [
        str,
        str,
        SandboxRuntime,
        LLMClient,
        str,
        str,
        ProgressCallback,
        AdversaryCallback,
        SearchTraceCallback,
    ],
    InteractionSpec | DegradeResult,
]
EvaluationRunner = Callable[
    [Path, Path, InteractionSpec, KnobPosition, SandboxRuntime], dict[str, Any],
]


class DiffRequest(BaseModel):
    """The two local source paths that identify one requested code diff."""

    base_file_path: str
    head_file_path: str
    reference_file_path: str | None = None


class RawDiffRequest(BaseModel):
    """A context-free raw diff that must degrade before static analysis begins."""

    diff: str = Field(min_length=1)


class ProspectiveRequest(BaseModel):
    """One plain-language hypothesis about a readable current Python module."""

    base_file_path: str
    hypothesis: str = Field(min_length=1, max_length=4_000)


class PullRequestIntakeRequest(BaseModel):
    """A GitHub pull request URL that Lever should resolve and dual-checkout."""

    url: str = Field(min_length=8, max_length=500)


class DiffAccepted(BaseModel):
    """The immediate response returned before asynchronous analysis begins."""

    changeId: str


class DemoInfo(BaseModel):
    """One curated demo chip exposed to the browser intake shell."""

    id: str
    label: str
    description: str


class SessionSummary(BaseModel):
    """One row in the durable session ledger for permalink browsing."""

    changeId: str
    outcome: str
    title: str
    savedAt: str | None = None
    fidelityBand: str | None = None
    speculative: bool = False


class EvaluationRequest(BaseModel):
    """A post-pipeline request for one exact, uncached knob position."""

    type: str
    requestId: str
    position: dict[str, KnobValue]


class ObjectiveSearchRequest(BaseModel):
    """A user-selected Adversary objective plus its optional unsafe predicate."""

    type: str
    requestId: str
    objective: AdversaryObjective
    unsafePredicate: UnsafePredicate | None = None


class PinRequest(BaseModel):
    """The already-evaluated position the user wants to preserve as a regression test."""

    position: dict[str, KnobValue]


class PinResponse(BaseModel):
    """The durable test path produced from the current cached observation."""

    testPath: str


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

    def add_search_trace_point(self, trace_point: TracePoint) -> None:
        """Queue one actual Adversary evaluation for immediate WebSocket delivery."""
        self.events.append(
            {
                "type": "search_trace",
                "tracePoint": {
                    "position": trace_point.position.root,
                    "divergence": trace_point.divergence,
                    "phase": trace_point.phase,
                },
            }
        )
        self.wake.set()

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
    pinned_tests_dir: str | Path | None = None,
    prospective_candidate_dir: str | Path | None = None,
    prospective_pipeline_runner: PipelineRunner | None = None,
    pr_resolver: PullRequestResolver | None = None,
    dual_checkout: DualCheckout | None = None,
    checkout_root: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> FastAPI:
    """Create an API app whose only retained state is the current process's runs."""
    runtime_factory = runtime_factory or E2BSandboxRuntime
    llm_factory = llm_factory or _openai_client
    injected_pipeline_runner = pipeline_runner
    pipeline_runner = pipeline_runner or _run_pipeline_with_callbacks
    evaluation_runner = evaluation_runner or _evaluate_position
    repository = repository or SQLiteRepository(database_path or DEFAULT_SESSION_DATABASE_PATH)
    pinned_tests_dir = Path(pinned_tests_dir or (_PROJECT_ROOT / "pinned_tests"))
    prospective_candidate_dir = Path(
        prospective_candidate_dir or DEFAULT_PROSPECTIVE_CANDIDATE_DIRECTORY
    )
    prospective_pipeline_runner = (
        prospective_pipeline_runner or _run_prospective_pipeline_with_callbacks
    )
    pr_resolver = pr_resolver or GitHubPullRequestResolver()
    dual_checkout = dual_checkout or GitDualCheckout()
    checkout_root = Path(checkout_root or DEFAULT_CHECKOUT_ROOT)
    app = FastAPI(title="Lever interface")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )
    runs: dict[str, _RunState] = {}
    app.state.runs = runs
    app.state.repository = repository
    app.state.pinned_tests_dir = pinned_tests_dir
    app.state.prospective_candidate_dir = prospective_candidate_dir
    app.state.checkout_root = checkout_root

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe for local demo scripts and deploy checks."""
        return {"status": "ok", "phase": "F"}

    @app.get("/demos", response_model=list[DemoInfo])
    async def list_demos() -> list[DemoInfo]:
        """Return curated hero chips so the browser never hardcodes fixture paths."""
        return [DemoInfo.model_validate(item) for item in DEMO_CATALOG]

    @app.get("/sessions", response_model=list[SessionSummary])
    async def list_sessions(limit: int = 40) -> list[SessionSummary]:
        """List recent persisted microworlds for the session ledger UI."""
        summaries: list[SessionSummary] = []
        for key in repository.list_keys(limit=max(1, min(limit, 200))):
            if key.startswith("hero:"):
                continue
            payload = repository.load(key)
            if not isinstance(payload, dict):
                continue
            summaries.append(_session_summary(key, payload))
        return summaries

    @app.get("/compose/demos/hero1")
    async def compose_hero1_demo() -> dict[str, Any]:
        """Return the measured Hero 1 2×2 composition (AB is executed, never inferred)."""
        try:
            return _hero1_composed_payload(runtime_factory())
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{type(error).__name__}: {error}",
            ) from error

    @app.post(
        "/demos/{demo_id}/run",
        response_model=DiffAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def run_demo(demo_id: str) -> DiffAccepted:
        """Start an async pipeline on a curated hero fixture (product demo path)."""
        if demo_id == "compose-hero1":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use GET /compose/demos/hero1 for the composed 2×2 demo.",
            )
        fixture_paths = HERO_FIXTURES.get(demo_id)
        if fixture_paths is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown demoId.")
        base_path, head_path = fixture_paths
        change_id = _request_change_id(base_path, head_path)
        existing = runs.get(change_id)
        if existing is None:
            state = _RunState(change_id=change_id, base_path=base_path, head_path=head_path)
            runs[change_id] = state
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
                name=f"lever-demo-{demo_id}-{change_id[:12]}",
            )
        return DiffAccepted(changeId=change_id)

    @app.post("/prs", response_model=DiffAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def create_pull_request(request: PullRequestIntakeRequest) -> DiffAccepted:
        """Resolve a GitHub PR, dual-checkout it, then reuse the existing pipeline."""
        try:
            resolved = pr_resolver.resolve(request.url.strip())
        except InvalidPullRequestUrl as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except PullRequestResolveError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(error),
            ) from error

        change_id = _pr_change_id(resolved)
        if change_id in runs:
            return DiffAccepted(changeId=change_id)

        work_root = checkout_root / change_id
        state = _RunState(
            change_id=change_id,
            base_path=work_root / "base",
            head_path=work_root / "head",
        )
        runs[change_id] = state
        state.task = asyncio.create_task(
            _run_pr_in_background(
                state,
                resolved,
                work_root,
                dual_checkout,
                runtime_factory,
                llm_factory,
                injected_pipeline_runner,
                repository,
                model,
                reasoning_effort,
            ),
            name=f"lever-pr-{change_id[:12]}",
        )
        return DiffAccepted(changeId=change_id)
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
            # Phase B: readable base/head files are enough. Direct reference programs are
            # generated beside the harness (registry or generative IR). A tests/ tree is
            # an optional boost, not a hard gate.
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
                    None,
                ),
            )
        return DiffAccepted(changeId=change_id)

    @app.post("/prospective", response_model=DiffAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def create_prospective(request: ProspectiveRequest) -> DiffAccepted:
        """Generate one candidate, then route current-vs-candidate through the normal pipeline."""
        base_path = Path(request.base_file_path).expanduser().resolve()
        if not base_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"missingFilePaths": [str(base_path)]},
            )
        change_id = _prospective_change_id(base_path, request.hypothesis)
        if change_id not in runs:
            state = _RunState(
                change_id=change_id,
                base_path=base_path,
                # This is replaced with the persisted generated candidate before
                # the existing pipeline starts.
                head_path=base_path,
            )
            runs[change_id] = state
            state.task = asyncio.create_task(
                _run_prospective_in_background(
                    state,
                    request.hypothesis,
                    runtime_factory,
                    llm_factory,
                    prospective_pipeline_runner,
                    repository,
                    prospective_candidate_dir,
                    model,
                    reasoning_effort,
                ),
                name=f"lever-prospective-{change_id[:12]}",
            )
        return DiffAccepted(changeId=change_id)

    @app.get("/diffs/{change_id}")
    async def get_diff(change_id: str) -> dict[str, Any]:
        """Return one persisted terminal result without recreating its pipeline run."""
        persisted = repository.load(change_id)
        if persisted is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown changeId.")
        return persisted

    @app.post("/diffs/{change_id}/pin", response_model=PinResponse)
    async def pin_current_position(change_id: str, request: PinRequest) -> PinResponse:
        """Write a head-regression test from a position already measured in this session."""
        state = _ensure_active_run(change_id, runs, repository)
        if state is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pinning requires a persisted or active Lever session for this changeId.",
            )
        if not state.completed or state.spec is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The interactive result is not ready to pin yet.",
            )
        position = _validated_position(state.spec, request.position)
        observation = state.position_cache.get(_position_key(position))
        if observation is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Evaluate this position before pinning it.",
            )
        head_observations = observation.get("head")
        if not isinstance(head_observations, dict):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The cached position has no head observation to pin.",
            )
        raw_trace = observation.get("trace")
        try:
            trace = TraceAttribution.model_validate(raw_trace) if raw_trace is not None else None
        except ValueError:
            trace = None
        test_path = write_pinned_head_test(
            pinned_tests_dir,
            state.base_path,
            state.head_path,
            state.spec,
            position,
            head_observations,
            trace.responsibleLine if trace is not None else None,
        )
        return PinResponse(testPath=str(test_path))

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
        state = _ensure_active_run(change_id, runs, repository)
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
                    await _serve_evaluations(
                        websocket,
                        state,
                        runtime_factory,
                        evaluation_runner,
                        repository,
                    )
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

    def on_search_trace(trace_point: TracePoint) -> None:
        loop.call_soon_threadsafe(state.add_search_trace_point, trace_point)

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
            on_search_trace,
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
            _terminal_payload(
                state.change_id,
                result,
                state.position_cache,
                _source_files(state.base_path, state.head_path),
            ),
        )
        return

    _persist_terminal(
        state,
        repository,
        _terminal_payload(
            state.change_id,
            result,
            state.position_cache,
            _source_files(state.base_path, state.head_path),
        ),
    )


async def _run_pr_in_background(
    state: _RunState,
    resolved: ResolvedPullRequest,
    work_root: Path,
    dual_checkout: DualCheckout,
    runtime_factory: Callable[[], SandboxRuntime],
    llm_factory: Callable[[str, str], LLMClient],
    injected_pipeline_runner: PipelineRunner | None,
    repository: Repository,
    model: str,
    reasoning_effort: str,
) -> None:
    """Materialize base/head trees, then reuse the standard async pipeline worker."""
    state.add_progress(
        "resolving",
        f"Resolved {resolved.owner}/{resolved.repo}#{resolved.number}: {resolved.title}",
    )
    try:
        checkout = await asyncio.to_thread(dual_checkout.materialize, resolved, work_root)
    except DualCheckoutError as error:
        _persist_terminal(
            state,
            repository,
            _terminal_payload(
                state.change_id,
                GracefulDegradation(
                    f"Dual checkout failed: {error}",
                    plain_explanation=(
                        "Lever could not materialize base and head trees for this pull request. "
                        "Confirm the repository is cloneable and retry."
                    ),
                ),
                {},
                None,
            ),
        )
        return

    if checkout.primary_base_file is None or checkout.primary_head_file is None:
        _persist_terminal(
            state,
            repository,
            _terminal_payload(
                state.change_id,
                GracefulDegradation(
                    checkout.selection_reason
                    or "No shared Python module was available on both base and head.",
                    plain_explanation=(
                        f"{resolved.title} changed files, but Lever Phase A needs one shared "
                        "Python module present on both sides of the PR before it can verify."
                    ),
                ),
                {},
                None,
            ),
        )
        return

    if checkout.selection_reason:
        state.add_progress("primary_pair", checkout.selection_reason)
    state.base_path = checkout.primary_base_file
    state.head_path = checkout.primary_head_file

    def pr_aware_runner(
        base_file_path: str,
        head_file_path: str,
        sandbox: SandboxRuntime,
        llm: LLMClient,
        runner_model: str,
        runner_effort: str,
        progress_callback: ProgressCallback,
        adversary_callback: AdversaryCallback,
        search_trace_callback: SearchTraceCallback,
    ) -> InteractionSpec | DegradeResult:
        """Tests inject a runner; production preserves PR SHAs in provenance."""
        if injected_pipeline_runner is not None:
            return injected_pipeline_runner(
                base_file_path,
                head_file_path,
                sandbox,
                llm,
                runner_model,
                runner_effort,
                progress_callback,
                adversary_callback,
                search_trace_callback,
            )
        return orchestrator.run_pipeline(
            base_file_path,
            head_file_path,
            sandbox,
            llm,
            runner_model,
            runner_effort,
            progress_callback=progress_callback,
            adversary_callback=adversary_callback,
            search_trace_callback=search_trace_callback,
            repo_provenance=orchestrator.RepoProvenance(
                repo_url=resolved.repo_url,
                base_sha=resolved.base_sha,
                head_sha=resolved.head_sha,
            ),
            files_touched_count=max(1, len(resolved.changed_files)),
        )

    await _run_in_background(
        state,
        state.base_path,
        state.head_path,
        runtime_factory,
        llm_factory,
        pr_aware_runner,
        repository,
        model,
        reasoning_effort,
    )


async def _run_prospective_in_background(
    state: _RunState,
    hypothesis: str,
    runtime_factory: Callable[[], SandboxRuntime],
    llm_factory: Callable[[str, str], LLMClient],
    pipeline_runner: PipelineRunner,
    repository: Repository,
    candidate_directory: Path,
    model: str,
    reasoning_effort: str,
) -> None:
    """Create one durable candidate, then reuse the existing pipeline unchanged."""
    loop = asyncio.get_running_loop()

    def on_progress(stage: str, message: str) -> None:
        loop.call_soon_threadsafe(state.add_progress, stage, message)

    def on_adversary(result: AdversaryResult) -> None:
        loop.call_soon_threadsafe(state.set_adversary_result, result)

    def on_search_trace(trace_point: TracePoint) -> None:
        loop.call_soon_threadsafe(state.add_search_trace_point, trace_point)

    def invoke() -> InteractionSpec | DegradeResult:
        llm = llm_factory(model, reasoning_effort)
        candidate = generate_candidate(llm, state.base_path.read_text(), hypothesis)
        candidate_directory.mkdir(parents=True, exist_ok=True)
        candidate_path = candidate_directory / f"{state.change_id}.py"
        candidate_path.write_text(candidate.source, encoding="utf-8")
        state.head_path = candidate_path
        result = pipeline_runner(
            str(state.base_path),
            str(candidate_path),
            runtime_factory(),
            llm,
            model,
            reasoning_effort,
            on_progress,
            on_adversary,
            on_search_trace,
        )
        # A custom test/adapter runner cannot accidentally erase the type-level
        # prospective discriminator or named-concept caveat before rendering or
        # persistence.
        if isinstance(result, InteractionSpec):
            return result.model_copy(
                update={
                    "provenance": result.provenance.model_copy(
                        update={
                            "speculative": True,
                            "hypothesisCaveat": candidate.hypothesis_caveat,
                        }
                    )
                }
            )
        return result

    try:
        result = await asyncio.to_thread(invoke)
    except CandidateGenerationError as error:
        _persist_terminal(
            state,
            repository,
            _terminal_payload(
                state.change_id,
                GracefulDegradation(
                    f"Prospective candidate generation failed: {error}",
                    plain_explanation=(
                        "Lever could not turn this hypothesis into executable code. "
                        "Refine the hypothesis or write the candidate explicitly."
                    ),
                ),
                {},
            ),
        )
        return
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
            _terminal_payload(
                state.change_id,
                result,
                state.position_cache,
                _source_files(state.base_path, state.head_path),
            ),
        )
        return

    _persist_terminal(
        state,
        repository,
        _terminal_payload(
            state.change_id,
            result,
            state.position_cache,
            _source_files(state.base_path, state.head_path)
            if state.head_path != state.base_path
            else None,
        ),
    )


def _persist_terminal(
    state: _RunState, repository: Repository, payload: dict[str, Any]
) -> None:
    """Durably write the permalink payload before reporting it to websocket clients."""
    repository.save(state.change_id, payload)
    state.finish(payload)


def _session_summary(change_id: str, payload: dict[str, Any]) -> SessionSummary:
    """Compress a persisted terminal payload into one ledger row."""
    outcome = str(payload.get("type") or payload.get("outcome") or "unknown")
    widget = payload.get("widgetConfig") if isinstance(payload.get("widgetConfig"), dict) else {}
    title = str(
        payload.get("title")
        or widget.get("thesis")
        or payload.get("degradeReason")
        or change_id
    )
    return SessionSummary(
        changeId=change_id,
        outcome=outcome,
        title=title[:160],
        savedAt=payload.get("savedAt") if isinstance(payload.get("savedAt"), str) else None,
        fidelityBand=widget.get("fidelityBand") if isinstance(widget.get("fidelityBand"), str) else None,
        speculative=bool(widget.get("speculative", False)),
    )


def _ensure_active_run(
    change_id: str,
    runs: dict[str, _RunState],
    repository: Repository,
) -> _RunState | None:
    """Return an in-memory run, rehydrating a completed permalink from SQLite when needed."""
    existing = runs.get(change_id)
    if existing is not None:
        return existing
    persisted = repository.load(change_id)
    if not isinstance(persisted, dict):
        return None
    rehydrated = _rehydrate_run(change_id, persisted)
    if rehydrated is None:
        return None
    runs[change_id] = rehydrated
    return rehydrated


def _rehydrate_run(change_id: str, payload: dict[str, Any]) -> _RunState | None:
    """Rebuild a completed _RunState so pin / evaluate / objective work after process restart."""
    source_files = payload.get("sourceFiles") if isinstance(payload.get("sourceFiles"), dict) else {}
    base_meta = source_files.get("base") if isinstance(source_files.get("base"), dict) else {}
    head_meta = source_files.get("head") if isinstance(source_files.get("head"), dict) else {}
    base_path = Path(
        str(payload.get("basePath") or base_meta.get("path") or f"<missing-base:{change_id}>")
    )
    head_path = Path(
        str(payload.get("headPath") or head_meta.get("path") or f"<missing-head:{change_id}>")
    )
    state = _RunState(change_id=change_id, base_path=base_path, head_path=head_path)
    cache = payload.get("positionCache")
    if isinstance(cache, dict):
        state.position_cache = {
            str(key): value for key, value in cache.items() if isinstance(value, dict)
        }
    if payload.get("type") == "complete":
        raw_spec = payload.get("interactionSpec")
        if not isinstance(raw_spec, dict):
            return None
        try:
            state.spec = InteractionSpec.model_validate(raw_spec)
        except Exception:
            return None
    state.events.append(payload)
    state.completed = True
    return state


def _terminal_payload(
    change_id: str,
    result: InteractionSpec | DegradeResult,
    position_cache: dict[str, dict[str, Any]],
    source_files: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Serialize every terminal state into one persistence and presentation payload."""
    saved_at = datetime.now(timezone.utc).isoformat()
    if isinstance(result, InteractionSpec):
        widget = synthesize(
            result,
            _synthesis_cache(position_cache),
        ).model_dump(mode="json")
        return {
            "type": "complete",
            "changeId": change_id,
            "widgetConfig": widget,
            "positionCache": position_cache,
            "sourceFiles": source_files or {},
            "interactionSpec": result.model_dump(mode="json"),
            "savedAt": saved_at,
            "title": result.thesis,
            "outcome": "complete",
            "basePath": str(source_files["base"]["path"]) if source_files and "base" in source_files else None,
            "headPath": str(source_files["head"]["path"]) if source_files and "head" in source_files else None,
        }
    return {
        "type": result.kind,
        "changeId": change_id,
        "degradeReason": result.reason,
        "plainExplanation": result.plain_explanation or _default_plain_explanation(result),
        "divergenceReport": list(result.divergence_report),
        # Preserve Delta's actual validated drafts for the Show-me diagnostic
        # expansion.  This makes a compatibility/instrumentation degradation
        # diagnosable from the persisted Session Ledger alone.
        "proposedSpecs": list(result.proposedSpecs),
        "outcome": asdict(result),
        "positionCache": position_cache,
        "savedAt": saved_at,
        "title": result.reason[:140],
        "manualTestRecipe": _manual_test_recipe(result),
        "staticNotes": _static_notes(result),
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


def _manual_test_recipe(result: DegradeResult) -> list[str]:
    """Build 1–3 concrete manual inputs from measured mismatches or a generic probe."""
    recipe: list[str] = []
    for entry in result.divergence_report[:3]:
        if not isinstance(entry, dict):
            continue
        position = entry.get("position")
        observable = entry.get("observable", "the observable")
        recipe.append(
            f"Run the changed entry point with input {json.dumps(position, sort_keys=True)} "
            f"and compare `{observable}` between base and head."
        )
    if not recipe:
        recipe.append(
            "Exercise the changed callable with one representative production input and "
            "compare base vs head side effects."
        )
    if result.kind == "unscopable":
        recipe.insert(
            0,
            "Drive the live framework request/session object through the changed view or handler.",
        )
    return recipe[:3]


def _static_notes(result: DegradeResult) -> list[str]:
    """Optional unverified static notes — always labeled as non-empirical."""
    notes: list[str] = [
        "UNVERIFIED STATIC NOTE: These notes are not a microworld and must not be treated as measured behavior.",
    ]
    if result.proposedSpecs:
        theses = [
            str(spec.get("thesis"))
            for spec in result.proposedSpecs
            if isinstance(spec, dict) and spec.get("thesis")
        ]
        if theses:
            notes.append(
                "Delta Analyst drafted "
                + "; ".join(f"“{thesis}”" for thesis in theses[:2])
                + " — draft only, never verified."
            )
    if result.kind == "unscopable":
        notes.append(
            "Scout classified the entry point as needing a live framework object."
        )
    return notes

def _cache_from_adversary(result: AdversaryResult) -> dict[str, dict[str, Any]]:
    """Convert the retained search cache into the JSON payload served to clients."""
    return {
        _position_key(entry): _cache_observation(entry)
        for entry in result.cache
    }


def _cache_observation(entry: CacheEntry) -> dict[str, Any]:
    """Serialize observations and their driver-collected source attribution."""
    payload: dict[str, Any] = {
        "position": entry.position.root,
        "base": entry.observations.base,
        "head": entry.observations.head,
    }
    if entry.observations.trace is not None:
        payload["trace"] = entry.observations.trace.model_dump(mode="json")
    return payload


def _synthesis_cache(position_cache: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapt serialized Adversary cache entries into Synthesizer's empirical tree input."""
    return [
        {
            "position": item.get("position"),
            "observations": {"base": item.get("base"), "head": item.get("head")},
        }
        for item in position_cache.values()
    ]


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
        lambda _trace_point: None,
    )
    return _terminal_payload(
        hero_key,
        result,
        position_cache,
        _source_files(fixture_paths[0], fixture_paths[1]),
    )


async def _serve_evaluations(
    websocket: WebSocket,
    state: _RunState,
    runtime_factory: Callable[[], SandboxRuntime],
    evaluation_runner: EvaluationRunner,
    repository: Repository,
) -> None:
    """Keep a completed run's socket open for explicit cache-miss evaluations."""
    while True:
        try:
            raw_request = await websocket.receive_json()
        except WebSocketDisconnect:
            return
        except Exception as error:
            await websocket.send_json({"type": "evaluation_error", "error": str(error)})
            continue

        request_type = raw_request.get("type") if isinstance(raw_request, dict) else None
        if request_type == "search_objective":
            await _serve_objective_search(
                websocket,
                state,
                runtime_factory,
                repository,
                raw_request,
            )
            continue
        if request_type != "evaluate":
            await websocket.send_json(
                {
                    "type": "evaluation_error",
                    "requestId": raw_request.get("requestId") if isinstance(raw_request, dict) else None,
                    "error": "Unsupported WebSocket message type.",
                }
            )
            continue

        try:
            request = EvaluationRequest.model_validate(raw_request)
        except Exception as error:
            await websocket.send_json({"type": "evaluation_error", "error": str(error)})
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
                # A cache-miss result is now part of the session ledger too.  Persist
                # it immediately so a permalink retains its empirical attribution.
                if state.spec is not None:
                    repository.save(
                        state.change_id,
                        _terminal_payload(
                            state.change_id,
                            state.spec,
                            state.position_cache,
                            _source_files(state.base_path, state.head_path),
                        ),
                    )
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


async def _serve_objective_search(
    websocket: WebSocket,
    state: _RunState,
    runtime_factory: Callable[[], SandboxRuntime],
    repository: Repository,
    raw_request: dict[str, Any],
) -> None:
    """Rerun only Adversary, streaming the newly selected objective's trace live."""
    try:
        request = ObjectiveSearchRequest.model_validate(raw_request)
        if request.objective == "reach_unsafe_state" and request.unsafePredicate is None:
            raise ValueError("reach_unsafe_state requires an unsafePredicate")
        if state.spec is None:
            raise ValueError("The completed run has no InteractionSpec to search.")
    except Exception as error:
        await websocket.send_json(
            {
                "type": "objective_error",
                "requestId": raw_request.get("requestId"),
                "error": f"{type(error).__name__}: {error}",
            }
        )
        return

    loop = asyncio.get_running_loop()
    trace_queue: asyncio.Queue[TracePoint] = asyncio.Queue()

    def on_trace(point: TracePoint) -> None:
        loop.call_soon_threadsafe(trace_queue.put_nowait, point)

    await websocket.send_json(
        {"type": "objective_started", "requestId": request.requestId, "objective": request.objective}
    )
    task = asyncio.create_task(
        asyncio.to_thread(
            _run_objective_search,
            state.base_path,
            state.head_path,
            state.spec,
            runtime_factory(),
            request.objective,
            request.unsafePredicate,
            on_trace,
        )
    )
    try:
        while not task.done():
            try:
                trace = await asyncio.wait_for(trace_queue.get(), timeout=0.05)
            except TimeoutError:
                continue
            await websocket.send_json(_trace_event(trace))
        result = await task
        while not trace_queue.empty():
            await websocket.send_json(_trace_event(trace_queue.get_nowait()))
    except Exception as error:
        await websocket.send_json(
            {
                "type": "objective_error",
                "requestId": request.requestId,
                "error": f"{type(error).__name__}: {error}",
            }
        )
        return

    # Retain these observations alongside the original successful search so a
    # security-search point is immediately reusable by the regular drag path.
    state.position_cache.update(_cache_from_adversary(result))
    repository.save(
        state.change_id,
        _terminal_payload(
            state.change_id,
            state.spec,
            state.position_cache,
            _source_files(state.base_path, state.head_path),
        ),
    )
    await websocket.send_json(
        {
            "type": "objective_result",
            "requestId": request.requestId,
            "objective": request.objective,
            "unsafePredicate": (
                request.unsafePredicate.model_dump(mode="json")
                if request.unsafePredicate is not None
                else None
            ),
            "noUnsafeState": result.no_divergence,
            "reason": result.reason,
            "surpriseMarker": (
                result.surprise_marker.model_dump(mode="json")
                if result.surprise_marker is not None
                else None
            ),
            "positionCache": state.position_cache,
        }
    )


def _trace_event(trace_point: TracePoint) -> dict[str, Any]:
    """Serialize one objective-search point in the existing Search Trace contract."""
    return {
        "type": "search_trace",
        "tracePoint": {
            "position": trace_point.position.root,
            "divergence": trace_point.divergence,
            "phase": trace_point.phase,
        },
    }


def _run_objective_search(
    base_path: Path,
    head_path: Path,
    spec: InteractionSpec,
    runtime: SandboxRuntime,
    objective: AdversaryObjective,
    unsafe_predicate: UnsafePredicate | None,
    trace_callback: SearchTraceCallback,
) -> AdversaryResult:
    """Reconstruct the executable pair and rerun Adversary without a new LLM/Fidelity pass."""
    base_source = base_path.read_text()
    head_source = head_path.read_text()
    parser = TreeSitterPythonParser()
    scope = scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
        str(base_path),
        str(head_path),
    )
    if scope.entry_point is None:
        raise ValueError(scope.reason or "Scout found no runnable entry point.")
    partial_spec = PartialInteractionSpec(
        thesis=spec.thesis,
        domainPack=spec.domainPack,
        knobs=spec.knobs,
        observables=spec.observables,
    )
    sandbox_id = runtime.create_sandbox("base")
    try:
        pair = HarnessEngineer().generate(
            scope,
            partial_spec,
            "/tmp/lever-objective/base.py",
            "/tmp/lever-objective/head.py",
            base_source,
            head_source,
        )
        verification = FidelityVerification(report=spec.fidelity, mismatches=(), observations=())
        return Adversary(runtime).search(
            sandbox_id,
            pair,
            partial_spec,
            verification,
            base_source,
            head_source,
            trace_callback,
            objective,
            unsafe_predicate,
        )
    finally:
        runtime.kill_sandbox(sandbox_id)


def _run_pipeline_with_callbacks(
    base_file_path: str,
    head_file_path: str,
    sandbox: SandboxRuntime,
    llm: LLMClient,
    model: str,
    reasoning_effort: str,
    progress_callback: ProgressCallback,
    adversary_callback: AdversaryCallback,
    search_trace_callback: SearchTraceCallback,
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
        search_trace_callback=search_trace_callback,
    )


def _run_prospective_pipeline_with_callbacks(
    base_file_path: str,
    head_file_path: str,
    sandbox: SandboxRuntime,
    llm: LLMClient,
    model: str,
    reasoning_effort: str,
    progress_callback: ProgressCallback,
    adversary_callback: AdversaryCallback,
    search_trace_callback: SearchTraceCallback,
) -> InteractionSpec | DegradeResult:
    """Run the standard agents against generated head source with explicit provenance."""
    return orchestrator.run_pipeline(
        base_file_path,
        head_file_path,
        sandbox,
        llm,
        model,
        reasoning_effort,
        progress_callback=progress_callback,
        adversary_callback=adversary_callback,
        search_trace_callback=search_trace_callback,
        speculative=True,
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
) -> dict[str, Any]:
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
            base_source,
            head_source,
        )
        _stage_source(
            runtime,
            sandbox_id,
            base_module,
            harness_pair.harness_a.instrumented_module_source or base_source,
        )
        _stage_source(
            runtime,
            sandbox_id,
            head_module,
            harness_pair.harness_b.instrumented_module_source or head_source,
        )
        _stage_source(runtime, sandbox_id, f"{base_module}.harness.py", harness_pair.harness_a.source)
        _stage_source(runtime, sandbox_id, f"{head_module}.harness.py", harness_pair.harness_b.source)
        base_result = _run_harness(
            runtime, sandbox_id, f"{base_module}.harness.py", position.root
        )
        head_result = _run_harness(
            runtime, sandbox_id, f"{head_module}.harness.py", position.root
        )
        payload: dict[str, dict[str, Any] | Any] = {
            "base": base_result["observations"],
            "head": head_result["observations"],
        }
        trace = trace_attribution(
            base_result.get("trace"),
            head_result.get("trace"),
            harness_pair.harness_a.instrumented_module_source or base_source,
            harness_pair.harness_b.instrumented_module_source or head_source,
        )
        if trace is not None:
            payload["trace"] = trace.model_dump(mode="json")
        return payload
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
    """Execute one generated harness and return observations plus its raw trace."""
    code = (
        "import json, runpy\n"
        f"namespace = runpy.run_path({harness_path!r})\n"
        f"position = json.loads({json.dumps(json.dumps(position))})\n"
        "print(json.dumps(namespace['run'](position, 0), sort_keys=True))\n"
    )
    result = runtime.run_code(sandbox_id, code)
    if result["exit_code"] != 0:
        raise RuntimeError(f"Harness execution failed: {result['stderr']}")
    return json.loads(result["stdout"])


def _source_files(base_path: Path, head_path: Path) -> dict[str, dict[str, str]]:
    """Serve the exact analyzed files once so the browser can highlight empirical lines."""
    return {
        "base": {"path": str(base_path), "source": base_path.read_text()},
        "head": {"path": str(head_path), "source": head_path.read_text()},
    }


def _hero1_composed_payload(runtime: SandboxRuntime) -> dict[str, Any]:
    """Build the curated Hero 1 composition demo from the four fixture modules."""
    from domain.composed_microworld import (
        CompositionCheckout,
        build_composed_harnesses,
        compose_widget_config,
        evaluate_composed_position,
    )
    from domain.schema import (
        AstNodeRef,
        ConfigBinding,
        CounterExtractor,
        DependencyLedger,
        DriverBinding,
        EntryPoint,
        Knob,
        KnobPosition,
        NumericDomain,
        Observable,
        PartialInteractionSpec,
        ScopedChangeSet,
    )

    fixture_dir = _PROJECT_ROOT / "fixtures" / "hero1"
    scope = ScopedChangeSet(
        entry_point=EntryPoint(
            file=str(fixture_dir / "head.py"),
            fn="RateLimiter.admit",
            signature="RateLimiter.admit(self, tenant_id: str, now: float) -> bool",
        ),
        changed_nodes=[
            AstNodeRef(
                kind="function_definition",
                name="RateLimiter.admit",
                start_byte=0,
                end_byte=100,
            )
        ],
        dependency_ledger=DependencyLedger(),
    )
    spec = PartialInteractionSpec(
        thesis="Compare the independent limit and tenant-window changes together.",
        domainPack="rate-limiter",
        knobs=[
            Knob(
                id="limit_per_sec",
                label="limit",
                binding=ConfigBinding(kind="config", path="limit_per_sec"),
                type="integer",
                domain=NumericDomain(min=1, max=100, step=1),
                default=5,
                scale="linear",
                unit="requests/s",
            ),
            Knob(
                id="burst",
                label="burst",
                binding=ConfigBinding(kind="config", path="burst"),
                type="integer",
                domain=NumericDomain(min=0, max=50, step=1),
                default=0,
                scale="linear",
                unit="requests",
            ),
            Knob(
                id="rps",
                label="rps",
                binding=DriverBinding(kind="driver", param="rps"),
                type="integer",
                domain=NumericDomain(min=1, max=100, step=1),
                default=6,
                scale="linear",
                unit="requests/s",
            ),
            Knob(
                id="tenants",
                label="tenants",
                binding=DriverBinding(kind="driver", param="tenants"),
                type="integer",
                domain=NumericDomain(min=1, max=16, step=1),
                default=2,
                scale="linear",
                unit="tenants",
            ),
        ],
        observables=[
            Observable(
                id="admitted",
                label="admitted",
                extractor=CounterExtractor(kind="counter", name="admitted"),
                render="timeseries",
                unit="requests",
                compareMode="overlay",
            )
        ],
    )
    checkout = CompositionCheckout(
        base_module_path=str(fixture_dir / "base.py"),
        a_module_path=str(fixture_dir / "head.py"),
        b_module_path=str(fixture_dir / "limit_head.py"),
        ab_module_path=str(fixture_dir / "combined.py"),
    )
    harnesses = build_composed_harnesses(scope, spec, checkout)
    sandbox_id = runtime.create_sandbox("compose-hero1")
    try:
        point = KnobPosition({"limit_per_sec": 5, "burst": 0, "rps": 6, "tenants": 2})
        evaluated = evaluate_composed_position(
            runtime, sandbox_id, harnesses, point, "admitted", tolerance=0.01
        )
    finally:
        runtime.kill_sandbox(sandbox_id)
    widget = compose_widget_config(
        "hero1-tenant-windows",
        "hero1-raised-limit",
        spec,
        point,
        evaluated.effect,
    )
    return {
        "type": "composed",
        "changeId": "compose-hero1",
        "composedWidgetConfig": widget.model_dump(mode="json"),
        "symmetristPassed": harnesses.symmetrist.passed,
    }


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


def _pr_change_id(resolved: ResolvedPullRequest) -> str:
    """Stable id for one owner/repo/number @ base/head SHA pair."""
    material = (
        f"pr\0{resolved.owner}/{resolved.repo}#{resolved.number}\0"
        f"{resolved.base_sha}\0{resolved.head_sha}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _fixture_has_executable_reference(base_path: Path, head_path: Path) -> bool:
    """Hero fixtures ship a sibling tests/ directory as their executable reference."""
    return _directory_has_python_tests(base_path.parent / "tests") or _directory_has_python_tests(
        head_path.parent / "tests"
    )


def _checkout_has_executable_reference(checkout: CheckoutHandle) -> bool:
    """Accept conventional tests/ trees under either checkout root or beside the primary file."""
    candidates = [
        checkout.head_root / "tests",
        checkout.base_root / "tests",
    ]
    if checkout.primary_head_file is not None:
        candidates.append(checkout.primary_head_file.parent / "tests")
        candidates.append(checkout.primary_head_file.parent.parent / "tests")
    if checkout.primary_base_file is not None:
        candidates.append(checkout.primary_base_file.parent / "tests")
    return any(_directory_has_python_tests(path) for path in candidates)


def _directory_has_python_tests(directory: Path) -> bool:
    return directory.is_dir() and any(directory.glob("*.py"))


def _prospective_change_id(base_path: Path, hypothesis: str) -> str:
    """Identify one stable current-source/hypothesis candidate request without repo history."""
    material = b"prospective\0" + base_path.read_bytes() + b"\0" + hypothesis.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


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
