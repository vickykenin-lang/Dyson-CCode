"""The internet gate (phase 6, D-026): the only way a capability reaches the web.

The browser and any web tool reach the internet only through here. Three rules on every request,
all of them, every time (the same spirit as G's six checks):
  1. the URL is https to a host on the capability's allowlist (exact host or a subdomain of one);
  2. the current STOP state allows it;
  3. the request is recorded, allowed or denied.
No userinfo, no raw IP address, no plain http. A host the capability did not declare is denied.
"""

from collections.abc import Callable

from dyson_contracts.common import Contract, NonEmptyStr


def normalise_host(host: str) -> str:
    return host.strip().rstrip(".").lower()


def host_allowed(host: str, allowlist: frozenset[str]) -> bool:
    """True if host equals an allowlisted host or is a subdomain of one."""
    h = normalise_host(host)
    if not h:
        return False
    for allowed in allowlist:
        a = normalise_host(allowed)
        if h == a or h.endswith("." + a):
            return True
    return False


def _is_ip_literal(host: str) -> bool:
    # A bare IPv4, or any IPv6 literal in brackets. Hosts must be names, not addresses.
    if host.startswith("["):
        return True
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


def _authority(url: str) -> tuple[str, str] | None:
    """Return (scheme, authority) by hand, so G imports no URL/network library."""
    if "://" not in url:
        return None
    scheme, rest = url.split("://", 1)
    # The authority ends at the first '/', '?' or '#'.
    for sep in ("/", "?", "#"):
        if sep in rest:
            rest = rest.split(sep, 1)[0]
    return scheme.lower(), rest


def _host_of(authority: str) -> str:
    """The host alone: drop any userinfo and port, keep an IPv6 literal's brackets."""
    if authority.startswith("["):  # [ipv6]:port
        return authority.split("]", 1)[0] + "]"
    return authority.rsplit(":", 1)[0] if ":" in authority else authority


def url_allowed(url: str, allowlist: frozenset[str]) -> tuple[bool, str]:
    """Return (allowed, reason). Only https to an allowlisted named host passes."""
    parsed = _authority(url)
    if parsed is None:
        return False, "unparseable url"
    scheme, authority = parsed
    if scheme != "https":
        return False, "not https"
    if "@" in authority:
        return False, "userinfo not allowed"
    host = _host_of(authority)
    if not host:
        return False, "no host"
    if _is_ip_literal(host):
        return False, "ip address not allowed"
    if not host_allowed(host, allowlist):
        return False, "host not on the allowlist"
    return True, "ok"


class GateDecision(Contract):
    url: NonEmptyStr
    allowed: bool
    reason: NonEmptyStr


class InternetGate:
    """One capability's window to the web: its allowlist, the STOP check, and an audit trail."""

    def __init__(
        self,
        allowlist: frozenset[str],
        stopped: Callable[[], bool] = lambda: False,
        record: Callable[[GateDecision], None] | None = None,
    ):
        self._allowlist = allowlist
        self._stopped = stopped
        self._record = record

    def request(self, url: str) -> GateDecision:
        if self._stopped():
            decision = GateDecision(url=url, allowed=False, reason="stopped")
        else:
            ok, reason = url_allowed(url, self._allowlist)
            decision = GateDecision(url=url, allowed=ok, reason=reason)
        if self._record is not None:
            self._record(decision)
        return decision
