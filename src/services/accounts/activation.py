"""Account activation and activation resend.

Both entry points are written so that an observer cannot learn whether an
address has an account. ``resend_activation`` in particular returns the same
thing and performs no side effect for an unknown address and for one that is
already active; the router turns that into a single fixed response body.
"""

from datetime import timedelta

from src.core.exceptions import AuthenticationError, InvalidRequestError
from src.integrations.email.interface import EmailSenderInterface
from src.models.accounts import ActivationToken, User
from src.repositories.accounts import UserRepository
from src.security.validators import normalize_email
from src.services.accounts.links import build_activation_link
from src.services.accounts.tokens import TokenLifecycleService

__all__ = ["ActivationService"]


class ActivationService:
    """Completes the activation handshake started by registration."""

    def __init__(
        self,
        users: UserRepository,
        tokens: TokenLifecycleService[ActivationToken],
        email_sender: EmailSenderInterface,
        activation_ttl: timedelta,
        activation_url: str,
        login_url: str,
    ) -> None:
        """Take every collaborator by injection; build none of them here."""
        self._users = users
        self._tokens = tokens
        self._email_sender = email_sender
        self._activation_ttl = activation_ttl
        self._activation_url = activation_url
        self._login_url = login_url

    async def activate_account(self, email: str, token: str) -> None:
        """Consume the token and mark the account active.

        Every failure that is not an expiry becomes ``InvalidRequestError``: an
        unknown address, a token issued to somebody else and a token that was
        already spent are deliberately indistinguishable, so the endpoint cannot
        be used to enumerate accounts. Expiry keeps its own error, because that
        user needs to be told to ask for a new link.
        """
        user = await self._pending_account(email)
        try:
            await self._tokens.consume(token, user.id)
        except AuthenticationError as error:
            raise InvalidRequestError("Activation token is invalid.") from error

        await self._users.update(user, is_active=True)
        await self._email_sender.send_activation_complete_email(
            user.email, self._login_url
        )

    async def resend_activation(self, email: str) -> None:
        """Issue a fresh token and e-mail it, when that is warranted.

        Silently does nothing when the address is unknown or its account is
        already active. The caller returns one fixed response either way, so the
        two cases are byte-identical to a client.
        """
        user = await self._users.get_by_email(normalize_email(email))
        if user is None or user.is_active:
            return

        token = await self._tokens.issue(user.id, self._activation_ttl)
        await self._email_sender.send_activation_email(
            user.email,
            build_activation_link(self._activation_url, user.email, token.token),
        )

    async def _pending_account(self, email: str) -> User:
        """Return the not-yet-active account this activation could apply to."""
        user = await self._users.get_by_email(normalize_email(email))
        if user is None:
            raise InvalidRequestError("Activation token is invalid.")
        if user.is_active:
            raise InvalidRequestError("Account is already active.")
        return user
