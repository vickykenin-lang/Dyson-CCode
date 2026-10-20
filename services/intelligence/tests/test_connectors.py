"""The Gmail and Calendar connectors declare a safe governance posture (phase 3, D-026)."""

from dyson_contracts.capability import CapabilityKind
from dyson_contracts.common import RiskLevel
from dyson_intelligence.connectors import CALENDAR, CONNECTORS, GMAIL


def test_both_connectors_are_valid_manifests():
    assert {c.id for c in CONNECTORS} == {"dyson.connector.gmail", "dyson.connector.calendar"}
    assert all(c.kind is CapabilityKind.CONNECTOR for c in CONNECTORS)


def test_sending_mail_needs_a_founder_approval():
    send = next(op for op in GMAIL.operations if op.name == "send")
    assert send.requires_approval and send.destructive and send.open_world
    assert GMAIL.needs_founder_admission  # the connector as a whole goes to the Founder


def test_gmail_reads_are_untrusted_and_the_rule_of_two_is_flagged():
    assert GMAIL.rule_of_two.all_three  # untrusted input + sensitive access + external effect
    get = next(op for op in GMAIL.operations if op.name == "get_message")
    assert get.read_only and get.open_world  # body is fetched read-only, then quarantined


def test_connectors_name_their_hosts_and_secrets_but_hold_no_token():
    assert "gmail.googleapis.com" in GMAIL.requests.egress_hosts
    assert GMAIL.requests.secrets == ("gmail_oauth_token",)  # by name only; the Hub injects it
    # The manifest carries no token value anywhere.
    assert "token" not in GMAIL.model_dump_json().lower().replace("oauth_token", "")


def test_creating_a_calendar_event_needs_approval():
    create = next(op for op in CALENDAR.operations if op.name == "create_event")
    assert create.requires_approval and CALENDAR.risk is RiskLevel.HIGH
    listing = next(op for op in CALENDAR.operations if op.name == "list_events")
    assert listing.read_only and not listing.requires_approval
