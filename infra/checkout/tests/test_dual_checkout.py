"""Local-git dual checkout coverage without contacting GitHub."""

import subprocess
from pathlib import Path

from domain.intake import ChangedFile, ResolvedPullRequest
from infra.checkout.dual_checkout import GitDualCheckout


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _build_local_repo(root: Path) -> tuple[str, str, Path]:
    """Create a tiny git repo with base and head commits; return SHAs and bare URL path."""
    repo = root / "origin"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    _git(repo, "config", "user.email", "lever@example.com")
    _git(repo, "config", "user.name", "Lever")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "limiter.py").write_text("def admit():\n    return 1\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_limiter.py").write_text("def test_admit():\n    assert True\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repo / "pkg" / "limiter.py").write_text("def admit():\n    return 2\n")
    _git(repo, "add", "pkg/limiter.py")
    _git(repo, "commit", "-m", "head")
    head_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return base_sha, head_sha, repo


def test_git_dual_checkout_materializes_primary_pair(tmp_path: Path) -> None:
    base_sha, head_sha, origin = _build_local_repo(tmp_path)
    resolved = ResolvedPullRequest(
        owner="acme",
        repo="widgets",
        number=7,
        title="Sliding window",
        repo_url="https://github.com/acme/widgets",
        clone_url=str(origin),
        base_sha=base_sha,
        head_sha=head_sha,
        base_ref="main",
        head_ref="feature",
        changed_files=(
            ChangedFile("pkg/limiter.py", "modified"),
            ChangedFile("tests/test_limiter.py", "modified"),
        ),
    )
    handle = GitDualCheckout().materialize(resolved, tmp_path / "work")
    assert handle.primary_base_file is not None
    assert handle.primary_head_file is not None
    assert "return 1" in handle.primary_base_file.read_text()
    assert "return 2" in handle.primary_head_file.read_text()
    assert (handle.head_root / "tests" / "test_limiter.py").is_file()
