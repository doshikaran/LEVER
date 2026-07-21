"""GitHub intake package."""

from infra.github.pr_resolver import GitHubPullRequestResolver, PullRequestResolveError

__all__ = ["GitHubPullRequestResolver", "PullRequestResolveError"]
