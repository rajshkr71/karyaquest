from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMRequest(StrictModel):
    request_id: UUID
    task_type: str
    prompt_template: str
    variables: dict[str, Any] = Field(default_factory=dict)
    provider: str
    model: str
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=1024, ge=1, le=32768)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "task_type",
        "prompt_template",
        "provider",
        "model",
    )
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class LLMResponse(StrictModel):
    request_id: UUID
    provider: str
    model: str
    model_version: str
    output_text: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    finish_reason: str
    redactions_applied: list[str] = Field(default_factory=list)

    @field_validator(
        "provider",
        "model",
        "model_version",
        "finish_reason",
    )
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class LLMError(StrictModel):
    request_id: UUID
    error_type: str
    safe_message: str
    retryable: bool

    @field_validator("error_type", "safe_message")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned
