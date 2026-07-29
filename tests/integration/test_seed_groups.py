"""Integration tests for the default user group seed."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import UserGroupEnum
from src.db.seed.groups import ensure_default_groups
from src.models.accounts import UserGroup

pytestmark = pytest.mark.integration


async def _group_names(db_session: AsyncSession) -> set[UserGroupEnum]:
    """Return the set of group names currently stored."""
    result = await db_session.execute(select(UserGroup.name))
    return set(result.scalars().all())


async def test_seed_creates_all_groups(db_session: AsyncSession) -> None:
    """The first run inserts every member of UserGroupEnum."""
    await ensure_default_groups(db_session)

    assert await _group_names(db_session) == set(UserGroupEnum)


async def test_seed_is_idempotent(db_session: AsyncSession) -> None:
    """A second run inserts nothing and raises no uniqueness error."""
    await ensure_default_groups(db_session)
    await ensure_default_groups(db_session)

    total = await db_session.scalar(select(func.count()).select_from(UserGroup))
    assert total == len(UserGroupEnum)


async def test_seed_completes_a_partial_set(db_session: AsyncSession) -> None:
    """Only the missing groups are inserted when some already exist."""
    db_session.add(UserGroup(name=UserGroupEnum.ADMIN))
    await db_session.flush()

    await ensure_default_groups(db_session)

    assert await _group_names(db_session) == set(UserGroupEnum)
