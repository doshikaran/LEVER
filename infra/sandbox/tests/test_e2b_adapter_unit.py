"""No-network error handling coverage for the persistent E2B adapter."""

from types import SimpleNamespace

import pytest
from e2b import SandboxNotFoundException

from infra.sandbox.e2b_adapter import E2BSandboxRuntime, SandboxExpiredError


class _MissingSandboxCommands:
    """Simulates E2B reporting that a retained sandbox no longer exists."""

    def run(self, command: str) -> None:
        raise SandboxNotFoundException("Sandbox sandbox-123 not found")


def test_run_code_wraps_an_expired_sandbox_in_a_named_error() -> None:
    """A stale retained E2B handle never leaks an SDK-specific stack trace."""
    runtime = object.__new__(E2BSandboxRuntime)
    runtime._sandboxes = {
        "sandbox-123": SimpleNamespace(commands=_MissingSandboxCommands())
    }

    with pytest.raises(
        SandboxExpiredError,
        match="Sandbox sandbox-123 expired or is no longer running; create a new sandbox.",
    ) as raised:
        runtime.run_code("sandbox-123", "print('hello')")

    assert isinstance(raised.value.__cause__, SandboxNotFoundException)
    assert "sandbox-123" not in runtime._sandboxes
