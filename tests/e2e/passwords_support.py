"""Shared constants and read helpers for the password end-to-end tests.

Kept apart from ``accounts_support`` rather than appended to it: registration,
activation and sessions are one bounded context and password management is
another, and the older module is already close to the 300-line cap.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.accounts import PasswordResetToken

CHANGE_PASSWORD_URL = "/api/v1/accounts/change-password/"
RESET_REQUEST_URL = "/api/v1/accounts/password-reset/request/"
RESET_COMPLETE_URL = "/api/v1/accounts/password-reset/complete/"

NEW_PASSWORD = "Ev3n!Stronger"
"""A password that satisfies every strength rule and differs from the default."""

WEAK_PASSWORDS: dict[str, str] = {
    "too_short": "Sh0rt!",
    "no_uppercase": "nouppercase1!",
    "no_lowercase": "NOLOWERCASE1!",
    "no_digit": "NoDigitsHere!",
    "no_special": "NoSpecial123A",
    "over_bcrypt_limit": "A1!" + "a" * 80,
}
"""One value per strength rule, including the 72-byte bcrypt ceiling.

The keys name the rule each value breaks, so a parametrised failure reports
which one regressed instead of printing the password.
"""


def change_payload(old_password: str, new_password: str) -> dict[str, str]:
    """Build the body of a password change request."""
    return {"old_password": old_password, "new_password": new_password}


def reset_request_payload(email: str) -> dict[str, str]:
    """Build the body of a password reset request."""
    return {"email": email}


def reset_complete_payload(
    email: str, token: str, new_password: str = NEW_PASSWORD
) -> dict[str, str]:
    """Build the body that finishes a password reset."""
    return {"email": email, "token": token, "new_password": new_password}


async def reset_tokens_for(
    db_session: AsyncSession, user_id: int
) -> list[PasswordResetToken]:
    """Return every password reset token row currently owned by the user.

    ``populate_existing`` for the same reason as elsewhere in the suite: the
    request under test wrote through a different session scope, and without it
    the identity map would answer from before that write.
    """
    statement = (
        select(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    result = await db_session.execute(statement)
    return list(result.scalars().all())
