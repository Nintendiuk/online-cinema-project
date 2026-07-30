"""Scheduled maintenance of the lifecycle token tables.

Each task is a transport wrapper and nothing more: it opens a session, delegates
to :class:`~src.services.accounts.tokens.TokenLifecycleService` and commits. Any
rule about *which* rows are stale belongs to the service, so that a beat job and
a request-time call can never disagree.

The two sweeps differ only in the model they name. That difference is a parameter
rather than a second copy of the body — a third token family would add a task
here and no new logic anywhere.
"""

import asyncio

from src.db.session import async_session_factory
from src.models.accounts import ActivationToken, PasswordResetToken
from src.repositories.tokens import TokenRepository, TokenT
from src.services.accounts.tokens import TokenLifecycleService
from src.tasks.celery_app import celery_app

__all__ = [
    "purge_expired_activation_tokens",
    "purge_expired_password_reset_tokens",
]


async def _purge_expired(model: type[TokenT]) -> int:
    """Delete every expired row of one token table; return how many went.

    Parametrised by the repository layer's own ``TokenT`` rather than a fresh
    type variable: the constraint list — which models are token models — is
    already stated once, in ``src/repositories/tokens.py``, and restating it here
    would be a second place to forget to update.
    """
    async with async_session_factory() as session:
        service = TokenLifecycleService(TokenRepository(session, model))
        removed = await service.purge_expired()
        await session.commit()
        return removed


@celery_app.task(  # type: ignore[misc]  # celery ships no stubs
    name="src.tasks.tokens.purge_expired_activation_tokens"
)
def purge_expired_activation_tokens() -> int:
    """Celery entry point for the activation sweep; returns rows removed.

    Celery workers run synchronously, so the async body is driven by
    ``asyncio.run`` here rather than leaking an event loop into the service.
    """
    return asyncio.run(_purge_expired(ActivationToken))


@celery_app.task(  # type: ignore[misc]  # celery ships no stubs
    name="src.tasks.tokens.purge_expired_password_reset_tokens"
)
def purge_expired_password_reset_tokens() -> int:
    """Celery entry point for the password reset sweep; returns rows removed.

    A spent or elapsed reset row is dead weight the moment it expires, and its
    table carries at most one row per account, so the same hourly cadence as the
    activation sweep is ample.
    """
    return asyncio.run(_purge_expired(PasswordResetToken))
