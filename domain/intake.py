"""Pure intake models and primary-file selection for Phase A PR checkouts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_PR_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/pull/"
    r"(?P<number>\d+)/?(?:[?#].*)?$",
    re.IGNORECASE,
)


class InvalidPullRequestUrl(ValueError):
    """Raised when a PR URL cannot be parsed into owner/repo/number."""


@dataclass(frozen=True)
class ChangedFile:
    """One path touched by the pull request, with GitHub's change status."""

    path: str
    status: str
    previous_path: str | None = None


@dataclass(frozen=True)
class ResolvedPullRequest:
    """Checkout coordinates and metadata for one GitHub pull request."""

    owner: str
    repo: str
    number: int
    title: str
    repo_url: str
    clone_url: str
    base_sha: str
    head_sha: str
    base_ref: str
    head_ref: str
    changed_files: tuple[ChangedFile, ...]


@dataclass(frozen=True)
class CheckoutHandle:
    """Materialized dual trees plus the Phase-A primary Python pair, if any."""

    work_root: Path
    base_root: Path
    head_root: Path
    resolved: ResolvedPullRequest
    primary_base_file: Path | None
    primary_head_file: Path | None
    selection_reason: str | None = None


def parse_github_pr_url(url: str) -> tuple[str, str, int]:
    """Extract (owner, repo, number) from a canonical github.com pull URL."""
    cleaned = url.strip()
    match = _PR_URL_RE.match(cleaned)
    if match is None:
        raise InvalidPullRequestUrl(
            "Expected a GitHub pull request URL like "
            "https://github.com/org/repo/pull/123"
        )
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def select_primary_python_pair(
    base_root: Path,
    head_root: Path,
    changed_files: tuple[ChangedFile, ...] | list[ChangedFile],
) -> tuple[Path, Path, str] | None:
    """Pick one shared Python module both trees can execute for the v2 pipeline.

    Phase A keeps Scout's single-file contract. Prefer modified non-test modules that
    exist on both sides; fall back to other shared ``.py`` paths. Pure adds/deletes
    cannot form a dual-checkout pair yet.
    """
    ranked: list[tuple[int, str, Path, Path]] = []
    for changed in changed_files:
        if changed.status == "removed":
            continue
        rel = changed.path
        if not rel.endswith(".py"):
            continue
        base_file = base_root / rel
        head_file = head_root / rel
        if changed.status == "renamed" and changed.previous_path:
            base_file = base_root / changed.previous_path
        if not base_file.is_file() or not head_file.is_file():
            continue
        rank = _selection_rank(rel)
        ranked.append((rank, rel, base_file.resolve(), head_file.resolve()))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]))
    _rank, rel, base_file, head_file = ranked[0]
    reason = f"Selected shared Python module `{rel}` as the Phase A primary pair."
    return base_file, head_file, reason


def _selection_rank(rel: str) -> int:
    """Lower ranks are preferred: non-test application modules first."""
    name = Path(rel).name
    parts = Path(rel).parts
    if name.startswith("test_") or name.endswith("_test.py") or "tests" in parts:
        return 2
    if name == "__init__.py":
        return 1
    return 0


__all__ = [
    "ChangedFile",
    "CheckoutHandle",
    "InvalidPullRequestUrl",
    "ResolvedPullRequest",
    "parse_github_pr_url",
    "select_primary_python_pair",
]
