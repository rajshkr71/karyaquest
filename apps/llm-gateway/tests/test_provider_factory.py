import pytest

from llm_gateway.fake_provider import FakeLLMProvider
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


def test_factory_rejects_unsupported_provider() -> None:
    settings = Settings(provider="unsupported")

    with pytest.raises(
        UnsupportedProviderError,
        match="unsupported provider",
    ):
        create_provider(settings)
