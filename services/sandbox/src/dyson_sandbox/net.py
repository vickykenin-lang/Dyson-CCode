"""Which URLs the sandbox may open. Sealed open-web: any public site, never inward.

The sandbox is sealed from the core at the network layer (an egress firewall drops private ranges),
but the app guards too (defence in depth). An open web still must not become a way back into the
Founder's own infrastructure, so this refuses anything that is not plain http/https to a public
host: no file://, no loopback, no private ranges, and above all no cloud metadata endpoint
(169.254.169.254). A hostname that resolves is allowed only if it is not a private literal; a bare
private IP is refused outright.
"""

import ipaddress
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http", "https")


class UnsafeUrl(ValueError):
    """The URL points somewhere the sandbox may not go (inward, or not a web page)."""


def _is_public_host(host: str) -> bool:
    """True if host is not an obviously-inward target. A non-IP hostname passes here; the egress
    firewall is the backstop for a name that resolves to a private address."""
    host = host.strip("[]")  # IPv6 literals arrive bracketed
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # a domain name, not a literal IP
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # 169.254/16 — the cloud metadata endpoint lives here
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def safe_public_url(url: str) -> str:
    """Return the URL if it is plain http/https to a public host, else raise UnsafeUrl."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrl(f"only http/https, not {parts.scheme!r}")
    if not parts.hostname:
        raise UnsafeUrl("no host in URL")
    if not _is_public_host(parts.hostname):
        raise UnsafeUrl("that address is inward (private, loopback or metadata); refused")
    return url.strip()
