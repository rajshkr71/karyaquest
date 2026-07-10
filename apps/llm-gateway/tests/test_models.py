from uuid import uuid4

import pytest
from pydantic import ValidationError

from llm_gateway.models import LLMError, LLMRequest, LLMResponse


def test_valid_llm_request() -> None:
    request_id = uuid4()

    request = LLMRequest(
        request_id=request_id,
        task_type="resume_generation",
        prompt_template="Tailor the resume for {job_title}",
        variables={"job_title": "Platform Engineer"},
        provider="fake",
        model="fake-model",
        temperature=0.2,
        max_output_tokens=1024,
        metadata={"job_id": "job-123"},
    )

    assert request.request_id == request_id
    assert request.task_type == "resume_generation"
    assert request.temperature == 0.2


@pytest.mark.parametrize(
    "field",
    ["task_type", "prompt_template", "provider", "model"],
)
def test_request_rejects_blank_required_strings(field: str) -> None:
    payload = {
        "request_id": uuid4(),
        "task_type": "resume_generation",
        "prompt_template": "Generate content",
        "provider": "fake",
        "model": "fake-model",
    }
    payload[field] = "   "

    with pytest.raises(ValidationError):
        LLMRequest(**payload)


@pytest.mark.parametrize("temperature", [-0.1, 2.1])
def test_request_rejects_invalid_temperature(temperature: float) -> None:
    with pytest.raises(ValidationError):
        LLMRequest(
            request_id=uuid4(),
            task_type="resume_generation",
            prompt_template="Generate content",
            provider="fake",
            model="fake-model",
            temperature=temperature,
        )


@pytest.mark.parametrize("max_output_tokens", [0, 32769])
def test_request_rejects_invalid_token_limits(max_output_tokens: int) -> None:
    with pytest.raises(ValidationError):
        LLMRequest(
            request_id=uuid4(),
            task_type="resume_generation",
            prompt_template="Generate content",
            provider="fake",
            model="fake-model",
            max_output_tokens=max_output_tokens,
        )


def test_valid_llm_response() -> None:
    response = LLMResponse(
        request_id=uuid4(),
        provider="fake",
        model="fake-model",
        model_version="fake-model-2026-07-10",
        output_text="Generated output",
        input_tokens=100,
        output_tokens=50,
        latency_ms=25,
        finish_reason="stop",
    )

    assert response.model_version == "fake-model-2026-07-10"
    assert response.redactions_applied == []


def test_response_requires_model_version() -> None:
    with pytest.raises(ValidationError):
        LLMResponse(
            request_id=uuid4(),
            provider="fake",
            model="fake-model",
            output_text="Generated output",
            input_tokens=100,
            output_tokens=50,
            latency_ms=25,
            finish_reason="stop",
        )


def test_valid_llm_error() -> None:
    error = LLMError(
        request_id=uuid4(),
        error_type="provider_timeout",
        safe_message="The provider timed out",
        retryable=True,
    )

    assert error.retryable is True


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        LLMRequest(
            request_id=uuid4(),
            task_type="resume_generation",
            prompt_template="Generate content",
            provider="fake",
            model="fake-model",
            unexpected_field="not allowed",
        )
