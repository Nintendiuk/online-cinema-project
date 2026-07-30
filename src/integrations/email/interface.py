"""Abstraction over transactional e-mail delivery.

Services depend on this ABC and are handed a concrete sender by injection; they
never import one. Password-reset and order-confirmation methods arrive in later
phases and are deliberately absent here, because an unused abstract method
breaks every implementation that does not yet override it.
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
