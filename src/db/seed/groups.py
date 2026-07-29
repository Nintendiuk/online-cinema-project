"""Seeding of the reference user groups.

Called from application startup or a CLI command. Safe to run repeatedly.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import UserGroupEnum
from src.models.accounts import UserGroup

__all__ = ["ensure_default_groups"]


async def ensure_default_groups(session: AsyncSession) -> None:
    """Create any missing member of ``UserGroupEnum`` as a group row.

    Existing rows are left untouched, so repeated runs change nothing. The
    caller owns the transaction; this function flushes but does not commit.
    """
    result = await session.execute(select(UserGroup.name))
    existing = set(result.scalars().all())
    missing = [name for name in UserGroupEnum if name not in existing]
    if not missing:
        return
    session.add_all([UserGroup(name=name) for name in missing])
    await session.flush()
