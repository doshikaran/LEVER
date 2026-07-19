"""Persistent E2B implementation of the sandbox runtime port."""

import os
import shlex
from pathlib import Path

from dotenv import load_dotenv
from e2b import Sandbox, SandboxNotFoundException, TimeoutException

from domain.ports import SandboxRuntime


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TIMEOUT_SECONDS = 3_600
_EXPIRATION_MARKERS = (
    "sandbox timeout",
    "end of life",
    "no longer running",
    "sandbox was killed",
)


class SandboxExpiredError(RuntimeError):
    """Raised when a retained E2B sandbox has reached its end of life."""


class E2BSandboxRuntime(SandboxRuntime):
    """Keeps E2B sandboxes warm and reuses them for every code execution."""

    def __init__(self, timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        load_dotenv(_PROJECT_ROOT / ".env")
        if not os.getenv("E2B_API_KEY"):
            raise RuntimeError("E2B_API_KEY must be set in .env or the environment")

        self._timeout_seconds = timeout_seconds
        self._sandboxes: dict[str, Sandbox] = {}

    def create_sandbox(self, template: str) -> str:
        """Create one long-lived sandbox and retain its live SDK handle by ID."""
        sandbox = Sandbox.create(
            template=template or None,
            timeout=self._timeout_seconds,
        )
        self._sandboxes[sandbox.sandbox_id] = sandbox
        return sandbox.sandbox_id

    def run_code(self, sandbox_id: str, code: str) -> dict:
        """Run code in the retained sandbox without creating another VM."""
        sandbox = self._require_sandbox(sandbox_id)
        try:
            result = sandbox.commands.run(f"python3 -c {shlex.quote(code)}")
        except SandboxNotFoundException as error:
            self._raise_expired(sandbox_id, error)
        except TimeoutException as error:
            if _is_lifetime_expiration(error):
                self._raise_expired(sandbox_id, error)
            raise
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
        }

    def kill_sandbox(self, sandbox_id: str) -> None:
        """Explicitly tear down the retained E2B sandbox and discard its handle."""
        sandbox = self._require_sandbox(sandbox_id)
        try:
            sandbox.kill()
        finally:
            self._sandboxes.pop(sandbox_id, None)

    def _require_sandbox(self, sandbox_id: str) -> Sandbox:
        """Return a retained sandbox, never silently creating a replacement."""
        try:
            return self._sandboxes[sandbox_id]
        except KeyError as error:
            raise KeyError(f"Unknown or terminated sandbox: {sandbox_id}") from error

    def _raise_expired(self, sandbox_id: str, error: Exception) -> None:
        """Forget a dead handle and surface an actionable adapter-level error."""
        self._sandboxes.pop(sandbox_id, None)
        raise SandboxExpiredError(
            f"Sandbox {sandbox_id} expired or is no longer running; create a new sandbox."
        ) from error


def _is_lifetime_expiration(error: TimeoutException) -> bool:
    """Distinguish sandbox end-of-life from a command's own execution timeout."""
    message = str(error).lower()
    return any(marker in message for marker in _EXPIRATION_MARKERS)
