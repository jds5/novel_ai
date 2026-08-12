"""Model-provider adapters behind a stable application contract."""

from novel_ai.providers.contracts import (
    CompletionStatus,
    GatewayOutput,
    ModelRequest,
    ProviderCapabilities,
    ProviderName,
    ProviderResponse,
)
from novel_ai.providers.gateway import ModelGateway

__all__ = [
    "CompletionStatus",
    "GatewayOutput",
    "ModelGateway",
    "ModelRequest",
    "ProviderCapabilities",
    "ProviderName",
    "ProviderResponse",
]
