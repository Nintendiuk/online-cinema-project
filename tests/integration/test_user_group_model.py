"""Integration tests for the ``user_groups`` table.

Uniqueness of the group name and the enum round trip, both of which are
properties of the database rather than of the ORM layer above it.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import UserGroupEnum
from src.models.accounts import UserGroup

pytestmark = pytest.mark.integration


class TestUserGroups:
    """Constraints and enum handling on the ``user_groups`` table."""

    async def test_insert_all_enum_members(self, db_session: AsyncSession) -> None:
        """Every member of UserGroupEnum is a valid group name."""
        for role in UserGroupEnum:
            db_session.add(UserGroup(name=role))
        await db_session.flush()

        result = await db_session.execute(select(UserGroup))
        groups = result.scalars().all()

        assert len(groups) == len(UserGroupEnum)
        assert {group.name for group in groups} == set(UserGroupEnum)

    async def test_duplicate_name_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """The group name is unique: a second group with it must be rejected."""
        db_session.add(UserGroup(name=UserGroupEnum.USER))
        await db_session.flush()

        db_session.add(UserGroup(name=UserGroupEnum.USER))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_name_enum_round_trip(self, db_session: AsyncSession) -> None:
        """The name comes back from the database as an enum member, not a string."""
        group = UserGroup(name=UserGroupEnum.ADMIN)
        db_session.add(group)
        await db_session.flush()
        await db_session.refresh(group)

        assert isinstance(group.name, UserGroupEnum)
        assert group.name is UserGroupEnum.ADMIN
