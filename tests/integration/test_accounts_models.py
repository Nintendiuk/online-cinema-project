"""Integration tests for the account models against a real PostgreSQL schema.

Every test runs inside the transaction opened by ``db_session`` and is rolled
back afterwards, so row counts are always scoped to the test itself.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import GenderEnum, UserGroupEnum
from src.models.accounts import (
    ActivationToken,
    PasswordResetToken,
    RefreshToken,
    User,
    UserGroup,
    UserProfile,
)

pytestmark = pytest.mark.integration


async def _get_group(
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


async def _create_group_and_user(
    db_session: AsyncSession,
    email: str = "user@example.com",
    group_name: UserGroupEnum = UserGroupEnum.USER,
) -> tuple[UserGroup, User]:
    """Create a user attached to the named group, reusing the group if it exists."""
    group = await _get_group(db_session, group_name)
    user = User(
        email=email,
        hashed_password="hashed_password_123",
        group_id=group.id,
    )
    db_session.add(user)
    await db_session.flush()
    return group, user


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


class TestUser:
    """Constraints, defaults and timestamps on the ``users`` table."""

    async def test_create_user_with_existing_group(
        self, db_session: AsyncSession
    ) -> None:
        """A user attached to an existing group persists and receives an id."""
        _, user = await _create_group_and_user(db_session, "persisted@example.com")

        assert user.id is not None

    async def test_is_active_defaults_to_false(self, db_session: AsyncSession) -> None:
        """A freshly created account is inactive until explicitly activated."""
        _, user = await _create_group_and_user(db_session, "inactive@example.com")

        assert user.is_active is False

    async def test_timestamps_are_populated_and_aware(
        self, db_session: AsyncSession
    ) -> None:
        """Both timestamps are filled by the server and carry a timezone."""
        _, user = await _create_group_and_user(db_session, "timestamps@example.com")
        await db_session.refresh(user)

        assert user.created_at is not None
        assert user.created_at.tzinfo is not None
        assert user.updated_at is not None
        assert user.updated_at.tzinfo is not None

    async def test_duplicate_email_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """The e-mail is unique across accounts."""
        group, _ = await _create_group_and_user(db_session, "dup@example.com")

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
        group, _ = await _create_group_and_user(db_session, "restrict@example.com")

        with pytest.raises(IntegrityError):
            await db_session.execute(delete(UserGroup).where(UserGroup.id == group.id))
        await db_session.rollback()


class TestProfile:
    """Constraints and optional fields on the ``user_profiles`` table."""

    async def test_create_profile_linked_to_user(
        self, db_session: AsyncSession
    ) -> None:
        """A profile persists and points back at its owner."""
        _, user = await _create_group_and_user(db_session, "profile@example.com")

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
        _, user = await _create_group_and_user(db_session, "unique_profile@example.com")

        db_session.add(UserProfile(user_id=user.id))
        await db_session.flush()

        db_session.add(UserProfile(user_id=user.id))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_all_profile_fields_optional(self, db_session: AsyncSession) -> None:
        """A profile carrying nothing but user_id is valid."""
        _, user = await _create_group_and_user(db_session, "minimal@example.com")

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
        _, man = await _create_group_and_user(db_session, "man@example.com")
        _, woman = await _create_group_and_user(db_session, "woman@example.com")

        man_profile = UserProfile(user_id=man.id, gender=GenderEnum.MAN)
        woman_profile = UserProfile(user_id=woman.id, gender=GenderEnum.WOMAN)
        db_session.add_all([man_profile, woman_profile])
        await db_session.flush()
        await db_session.refresh(man_profile)
        await db_session.refresh(woman_profile)

        assert isinstance(man_profile.gender, GenderEnum)
        assert man_profile.gender is GenderEnum.MAN
        assert woman_profile.gender is GenderEnum.WOMAN


class TestTokens:
    """Constraints and expiry behaviour shared by the three token tables."""

    async def test_create_all_token_types(self, db_session: AsyncSession) -> None:
        """One token of each kind can coexist for a single user."""
        _, user = await _create_group_and_user(db_session, "tokens@example.com")
        expires = datetime.now(UTC) + timedelta(hours=1)

        activation = ActivationToken(
            user_id=user.id, token="act_token_1", expires_at=expires
        )
        reset = PasswordResetToken(
            user_id=user.id, token="reset_token_1", expires_at=expires
        )
        refresh = RefreshToken(user_id=user.id, token="ref_token_1", expires_at=expires)
        db_session.add_all([activation, reset, refresh])
        await db_session.flush()

        assert activation.id is not None
        assert reset.id is not None
        assert refresh.id is not None

    async def test_second_activation_token_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """A user may hold at most one activation token."""
        _, user = await _create_group_and_user(db_session, "dup_act@example.com")
        expires = datetime.now(UTC) + timedelta(hours=1)

        db_session.add(
            ActivationToken(user_id=user.id, token="act_1", expires_at=expires)
        )
        await db_session.flush()

        db_session.add(
            ActivationToken(user_id=user.id, token="act_2", expires_at=expires)
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_second_password_reset_token_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """A user may hold at most one password reset token."""
        _, user = await _create_group_and_user(db_session, "dup_reset@example.com")
        expires = datetime.now(UTC) + timedelta(hours=1)

        db_session.add(
            PasswordResetToken(user_id=user.id, token="reset_1", expires_at=expires)
        )
        await db_session.flush()

        db_session.add(
            PasswordResetToken(user_id=user.id, token="reset_2", expires_at=expires)
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_multiple_refresh_tokens_allowed(
        self, db_session: AsyncSession
    ) -> None:
        """Refresh tokens are per session, so several may exist for one user."""
        _, user = await _create_group_and_user(db_session, "multi_ref@example.com")
        expires = datetime.now(UTC) + timedelta(hours=1)

        first = RefreshToken(user_id=user.id, token="ref_1", expires_at=expires)
        second = RefreshToken(user_id=user.id, token="ref_2", expires_at=expires)
        db_session.add_all([first, second])
        await db_session.flush()

        assert first.id is not None
        assert second.id is not None

    async def test_duplicate_token_value_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """The token string itself is unique within a table."""
        _, first_user = await _create_group_and_user(db_session, "tok1@example.com")
        _, second_user = await _create_group_and_user(db_session, "tok2@example.com")
        expires = datetime.now(UTC) + timedelta(hours=1)

        db_session.add(
            ActivationToken(user_id=first_user.id, token="same", expires_at=expires)
        )
        await db_session.flush()

        db_session.add(
            ActivationToken(user_id=second_user.id, token="same", expires_at=expires)
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_expires_at_is_timezone_aware(self, db_session: AsyncSession) -> None:
        """The expiry moment survives the round trip with its timezone."""
        _, user = await _create_group_and_user(db_session, "tz_token@example.com")

        token = ActivationToken(
            user_id=user.id,
            token="tz_act",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(token)
        await db_session.flush()
        await db_session.refresh(token)

        assert token.expires_at.tzinfo is not None

    async def test_is_expired_reflects_expiry_moment(
        self, db_session: AsyncSession
    ) -> None:
        """is_expired() is True for a past expiry and False for a future one."""
        _, user = await _create_group_and_user(db_session, "expiry@example.com")
        now = datetime.now(UTC)

        expired = ActivationToken(
            user_id=user.id, token="past_tok", expires_at=now - timedelta(hours=1)
        )
        valid = PasswordResetToken(
            user_id=user.id, token="future_tok", expires_at=now + timedelta(hours=1)
        )
        db_session.add_all([expired, valid])
        await db_session.flush()

        assert expired.is_expired() is True
        assert valid.is_expired() is False


class TestCascades:
    """Deletion behaviour across the account relationships."""

    async def test_delete_user_cascades_to_children(
        self, db_session: AsyncSession
    ) -> None:
        """Deleting a user removes its profile and all three token kinds."""
        _, user = await _create_group_and_user(db_session, "cascade@example.com")
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
        group, user = await _create_group_and_user(db_session, "leaves@example.com")
        group_id = group.id

        await db_session.execute(delete(User).where(User.id == user.id))
        db_session.expunge_all()

        remaining = await db_session.scalar(
            select(func.count()).select_from(UserGroup).where(UserGroup.id == group_id)
        )
        assert remaining == 1
