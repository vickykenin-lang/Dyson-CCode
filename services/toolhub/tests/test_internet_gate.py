"""The internet gate (phase 6): allowlist, https-only, no IPs, STOP, and an audit trail."""

from dyson_toolhub.internet_gate import (
    GateDecision,
    InternetGate,
    host_allowed,
    url_allowed,
)

ALLOW = frozenset({"youtube.com", "gmail.googleapis.com"})


def test_an_allowlisted_host_and_its_subdomains_pass():
    assert host_allowed("youtube.com", ALLOW)
    assert host_allowed("www.youtube.com", ALLOW)  # subdomain
    assert not host_allowed("youtube.com.evil.com", ALLOW)  # not a subdomain of the allowlist
    assert not host_allowed("notyoutube.com", ALLOW)


def test_only_https_to_a_named_allowlisted_host():
    assert url_allowed("https://www.youtube.com/watch", ALLOW) == (True, "ok")
    assert url_allowed("http://youtube.com", ALLOW)[0] is False  # not https
    assert url_allowed("https://evil.com", ALLOW)[0] is False  # not allowlisted


def test_ip_addresses_and_userinfo_are_refused():
    assert url_allowed("https://93.184.216.34/", ALLOW) == (False, "ip address not allowed")
    assert url_allowed("https://user:pw@youtube.com/", ALLOW) == (False, "userinfo not allowed")


def test_the_gate_records_every_decision():
    seen: list[GateDecision] = []
    gate = InternetGate(ALLOW, record=seen.append)
    gate.request("https://www.youtube.com/watch")
    gate.request("https://evil.com/steal")
    assert [d.allowed for d in seen] == [True, False]
    assert seen[1].reason == "host not on the allowlist"


def test_stop_blocks_every_request_whatever_the_url():
    gate = InternetGate(ALLOW, stopped=lambda: True)
    d = gate.request("https://www.youtube.com/watch")  # normally allowed
    assert not d.allowed and d.reason == "stopped"
