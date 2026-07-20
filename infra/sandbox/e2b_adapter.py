"""Persistent E2B implementation of the sandbox runtime port."""

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
import os
import shlex
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from e2b import CommandExitException, Sandbox, SandboxNotFoundException, TimeoutException
from e2b.api.client_sync import TransportWithLogger

from domain.ports import SandboxRuntime


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TIMEOUT_SECONDS = 3_600
_DEFAULT_CREATION_TIMEOUT_SECONDS = 25.0
_EXPIRATION_MARKERS = (
    "sandbox timeout",
    "end of life",
    "no longer running",
    "sandbox was killed",
)


class SandboxExpiredError(RuntimeError):
    """Raised when a retained E2B sandbox has reached its end of life."""


class SandboxCreationTimeoutError(RuntimeError):
    """Raised when the E2B control plane does not create a sandbox promptly."""


class E2BSandboxRuntime(SandboxRuntime):
    """Keeps E2B sandboxes warm and reuses them for every code execution."""

    def __init__(
        self,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        creation_timeout_seconds: float = _DEFAULT_CREATION_TIMEOUT_SECONDS,
    ) -> None:
        load_dotenv(_PROJECT_ROOT / ".env")
        if not os.getenv("E2B_API_KEY"):
            raise RuntimeError("E2B_API_KEY must be set in .env or the environment")
        if creation_timeout_seconds <= 0:
            raise ValueError("creation_timeout_seconds must be positive")

        self._timeout_seconds = timeout_seconds
        self._creation_timeout_seconds = creation_timeout_seconds
        self._sandboxes: dict[str, Sandbox] = {}

    def create_sandbox(self, template: str) -> str:
        """Create one long-lived sandbox via a fresh, bounded control-plane connection."""
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lever-e2b-create")
        future = executor.submit(self._create_fresh_sandbox, template)
        try:
            sandbox = future.result(timeout=self._creation_timeout_seconds)
        except FutureTimeout as error:
            # Python cannot cancel an in-flight socket operation.  If E2B finishes
            # after the caller has timed out, dispose of that late sandbox instead
            # of silently leaking a billable resource.
            future.add_done_callback(_kill_late_sandbox)
            executor.shutdown(wait=False, cancel_futures=True)
            raise SandboxCreationTimeoutError(
                "Creating an E2B sandbox exceeded "
                f"{self._creation_timeout_seconds:g} seconds; no sandbox was retained."
            ) from error
        except Exception:
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)
        self._sandboxes[sandbox.sandbox_id] = sandbox
        return sandbox.sandbox_id

    def _create_fresh_sandbox(self, template: str) -> Sandbox:
        """Call E2B with no SDK control-plane transport retained from an earlier run."""
        _close_control_plane_transports()
        try:
            return Sandbox.create(
                template=template or None,
                timeout=self._timeout_seconds,
                request_timeout=self._creation_timeout_seconds,
            )
        finally:
            _close_control_plane_transports()

    def run_code(self, sandbox_id: str, code: str) -> dict:
        """Run code in the retained sandbox without creating another VM.

        Stage the program through E2B's filesystem rather than embedding it in
        ``python -c``.  Differential batches deliberately contain many sampled
        points and can exceed the operating system's command-argument limit.
        """
        sandbox = self._require_sandbox(sandbox_id)
        program_path = f"/tmp/lever-runtime/{uuid4().hex}.py"
        try:
            sandbox.files.write(program_path, code)
            result = sandbox.commands.run(f"python3 {shlex.quote(program_path)}")
        except SandboxNotFoundException as error:
            self._raise_expired(sandbox_id, error)
        except TimeoutException as error:
            if _is_lifetime_expiration(error):
                self._raise_expired(sandbox_id, error)
            raise
        except CommandExitException as error:
            # The port contract represents guest-program failures as data.  E2B
            # raises for these by default, which would otherwise bypass callers'
            # normal exit-code handling.
            return {
                "stdout": error.stdout,
                "stderr": error.stderr,
                "exit_code": error.exit_code,
            }
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


def _close_control_plane_transports() -> None:
    """Close the E2B SDK's thread-local HTTP/2 pool before and after creation."""
    instances = getattr(TransportWithLogger._thread_local, "instances", {})
    TransportWithLogger._thread_local.instances = {}
    for transport in instances.values():
        try:
            transport.close()
        except Exception:
            # A previous failed connection must never make the next creation fail.
            continue


def _kill_late_sandbox(future: Future[Sandbox]) -> None:
    """Tear down a sandbox that completed after the caller received a timeout."""
    try:
        sandbox = future.result()
    except BaseException:
        return
    try:
        sandbox.kill()
    except Exception:
        # There is no retained ID on the caller side; avoid an exception in a
        # callback masking the original named timeout.
        return
