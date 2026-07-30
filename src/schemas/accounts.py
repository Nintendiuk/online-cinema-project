"""Request and response schemas for registration and account activation.

These schemas validate the *shape* of a payload. Every domain rule — password
strength, e-mail canonicalisation — is delegated to ``src.security.validators``
so that registration, password change and password reset all enforce one set of
rules. Re-implementing any of it here blocks a merge.
"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.security.validators import normalize_email, validate_password_strength

__all__ = [
    "ActivationRequestSchema",
    "ResendActivationRequestSchema",
    "UserRegistrationRequestSchema",
    "UserRegistrationResponseSchema",
]


class _EmailNormalizingSchema(BaseModel):
    """Base for request schemas carrying an ``email`` field.

    Normalisation runs in ``before`` mode on purpose: an address typed as
    ``"  User@Mail.COM "`` must reach ``EmailStr`` already trimmed and lowercased.
    An ``after`` validator would never see it, because ``EmailStr`` would have
    rejected the untrimmed string first.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value: object) -> object:
        """Trim and lowercase the address before ``EmailStr`` parses it."""
        if isinstance(value, str):
            return normalize_email(value)
        return value


class UserRegistrationRequestSchema(_EmailNormalizingSchema):
    """Credentials accepted by the registration endpoint."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "email": "user@example.com",
                "password": "Str0ng!Passphrase",
            },
        },
    )

    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        """Apply the project-wide password strength rules.

        The ``ValidationError`` raised by the validator is a domain exception and
        is deliberately allowed to propagate: the handler in ``src/main.py`` maps
        it to HTTP 422 together with the full list of broken rules. Catching it
        here would collapse that list into a generic message.
        """
        validate_password_strength(value)
        return value


class UserRegistrationResponseSchema(BaseModel):
    """Public view of a freshly created account.

    Deliberately narrow. Neither the password nor its hash may ever appear in
    this schema, and a test asserts their absence from the response body.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {"id": 1, "email": "user@example.com"},
        },
    )

    id: int
    email: EmailStr


class ActivationRequestSchema(_EmailNormalizingSchema):
    """Address and activation token submitted to finish registration."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "email": "user@example.com",
                "token": "s7Hn2QpVxK1mR4tZ8yLb0cJdA6wEuG3fOiN5rXqPvSk",
            },
        },
    )

    token: str = Field(..., min_length=1)


class ResendActivationRequestSchema(_EmailNormalizingSchema):
    """Address for which a fresh activation e-mail is requested."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"email": "user@example.com"},
        },
    )
