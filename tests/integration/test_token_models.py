"""Integration tests for the three lifecycle token tables.

Activation and password reset are one per account; refresh tokens are one per
session and may therefore coexist. That asymmetry is the reason phase 3 had to
add a ``replace_existing`` flag to the lifecycle service.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.accounts import ActivationToken, PasswordResetToken, RefreshToken
from tests.integration.accounts_model_support import create_group_and_user

pytestmark = pytest.mark.integration


class TestTokens:
    """Constraints and expiry behaviour shared by the three token tables."""

    async def test_create_all_token_types(self, db_session: AsyncSession) -> None:
        """One token of each kind can coexist for a single user."""
        _, user = await create_group_and_user(db_session, "tokens@example.com")
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
        _, user = await create_group_and_user(db_session, "dup_act@example.com")
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
        _, user = await create_group_and_user(db_session, "dup_reset@example.com")
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
        _, user = await create_group_and_user(db_session, "multi_ref@example.com")
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
        _, first_user = await create_group_and_user(db_session, "tok1@example.com")
        _, second_user = await create_group_and_user(db_session, "tok2@example.com")
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
        _, user = await create_group_and_user(db_session, "tz_token@example.com")

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
        _, user = await create_group_and_user(db_session, "expiry@example.com")
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
