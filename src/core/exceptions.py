"""Domain exception hierarchy.

The single source of application errors. Services and repositories raise these;
the FastAPI exception handler in ``src/main.py`` is the only place that maps them
to HTTP status codes. This module must stay free of web-framework imports.
"""

from typing import Any

__all__ = [
    "AppError",
    "AuthenticationError",
    "ConflictError",
    "ExternalServiceError",
    "InvalidRequestError",
    "NotFoundError",
    "PermissionDeniedError",
    "TokenExpiredError",
    "ValidationError",
]


class AppError(Exception):
    """Base class for all domain exceptions in the application."""

    default_message: str = "Application error."

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Store the resolved message and the optional details payload."""
        self.message: str = message if message is not None else self.default_message
        self.details: dict[str, Any] = details if details is not None else {}
        super().__init__(self.message)


class ValidationError(AppError):
    """Raised when input data fails domain or schema validation."""

    default_message: str = "Validation failed."


class NotFoundError(AppError):
    """Raised when a requested resource cannot be found."""

    default_message: str = "Requested resource was not found."


class ConflictError(AppError):
    """Raised when an operation conflicts with the current state of a resource."""

    default_message: str = "Resource conflict."


class AuthenticationError(AppError):
    """Raised when authentication credentials are missing or invalid."""

    default_message: str = "Authentication failed."


class PermissionDeniedError(AppError):
    """Raised when the caller lacks sufficient permissions for the operation."""

    default_message: str = "Not enough permissions."


class TokenExpiredError(AppError):
    """Raised when an authentication or authorization token has expired."""

    default_message: str = "Token has expired."


class InvalidRequestError(AppError):
    """Raised when a well-formed request cannot be applied to the current state.

    Distinct from ``ValidationError``, which is about the shape of the payload,
    and from ``AuthenticationError``, which is about a credential. This one
    covers a client mistake that only the domain can detect: an activation token
    that was never issued, one that belongs to somebody else, or an account that
    is already active.
    """

    default_message: str = "Request cannot be applied in the current state."


class ExternalServiceError(AppError):
    """Raised when an external service is unavailable or returns an error."""

    default_message: str = "External service is unavailable."
