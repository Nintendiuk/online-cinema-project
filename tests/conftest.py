"""Shared test fixtures: database isolation and an HTTP client for the app.

Every test runs inside a transaction that is rolled back afterwards, so tests
never see each other's writes. ``NullPool`` keeps connections from being reused
across event loops.
"""

from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.api.deps import get_email_sender
from src.core.config import get_settings
from src.db.base import Base
from src.db.session import get_session
from src.main import create_app
from tests.doubles.fake_email import FakeEmailSender


@pytest.fixture(scope="session")
def engine() -> Generator[AsyncEngine, None, None]:
    """Create the test engine once per session; NullPool avoids loop reuse."""
    test_engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    yield test_engine


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _schema(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Create the schema once per session and drop it afterwards."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session bound to a transaction that is rolled back after the test."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def fake_email_sender() -> FakeEmailSender:
    """Return a fresh in-memory e-mail sender for one test."""
    return FakeEmailSender()


@pytest.fixture
def app(
    db_session: AsyncSession, fake_email_sender: FakeEmailSender
) -> Generator[FastAPI, None, None]:
    """Build the application with the database and e-mail seams pinned.

    Overriding ``get_email_sender`` is what keeps SMTP out of the run: no test
    can reach a mail server even if one happens to be listening.
    """
    application = create_app()

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        """Yield the test-scoped session under the production transaction contract.

        ``get_session`` commits when the handler returns and rolls back when it
        raises; a substitute that only yields would let a failed request leave
        its flushed rows visible to the assertions that follow, and the suite
        would report atomicity the application does not actually provide.

        A savepoint rather than a real transaction, because the whole test is
        already wrapped in one that gets rolled back at teardown. Releasing or
        rolling back the savepoint leaves that outer transaction usable, so a
        test can issue a second request after a failed one.
        """
        savepoint = await db_session.begin_nested()
        try:
            yield db_session
        except Exception:
            if savepoint.is_active:
                await savepoint.rollback()
            raise
        if savepoint.is_active:
            await savepoint.commit()

    application.dependency_overrides[get_session] = override_get_session
    application.dependency_overrides[get_email_sender] = lambda: fake_email_sender
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Yield an HTTP client that talks to the app in-process over ASGI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
