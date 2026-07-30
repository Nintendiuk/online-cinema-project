"""Unit tests for the storage key derived from a refresh token.

``TokenMixin.token`` is ``String(255)`` and a signed JWT with claims runs 200-400
characters, so the refresh row stores a SHA-256 digest of the token instead of the
token itself. These tests pin the two properties that decision rests on: the
digest is short and fixed-width, and it is not reversible into a credential.
"""

from datetime import timedelta
from typing import Any

import pytest

from src.security.jwt_manager import JWTAuthManager, refresh_token_digest

pytestmark = pytest.mark.unit

ALGORITHM = "HS256"
PAYLOAD: dict[str, Any] = {"user_id": 1}


def build_manager() -> JWTAuthManager:
    """Build a manager with production-shaped lifetimes."""
    return JWTAuthManager(
        secret_key_access="access-secret",
        secret_key_refresh="refresh-secret",
        algorithm=ALGORITHM,
        access_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=7),
    )


class TestRefreshTokenDigest:
    """The storage key derived from a refresh token."""

    def test_digest_is_stable(self) -> None:
        """The same token always hashes to the same value; lookups depend on it."""
        token = build_manager().create_refresh_token(PAYLOAD)

        assert refresh_token_digest(token) == refresh_token_digest(token)

    def test_digest_is_sixty_four_hex_characters(self) -> None:
        """SHA-256 hex fits the 255-character token column with room to spare."""
        digest = refresh_token_digest(build_manager().create_refresh_token(PAYLOAD))

        assert len(digest) == 64
        assert all(char in "0123456789abcdef" for char in digest)

    def test_digest_does_not_contain_the_token(self) -> None:
        """A database leak yields nothing that can be replayed."""
        token = build_manager().create_refresh_token(PAYLOAD)

        assert token not in refresh_token_digest(token)

    def test_distinct_tokens_get_distinct_digests(self) -> None:
        """Two sessions cannot collide onto one row."""
        manager = build_manager()
        first = manager.create_refresh_token({"user_id": 1})
        second = manager.create_refresh_token({"user_id": 2})

        assert refresh_token_digest(first) != refresh_token_digest(second)
