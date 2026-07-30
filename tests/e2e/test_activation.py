"""End-to-end tests for account activation and activation resend.

Written before the endpoints exist: these fail until block C2 lands the service,
dependencies and routes. The resend cases carry the account-existence disclosure
guard — an unknown address and a settled account must be indistinguishable.
"""

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.accounts_support import (
    ACTIVATE_URL,
    RESEND_URL,
    VALID_EMAIL,
    get_user,
    pending_user,
    tokens_for,
)
from tests.factories.accounts import create_activation_token, create_user

if TYPE_CHECKING:  # the double arrives with F2.4, the fixture with block C2
    from tests.doubles.fake_email import FakeEmailSender

pytestmark = pytest.mark.e2e


class TestActivation:
    """POST /api/v1/accounts/activate/."""

    async def test_valid_token_activates_and_consumes_the_token(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A matching pair activates the account and deletes the token row."""
        user, token = await pending_user(db_session, "pending@example.com")

        response = await async_client.post(
            ACTIVATE_URL, json={"email": user.email, "token": token.token}
        )

        assert response.status_code == 200
        assert "message" in response.json()
        refreshed = await get_user(db_session, "pending@example.com")
        assert refreshed is not None
        assert refreshed.is_active is True
        assert await tokens_for(db_session, user.id) == []

    async def test_reusing_a_consumed_token_returns_400(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A token is single-use; the second attempt is rejected."""
        user, token = await pending_user(db_session, "reuse@example.com")
        body = {"email": user.email, "token": token.token}
        first = await async_client.post(ACTIVATE_URL, json=body)
        assert first.status_code == 200

        response = await async_client.post(ACTIVATE_URL, json=body)

        assert response.status_code == 400

    async def test_expired_token_returns_400_mentioning_expiry(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """An elapsed token is refused with a message that names the cause."""
        user, token = await pending_user(
            db_session, "stale@example.com", expires_in_hours=-1
        )

        response = await async_client.post(
            ACTIVATE_URL, json={"email": user.email, "token": token.token}
        )

        assert response.status_code == 400
        assert "expire" in response.json()["detail"].lower()

    async def test_token_belonging_to_another_user_returns_400(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Ownership is checked: another account's token does not activate."""
        owner, token = await pending_user(db_session, "owner@example.com")
        intruder, _ = await pending_user(db_session, "intruder@example.com")

        response = await async_client.post(
            ACTIVATE_URL, json={"email": intruder.email, "token": token.token}
        )

        assert response.status_code == 400
        refreshed = await get_user(db_session, "intruder@example.com")
        assert refreshed is not None
        assert refreshed.is_active is False
        assert len(await tokens_for(db_session, owner.id)) == 1

    async def test_unknown_token_returns_400(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A token that was never issued is refused."""
        user, _ = await pending_user(db_session, "unknown@example.com")

        response = await async_client.post(
            ACTIVATE_URL, json={"email": user.email, "token": "not-a-real-token"}
        )

        assert response.status_code == 400

    async def test_already_active_account_returns_400(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Activating twice conflicts with the account's current state."""
        user = await create_user(db_session, email="live@example.com", is_active=True)
        token = await create_activation_token(db_session, user)

        response = await async_client.post(
            ACTIVATE_URL, json={"email": user.email, "token": token.token}
        )

        assert response.status_code == 400

    async def test_empty_token_returns_422(self, async_client: AsyncClient) -> None:
        """An empty token fails schema validation, not domain validation."""
        response = await async_client.post(
            ACTIVATE_URL, json={"email": VALID_EMAIL, "token": ""}
        )

        assert response.status_code == 422


class TestResendActivation:
    """POST /api/v1/accounts/resend-activation/."""

    async def test_expired_token_is_replaced_and_emailed(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        fake_email_sender: "FakeEmailSender",
    ) -> None:
        """The stale token is swapped for exactly one fresh, longer-lived token."""
        user, old = await pending_user(
            db_session, "resend@example.com", expires_in_hours=-1
        )
        old_value, old_expiry = old.token, old.expires_at

        response = await async_client.post(RESEND_URL, json={"email": user.email})

        assert response.status_code == 200
        tokens = await tokens_for(db_session, user.id)
        assert len(tokens) == 1
        assert tokens[0].token != old_value
        assert tokens[0].expires_at > old_expiry
        assert fake_email_sender.count_for(user.email) == 1

    async def test_replaced_token_no_longer_activates(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The superseded value is dead even though the account is still pending."""
        user, old = await pending_user(
            db_session, "superseded@example.com", expires_in_hours=-1
        )
        old_value = old.token
        await async_client.post(RESEND_URL, json={"email": user.email})

        response = await async_client.post(
            ACTIVATE_URL, json={"email": user.email, "token": old_value}
        )

        assert response.status_code == 400

    async def test_active_account_gets_neutral_response_without_side_effects(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        fake_email_sender: "FakeEmailSender",
    ) -> None:
        """An already-active account triggers neither a token nor a message."""
        user = await create_user(
            db_session, email="settled@example.com", is_active=True
        )

        response = await async_client.post(RESEND_URL, json={"email": user.email})

        assert response.status_code == 200
        assert await tokens_for(db_session, user.id) == []
        assert fake_email_sender.sent == []

    async def test_unknown_email_gets_neutral_response_without_side_effects(
        self, async_client: AsyncClient, fake_email_sender: "FakeEmailSender"
    ) -> None:
        """An address with no account is answered as though it had one."""
        response = await async_client.post(
            RESEND_URL, json={"email": "ghost@example.com"}
        )

        assert response.status_code == 200
        assert fake_email_sender.sent == []

    async def test_active_and_unknown_responses_are_indistinguishable(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Account existence must not leak through the status or the body bytes."""
        user = await create_user(
            db_session, email="present@example.com", is_active=True
        )

        active = await async_client.post(RESEND_URL, json={"email": user.email})
        unknown = await async_client.post(
            RESEND_URL, json={"email": "absent@example.com"}
        )

        assert active.status_code == unknown.status_code
        assert active.content == unknown.content
