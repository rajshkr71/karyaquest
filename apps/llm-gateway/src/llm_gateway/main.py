from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status

from llm_gateway.fake_provider import FakeLLMProvider
from llm_gateway.models import LLMRequest, LLMResponse
from llm_gateway.provider import LLMProvider

app = FastAPI(title="KaryaQuest LLM Gateway")


def get_provider() -> LLMProvider:
    return FakeLLMProvider()


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
    if request.provider != provider.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported provider",
        )

    return provider.generate(request)
