from __future__ import annotations

import io
import json
import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from llm_gateway import audit_logging
from llm_gateway.audit_logging import log_audit_event
from llm_gateway.main import app, get_provider
from llm_gateway.models import LLMRequest, LLMResponse
from llm_gateway.provider import LLMProvider
from llm_gateway.settings import Settings, get_settings

client = TestClient(app)


class ExplodingProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("provider leaked user@example.com password=hunter2")


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> None:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def capture_audit_logs(caplog: pytest.LogCaptureFixture) -> None:
    audit_logging.configure_audit_logger()
    audit_logging.logger.addHandler(caplog.handler)
    yield
    audit_logging.logger.removeHandler(caplog.handler)


def valid_request(*, provider: str = "fake") -> dict[str, object]:
    return {
        "request_id": str(uuid4()),
        "task_type": "resume_generation",
        "prompt_template": "Generate content for user@example.com",
        "variables": {
            "email": "user@example.com",
            "authorization": "Bearer secret-token",
        },
        "provider": provider,
        "model": "fake-model",
        "temperature": 0.2,
        "max_output_tokens": 1024,
        "metadata": {
            "api_key": "secret-api-key",
            "password": "hunter2",
        },
    }


def audit_entries(
    caplog: pytest.LogCaptureFixture,
) -> list[dict[str, object]]:
    entries = []
    for record in caplog.records:
        if record.name == "llm_gateway.audit":
            assert "\n" not in record.message
            parsed_entry = json.loads(record.message)
            assert record.message == json.dumps(
                parsed_entry, separators=(",", ":"), sort_keys=False
            )
            entries.append(parsed_entry)
    return entries


def dedicated_audit_handlers() -> list[logging.StreamHandler]:
    handlers = [
        handler
        for handler in audit_logging.logger.handlers
        if getattr(handler, audit_logging.AUDIT_HANDLER_MARKER, False)
    ]
    assert all(isinstance(handler, logging.StreamHandler) for handler in handlers)
    return handlers


def test_audit_logger_enables_info_without_caplog_level_change() -> None:
    assert audit_logging.logger.level == logging.INFO
    assert audit_logging.logger.isEnabledFor(logging.INFO)


def test_audit_logger_has_exactly_one_dedicated_stream_handler() -> None:
    handlers = dedicated_audit_handlers()

    assert len(handlers) == 1


def test_audit_logger_configuration_is_idempotent() -> None:
    handler = dedicated_audit_handlers()[0]

    audit_logging.configure_audit_logger()
    audit_logging.configure_audit_logger()

    assert dedicated_audit_handlers() == [handler]


def test_audit_logger_configuration_removes_extra_marked_handlers() -> None:
    original_handlers = list(audit_logging.logger.handlers)
    for handler in original_handlers:
        audit_logging.logger.removeHandler(handler)

    retained_handler = logging.StreamHandler(io.StringIO())
    extra_handler = logging.StreamHandler(io.StringIO())
    unrelated_handler = logging.StreamHandler(io.StringIO())
    setattr(retained_handler, audit_logging.AUDIT_HANDLER_MARKER, True)
    setattr(extra_handler, audit_logging.AUDIT_HANDLER_MARKER, True)
    audit_logging.logger.addHandler(unrelated_handler)
    audit_logging.logger.addHandler(retained_handler)
    audit_logging.logger.addHandler(extra_handler)

    try:
        audit_logging.configure_audit_logger()

        assert dedicated_audit_handlers() == [retained_handler]
        assert unrelated_handler in audit_logging.logger.handlers
    finally:
        for handler in list(audit_logging.logger.handlers):
            audit_logging.logger.removeHandler(handler)
        for handler in original_handlers:
            audit_logging.logger.addHandler(handler)
        audit_logging.configure_audit_logger()


def test_audit_logger_propagation_is_disabled() -> None:
    assert audit_logging.logger.propagate is False


def test_audit_logger_emits_valid_compact_json_to_dedicated_handler() -> None:
    handler = dedicated_audit_handlers()[0]
    stream = io.StringIO()
    old_stream = handler.setStream(stream)

    try:
        log_audit_event(
            "llm.generate.started",
            request_id="request-123",
            outcome="started",
        )
    finally:
        handler.setStream(old_stream)

    output = stream.getvalue()
    line = output.removesuffix("\n")
    parsed_entry = json.loads(line)

    assert output == (
        json.dumps(parsed_entry, separators=(",", ":"), sort_keys=False) + "\n"
    )
    assert parsed_entry == {
        "schema_version": 1,
        "service": "llm-gateway",
        "event": "llm.generate.started",
        "outcome": "started",
        "request_id": "request-123",
    }


def test_audit_log_line_is_valid_compact_json_with_common_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log_audit_event(
        "llm.generate.started",
        request_id="request-123",
        outcome="started",
    )

    entries = audit_entries(caplog)

    assert entries == [
        {
            "schema_version": 1,
            "service": "llm-gateway",
            "event": "llm.generate.started",
            "outcome": "started",
            "request_id": "request-123",
        }
    ]


