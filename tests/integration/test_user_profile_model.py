"""Integration tests for the ``user_profiles`` table.

The one-to-one link back to a user, and the fact that every descriptive field
is optional.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import GenderEnum
from src.models.accounts import UserProfile
from tests.integration.accounts_model_support import create_group_and_user

pytestmark = pytest.mark.integration


class TestProfile:
    """Constraints and optional fields on the ``user_profiles`` table."""

    async def test_create_profile_linked_to_user(
        self, db_session: AsyncSession
    ) -> None:
        """A profile persists and points back at its owner."""
        _, user = await create_group_and_user(db_session, "profile@example.com")

        profile = UserProfile(user_id=user.id, first_name="John", last_name="Doe")
        db_session.add(profile)
        await db_session.flush()
        await db_session.refresh(user, ["profile"])

        assert profile.id is not None
        assert user.profile is profile

    async def test_second_profile_for_user_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """The profile is one-to-one: a user cannot hold two of them."""
        _, user = await create_group_and_user(db_session, "unique_profile@example.com")

        db_session.add(UserProfile(user_id=user.id))
        await db_session.flush()

        db_session.add(UserProfile(user_id=user.id))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_all_profile_fields_optional(self, db_session: AsyncSession) -> None:
        """A profile carrying nothing but user_id is valid."""
        _, user = await create_group_and_user(db_session, "minimal@example.com")

        profile = UserProfile(user_id=user.id)
        db_session.add(profile)
        await db_session.flush()

        assert profile.id is not None
        assert profile.first_name is None
        assert profile.last_name is None
        assert profile.avatar is None
        assert profile.gender is None
        assert profile.date_of_birth is None
        assert profile.info is None

    async def test_gender_enum_round_trip(self, db_session: AsyncSession) -> None:
        """Both gender members persist and read back as enum members."""
        _, man = await create_group_and_user(db_session, "man@example.com")
        _, woman = await create_group_and_user(db_session, "woman@example.com")

        man_profile = UserProfile(user_id=man.id, gender=GenderEnum.MAN)
        woman_profile = UserProfile(user_id=woman.id, gender=GenderEnum.WOMAN)
        db_session.add_all([man_profile, woman_profile])
        await db_session.flush()
        await db_session.refresh(man_profile)
        await db_session.refresh(woman_profile)

        assert isinstance(man_profile.gender, GenderEnum)
        assert man_profile.gender is GenderEnum.MAN
        assert woman_profile.gender is GenderEnum.WOMAN
