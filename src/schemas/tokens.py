"""Request and response schemas for the authentication endpoints.

Deliberately thinner than the registration schemas. Login validates the *shape*
of a credential and nothing else: a password that is too short or too weak is
still a credential the user may have typed, and rejecting it here would answer
422 where the contract promises 401 and would tell an attacker that the value
failed the strength rules rather than the comparison. Strength is registration's
concern alone.
"""

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.accounts import _EmailNormalizingSchema

__all__ = [
    "AccessTokenResponseSchema",
    "LoginRequestSchema",
    "LogoutRequestSchema",
    "RefreshRequestSchema",
    "TokenPairResponseSchema",
]

_EXAMPLE_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxfQ.5m0kQeXaMpLe"
"""Shaped but non-functional token, used only in the OpenAPI examples."""

_BEARER = "bearer"


class LoginRequestSchema(_EmailNormalizingSchema):
    """Credentials submitted to exchange for a token pair.

    Inherits the before-mode e-mail normaliser, so an address typed with stray
    whitespace or capitals reaches the service already canonical and matches the
    stored row. The subclass restates ``extra="forbid"`` because declaring
    ``model_config`` replaces the parent's rather than merging with it.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "email": "user@example.com",
                "password": "Str0ng!Passphrase",
            },
        },
    )

    password: str


class TokenPairResponseSchema(BaseModel):
    """The access and refresh tokens minted by a successful login."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": _EXAMPLE_JWT,
                "refresh_token": _EXAMPLE_JWT,
                "token_type": _BEARER,
            },
        },
    )

    access_token: str
    refresh_token: str
    token_type: str = _BEARER


class AccessTokenResponseSchema(BaseModel):
    """The single access token minted by a successful refresh."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": _EXAMPLE_JWT,
                "token_type": _BEARER,
            },
        },
    )

    access_token: str
    token_type: str = _BEARER


class RefreshRequestSchema(BaseModel):
    """The refresh token presented in exchange for a new access token."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"refresh_token": _EXAMPLE_JWT},
        },
    )

    refresh_token: str = Field(..., min_length=1)


class LogoutRequestSchema(BaseModel):
    """The refresh token identifying which session to end."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"refresh_token": _EXAMPLE_JWT},
        },
    )

    refresh_token: str = Field(..., min_length=1)
