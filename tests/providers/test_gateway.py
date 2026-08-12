import asyncio
from dataclasses import dataclass

import pytest

from novel_ai.providers.base import ModelProvider
from novel_ai.providers.contracts import (
    ApiStyle,
    CompletionStatus,
    ModelRequest,
    ProviderCapabilities,
    ProviderName,
    ProviderResponse,
    StructuredOutputMode,
)
from novel_ai.providers.errors import ProviderCompletionError, StructuredOutputError
from novel_ai.providers.gateway import ModelGateway, resolve_provider_name


@dataclass
class FakeProvider(ModelProvider):
    response: ProviderResponse

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.response.provider,
            api_style=ApiStyle.CHAT_COMPLETIONS,
            structured_output_mode=StructuredOutputMode.JSON_OBJECT,
            separates_reasoning_from_final=True,
            exposes_finish_reason=True,
            supports_streaming=False,
        )

    async def generate(self, request: ModelRequest) -> ProviderResponse:
        return self.response


def response(text: str | None, status: CompletionStatus) -> ProviderResponse:
    return ProviderResponse(
        provider=ProviderName.DEEPSEEK,
        endpoint="https://api.deepseek.com/chat/completions",
        response_id="response-1",
        model="deepseek-test",
        status=status,
        finish_reason="stop" if status == CompletionStatus.COMPLETED else "length",
        final_text=text,
        refusal=None,
        output_item_types=("message",),
        usage={},
        raw_payload={},
        latency_ms=1,
    )


def model_request() -> ModelRequest:
    return ModelRequest(
        model="deepseek-test",
        system="返回 JSON。",
        user="生成。",
        max_output_tokens=100,
        output_schema={
            "type": "object",
            "required": ["prose"],
            "properties": {"prose": {"type": "string"}},
            "additionalProperties": False,
        },
        schema_name="test_v1",
    )


def test_gateway_validates_provider_json_against_local_schema() -> None:
    gateway = ModelGateway(
        {ProviderName.DEEPSEEK: FakeProvider(response('{"other":1}', CompletionStatus.COMPLETED))}
    )

    with pytest.raises(StructuredOutputError, match="local JSON Schema"):
        asyncio.run(gateway.generate("deepseek", model_request()))


def test_gateway_rejects_incomplete_output_before_json_parsing() -> None:
    gateway = ModelGateway(
        {ProviderName.DEEPSEEK: FakeProvider(response('{"prose":"截', CompletionStatus.INCOMPLETE))}
    )

    with pytest.raises(ProviderCompletionError) as raised:
        asyncio.run(gateway.generate("deepseek", model_request()))
    assert raised.value.retryable


def test_chatgpt_alias_resolves_to_openai() -> None:
    assert resolve_provider_name("chatgpt") == ProviderName.OPENAI


def test_codex_session_has_an_explicit_alias() -> None:
    assert resolve_provider_name("codex_session") == ProviderName.OPENAI_CODEX_SESSION
