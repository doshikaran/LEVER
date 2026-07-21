"""HTTP/WebSocket contract coverage without calling external services."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domain.adversary import AdversaryResult, CacheEntry, ObservationBundle, TracePoint
from domain.orchestrator import (
    DegradeResult,
    GracefulDegradation,
    InertResult,
    SkippedResult,
    UnscopableResult,
)
from domain.schema import (
    Agreement,
    Coverage,
    CvStabilityEstimate,
    FidelityReport,
    InteractionSpec,
    KnobPosition,
    Provenance,
    RelativeTolerance,
    ResponsibleLine,
    Stability,
    SurpriseMarker,
    SymmetristSummary,
    TraceAttribution,
    VersionExecutionTrace,
)
from infra.persistence.sqlite_adapter import SQLiteRepository
from infra.fakes.fake_llm import FakeLLMClient
from interface.api import create_app


def _spec() -> InteractionSpec:
    """Build the smallest complete rate-limiter result accepted by Synthesizer."""
    return InteractionSpec.model_validate(
        {
            "specVersion": "2.0",
            "changeId": "domain-change-id",
            "thesis": "Old: global limit. New: per-tenant limit.",
            "domainPack": "rate-limiter",
            "knobs": [
                {
                    "id": "rps",
                    "label": "Requests per second",
                    "binding": {"kind": "driver", "param": "rps"},
                    "type": "integer",
                    "domain": {"min": 1, "max": 100, "step": 1},
                    "default": 3,
                    "scale": "linear",
                    "unit": "requests/s",
                    "axisRole": None,
                }
            ],
            "observables": [
                {
                    "id": "admitted",
                    "label": "Admitted requests",
                    "extractor": {"kind": "counter", "name": "admitted"},
                    "render": "timeseries",
                    "unit": "requests",
                    "compareMode": "overlay",
                }
            ],
            "initialPosition": {"rps": 3},
            "surpriseMarker": {
                "position": {"rps": 3},
                "divergence": 0.5,
                "caption": "Head admits twice as many requests.",
            },
            "presets": [],
            "fidelity": {
                "verdict": "verified",
                "symmetrist": {"passed": True, "hashA": "same", "hashB": "same", "unjustifiedKeys": []},
                "agreement": {
                    "samples": 128,
                    "matched": 128,
                    "rate": 1.0,
                    "tolerance": {"kind": "relative", "epsilon": 0.01},
                },
                "stability": {"replicates": 12, "perObservable": {"admitted": {"kind": "cv", "value": 0.0}}},
                "coverage": {"samples": 128, "strategy": "sobol"},
                "confidence": 0.9,
                "band": "high",
                "degradeReason": None,
            },
            "provenance": {
                "baseSha": "base",
                "headSha": "head",
                "repoUrl": "file:///tmp",
                "generatedAt": "1970-01-01T00:00:00Z",
                "modelIds": {"delta-analyst": "fake"},
                "harnessSourceUri": "sandbox://fake/harness",
            },
        }
    )


def test_post_returns_immediately_and_websocket_replays_progress_then_widget_cache(tmp_path) -> None:
    """The final browser payload includes all Adversary cache positions, not only presets."""
    base = tmp_path / "base.py"
    head = tmp_path / "head.py"
    base.write_text("def rate(): return 1\n")
    head.write_text("def rate(): return 2\n")
    reference = tmp_path / "reference.py"
    reference.write_text("def test_reference() -> None: pass\n")

    def scripted_runner(
        base_path,
        head_path,
        sandbox,
        llm,
        model,
        reasoning_effort,
        progress_callback,
        adversary_callback,
        search_trace_callback,
    ) -> InteractionSpec | DegradeResult:
        for stage, message in (
            ("files_touched", "1 file touched."),
            ("behavior_identified", "One behavior changed: request admission."),
            ("old_vs_new", "Old: global. New: tenant scoped."),
            ("building", "Building you something to pull on…"),
        ):
            progress_callback(stage, message)
        # These arrive before the terminal result, mirroring a live Sobol
        # exploration point followed by a coordinate-ascent probe.
        search_trace_callback(
            TracePoint(KnobPosition({"rps": 1}), 0.05, "explore")
        )
        search_trace_callback(
            TracePoint(KnobPosition({"rps": 3}), 0.5, "exploit")
        )
        adversary_callback(
            AdversaryResult(
                initial_position=KnobPosition({"rps": 3}),
                surprise_marker=SurpriseMarker(
                    position=KnobPosition({"rps": 3}),
                    divergence=0.5,
                    caption="Head admits twice as many requests.",
                ),
                presets=(),
                search_trace=(),
                cache=(
                    CacheEntry(
                        position=KnobPosition({"rps": 3}),
                        observations=ObservationBundle(
                            base={"admitted": 1},
                            head={"admitted": 2},
                            trace=TraceAttribution(
                                base=VersionExecutionTrace(
                                    file=str(base), executedLines=[1], entryLines=[1]
                                ),
                                head=VersionExecutionTrace(
                                    file=str(head), executedLines=[1], entryLines=[1]
                                ),
                                responsibleLine=ResponsibleLine(
                                    version="head",
                                    file=str(head),
                                    line=1,
                                    code="def rate(): return 2",
                                ),
                            ),
                        ),
                    ),
                ),
                no_divergence=False,
            )
        )
        return _spec()

    repository = SQLiteRepository(tmp_path / "sessions.sqlite3")
    app = create_app(
        runtime_factory=lambda: object(),
        llm_factory=lambda model, effort: object(),
        pipeline_runner=scripted_runner,
        pinned_tests_dir=tmp_path / "pinned_tests",
        evaluation_runner=lambda base, head, spec, position, runtime: {
            "base": {"admitted": int(position.root["rps"])},
            "head": {"admitted": int(position.root["rps"]) * 2},
        },
    )
    with TestClient(app) as client:
        assert client.get("/diffs/not-persisted").status_code == 404
        accepted = client.post(
            "/diffs",
            json={
                "base_file_path": str(base),
                "head_file_path": str(head),
                "reference_file_path": str(reference),
            },
        )
        assert accepted.status_code == 202
        change_id = accepted.json()["changeId"]

        with client.websocket_connect(f"/ws/{change_id}") as websocket:
            messages = [websocket.receive_json() for _ in range(7)]
            pinned = client.post(f"/diffs/{change_id}/pin", json={"position": {"rps": 3}})
            websocket.send_json(
                {"type": "evaluate", "requestId": "off-cache", "position": {"rps": 4}}
            )
            fresh_evaluation = websocket.receive_json()
            websocket.send_json(
                {"type": "evaluate", "requestId": "revisit", "position": {"rps": 4}}
            )
            revisited_evaluation = websocket.receive_json()
        persisted = client.get(f"/diffs/{change_id}")

    assert [message["stage"] for message in messages[:4]] == [
        "files_touched",
        "behavior_identified",
        "old_vs_new",
        "building",
    ]
    assert [message["type"] for message in messages[4:6]] == [
        "search_trace",
        "search_trace",
    ]
    assert messages[4]["tracePoint"] == {
        "position": {"rps": 1.0},
        "divergence": 0.05,
        "phase": "explore",
    }
    assert messages[5]["tracePoint"] == {
        "position": {"rps": 3.0},
        "divergence": 0.5,
        "phase": "exploit",
    }
    final = messages[-1]
    assert final["type"] == "complete"
    assert pinned.status_code == 200
    pinned_source = Path(pinned.json()["testPath"]).read_text()
    assert "HarnessEngineer().generate" in pinned_source
    assert "# Lever trace attribution:" in pinned_source
    assert "EXPECTED_HEAD = json.loads('{\"admitted\": 2}')" in pinned_source
    assert persisted.status_code == 200
    # The terminal event contains Adversary's original cache.  A later fresh
    # interaction is persisted immediately, so the permalink retains it too.
    persisted_payload = persisted.json()
    assert persisted_payload["type"] == "complete"
    assert persisted_payload["positionCache"] == {
        **final["positionCache"],
        "cb0eff150ae5c5462d1506b4ef0e2d3d0c5304e71fbadcd3aca51c92f696442b": {
            "base": {"admitted": 4},
            "head": {"admitted": 8},
        },
    }
    assert final["widgetConfig"]["charts"][0]["yAxisZeroAnchored"] is True
    assert len(final["positionCache"]) == 1
    assert all(len(position_hash) == 64 for position_hash in final["positionCache"])
    assert list(final["positionCache"].values()) == [
        {
            "position": {"rps": 3.0},
            "base": {"admitted": 1},
            "head": {"admitted": 2},
            "trace": {
                    "base": {
                        "file": str(base),
                        "executedLines": [1],
                        "entryLines": [1],
                        "lineHits": {},
                        "branchDecisions": [],
                    },
                    "head": {
                        "file": str(head),
                        "executedLines": [1],
                        "entryLines": [1],
                        "lineHits": {},
                        "branchDecisions": [],
                    },
                "responsibleLine": {
                    "version": "head",
                    "file": str(head),
                    "line": 1,
                    "code": "def rate(): return 2",
                },
            },
        }
    ]
    assert fresh_evaluation == {
        "type": "evaluation",
        "requestId": "off-cache",
        "positionKey": "cb0eff150ae5c5462d1506b4ef0e2d3d0c5304e71fbadcd3aca51c92f696442b",
        "observations": {"base": {"admitted": 4}, "head": {"admitted": 8}},
        "source": "fresh",
    }
    assert revisited_evaluation == {
        **fresh_evaluation,
        "requestId": "revisit",
        "source": "cache",
    }
    repository.close()


def test_websocket_objective_search_streams_boundary_trace_and_retains_new_cache_points(
    tmp_path, monkeypatch
) -> None:
    """The security selector reruns only Adversary and publishes its cache-forward result."""
    base = tmp_path / "base.py"
    head = tmp_path / "head.py"
    reference = tmp_path / "reference.py"
    base.write_text("def rate(): return 1\n")
    head.write_text("def rate(): return 2\n")
    reference.write_text("def test_reference() -> None: pass\n")

    def terminal_runner(*args) -> InteractionSpec:
        args[-2](
            AdversaryResult(
                initial_position=KnobPosition({"rps": 3}),
                surprise_marker=None,
                presets=(),
                search_trace=(),
                cache=(),
                no_divergence=False,
            )
        )
        return _spec()

    def scripted_objective_search(
        _base_path, _head_path, _specification, _runtime, objective, predicate, callback
    ) -> AdversaryResult:
        assert objective == "reach_unsafe_state"
        assert predicate is not None
        assert predicate.observableId == "admitted"
        callback(TracePoint(KnobPosition({"rps": -1}), 1.0, "explore"))
        return AdversaryResult(
            initial_position=KnobPosition({"rps": -1}),
            surprise_marker=SurpriseMarker(
                position=KnobPosition({"rps": -1}),
                divergence=1.0,
                caption="Unsafe state reached in head: admitted=1 > 0.",
            ),
            presets=(),
            search_trace=(),
            cache=(
                CacheEntry(
                    position=KnobPosition({"rps": -1}),
                    observations=ObservationBundle(
                        base={"admitted": 0}, head={"admitted": 1}
                    ),
                ),
            ),
            no_divergence=False,
            objective="reach_unsafe_state",
            unsafe_predicate=predicate,
        )

    monkeypatch.setattr("interface.api._run_objective_search", scripted_objective_search)
    repository = SQLiteRepository(tmp_path / "sessions.sqlite3")
    app = create_app(
        repository=repository,
        runtime_factory=lambda: object(),
        llm_factory=lambda _model, _effort: object(),
        pipeline_runner=terminal_runner,
    )
    with TestClient(app) as client:
        accepted = client.post(
            "/diffs",
            json={
                "base_file_path": str(base),
                "head_file_path": str(head),
                "reference_file_path": str(reference),
            },
        )
        with client.websocket_connect(f"/ws/{accepted.json()['changeId']}") as websocket:
            assert websocket.receive_json()["type"] == "complete"
            websocket.send_json(
                {
                    "type": "search_objective",
                    "requestId": "unsafe-1",
                    "objective": "reach_unsafe_state",
                    "unsafePredicate": {
                        "observableId": "admitted",
                        "operator": "gt",
                        "target": {"kind": "literal", "value": 0},
                    },
                }
            )
            started = websocket.receive_json()
            trace = websocket.receive_json()
            result = websocket.receive_json()

    assert started == {
        "type": "objective_started",
        "requestId": "unsafe-1",
        "objective": "reach_unsafe_state",
    }
    assert trace["type"] == "search_trace"
    assert trace["tracePoint"]["position"] == {"rps": -1.0}
    assert result["type"] == "objective_result"
    assert result["noUnsafeState"] is False
    assert result["surpriseMarker"]["caption"].startswith("Unsafe state reached")
    assert len(result["positionCache"]) == 1
    repository.close()


def test_prospective_intake_persists_one_generated_source_and_forces_speculative_provenance(
    tmp_path,
) -> None:
    """Current-vs-candidate reuses the normal pipeline while retaining the generated head."""
    base = tmp_path / "current.py"
    base.write_text("class RateLimiter:\n    pass\n")
    candidate_source = """\
