"""Integration tests for the expired-token sweep.

The hourly beat job delegates to ``TokenLifecycleService.purge_expired``; what
is pinned here is that it removes exactly the stale rows and nothing else.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.accounts import ActivationToken
from src.repositories.tokens import TokenRepository
from src.services.accounts.tokens import TokenLifecycleService
from tests.factories.accounts import create_activation_token, create_user

pytestmark = pytest.mark.integration


def _service(db_session: AsyncSession) -> TokenLifecycleService[ActivationToken]:
    """Build the lifecycle service over the activation token table."""
    return TokenLifecycleService(TokenRepository(db_session, ActivationToken))


async def _token_count(db_session: AsyncSession) -> int:
    """Count the activation tokens visible in this transaction."""
    result = await db_session.execute(select(func.count()).select_from(ActivationToken))
    return int(result.scalar_one())


async def test_purge_is_safe_on_an_empty_table(db_session: AsyncSession) -> None:
    """Sweeping a table with no rows removes nothing and does not raise."""
    assert await _service(db_session).purge_expired() == 0


async def test_purge_removes_only_expired_rows(db_session: AsyncSession) -> None:
    """Stale tokens go; a token still inside its window stays."""
    stale_owner = await create_user(db_session, is_active=False)
    fresh_owner = await create_user(db_session, is_active=False)
    await create_activation_token(db_session, stale_owner, expires_in_hours=-1)
    fresh = await create_activation_token(db_session, fresh_owner, expires_in_hours=24)

    removed = await _service(db_session).purge_expired()

    assert removed == 1
    assert await _token_count(db_session) == 1
    survivors = (await db_session.execute(select(ActivationToken))).scalars().all()
    assert [token.token for token in survivors] == [fresh.token]


async def test_purge_leaves_a_token_expiring_later(db_session: AsyncSession) -> None:
    """A token whose moment has not arrived is untouched."""
    owner = await create_user(db_session, is_active=False)
    await create_activation_token(db_session, owner, expires_in_hours=1)

    assert await _service(db_session).purge_expired() == 0
    assert await _token_count(db_session) == 1


async def test_purge_respects_an_explicit_moment(db_session: AsyncSession) -> None:
    """Passing a future moment sweeps tokens that are not yet stale in real time."""
    owner = await create_user(db_session, is_active=False)
    await create_activation_token(db_session, owner, expires_in_hours=1)

    removed = await _service(db_session).purge_expired(
        datetime.now(UTC) + timedelta(hours=2)
    )

    assert removed == 1
    assert await _token_count(db_session) == 0
