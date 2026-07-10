from uuid import uuid4

import pytest

from llm_gateway.models import LLMRequest, LLMResponse
from llm_gateway.provider import LLMProvider


class FakeProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            request_id=request.request_id,
            provider=self.name,
            model=request.model,
            model_version="fake-model-v1",
            output_text="Safe deterministic output",
            input_tokens=10,
            output_tokens=5,
            latency_ms=1,
            finish_reason="stop",
        )


def test_provider_interface_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        LLMProvider()


def test_fake_provider_satisfies_contract() -> None:
    provider = FakeProvider()

    request = LLMRequest(
        request_id=uuid4(),
        task_type="resume_generation",
        prompt_template="Generate content",
        provider="fake",
        model="fake-model",
    )

    response = provider.generate(request)

    assert provider.name == "fake"
    assert response.request_id == request.request_id
    assert response.provider == "fake"
    assert response.model == "fake-model"
    assert response.model_version == "fake-model-v1"
