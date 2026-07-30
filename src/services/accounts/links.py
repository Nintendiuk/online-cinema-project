"""Construction of the links that go out in account e-mail.

Registration and activation-resend both need the activation URL, which is the
second occurrence that makes this a shared helper rather than a private method
on either service. Base URLs come from settings; nothing here holds a literal.
"""

from urllib.parse import urlencode

__all__ = ["build_activation_link"]


def build_activation_link(activation_url: str, email: str, token: str) -> str:
    """Return the activation URL carrying the address and token as a query.

    Both values are percent-encoded, so a ``+`` in an address or a ``-`` in a
    URL-safe token survives the round trip intact.
    """
    query = urlencode({"email": email, "token": token})
    return f"{activation_url}?{query}"