class RateLimiter:
    def __init__(self, limit_per_sec: int):
        self.limit = limit_per_sec
        self.windows = {}

    def admit(self, tenant_id: str, now: float) -> bool:
        count = self.windows.get(tenant_id, 0)
        self.windows[tenant_id] = count + 1
        return count < self.limit
"""
    candidate_dir = tmp_path / "candidates"
    calls: list[tuple[str, str]] = []

    def prospective_runner(
        base_path,
        head_path,
        sandbox,
        llm,
        model,
        reasoning_effort,
        progress_callback,
        adversary_callback,
        search_trace_callback,
    ) -> InteractionSpec:
        calls.append((base_path, head_path))
        assert Path(head_path).read_text() == candidate_source
        return _spec()

    repository = SQLiteRepository(tmp_path / "prospective.sqlite3")
    app = create_app(
        repository=repository,
        runtime_factory=lambda: object(),
        llm_factory=lambda _model, _effort: FakeLLMClient(
            [{"source": candidate_source, "summary": "Returns candidate behavior."}]
        ),
        prospective_pipeline_runner=prospective_runner,
        prospective_candidate_dir=candidate_dir,
    )
    with TestClient(app) as client:
        accepted = client.post(
            "/prospective",
            json={
                "base_file_path": str(base),
                "hypothesis": "what if the burst allowance were per-tenant instead of shared?",
            },
        )
        assert accepted.status_code == 202
        change_id = accepted.json()["changeId"]
        with client.websocket_connect(f"/ws/{change_id}") as websocket:
            terminal = websocket.receive_json()

    assert calls == [(str(base), str(candidate_dir / f"{change_id}.py"))]
    assert terminal["type"] == "complete"
    assert terminal["interactionSpec"]["provenance"]["speculative"] is True
    assert terminal["widgetConfig"]["speculative"] is True
    assert "does not retain a burst-related identifier" in terminal["interactionSpec"]["provenance"]["hypothesisCaveat"]
    assert "does not retain a burst-related identifier" in terminal["widgetConfig"]["hypothesisCaveat"]
    assert terminal["sourceFiles"]["head"]["source"] == candidate_source
    assert (candidate_dir / f"{change_id}.py").read_text() == candidate_source
    repository.close()


@pytest.mark.parametrize(
    ("hero_id", "hero_key"),
    (("hero1", "hero:hero1"), ("hero4", "hero:hero4")),
)
def test_hero_result_is_frozen_without_reinvoking_orchestrator(
    tmp_path, monkeypatch, hero_id: str, hero_key: str
) -> None:
    """A pinned hero calls the real adapter's run_pipeline seam exactly once."""
    database_path = tmp_path / "hero-sessions.sqlite3"
    calls = 0

    def spy_run_pipeline(
        base_path,
        head_path,
        sandbox,
        llm,
        model,
        reasoning_effort,
        progress_callback=None,
        adversary_callback=None,
        search_trace_callback=None,
    ) -> InteractionSpec | DegradeResult:
        nonlocal calls
        calls += 1
        assert adversary_callback is not None
        adversary_callback(
            AdversaryResult(
                initial_position=KnobPosition({"rps": 3}),
                surprise_marker=SurpriseMarker(
                    position=KnobPosition({"rps": 3}),
                    divergence=0.5,
                    caption="Head admits twice as many requests.",
                ),
                presets=(),
                search_trace=(),
                cache=(
                    CacheEntry(
                        position=KnobPosition({"rps": 3}),
                        observations=ObservationBundle(
                            base={"admitted": 1}, head={"admitted": 2}
                        ),
                    ),
                ),
                no_divergence=False,
            )
        )
        return _spec()

    monkeypatch.setattr("domain.orchestrator.run_pipeline", spy_run_pipeline)

    first_repository = SQLiteRepository(database_path)
    first_app = create_app(
        repository=first_repository,
        runtime_factory=lambda: object(),
        llm_factory=lambda model, effort: object(),
    )
    with TestClient(first_app) as client:
        first = client.post(f"/heroes/{hero_id}/run")
        second = client.post(f"/heroes/{hero_id}/run")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["changeId"] == hero_key
    assert calls == 1
    first_repository.close()

    restarted_repository = SQLiteRepository(database_path)
    restarted_app = create_app(
        repository=restarted_repository,
        runtime_factory=lambda: object(),
        llm_factory=lambda model, effort: object(),
    )
    with TestClient(restarted_app) as client:
        after_restart = client.post(f"/heroes/{hero_id}/run")

    assert after_restart.status_code == 200
    assert after_restart.json() == first.json()
    assert calls == 1
    restarted_repository.close()


