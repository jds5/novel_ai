from __future__ import annotations

import time
from typing import Any

import httpx

from novel_ai.providers.contracts import ProviderName
from novel_ai.providers.errors import ProviderResponseError, ProviderTransportError


async def post_json(
    client: httpx.AsyncClient,
    *,
    provider: ProviderName,
    url: str,
    api_key: str | None,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str | None, int]:
    if not api_key:
        from novel_ai.providers.errors import ProviderConfigurationError

        raise ProviderConfigurationError(
            f"{provider} API key is not configured",
            provider=provider,
            code="API_KEY_MISSING",
            retryable=False,
        )
    started = time.perf_counter()
    try:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    except httpx.TimeoutException as exc:
        raise ProviderTransportError(
            f"{provider} request timed out",
            provider=provider,
            code="TIMEOUT",
            retryable=True,
        ) from exc
    except httpx.TransportError as exc:
        raise ProviderTransportError(
            f"{provider} transport failed",
            provider=provider,
            code="TRANSPORT_ERROR",
            retryable=True,
        ) from exc
    latency_ms = round((time.perf_counter() - started) * 1000)
    request_id = response.headers.get("x-request-id")
    if not response.is_success:
        error_code = _http_error_code(response.status_code)
        raise ProviderTransportError(
            _safe_http_error_message(provider, response),
            provider=provider,
            code=error_code,
            retryable=response.status_code == 429 or response.status_code >= 500,
            status_code=response.status_code,
        )
    try:
        decoded = response.json()
    except ValueError as exc:
        raise ProviderResponseError(
            f"{provider} returned a non-JSON response",
            provider=provider,
            code="INVALID_RESPONSE_JSON",
            retryable=True,
            status_code=response.status_code,
        ) from exc
    if not isinstance(decoded, dict):
        raise ProviderResponseError(
            f"{provider} response root is not an object",
            provider=provider,
            code="INVALID_RESPONSE_SHAPE",
            retryable=True,
            status_code=response.status_code,
        )
    return decoded, request_id, latency_ms


def _http_error_code(status_code: int) -> str:
    if status_code in {401, 403}:
        return "AUTHENTICATION_ERROR"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code >= 500:
        return "PROVIDER_UNAVAILABLE"
    return "INVALID_REQUEST"


def _safe_http_error_message(provider: ProviderName, response: httpx.Response) -> str:
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                detail = f": {error['message'][:300]}"
    except ValueError:
        pass
    return f"{provider} returned HTTP {response.status_code}{detail}"
