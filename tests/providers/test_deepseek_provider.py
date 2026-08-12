import asyncio
import json

import httpx

from novel_ai.providers.contracts import CompletionStatus, ModelRequest
from novel_ai.providers.deepseek import DeepSeekChatProvider


def test_deepseek_uses_json_output_and_never_appends_reasoning_content() -> None:
    captured: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured["path"] = http_request.url.path
        captured["body"] = json.loads(http_request.content)
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "model": "deepseek-test-snapshot",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "这部分绝不能进入正文",
                            "content": '{"prose":"门开了。"}',
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekChatProvider(client=client, api_key="secret")
            response = await provider.generate(
                ModelRequest(
                    model="deepseek-test",
                    system="只返回 JSON。",
                    user="生成正文。",
                    max_output_tokens=1000,
                    output_schema={"type": "object"},
                    schema_name="scene_prose_v1",
                    thinking_enabled=False,
                )
            )
        assert response.status == CompletionStatus.COMPLETED
        assert response.final_text == '{"prose":"门开了。"}'
        assert response.output_item_types == ("message", "reasoning_content")

    asyncio.run(run())
    assert captured["path"] == "/chat/completions"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}


def test_deepseek_length_finish_is_incomplete() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "model": "deepseek-test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": '{"prose":"截'},
                    }
                ],
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekChatProvider(client=client, api_key="secret")
            response = await provider.generate(
                ModelRequest(
                    model="deepseek-test",
                    system="返回 JSON。",
                    user="生成。",
                    max_output_tokens=10,
                    output_schema={"type": "object"},
                    schema_name="test_v1",
                )
            )
        assert response.status == CompletionStatus.INCOMPLETE
        assert response.finish_reason == "length"

    asyncio.run(run())
