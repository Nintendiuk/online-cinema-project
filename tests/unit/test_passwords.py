"""Unit tests for the password hashing helpers."""

import pytest

from src.core.exceptions import ValidationError
from src.security.passwords import (
    BCRYPT_MAX_PASSWORD_BYTES,
    hash_password,
    verify_password,
)

pytestmark = pytest.mark.unit

PLAIN = "Str0ng!Password"


def test_hash_differs_from_plaintext() -> None:
    """The stored value never contains the password itself."""
    hashed = hash_password(PLAIN)

    assert hashed != PLAIN
    assert PLAIN not in hashed


def test_hash_uses_bcrypt_scheme() -> None:
    """Hashes carry the bcrypt identifier."""
    assert hash_password(PLAIN).startswith("$2")


def test_two_hashes_of_same_password_differ() -> None:
    """A fresh salt per call means identical passwords hash differently."""
    assert hash_password(PLAIN) != hash_password(PLAIN)


def test_verify_accepts_correct_password() -> None:
    """Verification succeeds against the hash it was derived from."""
    assert verify_password(PLAIN, hash_password(PLAIN)) is True


def test_verify_rejects_wrong_password() -> None:
    """Verification fails for any other password."""
    assert verify_password("Wr0ng!Password", hash_password(PLAIN)) is False


def test_hash_rejects_password_beyond_bcrypt_limit() -> None:
    """Over-long passwords are refused rather than silently truncated."""
    too_long = "A" * (BCRYPT_MAX_PASSWORD_BYTES + 1)

    with pytest.raises(ValidationError) as exc_info:
        hash_password(too_long)

    assert "bytes" in exc_info.value.details["password"][0]


def test_password_at_the_limit_is_accepted() -> None:
    """Exactly 72 bytes still hashes: the boundary itself is valid."""
    at_limit = "A" * BCRYPT_MAX_PASSWORD_BYTES

    assert verify_password(at_limit, hash_password(at_limit)) is True


def test_verify_returns_false_for_malformed_hash() -> None:
    """A corrupted stored hash fails verification instead of raising."""
    assert verify_password(PLAIN, "not-a-bcrypt-hash") is False
