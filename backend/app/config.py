"""Environment configuration."""
from __future__ import annotations
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://lm:lm@localhost:5433/livingmemory"
    secret_key: str = "living-memory-demo-key"
    demo_mode: bool = True

    # "rules" = deterministic analyzer, needs no API key (DEFAULT)
    # "llm"   = LLM-backed analyzer, needs a key
    analyzer: str = "rules"
    answerer: str = "rules"
    llm_enabled: bool = False

    anthropic_api_key: str = ""
    groq_api_key: str = ""
    google_api_key: str = ""

    # Embeddings: "fastembed" (downloads ~90MB once) or "hash" (offline, instant)
    embedding_backend: str = "hash"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
