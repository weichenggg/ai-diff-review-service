from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration supplied by environment variables."""

    version: str = "0.1.0"
    max_payload_bytes: int = 1_048_576
    chunk_bytes: int = 65_536
    max_concurrent_jobs: int = 4
    rate_limit_per_minute: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
