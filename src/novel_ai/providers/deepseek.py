from __future__ import annotations

from typing import Any, NoReturn

import httpx

from novel_ai.providers.contracts import (
    ApiStyle,
    CompletionStatus,
    ModelRequest,
    ProviderCapabilities,
    ProviderName,
    ProviderResponse,
    StructuredOutputMode,
)
from novel_ai.providers.errors import ProviderConfigurationError, ProviderResponseError
from novel_ai.providers.http import post_json

DEEPSEEK_CAPABILITIES = ProviderCapabilities(
    provider=ProviderName.DEEPSEEK,
    api_style=ApiStyle.CHAT_COMPLETIONS,
    structured_output_mode=StructuredOutputMode.JSON_OBJECT,
    separates_reasoning_from_final=True,
    exposes_finish_reason=True,
    supports_streaming=False,
)


class DeepSeekChatProvider:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str | None,
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/chat/completions"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return DEEPSEEK_CAPABILITIES

    async def generate(self, request: ModelRequest) -> ProviderResponse:
        payload = self._build_payload(request)
        decoded, request_id, latency_ms = await post_json(
            self._client,
            provider=ProviderName.DEEPSEEK,
            url=self._url,
            api_key=self._api_key,
            payload=payload,
        )
        return self._parse_response(
            decoded,
            fallback_model=request.model,
            request_id=request_id,
            latency_ms=latency_ms,
        )

    def _build_payload(self, request: ModelRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        if request.output_schema is not None:
            if "json" not in f"{request.system}\n{request.user}".lower():
                raise ProviderConfigurationError(
                    "DeepSeek JSON Output requires the prompt to explicitly request JSON",
                    provider=ProviderName.DEEPSEEK,
                    code="JSON_INSTRUCTION_MISSING",
                    retryable=False,
                )
            payload["response_format"] = {"type": "json_object"}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.thinking_enabled is not None:
            payload["thinking"] = {"type": "enabled" if request.thinking_enabled else "disabled"}
        if request.reasoning_effort is not None:
            if request.reasoning_effort not in {"high", "max"}:
                raise ProviderConfigurationError(
                    "DeepSeek reasoning_effort must be high or max",
                    provider=ProviderName.DEEPSEEK,
                    code="UNSUPPORTED_REASONING_EFFORT",
                    retryable=False,
                )
            payload["reasoning_effort"] = request.reasoning_effort
        return payload

    def _parse_response(
        self,
        payload: dict[str, Any],
        *,
        fallback_model: str,
        request_id: str | None,
        latency_ms: int,
    ) -> ProviderResponse:
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            self._invalid("DeepSeek response must contain exactly one choice")
        choice = choices[0]
        if not isinstance(choice, dict):
            self._invalid("DeepSeek choice is not an object")
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            self._invalid("DeepSeek choice has no assistant message")
        if message.get("tool_calls"):
            self._invalid("DeepSeek returned an unexpected tool call")

        item_types = ["message"]
        if message.get("reasoning_content") is not None:
            item_types.append("reasoning_content")
        content = message.get("content")
        final_text = content if isinstance(content, str) and content else None
        refusal_value = message.get("refusal")
        refusal = refusal_value if isinstance(refusal_value, str) else None
        finish_value = choice.get("finish_reason")
        finish_reason = finish_value if isinstance(finish_value, str) else None
        if refusal is not None or finish_reason == "content_filter":
            status = CompletionStatus.REFUSED
        elif finish_reason == "stop" and final_text is not None:
            status = CompletionStatus.COMPLETED
        else:
            status = CompletionStatus.INCOMPLETE
            finish_reason = finish_reason or "empty_output"

        response_id = payload.get("id")
        model = payload.get("model")
        if not isinstance(response_id, str):
            self._invalid("DeepSeek response has no id")
        if not isinstance(model, str):
            model = fallback_model
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        system_fingerprint = payload.get("system_fingerprint")
        return ProviderResponse(
            provider=ProviderName.DEEPSEEK,
            endpoint=self._url,
            response_id=response_id,
            model=model,
            status=status,
            finish_reason=finish_reason,
            final_text=final_text,
            refusal=refusal,
            output_item_types=tuple(item_types),
            usage=usage,
            raw_payload=payload,
            latency_ms=latency_ms,
            request_id=request_id,
            system_fingerprint=(
                system_fingerprint if isinstance(system_fingerprint, str) else None
            ),
        )

    @staticmethod
    def _invalid(message: str) -> NoReturn:
        raise ProviderResponseError(
            message,
            provider=ProviderName.DEEPSEEK,
            code="INVALID_RESPONSE_SHAPE",
            retryable=True,
        )
