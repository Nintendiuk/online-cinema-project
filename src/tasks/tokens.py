"""Scheduled maintenance of the lifecycle token tables.

The task is a transport wrapper and nothing more: it opens a session, delegates
to :class:`~src.services.accounts.tokens.TokenLifecycleService` and commits.
Any rule about *which* rows are stale belongs to the service, so that the beat
job and a request-time call can never disagree.
"""

import asyncio

from src.db.session import async_session_factory
from src.models.accounts import ActivationToken
from src.repositories.tokens import TokenRepository
from src.services.accounts.tokens import TokenLifecycleService
from src.tasks.celery_app import celery_app

__all__ = ["purge_expired_activation_tokens"]


async def _purge_expired_activation_tokens() -> int:
    """Delete expired activation tokens in one transaction; return the count."""
    async with async_session_factory() as session:
        service = TokenLifecycleService(TokenRepository(session, ActivationToken))
        removed = await service.purge_expired()
        await session.commit()
        return removed


@celery_app.task(  # type: ignore[untyped-decorator]  # celery ships no stubs
    name="src.tasks.tokens.purge_expired_activation_tokens"
)
def purge_expired_activation_tokens() -> int:
    """Celery entry point for the hourly sweep; returns rows removed.

    Celery workers run synchronously, so the async body is driven by
    ``asyncio.run`` here rather than leaking an event loop into the service.
    """
    return asyncio.run(_purge_expired_activation_tokens())
