"""Centralized application configuration loaded via pydantic-settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LLAMA_SERVER_URL = 'http://localhost:8080'
DEFAULT_ALLOWED_ORIGINS = (
    'http://127.0.0.1:8001',
    'http://localhost:8001',
    'http://127.0.0.1',
    'http://localhost',
)
ENV_FILE_PATHS = (
    ROOT_DIR / 'service' / '.env',
    ROOT_DIR / '.env',
    ROOT_DIR / 'api' / '.env',
)


class Settings(BaseSettings):
    """Application settings validated at startup and environment-aware."""

    model_config = SettingsConfigDict(
        env_file=tuple(str(path) for path in ENV_FILE_PATHS),
        env_file_encoding='utf-8',
        extra='ignore',
    )

    RIOT_API_KEY: str = Field(default='')
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_ORIGINS))
    ALLOW_REMOTE_ACCESS: bool = Field(default=False)
    REDIS_URL: str | None = Field(default=None)
    LLAMA_SERVER_URL: str = Field(default=DEFAULT_LLAMA_SERVER_URL)

    @field_validator('RIOT_API_KEY', mode='before')
    @classmethod
    def strip_api_key(cls, value: Any) -> str:
        if value is None:
            return ''
        return str(value).strip()

    @field_validator('ALLOWED_ORIGINS', mode='before')
    @classmethod
    def parse_allowed_origins(cls, value: Any) -> list[str]:
        if value is None or value == '':
            return list(DEFAULT_ALLOWED_ORIGINS)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith('['):
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(origin).strip().rstrip('/') for origin in parsed if str(origin).strip()]
            return [origin.strip().rstrip('/') for origin in stripped.split(',') if origin.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(origin).strip().rstrip('/') for origin in value if str(origin).strip()]
        raise ValueError('Invalid ALLOWED_ORIGINS format')

    @field_validator('REDIS_URL', mode='before')
    @classmethod
    def normalize_redis_url(cls, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator('LLAMA_SERVER_URL', mode='before')
    @classmethod
    def normalize_llama_server_url(cls, value: Any) -> str:
        if value is None or not str(value).strip():
            return DEFAULT_LLAMA_SERVER_URL
        return str(value).strip().rstrip('/')


def get_settings() -> Settings:
    """Return a validated Settings instance reflecting current environment variables."""
    return Settings()


settings = get_settings()
