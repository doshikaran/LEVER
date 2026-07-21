"""SQLite implementation of the domain Repository port."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


class SQLiteRepository:
    """Persist JSON documents by key in a WAL-enabled SQLite session ledger."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def save(self, key: str, value: dict) -> None:
        """Insert or replace one JSON document under its stable ledger key."""
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self._lock:
            connection = self._connect()
            connection.execute(
                """
                INSERT INTO repository_entries (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, encoded),
            )
            connection.commit()

    def load(self, key: str) -> dict | None:
        """Return a decoded document, or None when the session ledger has no key."""
        with self._lock:
            row = self._connect().execute(
                "SELECT value FROM repository_entries WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def list_entries(self) -> list[dict]:
        """Return every saved document's key + full value, newest first by rowid.

        The Session Ledger is currently small enough (one row per generated
        microworld this session) that returning full documents is simpler and
        more honest than maintaining a second summary-only column set that
        could drift from the real payload.
        """
        with self._lock:
            rows = self._connect().execute(
                "SELECT value FROM repository_entries ORDER BY rowid DESC"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self) -> None:
        """Close this adapter's database connection without deleting persisted sessions."""
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _connect(self) -> sqlite3.Connection:
        """Open and initialize the ledger lazily so importing the API has no side effect."""
        if self._connection is not None:
            return self._connection
        if self._database_path != ":memory:":
            Path(self._database_path).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        connection = sqlite3.connect(self._database_path, check_same_thread=False)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS repository_entries (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.commit()
        self._connection = connection
        return connection


__all__ = ["SQLiteRepository"]
