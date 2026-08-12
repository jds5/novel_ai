from novel_ai.providers.audit import provider_audit_metadata
from novel_ai.providers.contracts import CompletionStatus, ProviderName, ProviderResponse


def test_audit_metadata_excludes_raw_and_final_content() -> None:
    response = ProviderResponse(
        provider=ProviderName.DEEPSEEK,
        endpoint="https://api.deepseek.com/chat/completions",
        response_id="response-1",
        model="deepseek-snapshot",
        status=CompletionStatus.COMPLETED,
        finish_reason="stop",
        final_text="正文内容",
        refusal=None,
        output_item_types=("message", "reasoning_content"),
        usage={"total_tokens": 12},
        raw_payload={"reasoning_content": "私有推理", "content": "正文内容"},
        latency_ms=42,
        request_id="request-1",
        system_fingerprint="fingerprint-1",
    )

    metadata = provider_audit_metadata(response)

    assert metadata["provider"] == "deepseek"
    assert metadata["response_item_types"] == ["message", "reasoning_content"]
    assert "raw_payload" not in metadata
    assert "final_text" not in metadata
