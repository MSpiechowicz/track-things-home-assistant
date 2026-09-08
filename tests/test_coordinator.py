"""Coordinator availability, explicit refresh and real lifecycle polling."""

from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.track_things.api_errors import ServerError
from custom_components.track_things.coordinator import MetadataCoordinator

from .auth_fixtures import setup_responses
from .test_metadata import metadata_api


async def test_refresh_failure_retains_snapshot_and_recovers(hass, config_entry):
    coordinator = MetadataCoordinator(hass, config_entry, metadata_api())
    await coordinator.async_refresh()
    first = coordinator.data
    original = coordinator.store.async_refresh
    coordinator.store.async_refresh = AsyncMock(side_effect=ServerError())
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.data is first
    coordinator.store.async_refresh = original
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    await coordinator.async_shutdown()


async def test_polling_and_listener_cleanup(hass, config_entry, auth_http):
    setup_responses(auth_http)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    coordinator = config_entry.runtime_data.coordinator
    assert coordinator.update_interval == timedelta(minutes=5)
    refresh = AsyncMock(return_value=coordinator.data)
    coordinator.store.async_refresh = refresh
    now = dt_util.utcnow()
    async_fire_time_changed(hass, now + timedelta(minutes=6))
    await hass.async_block_till_done()
    refresh.assert_awaited_once()
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    async_fire_time_changed(hass, now + timedelta(minutes=12))
    await hass.async_block_till_done()
    refresh.assert_awaited_once()
    assert not list(coordinator.async_contexts())


async def test_auth_failure_requires_reauthentication(hass, config_entry):
    import pytest
    from homeassistant.exceptions import ConfigEntryAuthFailed

    from custom_components.track_things.api_errors import PermissionDeniedError

    coordinator = MetadataCoordinator(hass, config_entry, metadata_api())
    coordinator.store.async_refresh = AsyncMock(side_effect=PermissionDeniedError())
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    await coordinator.async_shutdown()
