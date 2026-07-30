"""End-to-end tests for login and access-token renewal.

Two contracts dominate this module. A failed login must look identical whether
the address is unknown or the password is wrong, because any difference between
the two turns the endpoint into an account-enumeration oracle. And a refresh must
fail with 401 for every kind of unusable token — unknown, expired, foreign,
wrong family — while a *deactivated owner* is the one case that answers 403,
because that caller's credential is fine and their account is not.

Logout, concurrent sessions and the protected-route probe live in
``test_sessions.py``.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.accounts_support import (
    LOGIN_URL,
    REFRESH_URL,
    VALID_EMAIL,
    VALID_PASSWORD,
    active_user,
    app_jwt_manager,
    expired_jwt_manager,
    foreign_jwt_manager,
    inactive_user,
    login_payload,
    refresh_tokens_for,
    store_refresh_token,
)

pytestmark = pytest.mark.e2e


class TestLogin:
    """Exchanging credentials for a token pair."""

    async def test_active_user_receives_both_tokens(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """A correct login answers 201 with a non-empty pair."""
        await active_user(db_session)

        response = await async_client.post(LOGIN_URL, json=login_payload())

        assert response.status_code == 201
        body = response.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["token_type"] == "bearer"

    async def test_login_persists_a_refresh_token_row(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """The session is recorded server-side, keyed by the token's digest."""
        user = await active_user(db_session)

        response = await async_client.post(LOGIN_URL, json=login_payload())

        rows = await refresh_tokens_for(db_session, user.id)
        assert len(rows) == 1
        assert rows[0].token != response.json()["refresh_token"]
        assert len(rows[0].token) == 64

    async def test_wrong_password_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """A wrong password is a credential failure, so 401."""
        await active_user(db_session)

        response = await async_client.post(
            LOGIN_URL, json=login_payload(password="Wr0ng!Passphrase")
        )

        assert response.status_code == 401

    async def test_unknown_email_is_indistinguishable_from_wrong_password(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """The two failures are byte-identical, so accounts cannot be enumerated."""
        await active_user(db_session)

        wrong_password = await async_client.post(
            LOGIN_URL, json=login_payload(password="Wr0ng!Passphrase")
        )
        unknown_email = await async_client.post(
            LOGIN_URL, json=login_payload(email="nobody@example.com")
        )

        assert wrong_password.status_code == unknown_email.status_code == 401
        assert wrong_password.content == unknown_email.content

    async def test_inactive_account_is_forbidden(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """403 and a message that points at activation, not at the password."""
        await inactive_user(db_session)

        response = await async_client.post(LOGIN_URL, json=login_payload())

        assert response.status_code == 403
        assert "activat" in response.json()["detail"].lower()

    @pytest.mark.parametrize(
        "payload",
        [
            {"email": "not-an-email", "password": VALID_PASSWORD},
            {"email": VALID_EMAIL},
            {"password": VALID_PASSWORD},
            {"email": VALID_EMAIL, "password": VALID_PASSWORD, "extra": "x"},
        ],
        ids=["malformed-email", "missing-password", "missing-email", "extra-field"],
    )
    async def test_malformed_payload_is_unprocessable(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
        payload: dict[str, str],
    ) -> None:
        """Shape errors are 422 and never reach the credential comparison."""
        await active_user(db_session)

        response = await async_client.post(LOGIN_URL, json=payload)

        assert response.status_code == 422

    async def test_weak_password_still_reaches_the_comparison(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """A short password is 401, not 422.

        Login must not run the strength rules: answering 422 would tell the
        caller their guess failed a policy check rather than the comparison.
        """
        await active_user(db_session)

        response = await async_client.post(LOGIN_URL, json=login_payload(password="a"))

        assert response.status_code == 401

    @pytest.mark.parametrize(
        "typed",
        [VALID_EMAIL.upper(), f"  {VALID_EMAIL}  ", f" {VALID_EMAIL.title()} "],
        ids=["uppercase", "padded", "padded-mixed-case"],
    )
    async def test_email_is_normalised_before_lookup(
        self, db_session: AsyncSession, async_client: AsyncClient, typed: str
    ) -> None:
        """Case and surrounding whitespace do not stop a valid login."""
        await active_user(db_session)

        response = await async_client.post(LOGIN_URL, json=login_payload(email=typed))

        assert response.status_code == 201


class TestRefresh:
    """Renewing an access token from a stored session."""

    async def test_valid_refresh_token_yields_a_new_access_token(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """200 and a fresh access token that differs from the login one."""
        await active_user(db_session)
        login = await async_client.post(LOGIN_URL, json=login_payload())
        issued = login.json()

        response = await async_client.post(
            REFRESH_URL, json={"refresh_token": issued["refresh_token"]}
        )

        assert response.status_code == 200
        assert response.json()["access_token"]
        assert response.json()["access_token"] != issued["access_token"]

    async def test_unknown_refresh_token_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """A perfectly signed token with no row behind it is refused."""
        user = await active_user(db_session)
        orphan = app_jwt_manager().create_refresh_token({"user_id": user.id})

        response = await async_client.post(REFRESH_URL, json={"refresh_token": orphan})

        assert response.status_code == 401

    async def test_expired_refresh_token_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """An elapsed session is 401, not the 400 that a raw expiry would map to."""
        user = await active_user(db_session)
        stale = expired_jwt_manager().create_refresh_token({"user_id": user.id})
        await store_refresh_token(db_session, user, stale)

        response = await async_client.post(REFRESH_URL, json={"refresh_token": stale})

        assert response.status_code == 401

    async def test_expired_row_behind_a_live_token_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """The stored expiry is enforced too, not only the one inside the JWT."""
        user = await active_user(db_session)
        token = app_jwt_manager().create_refresh_token({"user_id": user.id})
        await store_refresh_token(db_session, user, token, expires_in_days=-1)

        response = await async_client.post(REFRESH_URL, json={"refresh_token": token})

        assert response.status_code == 401

    async def test_access_token_is_not_accepted_as_a_refresh_token(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """The short-lived credential cannot be spent as the long-lived one."""
        await active_user(db_session)
        login = await async_client.post(LOGIN_URL, json=login_payload())

        response = await async_client.post(
            REFRESH_URL, json={"refresh_token": login.json()["access_token"]}
        )

        assert response.status_code == 401

    async def test_foreign_signed_token_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """A syntactically valid token signed by somebody else is refused."""
        user = await active_user(db_session)
        forged = foreign_jwt_manager().create_refresh_token({"user_id": user.id})
        await store_refresh_token(db_session, user, forged)

        response = await async_client.post(REFRESH_URL, json={"refresh_token": forged})

        assert response.status_code == 401

    async def test_token_without_a_subject_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """A correctly signed token that names no account is refused."""
        await active_user(db_session)
        anonymous = app_jwt_manager().create_refresh_token({})

        response = await async_client.post(
            REFRESH_URL, json={"refresh_token": anonymous}
        )

        assert response.status_code == 401

    async def test_token_for_a_missing_account_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """A token naming an id that no longer exists is refused."""
        await active_user(db_session)
        ghost = app_jwt_manager().create_refresh_token({"user_id": 10_000_000})

        response = await async_client.post(REFRESH_URL, json={"refresh_token": ghost})

        assert response.status_code == 401

    async def test_deactivated_owner_is_forbidden(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """Deactivating the account stops renewal with 403, not 401."""
        user = await active_user(db_session)
        login = await async_client.post(LOGIN_URL, json=login_payload())
        user.is_active = False
        await db_session.flush()

        response = await async_client.post(
            REFRESH_URL, json={"refresh_token": login.json()["refresh_token"]}
        )

        assert response.status_code == 403

    @pytest.mark.parametrize(
        "payload",
        [{}, {"refresh_token": ""}, {"refresh_token": "x", "extra": "y"}],
        ids=["missing", "empty", "extra-field"],
    )
    async def test_malformed_payload_is_unprocessable(
        self, async_client: AsyncClient, payload: dict[str, str]
    ) -> None:
        """Shape errors are 422 and never reach the token decoder."""
        response = await async_client.post(REFRESH_URL, json=payload)

        assert response.status_code == 422
