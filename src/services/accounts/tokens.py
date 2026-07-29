"""The project's single token lifecycle implementation.

Activation (phase 2), refresh (phase 3) and password reset (phase 4) tokens all
run through this one service, parametrised by the model class. Forking this
logic into a per-token copy blocks a merge — the three models already share
``TokenMixin`` precisely so that this could stay generic.

The service raises ``AuthenticationError`` for a token that does not exist or
belongs to somebody else, and ``TokenExpiredError`` for one whose moment has
passed. A caller that serves a *form* rather than a *credential* — activation is
one — translates the former into ``InvalidRequestError``, because a mistyped
activation link is a bad request, not a failed authentication.
"""

import secrets
from datetime import UTC, datetime, timedelta

from src.core.exceptions import AuthenticationError, TokenExpiredError
from src.models.accounts import ActivationToken, PasswordResetToken, RefreshToken
from src.repositories.tokens import TokenRepository

__all__ = ["TOKEN_ENTROPY_BYTES", "TokenLifecycleService"]

TOKEN_ENTROPY_BYTES = 32
"""Bytes of entropy per token; ``token_urlsafe`` renders them as ~43 characters."""


class TokenLifecycleService[
    TokenT: (ActivationToken, PasswordResetToken, RefreshToken)
]:
    """Issue, verify, consume and purge one family of lifecycle tokens."""

    def __init__(self, repository: TokenRepository[TokenT]) -> None:
        """Take the repository by injection.

        The repository rather than the session: ``AsyncSession`` belongs to the
        persistence layer, and a service that accepted one would be able to open
        its own transaction behind the caller's back.
        """
        self._repository: TokenRepository[TokenT] = repository

    async def issue(self, user_id: int, ttl: timedelta) -> TokenT:
        """Replace whatever token this user holds with a freshly minted one.

        Dropping the old rows first is what makes a resend idempotent: the user
        ends up holding exactly one live token however often they ask.
        """
        await self._repository.delete_for_user(user_id)
        return await self._repository.create(
            user_id=user_id,
            token=secrets.token_urlsafe(TOKEN_ENTROPY_BYTES),
            expires_at=datetime.now(UTC) + ttl,
        )

    async def verify(self, token_value: str, user_id: int) -> TokenT:
        """Return the token if it exists, belongs to this user and is still live.

        Ownership is checked before expiry, so presenting somebody else's token
        never reveals whether that token happened to be valid.
        """
        token = await self._repository.get_by(token=token_value)
        if token is None or token.user_id != user_id:
            raise AuthenticationError("Token is unknown or does not match the account.")
        if token.is_expired():
            raise TokenExpiredError("Token has expired.")
        return token

    async def consume(self, token_value: str, user_id: int) -> TokenT:
        """Verify a token and delete it, so it cannot be presented twice."""
        token = await self.verify(token_value, user_id)
        await self._repository.delete(token)
        return token

    async def revoke_for(self, user_id: int) -> int:
        """Delete every token this user holds; returns how many were removed."""
        return await self._repository.delete_for_user(user_id)

    async def purge_expired(self, now: datetime | None = None) -> int:
        """Delete every token already past its expiry; returns how many went.

        Runs as one statement, is safe on an empty table and never touches a
        live row — which is what lets the hourly beat job run unattended.
        """
        moment = now if now is not None else datetime.now(UTC)
        return await self._repository.delete_expired(moment)
