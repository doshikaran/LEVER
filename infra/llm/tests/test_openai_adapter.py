"""Transport-lifetime tests for the OpenAI structured-output adapter."""

from __future__ import annotations

from typing import Any

from infra.llm.openai_adapter import OpenAIAdapter


def test_complete_uses_a_fresh_closed_client_with_a_hard_25_second_bound(
    monkeypatch,
) -> None:
    """Candidate generation and a kickback cannot reuse a stale HTTP connection."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    clients: list[_FakeOpenAI] = []

    class _FakeResponses:
        def create(self, **request: Any) -> _FakeResponse:
            self.owner.requests.append(request)
            return _FakeResponse('{"answer": 1}')

        def __init__(self, owner: _FakeOpenAI) -> None:
            self.owner = owner

    class _FakeOpenAI:
        def __init__(self, **configuration: Any) -> None:
            self.configuration = configuration
            self.requests: list[dict[str, Any]] = []
            self.closed = False
            self.responses = _FakeResponses(self)
            clients.append(self)

        def __enter__(self) -> _FakeOpenAI:
            return self

        def __exit__(self, *_: object) -> None:
            self.closed = True

    class _FakeResponse:
        def __init__(self, output_text: str) -> None:
            self.output_text = output_text

    monkeypatch.setattr("infra.llm.openai_adapter.OpenAI", _FakeOpenAI)
    # Pin the bound explicitly so an ambient LEVER_LLM_TIMEOUT_SECONDS (used to
    # widen the live demo budget) cannot make this wiring assertion flaky.
    adapter = OpenAIAdapter(
        model="test-model",
        reasoning_effort="high",
        request_timeout_seconds=25.0,
    )

    assert adapter.complete("first", {"type": "object", "properties": {"answer": {"type": "integer"}}}) == {"answer": 1}
    assert adapter.complete("second", {"type": "object", "properties": {"answer": {"type": "integer"}}}) == {"answer": 1}

    assert len(clients) == 2
    assert all(client.closed for client in clients)
    assert all(client.configuration["timeout"] == 25.0 for client in clients)
    assert all(client.configuration["max_retries"] == 0 for client in clients)
    assert [client.requests[0]["input"] for client in clients] == ["first", "second"]
