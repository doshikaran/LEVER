"""Contract coverage for the SQLite session-ledger adapter."""

import sqlite3

from domain.ports import Repository
from infra.persistence.sqlite_adapter import SQLiteRepository


def test_sqlite_repository_uses_wal_and_survives_reconnection(tmp_path) -> None:
    """The Repository port persists JSON through a WAL-mode database file."""
    database_path = tmp_path / "ledger.sqlite3"
    repository = SQLiteRepository(database_path)

    assert isinstance(repository, Repository)
    repository.save("change-1", {"result": {"admitted": 6}})
    assert repository.load("change-1") == {"result": {"admitted": 6}}
    repository.close()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)

    reopened = SQLiteRepository(database_path)
    assert reopened.load("change-1") == {"result": {"admitted": 6}}
    reopened.close()


def test_list_entries_returns_metadata_without_full_payloads(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "ledger.db")
    repo.save("key-1", {"changeId": "key-1", "provenance": {"repoUrl": "file:///a", "generatedAt": "2026-07-20T00:00:00Z"}, "thesis": "t1"})
    repo.save("key-2", {"changeId": "key-2", "provenance": {"repoUrl": "file:///b", "generatedAt": "2026-07-20T01:00:00Z"}, "thesis": "t2"})
    entries = repo.list_entries()
    assert {entry["changeId"] for entry in entries} == {"key-1", "key-2"}
    assert all("thesis" in entry for entry in entries)
