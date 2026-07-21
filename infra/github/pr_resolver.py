"""GitHub REST adapter for resolving public (or token-authenticated) pull requests."""

from __future__ import annotations

import os
from typing import Any

import httpx

from domain.intake import ChangedFile, InvalidPullRequestUrl, ResolvedPullRequest, parse_github_pr_url


class PullRequestResolveError(RuntimeError):
    """Raised when GitHub cannot return a usable pull-request payload."""


class GitHubPullRequestResolver:
    """Implements PullRequestResolver against api.github.com."""

    def __init__(
        self,
        *,
        token: str | None = None,
        api_base: str = "https://api.github.com",
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token if token is not None else os.getenv("GITHUB_TOKEN")
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def resolve(self, url: str) -> ResolvedPullRequest:
        """Fetch PR metadata and the changed-file list for dual checkout."""
        try:
            owner, repo, number = parse_github_pr_url(url)
        except InvalidPullRequestUrl:
            raise
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "lever-pr-intake",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        with httpx.Client(
            base_url=self._api_base,
            headers=headers,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            pull = self._get_json(client, f"/repos/{owner}/{repo}/pulls/{number}")
            files = self._list_files(client, owner, repo, number)

        base = pull.get("base") or {}
        head = pull.get("head") or {}
        base_repo = base.get("repo") or {}
        clone_url = base_repo.get("clone_url") or f"https://github.com/{owner}/{repo}.git"
        html_url = pull.get("html_url") or f"https://github.com/{owner}/{repo}/pull/{number}"
        base_sha = str(base.get("sha") or "")
        head_sha = str(head.get("sha") or "")
        if not base_sha or not head_sha:
            raise PullRequestResolveError(
                f"GitHub pull request {owner}/{repo}#{number} is missing base or head SHAs."
            )

        return ResolvedPullRequest(
            owner=owner,
            repo=repo.removesuffix(".git") if isinstance(repo, str) else repo,
            number=number,
            title=str(pull.get("title") or f"PR #{number}"),
            repo_url=f"https://github.com/{owner}/{repo}",
            clone_url=str(clone_url),
            base_sha=base_sha,
            head_sha=head_sha,
            base_ref=str(base.get("ref") or ""),
            head_ref=str(head.get("ref") or ""),
            changed_files=tuple(files),
        )

    def _list_files(
        self, client: httpx.Client, owner: str, repo: str, number: int
    ) -> list[ChangedFile]:
        """Page through the pull-request files endpoint."""
        changed: list[ChangedFile] = []
        page = 1
        while True:
            payload = self._get_json(
                client,
                f"/repos/{owner}/{repo}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            if not isinstance(payload, list) or not payload:
                break
            for item in payload:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("filename") or "")
                if not path:
                    continue
                previous = item.get("previous_filename")
                changed.append(
                    ChangedFile(
                        path=path,
                        status=str(item.get("status") or "modified"),
                        previous_path=str(previous) if previous else None,
                    )
                )
            if len(payload) < 100:
                break
            page += 1
            if page > 20:
                break
        return changed

    def _get_json(
        self,
        client: httpx.Client,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET a GitHub JSON resource and translate HTTP failures into domain errors."""
        response = client.get(path, params=params)
        if response.status_code == 404:
            raise PullRequestResolveError(
                f"GitHub could not find {path}. Check the URL or authentication."
            )
        if response.status_code == 401:
            raise PullRequestResolveError(
                "GitHub rejected credentials. Set GITHUB_TOKEN for private repositories."
            )
        if response.status_code == 403:
            raise PullRequestResolveError(
                "GitHub rate-limited or forbade this request. Set GITHUB_TOKEN and retry."
            )
        if response.status_code >= 400:
            raise PullRequestResolveError(
                f"GitHub API error {response.status_code} for {path}: {response.text[:300]}"
            )
        return response.json()


__all__ = [
    "GitHubPullRequestResolver",
    "PullRequestResolveError",
]
