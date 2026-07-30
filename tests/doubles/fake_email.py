"""In-memory stand-in for the e-mail sender.

Sends nothing and records everything, so a test can assert on what would have
gone out. ``raise_on_send`` turns it into a failing transport, which is how the
suite exercises the rollback path in registration.
"""

from typing import Final

from src.core.exceptions import ExternalServiceError
from src.integrations.email.interface import EmailSenderInterface, SentEmail

__all__ = [
    "ACTIVATION_COMPLETE_SUBJECT",
    "ACTIVATION_SUBJECT",
    "FakeEmailSender",
]

ACTIVATION_SUBJECT: Final[str] = "Activate your account"
ACTIVATION_COMPLETE_SUBJECT: Final[str] = "Account activated"


class FakeEmailSender(EmailSenderInterface):
    """Records outgoing messages instead of delivering them."""

    def __init__(self, *, raise_on_send: bool = False) -> None:
        """Start with an empty history and a working transport by default.

        Both attributes are per-instance: a class-level list would be shared by
        every test in the session and turn the suite into a source of false
        passes.
        """
        self.sent: list[SentEmail] = []
        self.raise_on_send: bool = raise_on_send

    @property
    def last(self) -> SentEmail | None:
        """The most recent message, or ``None`` when nothing was sent."""
        if not self.sent:
            return None
        return self.sent[-1]

    def clear(self) -> None:
        """Empty the history in place.

        In place rather than rebinding, because a fixture may already have
        handed the list itself to a caller.
        """
        self.sent.clear()

    def count_for(self, email: str) -> int:
        """How many messages were addressed to exactly this address."""
        return sum(1 for item in self.sent if item.to == email)

    async def send_activation_email(self, email: str, activation_link: str) -> None:
        """Record an activation message carrying the link verbatim.

        The link is embedded unescaped: a test asserts that the token value,
        which is a substring of the link, appears in the body.
        """
        self._guard()
        body = f"Please activate your account using this link: {activation_link}"
        self.sent.append(SentEmail(to=email, subject=ACTIVATION_SUBJECT, body=body))

    async def send_activation_complete_email(self, email: str, login_link: str) -> None:
        """Record a confirmation message carrying the login link verbatim."""
        self._guard()
        body = f"Your account has been activated. You can log in here: {login_link}"
        self.sent.append(
            SentEmail(to=email, subject=ACTIVATION_COMPLETE_SUBJECT, body=body)
        )

    def _guard(self) -> None:
        """Fail the send when the double is configured as a broken transport.

        Called before anything is appended, so a failed send leaves no trace.
        """
        if self.raise_on_send:
            raise ExternalServiceError("Fake e-mail transport is configured to fail.")
