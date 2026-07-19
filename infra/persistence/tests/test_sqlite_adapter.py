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
