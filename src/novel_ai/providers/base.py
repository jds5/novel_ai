from __future__ import annotations

from typing import Protocol

from novel_ai.providers.contracts import ModelRequest, ProviderCapabilities, ProviderResponse


class ModelProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def generate(self, request: ModelRequest) -> ProviderResponse: ...
