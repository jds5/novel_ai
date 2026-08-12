import asyncio
import json

import httpx
import pytest

from novel_ai.providers.contracts import CompletionStatus, ModelRequest
from novel_ai.providers.errors import ProviderTransportError
from novel_ai.providers.openai import OpenAIResponsesProvider


def request() -> ModelRequest:
    return ModelRequest(
        model="gpt-test",
        system="Return JSON only.",
        user="Write one scene.",
        max_output_tokens=1000,
        output_schema={
            "type": "object",
            "required": ["prose"],
            "properties": {"prose": {"type": "string"}},
            "additionalProperties": False,
        },
        schema_name="scene_prose_v1",
        reasoning_effort="low",
    )


def test_openai_uses_responses_strict_schema_and_ignores_reasoning_items() -> None:
    captured: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured["path"] = http_request.url.path
        captured["body"] = json.loads(http_request.content)
        return httpx.Response(
            200,
            headers={"x-request-id": "request-1"},
            json={
                "id": "response-1",
                "model": "gpt-test-snapshot",
                "status": "completed",
                "output": [
                    {"type": "reasoning", "id": "reasoning-1", "summary": []},
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": '{"prose":"雨落下来。"}'}],
                    },
                ],
                "usage": {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesProvider(client=client, api_key="secret")
            response = await provider.generate(request())

        assert response.status == CompletionStatus.COMPLETED
        assert response.final_text == '{"prose":"雨落下来。"}'
        assert response.output_item_types == ("reasoning", "message", "output_text")
        assert response.request_id == "request-1"

    asyncio.run(run())
    assert captured["path"] == "/v1/responses"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["store"] is False
    assert body["text"]["format"] == {
        "type": "json_schema",
        "name": "scene_prose_v1",
        "schema": {
            "type": "object",
            "required": ["prose"],
            "properties": {"prose": {"type": "string"}},
            "additionalProperties": False,
        },
        "strict": True,
    }
    assert body["reasoning"] == {"effort": "low"}


def test_openai_rate_limit_is_normalized_as_retryable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesProvider(client=client, api_key="secret")
            with pytest.raises(ProviderTransportError) as raised:
                await provider.generate(request())
        assert raised.value.code == "RATE_LIMITED"
        assert raised.value.retryable
        assert raised.value.status_code == 429

    asyncio.run(run())
