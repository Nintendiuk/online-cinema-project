"""Unit tests for the JWT boundary.

What is pinned here is mostly what the manager *refuses*. An access token and a
refresh token are both signed strings that look alike, and the entire value of
the separation is that one can never be spent as the other — by signature, by
type claim, or both. Time is injected as a negative lifetime rather than waited
for, so an expiry assertion costs nothing and cannot flake.
"""

from datetime import timedelta
from typing import Any

import pytest

from src.core.exceptions import AuthenticationError, TokenExpiredError
from src.security.jwt_manager import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    TOKEN_TYPE_CLAIM,
    JWTAuthManager,
    JWTAuthManagerInterface,
)

pytestmark = pytest.mark.unit

ACCESS_SECRET = "access-secret"
REFRESH_SECRET = "refresh-secret"
ALGORITHM = "HS256"
PAYLOAD: dict[str, Any] = {"user_id": 1}


def build_manager(
    *,
    access_ttl: timedelta = timedelta(minutes=15),
    refresh_ttl: timedelta = timedelta(days=7),
    secret_key_access: str = ACCESS_SECRET,
    secret_key_refresh: str = REFRESH_SECRET,
) -> JWTAuthManager:
    """Build a manager, overriding any part of its configuration."""
    return JWTAuthManager(
        secret_key_access=secret_key_access,
        secret_key_refresh=secret_key_refresh,
        algorithm=ALGORITHM,
        access_ttl=access_ttl,
        refresh_ttl=refresh_ttl,
    )


@pytest.fixture
def manager() -> JWTAuthManager:
    """The manager under test, configured with production-shaped lifetimes."""
    return build_manager()


def tamper(token: str) -> str:
    """Return the token with one character of its payload segment altered.

    The signature still covers the original payload, so the result is a
    well-formed JWT that cannot verify.
    """
    header, payload, signature = token.split(".")
    swapped = "B" if payload[5] != "B" else "C"
    mutated = payload[:5] + swapped + payload[6:]
    return f"{header}.{mutated}.{signature}"


class TestRoundTrip:
    """Claims survive encoding and come back with the right type stamped on."""

    def test_access_token_round_trip(self, manager: JWTAuthManager) -> None:
        """An access token decodes back to the payload it was minted from."""
        decoded = manager.decode_access_token(manager.create_access_token(PAYLOAD))

        assert decoded["user_id"] == 1

    def test_refresh_token_round_trip(self, manager: JWTAuthManager) -> None:
        """A refresh token decodes back to the payload it was minted from."""
        decoded = manager.decode_refresh_token(manager.create_refresh_token(PAYLOAD))

        assert decoded["user_id"] == 1

    def test_encoded_payload_carries_expiry_and_issued_at(
        self, manager: JWTAuthManager
    ) -> None:
        """Every token states when it was issued and when it stops being valid."""
        decoded = manager.decode_access_token(manager.create_access_token(PAYLOAD))

        assert "exp" in decoded
        assert "iat" in decoded
        assert decoded["exp"] > decoded["iat"]

    def test_token_types_differ_between_families(self, manager: JWTAuthManager) -> None:
        """The type claim distinguishes the two families."""
        access = manager.decode_access_token(manager.create_access_token(PAYLOAD))
        refresh = manager.decode_refresh_token(manager.create_refresh_token(PAYLOAD))

        assert access[TOKEN_TYPE_CLAIM] == ACCESS_TOKEN_TYPE
        assert refresh[TOKEN_TYPE_CLAIM] == REFRESH_TOKEN_TYPE
        assert access[TOKEN_TYPE_CLAIM] != refresh[TOKEN_TYPE_CLAIM]

    def test_minting_does_not_mutate_the_caller_payload(
        self, manager: JWTAuthManager
    ) -> None:
        """The dictionary handed in comes back unchanged.

        The service passes one literal to both create calls; if the manager
        stamped the type claim in place, the second token would inherit the
        first one's type.
        """
        claims: dict[str, Any] = {"user_id": 7}
        manager.create_access_token(claims)
        manager.create_refresh_token(claims)

        assert claims == {"user_id": 7}

    def test_two_tokens_for_one_user_are_distinct(
        self, manager: JWTAuthManager
    ) -> None:
        """Identical claims still yield different tokens.

        ``iat`` and ``exp`` are serialised as whole seconds, so without a random
        ``jti`` two logins inside the same second would mint the same string and
        the second refresh row would collide with the first on its unique index.
        """
        first = manager.create_refresh_token(PAYLOAD)
        second = manager.create_refresh_token(PAYLOAD)

        assert first != second
        assert manager.decode_refresh_token(first)["jti"] != (
            manager.decode_refresh_token(second)["jti"]
        )

    def test_access_ttl_is_shorter_than_refresh_ttl(
        self, manager: JWTAuthManager
    ) -> None:
        """The configured access lifetime is strictly the shorter of the two."""
        assert manager.access_ttl < manager.refresh_ttl

    def test_manager_implements_the_interface(self, manager: JWTAuthManager) -> None:
        """The concrete manager is substitutable for the declared interface."""
        assert isinstance(manager, JWTAuthManagerInterface)
        assert issubclass(JWTAuthManager, JWTAuthManagerInterface)


