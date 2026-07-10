from uuid import uuid4

from fastapi.testclient import TestClient

from llm_gateway.main import app
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
