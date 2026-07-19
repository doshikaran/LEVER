"""Measure three real cache-miss evaluation round trips through the local API."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import websockets

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.schema import KnobPosition
from interface.api import _position_key


API_BASE = "http://127.0.0.1:8765"


def _post_diff() -> str:
    """Start or reuse the real Hero 1 analysis and return its stable change ID."""
    payload = json.dumps(
        {
            "base_file_path": str(ROOT / "fixtures/hero1/base.py"),
            "head_file_path": str(ROOT / "fixtures/hero1/head.py"),
        }
    ).encode()
    request = urllib.request.Request(
        f"{API_BASE}/diffs", payload, {"content-type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request) as response:  # noqa: S310 - localhost test server
        return json.load(response)["changeId"]


def _candidate(widget: dict[str, Any], ordinal: int) -> dict[str, Any]:
    """Choose a deterministic valid position that differs across every requested sample."""
    position = dict(widget["initialPosition"])
    for index, control in enumerate(widget["controls"]):
        kind = control["type"]
        if kind in {"scalar", "integer"}:
            domain = control["domain"]
            steps = round((domain["max"] - domain["min"]) / domain["step"])
            offset = (ordinal * 31 + index * 17) % (steps + 1)
            value = domain["min"] + offset * domain["step"]
            position[control["id"]] = int(value) if kind == "integer" else value
        elif kind == "boolean":
            position[control["id"]] = bool((ordinal + index) % 2)
        elif kind == "enum":
            choices = control["domain"]["values"]
            position[control["id"]] = choices[(ordinal + index) % len(choices)]
    return position


async def main() -> None:
    """Run the pipeline to completion, then report three cache-miss wall times in milliseconds."""
    change_id = await asyncio.to_thread(_post_diff)
    print(f"Waiting for Hero 1 pipeline {change_id[:12]}…", flush=True)
    websocket_url = f"ws://127.0.0.1:8765/ws/{change_id}"
    async with websockets.connect(websocket_url, max_size=1_000_000) as websocket:
        complete: dict[str, Any] | None = None
        while complete is None:
            message = json.loads(await websocket.recv())
            if message["type"] == "complete":
                complete = message
            elif message["type"] in {"error", "terminal"}:
                raise RuntimeError(json.dumps(message))

        print("Pipeline complete; timing fresh positions…", flush=True)
        cache_keys = set(complete["positionCache"])
        widget = complete["widgetConfig"]
        timings: list[dict[str, Any]] = []
        ordinal = 1
        while len(timings) < 3:
            position = _candidate(widget, ordinal)
            ordinal += 1
            key = _position_key(KnobPosition(position))
            if key in cache_keys:
                continue
            request_id = f"timing-{len(timings) + 1}"
            started_ns = time.perf_counter_ns()
            await websocket.send(
                json.dumps({"type": "evaluate", "requestId": request_id, "position": position})
            )
            print(f"Measuring {request_id}…", flush=True)
            response = json.loads(await websocket.recv())
            elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
            if response.get("type") != "evaluation" or response.get("source") != "fresh":
                raise RuntimeError(f"Expected fresh evaluation, received {response}")
            cache_keys.add(response["positionKey"])
            timings.append(
                {
                    "position": position,
                    "round_trip_ms": round(elapsed_ms, 2),
                    "observations": response["observations"],
                }
            )

    print(json.dumps(timings, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
