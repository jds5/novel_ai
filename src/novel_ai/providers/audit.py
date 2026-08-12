from __future__ import annotations

from typing import Any

from novel_ai.providers.contracts import ProviderResponse


def provider_audit_metadata(response: ProviderResponse) -> dict[str, Any]:
    """Map a response to safe relational metadata; raw payload is archived separately."""

    return {
        "provider": response.provider,
        "endpoint": response.endpoint,
        "model_snapshot": response.model,
        "response_status": response.status,
        "finish_reason": response.finish_reason,
        "provider_request_id": response.request_id,
        "provider_response_id": response.response_id,
        "response_item_types": list(response.output_item_types),
        "system_fingerprint": response.system_fingerprint,
        "latency_ms": response.latency_ms,
        "usage_json": response.usage,
    }
