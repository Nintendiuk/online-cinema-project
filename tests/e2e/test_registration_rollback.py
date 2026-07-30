"""End-to-end tests for the atomicity of registration.

Registration writes a user, writes an activation token and then sends an e-mail,
all inside one request-scoped transaction that nothing in the service commits. So
a transport failure must leave the database exactly as it was — not a user
without a token, and not a user who can never register again because a half-
written row already occupies their address.

The interesting assertion is the last one: re-registering the same address after
a failure has to succeed with 201. An error code alone would be satisfied by an
application that wrote the user and then blew up.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.models.accounts import ActivationToken, User
from tests.doubles.fake_email import FakeEmailSender
from tests.e2e.accounts_support import (
    REGISTER_URL,
    get_user,
    registration_payload,
    tokens_for,
    user_count,
)

pytestmark = pytest.mark.e2e


async def count_rows(
    db_session: AsyncSession, model: type[User | ActivationToken]
) -> int:
    """Count every row of one model, scoped to this test's transaction."""
    result = await db_session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


class TestRegistrationRollback:
    """What survives a failed activation e-mail: nothing."""

    async def test_transport_failure_is_a_bad_gateway(
        self, async_client: AsyncClient, fake_email_sender: FakeEmailSender
    ) -> None:
        """A broken mail transport surfaces as 502 with a message attached."""
        fake_email_sender.raise_on_send = True

        response = await async_client.post(REGISTER_URL, json=registration_payload())

        assert response.status_code == 502
        assert response.json()["detail"]

    async def test_no_user_row_survives(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
        fake_email_sender: FakeEmailSender,
    ) -> None:
        """The account is rolled back, not left inactive and unreachable."""
        before = await count_rows(db_session, User)
        fake_email_sender.raise_on_send = True

        await async_client.post(REGISTER_URL, json=registration_payload())

        assert await count_rows(db_session, User) == before
        assert await get_user(db_session, registration_payload()["email"]) is None

    async def test_no_activation_token_row_survives(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
        fake_email_sender: FakeEmailSender,
    ) -> None:
        """The token is rolled back with its user."""
        before = await count_rows(db_session, ActivationToken)
        fake_email_sender.raise_on_send = True

        await async_client.post(REGISTER_URL, json=registration_payload())

        assert await count_rows(db_session, ActivationToken) == before

    async def test_the_double_recorded_nothing(
        self, async_client: AsyncClient, fake_email_sender: FakeEmailSender
    ) -> None:
        """The send aborted before a message was composed."""
        fake_email_sender.raise_on_send = True

        await async_client.post(REGISTER_URL, json=registration_payload())

        assert fake_email_sender.sent == []

    async def test_the_same_address_registers_once_the_transport_recovers(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
        fake_email_sender: FakeEmailSender,
    ) -> None:
        """201 rather than 409, which is what proves nothing was half-written."""
        payload = registration_payload()
        fake_email_sender.raise_on_send = True
        failed = await async_client.post(REGISTER_URL, json=payload)
        assert failed.status_code == 502

        fake_email_sender.raise_on_send = False
        response = await async_client.post(REGISTER_URL, json=payload)

        assert response.status_code == 201
        assert await user_count(db_session, payload["email"]) == 1
        assert len(await tokens_for(db_session, response.json()["id"])) == 1
        assert fake_email_sender.count_for(payload["email"]) == 1

    async def test_failure_does_not_leak_transport_configuration(
        self, async_client: AsyncClient, fake_email_sender: FakeEmailSender
    ) -> None:
        """The 502 body names no host, port, credential or transport library.

        Each configured value is checked only when it is non-empty: an empty
        setting is a substring of every string and would make the assertion pass
        or fail for reasons that have nothing to do with leaking.
        """
        settings = get_settings()
        fake_email_sender.raise_on_send = True

        response = await async_client.post(REGISTER_URL, json=registration_payload())

        assert response.status_code == 502
        body = response.text.lower()
        for secret in (
            settings.email_host,
            str(settings.email_port),
            settings.email_user,
            settings.email_password,
        ):
            if secret:
                assert secret.lower() not in body
        assert "smtp" not in body
        assert "aiosmtplib" not in body
