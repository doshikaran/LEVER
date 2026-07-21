"""Local git dual-checkout materialization for resolved pull requests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from domain.intake import CheckoutHandle, ResolvedPullRequest, select_primary_python_pair


class DualCheckoutError(RuntimeError):
    """Raised when base/head trees cannot be materialized from git."""


class GitDualCheckout:
    """Implements DualCheckout with git clone + detached worktrees."""

    def __init__(
        self,
        *,
        git_binary: str = "git",
        timeout_seconds: float = 300.0,
        token: str | None = None,
    ) -> None:
        self._git_binary = git_binary
        self._timeout_seconds = timeout_seconds
        self._token = token if token is not None else os.getenv("GITHUB_TOKEN")

    def materialize(self, resolved: ResolvedPullRequest, work_root: Path) -> CheckoutHandle:
        """Clone the repository once and attach base/head worktrees at the PR SHAs."""
        work_root = work_root.expanduser().resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        mirror = work_root / "mirror"
        base_root = work_root / "base"
        head_root = work_root / "head"
        clone_url = _authenticated_clone_url(resolved.clone_url, self._token)

        try:
            if mirror.exists():
                self._git(mirror, "remote", "set-url", "origin", clone_url)
            else:
                self._run(
                    [
                        self._git_binary,
                        "clone",
                        "--no-checkout",
                        clone_url,
                        str(mirror),
                    ],
                    cwd=work_root,
                )

            # Ensure both PR SHAs exist locally. Public PRs usually resolve after a
            # normal fetch of the SHAs; fall back to the pull ref when needed.
            fetch_ok = self._try_fetch(mirror, resolved.base_sha, resolved.head_sha)
            if not fetch_ok:
                self._git(mirror, "fetch", "origin", f"pull/{resolved.number}/head:refs/lever/pr-head")
                self._git(mirror, "fetch", "origin", resolved.base_ref or "HEAD")
                fetch_ok = self._try_fetch(mirror, resolved.base_sha, resolved.head_sha)
            if not fetch_ok:
                raise DualCheckoutError(
                    f"Could not fetch base `{resolved.base_sha[:12]}` and head "
                    f"`{resolved.head_sha[:12]}` for {resolved.repo_url}."
                )

            self._reset_worktree(mirror, base_root, resolved.base_sha)
            self._reset_worktree(mirror, head_root, resolved.head_sha)
        except DualCheckoutError:
            raise
        except Exception as error:
            raise DualCheckoutError(f"Dual checkout failed: {error}") from error

        selected = select_primary_python_pair(
            base_root, head_root, resolved.changed_files
        )
        if selected is None:
            return CheckoutHandle(
                work_root=work_root,
                base_root=base_root,
                head_root=head_root,
                resolved=resolved,
                primary_base_file=None,
                primary_head_file=None,
                selection_reason=(
                    "No shared Python module exists on both base and head among the "
                    "PR's changed files. Phase A requires one dual-sided .py pair."
                ),
            )
        base_file, head_file, reason = selected
        return CheckoutHandle(
            work_root=work_root,
            base_root=base_root,
            head_root=head_root,
            resolved=resolved,
            primary_base_file=base_file,
            primary_head_file=head_file,
            selection_reason=reason,
        )

    def _reset_worktree(self, mirror: Path, target: Path, sha: str) -> None:
        """Create or replace a detached worktree at ``sha``."""
        if target.exists():
            # Drop a previous worktree registration if git still knows it.
            try:
                self._git(mirror, "worktree", "remove", "--force", str(target))
            except DualCheckoutError:
                shutil.rmtree(target)
        self._git(mirror, "worktree", "add", "--detach", "--force", str(target), sha)

    def _try_fetch(self, mirror: Path, base_sha: str, head_sha: str) -> bool:
        """Best-effort fetch of the two commit objects."""
        try:
            self._git(mirror, "fetch", "--update-head-ok", "origin", base_sha, head_sha)
        except DualCheckoutError:
            try:
                self._git(mirror, "fetch", "origin", base_sha)
                self._git(mirror, "fetch", "origin", head_sha)
            except DualCheckoutError:
                return self._object_exists(mirror, base_sha) and self._object_exists(
                    mirror, head_sha
                )
        return self._object_exists(mirror, base_sha) and self._object_exists(mirror, head_sha)

    def _object_exists(self, mirror: Path, sha: str) -> bool:
        result = subprocess.run(
            [self._git_binary, "-C", str(mirror), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=self._timeout_seconds,
        )
        return result.returncode == 0

    def _git(self, repo: Path, *args: str) -> None:
        self._run([self._git_binary, "-C", str(repo), *args], cwd=repo)

    def _run(self, command: list[str], *, cwd: Path) -> None:
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "echo",
            "GC_NO_PROMPT": "1",
        }
        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=self._timeout_seconds,
            env=env,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise DualCheckoutError(
                f"Command failed ({result.returncode}): {' '.join(command)}\n{detail[:800]}"
            )


def _authenticated_clone_url(clone_url: str, token: str | None) -> str:
    """Inject a GitHub token into https clone URLs when present."""
    if not token:
        return clone_url
    parsed = urlparse(clone_url)
    if parsed.scheme not in {"http", "https"} or "github.com" not in (parsed.hostname or ""):
        return clone_url
    netloc = f"x-access-token:{quote(token, safe='')}@{parsed.hostname}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


__all__ = ["DualCheckoutError", "GitDualCheckout"]
