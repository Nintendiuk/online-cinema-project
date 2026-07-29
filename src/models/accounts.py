"""ORM models for accounts: groups, users, profiles and lifecycle tokens.

The module holds columns, relationships and database constraints only. Hashing
and validation live in ``src/security/``; nothing here may import them.
"""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text, false
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, IntPKMixin, TimestampMixin, TokenMixin
from src.db.enums import GenderEnum, UserGroupEnum


def _enum_values(enum_class: type[UserGroupEnum | GenderEnum]) -> Sequence[str]:
    """Persist enum *values* (``"user"``) rather than member names (``"USER"``).

    Without this callable SQLAlchemy stores ``.name``, which would put uppercase
    literals in the database and break round-tripping through the JSON layer.
    """
    return [member.value for member in enum_class]


class UserGroup(IntPKMixin, Base):
    """An access group a user belongs to; the group outlives its members."""

    __tablename__ = "user_groups"

    name: Mapped[UserGroupEnum] = mapped_column(
        SQLEnum(UserGroupEnum, name="user_group_enum", values_callable=_enum_values),
        unique=True,
        nullable=False,
    )

    users: Mapped[list["User"]] = relationship("User", back_populates="group")

    def __repr__(self) -> str:
        """Short identifying representation for logs and test output."""
        return f"<UserGroup id={self.id} name={self.name.value!r}>"


class User(IntPKMixin, TimestampMixin, Base):
    """Application user account with credentials and group membership."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=false()
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("user_groups.id", ondelete="RESTRICT"), nullable=False
    )

    group: Mapped["UserGroup"] = relationship("UserGroup", back_populates="users")
    profile: Mapped["UserProfile | None"] = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    activation_token: Mapped["ActivationToken | None"] = relationship(
        "ActivationToken",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    password_reset_token: Mapped["PasswordResetToken | None"] = relationship(
        "PasswordResetToken",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """Short identifying representation for logs and test output."""
        return f"<User id={self.id} email={self.email!r}>"


class UserProfile(IntPKMixin, Base):
    """Optional descriptive data attached to exactly one user."""

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gender: Mapped[GenderEnum | None] = mapped_column(
        SQLEnum(GenderEnum, name="gender_enum", values_callable=_enum_values),
        nullable=True,
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    info: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="profile")

    def __repr__(self) -> str:
        """Short identifying representation for logs and test output."""
        return f"<UserProfile id={self.id} user_id={self.user_id}>"


class ActivationToken(IntPKMixin, TokenMixin, Base):
    """Single-use token that activates a freshly registered account."""

    __tablename__ = "activation_tokens"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="activation_token")

    def __repr__(self) -> str:
        """Short identifying representation for logs and test output."""
        return f"<ActivationToken id={self.id} user_id={self.user_id}>"


class PasswordResetToken(IntPKMixin, TokenMixin, Base):
    """Single-use token authorising one password reset."""

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="password_reset_token")

    def __repr__(self) -> str:
        """Short identifying representation for logs and test output."""
        return f"<PasswordResetToken id={self.id} user_id={self.user_id}>"


class RefreshToken(IntPKMixin, TokenMixin, Base):
    """Long-lived session token; a user may hold several at once."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")

    def __repr__(self) -> str:
        """Short identifying representation for logs and test output."""
        return f"<RefreshToken id={self.id} user_id={self.user_id}>"
