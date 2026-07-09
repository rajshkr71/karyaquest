"""Application settings.

Codex should complete this using pydantic-settings.
Do not hardcode secrets here.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_host: str = "postgres.karyaquest-data.svc.cluster.local"
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str

    class Config:
        env_prefix = "POSTGRES_"


def get_settings() -> Settings:
    return Settings()
