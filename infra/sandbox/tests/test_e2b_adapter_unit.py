"""No-network error handling coverage for the persistent E2B adapter."""

import time
from types import SimpleNamespace

import pytest
from e2b import CommandExitException, SandboxNotFoundException

import infra.sandbox.e2b_adapter as e2b_adapter
from infra.sandbox.e2b_adapter import (
    E2BSandboxRuntime,
    SandboxCreationTimeoutError,
    SandboxExpiredError,
)


class _MissingSandboxCommands:
    """Simulates E2B reporting that a retained sandbox no longer exists."""

    def run(self, command: str) -> None:
        raise SandboxNotFoundException("Sandbox sandbox-123 not found")


class _Files:
    """Minimal file transport stand-in used before command execution."""

    def write(self, path: str, data: str) -> None:
        return None


class _FailingCommands:
    """Simulates a nonzero guest process result from an otherwise-live sandbox."""

    def run(self, command: str) -> None:
        raise CommandExitException("guest stderr", "guest stdout", 7, None)


def test_run_code_wraps_an_expired_sandbox_in_a_named_error() -> None:
    """A stale retained E2B handle never leaks an SDK-specific stack trace."""
    runtime = object.__new__(E2BSandboxRuntime)
    runtime._sandboxes = {
        "sandbox-123": SimpleNamespace(commands=_MissingSandboxCommands(), files=_Files())
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
    runtime._sandboxes = {
        "sandbox-123": SimpleNamespace(commands=_FailingCommands(), files=_Files())
    }

    assert runtime.run_code("sandbox-123", "raise SystemExit(7)") == {
        "stdout": "guest stdout",
        "stderr": "guest stderr",
        "exit_code": 7,
    }


def test_create_sandbox_closes_the_sdk_transport_pool_and_uses_the_creation_timeout(
    monkeypatch,
) -> None:
    """A new control-plane request cannot inherit a pooled connection from an old one."""
    closed: list[str] = []

    class _Transport:
        def close(self) -> None:
            closed.append("closed")

    fake_transport_class = SimpleNamespace(
        _thread_local=SimpleNamespace(instances={(True, None): _Transport()})
    )
    calls: list[dict] = []

    class _Sandbox:
        sandbox_id = "sandbox-fresh"

    def create(**kwargs):
        calls.append(kwargs)
        return _Sandbox()

    runtime = object.__new__(E2BSandboxRuntime)
    runtime._timeout_seconds = 3600
    runtime._creation_timeout_seconds = 0.25
    runtime._sandboxes = {}
    monkeypatch.setattr(e2b_adapter, "TransportWithLogger", fake_transport_class)
    monkeypatch.setattr(e2b_adapter.Sandbox, "create", create)

    assert runtime.create_sandbox("base") == "sandbox-fresh"
    assert closed == ["closed"]
    assert fake_transport_class._thread_local.instances == {}
    assert calls == [
        {"template": "base", "timeout": 3600, "request_timeout": 0.25}
    ]


def test_create_sandbox_times_out_loudly_and_kills_a_late_result(monkeypatch) -> None:
    """A hung control-plane call becomes a named 25-second-class failure, never silence."""
    late_sandbox = SimpleNamespace(sandbox_id="sandbox-late", killed=False)

    def kill() -> None:
        late_sandbox.killed = True

    late_sandbox.kill = kill

    def create(**_kwargs):
        time.sleep(0.05)
        return late_sandbox

    runtime = object.__new__(E2BSandboxRuntime)
    runtime._timeout_seconds = 3600
    runtime._creation_timeout_seconds = 0.01
    runtime._sandboxes = {}
    monkeypatch.setattr(e2b_adapter.Sandbox, "create", create)

    with pytest.raises(
        SandboxCreationTimeoutError,
        match="Creating an E2B sandbox exceeded 0.01 seconds; no sandbox was retained.",
    ):
        runtime.create_sandbox("base")

    time.sleep(0.1)
    assert late_sandbox.killed is True
    assert runtime._sandboxes == {}
