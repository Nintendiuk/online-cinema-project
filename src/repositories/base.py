"""Generic asynchronous CRUD.

This is the *only* CRUD implementation in the project. Concrete repositories
subclass it and add specialised queries; re-implementing get/create/update/delete
anywhere else is a review-blocking defect.

Nothing here commits. One request is one transaction and the session dependency
owns it, so a repository that committed would tear a service's work in half.
"""

from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.base import Base

__all__ = ["BaseRepository"]


class BaseRepository[ModelT: Base]:
    """Asynchronous create/read/update/delete over a single mapped model.

    Filters are passed as keyword arguments naming mapped columns and are
    combined with ``AND``. Anything richer than equality belongs in a concrete
    repository as a named query, not in here.
    """

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        """Bind the repository to a session and the model it manages."""
        self._session = session
        self._model = model

    def _conditions(self, filters: dict[str, object]) -> list[ColumnElement[bool]]:
        """Turn ``column=value`` keywords into SQLAlchemy equality clauses.

        Raises ``AttributeError`` on an unmapped name, which surfaces a typo at
        the call site instead of silently returning every row.
        """
        return [getattr(self._model, name) == value for name, value in filters.items()]

    async def get_by_id(self, entity_id: int) -> ModelT | None:
        """Return the row with this primary key, or ``None``."""
        return await self._session.get(self._model, entity_id)

    async def get_by(self, **filters: object) -> ModelT | None:
        """Return the single row matching every filter, or ``None``.

        Raises if the filters match more than one row: an ambiguous lookup is a
        bug in the caller, not a result to pick arbitrarily from.
        """
        statement = select(self._model).where(*self._conditions(filters))
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        **filters: object,
    ) -> Sequence[ModelT]:
        """Return every row matching the filters, optionally windowed."""
        statement = select(self._model).where(*self._conditions(filters))
        if offset is not None:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        result = await self._session.execute(statement)
        return result.scalars().all()

    async def create(self, **values: object) -> ModelT:
        """Insert a row and flush so the caller can read its generated key."""
        instance = self._model(**values)
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def update(self, instance: ModelT, **values: object) -> ModelT:
        """Apply the given attribute values to a loaded row and flush."""
        for name, value in values.items():
            setattr(instance, name, value)
        await self._session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        """Remove a loaded row and flush."""
        await self._session.delete(instance)
        await self._session.flush()

    async def exists(self, **filters: object) -> bool:
        """Whether at least one row matches every filter."""
        statement = select(
            select(self._model).where(*self._conditions(filters)).exists()
        )
        result = await self._session.execute(statement)
        return bool(result.scalar())

    async def count(self, **filters: object) -> int:
        """How many rows match every filter."""
        statement = (
            select(func.count())
            .select_from(self._model)
            .where(*self._conditions(filters))
        )
        result = await self._session.execute(statement)
        return int(result.scalar_one())
