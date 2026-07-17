"""Hero 1 coverage for Scout's static entry-point and dependency analysis."""

from pathlib import Path

from domain.scout import scout
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero1"


def test_scout_selects_rate_limiter_admit_with_only_pure_dependencies() -> None:
    """Hero 1 accepts its clock as data and therefore needs no clock stub."""
    base_source = (FIXTURE_DIR / "base.py").read_text(encoding="utf-8")
    head_source = (FIXTURE_DIR / "head.py").read_text(encoding="utf-8")
    parser = TreeSitterPythonParser()

    result = scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
    )

    assert not result.unscopable
    assert result.entry_point is not None
    assert result.entry_point.fn == "RateLimiter.admit"
    assert result.reach_depth <= 2
    assert all(entry.kind == "pure" for entry in result.dependency_ledger.entries)


def test_scout_never_traverses_past_reach_depth_two() -> None:
    """Behavioral scope stops at depth two while the ledger reaches deep I/O."""
    base_source = """\
import db

def entry(value):
    return first(value)

def first(value):
    return second(value)

def second(value):
    return third(value)

def third(value):
    return db.query(value)
"""
    head_source = base_source.replace("return first(value)", "return first(value) + 1")
    parser = TreeSitterPythonParser()

    result = scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
    )

    assert result.reach_depth == 2
    assert [node.name for node in result.reachable_nodes] == ["entry", "first", "second"]
    assert any(
        entry.name == "db.query" and entry.kind == "db" and entry.depth == 4
        for entry in result.dependency_ledger.entries
    )
