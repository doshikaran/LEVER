"""No-network error handling coverage for the persistent E2B adapter."""

from types import SimpleNamespace

import pytest
from e2b import CommandExitException, SandboxNotFoundException

from infra.sandbox.e2b_adapter import E2BSandboxRuntime, SandboxExpiredError


class _MissingSandboxCommands:
    """Simulates E2B reporting that a retained sandbox no longer exists."""

    def run(self, command: str) -> None:
        raise SandboxNotFoundException("Sandbox sandbox-123 not found")


class _FailingCommands:
    """Simulates a nonzero guest process result from an otherwise-live sandbox."""

    def run(self, command: str) -> None:
        raise CommandExitException("guest stderr", "guest stdout", 7, None)


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


def test_run_code_returns_a_nonzero_guest_result_using_the_port_shape() -> None:
    """A guest failure remains an ordinary stdout/stderr/exit-code response."""
    runtime = object.__new__(E2BSandboxRuntime)
    runtime._sandboxes = {"sandbox-123": SimpleNamespace(commands=_FailingCommands())}

    assert runtime.run_code("sandbox-123", "raise SystemExit(7)") == {
        "stdout": "guest stdout",
        "stderr": "guest stderr",
        "exit_code": 7,
    }
