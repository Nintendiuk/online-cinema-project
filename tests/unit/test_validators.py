"""Unit tests for password strength rules and e-mail normalisation."""

import pytest

from src.core.exceptions import ValidationError
from src.security.validators import normalize_email, validate_password_strength

pytestmark = pytest.mark.unit

VALID_PASSWORD = "Str0ng!Pass"


def test_valid_password_passes() -> None:
    """A password satisfying every rule raises nothing."""
    assert validate_password_strength(VALID_PASSWORD) is None


@pytest.mark.parametrize(
    ("password", "expected_fragment"),
    [
        ("Sh0rt!A", "at least 8 characters"),
        ("str0ng!pass", "uppercase letter"),
        ("STR0NG!PASS", "lowercase letter"),
        ("Strong!Pass", "digit"),
        ("Str0ngPass", "special character"),
        ("Str0ng!" + "a" * 70, "72 bytes"),
    ],
    ids=["too-short", "no-upper", "no-lower", "no-digit", "no-special", "too-long"],
)
def test_each_rule_is_enforced_separately(
    password: str, expected_fragment: str
) -> None:
    """Every rule fails on its own and names itself in the details payload."""
    with pytest.raises(ValidationError) as exc_info:
        validate_password_strength(password)

    violations = exc_info.value.details["password"]
    assert len(violations) == 1
    assert expected_fragment in violations[0]


def test_details_lists_every_violation() -> None:
    """A password breaking several rules reports all of them, not just the first."""
    with pytest.raises(ValidationError) as exc_info:
        validate_password_strength("abc")

    violations = exc_info.value.details["password"]
    assert len(violations) == 4
    assert any("at least 8 characters" in item for item in violations)
    assert any("uppercase letter" in item for item in violations)
    assert any("digit" in item for item in violations)
    assert any("special character" in item for item in violations)


def test_empty_password_breaks_every_rule() -> None:
    """An empty password violates all five rules at once."""
    with pytest.raises(ValidationError) as exc_info:
        validate_password_strength("")

    assert len(exc_info.value.details["password"]) == 5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  User@Example.COM  ", "user@example.com"),
        ("user@example.com", "user@example.com"),
        ("\tMiXeD@Case.Org\n", "mixed@case.org"),
    ],
    ids=["trims-and-lowers", "already-normal", "surrounding-whitespace"],
)
def test_normalize_email(raw: str, expected: str) -> None:
    """Normalisation trims surrounding whitespace and lowercases the address."""
    assert normalize_email(raw) == expected
