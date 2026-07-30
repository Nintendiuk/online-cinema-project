"""SMTP delivery of the account e-mails.

The only module in the project that speaks to a mail server. Every transport
failure is wrapped in ``ExternalServiceError`` so that services above never see
an ``aiosmtplib`` type, and links arrive already built — this class does not
know what a front-end URL looks like.
"""

from email.message import EmailMessage
from pathlib import Path
from typing import Final

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.core.exceptions import ExternalServiceError
from src.integrations.email.interface import EmailSenderInterface

__all__ = ["SMTPEmailSender"]

TEMPLATES_DIR: Final[Path] = Path(__file__).resolve().parent / "templates"

ACTIVATION_SUBJECT: Final[str] = "Activate your Online Cinema account"
ACTIVATION_COMPLETE_SUBJECT: Final[str] = "Your Online Cinema account is active"


class SMTPEmailSender(EmailSenderInterface):
    """Renders the HTML templates and hands the result to an SMTP server."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        use_tls: bool,
    ) -> None:
        """Store the connection settings and build the template environment."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._use_tls = use_tls
        self._templates = Environment(
            loader=FileSystemLoader(TEMPLATES_DIR),
            autoescape=select_autoescape(["html"]),
        )

    async def send_activation_email(self, email: str, activation_link: str) -> None:
        """Send the activation link to a freshly registered account."""
        body = self._render(
            "activation_request.html", email=email, activation_link=activation_link
        )
        await self._deliver(email, ACTIVATION_SUBJECT, body)

    async def send_activation_complete_email(self, email: str, login_link: str) -> None:
        """Confirm to the user that the account is now active."""
        body = self._render(
            "activation_complete.html", email=email, login_link=login_link
        )
        await self._deliver(email, ACTIVATION_COMPLETE_SUBJECT, body)

    def _render(self, template_name: str, **context: str) -> str:
        """Render one template from ``templates/`` with the given context."""
        return self._templates.get_template(template_name).render(**context)

    async def _deliver(self, to: str, subject: str, body: str) -> None:
        """Hand one HTML message to the configured server.

        Both ``SMTPException`` and ``OSError`` are caught: a refused connection
        or a DNS failure never reaches the mail library's own hierarchy, and a
        caller must not have to know the difference.
        """
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body, subtype="html")

        try:
            await aiosmtplib.send(
                message,
                hostname=self._host,
                port=self._port,
                username=self._username or None,
                password=self._password or None,
                start_tls=self._use_tls,
            )
        except (aiosmtplib.SMTPException, OSError) as error:
            raise ExternalServiceError(
                "Could not deliver the message.", {"recipient": to}
            ) from error
