from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def later():
    return NOW + timedelta(minutes=5)


@pytest.fixture
def uid():
    return uuid4
