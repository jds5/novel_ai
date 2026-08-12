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
from novel_ai.providers.errors import ProviderResponseError
from novel_ai.providers.http import post_json
from novel_ai.providers.strict_schema import normalize_openai_strict_schema

OPENAI_CAPABILITIES = ProviderCapabilities(
    provider=ProviderName.OPENAI,
    api_style=ApiStyle.RESPONSES,
    structured_output_mode=StructuredOutputMode.STRICT_JSON_SCHEMA,
    separates_reasoning_from_final=True,
    exposes_finish_reason=True,
    supports_streaming=False,
)


class OpenAIResponsesProvider:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str | None,
        base_url: str = "https://api.openai.com",
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/v1/responses"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return OPENAI_CAPABILITIES

    async def generate(self, request: ModelRequest) -> ProviderResponse:
        payload = self._build_payload(request)
        decoded, request_id, latency_ms = await post_json(
            self._client,
            provider=ProviderName.OPENAI,
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
            "instructions": request.system,
            "input": request.user,
            "max_output_tokens": request.max_output_tokens,
            "store": False,
        }
        if request.output_schema is not None and request.schema_name is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request.schema_name,
                    "schema": normalize_openai_strict_schema(request.output_schema),
                    "strict": True,
                }
            }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.reasoning_effort is not None:
            payload["reasoning"] = {"effort": request.reasoning_effort}
        return payload

    def _parse_response(
        self,
        payload: dict[str, Any],
        *,
        fallback_model: str,
        request_id: str | None,
        latency_ms: int,
    ) -> ProviderResponse:
        output = payload.get("output")
        if not isinstance(output, list):
            self._invalid("OpenAI response has no output item list")

        item_types: list[str] = []
        message_count = 0
        output_texts: list[str] = []
        refusals: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                self._invalid("OpenAI output item is not an object")
            item_type = item.get("type")
            if not isinstance(item_type, str):
                self._invalid("OpenAI output item has no type")
            item_types.append(item_type)
            if item_type == "reasoning":
                continue
            if item_type != "message":
                self._invalid(f"unexpected OpenAI output item type: {item_type}")
            message_count += 1
            if item.get("role") != "assistant":
                self._invalid("OpenAI final message is not from the assistant")
            content = item.get("content")
            if not isinstance(content, list):
                self._invalid("OpenAI message content is not a list")
            for content_item in content:
                if not isinstance(content_item, dict):
                    self._invalid("OpenAI message content item is not an object")
                content_type = content_item.get("type")
                item_types.append(str(content_type or "unknown_content"))
                if content_type == "output_text" and isinstance(content_item.get("text"), str):
                    output_texts.append(content_item["text"])
                elif content_type == "refusal" and isinstance(content_item.get("refusal"), str):
                    refusals.append(content_item["refusal"])
                else:
                    self._invalid(f"unexpected OpenAI message content type: {content_type}")

        if message_count > 1:
            self._invalid("OpenAI returned multiple final assistant messages")
        final_text = "".join(output_texts) or None
        refusal = "\n".join(refusals) or None
        provider_status = payload.get("status")
        finish_reason = _openai_finish_reason(payload)
        if refusal is not None:
            status = CompletionStatus.REFUSED
        elif provider_status == "completed" and final_text:
            status = CompletionStatus.COMPLETED
        else:
            status = CompletionStatus.INCOMPLETE
            finish_reason = finish_reason or "empty_output"

        response_id = payload.get("id")
        model = payload.get("model")
        if not isinstance(response_id, str):
            self._invalid("OpenAI response has no id")
        if not isinstance(model, str):
            model = fallback_model
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        system_fingerprint = payload.get("system_fingerprint")
        return ProviderResponse(
            provider=ProviderName.OPENAI,
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
            provider=ProviderName.OPENAI,
            code="INVALID_RESPONSE_SHAPE",
            retryable=True,
        )


def _openai_finish_reason(payload: dict[str, Any]) -> str | None:
    status = payload.get("status")
    if status == "completed":
        return "completed"
    details = payload.get("incomplete_details")
    if isinstance(details, dict):
        reason = details.get("reason")
        if isinstance(reason, str):
            return reason
    error = payload.get("error")
    if isinstance(error, dict):
        error_code = error.get("code")
        if isinstance(error_code, str):
            return error_code
    return status if isinstance(status, str) else None
