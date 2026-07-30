"""Infrastructure, authentication and authorisation dependencies.

Everything a route needs in order to know *who is calling* and *what it may
build from*: the session, the settings, the outbound e-mail seam, the token
manager, the current account and the two guards that gate a route on a group or
a permission.

Assembling the use-case services from those pieces lives one module over, in
``src/api/providers.py``. The two were one file until this file passed the
project's 300-line ceiling; the seam between them is that nothing here knows a
service exists.

Interfaces rather than implementations are declared as return types wherever a
test needs a seam: overriding one dependency is what keeps SMTP and the real
clock out of the suite.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Annotated, Any, Final

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.core.exceptions import (
    AuthenticationError,
    PermissionDeniedError,
    TokenExpiredError,
)
from src.db.enums import UserGroupEnum
from src.db.session import get_session
from src.integrations.email.interface import EmailSenderInterface
from src.integrations.email.smtp_sender import SMTPEmailSender
from src.models.accounts import User
from src.repositories.accounts import UserRepository
from src.security.jwt_manager import JWTAuthManager, JWTAuthManagerInterface
from src.security.permissions import Permission, belongs_to_any, has_permission
from src.services.accounts.authentication import INACTIVE_ACCOUNT_MESSAGE

__all__ = [
    "ADMIN_ONLY",
    "CurrentUserDep",
    "EmailSenderDep",
    "JWTAuthManagerDep",
    "SessionDep",
    "SettingsDep",
    "get_current_user",
    "get_email_sender",
    "get_jwt_manager",
    "require_group",
    "require_permission",
]

MISSING_CREDENTIALS_MESSAGE: Final[str] = (
    "Authentication credentials were not provided."
)
INVALID_ACCESS_TOKEN_MESSAGE: Final[str] = "Access token is invalid or has expired."
INSUFFICIENT_GROUP_MESSAGE: Final[str] = (
    "This operation is not available to your account group."
)
MISSING_PERMISSION_MESSAGE: Final[str] = (
    "Your account group does not hold the permission this operation requires."
)

_USER_ID_CLAIM: Final[str] = "user_id"

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

bearer_scheme = HTTPBearer(
    scheme_name="BearerAccessToken",
    description="Paste the access token returned by /accounts/login/.",
    auto_error=False,
)
"""Swagger's Authorize button and the header parser behind ``get_current_user``.

``auto_error=False`` is not optional: with the default, the class raises the
framework's own web exception, which this project forbids everywhere — error
translation happens once, in the handler registered in ``src/main.py``. Switched
off, a missing or malformed header arrives as ``None`` and is turned into a
domain error below.
"""


def get_email_sender(settings: SettingsDep) -> EmailSenderInterface:
    """Build the production e-mail sender.

    Declared as returning the interface on purpose: overriding this dependency
    is the single seam a test needs to keep SMTP out of the run.
    """
    return SMTPEmailSender(
        host=settings.email_host,
        port=settings.email_port,
        username=settings.email_user,
        password=settings.email_password,
        sender=settings.email_from,
        use_tls=settings.email_use_tls,
    )


EmailSenderDep = Annotated[EmailSenderInterface, Depends(get_email_sender)]


def get_jwt_manager(settings: SettingsDep) -> JWTAuthManagerInterface:
    """Build the token manager from the configured secrets and lifetimes.

    Declared as returning the interface for the same reason as the e-mail sender:
    a test that needs a token which is already expired overrides this dependency
    with a manager built on a negative lifetime instead of patching internals.
    """
    return JWTAuthManager(
        secret_key_access=settings.secret_key_access,
        secret_key_refresh=settings.secret_key_refresh,
        algorithm=settings.jwt_algorithm,
        access_ttl=timedelta(minutes=settings.access_token_ttl_minutes),
        refresh_ttl=timedelta(days=settings.refresh_token_ttl_days),
    )


JWTAuthManagerDep = Annotated[JWTAuthManagerInterface, Depends(get_jwt_manager)]
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


async def get_current_user(
    credentials: CredentialsDep,
    session: SessionDep,
    jwt_manager: JWTAuthManagerDep,
) -> User:
    """Resolve the account behind a bearer access token.

    The one authentication dependency in the project: every protected route in
    every later phase asks for this object rather than parsing a header itself.

    Only *access* tokens are accepted. A refresh token presented here fails on
    both its signature and its type claim, which is what stops the long-lived
    credential from being usable as the short-lived one. An elapsed access token
    is reported as 401 rather than the 400 that ``TokenExpiredError`` would map
    to, because the caller's remedy is to refresh, not to fix the request.

    The account is loaded with its group and re-read from the database on every
    call, so an access token can never carry an authority its holder has since
    lost: a group change applies to the target's next request rather than their
    next login. The two guards below rely on that.
    """
    if credentials is None:
        raise AuthenticationError(MISSING_CREDENTIALS_MESSAGE)
    payload = _decode_access_token(jwt_manager, credentials.credentials)
    user_id = payload.get(_USER_ID_CLAIM)
    if not isinstance(user_id, int):
        raise AuthenticationError(INVALID_ACCESS_TOKEN_MESSAGE)

    user = await UserRepository(session).get_with_group(user_id)
    if user is None:
        raise AuthenticationError(INVALID_ACCESS_TOKEN_MESSAGE)
    if not user.is_active:
        raise PermissionDeniedError(INACTIVE_ACCOUNT_MESSAGE)
    return user


def _decode_access_token(
    jwt_manager: JWTAuthManagerInterface, token: str
) -> dict[str, Any]:
    """Decode an access token, collapsing an expiry onto the 401 path."""
    try:
        return jwt_manager.decode_access_token(token)
    except TokenExpiredError as error:
        raise AuthenticationError(INVALID_ACCESS_TOKEN_MESSAGE) from error


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_group(*groups: UserGroupEnum) -> Callable[[User], User]:
    """Build a dependency that admits only callers in one of these groups.

    Composes with ``get_current_user`` rather than re-reading the header: there
    is one authentication dependency in the project and this is a check on top of
    it. The guard hands the account back, so a route can be gated and use the
    caller through the same parameter.

    Membership is exact. ``require_group(MODERATOR)`` does not admit an
    administrator; a route whose audience should widen with rank asks for a
    permission instead.
    """
    allowed = frozenset(groups)

    def guard(current_user: CurrentUserDep) -> User:
        """Admit the caller or refuse the operation with 403."""
        if not belongs_to_any(current_user.group.name, allowed):
            raise PermissionDeniedError(INSUFFICIENT_GROUP_MESSAGE)
        return current_user

    return guard


def require_permission(permission: Permission) -> Callable[[User], User]:
    """Build a dependency that admits any caller holding this permission.

    Preferred over naming groups once more than one group may perform an
    operation: the matrix in ``src/security/permissions.py`` is hierarchical, so
    a right granted to moderators is granted to administrators without the route
    having to say so.
    """

    def guard(current_user: CurrentUserDep) -> User:
        """Admit the caller or refuse the operation with 403."""
        if not has_permission(current_user.group.name, permission):
            raise PermissionDeniedError(MISSING_PERMISSION_MESSAGE)
        return current_user

    return guard


ADMIN_ONLY = Depends(require_group(UserGroupEnum.ADMIN))
"""The guard every administrative route is mounted behind.

Built here rather than in the router so that the enum member stays inside the
wiring layer: outside this module and the permission matrix, nothing in ``src``
names a role.
"""