def test_run_hero2_is_registered(tmp_path, monkeypatch) -> None:
    """Hero 2 is reachable through the pinned-hero endpoint, not just Hero 1/4."""
    _assert_hero_is_reachable(tmp_path, monkeypatch, "hero2")


def test_run_hero3_is_registered(tmp_path, monkeypatch) -> None:
    """Hero 3 is reachable through the pinned-hero endpoint, not just Hero 1/4."""
    _assert_hero_is_reachable(tmp_path, monkeypatch, "hero3")


def _assert_hero_is_reachable(tmp_path, monkeypatch, hero_id: str) -> None:
    """Confirm a hero_id is registered in HERO_FIXTURES without invoking real infra."""

    def stub_run_pipeline(
        base_path,
        head_path,
        sandbox,
        llm,
        model,
        reasoning_effort,
        progress_callback=None,
        adversary_callback=None,
        search_trace_callback=None,
    ) -> InteractionSpec | DegradeResult:
        return _spec()

    monkeypatch.setattr("domain.orchestrator.run_pipeline", stub_run_pipeline)
    repository = SQLiteRepository(tmp_path / f"{hero_id}-sessions.sqlite3")
    app = create_app(
        repository=repository,
        runtime_factory=lambda: object(),
        llm_factory=lambda model, effort: object(),
    )
    with TestClient(app) as client:
        response = client.post(f"/heroes/{hero_id}/run")

    assert response.status_code != 404
    repository.close()


