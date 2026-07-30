"""Shared URLs and account builders for the authorisation end-to-end tests.

The callers built here authenticate with a minted access token rather than by
logging in, so none of them needs a real password hash — bcrypt at twelve rounds
is the most expensive thing in the suite and none of these tests exercise it.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import UserGroupEnum
from src.models.accounts import User
from tests.e2e.accounts_support import access_token_for, bearer
from tests.factories.accounts import create_group, create_user

ADMIN_USERS_URL = "/api/v1/admin/users"
SALES_PROBE_URL = "/probe/sales/"


def group_change_url(user_id: int) -> str:
    """URL of the group change operation for one account."""
    return f"{ADMIN_USERS_URL}/{user_id}/group/"


def manual_activation_url(user_id: int) -> str:
    """URL of the manual activation operation for one account."""
    return f"{ADMIN_USERS_URL}/{user_id}/activate/"


async def user_in_group(
    db_session: AsyncSession,
    group: UserGroupEnum,
    *,
    email: str | None = None,
    is_active: bool = True,
) -> User:
    """Create an account belonging to the named group, seeding the group row."""
    row = await create_group(db_session, group)
    return await create_user(
        db_session, email=email, is_active=is_active, group=row
    )


async def caller_in_group(
    db_session: AsyncSession, group: UserGroupEnum
) -> dict[str, str]:
    """Create an account in this group and return its Authorization header."""
    user = await user_in_group(db_session, group)
    return bearer(access_token_for(user))
