"""Administrative account operations: group changes and manual activation.

Neither operation ends the account's sessions, and that is a decision rather than
an omission. An access token carries an account id and nothing else, and the
authentication dependency reloads the account — group included — on every single
request, so a moved role takes effect on the target's next call rather than their
next login. There is no stale authority to revoke.

Manual activation exists for the support case where the e-mail never arrived. It
is the same state change the activation link performs, minus the token, so it
also clears the pending token: leaving a live one behind would let a link that
was sent weeks ago still be presented against an account that no longer needs it.
"""

from typing import Final

from src.core.exceptions import InvalidRequestError, NotFoundError
from src.db.enums import UserGroupEnum
from src.models.accounts import ActivationToken, User, UserGroup
from src.repositories.accounts import UserRepository
from src.repositories.base import BaseRepository
from src.services.accounts.tokens import TokenLifecycleService

__all__ = [
    "ACCOUNT_ALREADY_ACTIVE_MESSAGE",
    "MISSING_GROUP_MESSAGE",
    "UNKNOWN_ACCOUNT_MESSAGE",
    "AdminService",
]

UNKNOWN_ACCOUNT_MESSAGE: Final[str] = "No account with this id exists."
ACCOUNT_ALREADY_ACTIVE_MESSAGE: Final[str] = "Account is already active."
MISSING_GROUP_MESSAGE: Final[str] = (
    "The requested group is missing; run the group seeding."
)


class AdminService:
    """Changes another account's group or activates it without a token."""

    def __init__(
        self,
        users: UserRepository,
        groups: BaseRepository[UserGroup],
        activation_tokens: TokenLifecycleService[ActivationToken],
    ) -> None:
        """Take every collaborator by injection; build none of them here."""
        self._users = users
        self._groups = groups
        self._activation_tokens = activation_tokens

    async def change_group(self, user_id: int, group: UserGroupEnum) -> User:
        """Move an account into the named group and return it.

        Moving an account into the group it already holds is a no-op rather than
        an error: the caller asked for a state and the state is already true, so
        there is nothing to report. The comparison is on the group's primary key,
        not its name — this service does not reason about what a role means.

        A group with no row is 404 and not 500, but it is an operator problem
        rather than a client one: the enum was accepted by the schema, so the
        table has not been seeded.
        """
        user = await self._account(user_id)
        target = await self._groups.get_by(name=group)
        if target is None:
            raise NotFoundError(MISSING_GROUP_MESSAGE)
        if user.group_id == target.id:
            return user

        await self._users.update(user, group_id=target.id)
        return await self._account(user_id)

    async def activate_manually(self, user_id: int) -> User:
        """Activate an account by hand and drop its pending activation token.

        An account that is already active raises: the request is well formed and
        the state forbids it, which is the same 400 the activation endpoint gives.
        """
        user = await self._account(user_id)
        if user.is_active:
            raise InvalidRequestError(ACCOUNT_ALREADY_ACTIVE_MESSAGE)

        await self._activation_tokens.revoke_for(user.id)
        return await self._users.update(user, is_active=True)

    async def _account(self, user_id: int) -> User:
        """Load an account with its group, or report that it does not exist.

        Reloading through this method after a write is what keeps the returned
        object's group relationship in step with the column that was just
        updated; the response is rendered from it.
        """
        user = await self._users.get_with_group(user_id)
        if user is None:
            raise NotFoundError(UNKNOWN_ACCOUNT_MESSAGE)
        return user
