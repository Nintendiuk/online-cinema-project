"""End-to-end tests for ``get_current_user`` used as a route guard.

The dependency is exercised through a real protected route rather than called
directly, because that is how every later phase will use it: what matters is the
status code a guarded endpoint returns, not the exception the function raises.
The route itself is a throwaway probe defined in ``tests/e2e/conftest.py`` —
production has no use for an endpoint that echoes the caller's own id.
"""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.accounts_support import (
    LOGIN_URL,
    PROBE_URL,
    active_user,
    app_jwt_manager,
    bearer,
    expired_jwt_manager,
    foreign_jwt_manager,
    login_payload,
)

pytestmark = pytest.mark.e2e


async def open_session(async_client: AsyncClient) -> tuple[str, str]:
    """Log in and return the ``(access, refresh)`` pair as the client sees it."""
    response = await async_client.post(LOGIN_URL, json=login_payload())
    assert response.status_code == 201
    body = response.json()
    return body["access_token"], body["refresh_token"]


class TestProtectedRoute:
    """The behaviour of ``get_current_user`` as a route guard."""

    async def test_no_header_is_unauthorised(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
        protected_probe: FastAPI,
    ) -> None:
        """A guarded route rejects an anonymous caller."""
        await active_user(db_session)

        response = await async_client.get(PROBE_URL)

        assert response.status_code == 401

    async def test_valid_access_token_is_accepted(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
        protected_probe: FastAPI,
    ) -> None:
        """A fresh access token resolves to the account that owns it."""
        user = await active_user(db_session)
        access, _ = await open_session(async_client)

        response = await async_client.get(PROBE_URL, headers=bearer(access))

        assert response.status_code == 200
        assert response.json() == {"user_id": user.id}

    @pytest.mark.parametrize(
        "token_factory",
        ["garbage", "refresh", "expired", "foreign", "subjectless"],
    )
    async def test_unusable_access_tokens_are_rejected(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
        protected_probe: FastAPI,
        token_factory: str,
    ) -> None:
        """Nothing but a live, correctly signed access token opens the route."""
        user = await active_user(db_session)
        tokens = {
            "garbage": "not.a.token",
            "refresh": app_jwt_manager().create_refresh_token({"user_id": user.id}),
            "expired": expired_jwt_manager().create_access_token({"user_id": user.id}),
            "foreign": foreign_jwt_manager().create_access_token({"user_id": user.id}),
            "subjectless": app_jwt_manager().create_access_token({}),
        }

        response = await async_client.get(
            PROBE_URL, headers=bearer(tokens[token_factory])
        )

        assert response.status_code == 401

    async def test_deactivated_account_is_forbidden(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
        protected_probe: FastAPI,
    ) -> None:
        """A valid token for a deactivated account is 403, not 401."""
        user = await active_user(db_session)
        access, _ = await open_session(async_client)
        user.is_active = False
        await db_session.flush()

        response = await async_client.get(PROBE_URL, headers=bearer(access))

        assert response.status_code == 403

    async def test_token_for_a_missing_account_is_unauthorised(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
        protected_probe: FastAPI,
    ) -> None:
        """A signed token naming an id that does not exist is refused."""
        await active_user(db_session)
        ghost = app_jwt_manager().create_access_token({"user_id": 10_000_000})

        response = await async_client.get(PROBE_URL, headers=bearer(ghost))

        assert response.status_code == 401
