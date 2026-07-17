"""Fixtures for the Symmetrist's exact config-symmetry checks."""

import pytest

from domain.symmetrist import symmetrist_check


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
