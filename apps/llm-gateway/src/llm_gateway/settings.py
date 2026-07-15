from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        extra="ignore",
        case_sensitive=False,
    )

    provider: str = "fake"
    model: str = "fake-model"
    model_version: str = "fake-v1"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=1024, ge=1, le=32768)
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=2, ge=0, le=10)
    openai_api_key: SecretStr | None = None
    log_level: str = "INFO"

    @field_validator(
        "provider",
        "model",
        "model_version",
        "log_level",
    )
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }
        if normalized not in allowed:
            raise ValueError("unsupported log level")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
