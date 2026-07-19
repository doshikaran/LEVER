"""Run the approved real Hero 1 pipeline once and emit its complete terminal JSON."""

import json
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from domain.orchestrator import run_pipeline
from domain.schema import InteractionSpec
from domain.synthesizer import synthesize
from infra.llm.openai_adapter import OpenAIAdapter
from infra.sandbox.e2b_adapter import E2BSandboxRuntime


MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "high"


def main() -> None:
    """Invoke the orchestrator once, then serialize the returned spec/widget or terminal state."""
    started = time.perf_counter()
    result = run_pipeline(
        str(PROJECT_ROOT / "fixtures" / "hero1" / "base.py"),
        str(PROJECT_ROOT / "fixtures" / "hero1" / "head.py"),
        E2BSandboxRuntime(),
        OpenAIAdapter(model=MODEL, reasoning_effort=REASONING_EFFORT),
        MODEL,
        REASONING_EFFORT,
    )
    elapsed_seconds = time.perf_counter() - started
    if isinstance(result, InteractionSpec):
        payload = {
            "resultType": "InteractionSpec",
            "interactionSpec": result.model_dump(mode="json"),
            "widgetConfig": synthesize(result).model_dump(mode="json"),
            "wallClockSeconds": elapsed_seconds,
        }
    else:
        payload = {
            "resultType": type(result).__name__,
            "terminal": asdict(result) if is_dataclass(result) else str(result),
            "wallClockSeconds": elapsed_seconds,
        }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
