"""Home Assistant fixtures shared by integration tests."""

from collections.abc import AsyncIterator

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.track_things.const import DOMAIN


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow Home Assistant's loader to discover this repository's component."""


@pytest.fixture
async def config_entry(hass: HomeAssistant) -> AsyncIterator[MockConfigEntry]:
    """A synthetic account entry exercises the real config flow and lifecycle."""
    from .auth_fixtures import ENTRY_DATA

    yield MockConfigEntry(domain=DOMAIN, title="Track Things test", data=ENTRY_DATA, version=1)


@pytest.fixture
async def auth_http(monkeypatch):
    """Mock only the HTTP boundary for real config flows and runtime tests."""
    from .api_fixtures import MockHttp

    return MockHttp(monkeypatch)


@pytest.fixture
async def api_http(monkeypatch):
    """Exercise the client's actual aiohttp session without opening network sockets."""
    from unittest.mock import AsyncMock

    import aiohttp

    from custom_components.track_things.api import TrackThingsApi

    from .api_fixtures import MockHttp

    http = MockHttp(monkeypatch)
    sleep = AsyncMock()
    async with aiohttp.ClientSession() as session:
        client = TrackThingsApi(
            "https://backend.example.test",
            session,
            access_token="sentinel-access",
            timeout=7,
            sleep=sleep,
        )
        yield client, http, sleep, session
