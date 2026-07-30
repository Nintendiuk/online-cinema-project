"""Builders shared by the account model integration tests.

Separate from ``tests/factories/accounts.py`` on purpose. The factories build
*valid* objects for tests about behaviour; these builders exist for tests about
*constraints*, which need to construct rows by hand so the database — not the
ORM's convenience layer — is what rejects them.

Not named ``test_*`` so that pytest does not try to collect it.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import UserGroupEnum
from src.models.accounts import User, UserGroup

__all__ = ["create_group_and_user", "get_group"]


async def get_group(
    db_session: AsyncSession, name: UserGroupEnum = UserGroupEnum.USER
) -> UserGroup:
    """Return the group with this name, inserting it only when absent.

    ``name`` is unique, so a plain insert would fail the second time the helper
    is called inside one test.
    """
    result = await db_session.execute(select(UserGroup).where(UserGroup.name == name))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    group = UserGroup(name=name)
    db_session.add(group)
    await db_session.flush()
    return group


async def create_group_and_user(
    db_session: AsyncSession,
    email: str = "user@example.com",
    group_name: UserGroupEnum = UserGroupEnum.USER,
) -> tuple[UserGroup, User]:
    """Create a user attached to the named group, reusing the group if it exists."""
    group = await get_group(db_session, group_name)
    user = User(
        email=email,
        hashed_password="hashed_password_123",
        group_id=group.id,
    )
    db_session.add(user)
    await db_session.flush()
    return group, user
