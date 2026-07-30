"""Fixtures shared by the end-to-end suite."""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUserDep
from src.db.enums import UserGroupEnum
from src.db.seed.groups import ensure_default_groups
from src.models.accounts import UserGroup
from tests.factories.accounts import create_group


@pytest_asyncio.fixture(autouse=True)
async def seed_user_group(db_session: AsyncSession) -> UserGroup:
    """Guarantee every reference group exists before any request is served.

    Registration assigns each new account to the USER group and an administrator
    may move one into any of the others, so all of them have to be present. The
    application seeds them from its lifespan hook, which ``ASGITransport`` does
    not run, so the suite stands them up itself — through the production seeding
    function, so that the rows a test sees are the rows production creates.

    The USER group is returned because it is the one a test is most likely to
    want a handle on.
    """
    await ensure_default_groups(db_session)
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
