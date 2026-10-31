from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: SecretStr = Field(min_length=1)
    vision_model: str = Field(min_length=1)

    min_classification_confidence: float = Field(
        default=0.70,
        ge=0,
        le=1,
    )

    vision_daily_call_limit: int = Field(
        default=20,
        ge=0,
    )

    embedding_model: str = Field(
        default="gemini-embedding-001",
        min_length=1,
    )

    embedding_dimensions: int = Field(
        default=768,
        ge=1,
        le=3072,
    )

    embedding_daily_call_limit: int = Field(
        default=100,
        ge=0,
    )

    min_match_similarity: float = Field(
        default=0.85,
        ge=-1,
        le=1,
    )

    max_images_per_workspace: int = Field(
        default=100,
        ge=1,
    )
    clerk_issuer: str | None = Field(
        default=None,
        min_length=1,
    )

    clerk_authorized_parties: list[str] = Field(
        default_factory=list,
    )
    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr = Field(min_length=1)
    postgres_db: str = Field(min_length=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()