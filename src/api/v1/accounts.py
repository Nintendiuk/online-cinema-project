"""Registration and activation endpoints.

Each handler is dependencies in, one service call, return. The resend endpoint
answers with one fixed message whatever the outcome, which is what keeps an
unknown address indistinguishable from a settled account.
"""

from typing import Final

from fastapi import APIRouter, status

from src.api.deps import ActivationServiceDep, RegistrationServiceDep
from src.models.accounts import User
from src.schemas.accounts import (
    ActivationRequestSchema,
    ResendActivationRequestSchema,
    UserRegistrationRequestSchema,
    UserRegistrationResponseSchema,
)
from src.schemas.common import MessageResponseSchema

__all__ = ["router"]

router = APIRouter(prefix="/accounts", tags=["accounts"])

ACTIVATION_COMPLETE_MESSAGE: Final[str] = "Account activated successfully."
RESEND_ACKNOWLEDGED_MESSAGE: Final[str] = (
    "If the account exists and is not yet active, an activation e-mail has been sent."
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