@pytest.mark.parametrize(
    ("terminal_result", "expected_kind"),
    [
        (
            GracefulDegradation(
                "Fidelity could not agree.",
                proposedSpecs=(
                    {
                        "thesis": "A captured Delta draft.",
                        "domainPack": "numeric-fn",
                        "knobs": [],
                        "observables": [],
                    },
                ),
            ),
            "degraded",
        ),
        (
            InertResult(
                "No divergence found.",
                proposedSpecs=(
                    {
                        "thesis": "A captured inert Delta draft.",
                        "domainPack": "rate-limiter",
                        "knobs": [],
                        "observables": [],
                    },
                ),
            ),
            "inert",
        ),
        (UnscopableResult("`view` requires live framework parameter `request`"), "unscopable"),
        (SkippedResult("formatting only"), "skipped"),
    ],
)
def test_degraded_and_inert_terminal_results_are_persisted(
    tmp_path, terminal_result: DegradeResult, expected_kind: str
) -> None:
    """Every non-widget terminal outcome has the same durable permalink behavior."""
    base = tmp_path / "base.py"
    head = tmp_path / "head.py"
    base.write_text("def rate(): return 1\n")
    head.write_text("def rate(): return 2\n")
    reference = tmp_path / "reference.py"
    reference.write_text("def test_reference() -> None: pass\n")
    repository = SQLiteRepository(tmp_path / f"{expected_kind}.sqlite3")

    def terminal_runner(*_args) -> InteractionSpec | DegradeResult:
        return terminal_result

    app = create_app(
        repository=repository,
        runtime_factory=lambda: object(),
        llm_factory=lambda model, effort: object(),
        pipeline_runner=terminal_runner,
    )
    with TestClient(app) as client:
        accepted = client.post(
            "/diffs",
            json={
                "base_file_path": str(base),
                "head_file_path": str(head),
                "reference_file_path": str(reference),
            },
        )
        change_id = accepted.json()["changeId"]
        with client.websocket_connect(f"/ws/{change_id}") as websocket:
            terminal = websocket.receive_json()
        persisted = client.get(f"/diffs/{change_id}")

    assert terminal["type"] == expected_kind
    assert terminal["degradeReason"] == terminal_result.reason
    assert terminal["outcome"]["kind"] == expected_kind
    assert terminal["proposedSpecs"] == list(terminal_result.proposedSpecs)
    assert persisted.json() == terminal
    repository.close()
