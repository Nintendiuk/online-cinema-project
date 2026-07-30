"""Registration, activation, session and password endpoints.

Each handler is dependencies in, one service call, return. Two of them answer with
one fixed message whatever the outcome — the activation resend and the password
reset request — which is what keeps an unknown address indistinguishable from a
settled account.

``/login/`` answers 201 rather than 200: it creates a session resource, and the
refresh token it returns is the handle to it. The password routes answer 200:
they change the state of a resource that already exists.
"""

from typing import Final

from fastapi import APIRouter, status

from src.api.deps import CurrentUserDep
from src.api.providers import (
    ActivationServiceDep,
    AuthenticationServiceDep,
    PasswordServiceDep,
    RegistrationServiceDep,
)
from src.models.accounts import User
from src.schemas.accounts import (
    ActivationRequestSchema,
    ResendActivationRequestSchema,
    UserRegistrationRequestSchema,
    UserRegistrationResponseSchema,
)
from src.schemas.common import MessageResponseSchema
from src.schemas.password import (
    PasswordChangeRequestSchema,
    PasswordResetCompleteSchema,
    PasswordResetRequestSchema,
)
from src.schemas.tokens import (
    AccessTokenResponseSchema,
    LoginRequestSchema,
    LogoutRequestSchema,
    RefreshRequestSchema,
    TokenPairResponseSchema,
)

__all__ = ["router"]

router = APIRouter(prefix="/accounts", tags=["accounts"])

ACTIVATION_COMPLETE_MESSAGE: Final[str] = "Account activated successfully."
RESEND_ACKNOWLEDGED_MESSAGE: Final[str] = (
    "If the account exists and is not yet active, an activation e-mail has been sent."
)
LOGOUT_COMPLETE_MESSAGE: Final[str] = "Session ended successfully."
PASSWORD_CHANGED_MESSAGE: Final[str] = (
    "Password changed successfully. Every session has been signed out."
)
RESET_ACKNOWLEDGED_MESSAGE: Final[str] = (
    "If the account exists and is active, a password reset e-mail has been sent."
)
RESET_COMPLETE_MESSAGE: Final[str] = (
    "Password has been reset. You can log in with the new password."
)


@router.post(
    "/register/",
    response_model=UserRegistrationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
    responses={
        409: {"description": "An account with this e-mail already exists."},
        422: {"description": "Malformed payload or a password that is too weak."},
        502: {"description": "The activation e-mail could not be delivered."},
    },
)
async def register(
    payload: UserRegistrationRequestSchema,
    service: RegistrationServiceDep,
) -> User:
    """Create a deactivated account and e-mail its activation link."""
    return await service.register_user(payload.email, payload.password)


@router.post(
    "/activate/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Activate an account",
    responses={
        400: {"description": "The token is invalid, spent, expired or foreign."},
        422: {"description": "Malformed payload."},
    },
)
async def activate(
    payload: ActivationRequestSchema,
    service: ActivationServiceDep,
) -> MessageResponseSchema:
    """Consume the activation token and mark the account active."""
    await service.activate_account(payload.email, payload.token)
    return MessageResponseSchema(message=ACTIVATION_COMPLETE_MESSAGE)


@router.post(
    "/resend-activation/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Request a fresh activation e-mail",
    responses={
        200: {
            "description": "Acknowledged; the reply never reveals whether the "
            "account exists."
        },
        422: {"description": "Malformed payload."},
    },
)
async def resend_activation(
    payload: ResendActivationRequestSchema,
    service: ActivationServiceDep,
) -> MessageResponseSchema:
    """Issue a new activation token when warranted, and always acknowledge."""
    await service.resend_activation(payload.email)
    return MessageResponseSchema(message=RESEND_ACKNOWLEDGED_MESSAGE)


@router.post(
    "/login/",
    response_model=TokenPairResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Open a session and receive a token pair",
    responses={
        401: {"description": "The e-mail or the password is wrong."},
        403: {"description": "The account exists but has not been activated."},
        422: {"description": "Malformed payload."},
    },
)
async def login(
    payload: LoginRequestSchema,
    service: AuthenticationServiceDep,
) -> TokenPairResponseSchema:
    """Exchange credentials for an access and a refresh token."""
    access_token, refresh_token = await service.login(payload.email, payload.password)
    return TokenPairResponseSchema(
        access_token=access_token, refresh_token=refresh_token
    )


@router.post(
    "/refresh/",
    response_model=AccessTokenResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Renew an access token",
    responses={
        401: {"description": "The refresh token is unknown, spent or expired."},
        403: {"description": "The account behind the token is no longer active."},
        422: {"description": "Malformed payload."},
    },
)
async def refresh(
    payload: RefreshRequestSchema,
    service: AuthenticationServiceDep,
) -> AccessTokenResponseSchema:
    """Mint a new access token for a session that is still valid."""
    access_token = await service.refresh(payload.refresh_token)
    return AccessTokenResponseSchema(access_token=access_token)


@router.post(
    "/logout/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="End one session",
    responses={
        401: {
            "description": "No bearer token, an invalid one, or a refresh token "
            "belonging to another account."
        },
        403: {"description": "The authenticated account is no longer active."},
        422: {"description": "Malformed payload."},
    },
)
async def logout(
    payload: LogoutRequestSchema,
    current_user: CurrentUserDep,
    service: AuthenticationServiceDep,
) -> MessageResponseSchema:
    """Revoke the presented refresh token, leaving the caller's others alive."""
    await service.logout(current_user.id, payload.refresh_token)
    return MessageResponseSchema(message=LOGOUT_COMPLETE_MESSAGE)


@router.post(
    "/change-password/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Change the password of the authenticated account",
    responses={
        400: {"description": "The new password is the one already in use."},
        401: {
            "description": "No bearer token, an invalid one, or a wrong current "
            "password."
        },
        403: {"description": "The authenticated account is no longer active."},
        422: {"description": "Malformed payload or a new password that is too weak."},
    },
)
async def change_password(
    payload: PasswordChangeRequestSchema,
    current_user: CurrentUserDep,
    service: PasswordServiceDep,
) -> MessageResponseSchema:
    """Replace the caller's own password and end every session they hold."""
    await service.change_password(
        current_user, payload.old_password, payload.new_password
    )
    return MessageResponseSchema(message=PASSWORD_CHANGED_MESSAGE)


@router.post(
    "/password-reset/request/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Request a password reset link",
    responses={
        200: {
            "description": "Acknowledged; the reply never reveals whether the "
            "account exists or is active."
        },
        422: {"description": "Malformed payload."},
        502: {"description": "The reset e-mail could not be delivered."},
    },
)
async def request_password_reset(
    payload: PasswordResetRequestSchema,
    service: PasswordServiceDep,
) -> MessageResponseSchema:
    """Issue a reset token when warranted, and always acknowledge."""
    await service.request_reset(payload.email)
    return MessageResponseSchema(message=RESET_ACKNOWLEDGED_MESSAGE)


@router.post(
    "/password-reset/complete/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Set a new password using a reset token",
    responses={
        400: {"description": "The token is invalid, spent, expired or foreign."},
        422: {"description": "Malformed payload or a new password that is too weak."},
        502: {"description": "The confirmation e-mail could not be delivered."},
    },
)
async def complete_password_reset(
    payload: PasswordResetCompleteSchema,
    service: PasswordServiceDep,
) -> MessageResponseSchema:
    """Consume the reset token, set the new password and end every session."""
    await service.complete_reset(payload.email, payload.token, payload.new_password)
    return MessageResponseSchema(message=RESET_COMPLETE_MESSAGE)
