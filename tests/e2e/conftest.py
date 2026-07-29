"""Fixtures shared by the end-to-end suite."""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

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
