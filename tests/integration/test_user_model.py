"""Integration tests for the ``users`` table.

Defaults, server-side timestamps and the constraints that make an account
unusable without a group.
"""

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.accounts import User, UserGroup
from tests.integration.accounts_model_support import create_group_and_user

pytestmark = pytest.mark.integration


class TestUser:
    """Constraints, defaults and timestamps on the ``users`` table."""

    async def test_create_user_with_existing_group(
        self, db_session: AsyncSession
    ) -> None:
        """A user attached to an existing group persists and receives an id."""
        _, user = await create_group_and_user(db_session, "persisted@example.com")

        assert user.id is not None

    async def test_is_active_defaults_to_false(self, db_session: AsyncSession) -> None:
        """A freshly created account is inactive until explicitly activated."""
        _, user = await create_group_and_user(db_session, "inactive@example.com")

        assert user.is_active is False

    async def test_timestamps_are_populated_and_aware(
        self, db_session: AsyncSession
    ) -> None:
        """Both timestamps are filled by the server and carry a timezone."""
        _, user = await create_group_and_user(db_session, "timestamps@example.com")
        await db_session.refresh(user)

        assert user.created_at is not None
        assert user.created_at.tzinfo is not None
        assert user.updated_at is not None
        assert user.updated_at.tzinfo is not None

    async def test_duplicate_email_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """The e-mail is unique across accounts."""
        group, _ = await create_group_and_user(db_session, "dup@example.com")

        db_session.add(
            User(email="dup@example.com", hashed_password="pwd", group_id=group.id)
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_null_group_id_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """Group membership is mandatory: a user without a group is rejected."""
        # None is deliberately invalid here; the database constraint is what is
        # under test, so the annotation violation is intentional.
        db_session.add(
            User(
                email="nogroup@example.com",
                hashed_password="pwd",
                group_id=None,  # type: ignore[arg-type]
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_delete_group_with_users_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """RESTRICT protects a group that still has members.

        The delete is issued as a Core statement so that the database constraint
        fires instead of the ORM nulling the foreign key first.
        """
        group, _ = await create_group_and_user(db_session, "restrict@example.com")

        with pytest.raises(IntegrityError):
            await db_session.execute(delete(UserGroup).where(UserGroup.id == group.id))
        await db_session.rollback()
