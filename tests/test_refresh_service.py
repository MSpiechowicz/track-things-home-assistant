"""Refresh metadata and invalidate shared caches through the HA action registry."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.track_things.api_errors import ServerError

from .calendar_fixtures import setup_calendar

pytestmark = pytest.mark.usefixtures("freezer")


async def test_refresh_invalidates_and_refreshes_metadata(hass, config_entry, auth_http):
    await setup_calendar(hass, config_entry, auth_http)
    runtime = config_entry.runtime_data
    assert runtime.calendar._cache
    snapshot = runtime.coordinator.store.snapshot
    with patch.object(
        runtime.coordinator.store, "async_refresh", AsyncMock(return_value=snapshot)
    ) as refresh:
        # The calendar listener schedules a read after metadata changes.
        with patch.object(runtime.calendar, "_async_read", AsyncMock(return_value=[])):
            generation = runtime.calendar._generation
            result = await hass.services.async_call(
                "track_things",
                "refresh",
                {"config_entry_id": config_entry.entry_id},
                blocking=True,
                return_response=True,
            )
            await hass.async_block_till_done()
            assert result == {"refreshed": True}
            refresh.assert_awaited_once()
            assert runtime.calendar._generation > generation
            await hass.services.async_call(
                "track_things",
                "refresh",
                {"config_entry_id": config_entry.entry_id},
                blocking=True,
            )
            await hass.async_block_till_done()
            assert refresh.await_count == 2


async def test_refresh_failure_is_not_success_and_discards_cache(hass, config_entry, auth_http):
    await setup_calendar(hass, config_entry, auth_http)
    runtime = config_entry.runtime_data
    with patch.object(
        runtime.coordinator.store, "async_refresh", AsyncMock(side_effect=ServerError())
    ):
        with pytest.raises(HomeAssistantError, match="refresh failed"):
            await hass.services.async_call(
                "track_things",
                "refresh",
                {"config_entry_id": config_entry.entry_id},
                blocking=True,
                return_response=True,
            )
        await hass.async_block_till_done()
    assert not runtime.calendar._cache
    assert not runtime.coordinator.last_update_success
