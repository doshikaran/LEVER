"""GitHub PR resolver tests using recorded JSON (no network)."""

import json
from pathlib import Path

import httpx
import pytest

from domain.intake import InvalidPullRequestUrl
from infra.github.pr_resolver import GitHubPullRequestResolver, PullRequestResolveError

FIXTURES = Path(__file__).parent / "fixtures"


class _FixtureTransport(httpx.BaseTransport):
    """Serve canned GitHub API responses from disk."""

    def __init__(self, pull: dict, files: list[dict]) -> None:
        self._pull = pull
        self._files = files

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/files"):
            return httpx.Response(200, json=self._files)
        if "/pulls/" in path:
            return httpx.Response(200, json=self._pull)
        return httpx.Response(404, json={"message": "not found"})


def test_resolver_maps_recorded_pull_payload() -> None:
    pull = json.loads((FIXTURES / "pull.json").read_text())
    files = json.loads((FIXTURES / "files.json").read_text())
    resolver = GitHubPullRequestResolver(
        api_base="https://api.github.com",
        transport=_FixtureTransport(pull, files),
    )
    resolved = resolver.resolve("https://github.com/acme/widgets/pull/7")
    assert resolved.owner == "acme"
    assert resolved.repo == "widgets"
    assert resolved.number == 7
    assert resolved.base_sha == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert resolved.head_sha == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert [item.path for item in resolved.changed_files] == [
        "pkg/limiter.py",
        "tests/test_limiter.py",
        "README.md",
    ]


def test_resolver_rejects_invalid_url() -> None:
    resolver = GitHubPullRequestResolver(transport=_FixtureTransport({}, []))
    with pytest.raises(InvalidPullRequestUrl):
        resolver.resolve("https://example.com/not-a-pr")


def test_resolver_translates_404() -> None:
    class NotFound(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "Not Found"})

    resolver = GitHubPullRequestResolver(transport=NotFound())
    with pytest.raises(PullRequestResolveError):
        resolver.resolve("https://github.com/acme/widgets/pull/404")
