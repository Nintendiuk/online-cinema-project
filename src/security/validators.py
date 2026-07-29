"""Credential validation rules.

The single source of truth for password strength and e-mail normalisation.
Registration, password change and password reset all call these functions;
re-implementing the rules elsewhere blocks a merge.
"""

from src.core.exceptions import ValidationError
from src.security.passwords import BCRYPT_MAX_PASSWORD_BYTES

__all__ = [
    "MIN_PASSWORD_LENGTH",
    "SPECIAL_CHARACTERS",
    "normalize_email",
    "validate_password_strength",
]

MIN_PASSWORD_LENGTH = 8
SPECIAL_CHARACTERS = "!@#$%^&*()-_=+[]{};:,.<>?/"


def validate_password_strength(password: str) -> None:
    """Raise ``ValidationError`` listing every strength rule the password breaks.

    All violations are collected before raising, so the caller can show the user
    the complete list instead of one rule at a time. ``details`` carries them
    under the ``password`` key.
    """
    violations: list[str] = []

    if len(password) < MIN_PASSWORD_LENGTH:
        violations.append(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    if len(password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        violations.append(
            f"Password must not exceed {BCRYPT_MAX_PASSWORD_BYTES} bytes."
        )
    if not any(char.isupper() for char in password):
        violations.append("Password must contain an uppercase letter.")
    if not any(char.islower() for char in password):
        violations.append("Password must contain a lowercase letter.")
    if not any(char.isdigit() for char in password):
        violations.append("Password must contain a digit.")
    if not any(char in SPECIAL_CHARACTERS for char in password):
        violations.append(
            f"Password must contain a special character from {SPECIAL_CHARACTERS}"
        )

    if violations:
        raise ValidationError(
            "Password does not meet the strength requirements.",
            {"password": violations},
        )


def normalize_email(email: str) -> str:
    """Return the e-mail trimmed of surrounding whitespace and lowercased."""
    return email.strip().lower()
