from __future__ import annotations

import json
import time
from typing import Protocol

from llm_gateway.models import LLMRequest, LLMResponse
from llm_gateway.provider import LLMProvider

MIN_OPENAI_OUTPUT_TOKENS = 16


class OpenAIProviderError(RuntimeError):
    pass


class OpenAIResponseUsage(Protocol):
    input_tokens: int | None
    output_tokens: int | None


class OpenAIIncompleteDetails(Protocol):
    reason: str | None


class OpenAIResponse(Protocol):
    output_text: str | None
    model: str | None
    status: str | None
    usage: OpenAIResponseUsage | None
    incomplete_details: OpenAIIncompleteDetails | None


class OpenAIResponsesAPI(Protocol):
    def create(
        self,
        *,
        model: str,
        input: str,
        temperature: float,
        max_output_tokens: int,
    ) -> OpenAIResponse: ...


class OpenAIClient(Protocol):
    responses: OpenAIResponsesAPI


def build_openai_prompt(request: LLMRequest) -> str:
    variables_json = json.dumps(
        request.variables,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"{request.prompt_template}\n{variables_json}"


def _token_count(value: int | None) -> int:
    if value is None:
        return 0
    return max(value, 0)


def _finish_reason(response: OpenAIResponse) -> str:
    status = (response.status or "").strip()
    reason = ""
    incomplete_details = response.incomplete_details
    if incomplete_details is not None:
        reason = (incomplete_details.reason or "").strip()

    if status == "completed":
        return "stop"
    if status == "incomplete" and reason == "max_output_tokens":
        return "length"
    return reason or status or "unknown"


class OpenAIProvider(LLMProvider):
    def __init__(self, client: OpenAIClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "openai"

    def generate(self, request: LLMRequest) -> LLMResponse:
        if request.max_output_tokens < MIN_OPENAI_OUTPUT_TOKENS:
            raise OpenAIProviderError(
                "openai max_output_tokens must be at least 16"
            )

        prompt = build_openai_prompt(request)
        started_at = time.perf_counter()
        response = self._client.responses.create(
            model=request.model,
            input=prompt,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
        )
        latency_ms = int((time.perf_counter() - started_at) * 1000)

        output_text = response.output_text
        if output_text is None or not output_text.strip():
            raise OpenAIProviderError("openai response did not include output text")

        usage = response.usage
        return LLMResponse(
            request_id=request.request_id,
            provider=self.name,
            model=request.model,
            model_version=response.model or request.model,
            output_text=output_text,
            input_tokens=_token_count(
                usage.input_tokens if usage is not None else None
            ),
            output_tokens=_token_count(
                usage.output_tokens if usage is not None else None
            ),
            latency_ms=latency_ms,
            finish_reason=_finish_reason(response),
            redactions_applied=[],
        )
