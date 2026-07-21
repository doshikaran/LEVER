"""Protocol interfaces that form the domain's only boundary to infrastructure."""

from typing import Any, Protocol, runtime_checkable


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

    def list_entries(self) -> list[dict]: ...
