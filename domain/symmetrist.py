"""Canonical stub-config comparison that enforces harness symmetry."""

import hashlib
import json
import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Mapping


_DEFAULT_REPLICATE_SEED = "0"
_TIMESTAMP_KEYS = frozenset(
    {
        "created_at",
        "event_time",
        "timestamp",
        "updated_at",
    }
)


@dataclass(frozen=True)
class SymmetristResult:
    """Pass/fail result carrying canonical hashes or the offending config keys."""

    passed: bool
    unjustified_keys: list[str] = field(default_factory=list)
    hash_a: str | None = None
    hash_b: str | None = None


@dataclass(frozen=True)
class FourWaySymmetristResult:
    """All six pairwise symmetry checks required before a 2×2 can be trusted."""

    passed: bool
    comparisons: dict[str, SymmetristResult]
    unjustified_keys: list[str] = field(default_factory=list)
    harness_source_mismatches: list[str] = field(default_factory=list)


def canonicalize(stub_config: dict, replicate_seed: str) -> dict:
    """Apply the exact deterministic canonicalization required by the spec."""
    base_seed = stub_config.get("seed")
    canonical = _canonicalize_mapping(stub_config)
    canonical["seed"] = _hash_bytes(
        _canonical_json_bytes(
            {
                "base_seed": _canonicalize_value(base_seed),
                "replicate_seed": str(replicate_seed),
            }
        )
    )
    return {key: canonical[key] for key in sorted(canonical)}


def symmetrist_check(
    harness_a_config: dict,
    harness_b_config: dict,
    diff_new_deps: set[str],
    diff_removed_deps: set[str],
) -> SymmetristResult:
    """Implement the spec's symmetric-difference and shared-hash pseudocode."""
    canonical_a = canonicalize(harness_a_config, _DEFAULT_REPLICATE_SEED)
    canonical_b = canonicalize(harness_b_config, _DEFAULT_REPLICATE_SEED)

    keys_a, keys_b = set(canonical_a), set(canonical_b)
    symmetric_difference = keys_a ^ keys_b
    justified = diff_new_deps | diff_removed_deps
    unjustified = symmetric_difference - justified
    if unjustified:
        return SymmetristResult(passed=False, unjustified_keys=sorted(unjustified))

    for key in sorted(keys_a & keys_b):
        if _hash_bytes(_canonical_json_bytes(canonical_a[key])) != _hash_bytes(
            _canonical_json_bytes(canonical_b[key])
        ):
            return SymmetristResult(passed=False, unjustified_keys=[key])

    return SymmetristResult(
        passed=True,
        hash_a=_hash_bytes(_canonical_json_bytes(canonical_a)),
        hash_b=_hash_bytes(_canonical_json_bytes(canonical_b)),
    )


def four_way_symmetrist_check(
    harness_configs: Mapping[str, dict],
    diff_new_deps: set[str] | None = None,
    diff_removed_deps: set[str] | None = None,
) -> FourWaySymmetristResult:
    """Run Symmetrist over every pair of base, A, B, and actually executed AB.

    Configuration symmetry is intentionally checked pairwise rather than by
    assuming a common baseline: a non-identical shared stub is just as invalid
    between A and AB as it is between base and A.
    """
    variants = ("base", "A", "B", "AB")
    missing = sorted(set(variants) - set(harness_configs))
    unexpected = sorted(set(harness_configs) - set(variants))
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing variants: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected variants: {', '.join(unexpected)}")
        raise ValueError("four-way Symmetrist requires base, A, B, and AB; " + "; ".join(details))

    comparisons: dict[str, SymmetristResult] = {}
    offending: list[str] = []
    new_deps = diff_new_deps or set()
    removed_deps = diff_removed_deps or set()
    for left, right in combinations(variants, 2):
        result = symmetrist_check(
            harness_configs[left], harness_configs[right], new_deps, removed_deps
        )
        label = f"{left}:{right}"
        comparisons[label] = result
        offending.extend(f"{label}:{key}" for key in result.unjustified_keys)
    return FourWaySymmetristResult(
        passed=not offending,
        comparisons=comparisons,
        unjustified_keys=sorted(offending),
    )


def _canonicalize_mapping(value: dict) -> dict:
    """Sort a mapping recursively while normalizing timestamp values to epoch zero."""
    if not all(isinstance(key, str) for key in value):
        raise TypeError("Stub-config keys must be strings for canonical JSON")
    return {
        key: 0 if _is_timestamp_key(key) else _canonicalize_value(value[key])
        for key in sorted(value)
    }


def _canonicalize_value(value: Any) -> Any:
    """Recursively normalize mappings and sequences without mutating caller input."""
    if isinstance(value, dict):
        return _canonicalize_mapping(value)
    if isinstance(value, list):
        return [_canonicalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_canonicalize_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Canonical JSON does not permit non-finite floats")
    return value


def _is_timestamp_key(key: str) -> bool:
    """Recognize timestamp fields without mistaking durations such as latency for time."""
    lowered = key.lower()
    return (
        lowered in _TIMESTAMP_KEYS
        or lowered.endswith("_timestamp")
        or lowered.endswith("_at")
    )


def _canonical_json_bytes(value: Any) -> bytes:
    """Serialize canonical JSON with lexicographic keys, no whitespace, and 17-digit floats."""
    return _canonical_json(value).encode("utf-8")


def _canonical_json(value: Any) -> str:
    """Encode JSON deterministically, using repr-style 17 significant digits for floats."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".17g")
    if isinstance(value, list):
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Canonical JSON object keys must be strings")
        return "{" + ",".join(
            f"{_canonical_json(key)}:{_canonical_json(value[key])}" for key in sorted(value)
        ) + "}"
    raise TypeError(f"Unsupported stub-config value: {type(value).__name__}")


def _hash_bytes(value: bytes) -> str:
    """Return the SHA-256 digest of canonical UTF-8 JSON bytes."""
    return hashlib.sha256(value).hexdigest()