def test_success_emits_started_and_succeeded_events(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = valid_request()
    request_id = request["request_id"]
    app.dependency_overrides[get_settings] = lambda: Settings(
        provider="fake",
        model_version="configured-fake-v2",
    )

    response = client.post("/generate", json=request)

    assert response.status_code == 200
    entries = audit_entries(caplog)
    assert [entry["event"] for entry in entries] == [
        "llm.generate.started",
        "llm.generate.succeeded",
    ]
    assert [entry["outcome"] for entry in entries] == [
        "started",
        "succeeded",
    ]
    assert all(entry["request_id"] == request_id for entry in entries)


def test_success_contains_generation_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        provider="fake",
        model_version="configured-fake-v2",
    )

    response = client.post("/generate", json=valid_request())

    assert response.status_code == 200
    succeeded = audit_entries(caplog)[1]
    assert succeeded["model_version"] == "configured-fake-v2"
    assert succeeded["latency_ms"] == 0
    assert succeeded["input_tokens"] == 0
    assert succeeded["output_tokens"] == 3
    assert succeeded["finish_reason"] == "stop"
    assert succeeded["redaction_count"] == 0


def test_provider_mismatch_emits_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(provider="fake")

    response = client.post("/generate", json=valid_request(provider="openai"))

    assert response.status_code == 400
    entries = audit_entries(caplog)
    assert len(entries) == 1
    assert entries[0] | {
        "request_id": entries[0]["request_id"],
    } == {
        "schema_version": 1,
        "service": "llm-gateway",
        "event": "llm.generate.rejected",
        "outcome": "rejected",
        "request_id": entries[0]["request_id"],
        "task_type": "resume_generation",
        "requested_provider": "openai",
        "configured_provider": "fake",
        "model": "fake-model",
        "status_code": 400,
        "reason": "provider_mismatch",
    }


def test_unsupported_provider_emits_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        provider="unsupported",
    )

    response = client.post("/generate", json=valid_request())

    assert response.status_code == 503
    entries = audit_entries(caplog)
    assert entries == [
        {
            "schema_version": 1,
            "service": "llm-gateway",
            "event": "llm.provider.unavailable",
            "outcome": "unavailable",
            "configured_provider": "unsupported",
            "status_code": 503,
            "error_type": "UnsupportedProviderError",
        }
    ]


def test_provider_exception_emits_failed_without_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app.dependency_overrides[get_provider] = lambda: ExplodingProvider()

    with pytest.raises(RuntimeError):
        client.post("/generate", json=valid_request())

    raw_logs = "\n".join(record.message for record in caplog.records)
    assert "provider leaked" not in raw_logs
    assert "user@example.com" not in raw_logs
    assert "hunter2" not in raw_logs

    entries = audit_entries(caplog)
    assert [entry["event"] for entry in entries] == [
        "llm.generate.started",
        "llm.generate.failed",
    ]
    assert entries[1]["outcome"] == "failed"
    assert entries[1]["error_type"] == "RuntimeError"
    assert "error_message" not in entries[1]


def test_sensitive_request_fields_are_absent_and_values_are_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request_id = str(uuid4())
    unrelated_uuid = str(uuid4())

    log_audit_event(
        "llm.generate.succeeded",
        request_id=request_id,
        outcome="succeeded",
        prompt_template="Email user@example.com",
        variables={"email": "user@example.com"},
        metadata={"api_key": "secret-api-key"},
        output_text="Generated user@example.com",
        response_text="Bearer secret-token",
        output="password=hunter2",
        notes=(
            "email=user@example.com "
            "Authorization: Bearer secret-token "
            "api_key=secret-api-key "
            "password=hunter2 "
            f"related={request_id} unrelated={unrelated_uuid}"
        ),
        api_key="direct-secret-api-key",
        password="direct-password",
        complex_value={"token": "nested-secret"},
    )

    raw_logs = "\n".join(record.message for record in caplog.records)
    assert "user@example.com" not in raw_logs
    assert "secret-token" not in raw_logs
    assert "secret-api-key" not in raw_logs
    assert "direct-secret-api-key" not in raw_logs
    assert "hunter2" not in raw_logs
    assert "direct-password" not in raw_logs
    assert "nested-secret" not in raw_logs
    assert unrelated_uuid not in raw_logs

    entry = audit_entries(caplog)[0]
    assert entry["request_id"] == request_id
    assert request_id in entry["notes"]
    assert "prompt_template" not in entry
    assert "variables" not in entry
    assert "metadata" not in entry
    assert "output_text" not in entry
    assert "response_text" not in entry
    assert "output" not in entry
    assert entry["api_key"] == "[REDACTED]"
    assert entry["password"] == "[REDACTED]"
    assert entry["complex_value"] == "<dict>"


def test_logging_failure_does_not_fail_successful_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_on_log(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("logging sink failed")

    monkeypatch.setattr(audit_logging.logger, "log", raise_on_log)
    app.dependency_overrides[get_settings] = lambda: Settings(provider="fake")

    response = client.post("/generate", json=valid_request())

    assert response.status_code == 200
    assert response.json()["output_text"] == "Deterministic fake response"


def test_health_check_does_not_emit_audit_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert audit_entries(caplog) == []
