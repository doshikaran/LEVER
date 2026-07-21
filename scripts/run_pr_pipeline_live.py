"""Resolve a GitHub PR, dual-checkout it, and run the Lever pipeline once."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from domain.orchestrator import run_pipeline_from_checkout
from domain.schema import InteractionSpec
from domain.synthesizer import synthesize
from infra.checkout.dual_checkout import GitDualCheckout
from infra.github.pr_resolver import GitHubPullRequestResolver
from infra.llm.openai_adapter import OpenAIAdapter
from infra.sandbox.e2b_adapter import E2BSandboxRuntime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr_url", help="GitHub pull request URL")
    parser.add_argument(
        "--checkout-root",
        default=str(PROJECT_ROOT / "data" / "checkouts" / "manual"),
        help="Directory for git worktrees",
    )
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    arguments = parser.parse_args()

    started = time.perf_counter()
    resolved = GitHubPullRequestResolver().resolve(arguments.pr_url)
    checkout = GitDualCheckout().materialize(resolved, Path(arguments.checkout_root))
    result = run_pipeline_from_checkout(
        checkout,
        E2BSandboxRuntime(),
        OpenAIAdapter(model=arguments.model, reasoning_effort=arguments.reasoning_effort),
        arguments.model,
        arguments.reasoning_effort,
        progress_callback=lambda stage, message: print(f"[{stage}] {message}", file=sys.stderr),
    )
    elapsed_seconds = time.perf_counter() - started
    if isinstance(result, InteractionSpec):
        payload = {
            "resultType": "InteractionSpec",
            "interactionSpec": result.model_dump(mode="json"),
            "widgetConfig": synthesize(result).model_dump(mode="json"),
            "primaryPair": {
                "base": str(checkout.primary_base_file),
                "head": str(checkout.primary_head_file),
            },
            "wallClockSeconds": elapsed_seconds,
        }
    else:
        payload = {
            "resultType": type(result).__name__,
            "terminal": asdict(result) if is_dataclass(result) else str(result),
            "selectionReason": checkout.selection_reason,
            "wallClockSeconds": elapsed_seconds,
        }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
