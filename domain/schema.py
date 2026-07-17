"""Pydantic schemas shared by deterministic domain analysis components."""

from typing import Literal

from pydantic import BaseModel, Field


DependencyKind = Literal["pure", "io", "clock", "random", "network", "db", "native"]


class AstNodeRef(BaseModel):
    """Stable source location for a Tree-sitter node involved in a change."""

    kind: str
    start_byte: int
    end_byte: int
    name: str | None = None


class EntryPoint(BaseModel):
    """A plain-data callable selected as the scoped execution entry point."""

    file: str | None = None
    fn: str
    signature: str


class DepEntry(BaseModel):
    """A statically discovered dependency and its deterministic classification."""

    name: str
    kind: DependencyKind
    depth: int = Field(ge=1)


class DependencyLedger(BaseModel):
    """Dependencies reachable from the selected entry point."""

    entries: list[DepEntry] = Field(default_factory=list)


class ScopedChangeSet(BaseModel):
    """The bounded behavioral scope passed from Scout to later pipeline stages."""

    entry_point: EntryPoint | None = None
    changed_nodes: list[AstNodeRef] = Field(default_factory=list)
    reachable_nodes: list[AstNodeRef] = Field(default_factory=list)
    dependency_ledger: DependencyLedger = Field(default_factory=DependencyLedger)
    reach_depth: int = Field(default=0, ge=0, le=2)
    unscopable: bool = False
    reason: str | None = None