class TestCrossUseRejected:
    """Neither family decodes as the other, whatever the secrets are."""

    def test_refresh_token_is_not_an_access_token(
        self, manager: JWTAuthManager
    ) -> None:
        """A refresh token presented as an access token is refused."""
        refresh = manager.create_refresh_token(PAYLOAD)

        with pytest.raises(AuthenticationError):
            manager.decode_access_token(refresh)

    def test_access_token_is_not_a_refresh_token(self, manager: JWTAuthManager) -> None:
        """An access token presented as a refresh token is refused."""
        access = manager.create_access_token(PAYLOAD)

        with pytest.raises(AuthenticationError):
            manager.decode_refresh_token(access)

    def test_type_claim_alone_rejects_cross_use(self) -> None:
        """Cross-use fails on the claim even when both secrets are identical.

        With one shared secret the signature check passes, so this isolates the
        type claim as an independent barrier rather than a redundant one.
        """
        shared = build_manager(
            secret_key_access="one-secret", secret_key_refresh="one-secret"
        )
        refresh = shared.create_refresh_token(PAYLOAD)

        with pytest.raises(AuthenticationError):
            shared.decode_access_token(refresh)

    def test_cross_secret_is_rejected(self, manager: JWTAuthManager) -> None:
        """The signature alone rejects a token minted under a different secret.

        Same family on both sides, so the type claim matches and cannot be what
        fails: only the access secret differs. This is the mirror of
        ``test_type_claim_alone_rejects_cross_use``, which holds the secret
        constant and varies the family.
        """
        other = build_manager(secret_key_access="a-different-access-secret")
        access = manager.create_access_token(PAYLOAD)

        with pytest.raises(AuthenticationError):
            other.decode_access_token(access)

    def test_refresh_secret_does_not_verify_an_access_token(
        self, manager: JWTAuthManager
    ) -> None:
        """The two families genuinely use different keys.

        Decoded with the families swapped: the refresh secret is asked to verify
        a token signed with the access secret.
        """
        swapped = build_manager(
            secret_key_access=REFRESH_SECRET, secret_key_refresh=ACCESS_SECRET
        )
        access = manager.create_access_token(PAYLOAD)

        with pytest.raises(AuthenticationError):
            swapped.decode_access_token(access)


class TestMalformedTokens:
    """Nothing a client can send escapes as a library exception."""

    def test_tampered_payload_is_rejected(self, manager: JWTAuthManager) -> None:
        """Flipping one character of the payload invalidates the signature."""
        token = tamper(manager.create_access_token(PAYLOAD))

        with pytest.raises(AuthenticationError):
            manager.decode_access_token(token)

    def test_foreign_signature_is_rejected(self, manager: JWTAuthManager) -> None:
        """A token signed with an unrelated secret is refused."""
        foreign = build_manager(
            secret_key_access="somebody-elses-secret",
            secret_key_refresh="somebody-elses-secret",
        )
        token = foreign.create_access_token(PAYLOAD)

        with pytest.raises(AuthenticationError):
            manager.decode_access_token(token)

    @pytest.mark.parametrize(
        "garbage",
        ["not.a.token", "", "   ", "onesegment", "a.b", "a.b.c.d"],
        ids=[
            "shaped",
            "empty",
            "blank",
            "one-segment",
            "two-segments",
            "four-segments",
        ],
    )
    def test_garbage_raises_authentication_error(
        self, manager: JWTAuthManager, garbage: str
    ) -> None:
        """Every malformed input becomes a domain error, never a PyJWT error."""
        with pytest.raises(AuthenticationError):
            manager.decode_access_token(garbage)

    def test_garbage_is_rejected_by_the_refresh_path_too(
        self, manager: JWTAuthManager
    ) -> None:
        """The refresh decoder translates library errors the same way."""
        with pytest.raises(AuthenticationError):
            manager.decode_refresh_token("not.a.token")


class TestExpiry:
    """An elapsed token is reported as an expiry, not as a bad signature."""

    def test_expired_access_token_raises_token_expired(self) -> None:
        """The exact type matters: the caller's remedy is to refresh."""
        stale = build_manager(access_ttl=timedelta(minutes=-1))
        token = stale.create_access_token(PAYLOAD)

        with pytest.raises(TokenExpiredError):
            stale.decode_access_token(token)

    def test_expired_refresh_token_raises_token_expired(self) -> None:
        """The refresh family reports expiry the same way."""
        stale = build_manager(refresh_ttl=timedelta(days=-1))
        token = stale.create_refresh_token(PAYLOAD)

        with pytest.raises(TokenExpiredError):
            stale.decode_refresh_token(token)

    def test_expiry_is_not_reported_as_an_authentication_failure(self) -> None:
        """``TokenExpiredError`` is not a subclass of ``AuthenticationError``.

        Written as an explicit non-match because the two are mapped to different
        status codes and an accidental inheritance would silently merge them.
        """
        stale = build_manager(access_ttl=timedelta(minutes=-1))
        token = stale.create_access_token(PAYLOAD)

        with pytest.raises(TokenExpiredError) as caught:
            stale.decode_access_token(token)
        assert not isinstance(caught.value, AuthenticationError)
