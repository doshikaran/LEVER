"""Run one persisted prospective intake through the real HTTP adapter.

This is deliberately a thin client of ``POST /prospective`` and ``/ws/{changeId}``.
It does not generate code, construct a harness, or call the pipeline itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from interface.api import _PROJECT_ROOT, create_app


def main() -> None:
    """Request one generated candidate and print the persisted terminal evidence."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-file-path",
        default=str(_PROJECT_ROOT / "fixtures" / "hero1" / "base.py"),
    )
    parser.add_argument(
        "--hypothesis",
        default="What if the burst allowance were per-tenant instead of shared?",
    )
    arguments = parser.parse_args()

    started_at = perf_counter()
    app = create_app()
    with TestClient(app) as client:
        accepted = client.post(
            "/prospective",
            json={
                "base_file_path": str(Path(arguments.base_file_path).resolve()),
                "hypothesis": arguments.hypothesis,
            },
        )
        accepted.raise_for_status()
        change_id = accepted.json()["changeId"]
        with client.websocket_connect(f"/ws/{change_id}") as websocket:
            while True:
                terminal = websocket.receive_json()
                if terminal.get("type") not in {"progress", "search_trace"}:
                    break

        persisted = client.get(f"/diffs/{change_id}")
        persisted.raise_for_status()

    print(
        json.dumps(
            {
                "elapsedSeconds": round(perf_counter() - started_at, 3),
                "terminal": terminal,
                "persisted": persisted.json(),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
