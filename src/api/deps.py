"""Dependency wiring for the API layer.

Every construction decision lives here. Routers ask for a finished service and
know nothing about repositories, senders or settings; services are handed the
``EmailSenderInterface`` rather than the SMTP class, which is what lets a test
swap in the double from ``tests/doubles``.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.db.session import get_session
from src.integrations.email.interface import EmailSenderInterface
from src.integrations.email.smtp_sender import SMTPEmailSender
from src.models.accounts import ActivationToken, UserGroup
from src.repositories.accounts import UserRepository
from src.repositories.base import BaseRepository
from src.repositories.tokens import TokenRepository
from src.services.accounts.activation import ActivationService
from src.services.accounts.registration import RegistrationService
from src.services.accounts.tokens import TokenLifecycleService

__all__ = [
    "ActivationServiceDep",
    "RegistrationServiceDep",
    "get_activation_service",
    "get_email_sender",
    "get_registration_service",
]

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


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
