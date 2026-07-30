"""Request schemas for password change and password reset.

The replacement password carries the project's strength rules, applied through
``src.security.validators`` so that registration, change and reset can never
disagree about what a strong password is. The *current* password and the reset
token carry none: both are values the user already holds, and rejecting them on
shape would answer 422 where the contract promises 401 or 400 — and would tell a
caller which of the two failed.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas.accounts import _EmailNormalizingSchema
from src.security.validators import validate_password_strength

__all__ = [
    "PasswordChangeRequestSchema",
    "PasswordResetCompleteSchema",
    "PasswordResetRequestSchema",
]

_EXAMPLE_PASSWORD = "Str0ng!Passphrase"
_EXAMPLE_NEW_PASSWORD = "Ev3n!Stronger"
_EXAMPLE_TOKEN = "s7Hn2QpVxK1mR4tZ8yLb0cJdA6wEuG3fOiN5rXqPvSk"


class _NewPasswordSchema(BaseModel):
    """Base for the two schemas that set a replacement password."""

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _validate_new_password(cls, value: str) -> str:
        """Apply the project-wide strength rules to the replacement.

        The ``ValidationError`` the validator raises is a domain exception and is
        allowed to propagate: the handler in ``src/main.py`` renders it as 422
        with the full list of broken rules, which collapsing it here would lose.
        """
        validate_password_strength(value)
        return value


class PasswordChangeRequestSchema(_NewPasswordSchema):
    """The current and replacement passwords of an authenticated caller.

    Carries no account identifier by design. The account the change applies to
    comes from the bearer token, so there is nothing in the body to point at
    somebody else, and ``extra="forbid"`` refuses an attempt to add one.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "old_password": _EXAMPLE_PASSWORD,
                "new_password": _EXAMPLE_NEW_PASSWORD,
            },
        },
    )

    old_password: str = Field(..., min_length=1)


class PasswordResetRequestSchema(_EmailNormalizingSchema):
    """The address a reset link is requested for."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"email": "user@example.com"},
        },
    )


class PasswordResetCompleteSchema(_EmailNormalizingSchema, _NewPasswordSchema):
    """The address, the emailed token and the password that replaces the old one."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "email": "user@example.com",
                "token": _EXAMPLE_TOKEN,
                "new_password": _EXAMPLE_NEW_PASSWORD,
            },
        },
    )

    token: str = Field(..., min_length=1)
