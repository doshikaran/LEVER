"""Session ledger + permalink rehydration for Phase C."""

from pathlib import Path

from fastapi.testclient import TestClient

from domain.schema import InteractionSpec
from domain.synthesizer import synthesize
from infra.persistence.sqlite_adapter import SQLiteRepository
from interface.api import create_app
from interface.tests.test_api import _spec


def test_sessions_lists_persisted_complete_payloads(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "sessions.sqlite3")
    repository.save(
        "change-a",
        {
            "type": "complete",
            "changeId": "change-a",
            "title": "Hero throughput delta",
            "savedAt": "2026-07-21T00:00:00+00:00",
            "widgetConfig": {
                "thesis": "Hero throughput delta",
                "fidelityBand": "high",
                "speculative": False,
            },
        },
    )
    repository.save("hero:hero1", {"type": "complete", "changeId": "hero:hero1", "title": "frozen"})
    app = create_app(repository=repository, database_path=tmp_path / "sessions.sqlite3")
    client = TestClient(app)
    rows = client.get("/sessions").json()
    assert len(rows) == 1
    assert rows[0]["changeId"] == "change-a"
    assert rows[0]["outcome"] == "complete"
    assert rows[0]["fidelityBand"] == "high"
    assert client.get("/health").json()["phase"] == "F"


def test_websocket_rehydrates_completed_permalink_from_sqlite(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "sessions.sqlite3")
    base = tmp_path / "base.py"
    head = tmp_path / "head.py"
    base.write_text("def admit():\n    return 1\n")
    head.write_text("def admit():\n    return 2\n")
    spec = _spec()
    InteractionSpec.model_validate(spec.model_dump(mode="json"))
    widget = synthesize(spec).model_dump(mode="json")
    payload = {
        "type": "complete",
        "changeId": "permalink-1",
        "title": spec.thesis,
        "savedAt": "2026-07-21T00:00:00+00:00",
        "interactionSpec": spec.model_dump(mode="json"),
        "widgetConfig": widget,
        "positionCache": {},
        "sourceFiles": {
            "base": {"path": str(base), "source": base.read_text()},
            "head": {"path": str(head), "source": head.read_text()},
        },
        "basePath": str(base),
        "headPath": str(head),
        "outcome": "complete",
    }
    repository.save("permalink-1", payload)
    app = create_app(repository=repository, database_path=tmp_path / "sessions.sqlite3")
    client = TestClient(app)
    assert client.get("/diffs/permalink-1").json()["changeId"] == "permalink-1"
    with client.websocket_connect("/ws/permalink-1") as websocket:
        event = websocket.receive_json()
        assert event["type"] == "complete"
        assert event["changeId"] == "permalink-1"
        assert "worldSpec" in event["widgetConfig"]
