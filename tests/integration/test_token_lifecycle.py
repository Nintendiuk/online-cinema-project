"""Integration tests for the two keyword parameters phase 3 added to ``issue``.

Both defaults reproduce the phase-2 behaviour exactly, which is the whole point:
activation and password reset were not touched, and the tests below pin that as
much as they pin the new paths.
"""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.accounts import ActivationToken, RefreshToken
from src.repositories.tokens import TokenRepository
from src.services.accounts.tokens import TokenLifecycleService
from tests.factories.accounts import create_user

pytestmark = pytest.mark.integration

TTL = timedelta(hours=1)


def refresh_service(session: AsyncSession) -> TokenLifecycleService[RefreshToken]:
    """Build the lifecycle service over the refresh token model."""
    return TokenLifecycleService(TokenRepository(session, RefreshToken))


def activation_service(session: AsyncSession) -> TokenLifecycleService[ActivationToken]:
    """Build the lifecycle service over the activation token model."""
    return TokenLifecycleService(TokenRepository(session, ActivationToken))


class TestReplaceExisting:
    """Whether issuing a token revokes the ones already held."""

    async def test_default_replaces_the_previous_token(
        self, db_session: AsyncSession
    ) -> None:
        """Activation keeps exactly one live token, however often it is asked."""
        user = await create_user(db_session)
        service = activation_service(db_session)

        first = await service.issue(user.id, TTL)
        second = await service.issue(user.id, TTL)

        assert first.token != second.token
        assert (
            await TokenRepository(db_session, ActivationToken).count(user_id=user.id)
            == 1
        )

    async def test_false_keeps_the_previous_token(
        self, db_session: AsyncSession
    ) -> None:
        """Sessions accumulate: a second login must not end the first."""
        user = await create_user(db_session)
        service = refresh_service(db_session)

        await service.issue(user.id, TTL, replace_existing=False)
        await service.issue(user.id, TTL, replace_existing=False)

        assert (
            await TokenRepository(db_session, RefreshToken).count(user_id=user.id) == 2
        )

    async def test_true_on_refresh_tokens_clears_every_session(
        self, db_session: AsyncSession
    ) -> None:
        """The flag still works the other way round, for a future logout-all."""
        user = await create_user(db_session)
        service = refresh_service(db_session)
        await service.issue(user.id, TTL, replace_existing=False)
        await service.issue(user.id, TTL, replace_existing=False)

        await service.issue(user.id, TTL, replace_existing=True)

        assert (
            await TokenRepository(db_session, RefreshToken).count(user_id=user.id) == 1
        )


class TestExplicitValue:
    """Whether the caller may choose the string that gets stored."""

    async def test_default_generates_a_random_value(
        self, db_session: AsyncSession
    ) -> None:
        """Omitting the value keeps the phase-2 behaviour: 32 bytes of entropy."""
        user = await create_user(db_session)

        token = await activation_service(db_session).issue(user.id, TTL)

        assert len(token.token) >= 43

    async def test_explicit_value_is_stored_verbatim(
        self, db_session: AsyncSession
    ) -> None:
        """Login stores a digest, so the value it passes must survive untouched."""
        user = await create_user(db_session)
        digest = "a" * 64

        token = await refresh_service(db_session).issue(
            user.id, TTL, value=digest, replace_existing=False
        )

        assert token.token == digest

    async def test_an_explicit_value_can_be_verified(
        self, db_session: AsyncSession
    ) -> None:
        """The row is findable by the value the caller chose."""
        user = await create_user(db_session)
        service = refresh_service(db_session)
        digest = "b" * 64
        await service.issue(user.id, TTL, value=digest, replace_existing=False)

        found = await service.verify(digest, user.id)

        assert found.token == digest

    async def test_two_explicit_values_coexist(self, db_session: AsyncSession) -> None:
        """Both new parameters work together, which is how login uses them."""
        user = await create_user(db_session)
        service = refresh_service(db_session)

        await service.issue(user.id, TTL, value="c" * 64, replace_existing=False)
        await service.issue(user.id, TTL, value="d" * 64, replace_existing=False)

        assert (
            await TokenRepository(db_session, RefreshToken).count(user_id=user.id) == 2
        )
