from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProviderName(StrEnum):
    OPENAI = "openai"
    OPENAI_CODEX_SESSION = "openai_codex_session"
    DEEPSEEK = "deepseek"


class ApiStyle(StrEnum):
    RESPONSES = "RESPONSES"
    CHAT_COMPLETIONS = "CHAT_COMPLETIONS"
    CODEX_EXEC = "CODEX_EXEC"


class StructuredOutputMode(StrEnum):
    STRICT_JSON_SCHEMA = "STRICT_JSON_SCHEMA"
    JSON_OBJECT = "JSON_OBJECT"


class CompletionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    provider: ProviderName
    api_style: ApiStyle
    structured_output_mode: StructuredOutputMode
    separates_reasoning_from_final: bool
    exposes_finish_reason: bool
    supports_streaming: bool
    supports_output_token_limit: bool = True
    production_eligible: bool = True
    requires_local_user_session: bool = False

    def public_metadata(self, *, configured: bool, default_model: str) -> dict[str, object]:
        return {
            "provider": self.provider,
            "api_style": self.api_style,
            "structured_output_mode": self.structured_output_mode,
            "separates_reasoning_from_final": self.separates_reasoning_from_final,
            "exposes_finish_reason": self.exposes_finish_reason,
            "supports_streaming": self.supports_streaming,
            "supports_output_token_limit": self.supports_output_token_limit,
            "production_eligible": self.production_eligible,
            "requires_local_user_session": self.requires_local_user_session,
            "configured": configured,
            "default_model": default_model,
        }


@dataclass(frozen=True, slots=True)
class ModelRequest:
    model: str
    system: str
    user: str
    max_output_tokens: int
    output_schema: dict[str, Any] | None = None
    schema_name: str | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None
    thinking_enabled: bool | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model is required")
        if not self.system.strip() or not self.user.strip():
            raise ValueError("system and user prompts are required")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if (self.output_schema is None) != (self.schema_name is None):
            raise ValueError("output_schema and schema_name must be supplied together")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    provider: ProviderName
    endpoint: str
    response_id: str
    model: str
    status: CompletionStatus
    finish_reason: str | None
    final_text: str | None
    refusal: str | None
    output_item_types: tuple[str, ...]
    usage: dict[str, Any]
    raw_payload: dict[str, Any] = field(repr=False)
    latency_ms: int
    request_id: str | None = None
    system_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class GatewayOutput:
    response: ProviderResponse
    text: str
    structured: object | None = None


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    capabilities: ProviderCapabilities
    default_model: str
    configured: bool
    aliases: tuple[str, ...] = field(default_factory=tuple)
    is_default: bool = False

    def public_metadata(self) -> dict[str, object]:
        metadata = self.capabilities.public_metadata(
            configured=self.configured, default_model=self.default_model
        )
        metadata["aliases"] = list(self.aliases)
        metadata["is_default"] = self.is_default
        return metadata
