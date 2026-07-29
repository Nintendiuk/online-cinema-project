"""Async builder helpers for account objects used across the test suite.

Every helper flushes and never commits: the suite runs each test inside a
transaction that is rolled back, and a commit here would break that isolation.
"""

import secrets
from datetime import UTC, date, datetime, timedelta
from itertools import count

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import GenderEnum, UserGroupEnum
from src.models.accounts import (
    ActivationToken,
    PasswordResetToken,
    RefreshToken,
    User,
    UserGroup,
    UserProfile,
)

_email_counter = count(1)


async def create_group(
    session: AsyncSession, name: UserGroupEnum = UserGroupEnum.USER
) -> UserGroup:
    """Return the group with this name, inserting it when it does not exist."""
    result = await session.execute(select(UserGroup).where(UserGroup.name == name))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    group = UserGroup(name=name)
    session.add(group)
    await session.flush()
    return group


async def create_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    password_hash: str = "hashed",
    is_active: bool = True,
    group: UserGroup | None = None,
) -> User:
    """Create a user, generating a unique e-mail and a USER group when omitted."""
    if email is None:
        email = f"user{next(_email_counter)}_{secrets.token_hex(4)}@example.com"
    if group is None:
        group = await create_group(session, UserGroupEnum.USER)
    user = User(
        email=email,
        hashed_password=password_hash,
        is_active=is_active,
        group_id=group.id,
    )
    session.add(user)
    await session.flush()
    return user


async def create_profile(
    session: AsyncSession, user: User, **overrides: object
) -> UserProfile:
    """Create the profile of a user; any field may be overridden by keyword."""
    values: dict[str, object] = {
        "first_name": "John",
        "last_name": "Doe",
        "gender": GenderEnum.MAN,
        "date_of_birth": date(1990, 1, 1),
        "info": "Test profile",
    }
    values.update(overrides)
    values["user_id"] = user.id
    profile = UserProfile(**values)
    session.add(profile)
    await session.flush()
    return profile


async def create_activation_token(
    session: AsyncSession, user: User, *, expires_in_hours: int = 24
) -> ActivationToken:
    """Create an activation token expiring the given number of hours from now."""
    token = ActivationToken(
        token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(hours=expires_in_hours),
        user_id=user.id,
    )
    session.add(token)
    await session.flush()
    return token


async def create_password_reset_token(
    session: AsyncSession, user: User, *, expires_in_minutes: int = 30
) -> PasswordResetToken:
    """Create a password reset token expiring the given minutes from now."""
    token = PasswordResetToken(
        token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
        user_id=user.id,
    )
    session.add(token)
    await session.flush()
    return token


async def create_refresh_token(
    session: AsyncSession, user: User, *, expires_in_days: int = 7
) -> RefreshToken:
    """Create a refresh token expiring the given number of days from now."""
    token = RefreshToken(
        token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
        user_id=user.id,
    )
    session.add(token)
    await session.flush()
    return token
