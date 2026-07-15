from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from llm_gateway.models import LLMRequest
from llm_gateway.openai_provider import (
    OpenAIProvider,
    OpenAIProviderError,
    build_openai_prompt,
)


@dataclass
class FakeUsage:
    input_tokens: int | None = 11
    output_tokens: int | None = 7


@dataclass
class FakeIncompleteDetails:
    reason: str | None = None


@dataclass
class FakeResponse:
    output_text: str | None = "Generated output"
    model: str | None = "gpt-test-2026-07-15"
    status: str | None = "completed"
    usage: FakeUsage | None = field(default_factory=FakeUsage)
    incomplete_details: FakeIncompleteDetails | None = None


class FakeResponsesAPI:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create(
        self,
        *,
        model: str,
        input: str,
        temperature: float,
        max_output_tokens: int,
    ) -> FakeResponse:
        self.calls.append(
            {
                "model": model,
                "input": input,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            }
        )
        return self.response


class FakeClient:
    def __init__(self, response: FakeResponse | None = None) -> None:
        self.responses = FakeResponsesAPI(response or FakeResponse())


def valid_request() -> LLMRequest:
    return LLMRequest(
        request_id=uuid4(),
        task_type="resume_generation",
        prompt_template="Generate resume content for the variables below.",
        variables={
            "job_title": "Platform Engineer",
            "count": 2,
        },
        provider="openai",
        model="gpt-5-mini",
        temperature=0.4,
        max_output_tokens=128,
        metadata={"api_key": "must-not-be-sent"},
    )


def test_openai_provider_name_is_openai() -> None:
    provider = OpenAIProvider(client=FakeClient())

    assert provider.name == "openai"


def test_responses_api_receives_expected_generation_request() -> None:
    request = valid_request()
    client = FakeClient()
    provider = OpenAIProvider(client=client)

    provider.generate(request)

    assert client.responses.calls == [
        {
            "model": "gpt-5-mini",
            "input": (
                "Generate resume content for the variables below.\n"
                '{"count":2,"job_title":"Platform Engineer"}'
            ),
            "temperature": 0.4,
            "max_output_tokens": 128,
        }
    ]
    assert "metadata" not in client.responses.calls[0]
    assert "must-not-be-sent" not in client.responses.calls[0]["input"]


def test_build_openai_prompt_serializes_variables_compactly_and_sorted() -> None:
    request = valid_request()

    assert build_openai_prompt(request) == (
        "Generate resume content for the variables below.\n"
        '{"count":2,"job_title":"Platform Engineer"}'
    )


def test_successful_response_maps_output_usage_latency_and_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = valid_request()
    client = FakeClient(
        FakeResponse(
            output_text="Tailored resume content",
            model="gpt-5-mini-2026-07-15",
            status="completed",
            usage=FakeUsage(input_tokens=31, output_tokens=17),
        )
    )
    timings = iter([10.0, 10.123])
    monkeypatch.setattr(
        "llm_gateway.openai_provider.time.perf_counter",
        lambda: next(timings),
    )

    response = OpenAIProvider(client=client).generate(request)

    assert response.request_id == request.request_id
    assert response.provider == "openai"
    assert response.model == "gpt-5-mini"
    assert response.model_version == "gpt-5-mini-2026-07-15"
    assert response.output_text == "Tailored resume content"
    assert response.input_tokens == 31
    assert response.output_tokens == 17
    assert response.latency_ms == 122
    assert response.finish_reason == "stop"
    assert response.redactions_applied == []


def test_completed_status_maps_to_stop() -> None:
    request = valid_request()
    client = FakeClient(FakeResponse(status="completed"))

    response = OpenAIProvider(client=client).generate(request)

    assert response.finish_reason == "stop"


def test_incomplete_max_output_tokens_maps_to_length() -> None:
    request = valid_request()
    client = FakeClient(
        FakeResponse(
            status="incomplete",
            incomplete_details=FakeIncompleteDetails(reason="max_output_tokens"),
        )
    )

    response = OpenAIProvider(client=client).generate(request)

    assert response.finish_reason == "length"


def test_missing_usage_maps_token_counts_to_zero() -> None:
    request = valid_request()
    client = FakeClient(FakeResponse(usage=None))

    response = OpenAIProvider(client=client).generate(request)

    assert response.input_tokens == 0
    assert response.output_tokens == 0


def test_missing_model_version_defaults_to_requested_model() -> None:
    request = valid_request()
    client = FakeClient(FakeResponse(model=None))

    response = OpenAIProvider(client=client).generate(request)

    assert response.model_version == request.model


@pytest.mark.parametrize("output_text", [None, "", "   "])
def test_blank_output_raises_safe_provider_exception(
    output_text: str | None,
) -> None:
    request = valid_request()
    client = FakeClient(FakeResponse(output_text=output_text))

    with pytest.raises(
        OpenAIProviderError,
        match="openai response did not include output text",
    ) as exc_info:
        OpenAIProvider(client=client).generate(request)

    assert "Generate resume content" not in str(exc_info.value)
    assert "must-not-be-sent" not in str(exc_info.value)


def test_token_limit_below_openai_minimum_fails_before_client_call() -> None:
    request = valid_request()
    request.max_output_tokens = 15
    client = FakeClient()

    with pytest.raises(
        OpenAIProviderError,
        match="openai max_output_tokens must be at least 16",
    ):
        OpenAIProvider(client=client).generate(request)

    assert client.responses.calls == []
