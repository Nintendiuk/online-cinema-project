"""Integration tests for deletion behaviour across the account relationships.

Deleting a user must take its profile and tokens with it, and must leave its
group standing.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.accounts import (
    ActivationToken,
    PasswordResetToken,
    RefreshToken,
    User,
    UserGroup,
    UserProfile,
)
from tests.integration.accounts_model_support import create_group_and_user

pytestmark = pytest.mark.integration


class TestCascades:
    """Deletion behaviour across the account relationships."""

    async def test_delete_user_cascades_to_children(
        self, db_session: AsyncSession
    ) -> None:
        """Deleting a user removes its profile and all three token kinds."""
        _, user = await create_group_and_user(db_session, "cascade@example.com")
        expires = datetime.now(UTC) + timedelta(hours=1)
        db_session.add_all(
            [
                UserProfile(user_id=user.id),
                ActivationToken(
                    user_id=user.id, token="cascade_act", expires_at=expires
                ),
                PasswordResetToken(
                    user_id=user.id, token="cascade_reset", expires_at=expires
                ),
                RefreshToken(user_id=user.id, token="cascade_ref", expires_at=expires),
            ]
        )
        await db_session.flush()

        await db_session.execute(delete(User).where(User.id == user.id))
        db_session.expunge_all()

        for model in (UserProfile, ActivationToken, PasswordResetToken, RefreshToken):
            remaining = await db_session.scalar(select(func.count()).select_from(model))
            assert remaining == 0

    async def test_delete_user_leaves_group_intact(
        self, db_session: AsyncSession
    ) -> None:
        """A group outlives its members."""
        group, user = await create_group_and_user(db_session, "leaves@example.com")
        group_id = group.id

        await db_session.execute(delete(User).where(User.id == user.id))
        db_session.expunge_all()

        remaining = await db_session.scalar(
            select(func.count()).select_from(UserGroup).where(UserGroup.id == group_id)
        )
        assert remaining == 1
