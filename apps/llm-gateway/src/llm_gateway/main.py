from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status

try:
    from openai import RateLimitError
except ImportError:
    RateLimitError = None  # type: ignore[assignment]

from llm_gateway.audit_logging import log_audit_event
from llm_gateway.models import LLMRequest, LLMResponse
from llm_gateway.provider import LLMProvider
from llm_gateway.provider_factory import (
    UnsupportedProviderError,
    create_provider,
)
from llm_gateway.settings import Settings, get_settings

app = FastAPI(title="KaryaQuest LLM Gateway")


def get_provider(
    settings: Settings = Depends(get_settings),
) -> LLMProvider:
    try:
        return create_provider(settings)
    except UnsupportedProviderError as exc:
        log_audit_event(
            "llm.provider.unavailable",
            configured_provider=settings.provider,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_type=type(exc).__name__,
            outcome="unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="configured provider is unavailable",
        ) from exc


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "llm-gateway"}


@app.post(
    "/generate",
    response_model=LLMResponse,
    status_code=status.HTTP_200_OK,
)
def generate(
    request: LLMRequest,
    provider: LLMProvider = Depends(get_provider),
) -> LLMResponse:
    if request.provider.lower() != provider.name.lower():
        log_audit_event(
            "llm.generate.rejected",
            request_id=request.request_id,
            task_type=request.task_type,
            requested_provider=request.provider,
            configured_provider=provider.name,
            model=request.model,
            status_code=status.HTTP_400_BAD_REQUEST,
            reason="provider_mismatch",
            outcome="rejected",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="requested provider does not match configured provider",
        )

    log_audit_event(
        "llm.generate.started",
        request_id=request.request_id,
        task_type=request.task_type,
        provider=provider.name,
        model=request.model,
        max_output_tokens=request.max_output_tokens,
        outcome="started",
    )

    try:
        response = provider.generate(request)
    except Exception as exc:
        log_audit_event(
            "llm.generate.failed",
            request_id=request.request_id,
            task_type=request.task_type,
            provider=provider.name,
            model=request.model,
            error_type=type(exc).__name__,
            outcome="failed",
        )
        if RateLimitError is not None and isinstance(exc, RateLimitError):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="upstream provider rate limit exceeded",
            ) from None
        raise

    log_audit_event(
        "llm.generate.succeeded",
        request_id=request.request_id,
        task_type=request.task_type,
        provider=provider.name,
        model=request.model,
        model_version=response.model_version,
        latency_ms=response.latency_ms,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        finish_reason=response.finish_reason,
        redaction_count=len(response.redactions_applied),
        outcome="succeeded",
    )
    return response
