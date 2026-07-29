"""Response envelopes shared by every feature of the API."""

from pydantic import BaseModel, ConfigDict

__all__ = ["MessageResponseSchema"]


class MessageResponseSchema(BaseModel):
    """A bare human-readable outcome message.

    Returned by endpoints that change state but have nothing to hand back, such
    as account activation. The wording is part of the contract only where a test
    pins it; callers must not parse it for control flow.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"message": "Account activated successfully."},
        },
    )

    message: str
