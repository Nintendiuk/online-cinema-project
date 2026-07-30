"""Specialised account queries.

CRUD comes from :class:`~src.repositories.base.BaseRepository`; only lookups that
need eager loading or a non-trivial clause are written here.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.accounts import User
from src.repositories.base import BaseRepository

__all__ = ["UserRepository"]


class UserRepository(BaseRepository[User]):
    """Lookups over user accounts."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session; the model is fixed to ``User``."""
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        """Return the account with this address, group and profile preloaded.

        Eager loading matters here: the caller is usually outside the session's
        reach by the time it touches ``user.group``, and a lazy load there would
        raise instead of querying.
        """
        statement = (
            select(User)
            .where(User.email == email)
            .options(selectinload(User.group), selectinload(User.profile))
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_with_group(self, user_id: int) -> User | None:
        """Return the account with this id, its group loaded and rows refreshed.

        Distinct from ``get_by_id`` for two reasons, both of which the
        authorisation check depends on. The inherited method reads through the
        identity map and leaves relationships lazy, so touching ``user.group``
        would attempt database IO from a synchronous attribute access — which
        raises under the async driver. And a cached instance answers with the
        group the account held when it was first loaded, whereas
        ``populate_existing`` re-reads the row; that is what makes a group change
        effective on the target's very next request instead of their next login.
        """
        statement = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.group))
            .execution_options(populate_existing=True)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        """Whether any account already uses this address."""
        return await self.exists(email=email)
