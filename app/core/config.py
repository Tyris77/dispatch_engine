import os
from typing import List, Optional, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "Multi-Tenant Operations & Dispatch Engine"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database URLs
    # Async URL for FastAPI runtime (PostgreSQL asyncpg or SQLite aiosqlite)
    # Default to /tmp/dispatch.db on Linux/container environments to prevent permission errors
    DATABASE_URL: str = (
        "sqlite+aiosqlite:///./dispatch.db"
        if os.name == "nt"
        else "sqlite+aiosqlite:////tmp/dispatch.db"
    )
    # Synchronous URL for Alembic CLI migrations
    SYNC_DATABASE_URL: str = (
        "sqlite:///./dispatch.db"
        if os.name == "nt"
        else "sqlite:////tmp/dispatch.db"
    )

    # Security
    SECRET_KEY: str = "default-insecure-secret-key-change-me"
    MASTER_ADMIN_API_KEY: str = "master_admin_dev_key"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day

    # External Integrations
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    HUBSPOT_API_KEY: str = ""
    SALESFORCE_CLIENT_ID: str = ""
    SALESFORCE_CLIENT_SECRET: str = ""

    # Twilio Configuration
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""

    # Stripe Configuration
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None

    # Search Engine Indexing & Verification (IndexNow & Google Search Console)
    INDEXNOW_KEY: str = "8f7b2a4c1e9d3b5a7c2e4f6a8b0d2e4f"
    GOOGLE_SITE_VERIFICATION: Optional[str] = None

    # CORS
    BACKEND_CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)


settings = Settings()
