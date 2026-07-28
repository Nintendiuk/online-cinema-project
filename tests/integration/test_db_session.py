"""Integration tests for the database session dependency and test isolation."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session

pytestmark = pytest.mark.integration

CREATE_PROBE_TABLE = (
    "CREATE TABLE isolation_probe ("
    "id INTEGER PRIMARY KEY, tag VARCHAR(50) UNIQUE NOT NULL)"
)
INSERT_PROBE_ROW = "INSERT INTO isolation_probe (id, tag) VALUES (1, 'duplicate-probe')"
COUNT_PROBE_ROWS = "SELECT COUNT(*) FROM isolation_probe WHERE tag = 'duplicate-probe'"


async def test_get_session_yields_usable_session() -> None:
    """get_session() yields a live AsyncSession that can execute a query."""
    generator = get_session()
    try:
        session = await anext(generator)
        assert isinstance(session, AsyncSession)
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    finally:
        await generator.aclose()


async def test_isolation_first_writer(db_session: AsyncSession) -> None:
    """First of two twin tests writing the same unique row into a probe table."""
    await db_session.execute(text(CREATE_PROBE_TABLE))
    await db_session.execute(text(INSERT_PROBE_ROW))
    result = await db_session.execute(text(COUNT_PROBE_ROWS))
    assert result.scalar_one() == 1


async def test_isolation_second_writer(db_session: AsyncSession) -> None:
    """Twin of the previous test: passes only if the first test was rolled back."""
    await db_session.execute(text(CREATE_PROBE_TABLE))
    await db_session.execute(text(INSERT_PROBE_ROW))
    result = await db_session.execute(text(COUNT_PROBE_ROWS))
    assert result.scalar_one() == 1
