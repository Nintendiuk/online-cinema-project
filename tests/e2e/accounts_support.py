"""Shared constants and read helpers for the account end-to-end tests.

Registration, activation and resend are exercised from two test modules; the
endpoint paths and the post-request database queries live here so neither module
grows a private copy of them.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.accounts import ActivationToken, User
from tests.factories.accounts import create_activation_token, create_user

REGISTER_URL = "/api/v1/accounts/register/"
ACTIVATE_URL = "/api/v1/accounts/activate/"
RESEND_URL = "/api/v1/accounts/resend-activation/"

VALID_EMAIL = "newcomer@example.com"
VALID_PASSWORD = "Str0ng!Passphrase"
ACTIVATION_TTL_HOURS = 24


def registration_payload(
    email: str = VALID_EMAIL, password: str = VALID_PASSWORD
) -> dict[str, str]:
    """Build a registration body, overriding either field."""
    return {"email": email, "password": password}


async def get_user(db_session: AsyncSession, email: str) -> User | None:
    """Return the user with this e-mail, refreshed from the database.

    ``populate_existing`` rather than ``expire_all``: expiring the whole session
    would also invalidate the objects the test is still holding, and reading an
    attribute off one of those would then attempt lazy IO from synchronous
    context and raise ``MissingGreenlet``.
    """
    statement = (
        select(User)
        .where(User.email == email)
        .execution_options(populate_existing=True)
    )
    result = await db_session.execute(statement)
    return result.scalar_one_or_none()


async def user_count(db_session: AsyncSession, email: str) -> int:
    """Count users stored under this exact e-mail."""
    result = await db_session.execute(
        select(func.count()).select_from(User).where(User.email == email)
    )
    return int(result.scalar_one())


async def tokens_for(db_session: AsyncSession, user_id: int) -> list[ActivationToken]:
    """Return every activation token currently owned by the user."""
    statement = (
        select(ActivationToken)
        .where(ActivationToken.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    result = await db_session.execute(statement)
    return list(result.scalars().all())


async def pending_user(
    db_session: AsyncSession,
    email: str,
    *,
    expires_in_hours: int = ACTIVATION_TTL_HOURS,
) -> tuple[User, ActivationToken]:
    """Create an inactive user together with exactly one activation token."""
    user = await create_user(db_session, email=email, is_active=False)
    token = await create_activation_token(
        db_session, user, expires_in_hours=expires_in_hours
    )
    return user, token
