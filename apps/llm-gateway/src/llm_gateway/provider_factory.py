from __future__ import annotations

from llm_gateway.fake_provider import FakeLLMProvider
from llm_gateway.provider import LLMProvider
from llm_gateway.settings import Settings


class UnsupportedProviderError(ValueError):
    pass


def create_provider(settings: Settings) -> LLMProvider:
    provider_name = settings.provider.lower()

    if provider_name == "fake":
        return FakeLLMProvider(
            model_version=settings.model_version,
        )

    raise UnsupportedProviderError(
        f"unsupported provider: {settings.provider}"
    )
