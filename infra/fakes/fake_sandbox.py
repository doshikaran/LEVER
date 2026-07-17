"""Local subprocess implementation of the sandbox runtime port for tests."""

import subprocess
import sys
from uuid import uuid4

from domain.ports import SandboxRuntime


class FakeSandboxRuntime(SandboxRuntime):
    """Runs Python snippets locally so domain tests do not use E2B."""

    def __init__(self) -> None:
        self._sandbox_ids: set[str] = set()

    def create_sandbox(self, template: str) -> str:
        """Create a local fake sandbox identifier."""
        sandbox_id = f"fake-{uuid4()}"
        self._sandbox_ids.add(sandbox_id)
        return sandbox_id

    def run_code(self, sandbox_id: str, code: str) -> dict:
        """Execute Python code locally and return its captured result."""
        if sandbox_id not in self._sandbox_ids:
            raise KeyError(f"Unknown sandbox: {sandbox_id}")

        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            check=False,
            text=True,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }

    def kill_sandbox(self, sandbox_id: str) -> None:
        """Remove a local fake sandbox identifier."""
        self._sandbox_ids.discard(sandbox_id)
