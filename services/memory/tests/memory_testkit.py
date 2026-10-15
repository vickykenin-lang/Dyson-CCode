"""Shared constants for the memory tests."""

import secrets
from datetime import UTC, datetime

CANARY = "canary-" + secrets.token_hex(16)
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
