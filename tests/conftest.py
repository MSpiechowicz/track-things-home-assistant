"""Home Assistant fixtures shared by integration tests."""

from collections.abc import AsyncIterator

import pytest
from homeassistant.config_entries import ConfigFlow
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_config_flow,
    mock_platform,
)

from custom_components.track_things.const import DOMAIN


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow Home Assistant's loader to discover this repository's component."""


@pytest.fixture
async def config_entry(hass: HomeAssistant) -> AsyncIterator[MockConfigEntry]:
    """Stub only the future flow; exercise the real loader and lifecycle hooks."""
    # HA requires a flow handler even for synthetic entries. Issue #7 owns the
    # actual flow, so use the harness's platform/flow stubs only in these tests.
    await async_get_integration(hass, DOMAIN)
    mock_platform(hass, f"{DOMAIN}.config_flow", built_in=False)
    with mock_config_flow(DOMAIN, ConfigFlow):
        yield MockConfigEntry(domain=DOMAIN, title="Track Things test", data={}, version=1)
