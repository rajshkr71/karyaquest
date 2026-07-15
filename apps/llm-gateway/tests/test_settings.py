import pytest
from pydantic import ValidationError

from llm_gateway.settings import Settings


def test_settings_use_safe_defaults() -> None:
    settings = Settings()

    assert settings.provider == "fake"
    assert settings.model == "fake-model"
    assert settings.model_version == "fake-v1"
    assert settings.temperature == 0.2
    assert settings.max_output_tokens == 1024
    assert settings.request_timeout_seconds == 30
    assert settings.max_retries == 2
    assert settings.openai_api_key is None
    assert settings.log_level == "INFO"


def test_settings_read_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "configured-model")
    monkeypatch.setenv("LLM_MODEL_VERSION", "configured-v2")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.4")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("LLM_MAX_RETRIES", "3")
    monkeypatch.setenv("LLM_OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("LLM_LOG_LEVEL", "debug")

    settings = Settings()

    assert settings.provider == "fake"
    assert settings.model == "configured-model"
    assert settings.model_version == "configured-v2"
    assert settings.temperature == 0.4
    assert settings.max_output_tokens == 2048
    assert settings.request_timeout_seconds == 45
    assert settings.max_retries == 3
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-openai-key"
    assert settings.log_level == "DEBUG"


def test_settings_repr_does_not_expose_openai_api_key() -> None:
    settings = Settings(openai_api_key="test-openai-key")

    assert "test-openai-key" not in repr(settings)
    assert "**********" in repr(settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "   "),
        ("model", ""),
        ("model_version", "   "),
        ("log_level", ""),
    ],
)
def test_settings_reject_blank_strings(field: str, value: str) -> None:
    payload = {field: value}

    with pytest.raises(ValidationError):
        Settings(**payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", -0.1),
        ("temperature", 2.1),
        ("max_output_tokens", 0),
        ("max_output_tokens", 32769),
        ("request_timeout_seconds", 0),
        ("request_timeout_seconds", 301),
        ("max_retries", -1),
        ("max_retries", 11),
    ],
)
def test_settings_reject_invalid_numeric_values(
    field: str,
    value: int | float,
) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_settings_reject_unsupported_log_level() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="verbose")
