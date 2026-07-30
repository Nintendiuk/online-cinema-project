"""Integration tests for the administrative service below the HTTP layer.

Everything the endpoints can reach is covered end to end in
``tests/e2e/test_admin_users.py``. What is left here is the one failure a request
cannot produce once the groups are seeded: an account being moved into a group
whose row is missing. The schema accepts the value — it is a member of the enum —
so only an unseeded database can get this far, and the service has to answer
rather than raise a ``TypeError`` on ``None``.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.db.enums import UserGroupEnum
from src.models.accounts import ActivationToken, UserGroup
from src.repositories.accounts import UserRepository
from src.repositories.base import BaseRepository
from src.repositories.tokens import TokenRepository
from src.services.accounts.admin import AdminService
from src.services.accounts.tokens import TokenLifecycleService
from tests.factories.accounts import create_user

pytestmark = pytest.mark.integration


def _service(db_session: AsyncSession) -> AdminService:
    """Assemble the service exactly as the dependency does, over the test session."""
    return AdminService(
        users=UserRepository(db_session),
        groups=BaseRepository(db_session, UserGroup),
        activation_tokens=TokenLifecycleService(
            TokenRepository(db_session, ActivationToken)
        ),
    )


async def test_change_group_reports_an_unseeded_group(
    db_session: AsyncSession,
) -> None:
    """A group with no row is reported, not assumed.

    Only the USER group is created here — by the user factory — so asking for the
    administrator group exercises the branch the e2e suite cannot reach.
    """
    user = await create_user(db_session)

    with pytest.raises(NotFoundError):
        await _service(db_session).change_group(user.id, UserGroupEnum.ADMIN)


async def test_change_group_leaves_the_account_alone_when_the_group_is_missing(
    db_session: AsyncSession,
) -> None:
    """The failure happens before the write, so the account keeps its group."""
    user = await create_user(db_session)
    original_group_id = user.group_id

    with pytest.raises(NotFoundError):
        await _service(db_session).change_group(user.id, UserGroupEnum.MODERATOR)

    assert user.group_id == original_group_id
