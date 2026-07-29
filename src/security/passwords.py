"""Password hashing.

The only place in the project where a password is hashed or verified. Services
call these two functions; nothing else may import ``bcrypt``.

``passlib`` is deliberately not used: its last release predates bcrypt 4 and its
backend probe breaks against current versions of the library.
"""

import bcrypt

from src.core.exceptions import ValidationError

__all__ = ["BCRYPT_MAX_PASSWORD_BYTES", "hash_password", "verify_password"]

BCRYPT_MAX_PASSWORD_BYTES = 72
"""Hard limit of the bcrypt algorithm: anything beyond is silently ignored."""

_BCRYPT_ROUNDS = 12


def hash_password(plain: str) -> str:
    """Return a salted bcrypt hash of the given plaintext password.

    Raises ``ValidationError`` when the password exceeds the bcrypt limit,
    rather than truncating it and hashing something the user never typed.
    """
    encoded = plain.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValidationError(
            "Password does not meet the strength requirements.",
            {
                "password": [
                    f"Password must not exceed {BCRYPT_MAX_PASSWORD_BYTES} bytes."
                ]
            },
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt(_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Whether the plaintext password matches the stored hash.

    A malformed or foreign hash yields ``False`` instead of an exception, so a
    corrupted row cannot turn into a 500 on the login path.
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False
