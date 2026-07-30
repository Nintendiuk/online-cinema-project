"""Set-based queries over the lifecycle token tables.

CRUD still comes from :class:`~src.repositories.base.BaseRepository`. What is
added here are the two bulk deletes, which must run as single statements: the
purge job sweeps a whole table on a schedule, and loading every row into the
identity map first would make its cost grow with the table.
"""

from datetime import datetime
from typing import Any, TypeVar, cast

from sqlalchemy import ColumnElement, CursorResult, delete

from src.models.accounts import ActivationToken, PasswordResetToken, RefreshToken
from src.repositories.base import BaseRepository

__all__ = ["TokenRepository", "TokenT"]

TokenT = TypeVar(
    "TokenT",
    ActivationToken,
    PasswordResetToken,
    RefreshToken,
)


class TokenRepository(BaseRepository[TokenT]):
    """CRUD plus the set-based deletes the token lifecycle needs.

    Construction is inherited unchanged from ``BaseRepository``: pass the
    session and the token model class.
    """

    async def delete_for_user(self, user_id: int) -> int:
        """Delete every token this user holds; returns the row count."""
        return await self._delete_where(self._model.user_id == user_id)

    async def delete_expired(self, moment: datetime) -> int:
        """Delete every token whose expiry is at or before ``moment``.

        Returns the row count, so a scheduled job can report what it swept
        without paying for a second query.
        """
        return await self._delete_where(self._model.expires_at <= moment)

    async def _delete_where(self, condition: ColumnElement[bool]) -> int:
        """Run one bulk delete and report how many rows it removed.

        ``execute`` is typed as returning a plain ``Result``; a DML statement
        actually yields a ``CursorResult``, which is the only one of the two
        that carries ``rowcount``.
        """
        statement = delete(self._model).where(condition)
        result = cast("CursorResult[Any]", await self._session.execute(statement))
        await self._session.flush()
        return int(result.rowcount)
