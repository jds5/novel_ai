from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from NOVEL_AI_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="NOVEL_AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "local"
    log_level: str = "INFO"
    database_url: str = Field(
        default="postgresql+asyncpg://novel_ai:novel_ai@127.0.0.1:5432/novel_ai"
    )
    database_echo: bool = False
    prompt_catalog_package: str = "novel_ai.prompts.catalog"
    model_request_timeout_seconds: float = Field(default=180.0, gt=0)
    default_model_provider: str = "openai"
    object_store_path: Path = Path(".novel_ai_objects")
    generation_max_output_tokens: int = Field(default=6000, ge=256)
    recent_chapter_context_chars: int = Field(default=6000, ge=0)
    max_chapter_chars: int = Field(default=200_000, ge=1000)
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com"
    openai_default_model: str = "gpt-5.6-terra"
    codex_session_enabled: bool = False
    codex_session_executable: str = "codex"
    codex_session_default_model: str = "gpt-5.6-terra"
    codex_session_timeout_seconds: float = Field(default=600.0, gt=0)
    codex_session_auth_timeout_seconds: float = Field(default=10.0, gt=0)
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_default_model: str = "deepseek-v4-pro"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
