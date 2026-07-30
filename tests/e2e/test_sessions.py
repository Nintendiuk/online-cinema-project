"""End-to-end tests for logout and concurrent sessions.

The concurrency group is the point of this module. ``TokenLifecycleService.issue``
revokes a user's other tokens by default, which is right for activation and fatal
for sessions, so login passes ``replace_existing=False``. If that flag were ever
dropped, logging in on a second device would silently sign the first one out —
and only a test that keeps two sessions alive at once would notice.

Split out of ``test_authentication.py`` to stay under the 300-line module cap;
the route guard itself is covered in ``test_route_guard.py``.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.accounts_support import (
    LOGIN_URL,
    LOGOUT_URL,
    REFRESH_URL,
    active_user,
    app_jwt_manager,
    bearer,
    login_payload,
    refresh_token_exists,
    refresh_tokens_for,
    store_refresh_token,
)

pytestmark = pytest.mark.e2e


async def open_session(async_client: AsyncClient) -> tuple[str, str]:
    """Log in and return the ``(access, refresh)`` pair as the client sees it."""
    response = await async_client.post(LOGIN_URL, json=login_payload())
    assert response.status_code == 201
    body = response.json()
    return body["access_token"], body["refresh_token"]


class TestLogout:
    """Ending one session."""

    async def test_logout_removes_the_presented_session(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """200, and the row backing that refresh token is gone."""
        await active_user(db_session)
        access, refresh = await open_session(async_client)

        response = await async_client.post(
            LOGOUT_URL, json={"refresh_token": refresh}, headers=bearer(access)
        )

        assert response.status_code == 200
        assert await refresh_token_exists(db_session, refresh) is False

    async def test_refresh_after_logout_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """The revoked token cannot be spent again."""
        await active_user(db_session)
        access, refresh = await open_session(async_client)
        await async_client.post(
            LOGOUT_URL, json={"refresh_token": refresh}, headers=bearer(access)
        )

        response = await async_client.post(REFRESH_URL, json={"refresh_token": refresh})

        assert response.status_code == 401

    async def test_logout_without_a_header_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """The endpoint is guarded; an anonymous caller gets 401."""
        await active_user(db_session)
        _, refresh = await open_session(async_client)

        response = await async_client.post(LOGOUT_URL, json={"refresh_token": refresh})

        assert response.status_code == 401

    @pytest.mark.parametrize(
        "header",
        [
            {"Authorization": "Bearer"},
            {"Authorization": "Token abc"},
            {"Authorization": "abc"},
            {"Authorization": "Bearer "},
            {"Authorization": ""},
        ],
        ids=["scheme-only", "wrong-scheme", "no-scheme", "empty-token", "empty-header"],
    )
    async def test_logout_with_a_malformed_header_is_unauthorised(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
        header: dict[str, str],
    ) -> None:
        """Every shape of broken Authorization header is 401, never a 500."""
        await active_user(db_session)
        _, refresh = await open_session(async_client)

        response = await async_client.post(
            LOGOUT_URL, json={"refresh_token": refresh}, headers=header
        )

        assert response.status_code == 401

    async def test_logout_with_a_foreign_refresh_token_leaves_it_intact(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """Authenticating as one account cannot end another account's session."""
        victim = await active_user(db_session, email="victim@example.com")
        victim_token = app_jwt_manager().create_refresh_token({"user_id": victim.id})
        await store_refresh_token(db_session, victim, victim_token)
        await active_user(db_session)
        attacker_access, _ = await open_session(async_client)

        response = await async_client.post(
            LOGOUT_URL,
            json={"refresh_token": victim_token},
            headers=bearer(attacker_access),
        )

        assert response.status_code == 401
        assert await refresh_token_exists(db_session, victim_token) is True

    async def test_logout_with_an_unknown_refresh_token_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """A signed token with no row behind it cannot be revoked."""
        user = await active_user(db_session)
        access, _ = await open_session(async_client)
        orphan = app_jwt_manager().create_refresh_token({"user_id": user.id})

        response = await async_client.post(
            LOGOUT_URL, json={"refresh_token": orphan}, headers=bearer(access)
        )

        assert response.status_code == 401

    async def test_logout_with_an_expired_session_is_unauthorised(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """An elapsed row answers 401, not the 400 a raw expiry would map to.

        Reached through the stored expiry rather than the token's own, so the
        translation inside ``logout`` is what is under test.
        """
        user = await active_user(db_session)
        access, _ = await open_session(async_client)
        stale = app_jwt_manager().create_refresh_token({"user_id": user.id})
        await store_refresh_token(db_session, user, stale, expires_in_days=-1)

        response = await async_client.post(
            LOGOUT_URL, json={"refresh_token": stale}, headers=bearer(access)
        )

        assert response.status_code == 401


class TestConcurrentSessions:
    """Several live sessions per account, which is what refresh tokens are for."""

    async def test_two_logins_produce_two_live_sessions(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """Logging in twice leaves two distinct rows, not one replaced row."""
        user = await active_user(db_session)

        _, first = await open_session(async_client)
        _, second = await open_session(async_client)

        assert first != second
        rows = await refresh_tokens_for(db_session, user.id)
        assert len(rows) == 2

    async def test_both_sessions_can_refresh(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """Neither login invalidated the other's token."""
        await active_user(db_session)
        _, first = await open_session(async_client)
        _, second = await open_session(async_client)

        first_refresh = await async_client.post(
            REFRESH_URL, json={"refresh_token": first}
        )
        second_refresh = await async_client.post(
            REFRESH_URL, json={"refresh_token": second}
        )

        assert first_refresh.status_code == 200
        assert second_refresh.status_code == 200

    async def test_logging_out_of_one_session_leaves_the_other_working(
        self, db_session: AsyncSession, async_client: AsyncClient
    ) -> None:
        """The acceptance gate for this phase, proven rather than inspected."""
        await active_user(db_session)
        first_access, first_refresh = await open_session(async_client)
        _, second_refresh = await open_session(async_client)

        await async_client.post(
            LOGOUT_URL,
            json={"refresh_token": first_refresh},
            headers=bearer(first_access),
        )

        assert await refresh_token_exists(db_session, first_refresh) is False
        survivor = await async_client.post(
            REFRESH_URL, json={"refresh_token": second_refresh}
        )
        assert survivor.status_code == 200
