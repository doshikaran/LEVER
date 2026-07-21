"""Compose demo + Degradation+ payload contract."""

from pathlib import Path

from fastapi.testclient import TestClient

from domain.orchestrator import GracefulDegradation
from infra.fakes.fake_sandbox import FakeSandboxRuntime
from infra.persistence.sqlite_adapter import SQLiteRepository
from interface.api import create_app


def test_compose_hero1_demo_returns_measured_2x2(tmp_path: Path) -> None:
    app = create_app(
        database_path=tmp_path / "sessions.sqlite3",
        runtime_factory=FakeSandboxRuntime,
    )
    with TestClient(app) as client:
        payload = client.get("/compose/demos/hero1").json()
    assert payload["type"] == "composed"
    assert payload["symmetristPassed"] is True
    cells = payload["composedWidgetConfig"]["cells"]
    assert [cell["variant"] for cell in cells] == ["base", "A", "B", "AB"]
    assert [cell["observation"] for cell in cells] == [5, 10, 10, 12]
    assert payload["composedWidgetConfig"]["interaction"]["detected"] is True


def test_degradation_payload_includes_recipe_and_static_notes(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "sessions.sqlite3")

    def pipeline_runner(*_args, **_kwargs):
        return GracefulDegradation(
            "Fidelity agreement stayed below 0.85 after all three Harness Engineer attempts.",
            plain_explanation="Manually probe the changed entry point.",
            divergence_report=(
                {
                    "position": {"rps": 7},
                    "version": "head",
                    "observable": "admitted",
                    "harness": 1,
                    "reference": 7,
                },
            ),
            proposedSpecs=({"thesis": "Per-tenant burst.", "domainPack": "rate-limiter"},),
        )

    app = create_app(
        repository=repository,
        database_path=tmp_path / "sessions.sqlite3",
        pipeline_runner=pipeline_runner,
        runtime_factory=FakeSandboxRuntime,
    )
    base = tmp_path / "base.py"
    head = tmp_path / "head.py"
    base.write_text("def admit():\n    return 1\n")
    head.write_text("def admit():\n    return 2\n")
    with TestClient(app) as client:
        change_id = client.post(
            "/diffs",
            json={"base_file_path": str(base), "head_file_path": str(head)},
        ).json()["changeId"]
        with client.websocket_connect(f"/ws/{change_id}") as websocket:
            while True:
                event = websocket.receive_json()
                if event.get("type") != "progress":
                    break
    assert event["type"] == "degraded"
    assert event["manualTestRecipe"]
    assert any("UNVERIFIED" in note for note in event["staticNotes"])
    assert event["proposedSpecs"]
