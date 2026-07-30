"""Login, refresh and logout.

Three rules shape everything here.

*Nothing distinguishes an unknown address from a wrong password.* Both raise the
same ``AuthenticationError`` with the same message, so the login endpoint cannot
be walked to discover which addresses hold accounts.

*A stale credential is a failed authentication, not a bad request.* The token
lifecycle reports an elapsed token as ``TokenExpiredError``, which the global
handler maps to 400 — correct for a mistyped activation link, wrong for a
session that simply ran out. Every expiry on this path is therefore translated
into ``AuthenticationError`` so the client sees 401 and knows to log in again.

*An inactive account is a permission problem.* Someone who typed the right
password is not failing authentication; they are failing authorisation until
they activate, which is 403 and a message that says so.
"""

from datetime import timedelta
from typing import Any, Final

from src.core.exceptions import (
    AuthenticationError,
    PermissionDeniedError,
    TokenExpiredError,
)
from src.models.accounts import RefreshToken, User
from src.repositories.accounts import UserRepository
from src.security.jwt_manager import JWTAuthManagerInterface, refresh_token_digest
from src.security.passwords import verify_password
from src.security.validators import normalize_email
from src.services.accounts.tokens import TokenLifecycleService

__all__ = [
    "INACTIVE_ACCOUNT_MESSAGE",
    "INVALID_CREDENTIALS_MESSAGE",
    "INVALID_SESSION_MESSAGE",
    "AuthenticationService",
]

INVALID_CREDENTIALS_MESSAGE: Final[str] = "E-mail or password is incorrect."
"""One message for both halves of a failed login; see the module docstring."""

INACTIVE_ACCOUNT_MESSAGE: Final[str] = (
    "Account is not activated. Follow the activation link sent by e-mail, or "
    "request a new one."
)
INVALID_SESSION_MESSAGE: Final[str] = "Refresh token is invalid or no longer active."

_USER_ID_CLAIM: Final[str] = "user_id"


class AuthenticationService:
    """Opens, renews and ends authenticated sessions."""

    def __init__(
        self,
        users: UserRepository,
        refresh_tokens: TokenLifecycleService[RefreshToken],
        jwt_manager: JWTAuthManagerInterface,
        refresh_ttl: timedelta,
    ) -> None:
        """Take every collaborator by injection; build none of them here."""
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._jwt_manager = jwt_manager
        self._refresh_ttl = refresh_ttl

    async def login(self, email: str, password: str) -> tuple[str, str]:
        """Verify credentials and return a fresh ``(access, refresh)`` pair.

        The password is checked before the activation state, so an attacker who
        guesses an address but not its password learns only that the credentials
        were wrong — the 403 that reveals an unactivated account is reachable
        only by someone who already knows the password.

        The refresh row is issued with ``replace_existing=False``: logging in on
        a second device must not end the session on the first.
        """
        address = normalize_email(email)
        user = await self._users.get_by_email(address)
        if user is None or not verify_password(password, user.hashed_password):
            raise AuthenticationError(INVALID_CREDENTIALS_MESSAGE)
        if not user.is_active:
            raise PermissionDeniedError(INACTIVE_ACCOUNT_MESSAGE)

        claims = {_USER_ID_CLAIM: user.id}
        access_token = self._jwt_manager.create_access_token(claims)
        refresh_token = self._jwt_manager.create_refresh_token(claims)
        await self._refresh_tokens.issue(
            user.id,
            self._refresh_ttl,
            value=refresh_token_digest(refresh_token),
            replace_existing=False,
        )
        return access_token, refresh_token

    async def refresh(self, refresh_token: str) -> str:
        """Return a new access token for a session that is still good.

        Four things have to hold, and they are checked in this order: the token
        verifies as a refresh token, its subject still exists and is active, and
        the row minted at login is still present and unexpired. Loading the user
        before the row lookup keeps a token naming a deleted account on the 401
        path rather than reaching a row that cannot exist.
        """
        payload = self._decode_refresh(refresh_token)
        user = await self._active_user(self._subject_of(payload))
        try:
            await self._refresh_tokens.verify(
                refresh_token_digest(refresh_token), user.id
            )
        except TokenExpiredError as error:
            raise AuthenticationError(INVALID_SESSION_MESSAGE) from error
        return self._jwt_manager.create_access_token({_USER_ID_CLAIM: user.id})

    async def logout(self, user_id: int, refresh_token: str) -> None:
        """End exactly one session: delete the row this token points at.

        ``consume`` checks ownership before it deletes, so presenting somebody
        else's refresh token raises and leaves the victim's row in place. Other
        sessions belonging to the caller are untouched.
        """
        try:
            await self._refresh_tokens.consume(
                refresh_token_digest(refresh_token), user_id
            )
        except TokenExpiredError as error:
            raise AuthenticationError(INVALID_SESSION_MESSAGE) from error

    def _decode_refresh(self, refresh_token: str) -> dict[str, Any]:
        """Decode a refresh token, reporting an elapsed one as a 401."""
        try:
            return self._jwt_manager.decode_refresh_token(refresh_token)
        except TokenExpiredError as error:
            raise AuthenticationError(INVALID_SESSION_MESSAGE) from error

    @staticmethod
    def _subject_of(payload: dict[str, Any]) -> int:
        """Return the user id a token names, rejecting a payload without one."""
        user_id = payload.get(_USER_ID_CLAIM)
        if not isinstance(user_id, int):
            raise AuthenticationError(INVALID_SESSION_MESSAGE)
        return user_id

    async def _active_user(self, user_id: int) -> User:
        """Load the account behind a token and insist it is still usable."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise AuthenticationError(INVALID_SESSION_MESSAGE)
        if not user.is_active:
            raise PermissionDeniedError(INACTIVE_ACCOUNT_MESSAGE)
        return user
