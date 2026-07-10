from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="requested provider does not match configured provider",
        )

    return provider.generate(request)
