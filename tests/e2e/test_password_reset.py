"""End-to-end tests for the forgotten-password flow.

Written before the endpoints exist. The request half must not disclose whether
an address holds an account, so an active, an inactive and an unknown address are
answered with the same status and the same bytes. The completion half treats an
elapsed link as a bad request rather than a failed authentication: it is a
well-formed submission the current state forbids, which is 400 exactly as a stale
activation link is, and deliberately not the 401 the session endpoints answer.
"""

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.accounts_support import (
    LOGIN_URL,
    REFRESH_URL,
    VALID_PASSWORD,
    active_user,
    inactive_user,
    login_payload,
    refresh_tokens_for,
)
from tests.e2e.passwords_support import (
    NEW_PASSWORD,
    RESET_COMPLETE_URL,
    RESET_REQUEST_URL,
    WEAK_PASSWORDS,
    reset_complete_payload,
    reset_request_payload,
    reset_tokens_for,
)
from tests.factories.accounts import create_password_reset_token

if TYPE_CHECKING:
    from tests.doubles.fake_email import FakeEmailSender

pytestmark = pytest.mark.e2e

UNKNOWN_EMAIL = "nobody@example.com"


class TestResetRequest:
    """POST /api/v1/accounts/password-reset/request/."""

    async def test_active_account_gets_one_token_and_one_message(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        fake_email_sender: "FakeEmailSender",
    ) -> None:
        """Exactly one token row is stored and exactly one e-mail is handed over."""
        user = await active_user(db_session, email="forgetful@example.com")

        response = await async_client.post(
            RESET_REQUEST_URL, json=reset_request_payload(user.email)
        )

        assert response.status_code == 200
        assert len(await reset_tokens_for(db_session, user.id)) == 1
        assert fake_email_sender.count_for(user.email) == 1

    async def test_second_request_supersedes_the_first(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Asking twice leaves one live token; the earlier value no longer works."""
        user = await active_user(db_session, email="twice@example.com")
        await async_client.post(
            RESET_REQUEST_URL, json=reset_request_payload(user.email)
        )
        first_token = (await reset_tokens_for(db_session, user.id))[0].token

        await async_client.post(
            RESET_REQUEST_URL, json=reset_request_payload(user.email)
        )

        tokens = await reset_tokens_for(db_session, user.id)
        assert len(tokens) == 1
        assert tokens[0].token != first_token
        spent = await async_client.post(
            RESET_COMPLETE_URL, json=reset_complete_payload(user.email, first_token)
        )
        assert spent.status_code == 400

    async def test_inactive_and_unknown_are_answered_identically(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        fake_email_sender: "FakeEmailSender",
    ) -> None:
        """Account existence leaks through neither the status nor the body bytes."""
        live = await active_user(db_session, email="live@example.com")
        pending = await inactive_user(db_session, email="pending@example.com")

        answers = [
            await async_client.post(
                RESET_REQUEST_URL, json=reset_request_payload(address)
            )
            for address in (live.email, pending.email, UNKNOWN_EMAIL)
        ]

        assert {answer.status_code for answer in answers} == {200}
        assert len({answer.content for answer in answers}) == 1
        assert fake_email_sender.count_for(pending.email) == 0
        assert fake_email_sender.count_for(UNKNOWN_EMAIL) == 0

    async def test_inactive_account_gets_no_token(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Nothing is written for an account that has never been activated."""
        pending = await inactive_user(db_session, email="unconfirmed@example.com")

        response = await async_client.post(
            RESET_REQUEST_URL, json=reset_request_payload(pending.email)
        )

        assert response.status_code == 200
        assert await reset_tokens_for(db_session, pending.id) == []


class TestResetCompletion:
    """POST /api/v1/accounts/password-reset/complete/."""

    async def test_valid_token_replaces_the_password_and_ends_sessions(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        fake_email_sender: "FakeEmailSender",
    ) -> None:
        """The credential changes, the token is spent and every session is gone."""
        user = await active_user(db_session, email="resetter@example.com")
        opened = await async_client.post(
            LOGIN_URL, json=login_payload(user.email, VALID_PASSWORD)
        )
        refresh_token = opened.json()["refresh_token"]
        token = await create_password_reset_token(db_session, user)
        fake_email_sender.clear()

        response = await async_client.post(
            RESET_COMPLETE_URL, json=reset_complete_payload(user.email, token.token)
        )

        assert response.status_code == 200
        assert await reset_tokens_for(db_session, user.id) == []
        assert await refresh_tokens_for(db_session, user.id) == []
        renewed = await async_client.post(
            REFRESH_URL, json={"refresh_token": refresh_token}
        )
        assert renewed.status_code == 401
        fresh = await async_client.post(
            LOGIN_URL, json=login_payload(user.email, NEW_PASSWORD)
        )
        assert fresh.status_code == 201
        assert fake_email_sender.count_for(user.email) == 1

    async def test_expired_token_is_a_bad_request_naming_expiry(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A stale link answers 400 — not the 401 of a stale credential."""
        user = await active_user(db_session, email="stale@example.com")
        token = await create_password_reset_token(
            db_session, user, expires_in_minutes=-1
        )

        response = await async_client.post(
            RESET_COMPLETE_URL, json=reset_complete_payload(user.email, token.token)
        )

        assert response.status_code == 400
        assert "expire" in response.json()["detail"].lower()

    async def test_token_belonging_to_another_account_is_refused(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Ownership is checked before anything is written."""
        owner = await active_user(db_session, email="owner@example.com")
        intruder = await active_user(db_session, email="intruder@example.com")
        token = await create_password_reset_token(db_session, owner)

        response = await async_client.post(
            RESET_COMPLETE_URL, json=reset_complete_payload(intruder.email, token.token)
        )

        assert response.status_code == 400
        assert len(await reset_tokens_for(db_session, owner.id)) == 1
        unchanged = await async_client.post(
            LOGIN_URL, json=login_payload(intruder.email, VALID_PASSWORD)
        )
        assert unchanged.status_code == 201

    async def test_a_token_cannot_be_used_twice(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The token is consumed by the first use, so the second is refused."""
        user = await active_user(db_session, email="replay@example.com")
        token = await create_password_reset_token(db_session, user)
        body = reset_complete_payload(user.email, token.token)
        first = await async_client.post(RESET_COMPLETE_URL, json=body)
        assert first.status_code == 200

        response = await async_client.post(RESET_COMPLETE_URL, json=body)

        assert response.status_code == 400

    async def test_unknown_token_is_refused(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A value that was never issued cannot reset anything."""
        user = await active_user(db_session, email="phantom@example.com")

        response = await async_client.post(
            RESET_COMPLETE_URL,
            json=reset_complete_payload(user.email, "never-issued-token"),
        )

        assert response.status_code == 400

    @pytest.mark.parametrize("rule", sorted(WEAK_PASSWORDS))
    async def test_weak_new_password_is_rejected(
        self, async_client: AsyncClient, db_session: AsyncSession, rule: str
    ) -> None:
        """The reset path enforces the same strength rules as registration."""
        user = await active_user(db_session, email=f"weakreset-{rule}@example.com")
        token = await create_password_reset_token(db_session, user)

        response = await async_client.post(
            RESET_COMPLETE_URL,
            json=reset_complete_payload(
                user.email, token.token, WEAK_PASSWORDS[rule]
            ),
        )

        assert response.status_code == 422
        assert len(await reset_tokens_for(db_session, user.id)) == 1
