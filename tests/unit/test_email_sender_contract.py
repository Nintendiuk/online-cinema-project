"""Contract tests binding the e-mail double to the interface it stands in for.

The suite injects ``FakeEmailSender`` wherever production injects
``SMTPEmailSender``, so a method added to the interface and implemented on only
one of them turns every e-mail assertion in the suite into a false pass. These
tests fail the moment the two drift apart, in either direction.
"""

import inspect

import pytest

from src.integrations.email.interface import EmailSenderInterface
from src.integrations.email.smtp_sender import SMTPEmailSender
from tests.doubles.fake_email import FakeEmailSender

pytestmark = pytest.mark.unit

REQUIRED_METHODS = (
    "send_activation_email",
    "send_activation_complete_email",
    "send_password_reset_email",
    "send_password_changed_email",
)
"""Every notification the account feature sends as of this phase."""

IMPLEMENTATIONS: list[type[EmailSenderInterface]] = [FakeEmailSender, SMTPEmailSender]


def _implementation_id(implementation: type[EmailSenderInterface]) -> str:
    """Name the implementation in the parametrised test id."""
    return implementation.__name__


def test_the_interface_declares_every_account_notification() -> None:
    """Each message the services send is abstract on the interface."""
    assert set(REQUIRED_METHODS) <= EmailSenderInterface.__abstractmethods__


@pytest.mark.parametrize(
    "implementation", IMPLEMENTATIONS, ids=_implementation_id
)
def test_implementation_has_no_missing_overrides(
    implementation: type[EmailSenderInterface],
) -> None:
    """A concrete sender leaves nothing abstract, so it can be instantiated."""
    assert implementation.__abstractmethods__ == frozenset()


@pytest.mark.parametrize("name", REQUIRED_METHODS)
@pytest.mark.parametrize(
    "implementation", IMPLEMENTATIONS, ids=_implementation_id
)
def test_signatures_match_the_interface(
    implementation: type[EmailSenderInterface], name: str
) -> None:
    """Same parameters and same return type, so a caller cannot tell them apart."""
    assert inspect.signature(getattr(implementation, name)) == inspect.signature(
        getattr(EmailSenderInterface, name)
    )
