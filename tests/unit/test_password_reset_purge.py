"""Tests for the scheduled sweep of expired password reset tokens.

The Celery entry point is deliberately not executed here: it opens its own
session through ``async_session_factory`` and commits, which would escape the
transaction this suite rolls back and leave rows behind for every later test.
What is asserted instead is the pair that makes the job correct — the wiring that
schedules it, and the behaviour of the service it delegates to.

The module lives under ``tests/unit`` because the phase document places it there,
although it touches the database and carries the integration marker.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.accounts import PasswordResetToken
from src.repositories.tokens import TokenRepository
from src.services.accounts.tokens import TokenLifecycleService
from src.tasks import tokens as token_tasks
from src.tasks.celery_app import celery_app
from tests.factories.accounts import create_password_reset_token, create_user

pytestmark = pytest.mark.integration

BEAT_ENTRY = "purge-expired-password-reset-tokens"
TASK_NAME = "src.tasks.tokens.purge_expired_password_reset_tokens"


def _service(db_session: AsyncSession) -> TokenLifecycleService[PasswordResetToken]:
    """Build the lifecycle service over the password reset table."""
    return TokenLifecycleService(TokenRepository(db_session, PasswordResetToken))


async def _token_count(db_session: AsyncSession) -> int:
    """Count the password reset tokens visible in this transaction."""
    result = await db_session.execute(
        select(func.count()).select_from(PasswordResetToken)
    )
    return int(result.scalar_one())


@pytest.mark.unit
def test_the_task_is_registered_and_scheduled() -> None:
    """Beat has an entry for the sweep and it points at a registered task."""
    assert hasattr(token_tasks, "purge_expired_password_reset_tokens")
    assert celery_app.conf.beat_schedule[BEAT_ENTRY]["task"] == TASK_NAME
    assert TASK_NAME in celery_app.tasks


async def test_purge_is_safe_on_an_empty_table(db_session: AsyncSession) -> None:
    """Sweeping a table with no rows removes nothing and does not raise."""
    assert await _service(db_session).purge_expired() == 0


async def test_purge_removes_only_expired_rows(db_session: AsyncSession) -> None:
    """A stale token goes; one still inside its window stays."""
    stale_owner = await create_user(db_session)
    fresh_owner = await create_user(db_session)
    await create_password_reset_token(db_session, stale_owner, expires_in_minutes=-1)
    fresh = await create_password_reset_token(
        db_session, fresh_owner, expires_in_minutes=15
    )

    removed = await _service(db_session).purge_expired()

    assert removed == 1
    assert await _token_count(db_session) == 1
    survivors = (
        (await db_session.execute(select(PasswordResetToken))).scalars().all()
    )
    assert [token.token for token in survivors] == [fresh.token]


async def test_purge_leaves_a_live_token(db_session: AsyncSession) -> None:
    """A token whose moment has not arrived is untouched."""
    owner = await create_user(db_session)
    await create_password_reset_token(db_session, owner, expires_in_minutes=15)

    assert await _service(db_session).purge_expired() == 0
    assert await _token_count(db_session) == 1


async def test_purge_respects_an_explicit_moment(db_session: AsyncSession) -> None:
    """Passing a future moment sweeps tokens that are not yet stale in real time."""
    owner = await create_user(db_session)
    await create_password_reset_token(db_session, owner, expires_in_minutes=15)

    removed = await _service(db_session).purge_expired(
        datetime.now(UTC) + timedelta(minutes=30)
    )

    assert removed == 1
    assert await _token_count(db_session) == 0
