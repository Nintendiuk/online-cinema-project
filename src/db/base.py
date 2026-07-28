"""Declarative base and reusable model mixins.

The naming convention is mandatory: without it Alembic autogenerate produces
noise for unnamed constraints and indexes.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in the project."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IntPKMixin:
    """Adds a surrogate integer primary key named ``id``."""

    id: Mapped[int] = mapped_column(primary_key=True)


class TimestampMixin:
    """Adds server-side timezone-aware creation and update timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TokenMixin:
    """Adds a unique token string with an expiry moment.

    Shared by activation, password-reset and refresh token models.
    """

    token: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    def is_expired(self, now: datetime | None = None) -> bool:
        """Whether the token's expiry moment lies in the past."""
        moment = now if now is not None else datetime.now(UTC)
        return self.expires_at <= moment
