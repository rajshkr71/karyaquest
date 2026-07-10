from uuid import uuid4

from llm_gateway.redaction import REDACTED, redact_text, safe_log_metadata


def test_redact_text_masks_sensitive_values() -> None:
    unknown_uuid = str(uuid4())

    value = (
        "email=user@example.com "
        "Authorization: Bearer secret-token-123 "
        "api_key=super-secret "
        "password=hunter2 "
        f"unknown_id={unknown_uuid}"
    )

    redacted = redact_text(value)

    assert "user@example.com" not in redacted
    assert "secret-token-123" not in redacted
    assert "super-secret" not in redacted
    assert "hunter2" not in redacted
    assert unknown_uuid not in redacted
    assert REDACTED in redacted


def test_redact_text_preserves_explicit_request_id() -> None:
    request_id = str(uuid4())
    unknown_uuid = str(uuid4())

    value = f"request_id={request_id} unknown_id={unknown_uuid}"

    redacted = redact_text(
        value,
        preserve_request_id=request_id,
    )

    assert request_id in redacted
    assert unknown_uuid not in redacted


def test_safe_log_metadata_omits_raw_prompt_and_output() -> None:
    request_id = str(uuid4())

    metadata = safe_log_metadata(
        {
            "request_id": request_id,
            "provider": "fake",
            "model": "fake-model",
            "prompt_template": "Write about user@example.com",
            "variables": {"email": "user@example.com"},
            "output_text": "Generated confidential content",
            "latency_ms": 25,
        },
        request_id=request_id,
    )

    assert metadata["request_id"] == request_id
    assert metadata["provider"] == "fake"
    assert metadata["model"] == "fake-model"
    assert metadata["latency_ms"] == 25

    assert "prompt_template" not in metadata
    assert "variables" not in metadata
    assert "output_text" not in metadata


def test_safe_log_metadata_redacts_string_fields() -> None:
    metadata = safe_log_metadata(
        {
            "error_message": (
                "provider failed for user@example.com "
                "with password=secret123"
            ),
        }
    )

    error_message = metadata["error_message"]

    assert "user@example.com" not in error_message
    assert "secret123" not in error_message
    assert REDACTED in error_message


def test_safe_log_metadata_does_not_serialize_complex_values() -> None:
    metadata = safe_log_metadata(
        {
            "headers": {"Authorization": "Bearer secret-token"},
            "items": ["sensitive-value"],
        }
    )

    assert metadata["headers"] == "<dict>"
    assert metadata["items"] == "<list>"
