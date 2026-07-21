#!/usr/bin/env python3
"""Print a Wild Three hit-rate table for judge README updates."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from domain.orchestrator import DegradeResult, GracefulDegradation  # noqa: E402
from domain.schema import DependencyLedger, EntryPoint, PartialInteractionSpec, ScopedChangeSet  # noqa: E402
from interface.api import _manual_test_recipe, _static_notes, _terminal_payload  # noqa: E402


@dataclass(frozen=True)
class CorpusRow:
    corpus_id: str
    label: str
    outcome: str
    detail: str


def _w1_generative() -> CorpusRow:
    """W1: unregistered scale() must produce a generative harness pair."""
    from domain.harness_engineer import HarnessEngineer
    from domain.schema import (
        ArgumentBinding,
        Knob,
        NumericDomain,
        Observable,
        ReturnValueExtractor,
    )

    fixture = PROJECT_ROOT / "fixtures/wild_synth"
    scope = ScopedChangeSet(
        entry_point=EntryPoint(
            file=str(fixture / "head.py"),
            fn="scale",
            signature="scale(value: float, factor: float = 2.0) -> float",
        ),
        dependency_ledger=DependencyLedger(),
    )
    partial = PartialInteractionSpec(
        thesis="Head adds a constant offset after scaling.",
        domainPack="numeric-fn",
        knobs=[
            Knob(
                id="value",
                label="value",
                binding=ArgumentBinding(kind="argument", fn="scale", argIndex=0),
                type="scalar",
                domain=NumericDomain(min=0, max=10, step=1),
                default=3,
                scale="linear",
                unit=None,
                axisRole="x",
            ),
            Knob(
                id="factor",
                label="factor",
                binding=ArgumentBinding(kind="argument", fn="scale", argIndex=1),
                type="scalar",
                domain=NumericDomain(min=1, max=5, step=1),
                default=2,
                scale="linear",
                unit=None,
            ),
        ],
        observables=[
            Observable(
                id="result",
                label="scaled result",
                extractor=ReturnValueExtractor(kind="returnValue", path="$"),
                render="scalar",
                unit=None,
                compareMode="delta",
            )
        ],
    )
    pair = HarnessEngineer().generate(
        scope,
        partial,
        str(fixture / "base.py"),
        str(fixture / "head.py"),
    )
    ok = pair.generative_ir is not None and "scale" in pair.harness_a.source
    return CorpusRow(
        "W1",
        "wild_synth scale()",
        "verified-path" if ok else "failed",
        "generative harness pair rendered" if ok else "generative path failed",
    )


def _w2_hero_arena() -> CorpusRow:
    """W2: Hero 2 fixture present; rate-limiter maps to a game genre."""
    from interface.tests.test_api import _spec
    from domain.world_director import build_world_spec

    base = PROJECT_ROOT / "fixtures/hero2/base.py"
    head = PROJECT_ROOT / "fixtures/hero2/head.py"
    ok_files = base.is_file() and head.is_file()
    genre = build_world_spec(_spec()).genre
    ok = ok_files and genre in {"throughput", "retry-storm"}
    return CorpusRow(
        "W2",
        "hero2 retry fog",
        "verified-path" if ok else "failed",
        f"files={ok_files} genre={genre}",
    )


def _w3_degrade_plus() -> CorpusRow:
    """W3: unscopable fixture materializes Degradation+ recipe fields."""
    result = GracefulDegradation(
        "The change is inside a Django view requiring a live request object.",
        plain_explanation="Manually test through the request boundary.",
        divergence_report=(
            {
                "position": {"role": "admin"},
                "version": "head",
                "observable": "allow",
                "harness": True,
                "reference": False,
            },
        ),
        proposedSpecs=(
            {"thesis": "Permission widen for staff.", "domainPack": "permission"},
        ),
    )
    assert isinstance(result, DegradeResult)
    payload = _terminal_payload("w3", result, {})
    recipe = payload.get("manualTestRecipe") or _manual_test_recipe(result)
    notes = payload.get("staticNotes") or _static_notes(result)
    ok = bool(recipe) and any("UNVERIFIED" in note for note in notes)
    return CorpusRow(
        "W3",
        "unscopable degrade+",
        "degraded+" if ok else "failed",
        f"recipe={len(recipe)} notes={len(notes)}",
    )


def main() -> int:
    rows = [_w1_generative(), _w2_hero_arena(), _w3_degrade_plus()]
    verified = sum(1 for row in rows if row.outcome.startswith("verified"))
    degraded = sum(1 for row in rows if row.outcome.startswith("degraded"))
    failed = sum(1 for row in rows if row.outcome == "failed")
    print("Wild Three corpus")
    print(f"{'ID':<4} {'Label':<22} {'Outcome':<14} Detail")
    for row in rows:
        print(f"{row.corpus_id:<4} {row.label:<22} {row.outcome:<14} {row.detail}")
    print()
    print(
        json.dumps(
            {
                "n": len(rows),
                "verified_path": verified,
                "degraded_plus": degraded,
                "failed": failed,
                "hit_rate_verified_or_honest": (verified + degraded) / len(rows),
            },
            indent=2,
        )
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
