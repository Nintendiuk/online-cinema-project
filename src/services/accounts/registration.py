"""Account registration.

One use case, one transaction. Nothing here commits: if the e-mail transport
fails, the ``ExternalServiceError`` travels up through the session dependency,
which rolls back, and no half-registered account survives. That is the whole
reason the send happens inside the request rather than after it.
"""

from datetime import timedelta

from src.core.exceptions import ConflictError, NotFoundError
from src.db.enums import UserGroupEnum
from src.integrations.email.interface import EmailSenderInterface
from src.models.accounts import ActivationToken, User, UserGroup
from src.repositories.accounts import UserRepository
from src.repositories.base import BaseRepository
from src.security.passwords import hash_password
from src.security.validators import normalize_email, validate_password_strength
from src.services.accounts.links import build_activation_link
from src.services.accounts.tokens import TokenLifecycleService

__all__ = ["RegistrationService"]


class RegistrationService:
    """Creates accounts and starts the activation handshake."""

    def __init__(
        self,
        users: UserRepository,
        groups: BaseRepository[UserGroup],
        tokens: TokenLifecycleService[ActivationToken],
        email_sender: EmailSenderInterface,
        activation_ttl: timedelta,
        activation_url: str,
    ) -> None:
        """Take every collaborator by injection; build none of them here."""
        self._users = users
        self._groups = groups
        self._tokens = tokens
        self._email_sender = email_sender
        self._activation_ttl = activation_ttl
        self._activation_url = activation_url

    async def register_user(self, email: str, password: str) -> User:
        """Create a deactivated account and e-mail its activation link.

        The password is checked for strength *before* it is hashed: ``bcrypt``
        silently ignores anything past 72 bytes, so hashing first would accept a
        password the user could never reproduce.
        """
        address = normalize_email(email)
        if await self._users.email_exists(address):
            raise ConflictError("An account with this e-mail already exists.")

        validate_password_strength(password)
        user = await self._users.create(
            email=address,
            hashed_password=hash_password(password),
            is_active=False,
            group_id=(await self._default_group()).id,
        )

        token = await self._tokens.issue(user.id, self._activation_ttl)
        await self._email_sender.send_activation_email(
            user.email,
            build_activation_link(self._activation_url, user.email, token.token),
        )
        return user

    async def _default_group(self) -> UserGroup:
        """Return the USER group every new account joins."""
        group = await self._groups.get_by(name=UserGroupEnum.USER)
        if group is None:
            raise NotFoundError(
                "The default user group is missing; run the group seeding."
            )
        return group
