"""JSON Web Token minting and verification.

The project's only PyJWT boundary. Every ``PyJWTError`` is translated here into a
domain exception, so no caller ever has to know which library signs the tokens —
a CI gate asserts that ``jwt.`` appears in no other module under ``src/``.

Two secrets rather than one, plus an explicit type claim on every token. Either
mechanism alone would stop a refresh token from being spent as an access token;
both are present because they fail differently. The secrets make cross-use a
signature error even if the claim were forgotten, and the claim makes it a
rejection even if the two secrets were ever configured to the same value.

Refresh tokens are additionally *stored* through :func:`refresh_token_digest`
rather than verbatim. ``TokenMixin.token`` is ``String(255)`` while a signed JWT
carrying claims runs 200-400 characters, so persisting the token itself would
pass on the short payloads a test produces and overflow in production. The
digest is a fixed 64 characters, and a database leak yields nothing a client
could present.
"""

import hashlib
import secrets
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt

from src.core.exceptions import AuthenticationError, TokenExpiredError

__all__ = [
    "ACCESS_TOKEN_TYPE",
    "REFRESH_TOKEN_TYPE",
    "TOKEN_TYPE_CLAIM",
    "JWTAuthManager",
    "JWTAuthManagerInterface",
    "refresh_token_digest",
]

TOKEN_TYPE_CLAIM: Final[str] = "token_type"
"""Claim naming which of the two families a token belongs to."""

ACCESS_TOKEN_TYPE: Final[str] = "access"
REFRESH_TOKEN_TYPE: Final[str] = "refresh"

_JTI_ENTROPY_BYTES: Final[int] = 16
"""Bytes of randomness in the per-token identity claim; see ``_encode``."""

_INVALID_TOKEN_MESSAGE: Final[str] = "Token is invalid."
_EXPIRED_TOKEN_MESSAGE: Final[str] = "Token has expired."


def refresh_token_digest(token: str) -> str:
    """Return the SHA-256 hex digest under which a refresh token is persisted.

    Deterministic and unsalted on purpose: the server has to find the row from
    the token the client presents, which rules out a per-row salt. That is safe
    here because the input is 32 bytes of signed, high-entropy JWT rather than a
    guessable secret, so a precomputed table is not a threat.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class JWTAuthManagerInterface(ABC):
    """The contract the API layer depends on for token work.

    Declared as an interface so that a test can substitute a manager with short
    or negative lifetimes without patching module internals.
    """

    @abstractmethod
    def create_access_token(self, data: dict[str, Any]) -> str:
        """Return a signed short-lived access token carrying ``data``."""

    @abstractmethod
    def create_refresh_token(self, data: dict[str, Any]) -> str:
        """Return a signed long-lived refresh token carrying ``data``."""

    @abstractmethod
    def decode_access_token(self, token: str) -> dict[str, Any]:
        """Return the claims of a valid access token.

        Raises ``TokenExpiredError`` when the lifetime has elapsed and
        ``AuthenticationError`` for every other defect, including a token of the
        wrong family.
        """

    @abstractmethod
    def decode_refresh_token(self, token: str) -> dict[str, Any]:
        """Return the claims of a valid refresh token.

        Raises the same two exceptions as :meth:`decode_access_token`.
        """


class JWTAuthManager(JWTAuthManagerInterface):
    """Signs and verifies the two token families with separate secrets."""

    def __init__(
        self,
        *,
        secret_key_access: str,
        secret_key_refresh: str,
        algorithm: str,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
    ) -> None:
        """Take both secrets, the algorithm and both lifetimes by injection."""
        self._secret_key_access = secret_key_access
        self._secret_key_refresh = secret_key_refresh
        self._algorithm = algorithm
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl

    @property
    def access_ttl(self) -> timedelta:
        """How long a freshly minted access token stays valid."""
        return self._access_ttl

    @property
    def refresh_ttl(self) -> timedelta:
        """How long a freshly minted refresh token stays valid."""
        return self._refresh_ttl

    def create_access_token(self, data: dict[str, Any]) -> str:
        """Return a signed short-lived access token carrying ``data``."""
        return self._encode(
            data, self._secret_key_access, ACCESS_TOKEN_TYPE, self._access_ttl
        )

    def create_refresh_token(self, data: dict[str, Any]) -> str:
        """Return a signed long-lived refresh token carrying ``data``."""
        return self._encode(
            data, self._secret_key_refresh, REFRESH_TOKEN_TYPE, self._refresh_ttl
        )

    def decode_access_token(self, token: str) -> dict[str, Any]:
        """Return the claims of a valid access token."""
        return self._decode(token, self._secret_key_access, ACCESS_TOKEN_TYPE)

    def decode_refresh_token(self, token: str) -> dict[str, Any]:
        """Return the claims of a valid refresh token."""
        return self._decode(token, self._secret_key_refresh, REFRESH_TOKEN_TYPE)

    def _encode(
        self,
        data: dict[str, Any],
        secret: str,
        token_type: str,
        ttl: timedelta,
    ) -> str:
        """Sign a copy of ``data`` stamped with its identity, type and lifetime.

        A copy rather than the argument: the caller's dictionary is often a
        literal reused across two calls, and mutating it would leak the first
        token's type claim into the second.

        ``jti`` is what makes two tokens minted for the same user distinct. PyJWT
        serialises ``iat`` and ``exp`` as whole seconds, so without a random
        identity two logins inside the same second would produce byte-identical
        tokens — and since the refresh row is keyed by the token's digest, the
        second login would collide with the first on a unique index instead of
        opening a second session.
        """
        issued_at = datetime.now(UTC)
        payload: dict[str, Any] = dict(data)
        payload[TOKEN_TYPE_CLAIM] = token_type
        payload["jti"] = secrets.token_urlsafe(_JTI_ENTROPY_BYTES)
        payload["iat"] = issued_at
        payload["exp"] = issued_at + ttl
        return jwt.encode(payload, secret, algorithm=self._algorithm)

    def _decode(self, token: str, secret: str, expected_type: str) -> dict[str, Any]:
        """Verify signature, expiry and family, and return the claims.

        The expiry check is PyJWT's, which is why an elapsed token is reported as
        ``TokenExpiredError`` before the family is even looked at: the holder of
        a stale token needs to be told to renew, not that the token was rejected.
        """
        try:
            payload: dict[str, Any] = jwt.decode(
                token, secret, algorithms=[self._algorithm]
            )
        except jwt.ExpiredSignatureError as error:
            raise TokenExpiredError(_EXPIRED_TOKEN_MESSAGE) from error
        except jwt.PyJWTError as error:
            raise AuthenticationError(_INVALID_TOKEN_MESSAGE) from error

        if payload.get(TOKEN_TYPE_CLAIM) != expected_type:
            raise AuthenticationError(_INVALID_TOKEN_MESSAGE)
        return payload
