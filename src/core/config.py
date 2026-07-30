"""Application configuration.

The only place in the project that reads the environment. Every other module
receives configuration through :func:`get_settings` or dependency injection.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from the environment and ``.env``.

    Field names map one-to-one onto the keys documented in ``.env.sample``;
    ``tests/unit/test_config.py`` enforces that correspondence.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )

    # Database
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str
    postgres_port: int

    # JWT and token lifetimes
    secret_key_access: str
    secret_key_refresh: str
    jwt_algorithm: str
    access_token_ttl_minutes: int
    refresh_token_ttl_days: int
    activation_token_ttl_hours: int
    password_reset_ttl_minutes: int

    # Email
    email_host: str
    email_port: int
    email_user: str
    email_password: str
    email_from: str
    email_use_tls: bool

    # Redis and Celery
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str

    # S3 / MinIO
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket_name: str

    # Stripe
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_success_url: str
    stripe_cancel_url: str

    # Application
    frontend_base_url: str
    environment: Literal["development", "test", "production"]
    docs_enabled: bool

    @property
    def activation_url(self) -> str:
        """Page the activation e-mail links to; the token is appended as a query."""
        return f"{self.frontend_base_url.rstrip('/')}/activate"

    @property
    def login_url(self) -> str:
        """Page the activation-complete e-mail links to."""
        return f"{self.frontend_base_url.rstrip('/')}/login"

    @property
    def password_reset_url(self) -> str:
        """Page the reset e-mail links to; address and token arrive as a query."""
        return f"{self.frontend_base_url.rstrip('/')}/password-reset"

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN used by the application engine."""
        return self._dsn(driver="postgresql+asyncpg")

    @property
    def sync_database_url(self) -> str:
        """Synchronous DSN, used only by Alembic in offline mode."""
        return self._dsn(driver="postgresql")

    def _dsn(self, driver: str) -> str:
        """Assemble a DSN for the given driver from the Postgres components."""
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"{driver}://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_production(self) -> bool:
        """Whether the application runs with production settings."""
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance, building it on first call."""
    return Settings()
