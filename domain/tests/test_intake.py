"""Unit coverage for Phase A intake URL parsing and primary-file selection."""

from pathlib import Path

import pytest

from domain.intake import (
    ChangedFile,
    InvalidPullRequestUrl,
    parse_github_pr_url,
    select_primary_python_pair,
)


def test_parse_github_pr_url_accepts_canonical_forms() -> None:
    assert parse_github_pr_url("https://github.com/openai/codex/pull/42") == (
        "openai",
        "codex",
        42,
    )
    assert parse_github_pr_url("https://github.com/openai/codex/pull/42/")[2] == 42


def test_parse_github_pr_url_rejects_non_pr_links() -> None:
    with pytest.raises(InvalidPullRequestUrl):
        parse_github_pr_url("https://github.com/openai/codex/issues/42")


def test_select_primary_python_pair_prefers_non_test_modules(tmp_path: Path) -> None:
    base = tmp_path / "base"
    head = tmp_path / "head"
    for root in (base, head):
        (root / "pkg").mkdir(parents=True)
        (root / "pkg" / "limiter.py").write_text("def admit():\n    return True\n")
        (root / "tests").mkdir()
        (root / "tests" / "test_limiter.py").write_text("def test_ok():\n    assert True\n")

    selected = select_primary_python_pair(
        base,
        head,
        (
            ChangedFile("tests/test_limiter.py", "modified"),
            ChangedFile("pkg/limiter.py", "modified"),
        ),
    )
    assert selected is not None
    base_file, head_file, reason = selected
    assert base_file.name == "limiter.py"
    assert head_file.name == "limiter.py"
    assert "pkg/limiter.py" in reason


def test_select_primary_python_pair_returns_none_without_shared_py(tmp_path: Path) -> None:
    base = tmp_path / "base"
    head = tmp_path / "head"
    base.mkdir()
    head.mkdir()
    (head / "new.py").write_text("x = 1\n")
    assert (
        select_primary_python_pair(
            base,
            head,
            (ChangedFile("new.py", "added"), ChangedFile("README.md", "modified")),
        )
        is None
    )
