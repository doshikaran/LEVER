"""Phase A PR intake and demo catalog API coverage."""

from pathlib import Path

from fastapi.testclient import TestClient

from domain.intake import ChangedFile, CheckoutHandle, ResolvedPullRequest
from domain.orchestrator import GracefulDegradation
from infra.fakes.fake_llm import FakeLLMClient
from infra.fakes.fake_sandbox import FakeSandboxRuntime
from interface.api import create_app
from interface.tests.test_api import _spec


class _FakeResolver:
    def __init__(self, resolved: ResolvedPullRequest) -> None:
        self._resolved = resolved

    def resolve(self, url: str) -> ResolvedPullRequest:
        return self._resolved


class _FakeCheckout:
    def __init__(self, handle: CheckoutHandle) -> None:
        self._handle = handle

    def materialize(self, resolved: ResolvedPullRequest, work_root: Path) -> CheckoutHandle:
        work_root.mkdir(parents=True, exist_ok=True)
        return self._handle


def test_health_and_demo_catalog(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "sessions.sqlite3")
    with TestClient(app) as client:
        assert client.get("/health").json()["phase"] == "F"
        demos = client.get("/demos").json()
        assert {item["id"] for item in demos} >= {"hero1", "hero3", "hero4"}


def test_post_prs_checkouts_then_streams_pipeline(tmp_path: Path) -> None:
    base = tmp_path / "pkg" / "limiter.py"
    head = tmp_path / "pkg" / "limiter.py"
    base.parent.mkdir(parents=True, exist_ok=True)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ref.py").write_text("def test_ok():\n    assert True\n")
    base.write_text("def admit():\n    return 1\n")
    # Same path content stands in for dual trees in the fake checkout handle.
    head.write_text("def admit():\n    return 2\n")

    resolved = ResolvedPullRequest(
        owner="acme",
        repo="widgets",
        number=7,
        title="Limiter",
        repo_url="https://github.com/acme/widgets",
        clone_url="https://github.com/acme/widgets.git",
        base_sha="a" * 40,
        head_sha="b" * 40,
        base_ref="main",
        head_ref="feature",
        changed_files=(ChangedFile("pkg/limiter.py", "modified"),),
    )
    handle = CheckoutHandle(
        work_root=tmp_path / "work",
        base_root=tmp_path,
        head_root=tmp_path,
        resolved=resolved,
        primary_base_file=base,
        primary_head_file=head,
        selection_reason="Selected shared Python module `pkg/limiter.py`.",
    )

    def scripted_runner(
        base_path,
        head_path,
        sandbox,
        llm,
        model,
        reasoning_effort,
        progress_callback,
        adversary_callback,
        search_trace_callback,
    ):
        progress_callback("files_touched", "1 file touched.")
        return GracefulDegradation(
            "Phase A pipeline reached orchestrator with PR provenance.",
            plain_explanation="ok",
        )

    app = create_app(
        database_path=tmp_path / "sessions.sqlite3",
        checkout_root=tmp_path / "checkouts",
        pr_resolver=_FakeResolver(resolved),
        dual_checkout=_FakeCheckout(handle),
        pipeline_runner=scripted_runner,
        runtime_factory=FakeSandboxRuntime,
        llm_factory=lambda *_: FakeLLMClient.valid_rate_limiter(),
    )
    with TestClient(app) as client:
        accepted = client.post("/prs", json={"url": "https://github.com/acme/widgets/pull/7"})
        assert accepted.status_code == 202
        change_id = accepted.json()["changeId"]
        with client.websocket_connect(f"/ws/{change_id}") as websocket:
            messages = []
            while True:
                message = websocket.receive_json()
                messages.append(message)
                if message.get("type") in {
                    "degraded",
                    "complete",
                    "error",
                    "skipped",
                    "unscopable",
                    "inert",
                }:
                    break
        assert any(item.get("type") == "progress" for item in messages)
        assert messages[-1]["type"] == "degraded"
        assert "Phase A pipeline reached orchestrator" in messages[-1]["degradeReason"]


def test_demo_run_uses_fixture_paths_without_browser_hardcoding(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def scripted_runner(
        base_path,
        head_path,
        sandbox,
        llm,
        model,
        reasoning_effort,
        progress_callback,
        adversary_callback,
        search_trace_callback,
    ):
        calls.append((base_path, head_path))
        progress_callback("files_touched", "1 file touched.")
        return _spec()

    app = create_app(
        database_path=tmp_path / "sessions.sqlite3",
        pipeline_runner=scripted_runner,
        runtime_factory=FakeSandboxRuntime,
        llm_factory=lambda *_: FakeLLMClient.valid_rate_limiter(),
    )
    with TestClient(app) as client:
        accepted = client.post("/demos/hero1/run")
        assert accepted.status_code == 202
        change_id = accepted.json()["changeId"]
        with client.websocket_connect(f"/ws/{change_id}") as websocket:
            while True:
                message = websocket.receive_json()
                if message.get("type") == "complete":
                    break
    assert calls
    assert calls[0][0].endswith("fixtures/hero1/base.py")
    assert calls[0][1].endswith("fixtures/hero1/head.py")
