"""Unit tests for application settings and their documentation in .env.sample."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.config import Settings, get_settings

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_SAMPLE = REPO_ROOT / ".env.sample"


def parse_env_sample() -> dict[str, str]:
    """Return the key/value pairs declared in .env.sample, keys casefolded."""
    assert ENV_SAMPLE.exists(), f"{ENV_SAMPLE} not found"
    pairs: dict[str, str] = {}
    for raw_line in ENV_SAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs[key.strip().casefold()] = value.strip()
    return pairs


def test_get_settings_returns_settings() -> None:
    """get_settings() returns a Settings instance."""
    assert isinstance(get_settings(), Settings)


def test_get_settings_is_cached() -> None:
    """Consecutive get_settings() calls return the very same object."""
    assert get_settings() is get_settings()


def test_env_sample_covers_all_settings_fields() -> None:
    """The .env.sample key set matches the Settings field set exactly."""
    sample_keys = set(parse_env_sample())
    field_keys = {name.casefold() for name in Settings.model_fields}
    diff = sample_keys ^ field_keys
    assert not diff, (
        "Mismatch between .env.sample and Settings fields: "
        f"only in .env.sample={sorted(sample_keys - field_keys)}, "
        f"only in Settings={sorted(field_keys - sample_keys)}"
    )


def test_missing_required_variable_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dropping one required variable from a complete environment fails validation."""
    for key, value in parse_env_sample().items():
        monkeypatch.setenv(key.upper(), value)
    monkeypatch.delenv("SECRET_KEY_ACCESS", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
