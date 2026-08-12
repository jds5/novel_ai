from __future__ import annotations

import json
from collections.abc import Mapping

import httpx
from jsonschema import ValidationError, validate

from novel_ai.prompts.models import RenderedPrompt
from novel_ai.providers.base import ModelProvider
from novel_ai.providers.contracts import (
    CompletionStatus,
    GatewayOutput,
    ModelRequest,
    ProviderName,
)
from novel_ai.providers.errors import (
    ProviderCompletionError,
    ProviderConfigurationError,
    StructuredOutputError,
)

_PROVIDER_ALIASES = {
    "openai": ProviderName.OPENAI,
    "chatgpt": ProviderName.OPENAI,
    "openai_codex_session": ProviderName.OPENAI_CODEX_SESSION,
    "codex_session": ProviderName.OPENAI_CODEX_SESSION,
    "deepseek": ProviderName.DEEPSEEK,
}


class ModelGateway:
    def __init__(
        self,
        providers: Mapping[ProviderName, ModelProvider],
        *,
        owned_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._providers = dict(providers)
        self._owned_client = owned_client

    async def generate(self, provider: ProviderName | str, request: ModelRequest) -> GatewayOutput:
        provider_name = resolve_provider_name(provider)
        try:
            adapter = self._providers[provider_name]
        except KeyError as exc:
            raise ProviderConfigurationError(
                f"provider {provider_name} is not registered",
                provider=provider_name,
                code="PROVIDER_NOT_REGISTERED",
                retryable=False,
            ) from exc
        response = await adapter.generate(request)
        if response.status != CompletionStatus.COMPLETED or response.final_text is None:
            raise ProviderCompletionError(
                f"{provider_name} generation did not complete: {response.finish_reason}",
                provider=provider_name,
                code=response.status,
                retryable=response.status == CompletionStatus.INCOMPLETE,
            )
        if request.output_schema is None:
            return GatewayOutput(response=response, text=response.final_text)
        try:
            structured: object = json.loads(response.final_text)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(
                f"{provider_name} returned invalid JSON",
                provider=provider_name,
                code="INVALID_OUTPUT_JSON",
                retryable=True,
            ) from exc
        try:
            validate(instance=structured, schema=request.output_schema)
        except ValidationError as exc:
            raise StructuredOutputError(
                f"{provider_name} output failed local JSON Schema validation: {exc.message}",
                provider=provider_name,
                code="OUTPUT_SCHEMA_MISMATCH",
                retryable=True,
            ) from exc
        return GatewayOutput(response=response, text=response.final_text, structured=structured)

    async def generate_prompt(
        self,
        provider: ProviderName | str,
        *,
        model: str,
        prompt: RenderedPrompt,
        max_output_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        thinking_enabled: bool | None = None,
    ) -> GatewayOutput:
        schema_name = (
            f"{prompt.key}_v{prompt.version}" if prompt.output_schema is not None else None
        )
        request = ModelRequest(
            model=model,
            system=prompt.system,
            user=prompt.user,
            max_output_tokens=max_output_tokens,
            output_schema=prompt.output_schema,
            schema_name=schema_name,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            thinking_enabled=thinking_enabled,
        )
        return await self.generate(provider, request)

    async def aclose(self) -> None:
        if self._owned_client is not None:
            await self._owned_client.aclose()


def resolve_provider_name(provider: ProviderName | str) -> ProviderName:
    if isinstance(provider, ProviderName):
        return provider
    try:
        return _PROVIDER_ALIASES[provider.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"unknown model provider: {provider}") from exc
