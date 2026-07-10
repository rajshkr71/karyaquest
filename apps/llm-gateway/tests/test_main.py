from uuid import uuid4

from fastapi.testclient import TestClient

from llm_gateway.main import app

client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "llm-gateway",
    }


def test_generate_returns_fake_response() -> None:
    request_id = str(uuid4())

    response = client.post(
        "/generate",
        json={
            "request_id": request_id,
            "task_type": "resume_generation",
            "prompt_template": "Generate content",
            "variables": {"job_title": "Platform Engineer"},
            "provider": "fake",
            "model": "fake-model",
            "temperature": 0.2,
            "max_output_tokens": 1024,
            "metadata": {"job_id": "job-123"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": request_id,
        "provider": "fake",
        "model": "fake-model",
        "model_version": "fake-v1",
        "output_text": "Deterministic fake response",
        "input_tokens": 0,
        "output_tokens": 3,
        "latency_ms": 0,
        "finish_reason": "stop",
        "redactions_applied": [],
    }


def test_generate_rejects_unsupported_provider() -> None:
    response = client.post(
        "/generate",
        json={
            "request_id": str(uuid4()),
            "task_type": "resume_generation",
            "prompt_template": "Generate content",
            "provider": "openai",
            "model": "some-model",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unsupported provider"}


def test_generate_rejects_blank_model() -> None:
    response = client.post(
        "/generate",
        json={
            "request_id": str(uuid4()),
            "task_type": "resume_generation",
            "prompt_template": "Generate content",
            "provider": "fake",
            "model": "   ",
        },
    )

    assert response.status_code == 422


def test_generate_rejects_invalid_temperature() -> None:
    response = client.post(
        "/generate",
        json={
            "request_id": str(uuid4()),
            "task_type": "resume_generation",
            "prompt_template": "Generate content",
            "provider": "fake",
            "model": "fake-model",
            "temperature": 2.1,
        },
    )

    assert response.status_code == 422


def test_generate_rejects_unknown_fields() -> None:
    response = client.post(
        "/generate",
        json={
            "request_id": str(uuid4()),
            "task_type": "resume_generation",
            "prompt_template": "Generate content",
            "provider": "fake",
            "model": "fake-model",
            "api_key": "must-not-be-accepted",
        },
    )

    assert response.status_code == 422
