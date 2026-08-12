from __future__ import annotations

from novel_ai.providers.contracts import ProviderName


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: ProviderName,
        code: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class ProviderConfigurationError(ProviderError):
    pass


class ProviderTransportError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


class ProviderCompletionError(ProviderError):
    pass


class StructuredOutputError(ProviderError):
    pass
