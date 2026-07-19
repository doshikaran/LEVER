"""Real E2B integration coverage for the persistent sandbox adapter."""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from domain.ports import SandboxRuntime
from infra.sandbox.e2b_adapter import E2BSandboxRuntime


load_dotenv(Path(__file__).resolve().parents[3] / ".env")
pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("E2B_API_KEY"),
    reason="requires a real E2B_API_KEY",
)
def test_e2b_adapter_reuses_one_sandbox_across_sequential_calls() -> None:
    """A sandbox-resident module written in call one remains available in calls two and three."""
    runtime = E2BSandboxRuntime()
    assert isinstance(runtime, SandboxRuntime)
    sandbox_id = runtime.create_sandbox("base")

    try:
        first = runtime.run_code(
            sandbox_id,
            "from pathlib import Path\n"
            "Path('/tmp/lever_shared_state.py').write_text('counter = 41\\n')\n"
            "print('initialized')",
        )
        second = runtime.run_code(
            sandbox_id,
            "from pathlib import Path\n"
            "state = {}\n"
            "exec(Path('/tmp/lever_shared_state.py').read_text(), state)\n"
            "Path('/tmp/lever_shared_state.py').write_text(f\"counter = {state['counter'] + 1}\\n\")\n"
            "print(state['counter'] + 1)",
        )
        third = runtime.run_code(
            sandbox_id,
            "from pathlib import Path\n"
            "state = {}\n"
            "exec(Path('/tmp/lever_shared_state.py').read_text(), state)\n"
            "print(state['counter'])",
        )

        assert first == {"stdout": "initialized\n", "stderr": "", "exit_code": 0}
        assert second == {"stdout": "42\n", "stderr": "", "exit_code": 0}
        assert third == {"stdout": "42\n", "stderr": "", "exit_code": 0}
    finally:
        runtime.kill_sandbox(sandbox_id)
