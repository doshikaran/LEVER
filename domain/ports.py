"""Protocol interfaces that form the domain's only boundary to infrastructure."""

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from domain.intake import CheckoutHandle, ResolvedPullRequest


class SandboxExecutionError(RuntimeError):
    """A staged program failed to run inside the sandbox (non-zero exit).

    Subclasses ``RuntimeError`` so existing call sites and tests that expect a
    ``RuntimeError`` keep working, while letting the orchestrator distinguish a
    sandbox-side execution failure (which must degrade honestly) from an
    unexpected domain bug (which must not be silently swallowed).
    """


@runtime_checkable
class SandboxRuntime(Protocol):
    """Hexagonal port through which the domain controls sandbox infrastructure."""

    def create_sandbox(self, template: str) -> str: ...

    def run_code(self, sandbox_id: str, code: str) -> dict: ...

    def kill_sandbox(self, sandbox_id: str) -> None: ...


@runtime_checkable
class LLMClient(Protocol):
    """Hexagonal port through which the domain requests structured LLM output."""

    def complete(self, prompt: str, schema: dict) -> dict: ...


@runtime_checkable
class CodeParser(Protocol):
    """Hexagonal port through which the domain obtains parse trees from source."""

    def parse(self, source: str, language: str) -> Any: ...


@runtime_checkable
class Repository(Protocol):
    """Hexagonal port through which the domain persists and retrieves data."""

    def save(self, key: str, value: dict) -> None: ...

    def load(self, key: str) -> dict | None: ...

    def list_keys(self, *, limit: int = 50) -> list[str]:
        """Return recent ledger keys (newest first when the adapter can order)."""
        ...


@runtime_checkable
class PullRequestResolver(Protocol):
    """Hexagonal port that turns a hosting-provider PR URL into checkout coordinates."""

    def resolve(self, url: str) -> ResolvedPullRequest: ...


@runtime_checkable
class DualCheckout(Protocol):
    """Hexagonal port that materializes base and head trees for one resolved PR."""

    def materialize(self, resolved: ResolvedPullRequest, work_root: Path) -> CheckoutHandle: ...
