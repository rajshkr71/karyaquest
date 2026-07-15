from __future__ import annotations

from llm_gateway.fake_provider import FakeLLMProvider
from llm_gateway.openai_provider import OpenAIProvider
from llm_gateway.provider import LLMProvider
from llm_gateway.settings import Settings

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised when dependency is absent
    OpenAI = None  # type: ignore[assignment]


class UnsupportedProviderError(ValueError):
    pass


def create_provider(settings: Settings) -> LLMProvider:
    provider_name = settings.provider.lower()

    if provider_name == "fake":
        return FakeLLMProvider(
            model_version=settings.model_version,
        )

    if provider_name == "openai":
        if settings.openai_api_key is None:
            raise UnsupportedProviderError("openai provider is not configured")
        if OpenAI is None:
            raise UnsupportedProviderError("openai provider dependency is missing")

        client = OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=float(settings.request_timeout_seconds),
            max_retries=settings.max_retries,
        )
        return OpenAIProvider(client=client)

    raise UnsupportedProviderError(
        f"unsupported provider: {settings.provider}"
    )
