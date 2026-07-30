"""End-to-end tests for the authenticated password change.

Written before the endpoint exists. Two properties carry most of the weight
here. The account the change applies to comes from the bearer token and from
nowhere else, so there is no user identifier in the payload to tamper with; and
a successful change ends every session the account holds, which is the "log out
everywhere" caller the token lifecycle was built to support.
"""

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.accounts_support import (
    LOGIN_URL,
    REFRESH_URL,
    VALID_PASSWORD,
    access_token_for,
    active_user,
    bearer,
    get_user,
    login_payload,
    refresh_tokens_for,
)
from tests.e2e.passwords_support import (
    CHANGE_PASSWORD_URL,
    NEW_PASSWORD,
    WEAK_PASSWORDS,
    change_payload,
)

if TYPE_CHECKING:
    from tests.doubles.fake_email import FakeEmailSender

pytestmark = pytest.mark.e2e


class TestPasswordChange:
    """POST /api/v1/accounts/change-password/."""

    async def test_correct_old_password_swaps_the_credential(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        fake_email_sender: "FakeEmailSender",
    ) -> None:
        """The old password stops working, the new one starts, and mail goes out."""
        user = await active_user(db_session, email="changer@example.com")

        response = await async_client.post(
            CHANGE_PASSWORD_URL,
            json=change_payload(VALID_PASSWORD, NEW_PASSWORD),
            headers=bearer(access_token_for(user)),
        )

        assert response.status_code == 200
        stale = await async_client.post(
            LOGIN_URL, json=login_payload(user.email, VALID_PASSWORD)
        )
        assert stale.status_code == 401
        fresh = await async_client.post(
            LOGIN_URL, json=login_payload(user.email, NEW_PASSWORD)
        )
        assert fresh.status_code == 201
        assert fake_email_sender.count_for(user.email) == 1

    async def test_change_revokes_every_session(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Both open sessions are dropped and the older refresh token is dead."""
        user = await active_user(db_session, email="sessions@example.com")
        first = await async_client.post(
            LOGIN_URL, json=login_payload(user.email, VALID_PASSWORD)
        )
        second = await async_client.post(
            LOGIN_URL, json=login_payload(user.email, VALID_PASSWORD)
        )
        assert len(await refresh_tokens_for(db_session, user.id)) == 2
        refresh_token = first.json()["refresh_token"]

        response = await async_client.post(
            CHANGE_PASSWORD_URL,
            json=change_payload(VALID_PASSWORD, NEW_PASSWORD),
            headers=bearer(second.json()["access_token"]),
        )

        assert response.status_code == 200
        assert await refresh_tokens_for(db_session, user.id) == []
        renewed = await async_client.post(
            REFRESH_URL, json={"refresh_token": refresh_token}
        )
        assert renewed.status_code == 401

    async def test_wrong_old_password_is_unauthorised(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The old password is a credential, so failing it is 401."""
        user = await active_user(db_session, email="mistyped@example.com")
        original_hash = user.hashed_password

        response = await async_client.post(
            CHANGE_PASSWORD_URL,
            json=change_payload("Wr0ng!Password", NEW_PASSWORD),
            headers=bearer(access_token_for(user)),
        )

        assert response.status_code == 401
        stored = await get_user(db_session, user.email)
        assert stored is not None
        assert stored.hashed_password == original_hash

    async def test_reusing_the_current_password_is_a_bad_request(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A well-formed request the current state forbids is 400, not 422."""
        user = await active_user(db_session, email="samesame@example.com")

        response = await async_client.post(
            CHANGE_PASSWORD_URL,
            json=change_payload(VALID_PASSWORD, VALID_PASSWORD),
            headers=bearer(access_token_for(user)),
        )

        assert response.status_code == 400

    @pytest.mark.parametrize("rule", sorted(WEAK_PASSWORDS))
    async def test_weak_new_password_is_rejected(
        self, async_client: AsyncClient, db_session: AsyncSession, rule: str
    ) -> None:
        """Every strength rule is enforced on the new password, the bcrypt cap too."""
        user = await active_user(db_session, email=f"weak-{rule}@example.com")

        response = await async_client.post(
            CHANGE_PASSWORD_URL,
            json=change_payload(VALID_PASSWORD, WEAK_PASSWORDS[rule]),
            headers=bearer(access_token_for(user)),
        )

        assert response.status_code == 422

    async def test_anonymous_caller_is_unauthorised(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The route is behind the bearer guard; no header means no change."""
        await active_user(db_session, email="anon@example.com")

        response = await async_client.post(
            CHANGE_PASSWORD_URL, json=change_payload(VALID_PASSWORD, NEW_PASSWORD)
        )

        assert response.status_code == 401

    async def test_caller_cannot_name_another_account(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """There is no identifier in the payload to point at somebody else.

        The schema forbids extra keys, so smuggling one in is refused outright,
        and a legitimate change by the caller leaves the other account alone.
        """
        caller = await active_user(db_session, email="caller@example.com")
        victim = await active_user(db_session, email="victim@example.com")
        victim_hash = victim.hashed_password

        smuggled = await async_client.post(
            CHANGE_PASSWORD_URL,
            json={
                "old_password": VALID_PASSWORD,
                "new_password": NEW_PASSWORD,
                "user_id": victim.id,
            },
            headers=bearer(access_token_for(caller)),
        )
        assert smuggled.status_code == 422

        own = await async_client.post(
            CHANGE_PASSWORD_URL,
            json=change_payload(VALID_PASSWORD, NEW_PASSWORD),
            headers=bearer(access_token_for(caller)),
        )
        assert own.status_code == 200
        stored = await get_user(db_session, victim.email)
        assert stored is not None
        assert stored.hashed_password == victim_hash
