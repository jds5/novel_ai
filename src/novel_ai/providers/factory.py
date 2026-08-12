from __future__ import annotations

import shutil

import httpx
from pydantic import SecretStr

from novel_ai.config import Settings
from novel_ai.providers.base import ModelProvider
from novel_ai.providers.codex_session import (
    CODEX_SESSION_CAPABILITIES,
    OpenAICodexSessionProvider,
)
from novel_ai.providers.contracts import ProviderDefinition, ProviderName
from novel_ai.providers.deepseek import DEEPSEEK_CAPABILITIES, DeepSeekChatProvider
from novel_ai.providers.gateway import ModelGateway, resolve_provider_name
from novel_ai.providers.openai import OPENAI_CAPABILITIES, OpenAIResponsesProvider


def provider_definitions(settings: Settings) -> tuple[ProviderDefinition, ...]:
    default_provider = resolve_provider_name(settings.default_model_provider)
    return (
        ProviderDefinition(
            capabilities=OPENAI_CAPABILITIES,
            default_model=settings.openai_default_model,
            configured=_secret_value(settings.openai_api_key) is not None,
            aliases=("chatgpt",),
            is_default=default_provider == ProviderName.OPENAI,
        ),
        ProviderDefinition(
            capabilities=CODEX_SESSION_CAPABILITIES,
            default_model=settings.codex_session_default_model,
            configured=_codex_session_configured(settings),
            aliases=("codex_session",),
            is_default=default_provider == ProviderName.OPENAI_CODEX_SESSION,
        ),
        ProviderDefinition(
            capabilities=DEEPSEEK_CAPABILITIES,
            default_model=settings.deepseek_default_model,
            configured=_secret_value(settings.deepseek_api_key) is not None,
            is_default=default_provider == ProviderName.DEEPSEEK,
        ),
    )


def build_model_gateway(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> ModelGateway:
    owned_client = None
    if client is None:
        owned_client = httpx.AsyncClient(timeout=settings.model_request_timeout_seconds)
        client = owned_client
    providers: dict[ProviderName, ModelProvider] = {
        ProviderName.OPENAI: OpenAIResponsesProvider(
            client=client,
            api_key=_secret_value(settings.openai_api_key),
            base_url=settings.openai_base_url,
        ),
        ProviderName.OPENAI_CODEX_SESSION: OpenAICodexSessionProvider(
            enabled=settings.codex_session_enabled,
            environment=settings.environment,
            executable=settings.codex_session_executable,
            timeout_seconds=settings.codex_session_timeout_seconds,
            auth_timeout_seconds=settings.codex_session_auth_timeout_seconds,
        ),
        ProviderName.DEEPSEEK: DeepSeekChatProvider(
            client=client,
            api_key=_secret_value(settings.deepseek_api_key),
            base_url=settings.deepseek_base_url,
        ),
    }
    return ModelGateway(providers, owned_client=owned_client)


def default_model_route(settings: Settings) -> tuple[ProviderName, str]:
    provider = resolve_provider_name(settings.default_model_provider)
    models = {
        ProviderName.OPENAI: settings.openai_default_model,
        ProviderName.OPENAI_CODEX_SESSION: settings.codex_session_default_model,
        ProviderName.DEEPSEEK: settings.deepseek_default_model,
    }
    return provider, models[provider]


def _secret_value(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    return value or None


def _codex_session_configured(settings: Settings) -> bool:
    local_environment = settings.environment.strip().lower() in {"local", "development", "test"}
    return (
        settings.codex_session_enabled
        and local_environment
        and shutil.which(settings.codex_session_executable) is not None
    )
