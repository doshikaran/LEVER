"""Canned LLM-client implementations for deterministic domain tests."""

from copy import deepcopy

from domain.ports import LLMClient


def _rate_limiter_response() -> dict:
    """Return a proposal that satisfies the rate-limiter arity contract."""
    return {
        "thesis": "The new limiter changes admitted requests as tenant load rises.",
        "domainPack": "rate-limiter",
        "knobs": [
            {
                "id": "rps",
                "label": "requests per second",
                "binding": {"kind": "driver", "param": "rps"},
                "type": "scalar",
                "domain": {"min": 1, "max": 1000, "step": 1},
                "default": 100,
                "scale": "log",
                "unit": "requests / sec",
            }
        ],
        "observables": [
            {
                "id": "admitted",
                "label": "admitted requests",
                "extractor": {"kind": "counter", "name": "admitted"},
                "render": "timeseries",
                "unit": "requests",
                "compareMode": "overlay",
            }
        ],
    }


def _invalid_rate_limiter_response() -> dict:
    """Return a rate-limiter proposal missing its required driver binding."""
    response = _rate_limiter_response()
    response["knobs"][0]["binding"] = {
        "kind": "argument",
        "fn": "RateLimiter.admit",
        "argIndex": 0,
    }
    return response


def _too_many_knobs_response() -> dict:
    """Return an otherwise-valid proposal that breaches the four-knob hard cap."""
    response = _rate_limiter_response()
    response["knobs"].extend(
        deepcopy(response["knobs"][0]) for _ in range(4)
    )
    return response


class FakeLLMClient(LLMClient):
    """Returns one of three deterministic canned Delta Analyst response scenarios."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = [deepcopy(response) for response in responses]
        self.prompts: list[str] = []
        self.schemas: list[dict] = []

    @classmethod
    def valid_rate_limiter(cls) -> "FakeLLMClient":
        """Return the canned response that succeeds on the first call."""
        return cls([_rate_limiter_response()])

    @classmethod
    def arity_then_correct(cls) -> "FakeLLMClient":
        """Return an invalid first response followed by a corrected response."""
        return cls([_invalid_rate_limiter_response(), _rate_limiter_response()])

    @classmethod
    def exhaust_retries(cls) -> "FakeLLMClient":
        """Exceed the hard cap twice, requiring numeric fallback."""
        return cls([_too_many_knobs_response(), _too_many_knobs_response()])

    def complete(self, prompt: str, schema: dict) -> dict:
        """Record the constrained request and return the next canned payload."""
        self.prompts.append(prompt)
        self.schemas.append(deepcopy(schema))
        if not self._responses:
            raise AssertionError("FakeLLMClient received more completions than configured")
        return self._responses.pop(0)
