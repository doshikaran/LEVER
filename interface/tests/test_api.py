"""HTTP/WebSocket contract coverage without calling external services."""

from fastapi.testclient import TestClient

from domain.adversary import AdversaryResult, CacheEntry, ObservationBundle
from domain.orchestrator import DegradeResult
from domain.schema import (
    Agreement,
    Coverage,
    CvStabilityEstimate,
    FidelityReport,
    InteractionSpec,
    KnobPosition,
    Provenance,
    RelativeTolerance,
    Stability,
    SurpriseMarker,
    SymmetristSummary,
)
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

    def scripted_runner(
        base_path,
        head_path,
        sandbox,
        llm,
        model,
        reasoning_effort,
        progress_callback,
        adversary_callback,
    ) -> InteractionSpec | DegradeResult:
        for stage, message in (
            ("files_touched", "1 file touched."),
            ("behavior_identified", "One behavior changed: request admission."),
            ("old_vs_new", "Old: global. New: tenant scoped."),
            ("building", "Building you something to pull on…"),
        ):
            progress_callback(stage, message)
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
                        observations=ObservationBundle(base={"admitted": 1}, head={"admitted": 2}),
                    ),
                ),
                no_divergence=False,
            )
        )
        return _spec()

    app = create_app(
        runtime_factory=lambda: object(),
        llm_factory=lambda model, effort: object(),
        pipeline_runner=scripted_runner,
        evaluation_runner=lambda base, head, spec, position, runtime: {
            "base": {"admitted": int(position.root["rps"])},
            "head": {"admitted": int(position.root["rps"]) * 2},
        },
    )
    with TestClient(app) as client:
        accepted = client.post(
            "/diffs", json={"base_file_path": str(base), "head_file_path": str(head)}
        )
        assert accepted.status_code == 202
        change_id = accepted.json()["changeId"]

        with client.websocket_connect(f"/ws/{change_id}") as websocket:
            messages = [websocket.receive_json() for _ in range(5)]
            websocket.send_json(
                {"type": "evaluate", "requestId": "off-cache", "position": {"rps": 4}}
            )
            fresh_evaluation = websocket.receive_json()
            websocket.send_json(
                {"type": "evaluate", "requestId": "revisit", "position": {"rps": 4}}
            )
            revisited_evaluation = websocket.receive_json()

    assert [message["stage"] for message in messages[:4]] == [
        "files_touched",
        "behavior_identified",
        "old_vs_new",
        "building",
    ]
    final = messages[-1]
    assert final["type"] == "complete"
    assert final["widgetConfig"]["charts"][0]["yAxisZeroAnchored"] is True
    assert len(final["positionCache"]) == 1
    assert all(len(position_hash) == 64 for position_hash in final["positionCache"])
    assert list(final["positionCache"].values()) == [
        {"base": {"admitted": 1}, "head": {"admitted": 2}}
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
