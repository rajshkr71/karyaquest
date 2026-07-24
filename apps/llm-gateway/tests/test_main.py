from uuid import uuid4
from unittest.mock import Mock, patch

import httpx
import openai
from fastapi.testclient import TestClient

from llm_gateway.main import app, get_provider
from llm_gateway.provider import LLMProvider
from llm_gateway.settings import Settings, get_settings

client = TestClient(app)


def valid_request(*, provider: str = "fake") -> dict[str, object]:
    return {
        "request_id": str(uuid4()),
        "task_type": "resume_generation",
        "prompt_template": "Generate content",
        "variables": {"job_title": "Platform Engineer"},
        "provider": provider,
        "model": "fake-model",
        "temperature": 0.2,
        "max_output_tokens": 1024,
        "metadata": {"job_id": "job-123"},
    }


def test_healthz() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "llm-gateway",
    }


def test_generate_uses_configured_fake_provider() -> None:
    request = valid_request()
    request_id = request["request_id"]

    app.dependency_overrides[get_settings] = lambda: Settings(
        provider="fake",
        model_version="configured-fake-v2",
    )

    try:
        response = client.post("/generate", json=request)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "request_id": request_id,
        "provider": "fake",
        "model": "fake-model",
        "model_version": "configured-fake-v2",
        "output_text": "Deterministic fake response",
        "input_tokens": 0,
        "output_tokens": 3,
        "latency_ms": 0,
        "finish_reason": "stop",
        "redactions_applied": [],
    }


def test_generate_rejects_provider_mismatch() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        provider="fake",
    )

    try:
        response = client.post(
            "/generate",
            json=valid_request(provider="openai"),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json() == {
        "detail": "requested provider does not match configured provider"
    }


def test_generate_returns_503_for_unsupported_configured_provider() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        provider="unsupported",
    )

    try:
        response = client.post(
            "/generate",
            json=valid_request(),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "detail": "configured provider is unavailable"
    }


def test_generate_maps_openai_rate_limit_error_to_safe_429() -> None:
    error = openai.RateLimitError(
        "rate limited: sk-secret project=proj-secret prompt=private",
        response=httpx.Response(
            429,
            headers={"x-sensitive": "quota-secret"},
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        ),
        body={"error": {"type": "rate_limit_exceeded", "output": "private"}},
    )

    _assert_safe_rate_limit_response(error)


def test_generate_maps_insufficient_quota_to_safe_429() -> None:
    error = openai.RateLimitError(
        "insufficient_quota for project proj-secret",
        response=httpx.Response(
            429,
            headers={"x-sensitive": "quota-secret"},
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        ),
        body={"error": {"type": "insufficient_quota", "api_key": "sk-secret"}},
    )

    _assert_safe_rate_limit_response(error)


def _assert_safe_rate_limit_response(error: openai.RateLimitError) -> None:
    provider = Mock(spec=LLMProvider)
    provider.name = "fake"
    provider.generate.side_effect = error
    app.dependency_overrides[get_provider] = lambda: provider

    try:
        with patch("llm_gateway.main.log_audit_event") as log_audit_event:
            response = client.post("/generate", json=valid_request())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.json() == {
        "detail": "upstream provider rate limit exceeded"
    }
    failed_call = next(
        call
        for call in log_audit_event.call_args_list
        if call.args == ("llm.generate.failed",)
    )
    assert failed_call.kwargs["error_type"] == "RateLimitError"


def test_generate_rejects_blank_model() -> None:
    request = valid_request()
    request["model"] = "   "

    response = client.post("/generate", json=request)

    assert response.status_code == 422


def test_generate_rejects_invalid_temperature() -> None:
    request = valid_request()
    request["temperature"] = 2.1

    response = client.post("/generate", json=request)

    assert response.status_code == 422


def test_generate_rejects_unknown_fields() -> None:
    request = valid_request()
    request["api_key"] = "must-not-be-accepted"

    response = client.post("/generate", json=request)

    assert response.status_code == 422
