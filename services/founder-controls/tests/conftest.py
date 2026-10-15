from datetime import timedelta

import pytest
from controls_testkit import CHANNEL_KEY, DEVICE_KEY, Audit, Clock, FakeGovernance
from fastapi.testclient import TestClient

from dyson_founder_controls.app import create_app
from dyson_founder_controls.client import ControlsClient
from dyson_founder_controls.ports import HmacChannelSigner
from dyson_founder_controls.stepup import DeviceKeyStepUp


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def gov():
    return FakeGovernance()


@pytest.fixture
def audit():
    return Audit()


@pytest.fixture
def http(gov, audit, clock):
    stepup = DeviceKeyStepUp(DEVICE_KEY, ttl=timedelta(minutes=2), clock=clock)
    return TestClient(create_app(gov, stepup, HmacChannelSigner(CHANNEL_KEY), audit, clock))


@pytest.fixture
def founder(http):
    return ControlsClient(http, DEVICE_KEY)
