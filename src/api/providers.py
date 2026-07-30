"""Assembly of the use-case services, one per request.

The counterpart to ``src/api/deps.py``: that module resolves who is calling and
hands out infrastructure, this one turns infrastructure into services. Routers
ask for a finished service and know nothing about repositories, senders or
settings; services are handed the ``EmailSenderInterface`` rather than the SMTP
class, which is what lets a test swap in the double from ``tests/doubles``.

Every service here is built fresh for the request that asked for it, over that
request's session, so nothing is shared between two calls and no service outlives
the transaction it belongs to.

There is one token-lifecycle implementation in the project. Activation, password
reset and refresh tokens are that one class parametrised by a different model;
none of them is forked.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import Depends

from src.api.deps import EmailSenderDep, JWTAuthManagerDep, SessionDep, SettingsDep
from src.models.accounts import (
    ActivationToken,
    PasswordResetToken,
    RefreshToken,
    UserGroup,
)
from src.repositories.accounts import UserRepository
from src.repositories.base import BaseRepository
from src.repositories.tokens import TokenRepository
from src.services.accounts.activation import ActivationService
from src.services.accounts.admin import AdminService
from src.services.accounts.authentication import AuthenticationService
from src.services.accounts.password import PasswordService
from src.services.accounts.registration import RegistrationService
from src.services.accounts.tokens import TokenLifecycleService

__all__ = [
    "ActivationServiceDep",
    "AdminServiceDep",
    "AuthenticationServiceDep",
    "PasswordServiceDep",
    "RegistrationServiceDep",
    "get_activation_service",
    "get_admin_service",
    "get_authentication_service",
    "get_password_service",
    "get_registration_service",
]


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


def get_authentication_service(
    session: SessionDep,
    settings: SettingsDep,
    jwt_manager: JWTAuthManagerDep,
) -> AuthenticationService:
    """Assemble the authentication use case for one request."""
    return AuthenticationService(
        users=UserRepository(session),
        refresh_tokens=TokenLifecycleService(TokenRepository(session, RefreshToken)),
        jwt_manager=jwt_manager,
        refresh_ttl=timedelta(days=settings.refresh_token_ttl_days),
    )


def get_password_service(
    session: SessionDep,
    settings: SettingsDep,
    email_sender: EmailSenderDep,
) -> PasswordService:
    """Assemble the password use cases for one request.

    Two lifecycles over two models: the reset tokens the flow consumes, and the
    refresh tokens it revokes. Replacing a credential ends every session opened
    with the old one, which is why this service holds both.
    """
    return PasswordService(
        users=UserRepository(session),
        reset_tokens=TokenLifecycleService(
            TokenRepository(session, PasswordResetToken)
        ),
        refresh_tokens=TokenLifecycleService(TokenRepository(session, RefreshToken)),
        email_sender=email_sender,
        reset_ttl=timedelta(minutes=settings.password_reset_ttl_minutes),
        reset_url=settings.password_reset_url,
    )


def get_admin_service(session: SessionDep) -> AdminService:
    """Assemble the administrative account operations for one request."""
    return AdminService(
        users=UserRepository(session),
        groups=BaseRepository(session, UserGroup),
        activation_tokens=TokenLifecycleService(
            TokenRepository(session, ActivationToken)
        ),
    )


RegistrationServiceDep = Annotated[
    RegistrationService, Depends(get_registration_service)
]
ActivationServiceDep = Annotated[ActivationService, Depends(get_activation_service)]
AuthenticationServiceDep = Annotated[
    AuthenticationService, Depends(get_authentication_service)
]
PasswordServiceDep = Annotated[PasswordService, Depends(get_password_service)]
AdminServiceDep = Annotated[AdminService, Depends(get_admin_service)]
