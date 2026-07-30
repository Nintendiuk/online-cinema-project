"""End-to-end tests for the administrative account operations.

Written before the router exists. The refusals for a moderator and for a plain
user are not repeated here: they are rows in the table in
``tests/e2e/test_permissions.py``, which is the one place authorisation is
asserted so that a new guarded route costs one line rather than a test class.

The case worth reading twice is the second one. A group change takes effect on
the caller's *next request*, not on their next login, because the access token
carries only an account id and the group is read from the database every time.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import UserGroupEnum
from tests.e2e.accounts_support import access_token_for, bearer, get_user, tokens_for
from tests.e2e.rbac_support import (
    caller_in_group,
    group_change_url,
    manual_activation_url,
    user_in_group,
)
from tests.factories.accounts import create_activation_token

pytestmark = pytest.mark.e2e

MISSING_USER_ID = 10_000_000


class TestGroupChange:
    """PATCH /api/v1/admin/users/{user_id}/group/."""

    async def test_administrator_moves_an_account_between_groups(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The account lands in the new group and the response says so."""
        headers = await caller_in_group(db_session, UserGroupEnum.ADMIN)
        target = await user_in_group(
            db_session, UserGroupEnum.USER, email="promotable@example.com"
        )

        response = await async_client.patch(
            group_change_url(target.id),
            json={"group": UserGroupEnum.MODERATOR.value},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json() == {
            "id": target.id,
            "email": "promotable@example.com",
            "is_active": True,
            "group": UserGroupEnum.MODERATOR.value,
        }

    async def test_change_applies_to_the_very_next_request(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """No re-login is needed: the token names an account, not a role."""
        admin_headers = await caller_in_group(db_session, UserGroupEnum.ADMIN)
        target = await user_in_group(
            db_session, UserGroupEnum.USER, email="promoted@example.com"
        )
        own_headers = bearer(access_token_for(target))
        admin_body = {"group": UserGroupEnum.ADMIN.value}

        before = await async_client.patch(
            group_change_url(target.id), json=admin_body, headers=own_headers
        )
        assert before.status_code == 403

        promotion = await async_client.patch(
            group_change_url(target.id), json=admin_body, headers=admin_headers
        )
        assert promotion.status_code == 200

        after = await async_client.patch(
            group_change_url(target.id), json=admin_body, headers=own_headers
        )
        assert after.status_code == 200

    async def test_moving_an_account_to_its_current_group_is_a_no_op(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Re-asserting the group the account already has is not an error."""
        headers = await caller_in_group(db_session, UserGroupEnum.ADMIN)
        target = await user_in_group(
            db_session, UserGroupEnum.USER, email="settled@example.com"
        )

        response = await async_client.patch(
            group_change_url(target.id),
            json={"group": UserGroupEnum.USER.value},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["group"] == UserGroupEnum.USER.value

    async def test_unknown_account_is_not_found(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """An id nobody holds is 404, distinct from a group that does not exist."""
        headers = await caller_in_group(db_session, UserGroupEnum.ADMIN)

        response = await async_client.patch(
            group_change_url(MISSING_USER_ID),
            json={"group": UserGroupEnum.MODERATOR.value},
            headers=headers,
        )

        assert response.status_code == 404

    async def test_group_outside_the_enumeration_is_unprocessable(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The payload is validated against the enum before any service runs."""
        headers = await caller_in_group(db_session, UserGroupEnum.ADMIN)
        target = await user_in_group(
            db_session, UserGroupEnum.USER, email="unchanged@example.com"
        )

        response = await async_client.patch(
            group_change_url(target.id), json={"group": "wizard"}, headers=headers
        )

        assert response.status_code == 422


class TestManualActivation:
    """POST /api/v1/admin/users/{user_id}/activate/."""

    async def test_administrator_activates_a_pending_account(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The account becomes active and its unused activation token is dropped."""
        headers = await caller_in_group(db_session, UserGroupEnum.ADMIN)
        target = await user_in_group(
            db_session,
            UserGroupEnum.USER,
            email="waiting@example.com",
            is_active=False,
        )
        await create_activation_token(db_session, target)

        response = await async_client.post(
            manual_activation_url(target.id), headers=headers
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is True
        stored = await get_user(db_session, "waiting@example.com")
        assert stored is not None
        assert stored.is_active is True
        assert await tokens_for(db_session, target.id) == []

    async def test_activating_a_live_account_is_a_bad_request(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A well-formed request the current state forbids answers 400."""
        headers = await caller_in_group(db_session, UserGroupEnum.ADMIN)
        target = await user_in_group(
            db_session, UserGroupEnum.USER, email="already@example.com"
        )

        response = await async_client.post(
            manual_activation_url(target.id), headers=headers
        )

        assert response.status_code == 400

    async def test_unknown_account_is_not_found(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Nothing to activate is 404, not 400."""
        headers = await caller_in_group(db_session, UserGroupEnum.ADMIN)

        response = await async_client.post(
            manual_activation_url(MISSING_USER_ID), headers=headers
        )

        assert response.status_code == 404
