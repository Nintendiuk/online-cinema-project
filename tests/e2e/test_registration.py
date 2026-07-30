"""End-to-end tests for account registration.

Written before the endpoint exists: these fail until block C2 lands the service,
dependencies and route. Every test runs inside the transaction opened by
``db_session`` — the same session the application is pinned to — so row counts
are scoped to the test itself and reads see the application's own writes.
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import UserGroupEnum
from src.models.accounts import UserGroup
from tests.e2e.accounts_support import (
    ACTIVATION_TTL_HOURS,
    REGISTER_URL,
    VALID_EMAIL,
    VALID_PASSWORD,
    get_user,
    registration_payload,
    tokens_for,
    user_count,
)

if TYPE_CHECKING:  # the double arrives with F2.4, the fixture with block C2
    from tests.doubles.fake_email import FakeEmailSender

pytestmark = pytest.mark.e2e


class TestRegistration:
    """POST /api/v1/accounts/register/."""

    async def test_valid_payload_returns_201_and_hides_credentials(
        self, async_client: AsyncClient
    ) -> None:
        """A good payload yields 201 and a body free of password material."""
        response = await async_client.post(REGISTER_URL, json=registration_payload())

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == VALID_EMAIL
        assert isinstance(body["id"], int)
        assert "password" not in body
        assert "hashed_password" not in body

    async def test_new_user_is_inactive_and_in_the_user_group(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The stored account starts deactivated and belongs to group USER."""
        await async_client.post(REGISTER_URL, json=registration_payload())

        user = await get_user(db_session, VALID_EMAIL)
        assert user is not None
        assert user.is_active is False
        group = await db_session.get(UserGroup, user.group_id)
        assert group is not None
        assert group.name == UserGroupEnum.USER

    async def test_exactly_one_token_valid_for_24_hours_is_issued(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Registration issues a single token expiring 24 h from now."""
        before = datetime.now(UTC)

        await async_client.post(REGISTER_URL, json=registration_payload())

        user = await get_user(db_session, VALID_EMAIL)
        assert user is not None
        tokens = await tokens_for(db_session, user.id)
        assert len(tokens) == 1
        expected = before + timedelta(hours=ACTIVATION_TTL_HOURS)
        assert abs((tokens[0].expires_at - expected).total_seconds()) <= 60

    async def test_one_email_carrying_the_token_is_sent(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        fake_email_sender: "FakeEmailSender",
    ) -> None:
        """Exactly one message goes out and it carries the token value."""
        await async_client.post(REGISTER_URL, json=registration_payload())

        user = await get_user(db_session, VALID_EMAIL)
        assert user is not None
        tokens = await tokens_for(db_session, user.id)
        assert fake_email_sender.count_for(VALID_EMAIL) == 1
        assert tokens[0].token in fake_email_sender.sent[0].body

    async def test_email_is_normalized_before_storage(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Stray whitespace and mixed case are canonicalised on the way in."""
        response = await async_client.post(
            REGISTER_URL, json=registration_payload(email="  User@Mail.COM ")
        )

        assert response.status_code == 201
        assert response.json()["email"] == "user@mail.com"
        assert await get_user(db_session, "user@mail.com") is not None

    async def test_duplicate_email_returns_409_without_side_effects(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        fake_email_sender: "FakeEmailSender",
    ) -> None:
        """A repeat registration conflicts and sends no second message."""
        first = await async_client.post(REGISTER_URL, json=registration_payload())
        assert first.status_code == 201

        response = await async_client.post(REGISTER_URL, json=registration_payload())

        assert response.status_code == 409
        assert await user_count(db_session, VALID_EMAIL) == 1
        assert fake_email_sender.count_for(VALID_EMAIL) == 1

    async def test_duplicate_differing_only_in_case_returns_409(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Uniqueness is enforced on the normalised address, not the raw one."""
        await async_client.post(
            REGISTER_URL, json=registration_payload(email="user@example.com")
        )

        response = await async_client.post(
            REGISTER_URL, json=registration_payload(email="USER@Example.com")
        )

        assert response.status_code == 409
        assert await user_count(db_session, "user@example.com") == 1

    @pytest.mark.parametrize(
        "password",
        [
            pytest.param("Sh0rt!a", id="too-short"),
            pytest.param("nouppercase1!", id="no-uppercase"),
            pytest.param("NOLOWERCASE1!", id="no-lowercase"),
            pytest.param("NoDigitsHere!", id="no-digit"),
            pytest.param("NoSpecial1Char", id="no-special-character"),
            pytest.param("Aa1!" + "x" * 80, id="over-72-bytes"),
        ],
    )
    async def test_weak_password_returns_422(
        self, async_client: AsyncClient, db_session: AsyncSession, password: str
    ) -> None:
        """Every strength rule, including the bcrypt byte cap, rejects with 422."""
        response = await async_client.post(
            REGISTER_URL, json=registration_payload(password=password)
        )

        assert response.status_code == 422
        assert await user_count(db_session, VALID_EMAIL) == 0

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                {"email": "not-an-email", "password": VALID_PASSWORD},
                id="malformed-email",
            ),
            pytest.param(
                {"email": VALID_EMAIL, "password": VALID_PASSWORD, "role": "admin"},
                id="unexpected-extra-field",
            ),
            pytest.param({"email": VALID_EMAIL}, id="missing-password"),
        ],
    )
    async def test_malformed_body_returns_422(
        self, async_client: AsyncClient, body: dict[str, str]
    ) -> None:
        """Shape violations are rejected before any domain rule runs."""
        response = await async_client.post(REGISTER_URL, json=body)

        assert response.status_code == 422
