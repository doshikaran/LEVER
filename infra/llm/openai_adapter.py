"""OpenAI Responses API adapter for structured domain requests."""

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from domain.ports import LLMClient


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_NAME = "lever_response"


class OpenAIAdapter(LLMClient):
    """Infrastructure implementation of the domain's structured LLM port."""

    def __init__(self, model: str, reasoning_effort: str | None = None) -> None:
        load_dotenv(_PROJECT_ROOT / ".env")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set in .env or the environment")

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._reasoning_effort = reasoning_effort

    def complete(self, prompt: str, schema: dict) -> dict:
        request = {
            "model": self._model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _SCHEMA_NAME,
                    "schema": self._to_strict_json_schema(schema),
                    "strict": True,
                }
            },
        }
        if self._reasoning_effort is not None:
            request["reasoning"] = {"effort": self._reasoning_effort}

        response = self._client.responses.create(**request)
        return json.loads(response.output_text)

    @staticmethod
    def _to_strict_json_schema(schema: dict) -> dict:
        """Adapt a caller schema to the OpenAI strict JSON Schema subset."""
        strict_schema = deepcopy(schema)

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                one_of = value.pop("oneOf", None)
                if one_of is not None:
                    value["anyOf"] = one_of
                    value.pop("discriminator", None)

                properties = value.get("properties")
                if isinstance(properties, dict):
                    value["required"] = list(properties)
                if value.get("type") == "object" and "additionalProperties" not in value:
                    value["additionalProperties"] = False
                if "default" in value and value["default"] is None:
                    value.pop("default")
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(strict_schema)
        return strict_schema
