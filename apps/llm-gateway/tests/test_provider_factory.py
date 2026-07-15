import pytest

from llm_gateway.fake_provider import FakeLLMProvider
from llm_gateway.openai_provider import OpenAIProvider
from llm_gateway import provider_factory
from llm_gateway.provider_factory import (
    UnsupportedProviderError,
    create_provider,
)
from llm_gateway.settings import Settings


def test_factory_creates_fake_provider() -> None:
    settings = Settings(
        provider="fake",
        model_version="configured-fake-v2",
    )

    provider = create_provider(settings)

    assert isinstance(provider, FakeLLMProvider)
    assert provider.name == "fake"


def test_factory_provider_name_is_case_insensitive() -> None:
    settings = Settings(provider="FAKE")

    provider = create_provider(settings)

    assert isinstance(provider, FakeLLMProvider)


def test_factory_creates_openai_provider_case_insensitively(
    monkeypatch,
) -> None:
    created_clients: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            created_clients.append(kwargs)
            self.responses = object()

    monkeypatch.setattr(provider_factory, "OpenAI", FakeOpenAI)
    settings = Settings(provider="OpEnAi", openai_api_key="secret-key")

    provider = create_provider(settings)

    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"


def test_factory_passes_timeout_retries_and_api_key_to_sdk_client(
    monkeypatch,
) -> None:
    created_clients: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            created_clients.append(kwargs)
            self.responses = object()

    monkeypatch.setattr(provider_factory, "OpenAI", FakeOpenAI)
    settings = Settings(
        provider="openai",
        openai_api_key="secret-key",
        request_timeout_seconds=45,
        max_retries=3,
    )

    create_provider(settings)

    assert created_clients == [
        {
            "api_key": "secret-key",
            "timeout": 45.0,
            "max_retries": 3,
        }
    ]


def test_factory_rejects_openai_without_api_key_safely() -> None:
    settings = Settings(provider="openai")

    with pytest.raises(
        UnsupportedProviderError,
        match="openai provider is not configured",
    ) as exc_info:
        create_provider(settings)

    assert "secret" not in str(exc_info.value).lower()


def test_factory_rejects_unsupported_provider() -> None:
    settings = Settings(provider="unsupported")

    with pytest.raises(
        UnsupportedProviderError,
        match="unsupported provider",
    ):
        create_provider(settings)
