"""Fixtures shared by the end-to-end suite."""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUserDep
from src.db.enums import UserGroupEnum
from src.models.accounts import UserGroup
from tests.factories.accounts import create_group


@pytest_asyncio.fixture(autouse=True)
async def seed_user_group(db_session: AsyncSession) -> UserGroup:
    """Guarantee the USER group exists before any request is served.

    Registration assigns every new account to it. The application seeds the
    groups from its lifespan hook, which ``ASGITransport`` does not run, so the
    suite has to stand the row up itself.
    """
    return await create_group(db_session, UserGroupEnum.USER)


@pytest.fixture
def protected_probe(app: FastAPI) -> FastAPI:
    """Mount a throwaway route that does nothing but require authentication.

    ``get_current_user`` is the dependency every later phase will guard its
    routes with, so it has to be tested as a route guard and not only as a
    function. The probe lives in the test suite rather than in ``src`` because
    production has no use for an endpoint that returns the caller's own id.
    """

    @app.get("/probe/")
    async def probe(current_user: CurrentUserDep) -> dict[str, int]:
        """Echo the authenticated account's id."""
        return {"user_id": current_user.id}

    return app
