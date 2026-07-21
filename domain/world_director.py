"""Mechanical WorldSpec selection from an InteractionSpec's domain pack.

This is deterministic theater direction — not an LLM. Genre picks the stage
renderer; trust still comes only from verified InteractionSpec + fidelity.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from domain.schema import DomainPackId, InteractionSpec

WorldGenre = Literal[
    "throughput",
    "access-matrix",
    "decision-path",
    "retry-storm",
    "state-workflow",
    "numeric-response",
    "queue-backlog",
    "cache-efficiency",
    "custom",
]

StageKind = Literal["arena", "matrix", "tree", "curve", "workflow"]
Affordance = Literal[
    "particles",
    "scrubber",
    "fog-of-war",
    "boss-fight",
    "evidence-chart",
    "dual-gates",
    "surprise-marker",
    "walk-animation",
]


class StageConfig(BaseModel):
    """How the frontend should stage the verified observations."""

    kind: StageKind
    layout: Literal["full-bleed", "split", "stacked"] = "full-bleed"


class WorldSpec(BaseModel):
    """v3 playable-world descriptor attached to WidgetConfig."""

    genre: WorldGenre
    stage: StageConfig
    affordances: list[Affordance] = Field(default_factory=list)
    narrationLine: str
    playHints: list[str] = Field(default_factory=list, max_length=3)


_PACK_TO_GENRE: dict[DomainPackId, WorldGenre] = {
    DomainPackId.RATE_LIMITER: "throughput",
    DomainPackId.PERMISSION: "access-matrix",
    DomainPackId.DECISION_TREE: "decision-path",
    DomainPackId.NUMERIC_FN: "numeric-response",
    DomainPackId.STATE_MACHINE: "state-workflow",
}

_GENRE_STAGE: dict[WorldGenre, StageConfig] = {
    "throughput": StageConfig(kind="arena", layout="full-bleed"),
    "retry-storm": StageConfig(kind="arena", layout="full-bleed"),
    "access-matrix": StageConfig(kind="matrix", layout="full-bleed"),
    "decision-path": StageConfig(kind="tree", layout="stacked"),
    "state-workflow": StageConfig(kind="workflow", layout="stacked"),
    "numeric-response": StageConfig(kind="curve", layout="stacked"),
    "queue-backlog": StageConfig(kind="curve", layout="stacked"),
    "cache-efficiency": StageConfig(kind="curve", layout="stacked"),
    "custom": StageConfig(kind="curve", layout="stacked"),
}

_GENRE_AFFORDANCES: dict[WorldGenre, list[Affordance]] = {
    "throughput": [
        "particles",
        "dual-gates",
        "surprise-marker",
        "fog-of-war",
        "boss-fight",
        "evidence-chart",
        "scrubber",
    ],
    "retry-storm": [
        "particles",
        "dual-gates",
        "surprise-marker",
        "fog-of-war",
        "boss-fight",
        "evidence-chart",
        "scrubber",
    ],
    "access-matrix": [
        "surprise-marker",
        "fog-of-war",
        "boss-fight",
        "evidence-chart",
        "scrubber",
    ],
    "decision-path": [
        "walk-animation",
        "surprise-marker",
        "fog-of-war",
        "boss-fight",
        "scrubber",
    ],
    "numeric-response": ["surprise-marker", "fog-of-war", "evidence-chart", "scrubber"],
    "state-workflow": ["surprise-marker", "fog-of-war", "scrubber"],
    "queue-backlog": ["surprise-marker", "evidence-chart", "scrubber"],
    "cache-efficiency": ["surprise-marker", "evidence-chart", "scrubber"],
    "custom": ["surprise-marker", "evidence-chart", "scrubber"],
}

_GENRE_HINTS: dict[WorldGenre, list[str]] = {
    "throughput": [
        "Drag load until the gates diverge.",
        "Click a fog point to jump to a measured probe.",
        "Pin a surprising position as a regression test.",
    ],
    "retry-storm": [
        "Raise concurrency until retries herd.",
        "Watch both gates under the same arrival seed.",
        "Pin the worst divergence you find.",
    ],
    "access-matrix": [
        "Toggle role and resource axes.",
        "Look for cells where only one version admits.",
        "Run a security search for an unsafe cell.",
    ],
    "decision-path": [
        "Follow the shared input until the fork ring.",
        "Dim nodes were unreached by one version.",
        "Click fog points to inspect other paths.",
    ],
    "numeric-response": [
        "Scrub the knobs and watch the paired curves.",
        "Zero is always on the chart.",
        "Use Search fog to find the measured surprise.",
    ],
    "state-workflow": ["Step the workflow knobs.", "Compare base vs head transitions."],
    "queue-backlog": ["Scrub load; watch backlog grow."],
    "cache-efficiency": ["Scrub hit rate knobs; compare versions."],
    "custom": ["Scrub knobs; compare measured outputs."],
}


def select_world_genre(spec: InteractionSpec) -> WorldGenre:
    """Map an InteractionSpec domain pack onto a WorldGenre (mechanical)."""
    return _PACK_TO_GENRE.get(spec.domainPack, "custom")


def build_world_spec(spec: InteractionSpec) -> WorldSpec:
    """Emit a complete WorldSpec from a verified InteractionSpec."""
    genre = select_world_genre(spec)
    narration = spec.surpriseMarker.caption if spec.surpriseMarker is not None else spec.thesis
    return WorldSpec(
        genre=genre,
        stage=_GENRE_STAGE[genre],
        affordances=list(_GENRE_AFFORDANCES[genre]),
        narrationLine=narration,
        playHints=list(_GENRE_HINTS[genre])[:3],
    )


__all__ = [
    "Affordance",
    "StageConfig",
    "StageKind",
    "WorldGenre",
    "WorldSpec",
    "build_world_spec",
    "select_world_genre",
]
