"""Abstraction over transactional e-mail delivery.

Services depend on this ABC and are handed a concrete sender by injection; they
never import one. Methods are added the moment a service needs one and not
before: an abstract method with no caller breaks every implementation that has
not yet overridden it, so order-confirmation and comment-reply notifications
still wait for the phases that send them.

Every method added here must be implemented in ``smtp_sender`` **and** in the
double under ``tests/doubles`` in the same commit. The suite injects the double
wherever production injects the sender, so a method present on only one of the
two turns every e-mail assertion in the suite into a false pass;
``tests/unit/test_email_sender_contract.py`` fails when they drift.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

__all__ = ["EmailSenderInterface", "SentEmail"]


@dataclass(frozen=True)
class SentEmail:
    """An immutable record of one message handed to a sender.

    Frozen on purpose: a recorded message cannot be rewritten after the fact, so
    an assertion about what was sent cannot be invalidated by later code.
    """

    to: str
    subject: str
    body: str


class EmailSenderInterface(ABC):
    """The contract every e-mail sender in the project implements.

    Implementations wrap transport failures in ``ExternalServiceError`` from
    ``src.core.exceptions``, so a caller never has to know which library moved
    the bytes.
    """

    @abstractmethod
    async def send_activation_email(self, email: str, activation_link: str) -> None:
        """Send the activation link to a freshly registered account.

        Raises ``ExternalServiceError`` when the message cannot be handed over.
        """

    @abstractmethod
    async def send_activation_complete_email(self, email: str, login_link: str) -> None:
        """Confirm to the user that the account is now active.

        Raises ``ExternalServiceError`` when the message cannot be handed over.
        """

    @abstractmethod
    async def send_password_reset_email(self, email: str, reset_link: str) -> None:
        """Send the single-use link that authorises one password reset.

        Raises ``ExternalServiceError`` when the message cannot be handed over.
        """

    @abstractmethod
    async def send_password_changed_email(self, email: str) -> None:
        """Tell the account holder that their password has just changed.

        Carries no link on purpose: this message is the alarm that fires when
        somebody else changed the credential, and an alarm must not offer the
        reader a button to click. It reports the change and nothing more.

        Raises ``ExternalServiceError`` when the message cannot be handed over.
        """
