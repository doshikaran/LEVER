"""Hero 1 coverage for Scout's static entry-point and dependency analysis."""

from pathlib import Path

import pytest

from domain.scout import scout
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hero1"
SYNTHETIC_BASE_PATH = "domain/tests/fixtures/synthetic_base.py"
SYNTHETIC_HEAD_PATH = "domain/tests/fixtures/synthetic_head.py"


@pytest.fixture
def non_pure_dependency_sources() -> tuple[str, str]:
    """A changed entry point with one statically recognizable call per non-pure kind."""
    base_source = """\
def exercise_dependencies():
    return None
"""
    head_source = """\
import ctypes
import random
import requests
import sqlite3
import time

def exercise_dependencies():
    return (
        time.time(),
        random.random(),
        open("/tmp/fixture.txt"),
        requests.get("https://example.test"),
        sqlite3.connect(":memory:"),
        ctypes.CDLL("libfixture.dylib"),
    )
"""
    return base_source, head_source


@pytest.fixture
def live_framework_input_sources() -> tuple[str, str]:
    """A changed callable requiring the live request type Scout must reject."""
    base_source = """\
def handle(incoming: HttpRequest):
    return "before"
"""
    head_source = """\
def handle(incoming: HttpRequest):
    return "after"
"""
    return base_source, head_source


def test_scout_selects_rate_limiter_admit_with_only_pure_dependencies() -> None:
    """Hero 1 accepts its clock as data and therefore needs no clock stub."""
    base_file_path = FIXTURE_DIR / "base.py"
    head_file_path = FIXTURE_DIR / "head.py"
    base_source = base_file_path.read_text(encoding="utf-8")
    head_source = head_file_path.read_text(encoding="utf-8")
    parser = TreeSitterPythonParser()

    result = scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
        str(base_file_path),
        str(head_file_path),
    )

    assert not result.unscopable
    assert result.entry_point is not None
    assert result.entry_point.file == str(head_file_path)
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
        SYNTHETIC_BASE_PATH,
        SYNTHETIC_HEAD_PATH,
    )

    assert result.entry_point is not None
    assert result.entry_point.file == SYNTHETIC_HEAD_PATH
    assert result.reach_depth == 2
    assert [node.name for node in result.reachable_nodes] == ["entry", "first", "second"]
    assert any(
        entry.name == "db.query" and entry.kind == "db" and entry.depth == 4
        for entry in result.dependency_ledger.entries
    )


def test_scout_classifies_every_non_pure_dependency_kind(
    non_pure_dependency_sources: tuple[str, str],
) -> None:
    """Every non-pure category must be exercised rather than defaulting to pure."""
    base_source, head_source = non_pure_dependency_sources
    parser = TreeSitterPythonParser()

    result = scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
        SYNTHETIC_BASE_PATH,
        SYNTHETIC_HEAD_PATH,
    )
    classifications = {
        entry.name: entry.kind for entry in result.dependency_ledger.entries
    }

    expected = {
        "time.time": "clock",
        "random.random": "random",
        "open": "io",
        "requests.get": "network",
        "sqlite3.connect": "db",
        "ctypes.CDLL": "native",
    }
    assert {name: classifications[name] for name in expected} == expected
    assert all(classifications[name] != "pure" for name in expected)


def test_scout_returns_a_specific_unscopable_reason_for_live_framework_input(
    live_framework_input_sources: tuple[str, str],
) -> None:
    """Live request objects fail loudly instead of receiving an unsafe harness."""
    base_source, head_source = live_framework_input_sources
    parser = TreeSitterPythonParser()

    result = scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
        SYNTHETIC_BASE_PATH,
        SYNTHETIC_HEAD_PATH,
    )

    assert result.unscopable
    assert result.entry_point is None
    assert result.reason == (
        "No changed function accepts only plain data: "
        "`handle` requires non-plain parameter `incoming: HttpRequest`."
    )
