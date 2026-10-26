"""The ingest secret scan refuses credential-shaped text."""

from dyson_knowledge.secrets_scan import has_secret


def test_detects_api_key_and_aws_key():
    assert has_secret("the key is sk-abcdefghijklmnopqrstuvwxyz0123") is True
    assert has_secret("AKIA" + "ABCDEFGHIJKLMNOP") is True


def test_plain_notes_are_clean():
    assert has_secret("some normal notes about youtube and my social media plan") is False
    assert has_secret("") is False
