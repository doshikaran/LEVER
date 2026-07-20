"""Fixtures for the Symmetrist's exact config-symmetry checks."""

import pytest

from domain.symmetrist import (
    DependencyChangeSet,
    four_way_symmetrist_check,
    symmetrist_check,
)


@pytest.fixture
def legitimate_new_dependency_configs() -> tuple[dict, dict]:
    """A Redis key exists only in head because the diff introduced Redis."""
    return (
        {
            "seed": "hero-1",
            "db.latency_ms": 5.0,
            "created_at": "2026-07-17T00:00:00Z",
        },
        {
            "seed": "hero-1",
            "db.latency_ms": 5.0,
            "created_at": "2026-07-18T00:00:00Z",
            "redis.latency_ms": 2.0,
        },
    )


@pytest.fixture
def asymmetric_shared_latency_configs() -> tuple[dict, dict]:
    """Both harnesses name the same DB latency key but give it different values."""
    return (
        {"seed": "hero-1", "db.latency_ms": 5.0},
        {"seed": "hero-1", "db.latency_ms": 20.0},
    )


def test_symmetrist_allows_a_diff_justified_new_dependency(
    legitimate_new_dependency_configs: tuple[dict, dict],
) -> None:
    """A key in the symmetric difference is allowed only when the diff adds it."""
    base_config, head_config = legitimate_new_dependency_configs

    result = symmetrist_check(
        base_config,
        head_config,
        diff_new_deps={"redis.latency_ms"},
        diff_removed_deps=set(),
    )

    assert result.passed
    assert result.unjustified_keys == []
    assert result.hash_a is not None
    assert result.hash_b is not None


def test_symmetrist_rejects_different_shared_mock_latency(
    asymmetric_shared_latency_configs: tuple[dict, dict],
) -> None:
    """Shared keys must hash byte-identically after canonicalization."""
    base_config, head_config = asymmetric_shared_latency_configs

    result = symmetrist_check(
        base_config,
        head_config,
        diff_new_deps=set(),
        diff_removed_deps=set(),
    )

    assert not result.passed
    assert result.unjustified_keys == ["db.latency_ms"]


def test_four_way_symmetrist_reports_the_pair_and_key_that_broke_symmetry() -> None:
    """Composition checks all six pairs rather than treating base as sufficient."""
    result = four_way_symmetrist_check(
        {
            "base": {},
            "A": {},
            "B": {"latency_ms": 5},
            "AB": {},
        }
    )

    assert not result.passed
    assert len(result.comparisons) == 6
    assert result.unjustified_keys == [
        "A:B:latency_ms",
        "B:AB:latency_ms",
        "base:B:latency_ms",
    ]


def test_four_way_symmetrist_derives_each_pairs_justification_from_a_or_b() -> None:
    """A's key is forbidden on base↔B even though it is allowed on base↔A."""
    a_changes = DependencyChangeSet(new_keys=frozenset({"a.stub"}))
    b_changes = DependencyChangeSet(new_keys=frozenset({"b.stub"}))
    valid = {
        "base": {},
        "A": {"a.stub": {"kind": "network"}},
        "B": {"b.stub": {"kind": "db"}},
        "AB": {
            "a.stub": {"kind": "network"},
            "b.stub": {"kind": "db"},
        },
    }

    result = four_way_symmetrist_check(valid, diff_a=a_changes, diff_b=b_changes)

    assert result.passed
    assert all(comparison.passed for comparison in result.comparisons.values())
    # A ↔ B is the derived (rather than adjacent) edge.  Its symmetric
    # difference is exactly {a.stub, b.stub}, the union J_A ∪ J_B, so its
    # shared-key hash comparison passes and produces ordinary canonical hashes.
    a_to_b = result.comparisons["A:B"]
    assert a_to_b.passed
    assert a_to_b.unjustified_keys == []
    assert a_to_b.hash_a is not None
    assert a_to_b.hash_b is not None

    # A key outside J_A ∪ J_B must fail the derived A ↔ B edge specifically.
    invalid_a = {
        **valid,
        "A": {"a.stub": {"kind": "network"}, "rogue.stub": {"kind": "io"}},
    }
    invalid_a_result = four_way_symmetrist_check(
        invalid_a, diff_a=a_changes, diff_b=b_changes
    )
    assert not invalid_a_result.comparisons["A:B"].passed
    assert invalid_a_result.comparisons["A:B"].unjustified_keys == ["rogue.stub"]
    assert "A:B:rogue.stub" in invalid_a_result.unjustified_keys

    # This is the regression for the original shared/global allowance bug:
    # a.stub belongs to diff A, so it cannot silently appear in B.
    invalid_b = {**valid, "B": {"a.stub": {"kind": "network"}, "b.stub": {"kind": "db"}}}
    invalid_result = four_way_symmetrist_check(
        invalid_b, diff_a=a_changes, diff_b=b_changes
    )

    assert not invalid_result.passed
    assert "base:B:a.stub" in invalid_result.unjustified_keys
    assert invalid_result.comparisons["base:B"].unjustified_keys == ["a.stub"]
