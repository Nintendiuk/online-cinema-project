"""Dependency wiring for the API layer.

Every construction decision lives here. Routers ask for a finished service and
know nothing about repositories, senders or settings; services are handed the
``EmailSenderInterface`` rather than the SMTP class, which is what lets a test
swap in the double from ``tests/doubles``.
"""

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
from src.db.session import get_session
from src.integrations.email.interface import EmailSenderInterface
from src.integrations.email.smtp_sender import SMTPEmailSender
from src.models.accounts import ActivationToken, RefreshToken, User, UserGroup
from src.repositories.accounts import UserRepository
from src.repositories.base import BaseRepository
from src.repositories.tokens import TokenRepository
from src.security.jwt_manager import JWTAuthManager, JWTAuthManagerInterface
from src.services.accounts.activation import ActivationService
from src.services.accounts.authentication import (
    INACTIVE_ACCOUNT_MESSAGE,
    AuthenticationService,
)
from src.services.accounts.registration import RegistrationService
from src.services.accounts.tokens import TokenLifecycleService

__all__ = [
    "ActivationServiceDep",
    "AuthenticationServiceDep",
    "CurrentUserDep",
    "JWTAuthManagerDep",
    "RegistrationServiceDep",
    "get_activation_service",
    "get_authentication_service",
    "get_current_user",
    "get_email_sender",
    "get_jwt_manager",
    "get_registration_service",
]

MISSING_CREDENTIALS_MESSAGE: Final[str] = (
    "Authentication credentials were not provided."
)
INVALID_ACCESS_TOKEN_MESSAGE: Final[str] = "Access token is invalid or has expired."

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


def get_registration_service(
    session: SessionDep,
    settings: SettingsDep,
    email_sender: EmailSenderDep,
) -> RegistrationService:
    """Assemble the registration use case for one request."""
    return RegistrationService(
        users=UserRepository(session),
        groups=BaseRepository(session, UserGroup),
        tokens=TokenLifecycleService(TokenRepository(session, ActivationToken)),
        email_sender=email_sender,
        activation_ttl=timedelta(hours=settings.activation_token_ttl_hours),
        activation_url=settings.activation_url,
    )


def get_activation_service(
    session: SessionDep,
    settings: SettingsDep,
    email_sender: EmailSenderDep,
) -> ActivationService:
    """Assemble the activation use case for one request."""
    return ActivationService(
        users=UserRepository(session),
        tokens=TokenLifecycleService(TokenRepository(session, ActivationToken)),
        email_sender=email_sender,
        activation_ttl=timedelta(hours=settings.activation_token_ttl_hours),
        activation_url=settings.activation_url,
        login_url=settings.login_url,
    )


RegistrationServiceDep = Annotated[
    RegistrationService, Depends(get_registration_service)
]
ActivationServiceDep = Annotated[ActivationService, Depends(get_activation_service)]


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


def get_authentication_service(
    session: SessionDep,
    settings: SettingsDep,
    jwt_manager: JWTAuthManagerDep,
) -> AuthenticationService:
    """Assemble the authentication use case for one request.

    The refresh tokens go through the same ``TokenLifecycleService`` as
    activation, parametrised with ``RefreshToken``. There is exactly one token
    lifecycle implementation in the project and this is it.
    """
    return AuthenticationService(
        users=UserRepository(session),
        refresh_tokens=TokenLifecycleService(TokenRepository(session, RefreshToken)),
        jwt_manager=jwt_manager,
        refresh_ttl=timedelta(days=settings.refresh_token_ttl_days),
    )


AuthenticationServiceDep = Annotated[
    AuthenticationService, Depends(get_authentication_service)
]


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
    """
    if credentials is None:
        raise AuthenticationError(MISSING_CREDENTIALS_MESSAGE)
    payload = _decode_access_token(jwt_manager, credentials.credentials)
    user_id = payload.get(_USER_ID_CLAIM)
    if not isinstance(user_id, int):
        raise AuthenticationError(INVALID_ACCESS_TOKEN_MESSAGE)

    user = await UserRepository(session).get_by_id(user_id)
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
