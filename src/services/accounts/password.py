"""Password change and the forgotten-password flow.

Three rules shape this module.

*Changing a password ends every session.* Both entry points that replace a hash
call ``revoke_for`` on the refresh-token lifecycle, so a stolen refresh token
dies with the credential it was minted from. This is the one caller in the
project that wants ``issue``'s default replacing behaviour rather than the login
path's ``replace_existing=False``.

*A stale reset link is a bad request, not a failed authentication.* The lifecycle
reports an elapsed token as ``TokenExpiredError``, which the global handler maps
to 400, and this module lets it travel. That is deliberate and it differs from
the session endpoints, which translate the same error to 401: a refresh token is
a credential, while a reset link is a well-formed submission the current state
forbids — exactly like a stale activation link, which already answers 400.

*Asking for a reset discloses nothing.* An unknown address, an address whose
account was never activated and a live account are answered identically; only
the last of the three sends mail.
"""

from datetime import timedelta
from typing import Final

from src.core.exceptions import AuthenticationError, InvalidRequestError
from src.integrations.email.interface import EmailSenderInterface
from src.models.accounts import PasswordResetToken, RefreshToken, User
from src.repositories.accounts import UserRepository
from src.security.passwords import hash_password, verify_password
from src.security.validators import normalize_email, validate_password_strength
from src.services.accounts.links import build_password_reset_link
from src.services.accounts.tokens import TokenLifecycleService

__all__ = [
    "INVALID_OLD_PASSWORD_MESSAGE",
    "INVALID_RESET_TOKEN_MESSAGE",
    "PASSWORD_UNCHANGED_MESSAGE",
    "PasswordService",
]

INVALID_OLD_PASSWORD_MESSAGE: Final[str] = "Current password is incorrect."
PASSWORD_UNCHANGED_MESSAGE: Final[str] = (
    "The new password must differ from the current one."
)
INVALID_RESET_TOKEN_MESSAGE: Final[str] = "Password reset token is invalid."
"""One message for an unknown token, a foreign one, a spent one and an unknown
address, so that none of the four can be told apart from the others."""


class PasswordService:
    """Replaces the credential of an account, by request or by reset link."""

    def __init__(
        self,
        users: UserRepository,
        reset_tokens: TokenLifecycleService[PasswordResetToken],
        refresh_tokens: TokenLifecycleService[RefreshToken],
        email_sender: EmailSenderInterface,
        reset_ttl: timedelta,
        reset_url: str,
    ) -> None:
        """Take every collaborator by injection; build none of them here."""
        self._users = users
        self._reset_tokens = reset_tokens
        self._refresh_tokens = refresh_tokens
        self._email_sender = email_sender
        self._reset_ttl = reset_ttl
        self._reset_url = reset_url

    async def change_password(
        self, user: User, old_password: str, new_password: str
    ) -> None:
        """Swap the credential of an authenticated account.

        The account is the one the bearer token resolved to, which is why this
        method takes a ``User`` and not an id: there is no identifier in the
        request for a caller to point at somebody else.

        A wrong current password is a failed authentication (401). A new password
        equal to the current one is a request the state forbids (400), and it is
        checked against the stored hash rather than against the submitted old
        value, so it holds even when the two arrive differently encoded.
        """
        if not verify_password(old_password, user.hashed_password):
            raise AuthenticationError(INVALID_OLD_PASSWORD_MESSAGE)
        if verify_password(new_password, user.hashed_password):
            raise InvalidRequestError(PASSWORD_UNCHANGED_MESSAGE)
        await self._replace_password(user, new_password)

    async def request_reset(self, email: str) -> None:
        """Issue a reset token and e-mail its link, when that is warranted.

        Silently does nothing for an unknown address or an unactivated account;
        the caller answers with one fixed body either way. The token is issued
        with the lifecycle's default replacing behaviour, so asking twice leaves
        the user holding exactly one live link and kills the earlier one.
        """
        user = await self._users.get_by_email(normalize_email(email))
        if user is None or not user.is_active:
            return

        token = await self._reset_tokens.issue(user.id, self._reset_ttl)
        await self._email_sender.send_password_reset_email(
            user.email,
            build_password_reset_link(self._reset_url, user.email, token.token),
        )

    async def complete_reset(self, email: str, token: str, new_password: str) -> None:
        """Consume the reset token and set the new credential.

        The token is spent before anything is written, so a failure leaves the
        account untouched. An expired token keeps its own error and reaches the
        client as 400 with a message that names expiry; every other rejection is
        flattened into one indistinguishable bad request.
        """
        user = await self._resettable_account(email)
        try:
            await self._reset_tokens.consume(token, user.id)
        except AuthenticationError as error:
            raise InvalidRequestError(INVALID_RESET_TOKEN_MESSAGE) from error

        await self._replace_password(user, new_password)

    async def _replace_password(self, user: User, new_password: str) -> None:
        """Store the new hash, end every session and notify the account holder.

        Strength is validated before hashing, because ``bcrypt`` ignores anything
        past 72 bytes and hashing first would accept a password the user could
        never reproduce.

        The notification goes out inside the request, like the activation mail:
        if the transport fails, the ``ExternalServiceError`` travels up through
        the session dependency, which rolls back, and the account keeps the
        credential its owner still believes in.
        """
        validate_password_strength(new_password)
        await self._users.update(user, hashed_password=hash_password(new_password))
        await self._refresh_tokens.revoke_for(user.id)
        await self._email_sender.send_password_changed_email(user.email)

    async def _resettable_account(self, email: str) -> User:
        """Return the active account a reset could apply to."""
        user = await self._users.get_by_email(normalize_email(email))
        if user is None or not user.is_active:
            raise InvalidRequestError(INVALID_RESET_TOKEN_MESSAGE)
        return user
