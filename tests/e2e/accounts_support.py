"""Shared constants and read helpers for the account end-to-end tests.

Registration, activation, resend and the three session endpoints are exercised
from several test modules; the endpoint paths and the post-request database
queries live here so no module grows a private copy of them.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.models.accounts import ActivationToken, RefreshToken, User
from src.security.jwt_manager import JWTAuthManager, refresh_token_digest
from src.security.passwords import hash_password
from tests.factories.accounts import create_activation_token, create_user

REGISTER_URL = "/api/v1/accounts/register/"
ACTIVATE_URL = "/api/v1/accounts/activate/"
RESEND_URL = "/api/v1/accounts/resend-activation/"
LOGIN_URL = "/api/v1/accounts/login/"
REFRESH_URL = "/api/v1/accounts/refresh/"
LOGOUT_URL = "/api/v1/accounts/logout/"
PROBE_URL = "/probe/"

VALID_EMAIL = "newcomer@example.com"
VALID_PASSWORD = "Str0ng!Passphrase"
ACTIVATION_TTL_HOURS = 24
REFRESH_TTL_DAYS = 7


def registration_payload(
    email: str = VALID_EMAIL, password: str = VALID_PASSWORD
) -> dict[str, str]:
    """Build a registration body, overriding either field."""
    return {"email": email, "password": password}


def login_payload(
    email: str = VALID_EMAIL, password: str = VALID_PASSWORD
) -> dict[str, str]:
    """Build a login body, overriding either field."""
    return {"email": email, "password": password}


def app_jwt_manager() -> JWTAuthManager:
    """Return a manager configured exactly as the application's own.

    Tests that have to mint a token the endpoint will accept — or one it must
    reject for a specific reason — need the same secrets and algorithm the app
    runs with, and reading them from settings keeps that in one place.
    """
    settings = get_settings()
    return JWTAuthManager(
        secret_key_access=settings.secret_key_access,
        secret_key_refresh=settings.secret_key_refresh,
        algorithm=settings.jwt_algorithm,
        access_ttl=timedelta(minutes=settings.access_token_ttl_minutes),
        refresh_ttl=timedelta(days=settings.refresh_token_ttl_days),
    )


def foreign_jwt_manager() -> JWTAuthManager:
    """Return a manager whose secrets do not match the application's.

    Used to produce a token that is syntactically perfect and verifies against
    nothing the server holds.
    """
    settings = get_settings()
    return JWTAuthManager(
        secret_key_access="foreign-access-secret",
        secret_key_refresh="foreign-refresh-secret",
        algorithm=settings.jwt_algorithm,
        access_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=7),
    )


def expired_jwt_manager() -> JWTAuthManager:
    """Return a manager with negative lifetimes, so every token it mints is stale.

    A negative ``timedelta`` rather than a sleep: the expiry is a claim, and
    backdating it is exact where waiting is slow and flaky.
    """
    settings = get_settings()
    return JWTAuthManager(
        secret_key_access=settings.secret_key_access,
        secret_key_refresh=settings.secret_key_refresh,
        algorithm=settings.jwt_algorithm,
        access_ttl=timedelta(minutes=-1),
        refresh_ttl=timedelta(days=-1),
    )


def bearer(token: str) -> dict[str, str]:
    """Build the Authorization header carrying a bearer token."""
    return {"Authorization": f"Bearer {token}"}


def access_token_for(user: User) -> str:
    """Mint an access token the application will accept for this account.

    Shorter than logging in and, unlike a login, it does not also create a
    refresh row — which matters to the tests that count those rows.
    """
    return app_jwt_manager().create_access_token({"user_id": user.id})


async def active_user(
    db_session: AsyncSession,
    email: str = VALID_EMAIL,
    password: str = VALID_PASSWORD,
) -> User:
    """Create an activated account whose stored hash matches ``password``.

    The factory takes a hash, not a password, so the real hashing function is
    used here: a login test has to exercise the same comparison production does.
    """
    return await create_user(
        db_session,
        email=email,
        password_hash=hash_password(password),
        is_active=True,
    )


async def inactive_user(
    db_session: AsyncSession,
    email: str = VALID_EMAIL,
    password: str = VALID_PASSWORD,
) -> User:
    """Create an unactivated account whose stored hash matches ``password``.

    The password has to be right for the 403 to be reachable at all: login
    checks credentials before activation state, so a wrong password here would
    answer 401 and the test would pass for the wrong reason.
    """
    return await create_user(
        db_session,
        email=email,
        password_hash=hash_password(password),
        is_active=False,
    )


async def store_refresh_token(
    db_session: AsyncSession,
    user: User,
    token: str,
    *,
    expires_in_days: int = REFRESH_TTL_DAYS,
) -> RefreshToken:
    """Persist the row that backs a refresh JWT, keyed by its digest.

    Mirrors what login does. Tests cannot use the plain ``create_refresh_token``
    factory for this, because that stores a random string which no JWT will ever
    hash to.
    """
    row = RefreshToken(
        user_id=user.id,
        token=refresh_token_digest(token),
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def refresh_tokens_for(
    db_session: AsyncSession, user_id: int
) -> list[RefreshToken]:
    """Return every refresh token row currently owned by the user."""
    statement = (
        select(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    result = await db_session.execute(statement)
    return list(result.scalars().all())


async def refresh_token_exists(db_session: AsyncSession, token: str) -> bool:
    """Whether the row backing this refresh JWT is still present."""
    result = await db_session.execute(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.token == refresh_token_digest(token))
    )
    return int(result.scalar_one()) == 1


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
