from __future__ import annotations

from llm_gateway.models import LLMRequest, LLMResponse
from llm_gateway.provider import LLMProvider


class FakeLLMProvider(LLMProvider):
    """
    Deterministic provider used only for local development and contract tests.

    It performs no network calls and does not invoke an actual language model.
    """

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            request_id=request.request_id,
            provider=self.name,
            model=request.model,
            model_version="fake-v1",
            output_text="Deterministic fake response",
            input_tokens=0,
            output_tokens=3,
            latency_ms=0,
            finish_reason="stop",
            redactions_applied=[],
        )
