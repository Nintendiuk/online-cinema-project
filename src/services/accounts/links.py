"""Construction of the links that go out in account e-mail.

Registration, activation-resend and the password reset request all need a link
that carries an address and a token, which is why the query building sits here
once rather than as a private method on three services. Base URLs come from
settings; nothing here holds a literal.
"""

from urllib.parse import urlencode

__all__ = ["build_activation_link", "build_password_reset_link"]


def _credentialed_link(base_url: str, email: str, token: str) -> str:
    """Return the URL carrying the address and token as a query string.

    Both values are percent-encoded, so a ``+`` in an address or a ``-`` in a
    URL-safe token survives the round trip intact.
    """
    query = urlencode({"email": email, "token": token})
    return f"{base_url}?{query}"


def build_activation_link(activation_url: str, email: str, token: str) -> str:
    """Return the link that activates one account."""
    return _credentialed_link(activation_url, email, token)


def build_password_reset_link(reset_url: str, email: str, token: str) -> str:
    """Return the link that authorises one password reset."""
    return _credentialed_link(reset_url, email, token)
